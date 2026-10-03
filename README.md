# Wony — Personal AI Assistant

Wony runs on a small Linux box with a touch screen — a Raspberry Pi 4B is the
target. Tap a tile or type a question, and the answer appears on the display.
She can read your calendar and mail, control your lights, run your music and
set timers. (The full assistant, with web browsing, maps and Drive, is the PC
version.)

You only get the parts you set up. Anything you skip is quietly left out.

## What you need

- A Raspberry Pi (or any computer) running **64-bit** Raspberry Pi OS or Linux
- Python 3.10 or newer
- An API key from Anthropic or Gemini — or your own Ollama server
- A touch screen, if you want to use it by hand

| AI service         | What happens to your requests                                                |
| ------------------ | ---------------------------------------------------------------------------- |
| Anthropic (Claude) | Not used to train Anthropic's models. Paid.                                  |
| Google Gemini      | Free tier: reviewed and used to train Google's models. A paid key isn't.     |
| Ollama             | Stays on your own server.                                                    |

With both a Claude and a Gemini key set and no provider chosen, Wony answers
with Claude.

## Install

Run the setup script first. It creates everything, asks which features you want,
and installs only those.

```bash
python setup.py
```

It will:

1. Offer to create a project virtual environment (recommended — say yes)
2. Create `.env` and `config.yaml`
3. Show a checklist of features — arrow keys to move, space to tick, enter to confirm
4. Install what you ticked
5. Ask for the keys, credentials and permissions those features need — checking
   each key against the service, and opening a browser for the Spotify and
   Google sign-ins

Press Enter to skip anything you do not have yet; it lists what is left. To come
back to that part on its own:

```bash
python setup.py configure
```

Then build the screen:

```bash
cd kiosk
npm install
npm run build
```

You can re-run `python setup.py` any time to add or remove features. It keeps
your settings and skips anything already installed.

## Start it

```bash
./venv/bin/python wony.py doctor   # check everything is set up
./venv/bin/python wony.py          # start
```

Open `http://localhost:8000` on the device. Other ways to start:

| Command                 | What it does                                       |
| ----------------------- | -------------------------------------------------- |
| `python wony.py`        | Normal start — the screen and everything behind it |
| `python wony.py text`   | Type to Wony in a terminal instead                 |
| `python wony.py doctor` | Check the setup and exit                           |

## Using the screen

The panel is touch-only — no typing, no microphone. Four tabs across the
bottom: **Home**, **Rooms**, **Music**, **Macros**.

**Home** is a grid of tiles you arrange yourself: tap **Edit**, then **+ Add
tile** for anything not already placed, or the × on a tile to remove it. A
tile is a routine, a device, a 10-minute timer, music play/pause, or Sleep —
whole-button actions that run the moment you tap them, no confirmation needed
except for a locked door or an alarm. The layout is saved on the device itself,
not in `config.yaml` — there is nothing to hand-edit here. Next to the grid, a
Now playing card and a Coming up list (your next timers, events and reminders)
stay visible without a tap.

**Rooms** lists your Home Assistant devices by room, one card each — a switch,
a slider, Open/Stop/Close, a thermostat's ± , a lock, or a vacuum's Start/Dock
— built from whatever `modules.home_assistant` reports.

**Music** is cover art, transport controls, volume and your playlists, wired
to Spotify.

**Macros** holds every routine you have as a tile (tap to run it), plus a row
of quick timers (1/5/10/15/30/60 minutes).

The **gear** icon in the header opens **Settings**, **Accounts** and **Sleep**
as a System view — see below.

### Routines

Say _"save a routine called good night that turns off the lights and sets an
alarm for seven"_ to your phone or desktop Wony, then run it from the panel's
Macros tab, or a Home tile you've added for it. A routine is just your own
words, so it can use anything Wony can do. Saving or deleting one is read back
to you first. The panel has no keyboard, so routines are made and edited from
another Wony surface (phone, desktop) and simply appear here to run.

**Notifications** appear when something happens on its own — a timer going off,
new mail arriving. The bell in the header shows how many are waiting; tap it to
read and dismiss them.

**The clock screen** takes over when nobody has touched anything for a while. It
shows the time, the date, and what is next in your calendar. Touch anywhere to
go back.

**Sleep** is for the end of the day, in the System view: pick a wake time or
"until I touch the screen", and the display goes dark — but nothing shuts
down, so your timers still go off overnight and waking is instant. Touch
anywhere to come back. Whatever you picked is what it offers you tomorrow
night.

## Start at boot

Setup offers this at the end. To do it later:

