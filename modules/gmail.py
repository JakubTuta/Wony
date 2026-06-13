import base64
import dataclasses
import email.message
import re
import typing
from datetime import datetime

import simplegmail

from helpers.accounts import GoogleAccounts
from helpers.audio import Audio
from helpers.cache import Cache
from helpers.config import Config
from helpers.decorators import capture_response
from helpers.jobs import BackgroundJobs
from helpers.logger import logger
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement


_METADATA_HEADERS = ["From", "To", "Cc", "Bcc", "Subject", "Date"]


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
        files=["credentials/google_credentials.json"],
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
        self._clients: typing.Dict[str, simplegmail.Gmail] = {}
        self._label_maps: typing.Dict[str, typing.Dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _client(self, account: str) -> simplegmail.Gmail:
        name = GoogleAccounts.resolve(account or None)
        if name not in self._clients:
            rec = GoogleAccounts.record(name)
            self._clients[name] = simplegmail.Gmail(
                client_secret_file="credentials/google_credentials.json",
                creds_file=rec["gmail_token"],
            )
        return self._clients[name]

    def _svc(self, account: str):
        """Auto-refreshing raw googleapiclient Gmail resource."""
        return self._client(account).service

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _default_max(self) -> int:
        return int(Config.module_settings("gmail").get("max_results", 20))

    def _max_body_chars(self) -> int:
        return int(Config.module_settings("gmail").get("max_body_chars", 1500))

    def _use_ai(self) -> bool:
        return bool(Config.module_settings("gmail").get("use_ai", False))

    def _ai_summary_max_emails(self) -> int:
        return int(Config.module_settings("gmail").get("ai_summary_max_emails", 30))

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
        audio: bool,
        count_template: str,
        verbose_override: typing.Optional[bool] = None,
    ) -> str:
        lines = [header]
        count_msg = count_template.format(count=len(messages))
        lines.append(count_msg)
        verbose = (not audio) if verbose_override is None else verbose_override
        max_body = self._max_body_chars() if audio else 0
        for msg in messages:
            lines.append("")
            lines.append(self._format_message(msg, verbose=verbose, max_body=max_body))
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
        result = summarize(payload, instruction, audio)
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
        messages = self._fetch(self._scope("is:unread"), self._default_max(), name)
        announced: typing.List[str] = Cache.get_value(cache_key) or []
        new = [m for m in messages if m.id not in announced]
        if new:
            Cache.set_value(cache_key, (announced + [m.id for m in new])[-200:])
        return new

    def _search(self, query: str, max_results: int = 0, account: str = "") -> typing.List[Msg]:
        """Public search helper returning Msg list (for external callers)."""
        return self._fetch(self._scope(query), max_results, account)

    # ------------------------------------------------------------------
    # Jobs — read
    # ------------------------------------------------------------------

    @capture_response
    @method_job
    def check_new_emails(self, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves and announces all unread emails from Gmail inbox.

        Use this job when the user wants to:
        - Check for new Gmail messages
        - Get email notifications and summaries
        - Review recent unread emails
        - See what unread emails they have
        - List unread messages

        Keywords: email, emails, inbox, unread, messages, check emails, new emails, gmail,
                 mail check, email update, inbox check, new messages, show unread, list unread

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: Count and details of unread emails.
        """
        messages = self._fetch(self._scope("is:unread"), self._default_max(), account)
        audio = Cache.get_audio()
        return self._render_messages(
            messages,
            header="Unread emails:",
            audio=audio,
            count_template="You have {count} unread message(s).",
        )

    @capture_response
    @method_job
    def get_past_emails(self, days_back: int = 7, max_results: int = 0, folder: str = "", account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves all emails from the past N days, optionally filtered by folder.

        Use this job when the user wants to:
        - Review past emails or conversations
        - See all messages received recently
        - Look back at email history
        - Get emails from sent folder or inbox from last N days

        Keywords: past emails, recent emails, previous messages, email history,
                 emails last week, show me emails from, read emails, all emails,
                 emails last N days, what emails did I get, show inbox history,
                 sent emails last N days, past sent emails,
                 list emails, list all emails, show all emails, show emails,
                 display emails, get all emails, fetch all emails

        Args:
            days_back (int): How many days back to search (default 30).
            max_results (int): Maximum emails to return (default from config).
            folder (str): Folder to search: inbox, sent (default: inbox).
            account (str): Google account to use (default: primary).

        Returns:
            str: All emails with full details.
        """
        days_back = int(days_back) if days_back else 30
        try:
            max_r = int(max_results) if max_results else 0
        except (TypeError, ValueError):
            max_r = 0
        if max_r <= 0:
            max_r = self._default_max()

        audio = Cache.get_audio()
        messages = self._fetch(
            self._scope(f"newer_than:{days_back}d", folder=folder), max_r, account
        )
        folder_label = f" ({folder})" if folder else ""
        return self._render_messages(
            messages,
            header=f"Emails from the past {days_back} day(s){folder_label}:",
            audio=audio,
            count_template=f"Found {{count}} email(s) in the past {days_back} days{folder_label}.",
        )

    @capture_response
    @method_job
    def search_emails(self, query: str = "", max_results: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Searches Gmail with a query string and returns matching emails.

        Use this job when the user wants to:
        - Search for specific emails by keyword, sender, or subject
        - Find emails matching certain criteria
        - Look up old or specific messages

        Keywords: search emails, find emails, look for email, email search, find message,
                 search inbox, email from, email about, emails with subject, find mail

        Args:
            query (str): Gmail search query (e.g. 'from:boss subject:report').
            max_results (int): Maximum emails to return (default from config).
            account (str): Google account to use (default: primary).

        Returns:
            str: Matching emails with full details.
        """
        audio = Cache.get_audio()
        if not max_results or max_results <= 0:
            max_results = self._default_max()
        messages = self._fetch(self._scope(query), max_results, account)
        return self._render_messages(
            messages,
            header=f"Searching emails: {query}",
            audio=audio,
            count_template="Found {count} email(s).",
        )

    @capture_response
    @method_job
    def get_emails_from_sender(self, sender: str, max_results: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves all emails from a specific sender.

        Use this job when the user wants to:
        - See all emails from a specific person or address
        - Review correspondence with someone
        - Find messages from a contact

        Keywords: emails from, messages from, mail from, show emails from person,
                 correspondence with, messages from sender, all emails from

        Args:
            sender (str): Email address or name to filter by. (required)
            max_results (int): Maximum emails to return (default from config).
            account (str): Google account to use (default: primary).

        Returns:
            str: All emails from that sender with full details.
        """
        if not sender:
            return "Please provide a sender name or address."
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 0
        if max_results <= 0:
            max_results = self._default_max()

        audio = Cache.get_audio()
        messages = self._fetch(self._scope(f"from:{sender}"), max_results, account)
        return self._render_messages(
            messages,
            header=f"Emails from: {sender}",
            audio=audio,
            count_template=f"Found {{count}} email(s) from {sender}.",
        )

    @capture_response
    @method_job
    def get_latest_email(self, folder: str = "inbox", sender: str = "", subject: str = "", account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves the single most recent email, optionally filtered
        by folder (inbox/sent), sender, or subject. Returns full details including body.

        Use this job when the user wants to:
        - Read the most recent or last email
        - Get the latest message from a specific person
        - See the last sent email
        - View the newest email in inbox or sent folder

        Keywords: last email, latest email, most recent email, newest email, last sent email,
                 latest sent email, my last message, most recent message, last inbox email,
                 last message from, newest message, what was my last email, get my last sent

        Args:
            folder (str): Folder to look in: inbox, sent (default: inbox).
            sender (str): Optional filter by sender name or address.
            subject (str): Optional filter by subject keywords.
            account (str): Google account to use (default: primary).

        Returns:
            str: Full details of the most recent matching email.
        """
        audio = Cache.get_audio()

        parts = []
        if sender:
            parts.append(f"from:{sender}")
        if subject:
            parts.append(f"subject:{subject}")
        query = self._scope(" ".join(parts), folder=folder)

        messages = self._fetch(query, 10, account)
        if not messages:
            return "No matching email found."

        max_body = self._max_body_chars() if audio else 0
        folder_label = f" ({folder})" if folder else ""
        return f"Latest email{folder_label}:\n" + self._format_message(messages[0], verbose=True, max_body=max_body)

    @capture_response
    @method_job
    def read_email(self, query: str = "", sender: str = "", subject: str = "", folder: str = "", account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Finds the most recent matching email and reads its full body.

        Use this job when the user wants to:
        - Read the content of a specific email
        - Open and view an email message
        - Hear or see what an email says

        Keywords: read email, open email, what does the email say, read the message,
                 read email from, show email content, read me the email, view email,
                 what did they write, read message from

        Args:
            query (str): Free-form Gmail search query to find the email.
            sender (str): Filter by sender name or address.
            subject (str): Filter by subject keywords.
            folder (str): Folder to search: inbox, sent (default: inbox).
            account (str): Google account to use (default: primary).

        Returns:
            str: Full email body and headers.
        """
        audio = Cache.get_audio()

        if query:
            scoped = self._scope(query, folder=folder)
        else:
            parts = []
            if sender:
                parts.append(f"from:{sender}")
            if subject:
                parts.append(f"subject:{subject}")
            scoped = self._scope(" ".join(parts), folder=folder)

        messages = self._fetch(scoped, 10, account)
        if not messages:
            return "No matching email found."

        max_body = self._max_body_chars() if audio else 0
        return self._format_message(messages[0], verbose=True, max_body=max_body)

    @capture_response
    @method_job
    def get_unread_count(self, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Returns the count of unread emails in the inbox.

        Use this job when the user wants to:
        - Know how many unread emails they have
        - Check if there is new mail
        - Get a quick inbox status

        Keywords: how many unread, unread count, unread emails, do I have new mail,
                 how many emails, new email count, unread messages, inbox count

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: Number of unread emails.
        """
        names = self._accounts(account)
        total = 0
        per: typing.List[str] = []
        for name in names:
            n = self._label_counts(self._svc(name), "INBOX").get("messagesUnread", 0)
            total += n
            per.append(f"{name}: {n}")
        if len(names) > 1:
            return f"You have {total} unread email(s) — " + ", ".join(per) + "."
        return f"You have {total} unread email(s)."

    @capture_response
    @method_job
    def list_labels(self, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Lists all Gmail labels and folders.

        Use this job when the user wants to:
        - See all Gmail labels or categories
        - Browse email folders
        - Check what labels exist in their mailbox

        Keywords: gmail labels, list labels, email folders, email categories,
                 my labels, show labels, inbox folders, gmail folders

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: All label names.
        """
        audio = Cache.get_audio()
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

        if audio:
            return (
                f"You have {len(user_labels)} custom label(s): "
                + (", ".join(user_labels) if user_labels else "none") + "."
            )
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
    def get_emails_by_label(self, label: str, max_results: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves emails with a specific Gmail label applied.

        Use this job when the user wants to:
        - See emails under a particular label or folder
        - Browse a specific Gmail category
        - Find labeled or tagged messages

        Keywords: emails labeled, in folder, under label, category emails, label emails,
                 emails with label, show label, tagged emails, gmail label

        Args:
            label (str): The label name to filter by. (required)
            max_results (int): Maximum emails to return (default from config).
            account (str): Google account to use (default: primary).

        Returns:
            str: Emails with that label.
        """
        if not label:
            return "Please specify a label name."
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 0
        if max_results <= 0:
            max_results = self._default_max()

        audio = Cache.get_audio()
        label_q = f'label:"{label}"' if " " in label else f"label:{label}"
        query = self._scope(label_q, no_inbox_prefix=True)
        messages = self._fetch(query, max_results, account)
        return self._render_messages(
            messages,
            header=f"Emails with label '{label}':",
            audio=audio,
            count_template=f"Found {{count}} email(s) with label '{label}'.",
        )

    @capture_response
    @method_job
    def get_emails_with_attachments(self, days_back: int = 30, max_results: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves recent emails that have file attachments.

        Use this job when the user wants to:
        - Find emails with attached files
        - See what documents or files were sent to them
        - Review emails containing attachments

        Keywords: emails with attachments, files sent to me, documents in email,
                 email attachments, emails with files, find attachment, messages with files,
                 email with pdf, email with document

        Args:
            days_back (int): How many days back to search (default 30).
            max_results (int): Maximum emails to return (default from config).
            account (str): Google account to use (default: primary).

        Returns:
            str: Emails with attachment filenames listed.
        """
        days_back = int(days_back) if days_back else 30
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 0
        if max_results <= 0:
            max_results = self._default_max()

        audio = Cache.get_audio()
        messages = self._fetch(
            self._scope(f"has:attachment newer_than:{days_back}d"), max_results, account
        )
        return self._render_messages(
            messages,
            header=f"Emails with attachments (past {days_back} days):",
            audio=audio,
            count_template="Found {count} email(s) with attachments.",
        )

    @capture_response
    @method_job
    def get_starred_emails(self, max_results: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves starred (bookmarked) emails.

        Use this job when the user wants to:
        - See their starred or bookmarked emails
        - Review important flagged messages
        - Browse starred inbox items

        Keywords: starred emails, starred messages, flagged emails, bookmarked emails,
                 show starred, my starred, starred mail

        Args:
            max_results (int): Maximum emails to return (default from config).
            account (str): Google account to use (default: primary).

        Returns:
            str: Starred emails with full details.
        """
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 0
        if max_results <= 0:
            max_results = self._default_max()

        audio = Cache.get_audio()
        messages = self._fetch(
            self._scope("is:starred", no_inbox_prefix=True), max_results, account
        )
        return self._render_messages(
            messages,
            header="Starred emails:",
            audio=audio,
            count_template="Found {count} starred email(s).",
        )

    @capture_response
    @method_job
    def get_important_emails(self, max_results: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves emails marked as important by Gmail.

        Use this job when the user wants to:
        - See high-priority or important emails
        - Review the priority inbox
        - Browse important flagged messages

        Keywords: important emails, priority inbox, important messages, high priority email,
                 show important, marked important, priority emails

        Args:
            max_results (int): Maximum emails to return (default from config).
            account (str): Google account to use (default: primary).

        Returns:
            str: Important emails with full details.
        """
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 0
        if max_results <= 0:
            max_results = self._default_max()

        audio = Cache.get_audio()
        messages = self._fetch(
            self._scope("is:important", no_inbox_prefix=True), max_results, account
        )
        return self._render_messages(
            messages,
            header="Important emails:",
            audio=audio,
            count_template="Found {count} important email(s).",
        )

    @capture_response
    @method_job
    def get_email_thread(self, query: str = "", subject: str = "", account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves and displays a full email conversation thread.

        Use this job when the user wants to:
        - Read an entire email conversation
        - See all replies in an email thread
        - Review the full exchange of messages

        Keywords: email thread, email conversation, full exchange, email replies,
                 read thread, show conversation, email chain, all replies, thread

        Args:
            query (str): Search query to find the thread (sender, subject, keywords).
            subject (str): Subject of the thread to find.
            account (str): Google account to use (default: primary).

        Returns:
            str: Full thread oldest to newest.
        """
        if not query and not subject:
            return "Please provide a query or subject to find the thread."

        audio = Cache.get_audio()
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
        max_body = self._max_body_chars() if audio else 0
        lines = [f"Thread: '{seed_subject}' — {len(thread_msgs)} message(s)"]
        for i, message in enumerate(thread_msgs, 1):
            lines.append(f"\n--- Message {i} ---")
            lines.append(self._format_message(message, verbose=True, max_body=max_body))
        return "\n".join(lines)

    @capture_response
    @method_job
    def summarize_inbox(self, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Provides a summary overview of the inbox status.

        Use this job when the user wants to:
        - Get a quick overview of their inbox
        - See inbox statistics at a glance
        - Know who is sending the most emails

        Keywords: inbox summary, inbox overview, email summary, what is in my inbox,
                 inbox status, email stats, how is my inbox, inbox report

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: Inbox summary including unread count, attachments, top senders.
        """
        unread_count = 0
        att_count = 0
        sender_counts: typing.Dict[str, int] = {}
        for name in self._accounts(account):
            svc = self._svc(name)
            label_map = self._label_map(name)
            unread_count += self._label_counts(svc, "INBOX").get("messagesUnread", 0)
            att_count += self._count(svc, self._scope("has:attachment newer_than:7d"))
            unread_refs = self._list_ids(svc, self._scope("is:unread"), 50)
            for m in self._batch_get(svc, unread_refs, "metadata", label_map):
                s = self._format_sender(m.sender or "Unknown")
                sender_counts[s] = sender_counts.get(s, 0) + 1
        top_senders = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        lines = [
            "Inbox summary:",
            f"Unread emails: {unread_count}",
            f"Emails with attachments (last 7 days): {att_count}",
        ]
        if top_senders:
            lines.append(f"Top senders (unread): {', '.join(f'{s} ({c})' for s, c in top_senders)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Jobs — background polling
    # ------------------------------------------------------------------

    @capture_response
    @method_job
    def start_checking_emails(self, interval_minutes: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Starts a background job that checks for new emails periodically.
        Announces new messages when they arrive. Stop with 'stop checking new emails'.

        Use this job when the user wants to:
        - Get automatic email notifications
        - Monitor inbox in the background
        - Start periodic email polling

        Keywords: start checking emails, monitor emails, watch inbox, email notifications,
                 background email, auto check email, email alerts, notify new email

        Args:
            interval_minutes (int): How often to check in minutes (default from config).
            account (str): Google account to monitor (default: primary).

        Returns:
            str: Confirmation that background polling started.
        """
        name = GoogleAccounts.resolve(account or None)
        job_name = _gmail_job_name(name)

        if BackgroundJobs.is_running(job_name):
            return f"Email polling for '{name}' is already running."

        if not interval_minutes or interval_minutes <= 0:
            interval_minutes = int(
                Config.module_settings("gmail").get("poll_interval_minutes", 15)
            )

        def _poll():
            messages = self._get_new_messages(name)
            if not messages:
                return
            msg = f"You have {len(messages)} new email(s) in {name}."
            Audio.notify(msg)
            logger.log_system_event("gmail_poll", msg)
            for message in messages:
                Audio.notify(self._format_message(message, verbose=False))

        BackgroundJobs.start(job_name, _poll, interval=interval_minutes * 60)
        return f"Checking '{name}' emails every {interval_minutes} minutes."

    @capture_response
    @method_job
    def stop_checking_emails(self, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Stops the background email polling job.

        Use this job when the user wants to:
        - Stop automatic email notifications
        - Cancel background email monitoring
        - Turn off email alerts

        Keywords: stop checking emails, stop email notifications, cancel email monitoring,
                 stop email polling, disable email alerts, stop watching inbox

        Args:
            account (str): Account to stop (default: stop all gmail polling).

        Returns:
            str: Confirmation that email polling was stopped.
        """
        if account:
            name = GoogleAccounts.resolve(account)
            stopped = BackgroundJobs.stop(_gmail_job_name(name))
            return (f"Email polling for '{name}' stopped."
                    if stopped else f"Email polling for '{name}' was not running.")
        all_jobs = BackgroundJobs.list_jobs()
        gmail_jobs = [j for j in all_jobs if j.startswith("gmail_polling_")]
        stopped_any = any(BackgroundJobs.stop(j) for j in gmail_jobs)
        return "Email polling stopped." if stopped_any else "Email polling was not running."

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
        [EMAIL MANAGEMENT JOB] Composes and sends a new email from a Gmail account.
        When allow_send is disabled, saves the email as a draft in Gmail instead.

        Use this job when the user wants to:
        - Send an email to someone
        - Compose and send a message
        - Email someone

        Keywords: send email, send message, compose email, email to, write email, draft and send

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

        cfg = Config.module_settings("gmail")
        subj = subject or "(no subject)"

        if not cfg.get("allow_send", False):
            try:
                self._save_draft(account, to, subj, body or "")
            except Exception as e:
                return f"Sending disabled; also failed to save draft: {e}"
            return (
                f"Sending is disabled (allow_send: false). "
                f"Email saved as draft in Gmail — To: {to}, Subject: '{subj}'.\n"
                "To send directly, set modules.gmail.allow_send: true in config.yaml."
            )

        try:
            sender_email = GoogleAccounts.record(GoogleAccounts.resolve(account or None)).get("email", "")
            svc = self._svc(account)
            svc.users().messages().send(
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
        [EMAIL MANAGEMENT JOB] Replies to an existing email thread.
        When allow_send is disabled, saves the reply as a draft in Gmail instead.

        Use this job when the user wants to:
        - Reply to an email
        - Respond to a message
        - Send a reply

        Keywords: reply, reply to email, respond to email, answer email, reply to message

        Args:
            query (str): Gmail search query to find the email to reply to.
            sender (str): Filter by sender address or name to find the email.
            subject (str): Subject or partial subject to find the email.
            reply_body (str): Text of the reply. (required) Provide at least one of query/sender/subject to identify which email.
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation that the reply was sent or saved as draft.
        """
        if not reply_body:
            return "Error: reply_body is required."

        svc = self._svc(account)
        label_map = self._label_map(account)

        q_parts = []
        if query:
            q_parts.append(query)
        if sender:
            q_parts.append(f"from:{sender}")
        if subject:
            q_parts.append(f"subject:{subject}")
        search_q = self._scope(" ".join(q_parts))

        try:
            refs = self._list_ids(svc, search_q, 10)
        except Exception as e:
            return f"Error searching for message: {e}"

        if not refs:
            return "No matching email found to reply to."

        msgs = self._sort_desc(self._batch_get(svc, refs, "full", label_map))
        if not msgs:
            return "No matching email found to reply to."

        msg = msgs[0]
        reply_subject = msg.subject if msg.subject.startswith("Re:") else f"Re: {msg.subject}"
        cfg = Config.module_settings("gmail")

        if not cfg.get("allow_send", False):
            try:
                self._save_draft(account, msg.sender, reply_subject, reply_body, thread_id=msg.thread_id)
            except Exception as e:
                return f"Sending disabled; also failed to save draft: {e}"
            return (
                f"Sending is disabled (allow_send: false). "
                f"Reply saved as draft — To: {msg.sender}, Subject: '{reply_subject}'.\n"
                "To send directly, set modules.gmail.allow_send: true in config.yaml."
            )

        try:
            sender_email = GoogleAccounts.record(GoogleAccounts.resolve(account or None)).get("email", "")
            svc.users().messages().send(
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
        [EMAIL MANAGEMENT JOB] Marks one or more emails as read.

        Use this job when the user wants to:
        - Mark emails as read
        - Clear the unread indicator on messages
        - Mark a specific email as read

        Keywords: mark as read, mark read, clear unread, read email, mark message read

        Args:
            query (str): Gmail search query to find emails to mark as read.
            sender (str): Filter by sender address or name.
            subject (str): Subject or partial subject to filter.
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation with count of messages marked as read.
        """
        svc = self._svc(account)

        q_parts = ["is:unread"]
        if query:
            q_parts.append(query)
        if sender:
            q_parts.append(f"from:{sender}")
        if subject:
            q_parts.append(f"subject:{subject}")

        try:
            refs = self._list_ids(svc, self._scope(" ".join(q_parts)), 500)
        except Exception as e:
            return f"Error searching for messages: {e}"

        if not refs:
            return "No unread messages matched."

        count = self._batch_modify(svc, [r["id"] for r in refs], add_labels=[], remove_labels=["UNREAD"])
        return f"Marked {count} message(s) as read."

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
        [EMAIL MANAGEMENT JOB] Moves matching emails to Trash.

        Use this job when the user wants to:
        - Delete an email
        - Move a message to trash
        - Remove emails matching a search

        Keywords: delete email, trash email, remove email, move to trash, delete message,
                 discard email, throw away email

        Args:
            query (str): Gmail search query to find emails to delete.
            sender (str): Filter by sender address or name.
            subject (str): Subject or partial subject to filter.
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation with count of messages moved to trash.
        """
        if not query and not sender and not subject:
            return "Error: Provide at least one of query, sender, or subject."

        cfg = Config.module_settings("gmail")
        if not cfg.get("allow_send", False):
            return (
                "Email deletion is disabled (allow_send: false). "
                "Set modules.gmail.allow_send: true in config.yaml to enable write operations."
            )

        svc = self._svc(account)
        q_parts = []
        if query:
            q_parts.append(query)
        if sender:
            q_parts.append(f"from:{sender}")
        if subject:
            q_parts.append(f"subject:{subject}")

        try:
            refs = self._list_ids(svc, self._scope(" ".join(q_parts)), 100)
        except Exception as e:
            return f"Error searching for messages: {e}"

        if not refs:
            return "No messages matched."

        count = 0
        for ref in refs:
            try:
                svc.users().messages().trash(userId="me", id=ref["id"]).execute()
                count += 1
            except Exception:
                pass
        return f"Moved {count} message(s) to trash."

    # ------------------------------------------------------------------
    # Jobs — draft CRUD
    # ------------------------------------------------------------------

    @capture_response
    @method_job
    def list_drafts(self, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Lists all Gmail drafts.

        Use this job when the user wants to:
        - See saved email drafts
        - Review unsent emails
        - Check what drafts exist

        Keywords: list drafts, show drafts, my drafts, email drafts, saved drafts, unsent emails

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: All drafts with id, subject, and recipient.
        """
        svc = self._svc(account)
        try:
            result = svc.users().drafts().list(userId="me", maxResults=20).execute()
        except Exception as e:
            return f"Error listing drafts: {e}"

        drafts = result.get("drafts", [])
        if not drafts:
            return "No drafts found."

        lines = [f"Drafts ({len(drafts)}):"]
        for d in drafts:
            draft_id = d.get("id", "")
            try:
                detail = svc.users().drafts().get(userId="me", id=draft_id, format="metadata").execute()
                msg = detail.get("message", {})
                headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
                subj = headers.get("subject", "(no subject)")
                to = headers.get("to", "")
                lines.append(f"  [{draft_id}] To: {to}  Subject: {subj}")
            except Exception:
                lines.append(f"  [{draft_id}]")
        return "\n".join(lines)

    @capture_response
    @method_job
    def create_draft(
        self,
        to: str,
        subject: str = "",
        body: str = "",
        account: str = "",
    ) -> str:
        """
        [EMAIL MANAGEMENT JOB] Creates a new Gmail draft.

        Use this job when the user wants to:
        - Save an email as a draft without sending
        - Create a draft to review later
        - Start composing an email

        Keywords: create draft, save draft, new draft, compose draft, write draft, draft email

        Args:
            to (str): Recipient email address. (required)
            subject (str): Email subject line.
            body (str): Plain text body of the email.
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation with the draft id.
        """
        if not to:
            return "Error: Recipient address (to) is required."
        if not subject and not body:
            return "Error: Draft must have a subject or body."
        try:
            draft_id = self._save_draft(account, to, subject or "(no subject)", body or "")
        except Exception as e:
            return f"Failed to create draft: {e}"
        return f"Draft created (id: {draft_id}) — To: {to}, Subject: '{subject or '(no subject)'}'."

    @capture_response
    @method_job
    def edit_draft(
        self,
        draft_id: str,
        to: str = "",
        subject: str = "",
        body: str = "",
        account: str = "",
    ) -> str:
        """
        [EMAIL MANAGEMENT JOB] Updates an existing Gmail draft.

        Use this job when the user wants to:
        - Edit a saved draft
        - Change the recipient, subject, or body of a draft
        - Update an unsent email

        Keywords: edit draft, update draft, change draft, modify draft, revise draft

        Args:
            draft_id (str): The id of the draft to edit (from list_drafts). (required)
            to (str): New recipient (leave empty to keep current).
            subject (str): New subject (leave empty to keep current).
            body (str): New body (leave empty to keep current).
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation of the update.
        """
        if not draft_id:
            return "Error: draft_id is required."

        svc = self._svc(account)
        try:
            existing = svc.users().drafts().get(userId="me", id=draft_id, format="metadata").execute()
            msg = existing.get("message", {})
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            current_to = headers.get("to", "")
            current_subject = headers.get("subject", "")
        except Exception as e:
            return f"Failed to fetch draft: {e}"

        new_to = to.strip() or current_to
        new_subject = subject.strip() or current_subject
        new_body = body  # empty string is fine as updated body

        sender_email = GoogleAccounts.record(GoogleAccounts.resolve(account or None)).get("email", "")
        msg_dict = _build_mime_raw(sender_email, new_to, new_subject or "(no subject)", new_body)

        try:
            svc.users().drafts().update(
                userId="me", id=draft_id, body={"message": msg_dict}
            ).execute()
        except Exception as e:
            return f"Failed to update draft: {e}"
        return f"Draft [{draft_id}] updated — To: {new_to}, Subject: '{new_subject}'."

    @capture_response
    @method_job
    def delete_draft(self, draft_id: str, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Deletes a Gmail draft permanently.

        Use this job when the user wants to:
        - Delete a draft
        - Remove an unsent email
        - Discard a saved draft

        Keywords: delete draft, remove draft, discard draft, trash draft, cancel draft

        Args:
            draft_id (str): The id of the draft to delete (from list_drafts). (required)
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation of deletion.
        """
        if not draft_id:
            return "Error: draft_id is required."
        svc = self._svc(account)
        try:
            svc.users().drafts().delete(userId="me", id=draft_id).execute()
        except Exception as e:
            return f"Failed to delete draft: {e}"
        return f"Draft [{draft_id}] deleted."
