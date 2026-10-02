import json
import os
import typing

from helpers.paths import repo_path

_ACCOUNTS_FILE = repo_path("credentials", "accounts.json")

# One OAuth client covers every account; accounts differ by token, not client.
CREDENTIALS_FILE = repo_path("credentials", "google_credentials.json")

# Before one token per account, each Google service kept its own file.
_LEGACY_KEYS = ("gmail_token", "calendar_token")


def _abs(path: str) -> str:
    """Token paths are stored repo-relative so accounts.json stays portable;
    resolve them before any filesystem access."""
    return repo_path(path) if path and not os.path.isabs(path) else path


def _token_rel(name: str) -> str:
    return f"credentials/google_token_{name}.json"


def _remove_file(path: str) -> None:
    path = _abs(path)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


class GoogleAccounts:
    """The accounts list in credentials/accounts.json. Signing in, scopes and
    tokens themselves are helpers/google_auth.py."""

    _data: typing.Optional[dict] = None

    @classmethod
    def _load(cls) -> dict:
        if cls._data is not None:
            return cls._data
        if os.path.exists(_ACCOUNTS_FILE):
            # Be tolerant of BOM-prefixed UTF-8 written by some editors/shell tools.
            with open(_ACCOUNTS_FILE, "r", encoding="utf-8-sig") as f:
                cls._data = json.load(f)
        else:
            cls._data = {"primary": None, "accounts": {}}
            cls._migrate_single_token_files()
        if cls._migrate_per_service_tokens():
            cls._save()
        return cls._data

    @classmethod
    def _save(cls) -> None:
        os.makedirs(os.path.dirname(_ACCOUNTS_FILE), exist_ok=True)
        with open(_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(cls._data, f, indent=2)

    @classmethod
    def _migrate_single_token_files(cls) -> None:
        """Oldest installs kept one gmail_token.json / calendar_token.json."""
        legacy = [p for p in ("credentials/gmail_token.json", "credentials/calendar_token.json")
                  if os.path.exists(_abs(p))]
        if legacy:
            cls._data["accounts"]["primary"] = {"gmail_token": legacy[0], "email": ""}
            cls._data["primary"] = "primary"

    @classmethod
    def _migrate_per_service_tokens(cls) -> bool:
        """One token per account replaced one per service. The old files only
        cover part of what is needed now, so the account signs in once more and
        they are deleted after that sign-in succeeds."""
        changed = False
        for name, rec in cls._data["accounts"].items():
            if "token" in rec:
                continue
            rec["legacy_tokens"] = [rec.pop(key) for key in _LEGACY_KEYS if rec.get(key)]
            rec["token"] = _token_rel(name)
            rec["needs_sign_in"] = True
            changed = True
        return changed

    @classmethod
    def list_accounts(cls) -> typing.List[str]:
        return list(cls._load()["accounts"].keys())

    @classmethod
    def get_primary(cls) -> typing.Optional[str]:
        return cls._load().get("primary")

    @classmethod
    def set_primary(cls, name: str) -> None:
        data = cls._load()
        if name not in data["accounts"]:
            raise ValueError(f"Account '{name}' not found.")
        data["primary"] = name
        cls._save()

    @classmethod
    def resolve(cls, name: typing.Optional[str]) -> str:
        """Return name if known, else primary. Raises if no account configured."""
        data = cls._load()
        if name and name in data["accounts"]:
            return name
        primary = data.get("primary")
        if primary and primary in data["accounts"]:
            return primary
        raise RuntimeError(
            "No Google account configured. Say 'add google account' to set one up."
        )

    @classmethod
    def record(cls, name: str) -> dict:
        """Account record with the token path resolved to absolute."""
        data = cls._load()
        if name not in data["accounts"]:
            raise ValueError(f"Account '{name}' not found.")
        rec = dict(data["accounts"][name])
        rec["token"] = _abs(rec["token"])
        return rec

    @classmethod
    def update(cls, name: str, **fields: typing.Any) -> None:
        data = cls._load()
        if name in data["accounts"]:
            data["accounts"][name].update(fields)
            cls._save()

    @classmethod
    def drop_legacy_tokens(cls, name: str) -> None:
        data = cls._load()
        rec = data["accounts"].get(name, {})
        if rec.get("legacy_tokens"):
            for path in rec.pop("legacy_tokens"):
                _remove_file(path)
            cls._save()

    @classmethod
    def add_account(cls, name: str) -> str:
        """Add a new account entry. Returns the normalized name."""
        data = cls._load()
        safe = name.strip().replace(" ", "_").lower()
        if safe in data["accounts"]:
            raise ValueError(f"Account '{safe}' already exists.")
        data["accounts"][safe] = {"token": _token_rel(safe), "email": ""}
        if not data.get("primary"):
            data["primary"] = safe
        cls._save()
        return safe

    @classmethod
    def remove_account(cls, name: str) -> None:
        data = cls._load()
        if name not in data["accounts"]:
            raise ValueError(f"Account '{name}' not found.")
        rec = data["accounts"].pop(name)
        for path in [rec.get("token", "")] + rec.get("legacy_tokens", []):
            _remove_file(path)
        if data.get("primary") == name:
            data["primary"] = next(iter(data["accounts"]), None)
        cls._save()

    @classmethod
    def rename_account(cls, old_name: str, new_name: str) -> str:
        """Rename an account, moving its token file. Returns the normalized new name."""
        data = cls._load()
        if old_name not in data["accounts"]:
            raise ValueError(f"Account '{old_name}' not found.")
        safe = new_name.strip().replace(" ", "_").lower()
        if safe == old_name:
            return old_name
        if safe in data["accounts"]:
            raise ValueError(f"Account '{safe}' already exists.")

        rec = data["accounts"].pop(old_name)
        new_rel = _token_rel(safe)
        if os.path.exists(_abs(rec["token"])):
            try:
                os.replace(_abs(rec["token"]), _abs(new_rel))
            except OSError:
                pass
        rec["token"] = new_rel
        data["accounts"][safe] = rec
        if data.get("primary") == old_name:
            data["primary"] = safe
        cls._save()
        return safe
