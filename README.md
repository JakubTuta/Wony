# Wony — Personal AI Assistant

Wony runs on a small Linux box with a touch screen — a Raspberry Pi 4B is the
target. Tap a tile or type a question, and the answer appears on the display.
She can read your calendar and mail, control your lights, run your music, set
timers and search the web.

You only get the parts you set up. Anything you skip is quietly left out.

## What you need

- A Raspberry Pi (or any computer) running **64-bit** Raspberry Pi OS or Linux
- Python 3.10 or newer
- An API key from Anthropic or Gemini — or your own Ollama server
- A touch screen, if you want to use it by hand

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

**Tiles** are the buttons on the home screen. Wony chooses a set based on what
you have enabled, and you can replace them with your own list — see Settings
below. Some answer on the spot; others open a page:

| Tile     | What you get                                                    |
| -------- | --------------------------------------------------------------- |
| Weather  | Temperature, conditions, wind, humidity, sunrise and sunset     |
| Today    | Today's and tomorrow's calendar, as a list                      |
| Timers   | Everything counting down, with a button to call one off         |
| Devices  | Every device you have, by room, one card each, with its controls |
| Music    | Cover art, play controls and volume                             |
| Accounts | Add, sign in to and switch Google accounts                      |
| Sleep    | Sends the screen dark for the night                             |

You can still ask Wony any of this in words — the tiles are the quicker way,
not the only one.

**Typing.** Tap the box at the bottom to bring up the on-screen keyboard. If you
plug in a USB or Bluetooth keyboard, just start typing anywhere and Wony picks
it up. Press Enter to send.

**Notifications** appear when something happens on its own — a timer going off,
new mail arriving. They wait on the screen until you tap them away, so nothing
is missed while you are out of the room.

**The clock screen** takes over when nobody has touched anything for a while. It
shows the time, the date, what is next in your calendar, and anything waiting
for you. Touch anywhere to go back.

**The Sleep tile** is for the end of the day. Pick a wake time or "until I
touch the screen", and the display goes dark — but nothing shuts down, so your
timers still go off overnight and waking is instant. Touch anywhere to come
back, or ask her ("go to sleep until seven"). Whatever you picked is what it
offers you tomorrow night.

**Two looks**, light and dark. Tap the sun or moon in the top bar to switch. The
screen remembers your choice.

**Settings** are behind the cog in the top bar — see below.

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
  - ai
  - status
  - basics # time, date, daily briefing
  - scheduler # timers, alarms, reminders
  - weather
  - gmail
  - calendar
  # - spotify
  # - home_assistant
  # - web              # web search
  # - mcp

# The buttons on the home screen. Leave this out and Wony picks them for you.
tiles:
  - id: agenda
    label: "Today"
    icon: "📅"
    kind: prompt
    prompt: "What's on my calendar today?"

kiosk:
  idle_minutes: 15 # minutes untouched before the clock screen appears
```

A few things are switched off until you say otherwise, so nothing surprising can
happen by accident. All four are on the settings screen too:

| Setting                              | Allows                                                                   |
| ------------------------------------ | ------------------------------------------------------------------------ |
| `modules.basics.allow_power_off`     | Switching the device off or restarting it from the screen                |
| `modules.gmail.allow_write`          | Sending, replying to and deleting email. Off, Wony saves a draft instead |
| `modules.calendar.allow_write`       | Creating, changing and deleting events                                   |
| `modules.home_assistant.allow_locks` | Unlocking doors, opening the garage, disarming alarms                    |

## Connecting your services

### Weather

1. Get a free key at [openweathermap.org/api](https://openweathermap.org/api)
2. Paste it when setup asks. A brand-new key can take up to two hours to work.

### Gmail and Calendar

1. In [Google Cloud Console](https://console.cloud.google.com/), create an OAuth
   client of type **Desktop** with the Gmail and Calendar APIs enabled, and add
   your own address as a test user on the consent screen
2. Download the JSON. Setup offers the one it finds in your Downloads folder, or
   takes the path — it files it away and opens the browser for consent

Want a second mailbox? Tap **Accounts** on the home screen and add one. Give it a
short name — "work", "personal" — and a browser opens for you to sign in with
Google. Add as many as you like; the one marked with a star is the one Wony uses
when you don't say which.

Signing in has to happen on the Pi's own screen, or on another computer with the
`credentials/` folder copied across afterwards.

If an account stops working — Google expires these on its own, and changing your
password expires them all — open it from the Accounts screen and tap **Sign in
again**.

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

### Web search

Tick **web** during setup. No key and nothing else to set up.

### Ollama, for a local AI

```bash
ollama serve
```

Then set `ai.provider: ollama` and `ai.ollama_model` in `config.yaml`. A Pi with
2 GB of memory cannot run a useful model itself, so point `OLLAMA_HOST` at
another machine on your network.

### Long-term memory

Lets Wony search everything she has been told by meaning rather than by keyword,
and read documents you give her. No key needed — tick it during setup. Ask her
to "index document" to add a file. Uses about 120 MB of memory, so leave it out
if the device is short on it.

### Connecting other tools (MCP)

Tick `mcp` during setup, then ask Wony in plain words, for example: _"Add an MCP
server called filesystem at command npx -y @modelcontextprotocol/server-filesystem"_.

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
