import base64
import dataclasses
import email.message
import re
import typing
from datetime import datetime

from helpers.accounts import CREDENTIALS_FILE, GoogleAccounts
from helpers.notify import notify
from helpers.cache import Cache
from helpers.config import Config
from helpers.decorators import capture_response
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement


_METADATA_HEADERS = ["From", "To", "Cc", "Bcc", "Subject", "Date"]

# Tuning knobs, not settings: a user asking "read my email" has no way to judge
# any of these numbers, and the right answer doesn't vary by person.
# How many messages a search returns when the caller doesn't cap it.
_DEFAULT_MAX_RESULTS = 20
# Body text kept per message. Above this, a spoken read-out drags and a
# summarisation request costs tokens for boilerplate and signatures.
_MAX_BODY_CHARS = 1500
# Ceiling on messages fed to one AI inbox summary.
_AI_SUMMARY_MAX_EMAILS = 30
# How often "check my email every so often" polls when no interval is given.
_DEFAULT_POLL_INTERVAL_MINUTES = 15
# Unread messages a poll tick scans. Above the display default so a burst of new
# mail between two ticks is announced in full rather than partly missed.
_POLL_SCAN_LIMIT = 100


@dataclasses.dataclass
class Msg:
    id: str = ""
    thread_id: str = ""
    sender: str = ""
    recipient: str = ""
    cc: typing.List[str] = dataclasses.field(default_factory=list)
    bcc: typing.List[str] = dataclasses.field(default_factory=list)
    subject: str = ""
    date: str = ""
    snippet: str = ""
    plain: str = ""
    html: str = ""
    label_names: typing.List[str] = dataclasses.field(default_factory=list)
    attachments: typing.List[str] = dataclasses.field(default_factory=list)
    account: str = ""


def _walk_parts(payload: dict) -> typing.Tuple[str, str, typing.List[str]]:
    """Walk MIME payload tree, return (plain_text, html_text, attachment_filenames)."""
    plain_parts: typing.List[str] = []
    html_parts: typing.List[str] = []
    attachments: typing.List[str] = []

    def _walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        filename = part.get("filename", "")

        if filename:
            attachments.append(filename)
            return

        if "parts" in part:
            for sub in part["parts"]:
                _walk(sub)
            return

        data = body.get("data", "")
        if not data:
            return

        try:
            text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        except Exception:
            return

        if mime == "text/plain":
            plain_parts.append(text)
        elif mime == "text/html":
            html_parts.append(text)

    _walk(payload)
    return "".join(plain_parts), "".join(html_parts), attachments


def _parse_raw(raw: dict, label_map: typing.Dict[str, str]) -> Msg:
    """Parse a raw Gmail API message dict into a Msg."""
    from email.utils import parsedate_to_datetime

    msg = Msg(
        id=raw.get("id", ""),
        thread_id=raw.get("threadId", ""),
        snippet=raw.get("snippet", ""),
    )

    payload = raw.get("payload", {})
    for h in payload.get("headers", []):
        name = h.get("name", "").lower()
        value = h.get("value", "")
        if name == "from":
            msg.sender = value
        elif name == "to":
            msg.recipient = value
        elif name == "cc":
            msg.cc = [x.strip() for x in value.split(",") if x.strip()]
        elif name == "bcc":
            msg.bcc = [x.strip() for x in value.split(",") if x.strip()]
        elif name == "subject":
            msg.subject = value
        elif name == "date":
            try:
                dt = parsedate_to_datetime(value)
                msg.date = dt.isoformat()
            except Exception:
                msg.date = value

    msg.label_names = [label_map.get(lid, lid) for lid in raw.get("labelIds", [])]

    if payload:
        plain, html, atts = _walk_parts(payload)
        msg.plain = plain
        msg.html = html
        msg.attachments = atts

    return msg


def _build_mime_raw(
    sender: str,
    to: str,
    subject: str,
    body: str,
    thread_id: typing.Optional[str] = None,
) -> dict:
    """Return a raw base64url MIME message dict for the Gmail API send/draft endpoints."""
    mime = email.message.EmailMessage()
    mime["To"] = to
    mime["From"] = sender
    mime["Subject"] = subject
    mime.set_content(body)
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    result: typing.Dict[str, str] = {"raw": raw}
    if thread_id:
        result["threadId"] = thread_id
    return result


def _gmail_job_name(account_name: str) -> str:
    return f"gmail_polling_{account_name}"


