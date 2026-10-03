#!/usr/bin/env python3
"""
Wony setup — the required, single-file installer.

    python setup.py

Sets the whole app up and leaves it working: picks/creates the Python
environment, installs only the dependencies for the features you choose,
writes .env / config.yaml and the required folders, builds the touch screen UI
with npm, then asks for every API key, credentials file and permission those
features need — checking each key against the service and running the Spotify
and Google sign-ins right here.

Re-run any time to add/remove modules: it reuses an existing venv, keeps your
.env and config.yaml, pre-marks what you already have, and SKIPS reinstalling
modules that are already set up — only the newly checked ones get installed.

    python setup.py configure

Just the keys-and-sign-ins part, for finishing a service you skipped or
signing in again later. Nothing is installed.

The installer itself is stdlib only; the configure step runs after the install
and may use what it put there (the app's own config reader, the Spotify and
Google sign-in paths). The feature menu is a scrollable arrow-key checklist
(space to toggle, enter to confirm); on a non-interactive terminal it falls
back to a numeric toggle prompt.
"""

import io
import os
import re
import subprocess
import sys

if sys.version_info < (3, 10):
    print(
        "\nWony requires Python 3.10 or newer — you are running %s.\n"
        "Install a newer Python from https://www.python.org/downloads/ and re-run:\n\n"
        "    python setup.py\n" % sys.version.split()[0]
    )
    sys.exit(1)

# Legacy Windows consoles crash on ✓/❯ glyphs — force UTF-8 + enable ANSI.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _enable_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes

        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        k.GetConsoleMode(h, ctypes.byref(mode))
        k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


_enable_ansi()

ROOT = os.path.dirname(os.path.abspath(__file__))
REQ = os.path.join(ROOT, "requirements")
CONFIG = os.path.join(ROOT, "config.yaml")
CONFIG_EXAMPLE = os.path.join(ROOT, "config.example.yaml")
ENV_FILE = os.path.join(ROOT, ".env")
MARKER = os.path.join(ROOT, ".wony_setup")
VENV_DIR = os.path.join(ROOT, "venv")
CREDENTIALS = os.path.join(ROOT, "credentials")
GOOGLE_CREDENTIALS = os.path.join(CREDENTIALS, "google_credentials.json")
KIOSK = os.path.join(ROOT, "kiosk")
KIOSK_INDEX = os.path.join(KIOSK, "dist", "index.html")

# The modules setup always installs. "ai", "status" and "employer" are always-on
# in the app itself (helpers/config.ALWAYS_ON) and are not written into
# enabled_modules; "basics" is a real choice that everyone gets by default.
ALWAYS_ON = ["basics"]


# key, label, requirement files, config module (None = run-mode/enhancement),
# default, description, external setup still needed.
FEATURES = [
    {
        "key": "kiosk",
        "label": "Kiosk — the touch screen UI and web API (recommended run mode)",
        "reqs": ["server.txt"],
        "module": None,
        "default": True,
        "desc": "Run Wony as a wall panel: tap tiles, devices and routines — touch only, no keyboard.",
        "needs": "Node.js 20.19+ — setup builds the screen for you. "
        "Start with: python wony.py   (then open the URL it prints).",
    },
    {
        "key": "weather",
        "label": "Weather",
        "reqs": ["weather.txt"],
        "module": "weather",
        "default": True,
        "desc": "Current weather and forecasts.",
        "needs": "A free API key from openweathermap.org/api — setup asks for it.",
    },
    {
        "key": "scheduler",
        "label": "Timers, alarms & reminders",
        # Its deps ship in core.txt — every install needs a working timer.
        "reqs": ["core.txt"],
        "module": "scheduler",
        "default": True,
        "desc": "Timers and alarms that survive restarts, and can run another job when they fire.",
        "needs": "",
    },
    {
        "key": "system",
        "label": "Computer health (battery, disk, memory)",
        "reqs": ["system.txt"],
        "module": "system",
        "default": False,
        "desc": "Report battery level, free disk space, memory and network status.",
        "needs": "",
    },
    {
        "key": "notes",
        # Stored in wony.db next to everything else — nothing to install.
        "reqs": [],
        "label": "Shopping & todo lists",
        "module": "notes",
        "default": True,
        "desc": "Keep written lists by asking: add an item, read one back, tick it off.",
        "needs": "",
    },
    {
        "key": "routines",
        # Stored in wony.db, and made of other modules' jobs — nothing to install.
        "reqs": [],
        "label": "Routines & morning briefing",
        "module": "routines",
        "default": True,
        "desc": "Named sets of steps you run by name. Ships with a briefing you can rewrite.",
        "needs": "",
    },
    {
        "key": "spotify",
        "label": "Spotify playback control",
        "reqs": [],
        "module": "spotify",
        "default": False,
        "desc": "Play, pause, skip, search, set volume.",
        "needs": "An app at developer.spotify.com/dashboard — setup asks for its ID and "
        "secret, then signs you in.",
    },
    {
        "key": "gmail",
        "label": "Gmail (read / search / monitor)",
        "reqs": ["google.txt"],
        "module": "gmail",
        "default": False,
        "desc": "Read, search and watch your inbox.",
        "needs": "A Google OAuth client file (Google Cloud Console) — setup asks for it and "
        "signs you in. Sending stays off until you allow it.",
    },
    {
        "key": "calendar",
        "label": "Google Calendar",
        "reqs": ["google.txt"],
        "module": "calendar",
        "default": False,
        "desc": "Read events, check availability, find free slots.",
        "needs": "The same Google OAuth client file as Gmail — setup asks for it and signs "
        "you in. Writing stays off until you allow it.",
    },
    {
        "key": "google_accounts",
        "label": "Google account manager",
        "reqs": [],
        "module": "google_accounts",
        "default": False,
        "desc": "Add, sign in to and switch Google accounts from the screen.",
        "needs": "Builds on Gmail/Calendar — enable one of those too.",
    },
    {
        "key": "home_assistant",
        "label": "Home Assistant (whole-house control)",
        "reqs": [],
        "module": "home_assistant",
        "default": False,
        "desc": "Control lights, blinds, thermostats, locks, scenes and scripts.",
        "needs": "A long-lived access token from your Home Assistant profile → Security — "
        "setup asks for it and for the address. Locks and the garage stay off "
        "until you allow them.",
    },
    {
        "key": "semantic",
        "label": "Semantic memory (RAG recall)",
        "reqs": ["semantic.txt"],
        "module": None,
        "default": False,
        "desc": "Smarter long-term memory recall using embeddings (fastembed).",
        "needs": "",
    },
]

