from helpers.accounts import GoogleAccounts
from helpers.audio import Audio
from helpers.cache import Cache
from helpers.registry import method_job, register_service


@register_service(module_name="google_accounts")
class GoogleAccountsService:
    """Google account management — add, remove, list, set primary."""

    def __init__(self):
        pass

    @method_job
    def list_google_accounts(self) -> None:
        """
        [GOOGLE ACCOUNTS JOB] Lists all configured Google accounts with their status.

        Use this job when the user wants to:
        - See which Google accounts are set up
        - Check which account is the primary/default
        - View all available email or calendar accounts

        Keywords: google accounts, list accounts, my accounts, which accounts,
                 show accounts, configured accounts, email accounts, account list,
                 available accounts

        Args:
            None

        Returns:
            None: Prints all configured accounts, marking the primary.
        """
        audio = Cache.get_audio()
        accounts = GoogleAccounts.list_accounts()
        primary = GoogleAccounts.get_primary()

        if not accounts:
            msg = "No Google accounts configured. Say 'add google account' to set one up."
            if audio:
                Audio.text_to_speech(msg)
            else:
                print(msg)
            return

        lines = []
        for name in accounts:
            rec = GoogleAccounts.record(name)
            email = rec.get("email", "")
            marker = " [primary]" if name == primary else ""
            lines.append(f"  {name}{marker}" + (f" ({email})" if email else ""))

        if audio:
            Audio.text_to_speech(
                f"You have {len(accounts)} Google account{'s' if len(accounts) != 1 else ''}. "
                + ", ".join(
                    f"{n}{' primary' if n == primary else ''}" for n in accounts
                )
            )
        else:
            print(f"Google accounts ({len(accounts)}):\n" + "\n".join(lines))

    @method_job
    def add_google_account(self, name: str = "") -> str:
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
            name (str): A short label for the account (e.g. 'work', 'personal').

        Returns:
            str: Confirmation that the account was added.
        """
        audio = Cache.get_audio()
        if not name:
            msg = "Please provide a name for the account, e.g. 'work' or 'personal'."
            if audio:
                Audio.text_to_speech(msg)
            else:
                print(msg)
            return msg

        try:
            safe_name = GoogleAccounts.add_account(name)
        except ValueError as e:
            msg = str(e)
            if audio:
                Audio.text_to_speech(msg)
            else:
                print(msg)
            return msg

        print(f"Account '{safe_name}' registered. Triggering OAuth authorization...")

        from helpers.registry import ServiceRegistry
        gmail_svc = ServiceRegistry.get_service_instance("gmail")
        cal_svc = ServiceRegistry.get_service_instance("calendar")

        if gmail_svc:
            try:
                print("Authorizing Gmail — a browser window will open...")
                gmail_svc._client(safe_name)
                print("Gmail authorized.")
            except Exception as e:
                print(f"Gmail auth failed: {e}")
        if cal_svc:
            try:
                print("Authorizing Calendar — a browser window will open...")
                cal_svc._service_for(safe_name)
                print("Calendar authorized.")
            except Exception as e:
                print(f"Calendar auth failed: {e}")

        result = f"Account '{safe_name}' added successfully."
        if audio:
            Audio.text_to_speech(result)
        else:
            print(result)
        return result

    @method_job
    def remove_google_account(self, name: str = "") -> str:
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
            name (str): The account name to remove (e.g. 'work').

        Returns:
            str: Confirmation that the account was removed.
        """
        audio = Cache.get_audio()
        if not name:
            msg = "Please specify which account to remove."
            if audio:
                Audio.text_to_speech(msg)
            else:
                print(msg)
            return msg

        try:
            GoogleAccounts.remove_account(name)
            result = f"Account '{name}' removed."
        except ValueError as e:
            result = str(e)

        if audio:
            Audio.text_to_speech(result)
        else:
            print(result)
        return result

    @method_job
    def set_primary_account(self, name: str = "") -> str:
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
            name (str): The account name to make primary.

        Returns:
            str: Confirmation that the primary account was updated.
        """
        audio = Cache.get_audio()
        if not name:
            msg = "Please specify which account to set as primary."
            if audio:
                Audio.text_to_speech(msg)
            else:
                print(msg)
            return msg

        try:
            GoogleAccounts.set_primary(name)
            result = f"Primary account set to '{name}'."
        except ValueError as e:
            result = str(e)

        if audio:
            Audio.text_to_speech(result)
        else:
            print(result)
        return result
