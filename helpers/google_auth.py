"""One Google sign-in per account, shared by every Google module, asking only
for what the safety switches allow.

Gmail stays read-and-draft until "Change my mailbox" is on, Drive stays
read-only until "Change my Drive files" is on, and so on. Turning a switch on
asks Google once more; turning it off gives the extra permission back the next
time the user is around to sign in.

The OAuth app stays in Google's Testing mode (publishing needs a public home
page, privacy policy and terms), so Google ends every sign-in after 7 days.
That is handled as a normal event: one notification, a "Sign in again" button,
and a heads-up the day before.
"""
import datetime
import os
import threading
import typing

from helpers.accounts import CREDENTIALS_FILE, GoogleAccounts

_API = "https://www.googleapis.com/auth/"
_IDENTITY = ["openid", _API + "userinfo.email"]

# Google module -> (scopes it always needs, extra scopes when its write switch
# is on, that switch). The one place permissions are decided.
_MODULE_SCOPES: typing.Dict[str, typing.Tuple[typing.List[str], typing.List[str], str]] = {
    "gmail": ([_API + "gmail.readonly", _API + "gmail.compose"], [_API + "gmail.modify"],
              "modules.gmail.allow_write"),
    "calendar": ([_API + "calendar.readonly"], [_API + "calendar.events"],
                 "modules.calendar.allow_write"),
    "drive": ([_API + "drive.readonly"],
              [_API + "documents", _API + "spreadsheets", _API + "drive.file"],
              "modules.drive.allow_write"),
    "contacts": ([_API + "contacts.readonly", _API + "contacts.other.readonly"], [_API + "contacts"],
                 "modules.contacts.allow_write"),
}
GOOGLE_MODULES = tuple(_MODULE_SCOPES)
_WRITE_SCOPES = {scope for _, extra, _ in _MODULE_SCOPES.values() for scope in extra}

# Consent happens in a browser at human speed: long enough for a password and a
# phone code, short enough that an abandoned sign-in does not hang forever.
_CONSENT_TIMEOUT_SECONDS = 180
# Testing-mode refresh tokens die 7 days after consent; warn a day early.
_WARN_AFTER = datetime.timedelta(days=6)
_WAKING_HOURS = range(9, 21)

_locks: typing.Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_services: typing.Dict[typing.Tuple[str, str, str], typing.Any] = {}


class SignInNeeded(RuntimeError):
    """Google needs the user before this account can be used. Fit to say aloud."""


def _lock_for(name: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def scopes_wanted() -> typing.List[str]:
    """Every scope the switched-on Google modules need right now."""
    from helpers.config import Config

    wanted = set(_IDENTITY)
    for module, (base, extra, switch) in _MODULE_SCOPES.items():
        if not Config.is_module_enabled(module):
            continue
        wanted.update(base)
        if switch and Config.get(switch, False):
            wanted.update(extra)
    return sorted(wanted)


def _token_path(name: str) -> str:
    return GoogleAccounts.record(name)["token"]


def _load(name: str) -> typing.Any:
    from google.oauth2.credentials import Credentials

    path = _token_path(name)
    if not os.path.exists(path):
        return None
    try:
        # No scopes argument: keep what Google actually granted.
        return Credentials.from_authorized_user_file(path)
    except (ValueError, KeyError):
        return None


def _save(name: str, creds: typing.Any) -> None:
    path = _token_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())


def _sign_in_line(name: str) -> str:
    return f"Say 'authorize {name}' or press Sign in again on the Accounts page."


def credentials(account: str = "") -> typing.Any:
    """Working credentials for `account` (default: primary).

    Raises SignInNeeded when Google needs the user and nobody is there to ask —
    a trigger, a scheduled action or a background poll never opens a browser.
    """
    from helpers.turn_context import at_machine, user_present

    name = GoogleAccounts.resolve(account or None)
    with _lock_for(name):
        need = set(scopes_wanted())
        creds = _load(name)
        if creds is not None:
            granted = set(creds.scopes or [])
            missing = need - granted
            surplus_write = (granted - need) & _WRITE_SCOPES
            if not missing and not (surplus_write and at_machine()):
                return _fresh(name, creds)
            if surplus_write and at_machine():
                # A write switch was turned off: give the permission back.
                _revoke(creds)
        if not at_machine():
            # A chat from a phone is the user, but the consent page would open
            # on an empty desk — so it is told to come to the PC instead.
            hint = _sign_in_line(name)
            if user_present():
                hint = f"Do this at your PC: {hint}"
            if creds is None:
                raise SignInNeeded(f"Google account '{name}' isn't signed in. {hint}")
            raise SignInNeeded(f"Google needs your OK for something new on '{name}'. {hint}")
        return _consent(name, need)


def _fresh(name: str, creds: typing.Any) -> typing.Any:
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request

    if creds.valid:
        return creds
    if not creds.refresh_token:
        _mark_signed_out(name)
        raise SignInNeeded(f"Google signed me out of '{name}'. {_sign_in_line(name)}")
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        _mark_signed_out(name)
        raise SignInNeeded(
            f"Google signed me out of '{name}' — it does that every week for "
            f"personal apps. {_sign_in_line(name)}"
        ) from exc
    _save(name, creds)
    return creds


