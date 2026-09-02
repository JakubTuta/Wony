#!/usr/bin/env python3
"""
Wony setup — the required, single-file installer.

    python setup.py

Sets the whole app up: picks/creates the Python environment, installs only the
dependencies for the features you choose, writes .env / config.yaml and the
required folders, and writes the completion marker that unlocks `wony.py`.

Re-run any time to add/remove modules: it reuses an existing venv, keeps your
.env and config.yaml, pre-marks what you already have, and SKIPS reinstalling
modules that are already set up — only the newly checked ones get installed.

Stdlib only. The feature menu is a scrollable arrow-key checklist (space to
toggle, enter to confirm); on a non-interactive terminal it falls back to a
numeric toggle prompt.
"""

import os
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

ALWAYS_ON = ["ai", "status", "basics"]


# key, label, requirement files, config module (None = run-mode/enhancement),
# default, description, external setup still needed.
FEATURES = [
    {
        "key": "kiosk",
        "label": "Kiosk — the touch screen UI and web API (recommended run mode)",
        "reqs": ["server.txt"],
        "module": None,
        "default": True,
        "desc": "Run Wony as a screen: tap tiles, type on the on-screen keyboard.",
        "needs": "Start with: python wony.py   (then open the URL it prints).",
    },
    {
        "key": "weather",
        "label": "Weather",
        "reqs": ["weather.txt"],
        "module": "weather",
        "default": True,
        "desc": "Current weather and forecasts.",
        "needs": "Add WEATHER_API_KEY to .env (free key: openweathermap.org/api).",
    },
    {
        "key": "web",
        "label": "Web search + URL fetch",
        "reqs": ["web.txt"],
        "module": "web",
        "default": True,
        "desc": "Search the web and read pages.",
        "needs": "Works out of the box (DuckDuckGo). Optional: TAVILY_API_KEY in .env.",
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
        "key": "spotify",
        "label": "Spotify playback control",
        "reqs": [],
        "module": "spotify",
        "default": False,
        "desc": "Play, pause, skip, search, set volume.",
        "needs": "developer.spotify.com app; SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET in .env; "
        "redirect URI http://127.0.0.1:8888/callback.",
    },
    {
        "key": "gmail",
        "label": "Gmail (read / search / monitor)",
        "reqs": ["gmail.txt"],
        "module": "gmail",
        "default": False,
        "desc": "Read, search and watch your inbox.",
        "needs": "Google OAuth: credentials/google_credentials.json. Sending stays off until you allow it on the settings screen.",
    },
    {
        "key": "calendar",
        "label": "Google Calendar",
        "reqs": ["calendar.txt"],
        "module": "calendar",
        "default": False,
        "desc": "Read events, check availability, find free slots.",
        "needs": "Google OAuth: credentials/google_credentials.json. Writing off until modules.calendar.allow_write: true.",
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
        "needs": "HOME_ASSISTANT_TOKEN in .env (profile → Security → Long-lived access "
        "tokens); set modules.home_assistant.base_url in config.yaml. Locks and the "
        "garage stay off until modules.home_assistant.allow_locks: true.",
    },
    {
        "key": "mcp",
        "label": "MCP client (external tool servers)",
        "reqs": ["mcp.txt"],
        "module": "mcp",
        "default": False,
        "desc": "Connect external Model Context Protocol tool servers.",
        "needs": "Configure servers in config.yaml under the mcp module.",
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
    "weather": "geocoder",
    "web": "duckduckgo_search",
    "scheduler": "apscheduler",
    "gmail": "simplegmail",
    "calendar": "googleapiclient",
    "mcp": "mcp",
    "semantic": "fastembed",
}


def c(text, code):
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def run_pip(args):
    cmd = [sys.executable, "-m", "pip", "install"] + args
    print(c("    $ " + " ".join(cmd[2:]), "90"))
    return subprocess.call(cmd)


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
    if os.path.exists(ENV_FILE):
        print(c("  . .env exists — keeping it.", "90"))
        return
    print(c("\n  AI provider (Wony needs one; you can edit .env later):", "1"))
    print(
        "    1) Anthropic (Claude)   2) Google Gemini   3) Ollama (local, no key)   4) Skip"
    )
    ai = input("  Choose [1/2/3/4] (default 1): ").strip()
    lines = ["# Wony secrets — never commit this file."]
    if ai == "2":
        lines.append(f'GEMINI_API_KEY="{input("  GEMINI_API_KEY: ").strip()}"')
    elif ai == "3":
        lines.append("# Ollama needs no key. Set ai.provider: ollama in config.yaml.")
    elif ai == "4":
        lines += ['# ANTHROPIC_API_KEY="sk-..."', '# GEMINI_API_KEY="..."']
    else:
        lines.append(f'ANTHROPIC_API_KEY="{input("  ANTHROPIC_API_KEY: ").strip()}"')
    lines += [
        "",
        "# Optional module keys (add as needed):",
        '# WEATHER_API_KEY="..."          # openweathermap.org/api',
        '# SPOTIFY_CLIENT_ID="..."',
        '# SPOTIFY_CLIENT_SECRET="..."',
        '# TAVILY_API_KEY="..."           # better web search (optional)',
        '# HOME_ASSISTANT_TOKEN="..."     # HA profile → Security → long-lived token',
    ]
    with open(ENV_FILE, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(c("  ✓ created .env", "32"))


def ensure_config():
    """Returns (ok, freshly_created). freshly_created is False when an
    existing config.yaml was left untouched — callers use it to gate
    one-time setup questions the same way ensure_env() only asks for an AI
    key when .env doesn't exist yet, so re-running setup never clobbers
    choices already made."""
    if os.path.exists(CONFIG):
        return True, False
    if not os.path.exists(CONFIG_EXAMPLE):
        print(c("  ! config.example.yaml missing — cannot create config.yaml.", "33"))
        return False, False
    with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as src, open(
        CONFIG, "w", encoding="utf-8"
    ) as dst:
        dst.write(src.read())
    print(c("  ✓ created config.yaml from config.example.yaml", "32"))
    return True, True


def write_config(updates):
    """Set dotted keys in config.yaml, keeping its comments.

    helpers/config_writer.py is the one implementation of this, shared with the
    settings screen; it is stdlib-only so it works here too, before any
    dependency has been installed.
    """
    sys.path.insert(0, ROOT)
    from helpers.config_writer import update as _update

    return _update(CONFIG, updates)


def apply_enabled_modules(chosen):
    ok, _ = ensure_config()
    if not ok:
        return
    wanted = list(ALWAYS_ON) + [f["module"] for f in chosen if f["module"]]
    with open(CONFIG, "r", encoding="utf-8") as fh:
        backup = fh.read()
    with open(CONFIG + ".bak", "w", encoding="utf-8") as bk:
        bk.write(backup)
    write_config({"enabled_modules": wanted})
    print(c(f"  ✓ enabled_modules = {', '.join(wanted)}", "32"))


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


def _dist_installed(name):
    import importlib.metadata

    try:
        importlib.metadata.version(name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False



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
            ok = importlib.util.find_spec(probe) is not None
        except Exception:
            ok = False
        if ok:
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
    print(c("  ✓ wrote .wony_setup — app unlocked.", "32"))


def next_steps(chosen, use_venv):
    print(c("\n  Done. Next steps", "1;36"))
    print("  " + "-" * 50)
    print(
        "  1. Ensure an AI key is in .env (or set ai.provider: ollama in config.yaml)."
    )
    notes = [(f["label"], f["needs"]) for f in chosen if f["needs"]]
    if notes:
        print("  2. Per-feature setup still required:")
        for label, need in notes:
            print(f"     • {c(label, '1')}: {need}")
    step = 3 if notes else 2
    # The touch UI is a built artifact, and skipping the build is silent: the
    # API answers fine and the display shows nothing at all.
    if any(f["key"] == "kiosk" for f in chosen) and not os.path.isfile(
        os.path.join(ROOT, "kiosk", "dist", "index.html")
    ):
        print(f"  {step}. Build the screen:  cd kiosk && npm install && npm run build")
        step += 1

    py = os.path.relpath(sys.executable, ROOT) if use_venv else "python"
    print(c(f"\n  {step}. Validate:  ", "1") + f"{py} wony.py doctor")
    run = (
        f"{py} wony.py"
        if any(f["key"] == "kiosk" for f in chosen)
        else f"{py} wony.py text"
    )
    print(c("     Start:     ", "1") + run)
    print(c("     At boot:   ", "1") + f"{py} wony.py autostart install")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────────


def main():
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
    _, config_fresh = ensure_config()

    selected, detected = detect()
    chosen = select_features(selected, detected)
    print(
        c("\n  Selected: ", "1")
        + (", ".join(f["label"] for f in chosen) or "core only")
    )
    if input("  Proceed? [Y/n] ").strip().lower() in ("n", "no"):
        print("  Aborted — no changes installed.")
        return

    install(chosen, detected)
    apply_enabled_modules(chosen)
    verify_install(chosen)
    write_marker(use_venv)
    next_steps(chosen, use_venv)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.stdout.write("\033[?25h")
        print("\n  Cancelled.")
        sys.exit(130)
