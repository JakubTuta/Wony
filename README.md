# Wony — Personal AI Assistant

A local personal assistant powered by AI that accepts text and voice commands. Connect
integrations incrementally — anything not configured is automatically skipped.

## Architecture overview

| File | Role |
|---|---|
| `.env` | **Secrets only** — API keys, client secrets. Never committed. |
| `config.yaml` | **Your choices** — assistant name, enabled modules, settings. Gitignored; copy from `config.example.yaml`. |
| `cache.json` | Machine-written runtime state (OAuth tokens, timestamps). |

Modules auto-register via decorators. If a module's env vars, credential files, or pip
packages are missing it registers as `disabled` / `misconfigured` / `unavailable` and its
commands are simply not offered — nothing crashes. The startup summary and `check setup`
command tell you exactly what to fix.

## Quick start

```powershell
# 1. Create and activate venv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install core deps (text mode + one AI provider is all you need)
pip install -r requirements/core.txt

# 3. Configure
Copy-Item config.example.yaml config.yaml   # then edit config.yaml
```

Create `.env` in the project root with at least one AI key:

```env
ANTHROPIC_API_KEY="sk-..."     # OR
GEMINI_API_KEY="..."            # OR use Ollama (no key needed, set ai.provider: ollama in config.yaml)
```

```powershell
# 4. Validate setup before running
python assistant.py --doctor

# 5. Run
python assistant.py
```

## Setup validation

```powershell
python assistant.py --doctor   # full ✓/✗ checklist with fix hints, then exits
```

Or while running, type `check setup` for the same report inside the assistant.

Every launch prints a brief health summary — which modules loaded, which need attention,
and the AI provider status. Type `help` to see all working commands.

## config.yaml — personalization & module selection

```yaml
assistant:
  name: "Wony"          # The assistant's name (used in AI prompts)
  owner_name: "Jakub"   # Your name (used in AI prompts)
  personality: "Friendly and concise."
  language: "en"

ai:
  provider: null        # null = auto-detect from .env keys; or: anthropic | gemini | ollama
  ollama_model: "llama3.1"

enabled_modules:        # Only listed modules load; comment out to disable
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
pip install -r requirements/voice.txt      # --audio mode (speech I/O)
pip install -r requirements/screen.txt     # screen capture + OCR
pip install -r requirements/automation.txt # league / mouse control
pip install -r requirements/weather.txt    # weather module
pip install -r requirements/gmail.txt      # gmail module
```

## Available commands (examples)

Commands are generated from live registered jobs — `help` always shows exactly what's working.

| Command | What it does |
|---|---|
| `help` | List all working commands grouped by module |
| `check setup` | Full ✓/✗ diagnostics with fix hints |
| `module status` | Table of all module states + hints |
| `what time is it` | Current time |
| `what's the date` | Today's date |
| `set timer 5` | 5-minute countdown timer (announces when done) |
| `list timers` | Show active timers |
| `cancel timers` | Stop all timers |
| `weather` | Current weather at your location |
| `play song <title>` | Play on Spotify |
| `what's playing` | Announce current Spotify track |
| `volume up / down` | Adjust Spotify volume |
| `check new emails` | Check Gmail inbox once |
| `start checking new emails` | Background email polling (every 15 min) |
| `stop checking new emails` | Stop background polling |
| `save screenshot` | Screenshot to screenshots/ |
| `explain screenshot` | AI vision analysis of the screen |
| `list active jobs` | Show running background jobs |
| `stop active jobs` | Stop all background jobs |
| `exit` | Quit the assistant |

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
2. Place `gmail_credentials.json` in `credentials/`
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
3. Run with `python assistant.py --audio`

Speech-to-text uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (offline, no API
key needed). On first run the model downloads automatically and is cached locally. GPU machines
use `large-v3`; CPU-only machines use `small`. A progress message is printed during download.

### Ollama (local AI)

```powershell
ollama serve          # start the server
# set in config.yaml: ai.provider: ollama  and  ai.ollama_model: "llama3.1"
python assistant.py
```

### Shelly smart switch

Set `modules.shelly.base_url` in `config.yaml` to your device IP and enable `shelly`.

## Running

```powershell
python assistant.py            # text mode (default)
python assistant.py --audio    # voice mode
python assistant.py --local    # force Ollama
python assistant.py --doctor   # validate setup and exit
```

## Logging

```powershell
python -m helpers.analyze_logs          # summary of latest session
python -m helpers.analyze_logs -o r.txt # save to file
```

Logs in `logs/` — `.log` (human) and `.csv` (structured).
