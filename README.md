# Wony — Personal AI Assistant

A local personal assistant powered by AI that accepts text and voice commands. Modules load on demand — anything not configured is automatically skipped.

## Architecture

| File          | Role                                                                            |
| ------------- | ------------------------------------------------------------------------------- |
| `.env`        | **Secrets only** — API keys, client secrets. Never committed.                   |
| `config.yaml` | **Your choices** — assistant name, enabled modules, settings. Copy from `config.example.yaml`. |
| `cache.json`  | Machine-written runtime state (Spotify tokens, poll timestamps). Google OAuth tokens live in `credentials/`. |
| `wony.db`     | Conversation history, remembered facts, reminders, embeddings.                  |

Modules auto-register via decorators. If a module's env vars, credential files, or pip packages are missing it registers as `disabled` / `misconfigured` / `unavailable` — nothing crashes. The startup summary and `check setup` command tell you exactly what to fix.

## Setup (required)

**Run the setup script before anything else.** One file sets up the entire app —
creates the Python environment, installs dependencies, writes `.env` / `config.yaml`
and the required folders, lets you pick which feature modules to enable, and unlocks
the app. `python wony.py` refuses to start until setup has completed.

```powershell
python setup.py
```

The script will:
1. Ask whether to use a **project virtual env** (`./venv`, recommended) or your **global** Python — and create the venv for you.
2. Create `.env` (prompts for your AI provider key) and `config.yaml` if missing.
3. Show an **arrow-key checklist** of every feature module (↑/↓ to move, space to toggle, enter to confirm) — what it does and what it needs.
4. Install only the dependencies for what you chose (and guarantee GPU `onnxruntime` when voice is selected).

**Re-run it any time** to add/remove modules — it reuses your venv, keeps your
`.env` and `config.yaml`, pre-marks (`✓`) what you already have, and **skips
reinstalling** modules that are already set up (only newly checked ones install).

After setup, validate and start:

```powershell
# if you chose a venv (recommended):
.\venv\Scripts\python.exe wony.py doctor   # validate
.\venv\Scripts\python.exe wony.py          # start (tray + web UI)

# if you chose global Python:
python wony.py doctor
python wony.py
```

## Running

```powershell
python wony.py                      # tray mode (recommended — background + web UI)
python wony.py tray                 # same
python wony.py text                 # console text REPL
python wony.py voice                # console voice mode
python wony.py web                  # web server only
python wony.py doctor               # validate setup and exit
python wony.py autostart install    # add Windows logon task
python wony.py autostart uninstall  # remove logon task
python wony.py autostart status     # show task info
```

## Web UI

Wony includes a browser-based chat interface. Start the app then open `http://127.0.0.1:8000` (or whatever port you set under `server.port` in `config.yaml`).

The web UI has two panels:
- **Chat** — send messages and see AI responses with tool call details
- **Jobs** — browse and invoke all registered commands directly

A diagnostics banner shows warnings and errors (e.g. CUDA fallback, missing deps) with fix hints.

## Tray mode (always-on)

`python wony.py` starts Wony in the background with a system tray icon. Right-click to:
- **Open in web** — opens the chat UI in your browser
- **Listen now** — start a voice turn without the hotkey or wake word
- **Stop speaking** — cancel the current reply
- **Mute / Unmute** — silence spoken replies (an earcon still confirms a turn opened)
- **Wake word: On / Off** — shown only when a wake word is configured
- **Pause / Resume assistant** — stop the wake word, web server and background jobs
- **Exit** — shut down cleanly

To start automatically at Windows login:

```powershell
python wony.py autostart install
```

Remove with `python wony.py autostart uninstall`.

| Problem                                          | Fix                                                              |
| ------------------------------------------------ | ---------------------------------------------------------------- |
| Icon doesn't appear                              | Run `python wony.py tray` manually and check for errors          |
| "AI provider not ready" balloon                  | Add an API key to `.env` and re-run                              |
| Already running — second instance exits silently | Only one tray instance runs at a time; check the system tray     |
| Task installed but doesn't start at login        | Task Scheduler → `WonyAssistant` → check "Last Run Result"       |

