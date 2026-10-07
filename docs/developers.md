# Wony for developers

The [README](../README.md) is for someone who wants the assistant to work. This
file is for someone changing it. Engineering rules live in `CLAUDE.md`; read
that first.

This is the wall-panel branch (`raspberry-pi`): a Raspberry Pi with a touch
screen, no microphone and no keyboard. It shares its agent loop, job registry,
confirm gate and Google/Spotify/Home Assistant modules with the PC build on
`main`, and drops everything that needs a PC.

## Layout

| Path                   | What lives there                                                          |
| ---------------------- | ------------------------------------------------------------------------- |
| `wony.sh`              | Launcher: finds `python` or `python3`, then runs `wony.py` (`setup` runs `setup.py`) |
| `wony.py`              | Entry point: `kiosk` (default), `text`, `doctor`, `autostart`             |
| `setup.py`             | Installer and `configure`. Stdlib only until it has installed packages    |
| `helpers/`             | Shared machinery: agent loop, registry, confirm gate, config, web API     |
| `helpers/kiosk.py`     | Home-screen tile layout and the idle screen's cards                       |
| `helpers/lowpower.py`  | Sleep: panel dark, pollers stopped, everything else running               |
| `helpers/display.py`   | Which command switches this panel off and on (wlopm, backlight, ...)      |
| `helpers/panels.py`    | Structured data for each screen, read through `/api/panel/{key}`          |
| `helpers/autostart.py` | The two systemd user units: Wony and the fullscreen browser               |
| `modules/`             | One file per switchable feature; each registers jobs                      |
| `kiosk/`               | React + Vite touch UI, built to `kiosk/dist` (not in the repo)            |
| `requirements/`        | One requirements file per feature                                         |
| `tests/`               | `python -m unittest discover -s tests -t .`                               |

## Running it

```bash
./wony.sh                      # API + touch UI on 127.0.0.1:8000 (`wony.py kiosk`, as systemd runs it)
./wony.sh text                 # plain text conversation in the terminal
./wony.sh doctor               # check the setup and exit
./wony.sh autostart install    # undo with: autostart uninstall
./wony.sh setup configure      # add a key or sign in again, no install
```

`wony.py` and `setup.py configure` relaunch themselves under the interpreter
recorded in `.wony_setup`, so these work from the system Python too.

Only one Wony runs per checkout. `kiosk` and `text` claim `helpers/instance.py`
(an OS file lock on `.wony_lock`, released by the OS if Wony dies) before they
start anything, and a second copy says so and exits — a second one would restore
every reminder from `wony.db` and fire it again. Stop the service before you use
`text`. A new entry point that starts the assistant must claim the lock too.

Build or hot-reload the screen:

```bash
cd kiosk
npm install
npm run build     # or: npm run dev   (proxies /api to the running backend)
npm run lint
```

The dev server rewrites the `Origin` of proxied requests (`kiosk/vite.config.ts`)
because the API only accepts same-origin requests. After a rebuild the browser
asks again for `index.html` (`Cache-Control: no-cache`), so a restart is enough.

## The API

The same routes, with the same bodies, are served by the PC build and the wall
panel (`raspberry-pi` branch), and `tests/test_api_contract.py` and
`tests/test_local_only.py` are the same files on both. A change to one of these
is a change to both branches.

| Route                                  | What it is                                                             |
| -------------------------------------- | ---------------------------------------------------------------------- |
| `GET /api/config`                      | Name, plus the settings the UI itself needs (platform-specific keys)   |
| `GET /api/health`                      | Module status and diagnostics (platform-specific extras)               |
| `GET /api/jobs`                        | Every job: `confirms` (is it gated) and `confirm_words` (which `action` values ask; null = every call) |
| `POST /api/invoke`                     | Run a job from a button; skips the confirm gate, the UI already asked  |
| `POST /api/chat`, `GET /api/chat/history`, `POST /api/chat/clear`, `WS /api/ws` | A sentence in, a turn out; the socket streams it |
| `GET /api/panels`, `GET /api/panel/{key}` | Structured data for a screen, read-only                             |
| `POST /api/devices/control`            | One Home Assistant device by exact id                                  |
| `GET /api/notifications`, `POST /api/notifications/{id}/ack`, `POST /api/notifications/ack-all` | The bell |
| `GET/POST /api/settings`, `POST /api/data/wipe` | Settings the UI may show and write; wiping the data           |

