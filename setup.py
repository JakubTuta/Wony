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
    {"key": "voice", "label": "Voice I/O (speech recognition + text-to-speech)",
     "reqs": ["voice.txt"], "module": None, "default": False,
     "desc": "Talk to Wony and hear replies. Whisper STT + Kokoro TTS.",
     "needs": "Downloads ~hundreds of MB of models on first run. NVIDIA GPU auto-accelerated; CPU otherwise."},
    {"key": "wakeword", "label": "Wake word — hands-free 'hey jarvis'",
     "reqs": ["wakeword.txt"], "module": None, "default": False,
     "desc": "Start a conversation by voice with no key press.",
     "needs": "Requires Voice I/O. Set voice.wake_word.enabled: true in config.yaml."},
    {"key": "tray", "label": "System tray + web chat UI (recommended run mode)",
     "reqs": ["tray.txt", "server.txt"], "module": None, "default": True,
     "desc": "Run Wony in the background with a tray icon and a browser chat UI.",
     "needs": "Start with: python wony.py   (then open the web UI URL it prints)."},
    {"key": "weather", "label": "Weather", "reqs": ["weather.txt"],
     "module": "weather", "default": True,
     "desc": "Current weather and forecasts.",
     "needs": "Add WEATHER_API_KEY to .env (free key: openweathermap.org/api)."},
    {"key": "web", "label": "Web search + URL fetch", "reqs": ["web.txt"],
     "module": "web", "default": True,
     "desc": "Search the web and read pages.",
     "needs": "Works out of the box (DuckDuckGo). Optional: TAVILY_API_KEY in .env."},
    {"key": "scheduler", "label": "Reminders & recurring notifications",
     "reqs": ["scheduler.txt"], "module": "scheduler", "default": False,
     "desc": "Persistent reminders and scheduled tasks.", "needs": ""},
    {"key": "spotify", "label": "Spotify playback control", "reqs": [],
     "module": "spotify", "default": False,
     "desc": "Play, pause, skip, search, set volume.",
     "needs": "developer.spotify.com app; SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET in .env; "
              "redirect URI http://127.0.0.1:8888/callback."},
    {"key": "gmail", "label": "Gmail (read / search / monitor)", "reqs": ["gmail.txt"],
     "module": "gmail", "default": False,
     "desc": "Read, search and watch your inbox.",
     "needs": "Google OAuth: credentials/google_credentials.json. Sending off until modules.gmail.allow_send: true."},
    {"key": "calendar", "label": "Google Calendar", "reqs": ["calendar.txt"],
     "module": "calendar", "default": False,
     "desc": "Read events, check availability, find free slots.",
     "needs": "Google OAuth: credentials/google_credentials.json. Writing off until modules.calendar.allow_write: true."},
    {"key": "google_accounts", "label": "Multiple Google accounts", "reqs": [],
     "module": "google_accounts", "default": False,
     "desc": "Manage more than one Google account for Gmail/Calendar.",
     "needs": "Builds on Gmail/Calendar — enable one of those too."},
    {"key": "screen", "label": "Screen capture + OCR", "reqs": ["screen.txt"],
     "module": "screen", "default": False,
     "desc": "Screenshot the screen and extract text.",
     "needs": "easyocr downloads OCR models (~tens of MB) on first use."},
    {"key": "desktop", "label": "Desktop control (apps, windows, clipboard)",
     "reqs": ["desktop.txt"], "module": "desktop", "default": False,
     "desc": "Open apps, manage windows, read/write clipboard, open files.",
     "needs": "Actions off until modules.desktop.allow_actions: true."},
    {"key": "league", "label": "League of Legends stats", "reqs": ["automation.txt"],
     "module": "league", "default": False,
     "desc": "Player stats and match history.", "needs": ""},
    {"key": "shelly", "label": "Shelly smart-home control", "reqs": [],
     "module": "shelly", "default": False,
     "desc": "Control Shelly devices on your network.",
     "needs": "Set modules.shelly.base_url in config.yaml to your device IP."},
    {"key": "mcp", "label": "MCP client (external tool servers)", "reqs": ["mcp.txt"],
     "module": "mcp", "default": False,
     "desc": "Connect external Model Context Protocol tool servers.",
     "needs": "Configure servers in config.yaml under the mcp module."},
    {"key": "semantic", "label": "Semantic memory (RAG recall)", "reqs": ["semantic.txt"],
     "module": None, "default": False,
     "desc": "Smarter long-term memory recall using embeddings (fastembed).", "needs": ""},
    {"key": "shazam", "label": "Song recognition (Shazam)", "reqs": ["shazam.txt"],
     "module": None, "default": False,
     "desc": "Identify the song currently playing.", "needs": ""},
]

