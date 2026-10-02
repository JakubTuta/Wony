import os
import threading
import typing

from helpers import google_auth
from helpers.accounts import CREDENTIALS_FILE, GoogleAccounts
from helpers.config import Config
from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import method_job, register_service

# Consent happens in a browser; the agent turn waits this long for it, and a
# little longer than the consent flow's own timeout so that one reports first.
_AUTH_WAIT_SECONDS = 200


@register_service(module_name="google_accounts")
class GoogleAccountsService:
    """Google account management — add, remove, list, authorize, set primary."""

    def __init__(self):
        pass

    def _authorize(self, name: str) -> str:
        """Run Google's consent for this account. Returns "" on success, else why not.

        The flow runs on a worker thread because it blocks on a person, and the
        caller is an agent turn.
        """
        if not any(Config.is_module_enabled(m) for m in google_auth.GOOGLE_MODULES):
            return "Neither Gmail nor Calendar is switched on, so there is nothing to sign in to."
        if not os.path.exists(CREDENTIALS_FILE):
            return (
                "credentials/google_credentials.json is missing — run "
                "'python setup.py configure' to add Google first."
            )

        problem: typing.List[str] = []

        def work() -> None:
            try:
                logger.log_system_event("google_account_auth", f"Signing in '{name}'...")
                google_auth.sign_in(name)
            except Exception as e:
                problem.append(str(e))
                logger.log_error(str(e), f"google_account_auth.{name}")

        worker = threading.Thread(target=work, name=f"google-oauth-{name}", daemon=True)
        worker.start()
        worker.join(_AUTH_WAIT_SECONDS)
        if worker.is_alive():
            return "Sign-in wasn't finished in time. Finishing it in the browser window still works."
        return problem[0] if problem else ""

    def accounts_snapshot(self) -> typing.Dict[str, typing.Any]:
        """Accounts as data, for the accounts panel.

        Not a job: manage_google_accounts returns a sentence, and a row with a
        primary marker and sign-in state cannot be parsed out of one. Reads only
        local files, so it never opens a consent prompt.
        """
        primary = GoogleAccounts.get_primary()
        accounts = []
        for name in GoogleAccounts.list_accounts():
            record = GoogleAccounts.record(name)
            accounts.append({
                "name": name,
                "email": (record.get("email", "") or "").strip(),
                "primary": name == primary,
                **google_auth.status(name),
            })

        enabled = Config.enabled_modules()
        return {
            "accounts": accounts,
            "primary": primary,
            "services": {module: module in enabled for module in google_auth.GOOGLE_MODULES},
            # Without the OAuth client file nothing can be authorized at all.
            "credentials_ready": os.path.exists(CREDENTIALS_FILE),
        }

    @capture_response
    @method_job(confirms={"add", "remove", "rename", "set_primary"})
    def manage_google_accounts(
        self,
        action: str = "list",
        name: str = "",
        new_name: str = "",
    ) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Lists, adds, signs in to, renames or removes the Google
        accounts Wony uses for Gmail and Calendar, and picks which one is the default. "Authorize" signs an account in again — Google signs Wony out
        every week. Adding and authorizing open a browser for consent.

        Args:
            action (str): "list" (the default), "add", "authorize", "remove", "rename"
                or "set_primary".
            name (str): Short label for the account, e.g. "work", "personal".
                (required for everything except "list")
            new_name (str): The new label. (required for "rename")

        Returns:
            str: The account list, or confirmation of what changed.
        """
        wanted = (action or "list").strip().lower()

        if wanted in ("list", "show"):
            return self._list_accounts()

        if not name:
            return f"Please say which account to {wanted}."

        if wanted == "add":
            return self._add_account(name)
        if wanted in ("authorize", "auth", "sign_in", "login"):
            return self._authorize_account(name)
        if wanted in ("remove", "delete", "forget"):
            return self._remove_account(name)
        if wanted == "rename":
            if not new_name:
                return "Error: 'new_name' is required to rename an account."
            return self._rename_account(name, new_name)
        if wanted in ("set_primary", "primary", "default"):
            try:
                GoogleAccounts.set_primary(name)
            except ValueError as e:
                return str(e)
            return f"Primary account set to '{name}'."

        return (
            f"Unknown action '{action}'. Use list, add, authorize, remove, "
            "rename or set_primary."
        )

    def _list_accounts(self) -> str:
        accounts = GoogleAccounts.list_accounts()
        primary = GoogleAccounts.get_primary()

        if not accounts:
            return "No Google accounts configured. Say 'add google account' to set one up."

        lines = []
        for name in accounts:
            email = (GoogleAccounts.record(name).get("email", "") or "").strip()
            marker = " [primary]" if name == primary else ""
            state = "" if not google_auth.status(name)["needs_sign_in"] else " — needs signing in"
            lines.append(f"  {name}{marker}" + (f" ({email})" if email else "") + state)
        return f"Google accounts ({len(accounts)}):\n" + "\n".join(lines)

    def _add_account(self, name: str) -> str:
        try:
            safe_name = GoogleAccounts.add_account(name)
        except ValueError as e:
            return str(e)
        problem = self._authorize(safe_name)
        if not problem:
            return f"Account '{safe_name}' added and signed in."
        return (
            f"Account '{safe_name}' was added, but sign-in didn't complete. "
            f"{problem} Say 'authorize {safe_name}' to try again."
        )

    def _authorize_account(self, name: str) -> str:
        if name not in GoogleAccounts.list_accounts():
            return f"Account '{name}' not found."
        problem = self._authorize(name)
        if problem:
            return f"Couldn't sign in to '{name}'. {problem}"
        email = GoogleAccounts.record(name).get("email", "")
        return f"'{name}' is signed in" + (f" as {email}." if email else ".")

    def _remove_account(self, name: str) -> str:
        if name not in GoogleAccounts.list_accounts():
            return f"Account '{name}' not found."
        google_auth.sign_out(name)
        GoogleAccounts.remove_account(name)
        return f"Account '{name}' removed."

    def _rename_account(self, name: str, new_name: str) -> str:
        if new_name.strip() == name:
            return "No changes made."
        try:
            safe = GoogleAccounts.rename_account(name, new_name)
        except ValueError as e:
            return str(e)
        google_auth.forget(name)
        return f"Account renamed: '{name}' → '{safe}'."