Everything else belongs to one branch: `/api/kiosk/tiles`, `/api/ambient`, `/api/sleep`, `/api/wake` and `/api/updates`. Requests are
checked by `helpers/local_only.py` (Host, Origin and Sec-Fetch-Site), which both
branches call with their own list of served host names (`_allowed_hosts` in
`helpers/web_app.py`).

## Settings and config

`config.yaml` is for the end user: only values a normal person could read and
choose. Tuning thresholds are module-level constants next to their code. Anything
a user may change is a `Field` in `helpers/settings.py`, which is what the
Settings screen renders. There are no secret fields: keys live in `.env` and are
written by `./wony.sh setup configure`, because a panel with no keyboard of its
own is the wrong place to type one.

`setup.py` asks about the same settings through `ask_setting(key)`, which takes
the label, help text and limits from the `Field` and writes with `settings.apply`,
so setup and the screen cannot describe a setting differently. A new `Field`
therefore also needs an `ask_setting` call in the matching setup step;
`tests/test_setup_questions.py` fails until it has one. A new option in
`config.example.yaml` needs a `Field` too (`tests/test_settings.py` checks it).

`helpers/settings.MODULES` is the one list of features. `working_modules()` says
which of them are on and actually working; the system prompt only claims Gmail
and Calendar access when both are.

Two things are deliberately not settings: the sleep wake time (remembered from
last night, `helpers/lowpower.py`) and the Home tab's tile layout (arranged by
touch, kept in the database under `kiosk.tiles`).

### What Wony says about itself

`system_status(scope="about", query=...)` (`helpers/guide.py`) answers "how long
before the clock screen shows" and "how do I set up Gmail" from live sources,
never from text kept in code: settings from `settings.explain`, a feature's state
from the registry, and the steps from `README.md`, cut into paragraphs and table
rows. An instruction belongs in the README, not in the prompt or a message.
It is read-only on purpose: the API has no password and runs any registered job,
so a job that wrote settings would let a page flip a switch that ships off.

### Switches that ship off

| Switch                              | Key                                  |
| ----------------------------------- | ------------------------------------ |
| Power off this device               | `modules.basics.allow_power_off`     |
| Change my mailbox                   | `modules.gmail.allow_write`          |
| Change my calendar                  | `modules.calendar.allow_write`       |
| Unlock doors and open the garage    | `modules.home_assistant.allow_locks` |
| Speak up on its own                 | `assistant.proactive.enabled`        |
| Learn about me on its own           | `assistant.memory.learn_from_my_data`|

## Safety model

Four layers, in order of how much they are trusted:

1. **Untrusted fence.** Text someone else wrote (mail, invites) is wrapped by
   `helpers/untrusted.wrap` and the system prompt tells the model it is data.
   `wrap` also marks the turn as having read untrusted text.
2. **Confirm gate** (`helpers/confirm.py`). A job registered with `confirms=`
   does not run on the first call; the call is armed, the model asks the user,
   and the same call in a *later* turn runs (blank and default arguments are
   ignored when comparing, `confirm.normalize`). `confirms` is `True`, a set of
   `action` values, or a callable of the arguments. Unattended turns (triggers,
   scheduled routines) can neither arm nor spend a confirmation. A confirm
   sheet's button runs the call through `/api/invoke`, which spends the armed
   confirmation and tells the history it ran. `confirm.after_untrusted` is the
   predicate for "ask only once this turn read untrusted text" — fenced text
   replayed from earlier turns counts.
3. **Argument validation.** `helpers/tools.validate_args` rejects any `Literal`
   argument outside its enum before the gate and before the job. This is what
   makes a set of gate words complete: a job whose `action` is a plain `str` can
   be called with a synonym the gate does not list ("reboot"), so every job with
   a set-valued `confirms` types `action` as a `Literal`
   (`tests/test_tool_schemas.py` checks it).
4. **Switches.** The `allow_*` settings above.

Confirm what is hard to take back; make the rest undoable. A job whose change is
cheap to reverse (a light, a list item, a playlist track, a timer, a fact)
calls `helpers/undo.push(what, revert)` instead of declaring `confirms`, and
"undo" reverses the latest one within 15 minutes. Only a user's request pushes.

A bare "yes", "no" or "undo" never reaches the model (`turn._answer_without_model`):
"yes" runs exactly what the previous turn armed (`confirm.take_previous_turn`),
"no" drops it.

