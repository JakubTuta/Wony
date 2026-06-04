import re
import typing
from datetime import datetime

import simplegmail
import simplegmail.query
from simplegmail.message import Message

from helpers.accounts import GoogleAccounts
from helpers.audio import Audio
from helpers.cache import Cache
from helpers.config import Config
from helpers.decorators import capture_response
from helpers.jobs import BackgroundJobs
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement


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

    # ------------------------------------------------------------------
    # Internal helpers
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

    def _default_max(self) -> int:
        return int(Config.module_settings("gmail").get("max_results", 20))

    def _max_body_chars(self) -> int:
        return int(Config.module_settings("gmail").get("max_body_chars", 1500))

    def _use_ai(self) -> bool:
        return bool(Config.module_settings("gmail").get("use_ai", False))

    def _ai_summary_max_emails(self) -> int:
        return int(Config.module_settings("gmail").get("ai_summary_max_emails", 30))

    def _folder_query(self, folder: str) -> str:
        """Return a raw Gmail search token for the given folder, or empty string."""
        folder = (folder or "").strip().lower()
        mapping = {
            "sent": "in:sent",
            "inbox": "in:inbox",
            "trash": "in:trash",
            "spam": "in:spam",
            "starred": "is:starred",
            "important": "is:important",
            "drafts": "in:drafts",
            "all": "",
        }
        return mapping.get(folder, "")

    def _sort_desc(self, messages: typing.List[Message]) -> typing.List[Message]:
        """Sort messages newest-first by date."""
        def _parse(m: Message) -> datetime:
            try:
                dt = datetime.fromisoformat(m.date.strip()) if m.date else datetime.min
                return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
            except (ValueError, AttributeError):
                return datetime.min
        return sorted(messages, key=_parse, reverse=True)

    def _fetch(
        self, query_params: dict, max_results: int, account: str
    ) -> typing.List[Message]:
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = 0
        if max_results <= 0:
            max_results = self._default_max()
        client = self._client(account)
        msgs = client.get_messages(
            query=simplegmail.query.construct_query(query_params)
        )
        return msgs[:max_results]

    def _get_new_messages(self, account: str) -> typing.List[Message]:
        name = GoogleAccounts.resolve(account or None)
        cache_key = f"last_email_date_{name}"
        newer_than_days = self._get_newer_than_days(cache_key)
        client = self._client(account)
        return client.get_messages(
            query=simplegmail.query.construct_query({
                "newer_than": (newer_than_days, "day"),
                "unread": True,
            })
        )

    def _get_newer_than_days(self, cache_key: str) -> int:
        last_email_date: typing.Optional[str] = Cache.get_value(cache_key)
        if last_email_date is None:
            last_email_date = datetime.now().isoformat()
        Cache.set_value(cache_key, datetime.now().isoformat())
        newer_than_date = datetime.fromisoformat(last_email_date)
        return (datetime.now() - newer_than_date).days + 1

    def _format_message(
        self, message: Message, verbose: bool = False, max_body: int = 0
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
            recipient = getattr(message, "recipient", "") or ""
            if recipient:
                parts.append(f"To: {recipient.strip()}")

            cc = getattr(message, "cc", None)
            if cc:
                cc_str = ", ".join(cc) if isinstance(cc, list) else str(cc)
                parts.append(f"CC: {cc_str.strip()}")

            bcc = getattr(message, "bcc", None)
            if bcc:
                bcc_str = ", ".join(bcc) if isinstance(bcc, list) else str(bcc)
                parts.append(f"BCC: {bcc_str.strip()}")

            labels = [str(l) for l in (getattr(message, "label_ids", []) or [])]
            readable_labels = [
                lbl for lbl in labels
                if lbl not in ("UNREAD", "CATEGORY_PERSONAL", "CATEGORY_PROMOTIONS",
                               "CATEGORY_UPDATES", "CATEGORY_SOCIAL", "INBOX")
            ]
            if readable_labels:
                parts.append(f"Labels: {', '.join(readable_labels)}")

            is_unread = "UNREAD" in labels
            parts.append(f"Read: {'No' if is_unread else 'Yes'}")

            attachments = getattr(message, "attachments", []) or []
            if attachments:
                att_names = [
                    getattr(a, "filename", None) or getattr(a, "name", "unnamed")
                    for a in attachments
                ]
                parts.append(f"Attachments: {', '.join(att_names)}")

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
        messages: typing.List[Message],
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
    # Jobs
    # ------------------------------------------------------------------

    @capture_response
    @method_job
    def check_new_emails(self, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves and announces new unread emails from Gmail.

        Use this job when the user wants to:
        - Check for new Gmail messages
        - Get email notifications and summaries
        - Review recent unread emails

        Keywords: email, emails, inbox, unread, messages, check emails, new emails, gmail,
                 mail check, email update, inbox check, new messages

        Args:
            account (str): Google account to use (default: primary).

        Returns:
            str: Count and details of new emails.
        """
        messages = self._get_new_messages(account)
        audio = Cache.get_audio()
        return self._render_messages(
            messages,
            header="Checking new emails...",
            audio=audio,
            count_template="You have {count} new message(s).",
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
                 sent emails last N days, past sent emails

        Args:
            days_back (int): How many days back to search (default 7).
            max_results (int): Maximum emails to return (default from config).
            folder (str): Folder to search: inbox, sent, all (default: all).
            account (str): Google account to use (default: primary).

        Returns:
            str: All emails with full details.
        """
        days_back = int(days_back) if days_back else 7
        audio = Cache.get_audio()
        base_q = simplegmail.query.construct_query({"newer_than": (days_back, "day")})
        folder_q = self._folder_query(folder)
        raw_query = f"{folder_q} {base_q}".strip() if folder_q else base_q
        try:
            max_r = int(max_results) if max_results else 0
        except (TypeError, ValueError):
            max_r = 0
        if max_r <= 0:
            max_r = self._default_max()
        client = self._client(account)
        messages = self._sort_desc(client.get_messages(query=raw_query)[:max_r])
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
        client = self._client(account)
        messages = self._sort_desc(client.get_messages(query=query)[:max_results])
        return self._render_messages(
            messages,
            header=f"Searching emails: {query}",
            audio=audio,
            count_template="Found {count} email(s).",
        )

    @capture_response
    @method_job
    def get_emails_from_sender(self, sender: str = "", max_results: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves all emails from a specific sender.

        Use this job when the user wants to:
        - See all emails from a specific person or address
        - Review correspondence with someone
        - Find messages from a contact

        Keywords: emails from, messages from, mail from, show emails from person,
                 correspondence with, messages from sender, all emails from

        Args:
            sender (str): Email address or name to filter by.
            max_results (int): Maximum emails to return (default from config).
            account (str): Google account to use (default: primary).

        Returns:
            str: All emails from that sender with full details.
        """
        if not sender:
            return "Please provide a sender name or address."
        audio = Cache.get_audio()
        messages = self._sort_desc(self._fetch({"sender": sender}, max_results, account))
        return self._render_messages(
            messages,
            header=f"Emails from: {sender}",
            audio=audio,
            count_template=f"Found {{count}} email(s) from {sender}.",
        )

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
            audio = Cache.get_audio()
            msg = f"You have {len(messages)} new email(s) in {name}."
            if audio:
                Audio.text_to_speech(msg)
            else:
                print(msg)
            for message in messages:
                formatted = self._format_message(message, verbose=False)
                if audio:
                    Audio.text_to_speech(formatted)
                else:
                    print(formatted)

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

    @capture_response
    @method_job
    def get_latest_email(self, folder: str = "inbox", sender: str = "", subject: str = "", account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves the single most recent email, optionally filtered
        by folder (inbox/sent/all), sender, or subject. Returns full details including body.

        Use this job when the user wants to:
        - Read the most recent or last email
        - Get the latest message from a specific person
        - See the last sent email
        - View the newest email in inbox or sent folder

        Keywords: last email, latest email, most recent email, newest email, last sent email,
                 latest sent email, my last message, most recent message, last inbox email,
                 last message from, newest message, what was my last email, get my last sent

        Args:
            folder (str): Folder to look in: inbox, sent, all (default: inbox).
            sender (str): Optional filter by sender name or address.
            subject (str): Optional filter by subject keywords.
            account (str): Google account to use (default: primary).

        Returns:
            str: Full details of the most recent matching email.
        """
        audio = Cache.get_audio()
        parts = []
        folder_q = self._folder_query(folder)
        if folder_q:
            parts.append(folder_q)
        if sender:
            parts.append(simplegmail.query.construct_query({"sender": sender}))
        if subject:
            parts.append(simplegmail.query.construct_query({"subject": subject}))
        raw_query = " ".join(parts) if parts else "in:inbox"

        client = self._client(account)
        messages = client.get_messages(query=raw_query)

        if not messages:
            return "No matching email found."

        messages = self._sort_desc(messages)
        message = messages[0]
        max_body = self._max_body_chars() if audio else 0
        folder_label = f" ({folder})" if folder else ""
        return f"Latest email{folder_label}:\n" + self._format_message(message, verbose=True, max_body=max_body)

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
            folder (str): Folder to search: inbox, sent, all (default: all).
            account (str): Google account to use (default: primary).

        Returns:
            str: Full email body and headers.
        """
        audio = Cache.get_audio()
        client = self._client(account)

        if query:
            messages = client.get_messages(query=query)
        else:
            parts = []
            folder_q = self._folder_query(folder)
            if folder_q:
                parts.append(folder_q)
            if sender:
                parts.append(simplegmail.query.construct_query({"sender": sender}))
            if subject:
                parts.append(simplegmail.query.construct_query({"subject": subject}))
            raw_query = " ".join(parts) if parts else "in:inbox"
            messages = client.get_messages(query=raw_query)

        if not messages:
            return "No matching email found."

        messages = self._sort_desc(messages)
        message = messages[0]
        max_body = self._max_body_chars() if audio else 0
        return self._format_message(message, verbose=True, max_body=max_body)

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
        client = self._client(account)
        messages = client.get_messages(
            query=simplegmail.query.construct_query({"unread": True})
        )
        return f"You have {len(messages)} unread email(s)."

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
        client = self._client(account)
        labels = client.list_labels()
        user_labels = [
            lbl.name for lbl in labels
            if not lbl.name.startswith("CATEGORY_") and lbl.name not in (
                "INBOX", "SENT", "TRASH", "SPAM", "STARRED", "IMPORTANT",
                "UNREAD", "DRAFT", "CHAT",
            )
        ]
        system_labels = [
            lbl.name for lbl in labels
            if lbl.name in ("INBOX", "SENT", "TRASH", "SPAM", "STARRED", "IMPORTANT", "DRAFT")
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
    def get_emails_by_label(self, label: str = "", max_results: int = 0, account: str = "") -> str:
        """
        [EMAIL MANAGEMENT JOB] Retrieves emails with a specific Gmail label applied.

        Use this job when the user wants to:
        - See emails under a particular label or folder
        - Browse a specific Gmail category
        - Find labeled or tagged messages

        Keywords: emails labeled, in folder, under label, category emails, label emails,
                 emails with label, show label, tagged emails, gmail label

        Args:
            label (str): The label name to filter by.
            max_results (int): Maximum emails to return (default from config).
            account (str): Google account to use (default: primary).

        Returns:
            str: Emails with that label.
        """
        if not label:
            return "Please specify a label name."
        audio = Cache.get_audio()
        messages = self._sort_desc(self._fetch({"labels": [[label]]}, max_results, account))
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
        audio = Cache.get_audio()
        messages = self._sort_desc(self._fetch(
            {"attachment": True, "newer_than": (days_back, "day")},
            max_results,
            account,
        ))
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
        audio = Cache.get_audio()
        messages = self._sort_desc(self._fetch({"starred": True}, max_results, account))
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
        audio = Cache.get_audio()
        messages = self._sort_desc(self._fetch({"important": True}, max_results, account))
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
        audio = Cache.get_audio()
        client = self._client(account)

        if query:
            seed_msgs = client.get_messages(query=query)
        elif subject:
            seed_msgs = client.get_messages(
                query=simplegmail.query.construct_query({"subject": subject})
            )
        else:
            return "Please provide a query or subject to find the thread."

        if not seed_msgs:
            return "No matching email found."

        seed = seed_msgs[0]
        thread_id = seed.thread_id
        seed_subject = seed.subject or ""

        if seed_subject:
            all_msgs = client.get_messages(
                query=simplegmail.query.construct_query({"subject": seed_subject})
            )
            thread_msgs = [m for m in all_msgs if m.thread_id == thread_id]
        else:
            thread_msgs = [seed]

        def _parse_date(m: Message) -> datetime:
            try:
                dt = datetime.fromisoformat(m.date.strip()) if m.date else datetime.min
                return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
            except (ValueError, AttributeError):
                return datetime.min

        thread_msgs.sort(key=_parse_date)

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
        client = self._client(account)

        unread_msgs = client.get_messages(
            query=simplegmail.query.construct_query({"unread": True})
        )
        attachment_msgs = client.get_messages(
            query=simplegmail.query.construct_query({
                "attachment": True,
                "newer_than": (7, "day"),
            })
        )

        sender_counts: typing.Dict[str, int] = {}
        for m in unread_msgs[:50]:
            s = self._format_sender(m.sender or "Unknown")
            sender_counts[s] = sender_counts.get(s, 0) + 1
        top_senders = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        lines = [
            "Inbox summary:",
            f"Unread emails: {len(unread_msgs)}",
            f"Emails with attachments (last 7 days): {len(attachment_msgs)}",
        ]
        if top_senders:
            top_str = ", ".join(f"{s} ({c})" for s, c in top_senders)
            lines.append(f"Top senders (unread): {top_str}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def _save_draft(
        self,
        client: "simplegmail.Gmail",
        sender: str,
        to: str,
        subject: str,
        body: str,
        thread_id: typing.Optional[str] = None,
    ) -> str:
        """Save a draft via the underlying Gmail API service."""
        import base64
        import email.message

        mime = email.message.EmailMessage()
        mime["To"] = to
        mime["From"] = sender
        mime["Subject"] = subject
        mime.set_content(body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

        draft_body: typing.Dict[str, typing.Any] = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        service = client.gmail_service
        draft = service.users().drafts().create(userId="me", body=draft_body).execute()
        return draft.get("id", "unknown")

    @capture_response
    @method_job
    def send_email(
        self,
        to: str = "",
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
            to (str): Recipient email address.
            subject (str): Email subject line.
            body (str): Plain text body of the email.
            account (str): Google account to send from (default: primary).

        Returns:
            str: Confirmation that the email was sent or saved as draft.
        """
        if not to:
            return "Error: Recipient address (to) is required."
        if not subject and not body:
            return "Error: Email must have a subject or body."

        client = self._client(account)
        sender_email = GoogleAccounts.record(GoogleAccounts.resolve(account or None)).get("email", "")
        cfg = Config.module_settings("gmail")

        if not cfg.get("allow_send", False):
            try:
                self._save_draft(client, sender_email, to, subject or "(no subject)", body)
            except Exception as e:
                return f"Sending disabled; also failed to save draft: {e}"
            return (
                f"Sending is disabled (allow_send: false). "
                f"Email saved as draft in Gmail — To: {to}, Subject: '{subject or '(no subject)'}'.\n"
                "To send directly, set modules.gmail.allow_send: true in config.yaml."
            )

        try:
            client.send_message(
                sender=sender_email,
                to=to,
                subject=subject or "(no subject)",
                msg_plain=body,
                msg_html=None,
            )
        except Exception as e:
            return f"Failed to send email: {e}"
        return f"Email sent to {to} with subject '{subject}'."

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
            reply_body (str): Text of the reply.
            account (str): Google account to use (default: primary).

        Returns:
            str: Confirmation that the reply was sent or saved as draft.
        """
        if not reply_body:
            return "Error: reply_body is required."

        client = self._client(account)
        q_parts = []
        if query:
            q_parts.append(query)
        if sender:
            q_parts.append(f"from:{sender}")
        if subject:
            q_parts.append(f"subject:{subject}")
        search_q = " ".join(q_parts) if q_parts else "in:inbox"

        try:
            messages = client.get_messages(query=search_q)
        except Exception as e:
            return f"Error searching for message: {e}"

        if not messages:
            return "No matching email found to reply to."

        msg = sorted(messages, key=lambda m: getattr(m, "date", ""), reverse=True)[0]
        sender_email = GoogleAccounts.record(GoogleAccounts.resolve(account or None)).get("email", "")
        reply_subject = str(msg.subject) if str(msg.subject).startswith("Re:") else f"Re: {msg.subject}"
        cfg = Config.module_settings("gmail")

        if not cfg.get("allow_send", False):
            try:
                self._save_draft(
                    client, sender_email, msg.sender, reply_subject, reply_body,
                    thread_id=msg.thread_id,
                )
            except Exception as e:
                return f"Sending disabled; also failed to save draft: {e}"
            return (
                f"Sending is disabled (allow_send: false). "
                f"Reply saved as draft — To: {msg.sender}, Subject: '{reply_subject}'.\n"
                "To send directly, set modules.gmail.allow_send: true in config.yaml."
            )

        try:
            client.send_message(
                sender=sender_email,
                to=msg.sender,
                subject=reply_subject,
                msg_plain=reply_body,
                msg_html=None,
                thread_id=msg.thread_id,
            )
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
        client = self._client(account)
        q_parts = ["is:unread"]
        if query:
            q_parts.append(query)
        if sender:
            q_parts.append(f"from:{sender}")
        if subject:
            q_parts.append(f"subject:{subject}")
        search_q = " ".join(q_parts)

        try:
            messages = client.get_messages(query=search_q)
        except Exception as e:
            return f"Error searching for messages: {e}"

        if not messages:
            return "No unread messages matched."

        count = 0
        for msg in messages:
            try:
                msg.mark_as_read()
                count += 1
            except Exception:
                pass
        return f"Marked {count} message(s) as read."
