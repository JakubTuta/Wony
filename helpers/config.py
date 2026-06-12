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
    max_seconds: float = 12.0
    silence_ms: int = 700
    vad_aggressiveness: int = 2


class DuckingSettings(BaseModel):
    enabled: bool = True
    level: float = 0.15


class ConversationSettings(BaseModel):
    enabled: bool = True
    follow_up_timeout: float = 4.0


class BargeInSettings(BaseModel):
    enabled: bool = False
    sustain_frames: int = 15


class WakeWordSettings(BaseModel):
    enabled: bool = False
    phrase: str = "hey jarvis"
    model_path: typing.Optional[str] = None
    threshold: float = 0.5
    cooldown_seconds: float = 2.0
    vad_threshold: float = 0.5
    noise_suppression: bool = False


class VoiceSettings(BaseModel):
    enabled: bool = False
    tts_voice: str = "af_heart"
    speed: float = 1.0
    volume: float = 0.6
    model_path: str = "models/kokoro-v1.0.onnx"
    voices_path: str = "models/voices-v1.0.bin"
    tts_device: str = "auto"
    stt: SttSettings = Field(default_factory=SttSettings)
    ducking: DuckingSettings = Field(default_factory=DuckingSettings)
    conversation: ConversationSettings = Field(default_factory=ConversationSettings)
    barge_in: BargeInSettings = Field(default_factory=BargeInSettings)
    wake_word: WakeWordSettings = Field(default_factory=WakeWordSettings)


class HistorySettings(BaseModel):
    enabled: bool = True
    max_turns: int = 5


class AgentSettings(BaseModel):
    max_steps: int = 5


class AiSettings(BaseModel):
    provider: typing.Optional[str] = None
    anthropic_model: typing.Optional[str] = None
    gemini_model: typing.Optional[str] = None
    ollama_model: str = "llama3.1"
    max_tokens: int = 8192
    # Reasoning policy: "on" (default) thinks only on direct knowledge
    # questions, never on tool-dispatch steps (keeps voice latency low);
    # "off" disables thinking everywhere.
    thinking: str = "on"
    history: HistorySettings = Field(default_factory=HistorySettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)


class TraySettings(BaseModel):
    notify_on_ready: bool = True
    open_browser_on_start: bool = False


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class ShellySettings(BaseModel):
    base_url: str = "http://192.168.18.53"


class WeatherSettings(BaseModel):
    default_units: str = "metric"


class GmailSettings(BaseModel):
    poll_interval_minutes: int = 15
    max_results: int = 20
    max_body_chars: int = 1500
    allow_send: bool = False
    use_ai: bool = False
    ai_summary_max_emails: int = 30


class CalendarSettings(BaseModel):
    poll_interval_minutes: int = 15
    lookahead_hours: int = 24
    max_results: int = 10
    search_days_back: int = 30
    search_days_ahead: int = 90
    work_start_hour: int = 9
    work_end_hour: int = 18
    allow_write: bool = False


class WebSettings(BaseModel):
    max_content_chars: int = 3000


class DesktopSettings(BaseModel):
    allow_actions: bool = False
    file_search_root: str = "~"


class ModulesSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    shelly: ShellySettings = Field(default_factory=ShellySettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)
    gmail: GmailSettings = Field(default_factory=GmailSettings)
    calendar: CalendarSettings = Field(default_factory=CalendarSettings)
    web: WebSettings = Field(default_factory=WebSettings)
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
    for candidate in [path, "config.example.yaml"]:
        if os.path.exists(candidate):
            return candidate
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
