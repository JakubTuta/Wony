import os
import typing

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import YamlConfigSettingsSource

_MISSING = object()


class AssistantSettings(BaseModel):
    name: str = "Wony"
    owner_name: str = "User"
    personality: str = "Friendly and concise."
    language: str = "en"


class SttSettings(BaseModel):
    start_timeout: float = 4.0
    silence_ms: int = 700


class MediaPauseSettings(BaseModel):
    enabled: bool = True
    # None = use the built-in default (see MediaPause._RESUME_LINGER).
    resume_linger_seconds: typing.Optional[float] = None


class ConversationSettings(BaseModel):
    enabled: bool = True
    follow_up_timeout: float = 4.0


class BargeInSettings(BaseModel):
    enabled: bool = False


class HotkeySettings(BaseModel):
    # pynput combination string; null/empty disables the hotkey entirely.
    #
    # Deliberately NOT "<ctrl>+l". pynput's HotKey matcher only tracks the keys
    # named in the combination and ignores any others held at the same time, so
    # a two-key binding also fires on ctrl+shift+l and ctrl+alt+l. Ctrl+L is the
    # browser address bar, clear-terminal, and VS Code select-line — every one of
    # those presses was silently opening a listening turn.
    push_to_talk: typing.Optional[str] = "<ctrl>+<alt>+w"


class WakeWordSettings(BaseModel):
    enabled: bool = False
    phrase: str = "hey jarvis"
    model_path: typing.Optional[str] = None
    threshold: float = 0.5


class VoiceSettings(BaseModel):
    tts_voice: str = "af_heart"
    speed: float = 1.0
    volume: float = 0.6
    model_path: str = "models/kokoro-v1.0.onnx"
    voices_path: str = "models/voices-v1.0.bin"
    input_device: typing.Optional[typing.Union[int, str]] = None
    output_device: typing.Optional[typing.Union[int, str]] = None
    stt: SttSettings = Field(default_factory=SttSettings)
    media_pause: MediaPauseSettings = Field(default_factory=MediaPauseSettings)
    conversation: ConversationSettings = Field(default_factory=ConversationSettings)
    barge_in: BargeInSettings = Field(default_factory=BargeInSettings)
    wake_word: WakeWordSettings = Field(default_factory=WakeWordSettings)
    hotkeys: HotkeySettings = Field(default_factory=HotkeySettings)


class HistorySettings(BaseModel):
    max_turns: int = 5


class AiSettings(BaseModel):
    provider: typing.Optional[str] = None
    anthropic_model: typing.Optional[str] = None
    gemini_model: typing.Optional[str] = None
    ollama_model: str = "llama3.1"
    # Reasoning policy: "on" (default) thinks only on direct knowledge
    # questions, never on tool-dispatch steps (keeps voice latency low);
    # "off" disables thinking everywhere.
    thinking: str = "on"
    history: HistorySettings = Field(default_factory=HistorySettings)


class TraySettings(BaseModel):
    notify_on_ready: bool = True
    open_browser_on_start: bool = False


class LoggingSettings(BaseModel):
    keep_days: int = 14


class ModelsSettings(BaseModel):
    # False: load Whisper/Kokoro lazily on first wake instead of at startup,
    # so idle tray holds only the tiny always-on wake-word model.
    preload: bool = False


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class HomeAssistantSettings(BaseModel):
    # homeassistant.local is the standard mDNS hostname a stock install answers on.
    base_url: str = "http://homeassistant.local:8123"
    allow_locks: bool = False


class WeatherSettings(BaseModel):
    default_units: str = "metric"


class GmailSettings(BaseModel):
    allow_send: bool = False
    use_ai: bool = False


class CalendarSettings(BaseModel):
    work_start_hour: int = 9
    work_end_hour: int = 18
    allow_write: bool = False


class DesktopSettings(BaseModel):
    allow_actions: bool = False
    file_search_root: str = "~"


class ModulesSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    home_assistant: HomeAssistantSettings = Field(default_factory=HomeAssistantSettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)
    gmail: GmailSettings = Field(default_factory=GmailSettings)
    calendar: CalendarSettings = Field(default_factory=CalendarSettings)
    desktop: DesktopSettings = Field(default_factory=DesktopSettings)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WONY_",
        env_nested_delimiter="__",
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    # Set before instantiation to control which YAML file is loaded.
    _yaml_file: typing.ClassVar[typing.Optional[str]] = None

    assistant: AssistantSettings = Field(default_factory=AssistantSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    enabled_modules: list[str] = Field(
        default_factory=lambda: ["ai", "status", "basics", "weather", "spotify", "screen"]
    )
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    tray: TraySettings = Field(default_factory=TraySettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    models: ModelsSettings = Field(default_factory=ModelsSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if cls._yaml_file:
            sources.append(
                YamlConfigSettingsSource(settings_cls, yaml_file=cls._yaml_file, yaml_file_encoding="utf-8")
            )
        return tuple(sources)


def _resolve_yaml_path(path: str) -> typing.Optional[str]:
    """Locate the config file, anchoring relative names to the repo root.

    Resolving against the process CWD instead meant `wony.py text` started from
    another directory — and the tray, which Task Scheduler starts from wherever
    it likes — silently fell through to config.example.yaml and ran on defaults.
    """
    from helpers.paths import resolve as _repo_resolve

    for candidate in [path, "config.example.yaml"]:
        full = _repo_resolve(candidate)  # absolute paths pass through unchanged
        if os.path.exists(full):
            return full
    return None


class Config:
    _settings: typing.Optional[AppSettings] = None
    _loaded: bool = False

    @classmethod
    def load(cls, path: str = "config.yaml") -> None:
        AppSettings._yaml_file = _resolve_yaml_path(path)
        cls._settings = AppSettings()
        cls._loaded = True

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls._loaded:
            cls.load()

    @classmethod
    def get(cls, dotted_key: str, default: typing.Any = None) -> typing.Any:
        cls._ensure_loaded()
        assert cls._settings is not None
        keys = dotted_key.split(".")
        node: typing.Any = cls._settings
        for key in keys:
            val = getattr(node, key, _MISSING)
            if val is _MISSING:
                if isinstance(node, dict):
                    val = node.get(key, _MISSING)
                if val is _MISSING:
                    return default
            node = val
        if isinstance(node, BaseModel):
            return node.model_dump()
        return node

    @classmethod
    def enabled_modules(cls) -> typing.Set[str]:
        cls._ensure_loaded()
        assert cls._settings is not None
        mods = cls._settings.enabled_modules
        return set(mods) if isinstance(mods, list) else set()

    @classmethod
    def is_module_enabled(cls, module_name: str) -> bool:
        if module_name in ("ai", "status"):
            return True
        return module_name in cls.enabled_modules()

    @classmethod
    def module_settings(cls, module_name: str) -> typing.Dict:
        cls._ensure_loaded()
        assert cls._settings is not None
        mod = getattr(cls._settings.modules, module_name, None)
        if mod is None:
            return {}
        if isinstance(mod, BaseModel):
            return mod.model_dump()
        if isinstance(mod, dict):
            return mod
        return {}
