"""The settings a user may change without opening a text editor.

config.yaml stays the source of truth and stays hand-editable; this is the list
of keys the web UI is allowed to show and write, with the label and help text
that make each one understandable to someone who has never read the code.

Anything absent from _FIELDS is deliberately not user-facing (see the Config
philosophy in CLAUDE.md) — tuning knobs live as constants next to their code.
"""
import os
import typing

from helpers import config_writer, env_writer
from helpers.config import Config
from helpers.paths import repo_path

CONFIG_FILE = repo_path("config.yaml")
ENV_FILE = repo_path(".env")

# A field kind "secret" is never backed by config.yaml — Field.key is instead
# the name of an environment variable, written to .env. os.environ is the
# live source of truth for these, not Config.
_ACRONYMS = {"id", "api", "url", "ai"}


def _humanize_env_var(var: str) -> str:
    """SPOTIFY_CLIENT_ID -> "Spotify Client ID" — a plain label for a raw
    environment variable name, keeping well-known acronyms upper-case."""
    return " ".join(
        word.upper() if word in _ACRONYMS else word.capitalize()
        for word in var.lower().split("_")
    )

# Modules a user picks from, with what each one gives them. Order is the order
# they appear in the UI.
MODULES: typing.List[typing.Tuple[str, str, str]] = [
    ("basics", "Everyday basics", "Time, date, shut down the PC."),
    ("routines", "Routines", "Named sets of steps you run by name, like the morning briefing."),
    ("scheduler", "Timers & reminders", "Timers and alarms that survive a restart."),
    ("notes", "Lists", "Shopping and todo lists you add to by voice."),
    ("weather", "Weather", "Now and the next few days, here or any city."),
    ("maps", "Maps & places", "Places near you and how long it takes to get somewhere."),
    ("web", "Web search", "Search the web, read pages, and click through them to find things."),
    ("system", "Computer health", "Battery, disk space, memory and network."),
    ("spotify", "Spotify", "Play, pause, skip, search, volume."),
    ("gmail", "Gmail", "Read, search and watch your inbox."),
    ("calendar", "Google Calendar", "Events, availability and free slots."),
    ("drive", "Google Drive", "Find and read your Drive files; create and edit Docs and Sheets."),
    ("contacts", "Google Contacts", "Look people up, and email or invite them by name."),
    ("google_accounts", "Google accounts", "Use more than one Google account."),
    ("home_assistant", "Home Assistant", "Lights, blinds, thermostats, vacuums, scenes."),
    ("desktop", "Desktop control", "Open apps and windows, clipboard, read and write files."),
    ("screen", "Screen reading", "Screenshot the screen and read text on it."),
    ("shazam", "Song recognition", "Name the song that is playing."),
    ("league", "League of Legends", "Launch the game and auto-accept queue."),
    ("mcp", "MCP tool servers", "Connect external Model Context Protocol servers."),
]

