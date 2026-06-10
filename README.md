# Wony — Personal AI Assistant

A local personal assistant powered by AI that accepts text and voice commands. Connect
integrations incrementally — anything not configured is automatically skipped.

## Architecture overview

| File          | Role                                                                                                       |
| ------------- | ---------------------------------------------------------------------------------------------------------- |
| `.env`        | **Secrets only** — API keys, client secrets. Never committed.                                              |
| `config.yaml` | **Your choices** — assistant name, enabled modules, settings. Gitignored; copy from `config.example.yaml`. |
| `cache.json`  | Machine-written runtime state (OAuth tokens, timestamps).                                                  |

Modules auto-register via decorators. If a module's env vars, credential files, or pip
packages are missing it registers as `disabled` / `misconfigured` / `unavailable` and its
commands are simply not offered — nothing crashes. The startup summary and `check setup`
command tell you exactly what to fix.

## Quick start

```powershell
# 1. Install core deps (text mode + one AI provider is all you need)
pip install -r requirements/core.txt

# 2. Configure
Copy-Item config.example.yaml config.yaml   # then edit config.yaml
```

Create `.env` in the project root with at least one AI key:

```env
ANTHROPIC_API_KEY="sk-..."     # OR
GEMINI_API_KEY="..."           # OR use Ollama (no key needed, set ai.provider: ollama in config.yaml)
```

```powershell
# 3. Validate setup before running
python wony.py doctor

# 4. Run
python wony.py
```

## Always-on background mode (tray)

Run Wony silently in the background with a system tray icon. This is the recommended way to use it day-to-day.

### Step 1 — Install tray dependency

```powershell
pip install -r requirements/tray.txt
```

### Step 2 — Test it manually first

```powershell
python wony.py tray
```

A blue circle icon appears in the system tray (bottom-right clock area). Right-click it:

- **Open in web** — opens the chat in your browser
- **Start / Stop** — pause or resume the assistant
- **Exit** — shut down

Close with **Exit** from the tray menu. If it works, move to Step 3.

### Step 3 — Enable autostart at Windows login

```powershell
python wony.py autostart install
```

This creates a Windows Task Scheduler entry that:

- Starts automatically when you log in
- Runs hidden (no console window)
- Restarts automatically if it crashes

Log off and back in — the tray icon should appear on its own.

**To remove autostart:**

```powershell
python wony.py autostart uninstall
```

**To check if the task is registered:**

```powershell
python wony.py autostart status
```

### Troubleshooting

| Problem                                          | Fix                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------- |
| Icon doesn't appear                              | Run `python wony.py tray` manually and check for error messages     |
| "AI provider not ready" balloon                  | Add an API key to `.env` and re-run                                 |
| Already running — second instance exits silently | Only one tray instance runs at a time; check the system tray        |
| Task installed but doesn't start at login        | Run Task Scheduler → find `WonyAssistant` → check "Last Run Result" |

## Setup validation

```powershell
python wony.py doctor   # full ✓/✗ checklist with fix hints, then exits
```

Or while running, type `check setup` for the same report inside the assistant.

Every launch prints a brief health summary — which modules loaded, which need attention,
and the AI provider status. Type `help` to see all working commands.

## config.yaml — personalization & module selection

```yaml
assistant:
  name: "Wony" # The assistant's name (used in AI prompts)
  owner_name: "Jakub" # Your name (used in AI prompts)
  personality: "Friendly and concise."
  language: "en"

ai:
  provider: null # null = auto-detect from .env keys; or: anthropic | gemini | ollama
  ollama_model: "llama3.1"

enabled_modules: # Only listed modules load; comment out to disable
  - ai
  - status
  - weather
  - spotify
  - system
  - screen
  # - gmail
  # - league
  # - shelly
```

Secrets stay in `.env`. Non-secret per-module settings (e.g. Shelly IP, Gmail poll interval)
go in `config.yaml` under `modules:`.

## Module dependencies

Install only what you use:

