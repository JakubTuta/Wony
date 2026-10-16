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
| `wony.py`              | Entry point: `kiosk` (default, the assistant and its API), `panel`, `text`, `doctor`, `autostart` |
| `setup.py`             | Installer and `configure`. Stdlib only until it has installed packages    |
| `helpers/`             | Shared machinery: agent loop, registry, confirm gate, config, web API     |
| `helpers/kiosk.py`     | Home-screen tile layout and the idle screen's cards                       |
| `helpers/lowpower.py`  | Sleep: panel dark, pollers stopped, everything else (Telegram too) running |
| `helpers/display.py`   | Which command switches this panel off and on (wlopm, backlight, ...)      |
| `helpers/wayland.py`   | Finds the Wayland session from a process that was not started inside it   |
| `helpers/panels.py`    | Structured data for each screen, read through `/api/panel/{key}`          |
| `helpers/screen.py`    | What the panel needs from the OS: apt packages, the `qml6` tool, how to launch it |
| `helpers/session.py`   | Builds labwc's config for the panel session: `kiosk/session` plus the user's touch/input settings |
| `helpers/browser.py`   | The throwaway Chromium (plus keyboard) a Google or Spotify sign-in opens over the panel |
| `helpers/autostart.py` | `wony.service` (user unit) and `wony-panel.service` (system unit, the display manager) |
| `modules/`             | One file per switchable feature; each registers jobs                      |
| `kiosk/`               | The touch panel: Qt Quick (QML), run by `qml6`; see "The panel app" below |
| `requirements/`        | One requirements file per feature (`dev-screen.txt` only for PCs and CI)  |
| `tests/`               | `python -m unittest discover -s tests -t .`; `screen_fixture.py` fakes the API for the panel |

## Running it

