# Wony for developers

The [README](../README.md) is for someone who wants the assistant to work. This
file is for someone changing it. Engineering rules live in
[CLAUDE.md](../CLAUDE.md); read that first.

## Layout

| Path                   | What lives there                                                      |
| ---------------------- | --------------------------------------------------------------------- |
| `wony.py`              | Entry point: `tray`, `text`, `voice`, `web`, `doctor`, `autostart`    |
| `tray_app.py`          | Tray icon host; owns restart and the single-instance lock             |
| `setup.py`             | Installer and `configure`. Stdlib only until it has installed packages |
| `helpers/`             | Shared machinery: agent loop, registry, confirm gate, config, web API |
| `modules/`             | One file per switchable feature; each registers jobs                  |
| `web/`                 | React + Vite chat UI, built to `web/dist` (not in the repo)           |
| `requirements/`        | One requirements file per feature                                     |
| `tests/`               | `python -m pytest -q` from the venv                                   |
| `training/`            | Custom wake-word training (WSL script and Colab notebook)             |

## Running it

```powershell
python wony.py            # tray + web page (what Wony.bat does)
python wony.py text       # plain text conversation in the terminal
python wony.py voice      # voice only, no tray
python wony.py web        # web page only (no restart button)
python wony.py doctor     # check the setup and exit
python wony.py autostart install    # undo with: autostart uninstall
python setup.py configure           # add a key or sign in again, no install
```

`wony.py` and `setup.py configure` relaunch themselves under the interpreter
recorded in `.wony_setup`, so these work from the system Python too.

Build or hot-reload the UI:

```powershell
cd web
npm install
npm run build     # or: npm run dev   (proxies /api to the running backend)
npm run lint
```

The dev server rewrites the `Origin` of proxied requests (`web/vite.config.ts`)
because the API only accepts same-origin requests.

## Settings and config

`config.yaml` is for the end user: only values a normal person could read and
choose. Tuning thresholds are module-level constants next to their code. Anything
a user may change is a `Field` in `helpers/settings.py`, which is what the
Settings page renders; secrets (`kind="secret"`) are written to `.env`.

`helpers/settings.MODULES` is the one list of features: key, label, description
and an example phrase. `capabilities()` splits it into what works now and what is
switched off. The system prompt, the chat chips and the welcome card all read
it, so they cannot disagree.

### Switches that ship off

| Switch                              | Key                                  |
| ----------------------------------- | ------------------------------------ |
| Change my mailbox                   | `modules.gmail.allow_write`          |
| Change my calendar / send invites   | `modules.calendar.allow_write`       |
| Change my Drive files               | `modules.drive.allow_write`          |
| Unlock doors and open the garage    | `modules.home_assistant.allow_locks` |
| Type and click for me               | `modules.desktop.allow_actions`      |
| Install MCP tool servers            | `modules.mcp.allow_install`          |
| Speak up on its own                 | `assistant.proactive.enabled`        |
| Learn about me on its own           | `assistant.memory.learn_from_my_data`|
| Tell it what I'm looking at         | `modules.desktop.share_window_title` |

## Safety model

Four layers, in order of how much they are trusted:

1. **Untrusted fence.** Text someone else wrote (mail, pages, invites, shared
   files, MCP results, screen and clipboard reads) is wrapped by
   `helpers/untrusted.wrap` and the system prompt tells the model it is data.
   `wrap` also marks the turn as having read untrusted text.
2. **Confirm gate** (`helpers/confirm.py`). A job registered with `confirms=`
   does not run on the first call; the call is armed, the model asks the user,
   and the identical call in a *later* turn runs. `confirms` is `True`, a set of
   `action` values, or a callable of the arguments. Unattended turns (triggers)
   can neither arm nor spend a confirmation. `confirm.after_untrusted` is the
   predicate for "ask only once this turn read untrusted text".
3. **Argument validation.** `helpers/tools.validate_args` rejects any `Literal`
   argument outside its enum before the gate and before the job, so jobs can
   trust their `action` values. `add_reminder` validates the action it schedules.
4. **Switches.** The `allow_*` settings above.

Scheduled actions run with no model in the loop, so `add_reminder` confirms
whenever it is given an `action_job`.

The web API listens on loopback only, checks `Host`, `Origin` and
`Sec-Fetch-Site`, serves no OpenAPI schema, and `/api/invoke` skips the confirm
gate because the UI dialog already confirmed.

## Adding a job

See "Jobs are the model's API" in CLAUDE.md. Short version: one job with an
`action` argument beats several near-identical ones; the first docstring
paragraph and `Args:` are what the model sees; return a `str` and use
`@capture_response`; declare `confirms=` for anything that changes something the
user cares about; give the module a `Requirement` whose `setup_hint` tells a
non-developer what to click.

## Voice

Speech recognition is faster-whisper (English models), speech is Kokoro, the wake
word is openWakeWord. All local.

### Training your own wake word

```powershell
python setup.py wakeword
```

It asks for your phrase, records you saying it a few times (the single biggest
accuracy win), wires up the config, and prints the training command: either
`training/train_hey_wony.sh` (WSL, about 4-6h on your own GPU) or
`training/train_hey_wony.ipynb` (Colab, about 4-8h free). Both are resumable, and
the script pauses so you can listen to a few generated clips first. Re-running
after changing settings needs `--fresh`. Keep the shell script and the notebook
in sync.

## Reading the logs

`logs/ai_assistant_<timestamp>.log` and `.csv` hold every turn and tool call.
Secrets and `appid=`/`key=`/`token=` query parameters are redacted on the way in.
