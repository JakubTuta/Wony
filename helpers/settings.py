"""The settings a user may change without a keyboard and a text editor.

config.yaml stays the source of truth and stays hand-editable; this is the list
of keys the screen is allowed to show and write, with the label and help text
that make each one understandable to someone who has never read the code.

Anything absent from _FIELDS is deliberately not user-facing (see the Config
philosophy in CLAUDE.md) — tuning knobs live as constants next to their code.
"""
import os
import typing

from helpers import config_writer, lookup
from helpers.config import Config
from helpers.paths import repo_path

CONFIG_FILE = repo_path("config.yaml")

# Modules a user picks from, with what each one gives them. Order is the order
# they appear in the UI.
MODULES: typing.List[typing.Tuple[str, str, str]] = [
    ("basics", "Everyday basics", "Time, date, power off this device."),
    ("routines", "Routines", "Named sets of steps you run by name, like the morning briefing."),
    ("scheduler", "Timers & reminders", "Timers and alarms that survive a restart."),
    ("notes", "Lists", "Shopping and todo lists you can add to by asking."),
    ("weather", "Weather", "Now and the next few days, here or any city."),
    ("system", "Device health", "Disk space, memory, processor load and network."),
    ("spotify", "Spotify", "Play, pause, skip, search, volume."),
    ("gmail", "Gmail", "Read, search and watch your inbox."),
    ("calendar", "Google Calendar", "Events, availability and free slots."),
    ("google_accounts", "Google accounts", "Use more than one Google account."),
    ("home_assistant", "Home Assistant", "Lights, blinds, thermostats, vacuums, scenes."),
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
    # Something the user typed about themselves: the assistant is told whether
    # it is set, never what it says (see explain). The screen still shows it.
    private: bool = False


_FIELDS: typing.List[typing.Tuple[str, typing.List[Field]]] = [
    ("Assistant", [
        Field("assistant.name", "Name", "text", "What you call it."),
        Field("assistant.owner_name", "Your name", "text", "How it addresses you."),
        Field("assistant.personality", "Personality", "longtext",
              "How it should talk to you, in your own words. "
              "For example: dry humour, short answers."),
        Field("assistant.home_address", "Home address", "text",
              "Where this device is, for local weather. Optional — without it the "
              "internet connection decides, which is good to roughly the city.",
              private=True),
    ]),
    ("AI", [
        Field("ai.provider", "AI provider", "choice",
              "Which service answers. Leave on auto to use whichever key is in .env — "
              "Anthropic first, then Gemini. Claude and Gemini always use their fastest "
              "model. Claude isn't used to train Anthropic's models; Gemini's free tier "
              "is reviewed and used to train Google's, a paid key isn't; Ollama is a "
              "server you run yourself, so nothing goes to a cloud.",
              choices=("auto", "anthropic", "gemini", "ollama"), restart=True),
        Field("ai.ollama_model", "Ollama model", "text",
              "The model name you pulled, e.g. llama3.1. Only used with Ollama.",
              restart=True),
        Field("ai.history.max_turns", "Conversation memory", "number",
              "How many past exchanges it keeps in mind during a chat.",
              minimum=1, maximum=50, step=1),
    ]),
    ("What Wony may do on its own", [
        Field("modules.gmail.allow_write", "Change my mailbox", "toggle",
              "Send, reply, delete, and mark mail as read. "
              "Off: emails are saved as drafts for you to send yourself.",
              module="gmail"),
        Field("modules.calendar.allow_write", "Change my calendar", "toggle",
              "Off: it tells you what to add instead of adding it.",
              module="calendar"),
        Field("modules.home_assistant.allow_locks", "Unlock doors and open the garage", "toggle",
              "Off: lights and blinds still work, locks and alarms do not.",
              module="home_assistant"),
        Field("modules.basics.allow_power_off", "Power off this device", "toggle",
              "Off: it refuses to shut down or restart the Pi.",
              module="basics"),
        Field("assistant.proactive.enabled", "Speak up on its own", "toggle",
              "Off: Wony only answers. On: it can start a conversation about a "
              "full disk, the device running hot, a meeting about to start or "
              "important mail. Ask 'what do you watch for' to see the full list.",
              restart=True),
        Field("assistant.memory.learn_from_my_data", "Learn about me on its own", "toggle",
              "Off: Wony remembers only what you tell it to remember. On: it reads "
              "back your own conversations, and your sent mail if Gmail is on, to "
              "save facts about you and how you write. Ask 'what do you know about "
              "me' to see and correct them.",
              restart=True),
    ]),
    ("This device", [
        Field("modules.home_assistant.base_url", "Home Assistant address", "text",
              "The same address you open in a browser.", module="home_assistant"),
        Field("modules.calendar.work_start_hour", "Working day starts", "number",
              "Used when finding free time.", minimum=0, maximum=23, step=1, module="calendar"),
        Field("modules.calendar.work_end_hour", "Working day ends", "number",
              minimum=1, maximum=24, step=1, module="calendar"),
        Field("kiosk.idle_minutes", "Go to the clock after", "number",
              "Minutes of nobody touching the screen before it shows the clock.",
              minimum=1, maximum=240, step=1),
        Field("kiosk.home_columns", "Home screen columns", "choice",
              "How many tiles fit across the Home tab.", choices=("3", "4")),
        Field("kiosk.confirm_all_devices", "Ask before every device", "toggle",
              "Off: tapping a light, blind, thermostat or vacuum on the panel "
              "runs it right away. On: every device asks first, same as a lock."),
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

    A hand-edited config must not vanish from the UI just because it is not one
    of the presets.
    """
    choices = list(field.choices)
    current = "" if value is None else str(value)
    if current and current not in choices:
        choices.append(current)
    return choices


def where(key: str) -> str:
    """Where a setting sits on the Settings screen, in the screen's own words, for
    a message that sends the user there — a renamed label cannot leave it stale."""
    for title, fields in _FIELDS:
        for field in fields:
            if field.key == key:
                return f"'{field.label}' under Settings → {title}"
    raise SettingsError(f"'{key}' is not a setting that can be changed here.")


# A broad keyword must not put the whole screen into the prompt.
_MAX_EXPLAINED = 8
_MAX_VALUE_CHARS = 200


def _say(field: Field, value: typing.Any) -> str:
    if field.private:
        return "set" if value else "not set"
    if field.kind == "toggle":
        return "on" if value else "off"
    if value is None or value == "":
        return "empty"
    return str(value)[:_MAX_VALUE_CHARS]


def _allowed(field: Field, value: typing.Any) -> str:
    if field.kind == "choice":
        return ", ".join(_choices_for(field, value))
    if field.kind == "number" and field.minimum is not None and field.maximum is not None:
        return f"{field.minimum:g} to {field.maximum:g}"
    return ""


def _feature_state(key: str, enabled: typing.Set[str]) -> str:
    """Whether a feature works and, if not, what it is waiting for."""
    from helpers.registry import ModuleStatus, ServiceRegistry
    from helpers.requirements import evaluate

    state, reason = ServiceRegistry.get_module_status().get(key, ("", ""))
    if key in enabled:
        if state == ModuleStatus.ENABLED:
            return "on and working."
        if state in ("", ModuleStatus.DISABLED):
            return "switched on, but not running yet: it starts after Wony restarts."
        hint = ServiceRegistry.get_module_hints().get(key, "")
        return f"on but not working: {reason or state}. {hint}".strip()
    requirement = ServiceRegistry.get_module_requirements().get(key)
    if requirement is None:
        return "off."
    ready, missing = evaluate(requirement)
    if ready:
        return "off. Everything it needs is already here."
    return f"off. It still needs: {missing}. {requirement.setup_hint}".strip()


def _setting_line(title: str, field: Field, enabled: typing.Set[str]) -> str:
    value = _current(field)
    parts = [f"- {field.label}: now {_say(field, value)}."]
    allowed = _allowed(field, value)
    if allowed:
        parts.append(f"It can be: {allowed}.")
    if field.help:
        parts.append(field.help if field.help.endswith((".", "!", "?")) else field.help + ".")
    parts.append(f"Under Settings → {title}.")
    parts.append("Needs a restart of Wony to apply." if field.restart else "Applies right away.")
    if field.module and field.module not in enabled:
        label = next((label for key, label, _ in MODULES if key == field.module), field.module)
        parts.append(f"Only shown once {label} is switched on.")
    return " ".join(parts)


def explain(words: typing.List[str]) -> str:
    """The features and settings that match the keywords, as the assistant should
    relay them: what each is now, what it can be, where to change it.

    A private value is only ever reported as set or not set. Empty when nothing
    matches.
    """
    enabled = Config.enabled_modules()
    pairs = [(title, field) for title, section in _FIELDS for field in section]
    features = [
        MODULES[index] for index in lookup.rank(
            words, [(f"{key} {text}".lower(), label.lower()) for key, label, text in MODULES]
        )
    ]
    fields = [
        pairs[index] for index in lookup.rank(
            words, [(f"{title} {field.key} {field.help}".lower(), field.label.lower()) for title, field in pairs]
        )
    ]

    lines: typing.List[str] = []
    if features:
        lines.append("Features:")
        lines += [
            f"- {label}: {text} It is {_feature_state(key, enabled)}"
            for key, label, text in features[:_MAX_EXPLAINED]
        ]
    if fields:
        lines.append("Settings:")
        lines += [_setting_line(title, field, enabled) for title, field in fields[:_MAX_EXPLAINED]]
        if len(fields) > _MAX_EXPLAINED:
            lines.append(f"({len(fields) - _MAX_EXPLAINED} more match: ask about one by name.)")
    if lines:
        lines.append(
            "Features and settings are both changed on the Settings screen (the cog in "
            "the top bar). I cannot change either myself."
        )
    return "\n".join(lines)


def overview() -> str:
    """Every setting and feature by name, for a question that names none."""
    enabled = Config.enabled_modules()
    lines = ["Settings, by section of the Settings screen:"]
    for title, fields in _FIELDS:
        shown = [field.label for field in fields if not field.module or field.module in enabled]
        if shown:
            lines.append(f"- {title}: {', '.join(shown)}")
    lines.append(
        "Features: "
        + ", ".join(f"{label} ({'on' if key in enabled else 'off'})" for key, label, _ in MODULES)
    )
    return "\n".join(lines)


def _describe_field(field: Field) -> typing.Dict[str, typing.Any]:
    value = _current(field)
    return {
        "key": field.key,
        "label": field.label,
        "kind": field.kind,
        "help": field.help,
        "choices": _choices_for(field, value),
        "min": field.minimum,
        "max": field.maximum,
        "step": field.step,
        "restart": field.restart,
        "value": value,
    }


def describe_field(key: str) -> typing.Dict[str, typing.Any]:
    """One field as the screen gets it, so setup.py can ask about a setting in the
    screen's own words instead of keeping a second copy of them."""
    field = _BY_KEY.get(key)
    if field is None:
        raise SettingsError(f"'{key}' is not a setting that can be changed here.")
    return _describe_field(field)


def describe() -> typing.Dict[str, typing.Any]:
    """Everything the settings screen needs: the fields, their values, the modules."""
    enabled = Config.enabled_modules()
    sections = []
    for title, fields in _FIELDS:
        shown = [
            _describe_field(field)
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
        # Home screen columns is a choice of numbers and must stay one in the file.
        return int(text) if text.isdigit() else text

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
        # Always-on modules are not written: the registry treats them as on
        # whatever the file says, and listing them reads like a choice.
        to_write["enabled_modules"] = [key for key, _, _ in MODULES if key in set(modules)]
        restart = True

    if not to_write:
        return {"written": [], "restart_required": False}

    _ensure_config_file()
    written = config_writer.update(CONFIG_FILE, to_write)
    Config.load()  # settings read through Config.get() take effect immediately
    return {"written": written, "restart_required": restart}
