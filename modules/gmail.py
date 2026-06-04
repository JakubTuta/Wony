import typing
from datetime import datetime

import simplegmail
from simplegmail.message import Message

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.config import Config
from helpers.jobs import BackgroundJobs
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement

_GMAIL_JOB_NAME = "gmail_polling"


@register_service(
    module_name="gmail",
    requires=Requirement(
        files=["credentials/gmail_credentials.json"],
        pip_modules=["simplegmail"],
        setup_hint=(
            "Follow simplegmail OAuth setup (pypi.org/project/simplegmail), "
            "place credentials/gmail_credentials.json in the credentials/ folder, "
            "then run: pip install -r requirements/gmail.txt"
        ),
    ),
)
class Gmail:
    """Gmail service for email management."""

    def __init__(self):
        try:
            self._gmail_instance = simplegmail.Gmail(
                client_secret_file="credentials/gmail_credentials.json",
                creds_file="credentials/gmail_token.json",
            )
        except Exception as e:
            print(f"Failed to initialize Gmail: {e}")
            raise

    @method_job
    def check_new_emails(self) -> None:
        """
        [EMAIL MANAGEMENT JOB] Retrieves and announces new unread emails from Gmail.

        Use this job when the user wants to:
        - Check for new Gmail messages
        - Get email notifications and summaries
        - Review recent unread emails

        Keywords: email, emails, inbox, unread, messages, check emails, new emails, gmail,
                 mail check, email update, inbox check, new messages

        Args:
            None

        Returns:
            None: Announces count and details of new emails.
        """
        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech("Checking new emails...")
        print("Checking new emails...")

        messages = self._get_new_messages()

        if audio:
            Audio.text_to_speech(f"You have {len(messages)} new messages.")
        else:
            print(f"You have {len(messages)} new messages.")

        for message in messages:
            formatted_message = self._format_message(message)
            if audio:
                Audio.text_to_speech(formatted_message)
            else:
                print(formatted_message)

    @method_job
    def start_checking_emails(self, interval_minutes: int = 0) -> str:
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

        Returns:
            str: Confirmation that background polling started.
        """
        if BackgroundJobs.is_running(_GMAIL_JOB_NAME):
            return "Email polling is already running."

        if not interval_minutes or interval_minutes <= 0:
            interval_minutes = int(
                Config.module_settings("gmail").get("poll_interval_minutes", 15)
            )

        def _poll():
            messages = self._get_new_messages()
            if not messages:
                return
            audio = Cache.get_audio()
            msg = f"You have {len(messages)} new email{'s' if len(messages) != 1 else ''}."
            if audio:
                Audio.text_to_speech(msg)
            else:
                print(msg)
            for message in messages:
                formatted = self._format_message(message)
                if audio:
                    Audio.text_to_speech(formatted)
                else:
                    print(formatted)

        BackgroundJobs.start(
            _GMAIL_JOB_NAME,
            _poll,
            interval=interval_minutes * 60,
        )

        result = f"Checking emails every {interval_minutes} minutes. Say 'stop checking new emails' to stop."
        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech(result)
        else:
            print(result)
        return result

    @method_job
    def stop_checking_emails(self) -> str:
        """
        [EMAIL MANAGEMENT JOB] Stops the background email polling job.

        Use this job when the user wants to:
        - Stop automatic email notifications
        - Cancel background email monitoring
        - Turn off email alerts

        Keywords: stop checking emails, stop email notifications, cancel email monitoring,
                 stop email polling, disable email alerts, stop watching inbox

        Args:
            None

        Returns:
            str: Confirmation that email polling was stopped.
        """
        if BackgroundJobs.stop(_GMAIL_JOB_NAME):
            result = "Email polling stopped."
        else:
            result = "Email polling was not running."

        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech(result)
        else:
            print(result)
        return result

    def _get_new_messages(self) -> typing.List[Message]:
        newer_than_days = self._get_newer_than_days()
        query_params = {
            "newer_than": (newer_than_days, "day"),
            "unread": True,
        }
        return self._gmail_instance.get_messages(
            query=simplegmail.query.construct_query(query_params)
        )

    def _format_message(self, message: Message) -> str:
        return (
            f"Message from {self._format_sender(message.sender.strip())} "
            f"at {self._format_time(message.date.strip())}. "
            f"Subject: {message.subject.strip()}."
        )

    def _format_sender(self, sender: str) -> str:
        return sender.split("<")[0].strip()

    def _format_time(self, time: str) -> str:
        dt = datetime.fromisoformat(time)
        return dt.strftime("%Y-%m-%d %H:%M")

    def _get_newer_than_days(self) -> int:
        last_email_date: str | None = Cache.get_value("last_email_date")
        if last_email_date is None:
            last_email_date = datetime.now().isoformat()
        Cache.set_value("last_email_date", datetime.now().isoformat())
        newer_than_date = datetime.fromisoformat(last_email_date)
        days_diff = (datetime.now() - newer_than_date).days + 1
        return days_diff