## Setup validation

```powershell
python wony.py doctor   # full ✓/✗ checklist with fix hints
```

Or type `check setup` inside the assistant for the same report.

## config.yaml

```yaml
assistant:
  name: "Wony"
  owner_name: "Jakub"
  personality: "Friendly and concise."
  language: "en"

ai:
  provider: null   # null = auto-detect from .env; or: anthropic | gemini | ollama
  ollama_model: "llama3.1"

enabled_modules:
  - ai
  - status
  - basics
  - scheduler
  - weather
  - spotify
  - screen
  - gmail
  - calendar
  - shazam
  # - league
  # - home_assistant
  # - web
  # - desktop
  # - mcp
```

Secrets stay in `.env`. Non-secret per-module settings (e.g. Home Assistant URL, Gmail poll interval) go in `config.yaml` under `modules:`.

## Module dependencies (manual / advanced)

`setup.py` installs these for you based on what you select — you normally don't
run these by hand. Listed here for reference or for adding a single module later:

```powershell
pip install -r requirements/core.txt       # always required
pip install -r requirements/voice.txt      # speech I/O, TTS
pip install -r requirements/screen.txt     # screen capture + OCR
pip install -r requirements/automation.txt # league / mouse control
pip install -r requirements/weather.txt    # weather module
pip install -r requirements/gmail.txt      # Gmail module
pip install -r requirements/calendar.txt   # Google Calendar module
pip install -r requirements/web.txt        # web search + URL fetch
pip install -r requirements/desktop.txt    # desktop control
pip install -r requirements/shazam.txt     # song recognition
pip install -r requirements/mcp.txt        # MCP client
pip install -r requirements/semantic.txt   # semantic memory / RAG
pip install -r requirements/wakeword.txt   # wake word detection
pip install -r requirements/tray.txt       # system tray icon
```

## Integrations setup

### Spotify

1. Create app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Set Redirect URI: `http://127.0.0.1:8888/callback`
3. Add to `.env`:
   ```env
   SPOTIFY_CLIENT_ID="..."
   SPOTIFY_CLIENT_SECRET="..."
   ```

### Weather