```bash
./wony.sh                      # the assistant and its API on 127.0.0.1:8000 (`wony.py kiosk`, as systemd runs it)
./wony.sh panel [--windowed]   # the touch panel, a separate process talking to that API
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

Working on the panel (there is nothing to build; QML is read as it is):

```bash
pip install -r requirements/dev-screen.txt       # Qt 6.8 through PySide6, the version Trixie ships
python tests/screen_fixture.py 8765               # a fake API with fixed data, no assistant needed
python kiosk/tools/dev_panel.py --api http://127.0.0.1:8765 --windowed
./wony.sh panel --windowed                        # or against the real assistant
pyside6-qmllint -W 0 $(find kiosk -name '*.qml')  # what CI lints with (kiosk/.qmllint.ini)
node --test kiosk/tests/*.test.mjs                # the panel's logic, in plain JS
python -m unittest tests.test_screen              # the whole panel, offscreen, against the fixture
```

`panel` runs `qml6 kiosk/Main.qml -- --api URL`: Qt's own tool passes what follows
`--` to the app as `Qt.application.arguments`. `pyside6-qml` rejects arguments for
the app, hence `kiosk/tools/dev_panel.py` on a PC (`helpers/screen.panel_command`
picks one).

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
`helpers/web_app.py`). The API serves no pages: the panel is a client like any
other. QML's `XMLHttpRequest` and `WebSocket` send no `Origin`, which the check
accepts as a non-browser client; `tests/screen_fixture.py` enforces the same
check, so a change that made the panel send one fails `tests/test_screen.py`.

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
`tests/test_setup_questions.py` fails until it has one. Only Telegram's `owner`
is not asked, because pairing fills it in. A new option in
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
`run_turn` for a sentence or a Telegram message, `/api/invoke` for a button): they all share the same
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
- **What Wony says unasked joins the conversation:** `notify` records it as a
  turn with a `source` and no user words (`Conversation.record_notice`), so a
  question about it ("what time is that?") has something to refer to. Send
  every proactive message through `notify`, never straight to Telegram.
  `private=True` keeps it from the model (a pairing code); `untrusted=True`
  fences the history's copy when it retells someone else's words. Readers of
  `turns` that mean "what the user said" skip rows with a `source` (`learn.py`,
  `people.py`).

## The screen

- **Tiles.** A tile id is `kind` or `kind:arg` (`routine:briefing`,
  `device:light.lamp`, `timer:10`, `music`, `volume`, `sleep`). Tapping one
  resolves straight to a job, with no model call. `helpers/kiosk.save_tiles`
  validates against an explicit pattern; the endpoint never stores free text.
- **Panels.** `helpers/panels.py` maps a key to a `snapshot()` on a module. Adding
  one is a snapshot function and a line in `_PANELS`.
- **Idle screen.** After `kiosk.idle_minutes` the panel shows a clock and
  `kiosk.ambient()` cards. Touching it anywhere returns to Home.
- **Notifications.** `helpers.notify.notify` writes the database and the
  conversation first and pushes to connected screens second. Nothing wakes a
  sleeping panel.
- **Sleep.** `helpers/lowpower.py` darkens the panel (`helpers/display.py` tries
  each backend until one works), stops the pollers and leaves the rest running.
  A job started with `BackgroundJobs.start(suspendable=False)` is not a poller
  and keeps running; that is Telegram, the way in while the panel is dark.
  A tap or the wake time ends it. A restart always turns the panel back on.

### The panel app

Why a native app: on a 2 GB Pi the desktop (~300 MB), Chromium (300-600 MB) and
Home Assistant do not fit, the board swaps and the web UI ran at about 1 fps.
`kiosk/` is Qt Quick (QML), run by the stock `qml6` tool from apt inside a bare
labwc session: no desktop, no browser, no Python or Node in the process.

```
kiosk/Main.qml       the Window: scales one 1280x800 Frame to any screen, black backdrop
kiosk/Shell.qml      header, one screen at a time (Loaders), nav bar, sheets, idle and sleep
kiosk/state/         singletons: Api (XHR), Wony (config, socket, sleep), Live (polls), Ui, Clock
kiosk/theme/         Theme.qml: palette, type, motion
kiosk/lib/*.mjs      the logic, no Qt: devices, tiles, jobs, time, layout (node --test runs them)
kiosk/components/    Pressable, Txt, Icon, Field, Keyboard, Scrim and the sheets
kiosk/screens/       Home, Rooms, Music, Macros, System (Settings, Accounts), Ambient
kiosk/icons/         Icons.mjs, generated by kiosk/tools/lucide_paths.py
kiosk/fonts/         Figtree and IBM Plex Mono (SIL OFL)
kiosk/session/       labwc's config: no frames, no shortcuts, kanshi for the display layout
```

- **One process, the same API.** Everything the panel does goes through `/api/*`
  and `/api/ws`, so the agent lock, the confirm gate and `local_only.py` still
  apply. A crash on screen cannot stop the timers behind it.
- **Polling** is one `Panel` per live panel in `state/Live.qml` (same intervals as
  before), stopped while asleep or idle and refreshed on wake. A poll whose JSON
  did not change is dropped, so delegates are not rebuilt.
- **Pure logic goes in `lib/*.mjs`** and takes plain data (`describeTile` returns
  what a tile shows and which action a tap means; QML carries it out). That is
  what `kiosk/tests/*.test.mjs` can check without Qt.
- **Repaints only when something changes.** Clock on the minute, countdown labels
  on a 1 s timer that exists only on Home and Music, the track bar is one animation.
- **Icons** are lucide paths drawn by a `Shape` (`CurveRenderer`). To add one,
  put its name in `ICONS` in `kiosk/tools/lucide_paths.py` and run it.
- **Text fields use Wony's own keyboard** (`components/Field.qml`, `Keyboard.qml`):
  a focused `Field` becomes `Ui.keyTarget`; `Scroller` keeps it above the keyboard.
- **QML gotchas this code hit:** a property named `onSomething` is a signal
  handler (`Theme.accentInk`, not `onAccent`); an `id` called `left` resolves to
  nothing inside a delegate; declaring `property var data` on an `Item` swallows
  its children; a derived sheet cannot redeclare `closed`.

### Starting at boot

`./wony.sh autostart install` writes two units:

- `wony.service`, a systemd *user* unit (`wony.py kiosk`), with lingering enabled
  so it starts without a login.
- `wony-panel.service`, a *system* unit installed with sudo, that runs
  `wony.py session` as the owner on tty1. That builds the session's config
  (`helpers/session.py`) and becomes
  `labwc -C ~/.cache/wony/session -S "<python> wony.py panel"`. `-S` ends labwc
  when the panel exits, so `Restart=always` brings the whole session back in
  about 3 s. It has `Alias=display-manager.service`, so it
  replaces lightdm: install disables the current display manager, enables the
  panel unit and records both in `.wony_autostart.json` (gitignored);
  `autostart uninstall` restores them. Every sudo command is printed first, and a
  failure after the desktop was switched off switches it back on.

**Touch and rotation.** `-C` makes labwc ignore the user's own config, including
what Raspberry Pi's Screen Configuration wrote there. labwc rotates touch events
with a rotated screen only through a libinput `calibrationMatrix` in rc.xml
(labwc-config(5)), so without it a display set to landscape draws landscape and
taps portrait. `session.build` therefore copies `<touch>`, `<libinput>` and
`<tablet>` from the first rc.xml labwc would have read (the user's, else the
system's) into the session's rc.xml; their keybindings, theme and rules stay
out. Output rotation itself comes from kanshi, started by
`kiosk/session/autostart`.

It is never started by `install` itself: it would fight the running desktop for
the display, so it comes up at the next boot. `--no-screen` installs only the
first unit. A legacy `wony-kiosk.service` (Chromium) is removed on install.

### The sign-in browser

Google refuses sign-in inside embedded webviews (`disallowed_useragent`) and its
device-code flow does not allow Gmail or Calendar scopes, so consent needs a real
browser. `helpers/browser.sign_in()` is a context manager around one sign-in: it
registers a `webbrowser` browser that starts Chromium (`--app`, a throwaway
profile, on the panel's Wayland socket) and `wvkbd-mobintl`, and closes both on
the way out, however the sign-in ended. `google_auth._consent` passes its name to
`run_local_server(browser=...)` and `spotify._get_auth_code` to `webbrowser.get`.
With no Wayland session or no Chromium it opens the default browser instead.
The OAuth app is published ("In production", unverified), so a sign-in lasts.

### Starting with no AI key

The device still comes up: timers, music and the smart home need no key. The AI
service fails on its own and is left unregistered; `get_ai_client()` retries it
(re-reading `.env`) on every turn and, until a key exists, a turn answers with
`NO_AI_MESSAGE`. Startup also puts that message on the bell once.

## Telegram

`modules/telegram.py` is the panel's chat. It is a service that registers no
jobs, polls outward (no open port, no public URL), checks who is talking, and
calls `run_turn(text, at_machine=False)` — the same entry as everything else, so
the agent lock, the confirm gate and the untrusted fence all apply.

Its polling thread starts from `bootstrap._start_telegram`, not from `__init__`:
anything that merely imports `modules` (the tests, `doctor`) would otherwise
start taking the real bot's messages.

- **Who may talk:** one paired owner, stored in `modules.telegram.owner`. Pairing
  is a code kept in kv until used, announced through `notify(private=True)` and
  shown on the Settings screen by the service's `setting_note`
  (`settings._live_note`). It is a credential: never put it in anything the
  assistant reads (`settings.explain`, the README). Five wrong codes retire it;
  strangers get no reply.
- **`at_machine` vs `user_present`:** a chat user is present (can confirm) but
  not at the screen. `turn_context.at_machine()` gates anything that opens a
  window here — Google consent in `google_auth.credentials` and
  `google_accounts._authorize`. A new job that opens something on screen needs
  the same check.
- **Forwarded text** is someone else's words: pass it as `run_turn(quoted=...)`,
  never inside `user_input`, so it is fenced and not counted as the user's.
- **Stale messages:** Telegram queues for 24h. A message older than
  `_STALE_SECONDS` gets "I was off" and is not run.
- **Out:** the module listens on `helpers.events` and copies `notification`
  events to the owner.
- **Text only:** there is no speech recognition here, so a voice note gets a
  reply saying so.
- **Tests:** `tests/test_telegram.py` fakes the Bot API at `net.post`.

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
`turn.py`, Google auth and the Gmail/Calendar/Spotify/Home Assistant/Weather/
Telegram modules. A fix to any of them belongs on both: port it when you make
it, and say so in the commit. `google_auth.py` and `spotify.py` call
`helpers/browser.sign_in()`, so `main` needs a `helpers/browser.py` too (there it
just opens the default browser), and the Google wording ("signed me out", no
weekly or day-before warning) is the same on both. What is deleted here is
deleted, not switched off.
Telegram differs only where the device does: no voice notes, and it stays
running through sleep.
