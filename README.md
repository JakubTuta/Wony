# Wony — Personal AI Assistant

Wony runs on a small Linux box with a touch screen — a Raspberry Pi 4B is the
target. Tap a tile and the answer appears on the display. It can read your
calendar and mail, control your lights, run your music and set timers. (The
full assistant, with voice, web browsing, maps and Drive, is the PC version.)

You only get the parts you set up. Anything you skip is quietly left out.

## What you need

- A Raspberry Pi (or any computer) running **64-bit** Raspberry Pi OS or Linux
- Python 3.10 or newer (`./wony.sh` finds `python` or `python3` itself, and tells you
  what to install if there is neither)
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
./wony.sh setup
```

It will:

1. Offer to create a project virtual environment (recommended — say yes)
2. Create `.env` and `config.yaml`
3. Show a checklist of features — arrow keys to move, space to tick, enter to confirm
4. Install what you ticked
5. Ask for the keys, credentials and permissions those features need — checking
   each key against the service, and opening a browser for the Spotify and
   Google sign-ins — and how you want Wony to behave: its personality, whether
   it may speak up on its own or learn about you, and when the screen goes to
   the clock. Every answer can be changed later on the Settings screen.

Press Enter to skip anything you do not have yet; it lists what is left. To come
back to that part on its own:

```bash
./wony.sh setup configure
```

Then build the screen:

```bash
cd kiosk
npm install
npm run build
```

You can re-run `./wony.sh setup` any time to add or remove features. It keeps
your settings and skips anything already installed.

## Start it

```bash
./wony.sh doctor   # check everything is set up
./wony.sh          # start
```

If a copy of Wony lost its executable bit on the way here, `chmod +x wony.sh`
once. Open `http://localhost:8000` on the device. Other ways to start:

| Command            | What it does                                       |
| ------------------ | -------------------------------------------------- |
| `./wony.sh`        | Normal start — the screen and everything behind it |
| `./wony.sh text`   | Type to Wony in a terminal instead (see below)     |
| `./wony.sh doctor` | Check the setup and exit                           |

## Using the screen

The panel has no chat and no microphone: you tap. (A text field in Settings
raises the display's own keyboard.) Four tabs across the bottom: **Home**,
**Rooms**, **Music**, **Macros**.

**Home** is a grid of tiles you arrange yourself: tap **Edit**, then **+ Add
tile** for anything not already placed, or the × on a tile to remove it. A
tile is a routine, a device, a 10-minute timer, music play/pause, or Sleep —
whole-button actions that run the moment you tap them, no confirmation needed
except for a locked door or an alarm. The layout is saved on the device itself.
Next to the grid, a Now playing card and a Coming up list (your next timers,
events and reminders) stay visible without a tap.

**Rooms** lists your Home Assistant devices by room, one card each — a switch,
a slider, Open/Stop/Close, a thermostat's ± , a lock, or a vacuum's Start/Dock
— built from whatever Home Assistant reports.

**Music** is cover art, transport controls, volume and your playlists, wired
to Spotify.

**Macros** holds every routine you have as a tile (tap to run it), plus a row
of quick timers (1/5/10/15/30/60 minutes).

The **gear** icon in the header opens **Settings**, **Accounts** and **Sleep**
as a System view — see below.

### Routines

Say _"save a routine called good night that turns off the lights and sets an
alarm for seven"_ in `./wony.sh text` (over SSH, or from a keyboard plugged
in), then run it from the panel's Macros tab, or a Home tile you've added for
it. A routine is just your own words, so it can use anything Wony can do.
Saving or deleting one is read back to you first. The panel has no chat, so
routines are made and edited in the terminal and simply appear here to run.
Routines live in this device's own `wony.db`; a Wony on another computer has
its own and shares nothing with it.

Only one Wony runs at a time, so `./wony.sh text` refuses to start while the
screen is up. Stop the screen for as long as you type: `systemctl --user stop wony`,
then `systemctl --user start wony` afterwards.

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

### Asking Wony about itself

The panel itself has no chat, but in `./wony.sh text` you can ask _"how long
before the clock screen shows"_, _"how do I set up Gmail"_ or _"why is the weather
switched off"_. Wony looks the answer up in its own settings and in this guide
instead of guessing, and tells you where to change something. It cannot change a
setting for you, and it never shows your keys. Ask _"check setup"_ there for the
same checklist as `./wony.sh doctor`.

## Start at boot

Setup offers this at the end. To do it later:

```bash
./wony.sh autostart install
```

Wony and the screen now come up on their own whenever the device is switched on,
without anyone logging in.

```bash
./wony.sh autostart status      # is it running?
./wony.sh autostart uninstall   # stop doing that
```

On a device with no display, add `--no-browser`.

## Settings

Tap the **cog** in the top bar, then **Settings**. You never need a text editor:
everything you might want to change is here, except passwords and keys.

- **Assistant** — its name, what it calls you, its personality, and your home
  address for local weather
- **AI** — which service answers, the Ollama model, and how many past exchanges
  it keeps in mind
- **What Wony may do on its own** — the switches below
- **This device** — where Home Assistant lives, your working day, how long the
  screen waits before showing the clock, how many tiles fit across the Home
  tab, whether every device tap asks first, and the port of the web page