# Always on, whatever config.yaml says (see ALWAYS_ON) — listed separately so
# the UI can show them without switches instead of hardcoding their names.
_ALWAYS_ON_MODULES: typing.List[typing.Tuple[str, str, str]] = [
    ("ai", "AI memory", "Remembers facts about you and searches past conversations."),
    ("status", "System status", "Reports what Wony can do and what is broken."),
    ("employer", "Conversation", "Runs your requests through the AI and the other jobs."),
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
        Field("assistant.home_address", "Home address", "text",
              "Used for 'near me' and local weather when Windows location is off. "
              "Optional."),
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
        Field("voice.conversation.follow_up_timeout", "How long to keep listening after a reply",
              "number", "Seconds of silence before Wony stops listening.",
              minimum=1, maximum=15, step=0.5),
        Field("voice.barge_in.enabled", "Let me interrupt", "toggle",
              "Talking over a reply stops it."),
        Field("voice.media_pause.enabled", "Pause my music while talking", "toggle",
              "Pauses Spotify, videos and other players, then resumes them."),
        Field("voice.hotkeys.push_to_talk", "Push-to-talk key", "text",
              'Key combination that starts listening, e.g. "<ctrl>+<alt>+w". '
              "Use three keys: a single key also starts listening every time you "
              "press it in any app. Leave empty to switch it off.", restart=True),
        Field("voice.input_device", "Microphone", "choice",
              "Which microphone Wony listens with.", restart=True),
        Field("voice.output_device", "Speakers", "choice",
              "Where Wony's voice plays.", restart=True),
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
              "Which service answers. Leave on auto to use whichever key is in .env — "
              "Anthropic first, then Gemini. Claude and Gemini always use their fastest "
              "model. Claude isn't used to train Anthropic's models; Gemini's free tier "
              "is reviewed and used to train Google's, a paid key isn't; Ollama runs on "
              "this computer and nothing leaves it.",
              choices=("anthropic", "gemini", "ollama"), restart=True),
        Field("ANTHROPIC_API_KEY", "Anthropic API key", "secret",
              "Used when the AI provider is Anthropic (Claude). Get one at "
              "console.anthropic.com.", restart=True),
        Field("GEMINI_API_KEY", "Gemini API key", "secret",
              "Used when the AI provider is Gemini. Get one at aistudio.google.com.",
              restart=True),
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
        Field("modules.calendar.allow_write", "Change my calendar and send invitations", "toggle",
              "Create, change and delete events, and email invitations to the people on "
              "them. Off: it tells you what to add instead of adding it.",
              module="calendar"),
        Field("modules.drive.allow_write", "Change my Drive files", "toggle",
              "Create Google Docs, add to Docs and Sheets, and upload files. "
              "Off: it can find and read your files only. Turning it on asks Google once more.",
              module="drive"),
        Field("modules.home_assistant.allow_locks", "Unlock doors and open the garage", "toggle",
              "Off: lights and blinds still work, locks and alarms do not.",
              module="home_assistant"),
        Field("modules.desktop.allow_actions", "Type and click for me", "toggle",
              "Off: it can look at the screen and read files, but not act on "
              "them — no typing, clicking, or writing files.",
              module="desktop"),
        Field("modules.mcp.allow_install", "Install MCP tool servers", "toggle",
              "Off: it tells you the command instead of running it. "
              "An MCP server is a program that runs on this computer.",
              module="mcp"),
        Field("assistant.proactive.enabled", "Speak up on its own", "toggle",
              "Off: Wony only answers. On: it can start a conversation about a "
              "low battery, a full disk, a meeting about to start or important "
              "mail. Ask 'what do you watch for' to see the full list.",
              restart=True),
        Field("assistant.memory.learn_from_my_data", "Learn about me on its own", "toggle",
              "Off: Wony remembers only what you tell it to remember. On: it reads "
              "back your own conversations, and your sent mail if Gmail is on, to "
              "save facts about you and how you write. Ask 'what do you know about "
              "me' to see and correct them.",
              restart=True),
        Field("modules.desktop.share_window_title", "Tell it what I'm looking at", "toggle",
              "Sends the title of the window in front to your AI provider with every "
              "message, so 'what does this mean' has something to point at. Window "
              "titles name documents, browser tabs and who you are chatting to.",
              module="desktop"),
    ]),
    ("This computer", [
        Field("modules.home_assistant.base_url", "Home Assistant address", "text",
              "The same address you open in a browser.", module="home_assistant"),
        Field("modules.maps.travel_mode", "How you usually get around", "choice",
              "Used when you ask how long it takes to get somewhere.",
              choices=("car", "public transport", "walking", "cycling"), module="maps"),
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
    ]),
]

def _dynamic_secret_fields() -> typing.List[Field]:
    """One secret Field per environment variable a switchable module declared
    as required, so its page can be fully set up without touching .env.

    Read from the registry rather than hand-listed here: every module already
    declares its own env_vars on its Requirement (see helpers/requirements.py),
    and duplicating that list here is exactly the kind of copy CLAUDE.md's
    "consolidate" rule warns against — it would drift the moment a module's
    requirement changed.
    """
    from helpers.registry import ServiceRegistry

    known_modules = {key for key, _, _ in MODULES}
    fields: typing.List[Field] = []
    seen: typing.Set[str] = set()
    for module_name, requires in ServiceRegistry.get_module_requirements().items():
        if module_name not in known_modules:
            continue
        for var in getattr(requires, "env_vars", None) or []:
            if var in seen:
                continue
            seen.add(var)
            fields.append(Field(
                key=var,
                label=_humanize_env_var(var),
                kind="secret",
                help=getattr(requires, "setup_hint", "") or f"Sets {var} in .env.",
                module=module_name,
                restart=True,
            ))
    return fields


# Keys a module works without but does better with. Requirements only declare
# what a module cannot run without, so these never reach _dynamic_secret_fields.
_OPTIONAL_SECRETS: typing.List[Field] = [
    Field("TAVILY_API_KEY", "Tavily API key", "secret",
          "Better web search results (free key at tavily.com). Search works without it.",
          module="web"),
    Field("GOOGLE_MAPS_API_KEY", "Google Maps API key", "secret",
          "Optional. Adds ratings, opening hours, live traffic and public transport. "
          "Needs a Google Cloud billing account; Wony stays inside Google's free "
          "monthly allowance and switches back to OpenStreetMap before it runs out.",
          module="maps"),
]


def _all_sections() -> typing.List[typing.Tuple[str, typing.List[Field]]]:
    dynamic = _dynamic_secret_fields()
    dynamic += [f for f in _OPTIONAL_SECRETS if f.key not in {d.key for d in dynamic}]
    return _FIELDS + [("Integration keys", dynamic)] if dynamic else _FIELDS