```powershell
pip install -r requirements/core.txt       # always required (text mode)
pip install -r requirements/voice.txt      # audio mode (speech I/O, TTS)
pip install -r requirements/screen.txt     # screen capture + OCR
pip install -r requirements/automation.txt # league / mouse control
pip install -r requirements/weather.txt    # weather module
pip install -r requirements/gmail.txt      # gmail module
pip install -r requirements/mcp.txt        # MCP client (external tool servers)
pip install -r requirements/semantic.txt   # semantic memory / RAG (fastembed)
```

## Available commands (examples)

Commands are generated from live registered jobs — `help` always shows exactly what's working.

| Command                     | What it does                                   |
| --------------------------- | ---------------------------------------------- |
| `help`                      | List all working commands grouped by module    |
| `check setup`               | Full ✓/✗ diagnostics with fix hints            |
| `module status`             | Table of all module states + hints             |
| `what time is it`           | Current time                                   |
| `what's the date`           | Today's date                                   |
| `set timer 5`               | 5-minute countdown timer (announces when done) |
| `list timers`               | Show active timers                             |
| `cancel timers`             | Stop all timers                                |
| `weather`                   | Current weather at your location               |
| `play song <title>`         | Play on Spotify                                |
| `what's playing`            | Announce current Spotify track                 |
| `volume up / down`          | Adjust Spotify volume                          |
| `check new emails`          | Check Gmail inbox once                         |
| `start checking new emails` | Background email polling (every 15 min)        |
| `stop checking new emails`  | Stop background polling                        |
| `save screenshot`           | Screenshot to screenshots/                     |
| `explain screenshot`        | AI vision analysis of the screen               |
| `list active jobs`          | Show running background jobs                   |
| `stop active jobs`          | Stop all background jobs                       |
| `exit`                      | Quit the assistant                             |

## Module status

Run `module status` inside the assistant to see which modules loaded:

```
Module status:
  Module         State             Reason
  -------------------------------------------------------
  ai             enabled
  screen         enabled
  weather        misconfigured     missing env: WEATHER_API_KEY
    Fix: Add WEATHER_API_KEY to .env (free key at openweathermap.org/api)...
  spotify        disabled          not in enabled_modules
  gmail          unavailable       pip module not installed: simplegmail
    Fix: Follow simplegmail OAuth setup, pip install -r requirements/gmail.txt
```

## Adding a new module

1. Create `modules/mymodule.py`
2. Import and use `@register_job(module_name="mymodule", requires=Requirement(...))` or
   `@register_service(module_name="mymodule", requires=Requirement(...))`.
3. Add `mymodule` to `enabled_modules` in `config.yaml`.

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

### Gmail