The API listens on loopback unless `server.host` says otherwise (bootstrap puts a
warning on the health page if it does). It checks `Host`, `Origin` and
`Sec-Fetch-Site` (`helpers/local_only.py`), serves no OpenAPI schema, and `/api/invoke` skips the confirm
gate because the screen's confirm sheet already asked.

Every path that reaches a job takes `agent_lock` (`kiosk._run_job` for a tile,
`run_turn` for a sentence, `/api/invoke` for a button): they all share the same
objects. The idle screen's poll takes it without waiting and gives up rather than
queue behind a turn. A new entry point must take it too.

## The agent turn

- **Tools sent** (`helpers/toolset.py`): above 25 jobs, a turn gets the
  always-needed features, the three the request is most about (by embedding once
  the model is loaded, by words before), and whatever the last two turns used.
  A job the model names that was not sent still runs, and a routine's steps
  widen the set mid-turn (`run_agent(more_jobs=...)`).
- **Calls in one step run together** (`agent._run_planned`): the checks (argument
  validation, confirm gate) run first, in order, on the turn's thread; then one
  lane per feature, lanes on worker threads. Calls to the same feature keep
  their order. Workers carry the turn's state (`turn_context.capture/carried`)
  and hand back what they marked (`absorb`), so an email read on a worker still
  gates the rest of the turn.
- **Thinking:** typed turns think (`run_turn(think=True)`); triggers and
  scheduled routines do not. Claude's reply blocks travel back unchanged
  (`_anthropic_content`, like Gemini's `_gemini_content`), which thinking needs.
- **Memory in the prompt:** the stable block carries up to 40 facts (stated
  before guessed, newest first); facts beyond that join the volatile block when
  the request is about them (`Profile.relevant`). Turns trimmed from the window
  are folded into a running summary (`Conversation._fold`), fenced text left out.
  `recall(scope="person")` gathers one person from facts, mail, calendar and
  past chats (`helpers/people.py`).

## The screen

- **Tiles.** A tile id is `kind` or `kind:arg` (`routine:briefing`,
  `device:light.lamp`, `timer:10`, `music`, `volume`, `sleep`). Tapping one
  resolves straight to a job, with no model call. `helpers/kiosk.save_tiles`
  validates against an explicit pattern; the endpoint never stores free text.
- **Panels.** `helpers/panels.py` maps a key to a `snapshot()` on a module. Adding
  one is a snapshot function and a line in `_PANELS`.
- **Idle screen.** After `kiosk.idle_minutes` the page shows a clock and
  `kiosk.ambient()` cards. Touching it anywhere returns to Home.
- **Notifications.** `helpers.notify.notify` writes the database first and pushes
  to connected screens second. Nothing wakes a sleeping panel.
- **Sleep.** `helpers/lowpower.py` darkens the panel (`helpers/display.py` tries
  each backend until one works), stops the pollers and leaves the rest running.
  A tap or the wake time ends it. A restart always turns the panel back on.

### Starting at boot

`./wony.sh autostart install` writes two systemd *user* units: `wony.service`
(`wony.py kiosk`) and `wony-kiosk.service` (Chromium, fullscreen, pointed at
`localhost:<server.port>`), and enables lingering so they start without a login.

### Starting with no AI key

The device still comes up: timers, music and the smart home need no key. The AI
service fails on its own and is left unregistered; `get_ai_client()` retries it
(re-reading `.env`) on every turn and, until a key exists, a turn answers with
`NO_AI_MESSAGE`. Startup also puts that message on the bell once.

## Adding a job

See "Jobs are the model's API" in CLAUDE.md. Short version: one job with an
`action` argument beats several near-identical ones; the first docstring
paragraph and `Args:` are what the model sees; return a `str` and use
`@capture_response`; type `action` as a `Literal`; declare `confirms=` for
anything that changes something the user cares about and is hard to take back,
`undo.push` for what is easy to; give the module a `Requirement` whose
`setup_hint` tells a non-developer what to do; add the module to
`helpers.settings.MODULES` with a description the tool picker can match
requests against.

## Keeping in step with main

Both branches carry the same agent loop, registry, confirm gate, `tools.py`,
`turn.py`, Google auth and the Gmail/Calendar/Spotify/Home Assistant/Weather
modules. A fix to any of them belongs on both: port it when you make it, and say
so in the commit. What is deleted here is deleted, not switched off.
