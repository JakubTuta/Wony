# F — Always-on Presence / Better UX (deferred)

Notes for a later iteration. Goal: escape CLI-only, let proactive reminders /
pollers reach the user without a focused terminal.

## 1. Always-on / autostart — no .exe required

Two separate problems: run without a terminal + start with Windows.

**Run without terminal**
- `pythonw.exe assistant.py` — pythonw = Python with no console window. venv already
  ships it. This alone removes the terminal window.
- PyInstaller `.exe` is **optional** — only for portability (machines without
  Python, single-file distribution). For personal use on own machine: skip it.
  Adds build complexity, larger artifact, slower startup.

**Start with Windows** (pick one)

| Method | Notes |
|---|---|
| Startup folder (`shell:startup` shortcut) | Simplest. Runs at login. |
| **Task Scheduler** ⭐ | Best. Run at login/boot, hidden, auto-restart on crash. |
| Registry `HKCU\...\Run` key | Same effect as startup folder. |

Recommended: **pythonw + Task Scheduler + pystray tray icon** = always-on, survives
crash, no terminal, no .exe. Tray icon makes "no window" usable (right-click menu:
pause / resume / quit / last briefing).

## 2. Escape CLI — surface options

Need *some* surface. Cheapest → richest:
- **Audio-only** — works, but needs wake-word or global hotkey to trigger with no
  window. Output via TTS + toasts. Discoverability poor (can't see capabilities).
- **Tray + toasts + hotkey-voice** ⭐ — minimal GUI, lightweight, sweet spot. No
  chat window, but visible + reachable.
- **Full GUI chat** — only if typed back-and-forth visible is wanted:
  - Web UI (FastAPI + browser) — easiest, cross-platform.
  - `pywebview` — lightweight native window wrapping a web UI.
  - `customtkinter` / PySide — native desktop window.

Recommend tray+toasts first; commit to a full GUI only if a chat window is actually
wanted.

## 3. Wake-word — cheaper than it seems

Instinct "constantly run whisper = too much" is **correct** — that's exactly why
dedicated wake-word engines exist.

How it works:
- A **tiny always-on model** (KB–few MB) processes mic audio in ~80ms frames,
  continuously.
- Does **one binary thing**: "heard the wake phrase — yes/no." Not transcribing
  speech. Cheap — ~single-digit % of one CPU core, no GPU.
- Only **after** the wake-word fires does heavy STT (whisper) spin up to transcribe
  the actual command.
- Audio processed frame-by-frame in RAM, discarded. On-device engines send nothing.

So the expensive part (whisper) runs only on demand; the cheap gate runs always.
Engines: **openWakeWord** (fully local/open) or **Porcupine/pvporcupine** (free
access key, custom "Hey Wony" phrase).

Verdict: not heavy, but real added complexity (false triggers, mic-always-on,
training a custom phrase). Current `ctrl+l` hotkey is zero-cost and fine at a desk.
Wake-word only wins for hands-free / across-the-room. **Defer or skip** — lowest
priority within F.

## Net plan for F (when tackled)
**pythonw + Task Scheduler + pystray + toasts** = always-on presence, minimal
effort, no .exe. GUI and wake-word are optional layers on top — add only if the
use-case demands.

Build pieces:
- `helpers/notify.py` — `notify(title, body)` via `win11toast` or `plyer`;
  scheduler + email/calendar pollers route through it. `requirements/notify.txt`.
- Tray app — `pystray` + `Pillow` (present): tray icon + menu; assistant loop runs
  in a background thread.
- Wake-word (optional) — `openwakeword` / `pvporcupine`, gated behind voice reqs.