# Representative import per feature — used to detect what's already installed.
PROBE = {
    "kiosk": "uvicorn",
    "scheduler": "apscheduler",
    "gmail": "googleapiclient",
    "calendar": "googleapiclient",
    "semantic": "fastembed",
    "system": "psutil",
}


def c(text, code):
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def run_pip(args):
    cmd = [sys.executable, "-m", "pip", "install"] + args
    print(c("    $ " + " ".join(cmd[2:]), "90"))
    return subprocess.call(cmd)


# ── Talking to the person running this ────────────────────────────────────────


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def section(title):
    print(c(f"\n  {title}", "1;36"))
    print("  " + "-" * 50)


def ok(message):
    print(c(f"  ✓ {message}", "32"))


def warn(message):
    print(c(f"  ! {message}", "33"))


def note(message):
    print(c(f"  . {message}", "90"))


def ask(question, default=""):
    answer = input(f"  {question}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def confirm(question, default=True):
    answer = input(f"  {question} {'[Y/n]' if default else '[y/N]'} ").strip().lower()
    return default if not answer else answer in ("y", "yes")


def choose(question, options, default=1):
    """One-of-N menu. `options` are (label, value) pairs; returns the value."""
    print(c("\n  " + question, "1"))
    for number, (label, _) in enumerate(options, 1):
        print(f"    {number}) {label}")
    raw = input(f"  Choose [1-{len(options)}] (default {default}): ").strip()
    picked = int(raw) if raw.isdigit() and 1 <= int(raw) <= len(options) else default
    return options[picked - 1][1]


def mask(secret):
    """Enough of a saved secret to recognise, not enough to read out."""
    return "•" * len(secret) if len(secret) <= 8 else secret[:4] + "…" + secret[-4:]


# ── Detection ─────────────────────────────────────────────────────────────────


def read_enabled_modules():
    if not os.path.exists(CONFIG):
        return set()
    names, in_block = set(), False
    with open(CONFIG, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.rstrip("\n").startswith("enabled_modules:"):
                in_block = True
                continue
            if in_block:
                s = line.rstrip("\n")
                if s.strip().startswith("- "):
                    names.add(s.strip()[2:].split("#")[0].strip())
                elif s.strip() == "" or s.startswith(("#", "  ", "\t")):
                    continue
                else:
                    break
    return names


def detect():
    """Return (selected, detected). detected = genuinely present (module enabled
    in config OR package importable). selected = detected OR recommended default."""
    import importlib.util

    enabled = read_enabled_modules()
    selected, detected = {}, set()
    for f in FEATURES:
        present = bool(f["module"] and f["module"] in enabled)
        probe = PROBE.get(f["key"])
        if probe and not present:
            try:
                present = importlib.util.find_spec(probe) is not None
            except Exception:
                present = False
        if present:
            detected.add(f["key"])
        selected[f["key"]] = present or f["default"]
    return selected, detected


def core_installed():
    import importlib.util

    return all(importlib.util.find_spec(m) for m in ("anthropic", "yaml", "dotenv"))


# ── Interactive checklist (arrow keys) ──────────────────────────────────────────


def _read_key():
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
        if ch == "\r":
            return "enter"
        if ch == " ":
            return "space"
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x1b":
            return "esc"
        return ch.lower()
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            return {"[A": "up", "[B": "down"}.get(seq, "esc")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == " ":
            return "space"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def select_features(selected, detected):
    """nuxt-style checklist. Returns the chosen feature dicts."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _select_numeric(selected, detected)

    keys = [f["key"] for f in FEATURES]
    cur = 0
    lines_drawn = 0

    def render():
        nonlocal lines_drawn
        if lines_drawn:
            sys.stdout.write(f"\033[{lines_drawn}A\033[0J")  # up + clear down
        buf = []
        buf.append(
            c("  Select features  ", "1;36")
            + c("(↑/↓ move · space toggle · a/n all/none · enter confirm)", "90")
        )
        buf.append(c(f"  Always installed: {', '.join(ALWAYS_ON)}", "90"))
        for i, f in enumerate(FEATURES):
            cursor = c("❯", "36") if i == cur else " "
            box = c("[x]", "32") if selected[f["key"]] else "[ ]"
            tick = c(" ✓", "32") if f["key"] in detected else ""
            label = c(f["label"], "1") if i == cur else f["label"]
            buf.append(f"  {cursor} {box} {label}{tick}")
        f = FEATURES[cur]
        buf.append("")
        buf.append(c("  " + f["desc"], "90"))
        buf.append(
            c("  needs: " + f["needs"], "90") if f["needs"] else c("  needs: —", "90")
        )
        out = "\n".join(buf)
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
        lines_drawn = out.count("\n") + 1

    sys.stdout.write("\033[?25l")  # hide cursor
    try:
        while True:
            render()
            k = _read_key()
            if k == "up":
                cur = (cur - 1) % len(keys)
            elif k == "down":
                cur = (cur + 1) % len(keys)
            elif k == "space":
                selected[keys[cur]] = not selected[keys[cur]]
            elif k == "a":
                selected = {kk: True for kk in selected}
            elif k == "n":
                selected = {kk: False for kk in selected}
            elif k == "enter":
                break
            elif k == "esc":
                raise KeyboardInterrupt
    finally:
        sys.stdout.write("\033[?25h")  # show cursor
        sys.stdout.flush()

    return _finalize(selected)


def _select_numeric(selected, detected):
    while True:
        print(
            c(
                "\n  Select features (toggle by number, 'a' all, 'n' none, Enter to confirm)",
                "1",
            )
        )
        print(c(f"  Always installed: {', '.join(ALWAYS_ON)}", "90"))
        for i, f in enumerate(FEATURES, 1):
            box = c("[x]", "32") if selected[f["key"]] else "[ ]"
            tick = c(" ✓", "32") if f["key"] in detected else ""
            print(f"  {i:>2}. {box} {f['label']}{tick}")
        raw = input("  > ").strip().lower()
        if raw == "":
            break
        if raw == "a":
            selected = {k: True for k in selected}
            continue
        if raw == "n":
            selected = {k: False for k in selected}
            continue
        for tok in raw.replace(" ", "").split(","):
            if tok.isdigit() and 1 <= int(tok) <= len(FEATURES):
                key = FEATURES[int(tok) - 1]["key"]
                selected[key] = not selected[key]
    return _finalize(selected)


def _finalize(selected):
    keys = {k for k, v in selected.items() if v}
    return [f for f in FEATURES if f["key"] in keys]


# ── Environment (venv vs global) ────────────────────────────────────────────────


def choose_env():
    """Return (target_python, use_venv). Creates the venv if requested."""
    venv_py = (
        os.path.join(VENV_DIR, "Scripts", "python.exe")
        if os.name == "nt"
        else os.path.join(VENV_DIR, "bin", "python")
    )

    if os.path.exists(venv_py):
        print(c("  Found existing project venv (./venv) — using it.", "32"))
        return venv_py, True

    print(c("\n  Where should packages install?", "1"))
    print("    1) Project virtual env  ./venv   (recommended — isolated)")
    print("    2) Global Python                 (shared with your system)")
    choice = input("  Choose [1/2] (default 1): ").strip()
    if choice == "2":
        return sys.executable, False

    print("  Creating virtual env at ./venv ...")
    if subprocess.call([sys.executable, "-m", "venv", VENV_DIR]) != 0:
        print(c("  ✗ venv creation failed — falling back to global.", "31"))
        return sys.executable, False
    return venv_py, True


# ── File scaffolding ────────────────────────────────────────────────────────────


def ensure_dirs():
    for d in ("credentials", "logs"):
        p = os.path.join(ROOT, d)
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            print(c(f"  ✓ created {d}/", "32"))


def ensure_env():
    """Create .env if it is missing. What goes in it is asked later, once the
    packages needed to check each key are installed."""
    if os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, "w", encoding="utf-8") as fh:
        fh.write("# Wony secrets — never commit this file.\n")
    ok("created .env")


def ensure_config():
    """Create config.yaml from the example. Returns whether one exists now."""
    if os.path.exists(CONFIG):
        return True
    if not os.path.exists(CONFIG_EXAMPLE):
        warn("config.example.yaml missing — cannot create config.yaml.")
        return False
    with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as src, open(
        CONFIG, "w", encoding="utf-8"
    ) as dst:
        dst.write(src.read())
    ok("created config.yaml from config.example.yaml")
    return True


def repo_on_path():
    """Make the repo importable, so setup can call the app's own code."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)


def write_config(updates):
    """Set dotted keys in config.yaml, keeping its comments.

    helpers/config_writer.py is the one implementation of this, shared with the
    settings screen; it is stdlib-only so it works here too, before any
    dependency has been installed.
    """
    repo_on_path()
    from helpers.config_writer import update as _update

    return _update(CONFIG, updates)


def config_value(dotted_key, default=None):
    """What config.yaml says now, read through the app's own config loader.
    Falls back to `default` before the install has put PyYAML there."""
    try:
        repo_on_path()
        from helpers.config import Config

        Config.load()
        return Config.get(dotted_key, default)
    except Exception:
        return default


def env_values():
    """Every KEY=value pair currently in .env."""
    values = {}
    if not os.path.exists(ENV_FILE):
        return values
    with open(ENV_FILE, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, raw = stripped.partition("=")
            values[key.strip()] = raw.strip().strip("\"'")
    return values


def env_set(updates):
    """Write keys into .env, keeping the rest of the file as the user left it.

    A key that is only there as a commented placeholder is replaced in place,
    so the file stays in the order its comments describe.
    """
    lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8-sig") as fh:
            lines = fh.readlines()

    for key, value in updates.items():
        rendered = f'{key}="{value}"\n'
        pattern = re.compile(r"^\s*#?\s*" + re.escape(key) + r"\s*=")
        for index, line in enumerate(lines):
            if pattern.match(line):
                lines[index] = rendered
                break
        else:
            lines.append(rendered)
        # The sign-in steps below read the keys back out of the environment.
        os.environ[key] = value

    with open(ENV_FILE, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)


# ── Connect: keys, sign-ins and the permissions that need an answer ───────────


def http_request(url, headers=None, payload=None, form=None, timeout=15):
    """(status, body) for one HTTP call.

    A call that never got an answer is status 0. Every caller here asks "what
    did the service say about this key", and an exception is not an answer.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    data = None
    headers = dict(headers or {})
    if payload is not None:
        import json

        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    try:
        request = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception:
        # A mistyped address is as much of a "no answer" as a dead server, and
        # it must not end the setup run.
        return 0, ""


def keep_existing(variable, current):
    """True when there is a saved value and the user wants to keep it."""
    if not current:
        return False
    print(f"  {variable} is already set ({mask(current)}).")
    return not confirm("Replace it?", default=False)


def ask_secret(label, variable, current):
    """Ask for a secret, offering the saved one without printing it back."""
    if keep_existing(variable, current):
        return current
    return ask(f"{label} (Enter to skip)")


def ask_key(variable, where, current, check, rejected_note=""):
    """Ask for one API key and check it against the service before saving it.

    Returns the key to use, or "" when the user skipped. A key the service
    rejects is never saved silently — the user decides what to do about it.
    """
    if keep_existing(variable, current):
        return current
    note(f"Get one at {where}")
    while True:
        key = ask(f"{variable} (Enter to skip)")
        if not key:
            return ""
        status = check(key)
        if status == 200:
            ok("Checked — the key works.")
            return key
        if status == 0:
            warn("Could not reach the service — saving the key unchecked.")
            return key
        warn(f"The service rejected this key (HTTP {status}).")
        if rejected_note:
            note(rejected_note)
        answer = choose(
            "What now?",
            [
                ("Type it again", "retry"),
                ("Save it anyway", "keep"),
                ("Skip for now", "skip"),
            ],
        )
        if answer == "keep":
            return key
        if answer == "skip":
            return ""


def gate(question, key):
    """Ask about one safety gate. It ships off; the answer is written either
    way, so answering "no" on a re-run turns a gate back off."""
    write_config({key: confirm(question, default=bool(config_value(key, False)))})


def configure(chosen):
    """Ask for every key, file and permission the chosen features need, and
    finish what can be finished here. Returns what is still missing."""
    keys = {f["key"] for f in chosen}
    pending = []

    section("Connecting your services")
    if not interactive():
        note("This terminal cannot ask questions — no keys or sign-ins were set up.")
        return ["Keys and sign-ins: run 'python setup.py configure' in a terminal."]

    note("Press Enter to skip any question.")
    note("Run 'python setup.py configure' to come back to this at any time.")

    env = env_values()
    step_assistant()
    step_ai(env, pending)
    if "weather" in keys:
        step_weather(env, pending)
    if "spotify" in keys:
        step_spotify(env, pending)
    if keys & {"gmail", "calendar"}:
        step_google(keys, pending)
    if "home_assistant" in keys:
        step_home_assistant(env, pending)
    if "kiosk" in keys:
        step_autostart()
    return pending


def step_assistant():
    section("About you")
    write_config(
        {
            "assistant.name": ask(
                "What should the assistant be called?",
                config_value("assistant.name", "Wony"),
            ),
            "assistant.owner_name": ask(
                "What should it call you?", config_value("assistant.owner_name", "User")
            ),
        }
    )


# ── AI provider ───────────────────────────────────────────────────────────────

_OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"


def check_anthropic(key):
    return http_request(
        "https://api.anthropic.com/v1/models",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )[0]


def check_gemini(key):
    return http_request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"x-goog-api-key": key},
    )[0]


_AI_PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", "console.anthropic.com/settings/keys", check_anthropic),
    "gemini": ("GEMINI_API_KEY", "aistudio.google.com/apikey", check_gemini),
}


def step_ai(env, pending):
    section("AI provider — Wony cannot answer anything without one")
    provider = choose(
        "Which service should answer?",
        [
            ("Anthropic (Claude) — paid, best answers, not used to train their models", "anthropic"),
            ("Google Gemini — free tier reviewed and used to train Google's models; a paid key isn't", "gemini"),
            ("Ollama — a server you run yourself, no key, nothing goes to a cloud", "ollama"),
            ("Decide later", ""),
        ],
        default=_ai_default(env),
    )
    if not provider:
        pending.append("AI provider: none chosen — Wony cannot answer until one is set.")
        return
    if provider == "ollama":
        _setup_ollama(pending)
        return

    variable, where, check = _AI_PROVIDERS[provider]
    key = ask_key(variable, where, env.get(variable, ""), check)
    if not key:
        pending.append(f"AI provider: no {variable} yet ({where}).")
        return
    env_set({variable: key})
    write_config({"ai.provider": provider})
    ok(f"{provider} will answer for Wony.")


def _ai_default(env):
    """Pre-select what this machine already looks set up for."""
    provider = config_value("ai.provider") or (
        "gemini" if env.get("GEMINI_API_KEY") else ""
    )
    return {"anthropic": 1, "gemini": 2, "ollama": 3}.get(provider, 1)


def _ollama_models():
    """Model names Ollama holds locally, or None when it is not running."""
    import json

    status, body = http_request(_OLLAMA_TAGS, timeout=5)
    if status != 200:
        return None
    try:
        return [model.get("name", "") for model in json.loads(body).get("models", [])]
    except ValueError:
        return []


def _setup_ollama(pending):
    models = _ollama_models()
    if models is None:
        warn("Ollama is not answering on this machine.")
        note("A Pi is slow at this — a server on the network is the usual answer.")
        pending.append("Ollama: not running — start it, then: ollama pull llama3.1")
    elif not models:
        warn("Ollama is running but has no models downloaded.")
        pending.append("Ollama: no model downloaded — run: ollama pull llama3.1")

    if models:
        model = choose(
            "Which model should Wony use?", [(name, name) for name in models]
        )
    else:
        model = ask(
            "Model to use once you have pulled it",
            config_value("ai.ollama_model", "llama3.1"),
        )
    write_config({"ai.provider": "ollama", "ai.ollama_model": model})
    ok(f"Ollama will answer with {model}.")


# ── Weather and web search ────────────────────────────────────────────────────


def check_weather(key):
    return http_request(
        f"https://api.openweathermap.org/data/2.5/weather?q=London&appid={key}"
    )[0]


def step_weather(env, pending):
    section("Weather")
    key = ask_key(
        "WEATHER_API_KEY",
        "openweathermap.org/api — free, on the 'API keys' tab",
        env.get("WEATHER_API_KEY", ""),
        check_weather,
        rejected_note="A brand-new OpenWeather key can take up to two hours to start working.",
    )
    if key:
        env_set({"WEATHER_API_KEY": key})
    else:
        pending.append("Weather: no WEATHER_API_KEY yet (openweathermap.org/api).")
    note("Units follow the device's region. Say \"remember I prefer Fahrenheit\" to change them.")
    write_config({"assistant.home_address": ask(
        "Where is this device, for local weather? (Enter to let Wony guess)",
        config_value("assistant.home_address", ""),
    )})


# ── Spotify ───────────────────────────────────────────────────────────────────

# Must match modules/spotify.py — Spotify only redirects to an address the app
# was registered with, and this is the one the code listens on.
_SPOTIFY_REDIRECT = "http://127.0.0.1:8888/callback"


def check_spotify(client_id, secret):
    """Ask Spotify whether these two values are a real app, before the browser
    step turns a typo into an error page nobody can read."""
    import base64

    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return http_request(
        "https://accounts.spotify.com/api/token",
        {"Authorization": f"Basic {basic}"},
        form={"grant_type": "client_credentials"},
    )[0]


def step_spotify(env, pending):
    section("Spotify")
    print("  1. Open developer.spotify.com/dashboard and create an app.")
    print(f"  2. Set its Redirect URI to exactly:  {_SPOTIFY_REDIRECT}")
    print("  3. Tick 'Web API', save, then copy both values from the app's settings.")

    client_id = ask_secret("Client ID", "SPOTIFY_CLIENT_ID", env.get("SPOTIFY_CLIENT_ID", ""))
    secret = ask_secret(
        "Client secret", "SPOTIFY_CLIENT_SECRET", env.get("SPOTIFY_CLIENT_SECRET", "")
    )
    if not (client_id and secret):
        pending.append("Spotify: no client ID and secret yet (developer.spotify.com/dashboard).")
        return

    status = check_spotify(client_id, secret)
    if status not in (200, 0):
        warn(f"Spotify rejected those values (HTTP {status}).")
        if not confirm("Save them anyway?", default=False):
            pending.append("Spotify: the client ID and secret were rejected.")
            return
    env_set({"SPOTIFY_CLIENT_ID": client_id, "SPOTIFY_CLIENT_SECRET": secret})

    if not confirm("Sign in to Spotify now? This opens your browser.", default=True):
        pending.append("Spotify: not signed in — run 'python setup.py configure'.")
        return
    _spotify_sign_in(pending)


def _spotify_sign_in(pending):
    """Run the app's own OAuth flow: building the service is what opens the
    browser and caches the tokens Wony uses later."""
    repo_on_path()
    try:
        from modules.spotify import Spotify

        Spotify()
        ok("Spotify signed in.")
    except Exception as e:
        warn(f"Spotify sign-in did not finish: {e}")
        pending.append("Spotify: sign-in unfinished — run 'python setup.py configure'.")


# ── Google (Gmail and Calendar) ───────────────────────────────────────────────

_GOOGLE_SIGN_IN_NOTES = (
    "Google will say it 'hasn't verified this app'. It is your own app: click",
    "Advanced, then continue. Because it stays in Testing, Google signs Wony out",
    "every 7 days — the screen tells you, and signing in again is one tap.",
)

_GOOGLE_STEPS = (
    "1. Open console.cloud.google.com and pick (or create) a project.",
    "2. APIs & Services → Library: enable 'Gmail API' and 'Google Calendar API'.",
    "3. OAuth consent screen: choose 'External', leave it in Testing, and add your",
    "   own Google address under Test users.",
    "4. Credentials → Create credentials → OAuth client ID → Desktop app → Download JSON.",
)


def step_google(keys, pending):
    section("Google — Gmail and Calendar")
    if not os.path.exists(GOOGLE_CREDENTIALS) and not _install_google_credentials():
        pending.append("Google: credentials/google_credentials.json is still missing.")
        return

    wants = keys & {"gmail", "calendar"}
    # Before signing in: the switches decide what Google is asked for, and
    # switching one on afterwards would mean a second consent screen.
    if "gmail" in wants:
        gate(
            "May Wony send and delete email? (off: it saves drafts for you)",
            "modules.gmail.allow_write",
        )
    if "calendar" in wants:
        gate(
            "May Wony create, change and delete calendar events?",
            "modules.calendar.allow_write",
        )

    for line in _GOOGLE_SIGN_IN_NOTES:
        note(line)
    if confirm("Sign in to your Google account now? This opens a browser.", default=True):
        _google_sign_in(pending)
    else:
        pending.append("Google: not signed in — run 'python setup.py configure'.")


def _install_google_credentials():
    """Put the downloaded OAuth client file where the app looks for it."""
    import shutil

    for line in _GOOGLE_STEPS:
        print("  " + line)

    found = _downloaded_google_json()
    source = found if found and confirm(f"Use {found}?", default=True) else ""
    while not source:
        source = ask("Path to the downloaded JSON (Enter to skip)").strip("\"'")
        if not source:
            return False
        if not os.path.isfile(source):
            warn(f"There is no file at {source}.")
            source = ""

    problem = _google_json_problem(source)
    if problem:
        warn(problem)
        return False

    os.makedirs(CREDENTIALS, exist_ok=True)
    shutil.copyfile(source, GOOGLE_CREDENTIALS)
    ok("saved credentials/google_credentials.json")
    return True


def _downloaded_google_json():
    """Newest OAuth client file sitting where a browser would have put it."""
    import glob

    folders = (os.path.join(os.path.expanduser("~"), "Downloads"), os.getcwd(), ROOT)
    found = []
    for folder in folders:
        for pattern in ("client_secret*.json", "*credentials*.json"):
            found += glob.glob(os.path.join(folder, pattern))
    found = [p for p in found if os.path.abspath(p) != GOOGLE_CREDENTIALS]
    return max(found, key=os.path.getmtime) if found else ""


def _google_json_problem(path):
    """Why this file cannot serve as the OAuth client, or "" when it can."""
    import json

    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except Exception as e:
        return f"That file is not readable JSON: {e}"
    if "installed" in data:
        return ""
    if "web" in data:
        return "That is a Web application client. Create it again as a 'Desktop app'."
    return "That JSON is not a Google OAuth client file."


def _google_sign_in(pending):
    """One consent for Gmail and Calendar, through the same call the
    'authorize' job and the Sign in again button make."""
    repo_on_path()
    try:
        from helpers import google_auth
        from helpers.accounts import GoogleAccounts
        from helpers.config import Config

        Config.load()  # the switches just answered decide what is asked for
        name = GoogleAccounts.get_primary() or GoogleAccounts.add_account("primary")
        email = google_auth.sign_in(name)
    except Exception as e:
        warn(f"Google sign-in did not finish: {e}")
        pending.append(f"Google: sign-in failed — {e}")
        return
    ok(f"Signed in as {email}." if email else "Signed in to Google.")


# ── Home Assistant and starting at boot ───────────────────────────────────────


def check_home_assistant(base_url, token):
    return http_request(
        base_url.rstrip("/") + "/api/", {"Authorization": f"Bearer {token}"}
    )[0]


def step_home_assistant(env, pending):
    section("Home Assistant")
    base_url = ask(
        "Address you open Home Assistant at",
        config_value("modules.home_assistant.base_url", "http://homeassistant.local:8123"),
    )
    # People type what they see in the address bar, which drops the scheme.
    if base_url and "://" not in base_url:
        base_url = "http://" + base_url
    write_config({"modules.home_assistant.base_url": base_url})

    token = ask_key(
        "HOME_ASSISTANT_TOKEN",
        "your Home Assistant profile → Security → Long-lived access tokens",
        env.get("HOME_ASSISTANT_TOKEN", ""),
        lambda key: check_home_assistant(base_url, key),
    )
    if token:
        env_set({"HOME_ASSISTANT_TOKEN": token})
    else:
        pending.append("Home Assistant: no access token yet.")
    gate(
        "May Wony unlock doors, open the garage and disarm alarms?",
        "modules.home_assistant.allow_locks",
    )


def step_autostart():
    """A screen on a wall has nobody to start it — offer the systemd units that
    bring Wony and the browser up at boot."""
    section("Starting at boot")
    if not confirm("Start Wony and the screen automatically at boot?", default=False):
        return
    command = [sys.executable, os.path.join(ROOT, "wony.py"), "autostart", "install"]
    if subprocess.call(command) != 0:
        warn("The boot units were not installed — 'python wony.py' still starts Wony.")


def prune_config():
    """Remove keys this version of Wony no longer reads from config.yaml.

    Left in place they look like working settings and do nothing. The old file
    is kept as config.yaml.bak.
    """
    if not os.path.exists(CONFIG):
        return
    try:
        repo_on_path()
        import yaml

        from helpers.config import dead_keys
        from helpers.config_writer import remove

        with io.open(CONFIG, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
        raw = yaml.safe_load(text) or {}
    except Exception as e:
        warn(f"Could not check config.yaml for old settings: {e}")
        return
    dead = dead_keys(raw)
    if not dead:
        return
    _carry_over_port(raw)
    with io.open(CONFIG + ".bak", "w", encoding="utf-8") as bk:
        bk.write(text)
    removed = remove(CONFIG, dead)
    ok(f"removed old settings from config.yaml: {', '.join(removed)} (backup: config.yaml.bak)")


def _carry_over_port(raw):
    """server.port is now picked automatically — keep the one the user had, so
    their bookmark still works."""
    port = (raw.get("server") or {}).get("port")
    if not isinstance(port, int):
        return
    try:
        from helpers.memory_db import get_kv, set_kv

        if not get_kv("web.port", ""):
            set_kv("web.port", str(port))
    except Exception:
        pass


def apply_enabled_modules(chosen):
    if not ensure_config():
        return
    wanted = list(ALWAYS_ON) + [f["module"] for f in chosen if f["module"]]
    with open(CONFIG, "r", encoding="utf-8") as fh:
        backup = fh.read()
    with open(CONFIG + ".bak", "w", encoding="utf-8") as bk:
        bk.write(backup)
    write_config({"enabled_modules": wanted})
    ok(f"enabled_modules = {', '.join(wanted)}")


# ── The touch UI (a built artifact, not a Python package) ─────────────────────

# Vite refuses to run below this, and the Node in Raspberry Pi OS is often older.
NODE_MIN = "Node 20.19+ (or 22.12+)"
NODE_INSTALL = (
    "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - "
    "&& sudo apt install -y nodejs"
)
BUILD_BY_HAND = "cd kiosk && npm install && npm run build"


def _npm():
    """Path to npm, or "" when Node is not installed."""
    import shutil

    return shutil.which("npm") or ""


def _node_too_old():
    """The version string when node is present but too old to build with,
    otherwise "" (which also covers "cannot tell")."""
    try:
        version = subprocess.check_output(
            ["node", "--version"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""
    match = re.match(r"v(\d+)\.(\d+)", version)
    if not match:
        return ""
    major, minor = int(match.group(1)), int(match.group(2))
    # Vite's own range: ^20.19 || >=22.12.
    supported = major > 22 or (major == 22 and minor >= 12) or (major == 20 and minor >= 19)
    return "" if supported else version


def _kiosk_built() -> bool:
    """True when kiosk/dist/index.html exists *and* has content.

    Existence alone is not enough: a build killed partway through (an OOM on a
    Pi is the usual way) leaves a zero-byte index.html behind. That file passes
    an isfile() check, so setup calls the build done and skips it forever after,
    while the server happily serves `200 OK` with an empty body — a blank screen
    and a curl that prints nothing, with no error anywhere to explain it.
    """
    try:
        return os.path.getsize(KIOSK_INDEX) > 0
    except OSError:
        return False


def build_kiosk(chosen):
    """Build the touch UI, and return what is still missing.

    This is the one gap the app cannot report itself: without kiosk/dist the
    API still answers every request, so the screen looks like a working server
    that has decided the home page does not exist ({"detail":"Not found"}).
    """
    if not any(f["key"] == "kiosk" for f in chosen):
        return []

    section("The touch screen UI")
    built = _kiosk_built()
    if built:
        note("Already built (kiosk/dist).")
        note("Rebuild it after every 'git pull' — the screen is not in the repo.")
        if not (interactive() and confirm("Rebuild it now?", default=False)):
            return []

    npm = _npm()
    if not npm:
        warn("Node.js is not installed — the screen cannot be built here.")
        note(f"Install {NODE_MIN}, then:  {BUILD_BY_HAND}")
        note(NODE_INSTALL)
        return (
            []
            if built
            else [f"Screen UI: not built — install Node.js, then: {BUILD_BY_HAND}"]
        )

    outdated = _node_too_old()
    if outdated:
        warn(f"Node {outdated} is older than the build needs ({NODE_MIN}).")
        note(f"Upgrade with:  {NODE_INSTALL}")

    note("This downloads the UI's packages — a few minutes on a Pi.")
    for step in (["install"], ["run", "build"]):
        print(c("    $ npm " + " ".join(step), "90"))
        if subprocess.call([npm] + step, cwd=KIOSK) != 0:
            warn(f"'npm {' '.join(step)}' failed — the screen will not load.")
            note(
                "A Pi with little RAM usually runs out of memory here: add swap, or "
                "build on another machine and copy kiosk/dist across."
            )
            return [f"Screen UI: build failed — {BUILD_BY_HAND}"]

    if _kiosk_built():
        ok("built kiosk/dist — the screen has something to show.")
        return []
    if os.path.isfile(KIOSK_INDEX):
        warn("The build left kiosk/dist/index.html empty — the screen will be blank.")
        note(
            "That is what a build killed partway through looks like: add swap, or "
            "build on another machine and copy kiosk/dist across."
        )
        return [f"Screen UI: kiosk/dist/index.html is empty — {BUILD_BY_HAND}"]
    warn("The build finished but kiosk/dist/index.html is not there.")
    return [f"Screen UI: build produced no kiosk/dist/index.html — {BUILD_BY_HAND}"]


# ── Install ─────────────────────────────────────────────────────────────────────


def install(chosen, detected):
    if core_installed():
        print(c("  . core already installed — skipped.", "90"))
    else:
        print(c("\n  Installing core...", "1;36"))
        if run_pip(["-r", os.path.join(REQ, "core.txt")]) != 0:
            print(c("  ✗ core install failed — aborting.", "31"))
            sys.exit(1)

    new = [f for f in chosen if f["key"] not in detected]
    skipped = [f for f in chosen if f["key"] in detected]
    if skipped:
        print(
            c(
                f"  . skipping already-installed: {', '.join(f['key'] for f in skipped)}",
                "90",
            )
        )

    seen = set()
    for f in new:
        for rf in f["reqs"]:
            if rf in seen or not os.path.exists(os.path.join(REQ, rf)):
                continue
            seen.add(rf)
            print(c(f"\n  Installing {f['label']} ({rf})...", "1;36"))
            if run_pip(["-r", os.path.join(REQ, rf)]) != 0:
                print(c(f"  ✗ {rf} failed — continuing.", "31"))


def verify_install(chosen):
    """Probe each selected feature's key import and report what works."""
    import importlib
    import importlib.util

    importlib.invalidate_caches()
    print(c("\n  Verifying installed features", "1;36"))
    print("  " + "-" * 50)
    failures = []
    for f in chosen:
        probe = PROBE.get(f["key"])
        if not probe:
            print(f"  {c('✓', '32')} {f['label']} (no packages needed)")
            continue
        try:
            installed = importlib.util.find_spec(probe) is not None
        except Exception:
            installed = False
        if installed:
            print(f"  {c('✓', '32')} {f['label']}")
        else:
            failures.append(f)
            reqs = ", ".join(f["reqs"]) or "—"
            print(f"  {c('✗', '31')} {f['label']} — package '{probe}' missing.")
            print(
                c(
                    (
                        f"      fix: pip install -r requirements/{f['reqs'][0]}"
                        if f["reqs"]
                        else f"      fix: re-run python setup.py ({reqs})"
                    ),
                    "90",
                )
            )
    return failures


def write_marker(use_venv):
    import json

    data = {
        "completed": True,
        "python": sys.executable,
        "python_dir": os.path.dirname(os.path.abspath(sys.executable)),
        "venv": use_venv,
    }
    with open(MARKER, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    ok("wrote .wony_setup — app unlocked.")


def show_pending(pending):
    if not pending:
        return
    print(c("  Still to finish:", "1"))
    for item in pending:
        print(f"     • {item}")
    note("Come back to these with:  python setup.py configure")


def run_doctor():
    """The app's own checklist — one report covering every module, so setup
    never grows a second opinion about what is working."""
    subprocess.call([sys.executable, os.path.join(ROOT, "wony.py"), "doctor"])


def next_steps(chosen, use_venv, pending):
    section("Done")
    show_pending(pending)
    kiosk = any(f["key"] == "kiosk" for f in chosen)
    # The touch UI is a built artifact, and skipping the build is silent: the
    # API answers fine and the display shows nothing at all.
    if kiosk and not os.path.isfile(KIOSK_INDEX):
        print(c("\n  Build the screen: ", "1") + BUILD_BY_HAND)

    py = os.path.relpath(sys.executable, ROOT) if use_venv else "python"
    print(c("\n  Start Wony:  ", "1") + (f"{py} wony.py" if kiosk else f"{py} wony.py text"))
    print(c("  Check setup: ", "1") + f"{py} wony.py doctor")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────────


def cmd_configure():
    """Re-run only the keys and sign-ins, for a service added or skipped later.
    Nothing is installed, so it works on whatever is already set up here."""
    if not os.path.exists(CONFIG):
        warn("Nothing is installed yet — run 'python setup.py' first.")
        return
    ensure_env()
    prune_config()
    _, detected = detect()
    pending = configure([f for f in FEATURES if f["key"] in detected])
    # Nothing is installed here, so the screen is not built either — but it is
    # still the reason a finished-looking install shows nothing.
    if "kiosk" in detected and not os.path.isfile(KIOSK_INDEX):
        pending.append(f"Screen UI: not built — {BUILD_BY_HAND}")
    section("Done")
    show_pending(pending)
    print()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "configure":
        cmd_configure()
        return

    print(c("\n  Wony setup", "1;36"))
    print("  " + "-" * 50)
    print(f"  Python {sys.version.split()[0]}  ({sys.executable})")

    staged = "--staged" in sys.argv
    use_venv = "--venv=1" in sys.argv

    if not staged:
        target, use_venv = choose_env()
        if os.path.normcase(os.path.abspath(target)) != os.path.normcase(
            os.path.abspath(sys.executable)
        ):
            # Re-launch under the chosen interpreter and continue there.
            print(c(f"  → switching to {target}\n", "36"))
            os.execv(
                target,
                [
                    target,
                    os.path.abspath(__file__),
                    "--staged",
                    f"--venv={1 if use_venv else 0}",
                ],
            )

    print(c("\n  Upgrading pip...", "90"))
    subprocess.call(
        [sys.executable, "-m", "pip", "install", "--upgrade", "pip", "--quiet"]
    )

    ensure_dirs()
    ensure_env()
    ensure_config()

    selected, detected = detect()
    chosen = select_features(selected, detected)
    print(
        c("\n  Selected: ", "1")
        + (", ".join(f["label"] for f in chosen) or "core only")
    )
    if not confirm("Proceed?", default=True):
        print("  Aborted — no changes installed.")
        return

    install(chosen, detected)
    prune_config()
    apply_enabled_modules(chosen)
    verify_install(chosen)
    pending = build_kiosk(chosen)
    # Before the questions: the marker unlocks wony.py, which the boot-units
    # step runs, and the sign-in steps import what was just installed.
    write_marker(use_venv)
    pending += configure(chosen)
    print()
    if interactive() and confirm("Run the full setup check now?", default=True):
        run_doctor()
    next_steps(chosen, use_venv, pending)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        # EOFError: the questions below run for a while, and a terminal that
        # closes mid-answer should read as "cancelled", not as a crash.
        sys.stdout.write("\033[?25h")
        print("\n  Cancelled.")
        sys.exit(130)
