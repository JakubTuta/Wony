import json
import os
import typing


_PROFILE_FILE = "profile.json"


class Profile:
    """Persistent personalization store — durable user facts that survive restarts.

    Holds things like preferred account, preferred units, user relationships, etc.
    Distinct from the rolling conversation window (Conversation).
    """

    _data: typing.Optional[typing.Dict[str, str]] = None

    @classmethod
    def _load(cls) -> typing.Dict[str, str]:
        if cls._data is not None:
            return cls._data

        if os.path.exists(_PROFILE_FILE):
            try:
                with open(_PROFILE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        cls._data = {str(k): str(v) for k, v in loaded.items()}
                        return cls._data
            except Exception:
                pass

        # Seed from config on first run
        cls._data = cls._seed_from_config()
        cls._save()
        return cls._data

    @classmethod
    def _seed_from_config(cls) -> typing.Dict[str, str]:
        try:
            from helpers.config import Config
            data: typing.Dict[str, str] = {}
            name = Config.get("assistant.owner_name")
            if name and name != "User":
                data["owner_name"] = name
            language = Config.get("assistant.language")
            if language and language != "en":
                data["language"] = language
            units = Config.get("modules.weather.default_units")
            if units:
                data["preferred_units"] = units
            return data
        except Exception:
            return {}

    @classmethod
    def _save(cls) -> None:
        if cls._data is None:
            return
        try:
            with open(_PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump(cls._data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    @classmethod
    def get(cls, key: str, default: typing.Optional[str] = None) -> typing.Optional[str]:
        return cls._load().get(key, default)

    @classmethod
    def set(cls, key: str, value: str) -> None:
        cls._load()[key] = value
        cls._save()

    @classmethod
    def remove(cls, key: str) -> bool:
        data = cls._load()
        if key in data:
            del data[key]
            cls._save()
            return True
        return False

    @classmethod
    def all(cls) -> typing.Dict[str, str]:
        return dict(cls._load())

    @classmethod
    def as_text(cls) -> str:
        """Return profile facts as a short prose block for injection into system prompts."""
        data = cls._load()
        if not data:
            return ""
        lines = [f"{k.replace('_', ' ')}: {v}" for k, v in sorted(data.items())]
        return "Known user facts: " + "; ".join(lines) + "."
