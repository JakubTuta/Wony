# Wony — Personal AI Assistant

A local personal assistant powered by AI that accepts text and voice commands. Modules load on demand — anything not configured is automatically skipped.

## Architecture

| File          | Role                                                                            |
| ------------- | ------------------------------------------------------------------------------- |
| `.env`        | **Secrets only** — API keys, client secrets. Never committed.                   |
| `config.yaml` | **Your choices** — assistant name, enabled modules, settings. Copy from `config.example.yaml`. |
| `cache.json`  | Machine-written runtime state (OAuth tokens, timestamps).                       |

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

Wony includes a browser-based chat interface. Start the app then open `http://127.0.0.1:8111` (or whatever port you set in `config.yaml`).

The web UI has two panels:
- **Chat** — send messages and see AI responses with tool call details
- **Jobs** — browse and invoke all registered commands directly

A diagnostics banner shows warnings and errors (e.g. CUDA fallback, missing deps) with fix hints.

## Tray mode (always-on)

`python wony.py` starts Wony in the background with a system tray icon. Right-click to:
- **Open in web** — opens the chat UI in your browser
- **Start / Stop** — pause or resume the assistant
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
  - weather
  - spotify
  - screen
  - gmail
  - calendar
  - shazam
  # - league
  # - shelly
  # - scheduler
  # - web
  # - desktop
  # - mcp
```

Secrets stay in `.env`. Non-secret per-module settings (e.g. Shelly IP, Gmail poll interval) go in `config.yaml` under `modules:`.

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
pip install -r requirements/scheduler.txt  # persistent reminders
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

Speech-to-text uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (offline). GPU machines use `large-v3`; CPU-only machines use `distil-small.en` or `small`.

**Low-latency streaming**: the assistant starts speaking as soon as the first sentence is ready — you don't wait for the full AI response. The same streaming applies to the web UI (live text bubble) and console output.

### Wake word (hands-free trigger)

1. `pip install -r requirements/wakeword.txt`
2. Enable in `config.yaml`:
   ```yaml
   voice:
     wake_word:
       enabled: true
       phrase: "hey jarvis"   # built-in: "alexa", "hey mycroft", "hey rhasspy"
   ```

### Training a custom wake word ("Hey Wony")

| | [train_hey_wony.sh](training/train_hey_wony.sh) | [train_hey_wony.ipynb](training/train_hey_wony.ipynb) |
|---|---|---|
| **Where to run** | WSL (Windows Subsystem for Linux) | Google Colab |
| **GPU** | RTX 4060 (CUDA 12.1) | T4 free tier |
| **Time** | ~1–2 h | ~2–4 h |

**WSL:**
```bash
bash /mnt/d/Projekty/Wony/training/train_hey_wony.sh
```

**Colab:** Open `training/train_hey_wony.ipynb`, set Runtime to GPU (T4), run all cells, download `hey_wony.onnx`.

**After training:**
```bash
cp hey_wony.onnx models/hey_wony.onnx
```
```yaml
voice:
  wake_word:
    enabled: true
    model_path: "models/hey_wony.onnx"
    threshold: 0.5
```

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

### Shelly smart switch

Set `modules.shelly.base_url` in `config.yaml` to your device IP and enable `shelly`.

## Adding a new module

1. Create `modules/mymodule.py`
2. Use `@register_job(module_name="mymodule", requires=Requirement(...))` or `@register_service(...)`
3. Add `mymodule` to `enabled_modules` in `config.yaml`

## Logging

```powershell
python -m helpers.analyze_logs          # summary of latest session
python -m helpers.analyze_logs -o r.txt # save to file
```

Logs in `logs/` — `.log` (human) and `.csv` (structured).
