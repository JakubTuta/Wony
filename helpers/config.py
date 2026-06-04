import os
import typing

DEFAULTS: typing.Dict[str, typing.Any] = {
    "assistant": {
        "name": "Wony",
        "owner_name": "User",
        "personality": "Friendly and concise.",
        "language": "en",
    },
    "voice": {
        "enabled": False,
        "tts_voice_index": 1,
        "rate": 150,
        "volume": 0.6,
    },
    "ai": {
        "provider": None,
        "anthropic_model": None,
        "gemini_model": None,
        "ollama_model": "llama3.1",
        "max_tokens": 2048,
        "history": {
            "enabled": True,
            "max_turns": 5,
            "idle_timeout_minutes": 10,
        },
        "agent": {
            "max_steps": 5,
            "narrate": True,
        },
    },
    "enabled_modules": ["ai", "status", "weather", "spotify", "system", "screen"],
    "modules": {
        "shelly": {"base_url": "http://192.168.18.53"},
        "system": {"allow_shutdown": False},
        "weather": {"default_units": "metric"},
        "gmail": {
            "poll_interval_minutes": 15,
            "max_results": 20,
            "max_body_chars": 1500,
            "allow_send": False,
            "use_ai": False,
            "ai_summary_max_emails": 30,
        },
        "calendar": {
            "poll_interval_minutes": 15,
            "lookahead_hours": 24,
            "max_results": 10,
            "search_days_back": 30,
            "search_days_ahead": 90,
            "work_start_hour": 9,
            "work_end_hour": 18,
            "allow_write": False,
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    _data: typing.Dict = {}
    _loaded: bool = False

    @classmethod
    def load(cls, path: str = "config.yaml") -> None:
        import yaml

        data: dict = {}
        for candidate in [path, "config.example.yaml"]:
            if os.path.exists(candidate):
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        loaded = yaml.safe_load(f)
                        if loaded and isinstance(loaded, dict):
                            data = loaded
                except Exception:
                    pass
                break

        cls._data = _deep_merge(DEFAULTS, data)
        cls._loaded = True

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls._loaded:
            cls.load()

    @classmethod
    def get(cls, dotted_key: str, default: typing.Any = None) -> typing.Any:
        cls._ensure_loaded()
        keys = dotted_key.split(".")
        node: typing.Any = cls._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @classmethod
    def enabled_modules(cls) -> typing.Set[str]:
        cls._ensure_loaded()
        mods = cls._data.get("enabled_modules", DEFAULTS["enabled_modules"])
        return set(mods) if isinstance(mods, list) else set()

    @classmethod
    def is_module_enabled(cls, module_name: str) -> bool:
        if module_name in ("ai", "status"):
            return True
        return module_name in cls.enabled_modules()

    @classmethod
    def module_settings(cls, module_name: str) -> typing.Dict:
        cls._ensure_loaded()
        modules = cls._data.get("modules", {})
        return modules.get(module_name, {})
