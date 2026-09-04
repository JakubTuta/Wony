"""The settings a user may change without opening a text editor.

config.yaml stays the source of truth and stays hand-editable; this is the list
of keys the web UI is allowed to show and write, with the label and help text
that make each one understandable to someone who has never read the code.

Anything absent from _FIELDS is deliberately not user-facing (see the Config
philosophy in CLAUDE.md) — tuning knobs live as constants next to their code.
"""
import os
import typing

from helpers import config_writer
from helpers.config import Config
from helpers.paths import repo_path

CONFIG_FILE = repo_path("config.yaml")

# Modules a user picks from, with what each one gives them. Order is the order
# they appear in the UI.
MODULES: typing.List[typing.Tuple[str, str, str]] = [
    ("basics", "Everyday basics", "Time, date, daily briefing, shut down the PC."),
    ("scheduler", "Timers & reminders", "Timers and alarms that survive a restart."),
    ("weather", "Weather", "Current conditions for here or any city."),
    ("web", "Web search", "Search the web and read pages."),
    ("spotify", "Spotify", "Play, pause, skip, search, volume."),
    ("gmail", "Gmail", "Read, search and watch your inbox."),
    ("calendar", "Google Calendar", "Events, availability and free slots."),
    ("google_accounts", "Google accounts", "Use more than one Google account."),
    ("home_assistant", "Home Assistant", "Lights, blinds, thermostats, vacuums, scenes."),
    ("desktop", "Desktop control", "Open apps, windows, clipboard, files."),
    ("screen", "Screen reading", "Screenshot the screen and read text on it."),
    ("shazam", "Song recognition", "Name the song that is playing."),
    ("league", "League of Legends", "Launch the game and auto-accept queue."),
    ("mcp", "MCP tool servers", "Connect external Model Context Protocol servers."),
]

# A field the UI renders. restart=True means the change only takes effect after
# Wony is restarted, and the UI says so rather than letting it look broken.
class Field(typing.NamedTuple):
    key: str
    label: str
    kind: str  # text | longtext | number | toggle | choice
    help: str = ""
    choices: typing.Tuple[str, ...] = ()
    minimum: typing.Optional[float] = None
    maximum: typing.Optional[float] = None
    step: typing.Optional[float] = None
    restart: bool = False
    module: str = ""  # only shown when this module is switched on


