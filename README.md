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
2. Create `.env` and `config.yaml`, asking for your AI key
3. Show a checklist of features — arrow keys to move, space to tick, enter to confirm
4. Install what you ticked

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

| Command | What it does |
| --- | --- |
| `python wony.py` | Normal start — the screen and everything behind it |
| `python wony.py text` | Type to Wony in a terminal instead |
| `python wony.py doctor` | Check the setup and exit |

## Using the screen

**Tiles** are the buttons on the home screen. Wony chooses a set based on what
you have enabled, and you can replace them with your own list — see Settings
below. Some answer on the spot; others open a page:

| Tile | What you get |
| --- | --- |
| Weather | Temperature, conditions, wind, humidity, sunrise and sunset |
| Today | Today's and tomorrow's calendar, as a list |
| Devices | Every smart device you have, by room, with switches and dimmers |
| Music | Cover art, play controls and volume |
| Accounts | Add, sign in to and switch Google accounts |

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

**Two looks**, light and dark. Tap the sun or moon in the top bar to switch. The
screen remembers your choice.

## Start at boot

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

Your choices live in `config.yaml`. Your passwords and keys live in `.env`, and
never go anywhere else.

```yaml
assistant:
  name: "Wony"
  owner_name: "Jakub"
  personality: "Friendly and concise."
  language: "en"        # "en", "pl", ...

ai:
  provider: null        # leave empty to pick automatically
  ollama_model: "llama3.1"

# Only what is listed here is switched on.
enabled_modules:
  - ai
  - status
  - basics             # time, date, daily briefing
  - scheduler          # timers, alarms, reminders
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
  idle_minutes: 15      # minutes untouched before the clock screen appears
```

A few things are switched off until you say otherwise, so nothing surprising can
happen by accident:

| Setting | Allows |
| --- | --- |
| `modules.basics.allow_power_off` | Switching the device off or restarting it from the screen |
| `modules.gmail.allow_send` | Sending and replying to email |
| `modules.calendar.allow_write` | Creating, changing and deleting events |
| `modules.home_assistant.allow_locks` | Unlocking doors, opening the garage, disarming alarms |

## Connecting your services

### Weather

1. Get a free key at [openweathermap.org/api](https://openweathermap.org/api)
2. Add to `.env`: `WEATHER_API_KEY="..."`

### Gmail and Calendar

1. Follow the [simplegmail setup guide](https://pypi.org/project/simplegmail/) to
   create Google credentials
2. Save the file as `google_credentials.json` inside `credentials/`
3. Enable `gmail`, `calendar` and `google_accounts` in `config.yaml`

Then tap **Accounts** on the home screen and add one. Give it a short name —
"work", "personal" — and a browser opens for you to sign in with Google. Add as
many as you like; the one marked with a star is the one Wony uses when you don't
say which.

Signing in has to happen on the Pi's own screen, or on another computer with the
`credentials/` folder copied across afterwards.

If an account stops working — Google expires these on its own, and changing your
password expires them all — open it from the Accounts screen and tap **Sign in
again**.

### Spotify

1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Set the Redirect URI to `http://127.0.0.1:8888/callback`
3. Add to `.env`:

   ```env
   SPOTIFY_CLIENT_ID="..."
   SPOTIFY_CLIENT_SECRET="..."
   ```

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
thermostats, media players, locks, scenes — by name or by room. Try "dim the
bedroom lamp to 30", "close the blinds", "is the garage open".

1. In Home Assistant: your profile → **Security** → **Long-lived access tokens**
   → *Create token*
2. Add it to `.env`:

   ```env
   HOME_ASSISTANT_TOKEN="..."
   ```

3. Put your Home Assistant address in `config.yaml` under
   `modules.home_assistant.base_url`, and enable `home_assistant`

The **Devices** tile then lists everything by room, with a switch on each and a
slider on any light that is on. Doors, garages and alarms are shown but stay
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

Tick `mcp` during setup, then ask Wony in plain words, for example: *"Add an MCP
server called filesystem at command npx -y @modelcontextprotocol/server-filesystem"*.

## If something goes wrong

Start here — it checks everything and tells you exactly what to fix:

```bash
python wony.py doctor
```

You can also just ask Wony "check setup" on the screen.

| Problem | Fix |
| --- | --- |
| The screen is blank | The screen was never built: `cd kiosk && npm install && npm run build` |
| You rebuilt, but the screen looks the same | Press Ctrl+Shift+R once to refresh it properly |
| "AI provider not ready" | Add an API key to `.env`, then restart |
| Nothing happens after a reboot | Run `python wony.py autostart install` again |
| The screen never appears at boot | `systemctl --user status wony-kiosk` |
| "Port already in use" | Wony is already running: `systemctl --user stop wony` |
| Something else | `journalctl --user -u wony -f` shows what she is doing |

Logs are also kept in the `logs/` folder, and tidied up automatically.

---

Building on Wony or curious how she works inside? See
[docs/development.md](docs/development.md).
