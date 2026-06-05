import typing

_seeded: bool = False


def _seed_from_config() -> None:
    global _seeded
    if _seeded:
        return
    _seeded = True
    from helpers.memory_db import all_facts, import_facts_from_dict
    if all_facts():
        return
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
        if data:
            import_facts_from_dict(data)
    except Exception:
        pass


class Profile:
    """Persistent personalization store backed by the SQLite facts table in wony.db."""

    @classmethod
    def get(cls, key: str, default: typing.Optional[str] = None) -> typing.Optional[str]:
        _seed_from_config()
        from helpers.memory_db import get_fact
        value = get_fact(key)
        return value if value is not None else default

    @classmethod
    def set(cls, key: str, value: str) -> None:
        from helpers.memory_db import set_fact
        set_fact(key, value)

    @classmethod
    def remove(cls, key: str) -> bool:
        from helpers.memory_db import remove_fact
        return remove_fact(key)

    @classmethod
    def all(cls) -> typing.Dict[str, str]:
        _seed_from_config()
        from helpers.memory_db import all_facts
        return all_facts()

    @classmethod
    def as_text(cls) -> str:
        data = cls.all()
        if not data:
            return ""
        lines = [f"{k.replace('_', ' ')}: {v}" for k, v in sorted(data.items())]
        return "Known user facts: " + "; ".join(lines) + "."