_FIELDS: typing.List[typing.Tuple[str, typing.List[Field]]] = [
    ("Assistant", [
        Field("assistant.name", "Name", "text", "What you call it."),
        Field("assistant.owner_name", "Your name", "text", "How it addresses you."),
        Field("assistant.personality", "Personality", "longtext",
              "Free text describing how it should talk to you."),
    ]),
    ("Voice", [
        Field("voice.tts_voice", "Voice", "choice",
              "Which voice speaks the replies.",
              choices=("af_heart", "af_sarah", "af_bella", "am_michael", "am_adam",
                       "bf_emma", "bf_isabella", "bm_george", "bm_lewis")),
        Field("voice.speed", "Speaking speed", "number", "1.0 is normal.",
              minimum=0.5, maximum=2.0, step=0.1),
        Field("voice.volume", "Speaking volume", "number", "0 is silent, 1 is loudest.",
              minimum=0.0, maximum=1.0, step=0.05),
        Field("voice.stt.silence_ms", "Pause before answering", "number",
              "Milliseconds of silence that end your sentence. Raise it if you get cut off.",
              minimum=200, maximum=3000, step=50),
        Field("voice.conversation.enabled", "Keep listening after a reply", "toggle",
              "Carry on a back-and-forth without repeating the wake word."),
        Field("voice.barge_in.enabled", "Let me interrupt", "toggle",
              "Talking over a reply stops it."),
        Field("voice.media_pause.enabled", "Pause my music while talking", "toggle",
              "Pauses Spotify, videos and other players, then resumes them."),
        Field("voice.hotkeys.push_to_talk", "Push-to-talk key", "text",
              'Key combination that starts listening, e.g. "<ctrl>+<alt>+w". '
              "Leave empty to switch it off.", restart=True),
    ]),
    ("Wake word", [
        Field("voice.wake_word.enabled", "Listen for a wake word", "toggle",
              "Start a conversation hands-free.", restart=True),
        Field("voice.wake_word.phrase", "Wake phrase", "choice",
              "Built-in phrases only. For your own phrase, run: python setup.py wakeword",
              choices=("hey jarvis", "alexa", "hey mycroft", "hey rhasspy"), restart=True),
        Field("voice.wake_word.threshold", "Wake sensitivity", "number",
              "Lower triggers more easily, and also more often by mistake.",
              minimum=0.1, maximum=0.9, step=0.05, restart=True),
    ]),
    ("AI", [
        Field("ai.provider", "AI provider", "choice",
              "Which service answers. Leave on auto to use whichever key is in .env.",
              choices=("auto", "anthropic", "gemini", "ollama"), restart=True),
        Field("ai.thinking", "Thinking", "choice",
              "'on' reasons harder on knowledge questions; 'off' is fastest.",
              choices=("on", "off")),
        Field("ai.history.max_turns", "Conversation memory", "number",
              "How many past exchanges it keeps in mind during a chat.",
              minimum=1, maximum=50, step=1),
    ]),
    ("What Wony may do on its own", [
        Field("modules.gmail.allow_write", "Send and delete email", "toggle",
              "Off: emails are saved as drafts for you to send yourself.",
              module="gmail"),
        Field("modules.calendar.allow_write", "Change my calendar", "toggle",
              "Off: it tells you what to add instead of adding it.",
              module="calendar"),
        Field("modules.home_assistant.allow_locks", "Unlock doors and open the garage", "toggle",
              "Off: lights and blinds still work, locks and alarms do not.",
              module="home_assistant"),
        Field("modules.desktop.allow_actions", "Type and click for me", "toggle",
              "Off: it can look at the screen but not act on it.",
              module="desktop"),
        Field("modules.gmail.use_ai", "Summarise email with AI", "toggle",
              "Sends the text of your emails to your AI provider.", module="gmail"),
    ]),
    ("This computer", [
        Field("modules.home_assistant.base_url", "Home Assistant address", "text",
              "The same address you open in a browser.", module="home_assistant"),
        Field("modules.weather.default_units", "Units", "choice",
              "Celsius or Fahrenheit.", choices=("metric", "imperial"), module="weather"),
        Field("modules.calendar.work_start_hour", "Working day starts", "number",
              "Used when finding free time.", minimum=0, maximum=23, step=1, module="calendar"),
        Field("modules.calendar.work_end_hour", "Working day ends", "number",
              minimum=1, maximum=24, step=1, module="calendar"),
        Field("tray.notify_on_ready", "Say hello at startup", "toggle",
              "Show a notification when Wony finishes starting."),
        Field("tray.open_browser_on_start", "Open the web page at startup", "toggle"),
        Field("models.preload", "Load speech models at startup", "toggle",
              "Faster first reply, but holds memory the whole time Wony runs.",
              restart=True),
        Field("server.port", "Web page port", "number",
              "Change only if something else already uses this port.",
              minimum=1024, maximum=65535, step=1, restart=True),
    ]),
]

_BY_KEY = {field.key: field for section in _FIELDS for field in section[1]}


def _current(field: Field) -> typing.Any:
    value = Config.get(field.key)
    if field.key == "ai.provider" and not value:
        return "auto"
    return value


def _choices_for(field: Field, value: typing.Any) -> typing.List[str]:
    """The offered choices, plus whatever is configured now.

    A hand-edited config (a custom wake word, say) must not vanish from the UI
    just because it is not one of the presets.
    """
    choices = list(field.choices)
    current = "" if value is None else str(value)
    if current and current not in choices:
        choices.append(current)
    return choices