def secret_env_keys() -> typing.List[str]:
    """Every environment-variable key that holds a secret value (API keys,
    OAuth client secrets). Read by helpers/logger.py so a value never lands
    in a log file verbatim."""
    return [field.key for _, fields in _all_sections() for field in fields if field.kind == "secret"]


def _field_by_key(key: str) -> typing.Optional[Field]:
    for _, fields in _all_sections():
        for field in fields:
            if field.key == key:
                return field
    return None


# Choice fields where null in config.yaml means "decide for me", and the word
# the UI shows for it.
_NULL_CHOICE = {
    "ai.provider": "auto",
    "voice.input_device": "Windows default",
    "voice.output_device": "Windows default",
}


def _device_choices(kind: str) -> typing.Callable[[], typing.List[str]]:
    def names() -> typing.List[str]:
        try:
            from helpers.mic import device_names

            return device_names(kind)
        except Exception:
            return []  # no audio stack installed: only "Windows default" is offered
    return names


# Choices that depend on this machine, read when the page asks for them.
_DYNAMIC_CHOICES: typing.Dict[str, typing.Callable[[], typing.List[str]]] = {
    "voice.input_device": _device_choices("input"),
    "voice.output_device": _device_choices("output"),
}


def _current(field: Field) -> typing.Any:
    if field.kind == "secret":
        # Never hand the actual secret to the browser — only whether it's set.
        return bool(os.environ.get(field.key))
    value = Config.get(field.key)
    if field.key in _NULL_CHOICE and value is None:
        return _NULL_CHOICE[field.key]
    return value


def _choices_for(field: Field, value: typing.Any) -> typing.List[str]:
    """The offered choices, plus whatever is configured now.

    A hand-edited config (a custom wake word, say) must not vanish from the UI
    just because it is not one of the presets.
    """
    choices = list(field.choices)
    if field.key in _DYNAMIC_CHOICES:
        choices += _DYNAMIC_CHOICES[field.key]()
    if field.key in _NULL_CHOICE and _NULL_CHOICE[field.key] not in choices:
        choices.insert(0, _NULL_CHOICE[field.key])
    current = "" if value is None else str(value)
    if current and current not in choices:
        choices.append(current)
    return choices


def describe() -> typing.Dict[str, typing.Any]:
    """Everything the settings UI needs: the fields, their values, the modules."""
    enabled = Config.enabled_modules()
    sections = []
    for title, fields in _all_sections():
        shown = [
            {
                "key": field.key,
                "label": field.label,
                "kind": field.kind,
                "help": field.help,
                "choices": _choices_for(field, _current(field)) if field.kind == "choice" else [],
                "min": field.minimum,
                "max": field.maximum,
                "step": field.step,
                "restart": field.restart,
                "module": field.module,
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
            {"key": key, "label": label, "help": help_text, "enabled": key in enabled, "always_on": False}
            for key, label, help_text in MODULES
        ] + [
            {"key": key, "label": label, "help": help_text, "enabled": True, "always_on": True}
            for key, label, help_text in _ALWAYS_ON_MODULES
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


def _ensure_env_file() -> None:
    """Create .env if it is missing, same reasoning as _ensure_config_file."""
    if os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, "w", encoding="utf-8") as handle:
        handle.write("# Wony secrets — never commit this file.\n")


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
        choices = _choices_for(field, _current(field))
        if text not in choices:
            raise SettingsError(f"{field.label} must be one of: {', '.join(choices)}.")
        if text == _NULL_CHOICE.get(field.key):
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
    env_updates: typing.Dict[str, str] = {}
    restart = False

    for key, value in (updates or {}).items():
        field = _field_by_key(key)
        if field is None:
            raise SettingsError(f"'{key}' is not a setting that can be changed here.")
        coerced = _coerce(field, value)
        if field.kind == "secret":
            if not coerced:
                # Blank means "leave it as it is" — describe() never sends the
                # real value back, so an untouched field always looks blank.
                continue
            env_updates[field.key] = coerced
        else:
            to_write[key] = coerced
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

    written: typing.List[str] = []
    if to_write:
        _ensure_config_file()
        written += config_writer.update(CONFIG_FILE, to_write)
    if env_updates:
        _ensure_env_file()
        try:
            written += env_writer.update(ENV_FILE, env_updates)
        except ValueError as e:
            raise SettingsError(str(e)) from e
        for var, val in env_updates.items():
            # A module built its client from the old (missing) value once at
            # startup, so this alone isn't enough — restart_required below
            # still applies. Setting it now just means a later retry or
            # restart sees it without the user re-typing anything.
            os.environ[var] = val

    if not written:
        return {"written": [], "restart_required": False}

    Config.load()  # settings read through Config.get() take effect immediately
    return {"written": written, "restart_required": restart}
