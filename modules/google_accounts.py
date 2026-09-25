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
                    email = service.sign_in(name)
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

        Not a job: manage_google_accounts returns a sentence, and a row with a
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
    @method_job(confirms={"add", "authorize", "remove", "rename", "set_primary"})
    def manage_google_accounts(
        self,
        action: typing.Literal[
            "list", "add", "authorize", "remove", "rename", "set_primary"
        ] = "list",
        name: str = "",
        new_name: str = "",
    ) -> str:
        """
        [GOOGLE ACCOUNTS JOB] Lists, adds, signs in to, renames or removes the Google
        accounts Wony can use for Gmail and Calendar, and picks which one is the default.
        Adding and authorizing open a browser for consent.

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

    def _add_account(self, name: str) -> str:
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

    def _authorize_account(self, name: str) -> str:
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

    def _remove_account(self, name: str) -> str:
        try:
            GoogleAccounts.remove_account(name)
        except ValueError as e:
            return str(e)

        self._forget_cached(name)
        return f"Account '{name}' removed."

    def _rename_account(self, name: str, new_name: str) -> str:
        if new_name.strip() == name:
            return "No changes made."
        try:
            safe = GoogleAccounts.rename_account(name, new_name)
        except ValueError as e:
            return str(e)
        # Token files moved with the account, so anything cached under either
        # name now points at a path that no longer exists.
        self._forget_cached(name)
        self._forget_cached(safe)
        return f"Account renamed: '{name}' → '{safe}'."