def describe() -> typing.Dict[str, typing.Any]:
    """Everything the settings UI needs: the fields, their values, the modules."""
    enabled = Config.enabled_modules()
    sections = []
    for title, fields in _FIELDS:
        shown = [
            {
                "key": field.key,
                "label": field.label,
                "kind": field.kind,
                "help": field.help,
                "choices": _choices_for(field, _current(field)),
                "min": field.minimum,
                "max": field.maximum,
                "step": field.step,
                "restart": field.restart,
                "value": _current(field),
            }
            for field in fields
            if not field.module or field.module in enabled
        ]
        if shown:
            sections.append({"title": title, "fields": shown})

    return {
        "sections": sections,
        "modules": [
            {"key": key, "label": label, "help": help_text, "enabled": key in enabled}
            for key, label, help_text in MODULES
        ],
        "config_file": CONFIG_FILE,
    }


class SettingsError(Exception):
    """A value the UI sent cannot go into config.yaml."""


def _ensure_config_file() -> None:
    """Create config.yaml from the example if it is missing.

    Someone running on the shipped defaults has no config.yaml at all, and
    writing to a file that does not exist would report success and change
    nothing.
    """
    import shutil

    if os.path.exists(CONFIG_FILE):
        return
    example = repo_path("config.example.yaml")
    if not os.path.exists(example):
        raise SettingsError("config.example.yaml is missing, so config.yaml cannot be created.")
    shutil.copyfile(example, CONFIG_FILE)


def _coerce(field: Field, value: typing.Any) -> typing.Any:
    if field.kind == "toggle":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    if field.kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{field.label} needs to be a number.") from None
        if field.minimum is not None and number < field.minimum:
            raise SettingsError(f"{field.label} cannot be below {field.minimum:g}.")
        if field.maximum is not None and number > field.maximum:
            raise SettingsError(f"{field.label} cannot be above {field.maximum:g}.")
        if field.step is not None and float(field.step).is_integer() and field.step >= 1:
            return int(round(number))
        return round(number, 3)

    text = "" if value is None else str(value).strip()

    if field.kind == "choice":
        if text not in _choices_for(field, _current(field)):
            raise SettingsError(f"{field.label} must be one of: {', '.join(field.choices)}.")
        if field.key == "ai.provider" and text == "auto":
            return None
        return text

    if field.key == "voice.hotkeys.push_to_talk" and not text:
        return None
    return text


def apply(
    updates: typing.Dict[str, typing.Any],
    modules: typing.Optional[typing.List[str]] = None,
) -> typing.Dict[str, typing.Any]:
    """Write settings to config.yaml and reload them.

    Returns which keys changed and whether a restart is needed for them to take
    effect. Unknown keys are refused rather than written: this endpoint must not
    become a way to put arbitrary text into the config file.
    """
    to_write: typing.Dict[str, typing.Any] = {}
    restart = False

    for key, value in (updates or {}).items():
        field = _BY_KEY.get(key)
        if field is None:
            raise SettingsError(f"'{key}' is not a setting that can be changed here.")
        to_write[key] = _coerce(field, value)
        restart = restart or field.restart

    if modules is not None:
        known = {key for key, _, _ in MODULES}
        unknown = [name for name in modules if name not in known]
        if unknown:
            raise SettingsError(f"Unknown module(s): {', '.join(unknown)}.")
        # ai and status are always on; the registry treats them as such and the
        # app has nothing to say without them.
        to_write["enabled_modules"] = ["ai", "status"] + [
            key for key, _, _ in MODULES if key in set(modules)
        ]
        restart = True

    if not to_write:
        return {"written": [], "restart_required": False}

    _ensure_config_file()
    written = config_writer.update(CONFIG_FILE, to_write)
    Config.load()  # settings read through Config.get() take effect immediately
    return {"written": written, "restart_required": restart}
