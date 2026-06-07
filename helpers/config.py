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
        "tts_voice": "af_heart",
        "speed": 1.0,
        "volume": 0.6,
        "model_path": "models/kokoro-v1.0.onnx",
        "voices_path": "models/voices-v1.0.bin",
        "stt": {
            "start_timeout": 4.0,
            "max_seconds": 12.0,
            "silence_ms": 500,
            "vad_aggressiveness": 2,
        },
        "wake_word": {
            "enabled": False,
            "phrase": "hey jarvis",    # built-in model name; ignored when model_path is set
            "model_path": None,        # path to a custom .onnx model (optional)
            "threshold": 0.5,          # detection score cutoff 0..1
            "cooldown_seconds": 2.0,
        },
    },
    "ai": {
        "provider": None,
        "anthropic_model": None,
        "gemini_model": None,
        "ollama_model": "llama3.1",
        "max_tokens": 8192,
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
    "enabled_modules": ["ai", "status", "basics", "weather", "spotify", "screen"],
    "modules": {
        "shelly": {"base_url": "http://192.168.18.53"},
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
        "scheduler": {
            "daily_briefing_time": None,
        },
        "web": {
            "max_content_chars": 3000,
        },
        "desktop": {
            "allow_actions": False,
            "file_search_root": "~",
        },
        "memory": {
            "max_history_days": 90,
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
