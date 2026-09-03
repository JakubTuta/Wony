import json
import os
import typing

from helpers.paths import repo_path

_ACCOUNTS_FILE = repo_path("credentials", "accounts.json")

# One OAuth client covers every account; accounts differ by token, not client.
CREDENTIALS_FILE = repo_path("credentials", "google_credentials.json")

_TOKEN_KEYS = ("gmail_token", "calendar_token")


def _abs(path: str) -> str:
    """Token paths are stored repo-relative so accounts.json stays portable;
    resolve them before any filesystem access."""
    return repo_path(path) if path and not os.path.isabs(path) else path


class GoogleAccounts:
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
            cls._migrate_legacy()
        return cls._data

    @classmethod
    def _save(cls) -> None:
        os.makedirs(os.path.dirname(_ACCOUNTS_FILE), exist_ok=True)
        with open(_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(cls._data, f, indent=2)

    @classmethod
    def _migrate_legacy(cls) -> None:
        """Seed accounts.json from legacy single-token files on first run."""
        has_gmail = os.path.exists(_abs("credentials/gmail_token.json"))
        has_calendar = os.path.exists(_abs("credentials/calendar_token.json"))
        if has_gmail or has_calendar:
            cls._data["accounts"]["primary"] = {
                "gmail_token": "credentials/gmail_token.json",
                "calendar_token": "credentials/calendar_token.json",
                "email": "",
            }
            cls._data["primary"] = "primary"
            cls._save()

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
        """Account record with token paths resolved to absolute."""
        data = cls._load()
        if name not in data["accounts"]:
            raise ValueError(f"Account '{name}' not found.")
        rec = dict(data["accounts"][name])
        for key in _TOKEN_KEYS:
            if rec.get(key):
                rec[key] = _abs(rec[key])
        return rec

    @classmethod
    def add_account(cls, name: str) -> str:
        """Add a new account entry. Returns the normalized name."""
        data = cls._load()
        safe = name.strip().replace(" ", "_").lower()
        if safe in data["accounts"]:
            raise ValueError(f"Account '{safe}' already exists.")
        data["accounts"][safe] = {
            "gmail_token": f"credentials/gmail_token_{safe}.json",
            "calendar_token": f"credentials/calendar_token_{safe}.json",
            "email": "",
        }
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
        cls._delete_token_files(rec)
        if data.get("primary") == name:
            data["primary"] = next(iter(data["accounts"]), None)
        cls._save()

    @staticmethod
    def _remove_token(path: str) -> None:
        path = _abs(path)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    @classmethod
    def _delete_token_files(cls, rec: dict) -> None:
        for key in _TOKEN_KEYS:
            cls._remove_token(rec.get(key, ""))

    @classmethod
    def clear_token(cls, name: str, service: str) -> None:
        """Delete one service's stored token so its next use re-runs OAuth.

        Per service, not per account: a stale Gmail token must not take a
        working Calendar sign-in down with it.
        """
        data = cls._load()
        if name not in data["accounts"]:
            raise ValueError(f"Account '{name}' not found.")
        key = f"{service}_token"
        if key not in _TOKEN_KEYS:
            raise ValueError(f"Unknown service '{service}'.")
        cls._remove_token(data["accounts"][name].get(key, ""))

    @classmethod
    def clear_tokens(cls, name: str) -> None:
        """Delete an account's stored tokens so the next use re-runs OAuth.

        Without this, re-authorizing is a no-op: both Google libraries load
        whatever token file is on disk, revoked or not.
        """
        data = cls._load()
        if name not in data["accounts"]:
            raise ValueError(f"Account '{name}' not found.")
        cls._delete_token_files(data["accounts"][name])

    @classmethod
    def token_status(cls, name: str) -> typing.Dict[str, bool]:
        """Which services this account has a stored token for.

        A file on disk is not proof the token still works, but it is the only
        answer available without a network call.
        """
        rec = cls.record(name)
        return {
            "gmail": bool(rec.get("gmail_token")) and os.path.exists(rec["gmail_token"]),
            "calendar": bool(rec.get("calendar_token"))
            and os.path.exists(rec["calendar_token"]),
        }

    @classmethod
    def set_email(cls, name: str, email: str) -> None:
        data = cls._load()
        if name in data["accounts"]:
            data["accounts"][name]["email"] = email
            cls._save()

    @classmethod
    def rename_account(cls, old_name: str, new_name: str) -> str:
        """Rename an account. Returns the normalized new name."""
        data = cls._load()
        if old_name not in data["accounts"]:
            raise ValueError(f"Account '{old_name}' not found.")
        safe = new_name.strip().replace(" ", "_").lower()
        if safe == old_name:
            return old_name
        if safe in data["accounts"]:
            raise ValueError(f"Account '{safe}' already exists.")

        rec = data["accounts"].pop(old_name)

        # Rename token files on disk (rec keeps the repo-relative form).
        for key in _TOKEN_KEYS:
            old_rel = rec.get(key, "")
            if old_rel and os.path.exists(_abs(old_rel)):
                new_rel = old_rel.replace(f"_{old_name}.", f"_{safe}.")
                try:
                    os.rename(_abs(old_rel), _abs(new_rel))
                    rec[key] = new_rel
                except OSError:
                    pass

        data["accounts"][safe] = rec
        if data.get("primary") == old_name:
            data["primary"] = safe
        cls._save()
        return safe