```bash
python wony.py autostart install
```

Wony and the screen now come up on their own whenever the device is switched on,
without anyone logging in.

```bash
python wony.py autostart status      # is it running?
python wony.py autostart uninstall   # stop doing that
```

On a device with no display, add `--no-browser`.

## Settings

Tap the **cog** in the top bar. Everything there is also in `config.yaml`, which
you can still edit by hand; the screen just means you do not have to find a
keyboard. Your passwords and keys live in `.env`, and never go anywhere else.

The settings screen changes the assistant's name and personality, which AI
provider answers, which features are switched on, what Wony may do on its own,
and how long the screen waits before showing the clock. It also tells you
whether a newer Wony is waiting — it never installs one; that is `git pull` and
`python setup.py`, run by you.

```yaml
assistant:
  name: "Wony"
  owner_name: "Jakub"
  personality: "Friendly and concise."
  language: "en" # "en", "pl", ...

ai:
  provider: null # leave empty to pick automatically
  ollama_model: "llama3.1"

# Only what is listed here is switched on.
enabled_modules:
  - basics # time, date, sleep, power off
  - routines # the briefing, and any you save yourself
  - scheduler # timers, alarms, reminders
  - notes # shopping and todo lists
  - weather
  - gmail
  - calendar
  # - system           # disk space, memory, processor load, network
  # - spotify
  # - home_assistant

kiosk:
  idle_minutes: 15 # minutes untouched before the clock screen appears
  home_columns: 3 # 3 or 4 tiles across on the Home tab
  confirm_all_devices: false # true: every device tap asks first, like a lock
```

The Home tab's own tile layout is arranged by touch (**Edit**, on the panel)
and saved on the device — there is no `tiles:` list in `config.yaml` to hand-edit.

A few things are switched off until you say otherwise, so nothing surprising can
happen by accident. All six are on the settings screen too:

| Setting                              | Allows                                                                   |
| ------------------------------------ | ------------------------------------------------------------------------ |
| `modules.basics.allow_power_off`     | Switching the device off or restarting it from the screen                |
| `modules.gmail.allow_write`          | Sending, replying to and deleting email. Off, Wony saves a draft instead |
| `modules.calendar.allow_write`       | Creating, changing and deleting events                                   |
| `modules.home_assistant.allow_locks` | Unlocking doors, opening the garage, disarming alarms                    |
| `assistant.proactive.enabled`        | Speaking up on its own about a drive nearly full, the device running hot, a meeting about to start, or important mail |
| `assistant.memory.learn_from_my_data` | Keeping facts it works out from your own conversations, and how you write from your sent mail |

**Speaking up on its own** says it in Wony's own words rather than a canned
alert. Ask _"what do you watch for"_ to see the list, or _"stop watching for
important email"_ to switch one off. A meeting about to start comes with who is
coming, what you last wrote to them and anything on your lists with its name on
it. _"Watch my inbox"_ and _"watch my calendar"_ add new mail and new events to
the list, whatever that switch says. What you turn on or off is remembered.

Temperatures follow the device's region; say _"remember I prefer Fahrenheit"_ to
change that. Claude and Gemini always use their fastest model.

**Learning about you** keeps the things you mention in passing — the dog's name,
that you cycle to work — instead of only what you say "remember that" about.
With Gmail on it also reads your sent mail once a week to describe how you
write, so a drafted reply sounds like you. Ask _"what do you know about me"_ to
see everything it kept; the ones it worked out for itself say so, and _"forget
that"_ throws one away.

Separately from those switches, anything that changes something you care about —
sending or deleting mail, changing your calendar, cancelling a timer, powering
the device down — is read back to you first and only happens once you say yes.
Tapping it on a screen gives you a confirm dialog; asking for it in words means
Wony tells you what it is about to do and waits for an answer.

## Connecting your services

### Weather