@register_service(
    module_name="gmail",
    requires=Requirement(
        files=[CREDENTIALS_FILE],
        pip_modules=["simplegmail"],
        setup_hint=(
            "Follow simplegmail OAuth setup (pypi.org/project/simplegmail), "
            "place credentials/google_credentials.json in the credentials/ folder, "
            "then run: pip install -r requirements/gmail.txt"
        ),
    ),
)
class Gmail:
    """Gmail service for email management. Supports multiple Google accounts."""

    def __init__(self):
        self._clients: typing.Dict[str, typing.Any] = {}
        self._label_maps: typing.Dict[str, typing.Dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _client(self, account: str) -> typing.Any:
        # Imported here, not at module scope: a missing simplegmail must leave
        # the module importable so its Requirement still reaches `doctor`.
        import simplegmail

        name = GoogleAccounts.resolve(account or None)
        if name not in self._clients:
            rec = GoogleAccounts.record(name)
            self._clients[name] = simplegmail.Gmail(
                client_secret_file=CREDENTIALS_FILE,
                creds_file=rec["gmail_token"],
            )
        return self._clients[name]

    def _svc(self, account: str):
        """Auto-refreshing raw googleapiclient Gmail resource."""
        return self._client(account).service

    def forget_account(self, name: str) -> None:
        """Drop cached state for an account whose token changed or went away —
        both caches are keyed by name, so a re-auth would reuse the old client."""
        self._clients.pop(name, None)
        self._label_maps.pop(name, None)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _default_max(self) -> int:
        return _DEFAULT_MAX_RESULTS

    def _max_body_chars(self) -> int:
        return _MAX_BODY_CHARS

    def _use_ai(self) -> bool:
        return bool(Config.module_settings("gmail").get("use_ai", False))

    def _ai_summary_max_emails(self) -> int:
        return _AI_SUMMARY_MAX_EMAILS

    def _write_allowed(self) -> bool:
        return bool(Config.module_settings("gmail").get("allow_write", False))

    def _write_disabled_note(self, what: str) -> str:
        return (
            f"{what} is disabled. To allow it, set modules.gmail.allow_write: true "
            "in config.yaml (or switch it on in the web UI under Settings)."
        )

    # ------------------------------------------------------------------
    # Raw API helpers
    # ------------------------------------------------------------------

    def _label_map(self, account: str) -> typing.Dict[str, str]:
        """Cached {label_id: label_name} per account. Fetched once."""
        name = GoogleAccounts.resolve(account or None)
        if name not in self._label_maps:
            res = self._svc(account).users().labels().list(userId="me").execute()
            self._label_maps[name] = {
                lbl["id"]: lbl["name"] for lbl in res.get("labels", [])
            }
        return self._label_maps[name]

    def _scope(self, query: str, folder: str = "", no_inbox_prefix: bool = False) -> str:
        """Build a scoped Gmail query. Default scope is inbox; always strips spam/trash."""
        folder = (folder or "").strip().lower()
        folder_map = {
            "sent": "in:sent",
            "inbox": "in:inbox",
            "starred": "is:starred",
            "important": "is:important",
            "drafts": "in:drafts",
        }
        if no_inbox_prefix:
            prefix = ""
        elif folder:
            prefix = folder_map.get(folder, "in:inbox")
        else:
            prefix = "in:inbox"
        parts = [p for p in [prefix, query, "-in:spam -in:trash"] if p]
        return " ".join(parts)

    def _list_ids(self, svc, query: str, cap: int) -> typing.List[dict]:
        """Fetch up to cap message refs ({id, threadId}) without downloading bodies."""
        refs: typing.List[dict] = []
        kwargs: typing.Dict[str, typing.Any] = {
            "userId": "me",
            "q": query,
            "maxResults": min(cap, 500),
        }
        while len(refs) < cap:
            resp = svc.users().messages().list(**kwargs).execute()
            batch = resp.get("messages", [])
            refs.extend(batch)
            if not batch or len(refs) >= cap or "nextPageToken" not in resp:
                break
            kwargs["pageToken"] = resp["nextPageToken"]
            kwargs["maxResults"] = min(cap - len(refs), 500)
        return refs[:cap]

    def _batch_get(
        self,
        svc,
        refs: typing.List[dict],
        fmt: str,
        label_map: typing.Dict[str, str],
    ) -> typing.List[Msg]:
        """Fetch and parse messages in batches of 100 via HTTP batch requests."""
        if not refs:
            return []

        results: typing.List[typing.Optional[Msg]] = [None] * len(refs)

        def _make_cb(idx: int):
            def cb(request_id, response, exception):
                if exception is None and response:
                    results[idx] = _parse_raw(response, label_map)
            return cb

        for start in range(0, len(refs), 100):
            chunk = refs[start:start + 100]
            batch_req = svc.new_batch_http_request()
            for j, ref in enumerate(chunk):
                req_kwargs: typing.Dict[str, typing.Any] = {
                    "userId": "me",
                    "id": ref["id"],
                    "format": fmt,
                }
                if fmt == "metadata":
                    req_kwargs["metadataHeaders"] = _METADATA_HEADERS
                batch_req.add(
                    svc.users().messages().get(**req_kwargs),
                    callback=_make_cb(start + j),
                )
            batch_req.execute()

        return [m for m in results if m is not None]

    def _count(self, svc, query: str) -> int:
        """Approximate message count via resultSizeEstimate (1 API call, no bodies)."""
        resp = svc.users().messages().list(
            userId="me", q=query, maxResults=1
        ).execute()
        return resp.get("resultSizeEstimate", len(resp.get("messages", [])))

    def _label_counts(self, svc, label_id: str) -> dict:
        """Return label stats dict (messagesUnread, messagesTotal) — 1 API call."""
        return svc.users().labels().get(userId="me", id=label_id).execute()

    def _batch_modify(
        self,
        svc,
        ids: typing.List[str],
        add_labels: typing.List[str],
        remove_labels: typing.List[str],
    ) -> int:
        """Batch modify labels on messages. Returns count of successfully modified."""
        if not ids:
            return 0

        count = 0

        def _cb(request_id, response, exception):
            nonlocal count
            if exception is None:
                count += 1

        for start in range(0, len(ids), 100):
            chunk = ids[start:start + 100]
            batch_req = svc.new_batch_http_request()
            for mid in chunk:
                batch_req.add(
                    svc.users().messages().modify(
                        userId="me",
                        id=mid,
                        body={"addLabelIds": add_labels, "removeLabelIds": remove_labels},
                    ),
                    callback=_cb,
                )
            batch_req.execute()

        return count

    def _save_draft(
        self,
        account: str,
        to: str,
        subject: str,
        body: str,
        thread_id: typing.Optional[str] = None,
    ) -> str:
        """Save a draft via the Gmail API. Returns draft ID."""
        sender_email = GoogleAccounts.record(GoogleAccounts.resolve(account or None)).get("email", "")
        svc = self._svc(account)
        msg_dict = _build_mime_raw(sender_email, to, subject, body, thread_id)
        draft = svc.users().drafts().create(
            userId="me", body={"message": msg_dict}
        ).execute()
        return draft.get("id", "unknown")

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(m: Msg) -> datetime:
        try:
            dt = datetime.fromisoformat(m.date.strip()) if m.date else datetime.min
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
        except (ValueError, AttributeError):
            return datetime.min

    def _sort_desc(self, messages: typing.List[Msg]) -> typing.List[Msg]:
        return sorted(messages, key=Gmail._parse_date, reverse=True)

    def _format_message(
        self, message: Msg, verbose: bool = False, max_body: int = 0
    ) -> str:
        sender = self._format_sender(message.sender.strip()) if message.sender else "Unknown"
        date = self._format_time(message.date.strip()) if message.date else "Unknown date"
        subject = message.subject.strip() if message.subject else "(no subject)"

        parts = [
            f"From: {sender}",
            f"Date: {date}",
            f"Subject: {subject}",
        ]

        if verbose:
            if message.account and len(GoogleAccounts.list_accounts()) > 1:
                parts.append(f"Account: {message.account}")

            if message.recipient:
                parts.append(f"To: {message.recipient.strip()}")

            if message.cc:
                parts.append(f"CC: {', '.join(message.cc)}")

            if message.bcc:
                parts.append(f"BCC: {', '.join(message.bcc)}")

            labels = message.label_names or []
            readable_labels = [
                lbl for lbl in labels
                if lbl not in ("UNREAD", "CATEGORY_PERSONAL", "CATEGORY_PROMOTIONS",
                               "CATEGORY_UPDATES", "CATEGORY_SOCIAL", "INBOX")
            ]
            if readable_labels:
                parts.append(f"Labels: {', '.join(readable_labels)}")

            parts.append(f"Read: {'No' if 'UNREAD' in labels else 'Yes'}")

            if message.attachments:
                parts.append(f"Attachments: {', '.join(message.attachments)}")

            body = ""
            if message.plain:
                body = message.plain.strip()
            elif message.html:
                body = re.sub(r'<[^>]+>', ' ', message.html)
                body = re.sub(r'\s+', ' ', body).strip()
            elif message.snippet:
                body = message.snippet.strip()

            if body:
                limit = max_body if max_body > 0 else 3000
                if len(body) > limit:
                    body = body[:limit] + "..."
                parts.append(f"Body:\n    {body}")

        return "\n  ".join(parts)

    def _format_sender(self, sender: str) -> str:
        return sender.split("<")[0].strip()

    def _format_time(self, time: str) -> str:
        try:
            dt = datetime.fromisoformat(time)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return time

    def _strip_html(self, html_str: str) -> str:
        text = re.sub(r'<[^>]+>', ' ', html_str)
        return re.sub(r'\s+', ' ', text).strip()

    def _render_messages(
        self,
        messages: typing.List[Msg],
        header: str,
        count_template: str,
        verbose_override: typing.Optional[bool] = None,
    ) -> str:
        lines = [header]
        count_msg = count_template.format(count=len(messages))
        lines.append(count_msg)
        verbose = True if verbose_override is None else verbose_override
        for msg in messages:
            lines.append("")
            lines.append(self._format_message(msg, verbose=verbose))
        raw = "\n".join(lines)

        if not self._use_ai() or not messages:
            return raw

        from helpers.ai_assist import summarize

        cap = self._ai_summary_max_emails()
        body_limit = self._max_body_chars()
        payload_parts = [header, count_msg]
        for msg in messages[:cap]:
            payload_parts.append("")
            payload_parts.append(self._format_message(msg, verbose=True, max_body=body_limit))
        payload = "\n".join(payload_parts)

        instruction = (
            f"Summarize the following emails for the user. "
            f"Highlight key senders, main topics, and anything that looks like it needs a reply or action. "
            f"Context: {header}"
        )
        result = summarize(payload, instruction)
        if result is None:
            return raw
        return f"{header}\n{count_msg}\n\n{result}"

    # ------------------------------------------------------------------
    # Internal fetch helpers
    # ------------------------------------------------------------------

    def _accounts(self, account: str) -> typing.List[str]:
        """Accounts to operate on: the named one if given, else every configured
        account (so an unspecified account searches all). Raises via resolve()
        if none are configured."""
        if account:
            return [GoogleAccounts.resolve(account)]
        return GoogleAccounts.list_accounts() or [GoogleAccounts.resolve(None)]

    def _fetch(
        self,
        scoped_query: str,
        max_results: int,
        account: str,
        fmt: str = "full",
    ) -> typing.List[Msg]:
        """Run an already-scoped query across the target account(s), tag each
        message with its account, and return them sorted newest-first."""
        if max_results <= 0:
            max_results = self._default_max()
        out: typing.List[Msg] = []
        for name in self._accounts(account):
            svc = self._svc(name)
            label_map = self._label_map(name)
            refs = self._list_ids(svc, scoped_query, max_results)
            msgs = self._batch_get(svc, refs, fmt, label_map)
            for m in msgs:
                m.account = name
            out.extend(msgs)
        return self._sort_desc(out)

    def _get_new_messages(self, account: str) -> typing.List[Msg]:
        """Unread messages not yet announced by background polling. ID-based
        dedup mirrors the calendar poller — robust against Gmail's day-granular
        date filters re-announcing the same mail every interval."""
        name = GoogleAccounts.resolve(account or None)
        cache_key = f"announced_email_ids_{name}"
        messages = self._fetch(self._scope("is:unread"), _POLL_SCAN_LIMIT, name)
        announced: typing.List[str] = Cache.get_value(cache_key) or []
        new = [m for m in messages if m.id not in announced]
        if new:
            Cache.set_value(cache_key, (announced + [m.id for m in new])[-500:])
        return new

    def _search(self, query: str, max_results: int = 0, account: str = "") -> typing.List[Msg]:
        """Public search helper returning Msg list (for external callers)."""
        return self._fetch(self._scope(query), max_results, account)

    @staticmethod
    def _locator(query: str, sender: str, subject: str) -> str:
        """The query fragment every "find the one they mean" job builds."""
        parts = []
        if query:
            parts.append(query)
        if sender:
            parts.append(f"from:{sender}")
        if subject:
            parts.append(f"subject:{subject}")
        return " ".join(parts)

    def _find_latest(
        self, scoped_query: str, account: str
    ) -> typing.Optional[typing.Tuple[str, Msg]]:
        """Newest match across the target account(s), with the account holding it.

        Write jobs must act on that account: an unspecified account searches
        every one, so replying via the primary account would answer an email
        the primary account never received.
        """
        best: typing.Optional[typing.Tuple[str, Msg]] = None
        for name in self._accounts(account):
            svc = self._svc(name)
            refs = self._list_ids(svc, scoped_query, 10)
            msgs = self._sort_desc(self._batch_get(svc, refs, "full", self._label_map(name)))
            if not msgs:
                continue
            if best is None or Gmail._parse_date(msgs[0]) > Gmail._parse_date(best[1]):
                best = (name, msgs[0])
        return best

    def _find_ids(
        self, scoped_query: str, account: str, cap: int
    ) -> typing.List[typing.Tuple[str, typing.List[str]]]:
        """(account, message ids) per account, for a bulk operation."""
        found = []
        for name in self._accounts(account):
            refs = self._list_ids(self._svc(name), scoped_query, cap)
            if refs:
                found.append((name, [r["id"] for r in refs]))
        return found

    # ------------------------------------------------------------------
    # Jobs — read
    # ------------------------------------------------------------------

    @staticmethod
    def _as_int(value: typing.Any, fallback: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @capture_response
    @method_job
    def find_emails(
        self,
        query: str = "",
        sender: str = "",
        subject: str = "",
        label: str = "",
        folder: str = "",
        days_back: int = 0,
        unread_only: bool = False,
        starred: bool = False,
        important: bool = False,
        has_attachment: bool = False,
        max_results: int = 0,
        account: str = "",
    ) -> str:
        """
        [EMAIL MANAGEMENT JOB] Finds emails in Gmail. This is the single tool for every
        kind of email lookup — unread mail, recent mail, mail from a person, by label,
        starred, important, or with attachments. Combine filters freely; with no filters
        it lists recent inbox mail. Returns headers and previews, not full bodies —
        use read_email for the body of one message.

        Args:
            query (str): Raw Gmail search syntax, e.g. 'from:boss subject:report'. Use
                only for things the other filters can't express.
            sender (str): Only mail from this name or address.
            subject (str): Only mail whose subject matches these keywords.
            label (str): Only mail carrying this Gmail label.
            folder (str): Which folder to search: inbox (default), sent, drafts.
            days_back (int): Only mail newer than this many days.
            unread_only (bool): Only unread mail.
            starred (bool): Only starred mail.
            important (bool): Only mail Gmail marked important.
            has_attachment (bool): Only mail with file attachments.
            max_results (int): Cap on how many to return (defaults to 20).
            account (str): Google account to use (default: primary).

        Returns:
            str: Matching emails with sender, subject, date and a preview.
        """
        terms: typing.List[str] = []
        described: typing.List[str] = []

        if query:
            terms.append(query)
            described.append(f"matching '{query}'")
        if sender:
            terms.append(f"from:{sender}")
            described.append(f"from {sender}")
        if subject:
            terms.append(f"subject:{subject}")
            described.append(f"about '{subject}'")
        if label:
            terms.append(f'label:"{label}"' if " " in label else f"label:{label}")
            described.append(f"labelled '{label}'")
        if unread_only:
            terms.append("is:unread")
            described.append("unread")
        if starred:
            terms.append("is:starred")
            described.append("starred")
        if important:
            terms.append("is:important")
            described.append("important")
        if has_attachment:
            terms.append("has:attachment")
            described.append("with attachments")

        days = self._as_int(days_back)
        if days > 0:
            terms.append(f"newer_than:{days}d")
            described.append(f"from the past {days} day(s)")

        limit = self._as_int(max_results)
        if limit <= 0:
            limit = self._default_max()

        # label/starred/important are cross-folder in Gmail; forcing in:inbox on
        # them silently hides everything filed elsewhere.
        no_inbox = bool(label or starred or important) and not folder
        scoped = self._scope(" ".join(terms), folder=folder, no_inbox_prefix=no_inbox)

        messages = self._fetch(scoped, limit, account)
        folder_label = f" in {folder}" if folder else ""
        criteria = (" " + ", ".join(described)) if described else ""
        return self._render_messages(
            messages,
            header=f"Emails{criteria}{folder_label}:",
            count_template="Found {count} email(s).",
        )


    @capture_response
    @method_job
    def read_email(self, query: str = "", sender: str = "", subject: str = "", folder: str = "", account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Reads the full body of the most recent matching email.
        With no filters this is the latest email in the folder, so it also answers
        "read my last email" / "what was the last thing I sent". Use find_emails to
        list several; use this to actually read one.

        Args:
            query (str): Raw Gmail search syntax to locate the email.
            sender (str): Only mail from this name or address.
            subject (str): Only mail whose subject matches these keywords.
            folder (str): Which folder to look in: inbox (default), sent, drafts.
            account (str): Google account to use (default: primary).

        Returns:
            str: Full email body and headers.
        """
        scoped = self._scope(self._locator(query, sender, subject), folder=folder)

        messages = self._fetch(scoped, 10, account)
        if not messages:
            return "No matching email found."

        return self._format_message(messages[0], verbose=True)

    @capture_response
    @method_job
    def inbox_overview(self, detailed: bool = False, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Summarises the state of the inbox: how many unread
        emails there are, and — with detailed=true — who they are from and how much
        recent mail carries attachments. Answers "how many unread do I have" and
        "what's in my inbox" alike. Use find_emails to actually list the messages.

        Args:
            detailed (bool): Add top unread senders and the recent attachment count.
            account (str): Google account to use (default: every configured account).

        Returns:
            str: Unread counts, plus the extra breakdown when detailed is set.
        """
        names = self._accounts(account)
        unread_total = 0
        per_account: typing.List[str] = []
        attachments = 0
        senders: typing.Dict[str, int] = {}

        for name in names:
            svc = self._svc(name)
            count = self._label_counts(svc, "INBOX").get("messagesUnread", 0)
            unread_total += count
            per_account.append(f"{name}: {count}")
            if not detailed:
                continue
            attachments += self._count(svc, self._scope("has:attachment newer_than:7d"))
            refs = self._list_ids(svc, self._scope("is:unread"), 50)
            for msg in self._batch_get(svc, refs, "metadata", self._label_map(name)):
                who = self._format_sender(msg.sender or "Unknown")
                senders[who] = senders.get(who, 0) + 1

        headline = f"You have {unread_total} unread email(s)"
        if len(names) > 1:
            headline += " — " + ", ".join(per_account)
        headline += "."
        if not detailed:
            return headline

        lines = [headline, f"With attachments (last 7 days): {attachments}"]
        top = sorted(senders.items(), key=lambda item: item[1], reverse=True)[:5]
        if top:
            lines.append(
                "Top unread senders: "
                + ", ".join(f"{who} ({count})" for who, count in top)
            )
        return "\n".join(lines)

    @capture_response
    @method_job
    def list_labels(self, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Lists all Gmail labels and folders.

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: All label names.
        """
        all_names: typing.List[str] = []
        for name in self._accounts(account):
            all_names.extend(self._label_map(name).values())
        all_names = list(dict.fromkeys(all_names))

        user_labels = [
            n for n in all_names
            if not n.startswith("CATEGORY_") and n not in (
                "INBOX", "SENT", "TRASH", "SPAM", "STARRED", "IMPORTANT",
                "UNREAD", "DRAFT", "CHAT",
            )
        ]
        system_labels = [
            n for n in all_names
            if n in ("INBOX", "SENT", "TRASH", "SPAM", "STARRED", "IMPORTANT", "DRAFT")
        ]

        lines = [f"System labels: {', '.join(system_labels)}"]
        if user_labels:
            lines.append(f"Custom labels ({len(user_labels)}):")
            for name in sorted(user_labels):
                lines.append(f"  {name}")
        else:
            lines.append("No custom labels.")
        return "\n".join(lines)





    @capture_response
    @method_job
    def get_email_thread(self, query: str = "", subject: str = "", account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves a full email conversation thread, oldest
        message first.

        Args:
            query (str): Search query to find the thread (sender, subject, keywords).
            subject (str): Subject of the thread to find.
            account (str): Google account to use (default: primary).

        Returns:
            str: Full thread oldest to newest.
        """
        if not query and not subject:
            return "Please provide a query or subject to find the thread."

        search_q = self._scope(query if query else f"subject:{subject}")

        svc = None
        label_map: typing.Dict[str, str] = {}
        thread_id = ""
        for name in self._accounts(account):
            candidate = self._svc(name)
            refs = self._list_ids(candidate, search_q, 1)
            if refs and refs[0].get("threadId"):
                svc = candidate
                label_map = self._label_map(name)
                thread_id = refs[0]["threadId"]
                break

        if not thread_id or svc is None:
            return "No matching email found."

        thread_raw = svc.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute()

        thread_msgs = [
            _parse_raw(raw_msg, label_map)
            for raw_msg in thread_raw.get("messages", [])
        ]
        thread_msgs.sort(key=Gmail._parse_date)

        seed_subject = thread_msgs[0].subject if thread_msgs else (subject or "")
        lines = [f"Thread: '{seed_subject}' — {len(thread_msgs)} message(s)"]
        for i, message in enumerate(thread_msgs, 1):
            lines.append(f"\n--- Message {i} ---")
            lines.append(self._format_message(message, verbose=True))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Jobs — background polling
    # ------------------------------------------------------------------

    @capture_response
    @method_job
    def watch_inbox(self, action: str = "start", interval_minutes: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Starts or stops background inbox monitoring. While it
        runs, new mail is announced as it arrives.

        Args:
            action (str): "start" (the default) or "stop".
            interval_minutes (int): How often to check when starting (defaults to 15).
            account (str): Google account to watch. Stopping with no account stops all.

        Returns:
            str: Confirmation of what is now running.
        """
        wanted = (action or "start").strip().lower()

        if wanted in ("stop", "off", "cancel"):
            if account:
                name = GoogleAccounts.resolve(account)
                stopped = BackgroundJobs.stop(_gmail_job_name(name))
                return (f"Stopped watching '{name}'." if stopped
                        else f"'{name}' was not being watched.")
            watched = [j for j in BackgroundJobs.list_jobs() if j.startswith("gmail_polling_")]
            stopped_any = any(BackgroundJobs.stop(job) for job in watched)
            return "Stopped watching the inbox." if stopped_any else "The inbox was not being watched."

        if wanted not in ("start", "on", "watch"):
            return f"Unknown action '{action}'. Use start or stop."

        name = GoogleAccounts.resolve(account or None)
        job_name = _gmail_job_name(name)
        if BackgroundJobs.is_running(job_name):
            return f"Already watching '{name}'."

        if not interval_minutes or interval_minutes <= 0:
            interval_minutes = _DEFAULT_POLL_INTERVAL_MINUTES

        def _poll() -> None:
            messages = self._get_new_messages(name)
            if not messages:
                return
            headline = f"You have {len(messages)} new email(s) in {name}."
            logger.log_system_event("gmail_poll", headline)
            notify(
                [headline] + [self._format_message(m, verbose=False) for m in messages],
                kind="alert",
                source="gmail",
            )

        BackgroundJobs.start(job_name, _poll, interval=interval_minutes * 60)
        return f"Watching '{name}' — checking every {interval_minutes} minutes."

    # ------------------------------------------------------------------
    # Jobs — write
    # ------------------------------------------------------------------

    @capture_response
    @method_job
    def send_email(
        self,
        to: str,
        subject: str = "",
        body: str = "",
        account: str = "",
    ) -> str:
        """
        [EMAIL MANAGEMENT JOB] Composes and sends a new email. While sending is
        switched off it saves the message as a Gmail draft instead, so nothing is lost.

        Args:
            to (str): Recipient email address. (required)
            subject (str): Email subject line (provide subject or body or both).
            body (str): Plain text body of the email (provide subject or body or both).
            account (str): Google account to send from (default: primary).

        Returns:
            str: Confirmation that the email was sent or saved as draft.
        """
        if not to:
            return "Error: Recipient address (to) is required."
        if not subject and not body:
            return "Error: Email must have a subject or body."

        subj = subject or "(no subject)"

        if not self._write_allowed():
            try:
                self._save_draft(account, to, subj, body or "")
            except Exception as e:
                return f"Sending is switched off; saving a draft also failed: {e}"
            return (
                f"Saved as a draft instead — To: {to}, Subject: '{subj}'.\n"
                + self._write_disabled_note("Sending email")
            )

        try:
            name = GoogleAccounts.resolve(account or None)
            sender_email = GoogleAccounts.record(name).get("email", "")
            self._svc(name).users().messages().send(
                userId="me",
                body=_build_mime_raw(sender_email, to, subj, body or ""),
            ).execute()
        except Exception as e:
            return f"Failed to send email: {e}"
        return f"Email sent to {to} with subject '{subj}'."

    @capture_response
    @method_job
    def reply_to_email(
        self,
        query: str = "",
        sender: str = "",
        subject: str = "",
        reply_body: str = "",
        account: str = "",
    ) -> str:
        """
        [EMAIL MANAGEMENT JOB] Replies to an existing email thread. While sending is
        switched off it saves the reply as a Gmail draft instead.

        Args:
            query (str): Gmail search query to find the email to reply to.
            sender (str): Filter by sender address or name to find the email.
            subject (str): Subject or partial subject to find the email.
            reply_body (str): Text of the reply. (required) Provide at least one of query/sender/subject to identify which email.
            account (str): Google account to use (default: search every account).

        Returns:
            str: Confirmation that the reply was sent or saved as draft.
        """
        if not reply_body:
            return "Error: reply_body is required."

        try:
            found = self._find_latest(
                self._scope(self._locator(query, sender, subject)), account
            )
        except Exception as e:
            return f"Error searching for message: {e}"

        if found is None:
            return "No matching email found to reply to."

        name, msg = found
        reply_subject = msg.subject if msg.subject.startswith("Re:") else f"Re: {msg.subject}"

        if not self._write_allowed():
            try:
                self._save_draft(name, msg.sender, reply_subject, reply_body, thread_id=msg.thread_id)
            except Exception as e:
                return f"Sending is switched off; saving a draft also failed: {e}"
            return (
                f"Saved as a draft instead — To: {msg.sender}, Subject: '{reply_subject}'.\n"
                + self._write_disabled_note("Sending email")
            )

        try:
            sender_email = GoogleAccounts.record(name).get("email", "")
            self._svc(name).users().messages().send(
                userId="me",
                body=_build_mime_raw(sender_email, msg.sender, reply_subject, reply_body, msg.thread_id),
            ).execute()
        except Exception as e:
            return f"Failed to send reply: {e}"
        return f"Reply sent to {msg.sender} in thread '{reply_subject}'."

    @capture_response
    @method_job
    def mark_as_read(
        self,
        query: str = "",
        sender: str = "",
        subject: str = "",
        account: str = "",
    ) -> str:
        """
        [EMAIL MANAGEMENT JOB] Marks matching unread emails as read.

        Args:
            query (str): Gmail search query to find emails to mark as read.
            sender (str): Filter by sender address or name.
            subject (str): Subject or partial subject to filter.
            account (str): Google account to use (default: every configured account).

        Returns:
            str: Confirmation with count of messages marked as read.
        """
        locator = " ".join(
            part for part in ("is:unread", self._locator(query, sender, subject)) if part
        )
        try:
            per_account = self._find_ids(self._scope(locator), account, 500)
        except Exception as e:
            return f"Error searching for messages: {e}"

        if not per_account:
            return "No unread messages matched."

        marked = 0
        for name, ids in per_account:
            marked += self._batch_modify(
                self._svc(name), ids, add_labels=[], remove_labels=["UNREAD"]
            )
        return f"Marked {marked} message(s) as read."

    @capture_response
    @method_job
    def delete_email(
        self,
        query: str = "",
        sender: str = "",
        subject: str = "",
        account: str = "",
    ) -> str:
        """
        [EMAIL MANAGEMENT JOB] Moves matching emails to Trash, where Gmail keeps them
        for 30 days.

        Args:
            query (str): Gmail search query to find emails to delete.
            sender (str): Filter by sender address or name.
            subject (str): Subject or partial subject to filter.
            account (str): Google account to use (default: every configured account).

        Returns:
            str: Confirmation with count of messages moved to trash.
        """
        locator = self._locator(query, sender, subject)
        if not locator:
            return "Error: Provide at least one of query, sender, or subject."

        if not self._write_allowed():
            return self._write_disabled_note("Deleting email")

        try:
            per_account = self._find_ids(self._scope(locator), account, 100)
        except Exception as e:
            return f"Error searching for messages: {e}"

        if not per_account:
            return "No messages matched."

        trashed = 0
        for name, ids in per_account:
            svc = self._svc(name)
            for message_id in ids:
                try:
                    svc.users().messages().trash(userId="me", id=message_id).execute()
                    trashed += 1
                except Exception:
                    pass
        return f"Moved {trashed} message(s) to trash."

    @capture_response
    @method_job
    def manage_drafts(
        self,
        action: str = "list",
        draft_id: str = "",
        to: str = "",
        subject: str = "",
        body: str = "",
        account: str = "",
    ) -> str:
        """
        [EMAIL MANAGEMENT JOB] Works with Gmail drafts: list them, create one, edit one,
        or delete one. Editing keeps any field left empty as it was.

        Args:
            action (str): "list" (the default), "create", "edit" or "delete".
            draft_id (str): Which draft to edit or delete, as shown by the list action.
            to (str): Recipient address. (required when creating)
            subject (str): Subject line.
            body (str): Plain text body.
            account (str): Google account to use (default: primary).

        Returns:
            str: The draft list, or confirmation of the change.
        """
        wanted = (action or "list").strip().lower()
        svc = self._svc(account)

        if wanted == "list":
            try:
                result = svc.users().drafts().list(userId="me", maxResults=20).execute()
            except Exception as e:
                return f"Error listing drafts: {e}"
            drafts = result.get("drafts", [])
            if not drafts:
                return "No drafts found."
            lines = [f"Drafts ({len(drafts)}):"]
            for entry in drafts:
                entry_id = entry.get("id", "")
                try:
                    detail = svc.users().drafts().get(
                        userId="me", id=entry_id, format="metadata"
                    ).execute()
                    headers = {
                        h["name"].lower(): h["value"]
                        for h in detail.get("message", {}).get("payload", {}).get("headers", [])
                    }
                    subject_line = headers.get("subject", "(no subject)")
                    lines.append(
                        f"  [{entry_id}] To: {headers.get('to', '')}  Subject: {subject_line}"
                    )
                except Exception:
                    lines.append(f"  [{entry_id}]")
            return "\n".join(lines)

        if wanted == "create":
            if not to:
                return "Error: Recipient address (to) is required."
            if not subject and not body:
                return "Error: A draft needs a subject or a body."
            try:
                new_id = self._save_draft(account, to, subject or "(no subject)", body or "")
            except Exception as e:
                return f"Failed to create draft: {e}"
            return f"Draft created (id: {new_id}) — To: {to}, Subject: '{subject or '(no subject)'}'."

        if wanted == "edit":
            if not draft_id:
                return "Error: draft_id is required — use action 'list' to see them."
            try:
                # format="full" so an edit that keeps the body can carry it forward
                existing = svc.users().drafts().get(
                    userId="me", id=draft_id, format="full"
                ).execute()
                payload = existing.get("message", {}).get("payload", {})
                headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
                plain, html, _ = _walk_parts(payload)
                current_body = plain or self._strip_html(html)
            except Exception as e:
                return f"Failed to fetch draft: {e}"

            new_to = to.strip() or headers.get("to", "")
            new_subject = subject.strip() or headers.get("subject", "")
            new_body = body if body.strip() else current_body
            sender_email = GoogleAccounts.record(
                GoogleAccounts.resolve(account or None)
            ).get("email", "")

            try:
                svc.users().drafts().update(
                    userId="me",
                    id=draft_id,
                    body={
                        "message": _build_mime_raw(
                            sender_email, new_to, new_subject or "(no subject)", new_body
                        )
                    },
                ).execute()
            except Exception as e:
                return f"Failed to update draft: {e}"
            return f"Draft [{draft_id}] updated — To: {new_to}, Subject: '{new_subject}'."

        if wanted == "delete":
            if not draft_id:
                return "Error: draft_id is required — use action 'list' to see them."
            try:
                svc.users().drafts().delete(userId="me", id=draft_id).execute()
            except Exception as e:
                return f"Failed to delete draft: {e}"
            return f"Draft [{draft_id}] deleted."

        return f"Unknown action '{action}'. Use list, create, edit or delete."
