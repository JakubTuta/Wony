import os
import threading
import typing

from helpers.accounts import CREDENTIALS_FILE, GoogleAccounts
from helpers.config import Config
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import ServiceRegistry, method_job, register_service

# Services holding their own OAuth token per account. All are authorized
# together — an account signed in for mail but not calendar is half configured.
_GOOGLE_SERVICES = ("gmail", "calendar")

# Consent happens in a browser at human speed. Long enough for a password and a
# phone code, short enough that an abandoned sign-in doesn't wedge the turn.
_AUTH_TIMEOUT_SECONDS = 180


@register_service(module_name="google_accounts")
class GoogleAccountsService:
    """Google account management — add, remove, list, authorize, set primary."""

    def __init__(self):
        pass

    def _email_from_gmail(self, gmail_svc, account: str) -> str:
        try:
            profile = gmail_svc._svc(account).users().getProfile(userId="me").execute()
            return (profile or {}).get("emailAddress", "")
        except Exception as e:
            logger.log_error(str(e), f"google_account_email.gmail_profile.{account}")
            return ""

    def _email_from_calendar(self, cal_svc, account: str) -> str:
        try:
            primary = (
                cal_svc._service_for(account)
                .calendarList()
                .get(calendarId="primary")
                .execute()
            )
            cal_id = (primary or {}).get("id", "")
            return cal_id if "@" in cal_id else ""
        except Exception as e:
            logger.log_error(str(e), f"google_account_email.calendar_primary.{account}")
            return ""

    def _sign_in(self, module: str, service: typing.Any, name: str) -> str:
        """Build the client — which is what triggers consent, since both
        libraries run the flow on first use — and report the email it belongs to."""
        if module == "gmail":
            service._client(name)
            return self._email_from_gmail(service, name)

        service._service_for(name)
        return self._email_from_calendar(service, name)

    def _forget_cached(self, name: str) -> None:
        """Tell each Google service to drop what it cached for this account —
        its token is about to change or has just been deleted."""
        for module in _GOOGLE_SERVICES:
            service = ServiceRegistry.get_service_instance(module)
            if service is not None:
                service.forget_account(name)

    def _authorize(self, name: str) -> typing.Tuple[typing.List[str], typing.List[str]]:
        """Run OAuth consent for every enabled Google service.

        Returns (authorized, problems). The flow runs on a worker thread
        because it blocks on a person, and the caller is an agent turn.
        """
        services = {
            module: service
            for module in _GOOGLE_SERVICES
            if (service := ServiceRegistry.get_service_instance(module)) is not None
        }
        if not services:
            return [], [
                "Neither gmail nor calendar is enabled, so there is nothing to sign in to."
            ]
        if not os.path.exists(CREDENTIALS_FILE):
            return [], [
                "credentials/google_credentials.json is missing — download the OAuth "
                "client from Google Cloud Console and put it there first."
            ]

        authorized: typing.List[str] = []
        problems: typing.List[str] = []

        def work() -> None:
            for module, service in services.items():
                try:
                    logger.log_system_event(
                        "google_account_auth", f"Authorizing {module} for '{name}'..."
                    )
                    email = self._sign_in(module, service, name)
                    if email:
                        GoogleAccounts.set_email(name, email)
                    authorized.append(module)
                except Exception as e:
                    problems.append(f"{module.capitalize()}: {e}")
                    logger.log_error(str(e), f"google_account_auth.{module}.{name}")

        worker = threading.Thread(target=work, name=f"google-oauth-{name}", daemon=True)
        worker.start()
        worker.join(_AUTH_TIMEOUT_SECONDS)

        if worker.is_alive():
            problems.append(
                "Sign-in wasn't finished in time. The browser window is still open — "
                "finishing there completes it."
            )

        # Copied: an abandoned worker may still append to these.
        return list(authorized), list(problems)

    def accounts_snapshot(self) -> typing.Dict[str, typing.Any]:
        """Accounts as data, for the accounts panel.

        Not a job: list_google_accounts returns a sentence, and a row with a
        primary marker and per-service sign-in state cannot be parsed out of
        one. Reads only local files, so it never triggers a consent prompt.
        """
        primary = GoogleAccounts.get_primary()

        accounts = []
        for name in GoogleAccounts.list_accounts():
            record = GoogleAccounts.record(name)
            accounts.append(
                {
                    "name": name,
                    "email": (record.get("email", "") or "").strip(),
                    "primary": name == primary,
                    "tokens": GoogleAccounts.token_status(name),
                }
            )

        enabled = Config.enabled_modules()
        return {
            "accounts": accounts,
            "primary": primary,
            "services": {module: module in enabled for module in _GOOGLE_SERVICES},
            # Without the OAuth client file nothing can be authorized at all.
            "credentials_ready": os.path.exists(CREDENTIALS_FILE),
        }

    @capture_response
    @method_job
    def list_google_accounts(self) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Lists all configured Google accounts with their status.

        Returns:
            str: All configured accounts, marking the primary.
        """
        accounts = GoogleAccounts.list_accounts()
        primary = GoogleAccounts.get_primary()

        if not accounts:
            return (
                "No Google accounts configured. Say 'add google account' to set one up."
            )

        lines = []
        for name in accounts:
            # Listing should be read-only and must not trigger OAuth.
            rec = GoogleAccounts.record(name)
            email = (rec.get("email", "") or "").strip()
            marker = " [primary]" if name == primary else ""
            lines.append(f"  {name}{marker}" + (f" ({email})" if email else ""))

        return f"Google accounts ({len(accounts)}):\n" + "\n".join(lines)

    @capture_response
    @method_job
    def add_google_account(self, name: str) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Adds a new Google account for Gmail and Calendar access.
        Opens browser for OAuth consent. The first account added becomes the primary.

        Args:
            name (str): A short label for the account (e.g. 'work', 'personal'). (required)

        Returns:
            str: Confirmation that the account was added.
        """
        if not name:
            return "Please provide a name for the account, e.g. 'work' or 'personal'."

        try:
            safe_name = GoogleAccounts.add_account(name)
        except ValueError as e:
            return str(e)

        logger.log_system_event(
            "google_account_add",
            f"Account '{safe_name}' registered. Triggering OAuth authorization...",
        )

        authorized, problems = self._authorize(safe_name)
        if not problems:
            return f"Account '{safe_name}' added successfully."

        details = " ".join(problems)
        if authorized:
            return (
                f"Account '{safe_name}' was added and signed in to "
                f"{', '.join(authorized)}, but not the rest. {details}"
            )
        return (
            f"Account '{safe_name}' was registered, but sign-in didn't complete. "
            f"{details} Say 'authorize {safe_name}' to try again."
        )

    @capture_response
    @method_job
    def authorize_google_account(self, name: str) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Signs in to an already-added Google account again.
        Opens a browser for consent. Use this when an account has stopped working.

        Args:
            name (str): The account name to authorize (e.g. 'work'). (required)

        Returns:
            str: Which services were signed in, or what went wrong.
        """
        if not name:
            return "Please specify which account to authorize."

        try:
            GoogleAccounts.clear_tokens(name)
        except ValueError as e:
            return str(e)
        self._forget_cached(name)

        authorized, problems = self._authorize(name)
        if authorized and not problems:
            return f"Account '{name}' is signed in to {', '.join(authorized)}."
        if authorized:
            return (
                f"Account '{name}' is signed in to {', '.join(authorized)}, "
                f"but not the rest. {' '.join(problems)}"
            )
        return f"Couldn't sign in to '{name}'. {' '.join(problems)}"

    @capture_response
    @method_job
    def remove_google_account(self, name: str) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Removes a configured Google account and deletes its tokens.

        Args:
            name (str): The account name to remove (e.g. 'work'). (required)

        Returns:
            str: Confirmation that the account was removed.
        """
        if not name:
            return "Please specify which account to remove."

        try:
            GoogleAccounts.remove_account(name)
        except ValueError as e:
            return str(e)

        self._forget_cached(name)
        return f"Account '{name}' removed."

    @capture_response
    @method_job
    def edit_google_account(self, name: str, new_name: str = "", set_primary: bool = False) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Edits a Google account — rename it or make it the primary.

        Args:
            name (str): The account name to edit. (required)
            new_name (str): New label for the account (leave empty to keep current).
            set_primary (bool): If true, make this account the primary/default.

        Returns:
            str: Confirmation of the change, or an error message.
        """
        if not name:
            return "Error: Account name is required."
        if not new_name and not set_primary:
            return "Error: Provide new_name or set set_primary=true."

        messages = []

        if new_name and new_name.strip() != name:
            try:
                safe = GoogleAccounts.rename_account(name, new_name)
            except ValueError as e:
                return str(e)
            # Token files moved with the account, so anything cached under
            # either name now points at a path that no longer exists.
            self._forget_cached(name)
            self._forget_cached(safe)
            messages.append(f"Account renamed: '{name}' → '{safe}'.")
            name = safe  # use new name for subsequent set_primary

        if set_primary:
            try:
                GoogleAccounts.set_primary(name)
                messages.append(f"Primary account set to '{name}'.")
            except ValueError as e:
                return str(e)

        return " ".join(messages) if messages else "No changes made."
