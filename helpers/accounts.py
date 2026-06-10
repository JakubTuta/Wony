import json
import os
import typing

_ACCOUNTS_FILE = "credentials/accounts.json"


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
        has_gmail = os.path.exists("credentials/gmail_token.json")
        has_calendar = os.path.exists("credentials/calendar_token.json")
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
        data = cls._load()
        if name not in data["accounts"]:
            raise ValueError(f"Account '{name}' not found.")
        return data["accounts"][name]

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
        for key in ("gmail_token", "calendar_token"):
            path = rec.get(key, "")
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        if data.get("primary") == name:
            data["primary"] = next(iter(data["accounts"]), None)
        cls._save()

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

        # Rename token files on disk
        for key in ("gmail_token", "calendar_token"):
            old_path = rec.get(key, "")
            if old_path and os.path.exists(old_path):
                new_path = old_path.replace(f"_{old_name}.", f"_{safe}.")
                try:
                    os.rename(old_path, new_path)
                    rec[key] = new_path
                except OSError:
                    pass

        data["accounts"][safe] = rec
        if data.get("primary") == old_name:
            data["primary"] = safe
        cls._save()
        return safe
