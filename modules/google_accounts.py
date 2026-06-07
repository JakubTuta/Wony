from helpers.accounts import GoogleAccounts
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import method_job, register_service


@register_service(module_name="google_accounts")
class GoogleAccountsService:
    """Google account management — add, remove, list, set primary."""

    def __init__(self):
        pass

    def _email_from_gmail(self, gmail_svc, account: str) -> str:
        if not gmail_svc:
            return ""
        try:
            profile = gmail_svc._svc(account).users().getProfile(userId="me").execute()
            return (profile or {}).get("emailAddress", "")
        except Exception as e:
            logger.log_error(str(e), f"google_account_email.gmail_profile.{account}")
            return ""

    def _email_from_calendar(self, cal_svc, account: str) -> str:
        if not cal_svc:
            return ""
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

    def _ensure_account_email(self, account: str, gmail_svc=None, cal_svc=None) -> str:
        rec = GoogleAccounts.record(account)
        email = (rec.get("email", "") or "").strip()
        if email:
            return email

        email = self._email_from_gmail(gmail_svc, account)
        if not email:
            email = self._email_from_calendar(cal_svc, account)

        if email:
            GoogleAccounts.set_email(account, email)
        return email

    @capture_response
    @method_job
    def list_google_accounts(self) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Lists all configured Google accounts with their status.

        Use this job when the user wants to:
        - See which Google accounts are set up
        - Check which account is the primary/default
        - View all available email or calendar accounts

        Keywords: google accounts, list accounts, my accounts, which accounts,
                 show accounts, configured accounts, email accounts, account list,
                 available accounts, list all accounts, all accounts, all google accounts,
                 show all accounts, get accounts, fetch accounts, display accounts

        Args:
            None

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

        Use this job when the user wants to:
        - Add a new Google or Gmail account
        - Connect another email or calendar
        - Set up a work or secondary account
        - Link a new Google account

        Keywords: add google account, connect account, new account, add email account,
                 link account, setup google account, add work account, add second account,
                 new google account

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

        from helpers.registry import ServiceRegistry

        gmail_svc = ServiceRegistry.get_service_instance("gmail")
        cal_svc = ServiceRegistry.get_service_instance("calendar")
        auth_errors = []
        gmail_ok = False
        calendar_ok = False

        if gmail_svc:
            try:
                logger.log_system_event("google_account_add", "Authorizing Gmail...")
                gmail_svc._client(safe_name)
                email = self._email_from_gmail(gmail_svc, safe_name)
                if email:
                    GoogleAccounts.set_email(safe_name, email)
                logger.log_system_event("google_account_add", "Gmail authorized.")
                gmail_ok = True
            except Exception as e:
                auth_errors.append(f"Gmail auth failed: {e}")
                logger.log_error(str(e), f"google_account_add.gmail_auth.{safe_name}")
        if cal_svc:
            try:
                logger.log_system_event("google_account_add", "Authorizing Calendar...")
                cal_svc._service_for(safe_name)
                if not GoogleAccounts.record(safe_name).get("email", ""):
                    email = self._email_from_calendar(cal_svc, safe_name)
                    if email:
                        GoogleAccounts.set_email(safe_name, email)
                logger.log_system_event("google_account_add", "Calendar authorized.")
                calendar_ok = True
            except Exception as e:
                auth_errors.append(f"Calendar auth failed: {e}")
                logger.log_error(
                    str(e), f"google_account_add.calendar_auth.{safe_name}"
                )
        if auth_errors:
            details = "; ".join(auth_errors)
            if gmail_ok or calendar_ok:
                return (
                    f"Account '{safe_name}' was added, but authorization only partially "
                    f"completed. {details}"
                )
            return (
                f"Account '{safe_name}' was registered, but authorization failed. "
                f"{details}"
            )

        return f"Account '{safe_name}' added successfully."

    @capture_response
    @method_job
    def remove_google_account(self, name: str) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Removes a configured Google account and deletes its tokens.

        Use this job when the user wants to:
        - Remove a Google account
        - Delete an account configuration
        - Disconnect an email or calendar account

        Keywords: remove google account, delete account, disconnect account,
                 remove email account, unlink account, remove work account,
                 delete google account

        Args:
            name (str): The account name to remove (e.g. 'work'). (required)

        Returns:
            str: Confirmation that the account was removed.
        """
        if not name:
            return "Please specify which account to remove."

        try:
            GoogleAccounts.remove_account(name)
            return f"Account '{name}' removed."
        except ValueError as e:
            return str(e)

    @capture_response
    @method_job
    def set_primary_account(self, name: str) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Sets the primary (default) Google account used when
        no specific account is mentioned.

        Use this job when the user wants to:
        - Change the default Google account
        - Switch primary email or calendar
        - Set a specific account as the default

        Keywords: set primary account, change default account, switch primary,
                 use account as default, make default account, primary google account,
                 set default account

        Args:
            name (str): The account name to make primary. (required)

        Returns:
            str: Confirmation that the primary account was updated.
        """
        if not name:
            return "Please specify which account to set as primary."

        try:
            GoogleAccounts.set_primary(name)
            return f"Primary account set to '{name}'."
        except ValueError as e:
            return str(e)
