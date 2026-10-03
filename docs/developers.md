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

`setup.py` asks about the same settings through `ask_setting(key)`, which takes
the label, help text, limits and validation from the `Field` and writes with
`settings.apply`, so setup and the page cannot describe a setting differently.
A new `Field` therefore also needs an `ask_setting` call in the matching setup
step; `tests/test_setup_questions.py` fails until it has one. Only
Telegram's `owner` is not asked, because pairing fills it in. Keys, sign-ins and
the safety gates keep their own prompts in `setup.py` (they check the key or open
a browser), and a new option in `config.example.yaml` needs a `Field` too
(`tests/test_settings.py` checks it).

`helpers/settings.MODULES` is the one list of features: key, label, description
and an example phrase. `capabilities()` splits it into what works now and what is
switched off. The system prompt, the chat chips and the welcome card all read
it, so they cannot disagree.

### What Wony says about itself

`system_status(scope="about", query=...)` (`helpers/guide.py`) answers "what is my
speaking speed", "how do I set up Gmail" and "how do I install this" from live
sources, never from text kept in code: settings from `settings.explain` (current
value, limits, Settings section, restart), a feature's state from the registry,
and the steps from `README.md`, cut into paragraphs and table rows. Both are
ranked by `helpers/lookup.py`, where a rare word outweighs a common one and a
word in a label or heading outweighs one in the text. A new `Field` is explained
with no further work, and an instruction belongs in the README — not in the
prompt or a message.

- Secrets (`kind="secret"`) and `private=True` fields are reported only as set or
  not set. `tests/test_self_help.py` fails if any secret value reaches the output.
- A message that sends the user to a setting uses `settings.where(key)`, never a
  key name or "edit config.yaml".
- It is read-only on purpose. The web API has no password and runs any
  registered job, so a job that wrote settings would let a page flip a switch
  that ships off.

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

## Chat channels

`modules/telegram.py` is the pattern for reaching Wony from outside the PC; a
Discord or email channel would copy it. A channel is a service that registers no
jobs, polls outward (no open port, no public URL), checks who is talking, and
calls `run_turn(text, at_machine=False)` — the same entry as voice and the web
page, so the agent lock, the confirm gate and the untrusted fence all apply.

Its polling thread starts from `bootstrap._start_telegram`, not from `__init__`:
anything that merely imports `modules` (the tests, `doctor`) would otherwise
start taking the real bot's messages.

- **Who may talk:** one paired owner, stored in `modules.telegram.owner`. Pairing
  is a one-time code announced through `notify`; five wrong codes switch pairing
  off until restart; strangers get no reply.
- **`at_machine` vs `user_present`:** a chat user is present (can confirm) but not
  at the PC. `turn_context.at_machine()` gates anything that opens a window on the
  desktop — Google consent in `google_auth.credentials`, typing and clicking in
  `desktop._require_actions`. A new job that opens or clicks something on screen
  needs the same check.
- **Forwarded text** is someone else's words: pass it as `run_turn(quoted=...)`,
  never inside `user_input`, so it is fenced and not counted as the user's.
- **Stale messages:** Telegram queues for 24h. A message older than
  `_STALE_SECONDS` gets "I was off" and is not run.
- **Out:** the module listens on `helpers.events` and copies `notification`
  events to the owner. It stays quiet while paused (`BackgroundJobs` not running).
- **Tests:** `tests/test_telegram.py` fakes the Bot API at `net.post`.

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