# Representative import per feature — used to detect what's already installed.
PROBE = {
    "voice": "kokoro_onnx", "wakeword": "openwakeword", "tray": "pystray",
    "weather": "geocoder", "web": "duckduckgo_search", "scheduler": "apscheduler",
    "gmail": "simplegmail", "calendar": "googleapiclient", "screen": "mss",
    "desktop": "pyautogui", "mcp": "mcp", "semantic": "fastembed", "shazam": "shazamio",
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
        buf.append(c("  Select features  ", "1;36")
                   + c("(↑/↓ move · space toggle · a/n all/none · enter confirm)", "90"))
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
        buf.append(c("  needs: " + f["needs"], "90") if f["needs"] else c("  needs: —", "90"))
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
        print(c("\n  Select features (toggle by number, 'a' all, 'n' none, Enter to confirm)", "1"))
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
    if "wakeword" in keys and "voice" not in keys:
        print(c("\n  ! Wake word needs Voice I/O — adding it too.", "33"))
        keys.add("voice")
    return [f for f in FEATURES if f["key"] in keys]


# ── Environment (venv vs global) ────────────────────────────────────────────────


def choose_env():
    """Return (target_python, use_venv). Creates the venv if requested."""
    venv_py = os.path.join(VENV_DIR, "Scripts", "python.exe") if os.name == "nt" \
        else os.path.join(VENV_DIR, "bin", "python")

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
    for d in ("credentials", "models", "logs"):
        p = os.path.join(ROOT, d)
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            print(c(f"  ✓ created {d}/", "32"))


def ensure_env():
    if os.path.exists(ENV_FILE):
        print(c("  . .env exists — keeping it.", "90"))
        return
    print(c("\n  AI provider (Wony needs one; you can edit .env later):", "1"))
    print("    1) Anthropic (Claude)   2) Google Gemini   3) Ollama (local, no key)   4) Skip")
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
    ]
    with open(ENV_FILE, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(c("  ✓ created .env", "32"))


def ensure_config():
    if os.path.exists(CONFIG):
        return True
    if not os.path.exists(CONFIG_EXAMPLE):
        print(c("  ! config.example.yaml missing — cannot create config.yaml.", "33"))
        return False
    with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as src, open(CONFIG, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    print(c("  ✓ created config.yaml from config.example.yaml", "32"))
    return True


def apply_enabled_modules(chosen):
    if not ensure_config():
        return
    wanted = list(ALWAYS_ON) + [f["module"] for f in chosen if f["module"]]
    with open(CONFIG, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    with open(CONFIG + ".bak", "w", encoding="utf-8") as bk:
        bk.writelines(lines)

    out, i, replaced = [], 0, False
    while i < len(lines):
        line = lines[i]
        if line.rstrip("\n").startswith("enabled_modules:") and not replaced:
            out.append("enabled_modules:\n")
            out.extend(f"  - {m}\n" for m in wanted)
            replaced = True
            i += 1
            while i < len(lines):
                s = lines[i]
                if s.strip() == "" or s.startswith(("  ", "\t", "#")):
                    i += 1
                    continue
                break
            continue
        out.append(line)
        i += 1
    if not replaced:
        out.append("\nenabled_modules:\n")
        out.extend(f"  - {m}\n" for m in wanted)
    with open(CONFIG, "w", encoding="utf-8") as fh:
        fh.writelines(out)
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
        print(c(f"  . skipping already-installed: {', '.join(f['key'] for f in skipped)}", "90"))

    seen = set()
    for f in new:
        for rf in f["reqs"]:
            if rf in seen or not os.path.exists(os.path.join(REQ, rf)):
                continue
            seen.add(rf)
            print(c(f"\n  Installing {f['label']} ({rf})...", "1;36"))
            if run_pip(["-r", os.path.join(REQ, rf)]) != 0:
                print(c(f"  ✗ {rf} failed — continuing.", "31"))

    _ensure_gpu_onnxruntime(chosen, new)

    # Download Kokoro model files then pre-render cached voice clips.
    if any(f["key"] == "voice" for f in new):
        for script in ("download_kokoro.py", "render_voice_clips.py"):
            path = os.path.join(ROOT, "scripts", script)
            if os.path.exists(path):
                print(c(f"\n  Running {script}...", "1;36"))
                subprocess.call([sys.executable, path])


def _dist_installed(name):
    import importlib.metadata
    try:
        importlib.metadata.version(name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def _has_nvidia_gpu():
    import shutil
    return shutil.which("nvidia-smi") is not None


def _ensure_gpu_onnxruntime(chosen, new):
    """Keep the GPU onnxruntime build when it makes sense; CPU everywhere else.

    Other feature requirements (wakeword, semantic, screen) pull the plain CPU
    `onnxruntime` package, which clobbers `onnxruntime-gpu`'s provider. When
    voice is selected on a CUDA machine, reinstall the GPU build whenever the
    CPU package has crept in. macOS has no CUDA build at all — never touch it.
    """
    if sys.platform == "darwin":
        return
    voice_selected = any(f["key"] == "voice" for f in chosen)
    if not voice_selected:
        return

    if not _has_nvidia_gpu():
        if any(f["key"] == "voice" for f in new):
            print(c("  . No NVIDIA GPU detected — voice will run on CPU "
                    "(fully supported, just slower).", "90"))
        return

    voice_new = any(f["key"] == "voice" for f in new)
    cpu_clobber = _dist_installed("onnxruntime") and _dist_installed("onnxruntime-gpu")
    if not voice_new and not cpu_clobber:
        return

    print(c("\n  Securing GPU onnxruntime build...", "1;36"))
    subprocess.call([sys.executable, "-m", "pip", "uninstall", "-y",
                     "onnxruntime", "onnxruntime-gpu"])
    if run_pip(["--no-deps", "onnxruntime-gpu"]) != 0:
        print(c("  ✗ onnxruntime-gpu install failed — falling back to CPU build.", "31"))
        run_pip(["onnxruntime"])


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
            print(c(f"      fix: pip install -r requirements/{f['reqs'][0]}" if f["reqs"]
                    else f"      fix: re-run python setup.py ({reqs})", "90"))
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
    print("  1. Ensure an AI key is in .env (or set ai.provider: ollama in config.yaml).")
    notes = [(f["label"], f["needs"]) for f in chosen if f["needs"]]
    if notes:
        print("  2. Per-feature setup still required:")
        for label, need in notes:
            print(f"     • {c(label, '1')}: {need}")
    py = os.path.relpath(sys.executable, ROOT) if use_venv else "python"
    print(c("\n  3. Validate:  ", "1") + f"{py} wony.py doctor")
    run = f"{py} wony.py" if any(f["key"] == "tray" for f in chosen) else f"{py} wony.py text"
    print(c("     Start:     ", "1") + run)
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
        if os.path.normcase(os.path.abspath(target)) != os.path.normcase(os.path.abspath(sys.executable)):
            # Re-launch under the chosen interpreter and continue there.
            print(c(f"  → switching to {target}\n", "36"))
            os.execv(target, [target, os.path.abspath(__file__), "--staged",
                              f"--venv={1 if use_venv else 0}"])

    print(c("\n  Upgrading pip...", "90"))
    subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "--quiet"])

    ensure_dirs()
    ensure_env()
    ensure_config()

    selected, detected = detect()
    chosen = select_features(selected, detected)
    print(c("\n  Selected: ", "1") + (", ".join(f["label"] for f in chosen) or "core only"))
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