1. Follow [simplegmail Getting Started](https://pypi.org/project/simplegmail/)
2. Place `google_credentials.json` in `credentials/`
3. `pip install -r requirements/gmail.txt`
4. Enable `gmail` in `config.yaml`
5. Optional: set `modules.gmail.poll_interval_minutes` in `config.yaml` (default: 15)

### Voice input/output

1. `pip install -r requirements/voice.txt`
2. On NVIDIA GPU machines, also install the CUDA runtime wheels for acceleration:
   ```powershell
   pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
   ```
   Without these, the assistant falls back to CPU automatically.
3. Run with `python wony.py voice`

Speech-to-text uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (offline, no API
key needed). On first run the model downloads automatically and is cached locally. GPU machines
use `large-v3`; CPU-only machines use `small`. A progress message is printed during download.

### Wake word (hands-free trigger)

1. `pip install -r requirements/wakeword.txt`
2. No account or API key required — fully local and free.
3. Enable in `config.yaml`:
   ```yaml
   voice:
     wake_word:
       enabled: true
       phrase: "hey jarvis"  # built-in; also: "alexa", "hey mycroft", "hey rhasspy"
   ```
4. Wake word works in `voice` mode and `tray` mode. On first run, pre-trained model
   weights download automatically (~tens of MB).

### Training a custom wake word ("Hey Wony")

Two equivalent pipelines — pick whichever fits your setup:

| | [train_hey_wony.sh](training/train_hey_wony.sh) | [train_hey_wony.ipynb](training/train_hey_wony.ipynb) |
|---|---|---|
| **Where to run** | WSL (Windows Subsystem for Linux) | Google Colab |
| **GPU** | RTX 4060 (CUDA 12.1) | T4 free tier |
| **Time** | ~1–2 h | ~2–4 h |

**WSL script:**
```bash
bash /mnt/d/Projekty/Wony/training/train_hey_wony.sh
```
Requires Python 3.11 (installed automatically via deadsnakes PPA if missing).

**Colab notebook:**
1. Open `training/train_hey_wony.ipynb` in Google Colab
2. Runtime → Change runtime type → **GPU (T4)**
3. Run all cells top-to-bottom
4. Download `hey_wony.onnx` from the last cell

**After training:**

Place the model in the repo and point `config.yaml` at it:
```bash
# WSL — script copies automatically; for Colab place the downloaded file here:
cp hey_wony.onnx models/hey_wony.onnx
```
```yaml
voice:
  wake_word:
    enabled: true
    model_path: "models/hey_wony.onnx"
    threshold: 0.5   # lower = more sensitive, raise to cut false triggers
```

Verify the model loads:
```python
from openwakeword.model import Model
m = Model(wakeword_models=["models/hey_wony.onnx"], inference_framework="onnx")
print(list(m.prediction_buffer.keys()))  # should contain 'hey_wony'
```

### Ollama (local AI)

```powershell
ollama serve          # start the server
# set in config.yaml: ai.provider: ollama  and  ai.ollama_model: "llama3.1"
python wony.py
```

### MCP client (external tool servers)

Connect any [MCP](https://modelcontextprotocol.io)-compatible server entirely from chat — no config editing required.

```powershell
pip install -r requirements/mcp.txt
# enable 'mcp' in config.yaml
```

Example chat commands:
- *"Add an MCP server called filesystem at command npx -y @modelcontextprotocol/server-filesystem"*
- *"Connect the filesystem server"*
- *"List my MCP servers"*

Tools from connected servers appear immediately as normal commands with no restart.

### Semantic memory (RAG)

Long-term recall across sessions using local embeddings (no API key required).

```powershell
pip install -r requirements/semantic.txt
```

Activates automatically. Conversation turns and profile facts are embedded in the background. Use the `semantic recall` command to search by meaning, or `index document` to make a file searchable.

### Voice barge-in

Any speech during TTS playback stops the assistant mid-sentence. Enable in `config.yaml`:

```yaml
voice:
  barge_in:
    enabled: true
```

Interruption behaviour: empty/noise or resume phrase → resumes from where it stopped; stop phrase → ends turn; real command → processes immediately.

### Shelly smart switch

Set `modules.shelly.base_url` in `config.yaml` to your device IP and enable `shelly`.

## Running

### Unified entry point (recommended)

```powershell
python wony.py                 # tray mode (default — always-on background)
python wony.py tray            # same as above
python wony.py text            # console text REPL
python wony.py voice           # console voice mode (Ctrl+L + optional wake word)
python wony.py web             # web server only
python wony.py doctor          # validate setup and exit
python wony.py autostart install    # add Windows logon task (starts at login)
python wony.py autostart uninstall  # remove logon task
python wony.py autostart status     # show task info
```

### Tray mode (always-on)

`python wony.py` or `pythonw wony.py` starts Wony in the background with a system
tray icon. Right-click the icon to:

- **Open in web** — opens the chat UI in your browser
- **Start / Stop** — pause or resume listening and the web server
- **Exit** — shut down cleanly

To start automatically at Windows login:

```powershell
python wony.py autostart install
```

This creates a hidden Task Scheduler entry that runs `pythonw wony.py tray` at logon
and restarts on crash. Remove it with `python wony.py autostart uninstall`.


## Logging

```powershell
python -m helpers.analyze_logs          # summary of latest session
python -m helpers.analyze_logs -o r.txt # save to file
```

Logs in `logs/` — `.log` (human) and `.csv` (structured).