1. Free key at [openweathermap.org/api](https://openweathermap.org/api)
2. Add to `.env`: `WEATHER_API_KEY="..."`

### Gmail / Calendar

1. Follow [simplegmail Getting Started](https://pypi.org/project/simplegmail/) for OAuth setup
2. Place `google_credentials.json` in `credentials/`
3. `pip install -r requirements/gmail.txt` and/or `pip install -r requirements/calendar.txt`
4. Enable `gmail` and/or `calendar` in `config.yaml`

### Voice input/output

Select **Voice I/O** in `setup.py` — it installs `requirements/voice.txt` plus the
full NVIDIA CUDA wheel set and guarantees the GPU `onnxruntime` build wins.

GPU acceleration is automatic: if a CUDA GPU is present it is used, otherwise the
app falls back to CPU. `requirements/voice.txt` bundles the complete CUDA 12 runtime
(`cuda-runtime`, `cudnn`, `cublas`, `cufft`, `curand`) so **no system CUDA toolkit is
needed** — cuDNN/cuBLAS alone are not enough, the CUDA provider also links cudart,
cuFFT and cuRAND. Verify with `wony.py doctor` (look for `TTS (Kokoro): GPU`).

Then run with `wony.py voice`.

Speech-to-text uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (offline). GPU machines use `distil-large-v3` (English) or `large-v3` (other languages, multilingual); CPU-only machines use `distil-small.en` or `small`.

**Low-latency streaming**: the assistant starts speaking as soon as the first sentence is ready — you don't wait for the full AI response. The same streaming applies to the web UI (live text bubble) and console output.

### Wake word (hands-free trigger)

By default (and out of the box after `pip install -r requirements/wakeword.txt`), wake word
uses a **pre-trained built-in phrase** — no training required:

```yaml
voice:
  wake_word:
    enabled: true
    phrase: "hey jarvis"   # built-in: "hey jarvis", "alexa", "hey mycroft", "hey rhasspy"
```

If `model_path` is set but the file is missing, or `phrase` isn't one of the built-ins above,
Wony logs a diagnostic and falls back to `"hey jarvis"` automatically rather than silently
disabling wake word — check `python wony.py doctor` or the tray diagnostics if it ever
sounds like the wrong word is being listened for.

### Training a custom wake word

Want your own phrase instead of a built-in? Start the guided setup:

```powershell
python setup.py wakeword
```

It asks for your phrase, optionally records you saying it (via
[training/record_wake_word.py](training/record_wake_word.py) — the single biggest accuracy
win, since a model that's never heard a real human sometimes only fires on synthetic voices),
and wires `config.yaml` for you. It then prints the one training command to run — either
[train_hey_wony.sh](training/train_hey_wony.sh) (WSL, ~4–6h on your own GPU) or
[train_hey_wony.ipynb](training/train_hey_wony.ipynb) (Colab, ~4–8h on a free T4) — both
resumable if interrupted, and both fully commented for anyone who wants the details.

Two things worth knowing going in: the script pauses partway through so you can listen to a
few generated clips before committing to the multi-hour part (they should sound like *you*
saying the phrase — if not, stop and adjust); and re-running after changing settings needs
`--fresh` (script flag / notebook cell), or old clips stay mixed into the new run.

### Voice barge-in

Interrupt the assistant mid-sentence. Enable in `config.yaml`:

```yaml
voice:
  barge_in:
    enabled: true
```

### Ollama (local AI)

```powershell
ollama serve
# set in config.yaml: ai.provider: ollama  and  ai.ollama_model: "llama3.1"
```

### MCP client

Connect any [MCP](https://modelcontextprotocol.io)-compatible server from chat:

```powershell
pip install -r requirements/mcp.txt
# enable 'mcp' in config.yaml
```

Example: *"Add an MCP server called filesystem at command npx -y @modelcontextprotocol/server-filesystem"*

### Semantic memory

Long-term recall using local embeddings (no API key required):

```powershell
pip install -r requirements/semantic.txt
```

Activates automatically. Use `semantic recall` to search by meaning or `index document` to make a file searchable.

### Home Assistant

Controls anything Home Assistant already controls — lights, switches, blinds,
thermostats, media players, locks, scenes and scripts — by name or by room
("dim the bedroom lamp to 30", "close the blinds", "is the garage open").

1. In Home Assistant, open your profile → **Security** → **Long-lived access
   tokens** → *Create token*.
2. Add it to `.env`:

   ```
   HOME_ASSISTANT_TOKEN="..."
   ```

3. Point `modules.home_assistant.base_url` in `config.yaml` at your Home
   Assistant (the same URL you open in a browser) and enable `home_assistant`.

Locks, alarms and garage doors are refused until you set
`modules.home_assistant.allow_locks: true` — everything else works right away.
No extra packages needed.

## Adding a new module

1. Create `modules/mymodule.py`
2. Use `@register_job(module_name="mymodule", requires=Requirement(...))` or `@register_service(...)`
3. Add `mymodule` to `enabled_modules` in `config.yaml`

## Tests

```powershell
python -m unittest discover -s tests -t .
```

Core dependencies only — the optional modules gate themselves off when their
packages are missing, which is the path CI runs. The suite covers the pieces
that fail silently rather than loudly: tool-schema generation, config keys that
must resolve against the settings schema, repo-anchored data paths, and the
SQLite store.

## Logging

```powershell
python -m helpers.analyze_logs          # summary of latest session
python -m helpers.analyze_logs -o r.txt # save to file
```

Logs in `logs/` — `.log` (human) and `.csv` (structured).