- **Features** — an on/off switch for each feature
- **Updates** — whether a newer Wony is waiting. It never installs one; that is
  `git pull` and `./wony.sh setup`, run by you.

Passwords and keys are not on the screen. They live in `.env`, are added with
`./wony.sh setup configure`, and never go anywhere else.

These six start **off**, so nothing surprising can happen by accident. Turn them
on under **Settings → What Wony may do on its own**:

| Switch                           | Allows                                                                   |
| -------------------------------- | ------------------------------------------------------------------------ |
| Power off this device            | Switching the device off or restarting it from the screen                |
| Change my mailbox                | Sending, replying to and deleting email. Off, Wony saves a draft instead |
| Change my calendar               | Creating, changing and deleting events                                   |
| Unlock doors and open the garage | Unlocking doors, opening the garage, disarming alarms                    |
| Speak up on its own              | Speaking up about a drive nearly full, the device running hot, a meeting about to start, or important mail |
| Learn about me on its own        | Keeping facts it works out from your own conversations, and how you write from your sent mail |

**Speaking up on its own** says it in Wony's own words rather than a canned
alert. It mentions each email once; the email stays unread in Gmail. Ask _"what
do you watch for"_ to see the list, or _"stop watching my inbox"_ to switch the
mail watcher off. A meeting about to start comes with who is coming, what you
last wrote to them and anything on your lists with its name on it. _"Watch my
inbox"_ widens the mail watcher from important mail to all new mail, and _"watch
my calendar"_ adds new events to the list, whatever that switch says. What you
turn on or off is remembered.

Temperatures follow the device's region; say _"remember I prefer Fahrenheit"_ to
change that. Claude and Gemini always use their fastest model.

**Learning about you** keeps the things you mention in passing — the dog's name,
that you cycle to work — instead of only what you say "remember that" about.
With Gmail on it also reads your sent mail once a week to describe how you
write, so a drafted reply sounds like you. Ask _"what do you know about me"_ to
see everything it kept; the ones it worked out for itself say so, and _"forget
that"_ throws one away. _"What's going on with Anna"_ gathers what you told it
about her, your recent mail and meetings with her, and past chats that name her.

Separately from those switches, anything that changes something you care about —
sending or deleting mail, changing your calendar, cancelling a timer, powering
the device down — is read back to you first and only happens once you say yes.
Tapping it on a screen gives you a confirm dialog; asking for it in words means
Wony tells you what it is about to do and waits for an answer — a plain _"yes"_
or _"no"_ is enough. Small changes — a light, a list, a playlist, a timer — just
happen; _"undo"_ takes back the last one from the past 15 minutes.

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
locked until you turn on **Unlock doors and open the garage** in Settings.

### Ollama, for a local AI

```bash
ollama serve
```

Then pick **Ollama** under **Settings → AI** and type the model's name. A Pi with
2 GB of memory cannot run a useful model itself, so point `OLLAMA_HOST` at
another machine on your network.

### Long-term memory

Lets Wony search everything it has been told by meaning rather than by keyword.
No key needed — tick it during setup. Uses about 120 MB of memory, so leave it
out if the device is short on it.

## Privacy

Conversations, remembered facts, lists and reminders live in `wony.db` in this
folder. The panel has no button to clear it. To start clean, stop Wony and delete
`wony.db`, `cache.json` (the Spotify sign-in) and the files in `logs/`; they are
made again on the next start. Your API keys and Google sign-ins are separate:
delete those by hand (`.env`, `credentials/`).

What leaves the device, and only when a feature you set up needs it:

| Goes to                       | What                                                        |
| ----------------------------- | ----------------------------------------------------------- |
| Your AI service               | Your requests, recent turns, remembered facts and whatever it reads to answer (mail, calendar entries) |
| OpenWeatherMap, OpenStreetMap | A city name or coordinates for the weather                  |
| ipinfo.io                     | Only to guess your city when no home address is set in Settings |
| Google (Gmail, Calendar)      | What the feature needs, once signed in                      |
| Spotify, Home Assistant       | Playback and device commands                                |

No telemetry. Keys and `appid=`/`key=`/`token=` values are removed from the logs.

## If something goes wrong

Start here — it checks everything and tells you exactly what to fix:

```bash
./wony.sh doctor
```

The same checklist is there when you type "check setup" in `./wony.sh text`.

| Problem                                    | Fix                                                                    |
| ------------------------------------------ | ---------------------------------------------------------------------- |
| The screen is blank                        | The screen was never built: `cd kiosk && npm install && npm run build` |
| You rebuilt, but the screen looks the same | Press Ctrl+Shift+R once to refresh it properly                         |
| "No AI service is set up yet"              | Add a key with `./wony.sh setup configure`, then try again             |
| The screen stays lit after Sleep           | `sudo apt install wlopm`, then check with `./wony.sh doctor`           |
| Nothing happens after a reboot             | Run `./wony.sh autostart install` again                                |
| The screen never appears at boot           | `systemctl --user status wony-kiosk`                                   |
| "Wony is already running"                  | Only one runs at a time: `systemctl --user stop wony`                  |
| Something else                             | `journalctl --user -u wony -f` shows what it is doing                  |

Logs are also kept in the `logs/` folder, and tidied up automatically.

Changing Wony itself? See [docs/developers.md](docs/developers.md).