1. Get a free key at [openweathermap.org/api](https://openweathermap.org/api)
2. Paste it when setup asks. A brand-new key can take up to two hours to work.

### Gmail and Calendar

Both share **one sign-in per account**, and Wony asks Google only for what your
switches allow: read-only until "Change my mailbox" or "Change my calendar" is
on, which then asks Google once more.

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the Gmail
   and Calendar APIs, set the OAuth consent screen to **External** in
   **Testing**, add your own address as a test user, and create an OAuth client
   of type **Desktop**
2. Download the JSON. Setup offers the one it finds in your Downloads folder, or
   takes the path — it files it away and opens the browser for consent

Google will say it **hasn't verified this app** — it is your own app: tap
**Advanced**, then continue.

Want a second mailbox? Tap **Accounts** on the home screen and add one. Give it a
short name — "work", "personal" — and a browser opens for you to sign in with
Google. Add as many as you like; the one marked with a star is the one Wony uses
when you don't say which.

Signing in has to happen on the Pi's own screen, or on another computer with the
`credentials/` folder copied across afterwards.

**Google signs Wony out every 7 days** — its rule for apps in Testing (publishing
needs a public website, privacy policy and terms). Wony tells you once, warns you
the day before, and the Accounts screen shows **Sign in again**. Updating from a
version with separate Gmail and Calendar sign-ins asks you to sign in once.

### Spotify

1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Set the Redirect URI to `http://127.0.0.1:8888/callback`
3. Paste the client ID and secret when setup asks — it opens a browser once to
   connect your account

You get a music screen with cover art, play controls and volume. The sound comes
out of whichever speaker Spotify is playing on.

To play the music on the Pi itself, install
[raspotify](https://dtcooper.github.io/raspotify/) and then pick the device by
name in any Spotify app:

```bash
sudo apt-get -y install curl && curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
```

Needs Spotify Premium. Raspotify is made by someone else and is intended for
personal use only.

### Home Assistant

Controls whatever Home Assistant controls — lights, switches, blinds,
thermostats, media players, vacuums, locks, scenes — by name or by room,
including devices added through HACS. Try "dim the bedroom lamp to 30", "close
the blinds", "is the garage open", "start the vacuum", "set the suction to
turbo", "turn all the lights off".

A room or a device type has to be named before Wony will change a whole set of
things at once, and anything you have hidden in Home Assistant stays hidden
here.

1. In Home Assistant: your profile → **Security** → **Long-lived access tokens**
   → _Create token_
2. Paste it when setup asks, along with the address you open Home Assistant at.
   Setup checks both before saving them.

The **Devices** tile then lists your devices by room, one card each, with its
switch, slider and settings on it. Doors, garages and alarms are shown but stay
locked until you set `modules.home_assistant.allow_locks: true`.

### Ollama, for a local AI

```bash
ollama serve
```

Then set `ai.provider: ollama` and `ai.ollama_model` in `config.yaml`. A Pi with
2 GB of memory cannot run a useful model itself, so point `OLLAMA_HOST` at
another machine on your network.

### Long-term memory

Lets Wony search everything she has been told by meaning rather than by keyword.
No key needed — tick it during setup. Uses about 120 MB of memory, so leave it
out if the device is short on it.

## Privacy

Conversations, remembered facts, lists and reminders live in `wony.db` in this
folder. **Wipe data** deletes that file's contents, the Spotify sign-in cache and
every log file. It does not remove your API keys or Google sign-ins; delete those
by hand (`.env`, `credentials/`).

What leaves the device, and only when a feature you set up needs it:

| Goes to                       | What                                                        |
| ----------------------------- | ----------------------------------------------------------- |
| Your AI service               | Your requests, recent turns, remembered facts and whatever it reads to answer (mail, calendar entries) |
| OpenWeatherMap, OpenStreetMap | A city name or coordinates for the weather                  |
| ipinfo.io                     | Only to guess your city when `assistant.home_address` is empty |
| Google (Gmail, Calendar)      | What the feature needs, once signed in                      |
| Spotify, Home Assistant       | Playback and device commands                                |

No telemetry. Keys and `appid=`/`key=`/`token=` values are removed from the logs.

## If something goes wrong

Start here — it checks everything and tells you exactly what to fix:

```bash
python wony.py doctor
```

You can also just ask Wony "check setup" on the screen.

| Problem                                    | Fix                                                                    |
| ------------------------------------------ | ---------------------------------------------------------------------- |
| The screen is blank                        | The screen was never built: `cd kiosk && npm install && npm run build` |
| You rebuilt, but the screen looks the same | Press Ctrl+Shift+R once to refresh it properly                         |
| "AI provider not ready"                    | `python setup.py configure` and give it a key, then restart            |
| The screen stays lit after Sleep           | `sudo apt install wlopm`, then check with `python wony.py doctor`      |
| Nothing happens after a reboot             | Run `python wony.py autostart install` again                           |
| The screen never appears at boot           | `systemctl --user status wony-kiosk`                                   |
| "Port already in use"                      | Wony is already running: `systemctl --user stop wony`                  |
| Something else                             | `journalctl --user -u wony -f` shows what she is doing                 |

Logs are also kept in the `logs/` folder, and tidied up automatically.

---

Building on Wony or curious how she works inside? See
[docs/development.md](docs/development.md).