def _consent(name: str, scopes: typing.Set[str]) -> typing.Any:
    """Open the browser for Google's consent screen and keep the result."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(CREDENTIALS_FILE):
        raise SignInNeeded(
            "credentials/google_credentials.json is missing — run 'python setup.py "
            "configure' to add Google."
        )
    # Google answers with every scope ever granted when include_granted_scopes is
    # set; oauthlib treats that difference as an error unless told otherwise.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, scopes=sorted(scopes))
    hint = GoogleAccounts.record(name).get("email") or None
    creds = flow.run_local_server(
        port=0,
        timeout_seconds=_CONSENT_TIMEOUT_SECONDS,
        # Ask again even when Google remembers an earlier grant, or no refresh
        # token comes back and the sign-in dies within the hour.
        prompt="consent",
        login_hint=hint,
    )
    _save(name, creds)
    forget(name)
    email = _email_for(creds) or hint or ""
    GoogleAccounts.update(
        name,
        email=email,
        signed_in_at=datetime.datetime.now().isoformat(timespec="seconds"),
        needs_sign_in=False,
        warned_for="",
    )
    GoogleAccounts.drop_legacy_tokens(name)
    return creds


def _email_for(creds: typing.Any) -> str:
    from google.auth.transport.requests import AuthorizedSession

    try:
        response = AuthorizedSession(creds).get(
            "https://openidconnect.googleapis.com/v1/userinfo", timeout=10
        )
        return response.json().get("email", "")
    except Exception:
        return ""


def _revoke(creds: typing.Any) -> None:
    from helpers import net

    token = creds.refresh_token or creds.token
    if token:
        try:
            net.post("https://oauth2.googleapis.com/revoke", params={"token": token})
        except Exception:
            pass  # deleting the file below is what matters locally


def sign_in(account: str) -> str:
    """Ask Google for consent now, for everything the switches allow. Returns the
    address signed in. Only for a request the user made."""
    name = GoogleAccounts.resolve(account or None)
    with _lock_for(name):
        need = set(scopes_wanted())
        creds = _load(name)
        # Revoking ends the whole grant, so it can only come before a consent,
        # and only when a write switch went off since the last one.
        if creds is not None and (set(creds.scopes or []) - need) & _WRITE_SCOPES:
            _revoke(creds)
        _consent(name, need)
    return GoogleAccounts.record(name).get("email", "")


def sign_out(account: str) -> None:
    """Give the permission back to Google and forget the token."""
    name = GoogleAccounts.resolve(account or None)
    with _lock_for(name):
        creds = _load(name)
        if creds is not None:
            _revoke(creds)
        path = _token_path(name)
        if os.path.exists(path):
            os.remove(path)
        forget(name)


def forget(name: str) -> None:
    """Drop cached API clients for an account whose token changed."""
    for key in [k for k in _services if k[0] == name]:
        _services.pop(key, None)


def service(api: str, version: str, account: str = "") -> typing.Any:
    """A googleapiclient resource for `api` on `account`."""
    from googleapiclient.discovery import build

    name = GoogleAccounts.resolve(account or None)
    creds = credentials(name)
    key = (name, api, version)
    cached = _services.get(key)
    if cached is not None and cached[0] is creds:
        return cached[1]
    resource = build(api, version, credentials=creds, cache_discovery=False)
    _services[key] = (creds, resource)
    return resource


def _mark_signed_out(name: str) -> None:
    """Record it once and tell the user once — not an error on every call."""
    if GoogleAccounts.record(name).get("needs_sign_in"):
        return
    GoogleAccounts.update(name, needs_sign_in=True)
    from helpers.notify import notify

    notify(
        f"Google signed me out of '{name}' (it does that weekly for personal apps). "
        f"{_sign_in_line(name)}",
        kind="alert", source="google",
    )


def status(account: str) -> typing.Dict[str, typing.Any]:
    """Sign-in state for the accounts page. Local only: never prompts."""
    record = GoogleAccounts.record(account)
    creds = _load(account)
    granted = set(creds.scopes or []) if creds is not None else set()
    missing = set(scopes_wanted()) - granted
    return {
        "signed_in": creds is not None and not record.get("needs_sign_in"),
        "needs_sign_in": creds is None or bool(record.get("needs_sign_in")) or bool(missing),
        "modules": {
            module: bool(base) and set(base) <= granted
            for module, (base, _, _) in _MODULE_SCOPES.items()
        },
        "signed_in_at": record.get("signed_in_at", ""),
    }


def warn_before_sign_out() -> None:
    """A day before Google's weekly sign-out, say so at a waking hour, so the
    morning briefing does not fail. Called from the health watcher."""
    from helpers.notify import notify

    now = datetime.datetime.now()
    if now.hour not in _WAKING_HOURS:
        return
    for name in GoogleAccounts.list_accounts():
        record = GoogleAccounts.record(name)
        stamp = record.get("signed_in_at", "")
        if not stamp or record.get("needs_sign_in") or record.get("warned_for") == stamp:
            continue
        try:
            signed_in = datetime.datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if now - signed_in < _WARN_AFTER:
            continue
        GoogleAccounts.update(name, warned_for=stamp)
        notify(
            f"Google will sign me out of '{name}' tomorrow. Sign in again now to keep "
            f"mail and calendar working: {_sign_in_line(name)}",
            kind="alert", source="google",
        )
