# Wony

A personal AI assistant that runs on your own Windows PC. Talk to it or type to
it, and it can handle your email, calendar, music, smart home, timers and the
web — using whatever you switch on, and nothing you don't.

- **Say "hey jarvis"**, press a hotkey, or just type in the browser.
- **Everything is off by default.** It cannot send an email, change your
  calendar or unlock a door until you allow it.
- **Your data stays on your machine** — history, notes and reminders live in a
  file next to the app. Only what you ask goes to your AI provider.

---

## Install

1. **Get the code.** Download this folder, or `git clone` it.
2. **Double-click `install.bat`.** It checks for Python, installs what is
   missing, and asks which features you want (arrow keys to move, space to tick,
   Enter to confirm).
3. **Double-click `Wony.bat`.** A tray icon appears near the clock, and the chat
   page opens at http://127.0.0.1:8000.

`Wony.bat` is how you start it every time — keep a shortcut to it somewhere
handy, or have it start by itself when you log in:

```powershell
python wony.py autostart install
```

You need one AI key. The installer asks for it and writes it to `.env`:

| Provider | Where to get a key | Cost |
| --- | --- | --- |
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com) | paid |
| Google Gemini | [aistudio.google.com](https://aistudio.google.com/apikey) | free tier |
| Ollama | nothing to get — it runs on your own PC | free, slower |

Prefer the terminal? `python setup.py`, then `python wony.py`.

**Something not working?** Run `python wony.py doctor` for a checklist with
fixes, or ask Wony "check setup".

---

## Using it

**Type** in the chat page, or **talk**:

| Way in | How |
| --- | --- |
| Wake word | Say the wake phrase, then your request. Off until you switch it on. |
| Hotkey | `Ctrl + Alt + W` anywhere in Windows. |
| Tray icon | Right-click → **Listen now**. |
| Browser | The microphone button in the chat page. |

Things to try: *"what's the weather"*, *"set a timer for 10 minutes"*, *"read my
last email"*, *"what's on my calendar tomorrow"*, *"play some jazz"*, *"turn off
the kitchen light"*, *"remember I prefer metric"*, *"what did we talk about on
Monday"*.

A timer can also run something else when it fires, which is how you get a daily
briefing: *"every weekday at 8am run greeting"* reads out the time, weather,
unread email and today's meetings. Others: *"in 10 minutes pause the music"*,
*"every day at 7am turn on the bedroom light"*.

Say *"thanks"*, *"stop"* or *"that's all"* to end a spoken conversation.

### The chat page

Two halves: the conversation on the left, and on the right the things worth
looking at rather than asking about.

| Panel | Appears when you enable | Shows |
| --- | --- | --- |
| Weather | Weather | Temperature, wind, humidity, sunrise and sunset |
| Today | Google Calendar | Today's and tomorrow's events |
| Timers | Timers & reminders | Everything counting down, with a cancel button |
| Devices | Home Assistant | Every smart device by room, with switches and dimmers |
| Music | Spotify | Cover art, transport and volume |
| Accounts | Google accounts | Add, sign in to and switch Google accounts |
| Settings | always | Everything below, without touching a config file |

The **bell** in the header holds anything Wony said while you were away — a
timer that fired, new email it spotted. **All commands** at the bottom opens
every command it knows, with a form for each.

### The tray icon

Right-click it for: **Open in web**, **Listen now**, **Stop speaking**,
**Mute**, **Wake word on/off**, **Settings**, **Check for updates**,
**Pause assistant**, **Exit**.

To start Wony automatically when you log in:

```powershell
python wony.py autostart install     # undo with: autostart uninstall
```

---

## Settings

Open the chat page → **Settings**. Everything there is also in `config.yaml`,
which you can still edit by hand; the page just means you don't have to.

You can change the assistant's name and personality, the voice and how fast it
speaks, the wake word and hotkey, which AI provider answers, and which features
are switched on.

### What Wony may do on its own

These four start **off**. Nothing else can turn them on.

| Switch | Off (the default) | On |
| --- | --- | --- |
| Send and delete email | Writes a draft in Gmail for you to send | Sends and deletes for you |
| Change my calendar | Tells you what to add | Creates, edits and deletes events |
| Unlock doors and open the garage | Lights and blinds still work | Locks, garage and alarms too |
| Type and click for me | Can look at the screen | Can type, click and open files |

They are `modules.gmail.allow_write`, `modules.calendar.allow_write`,
`modules.home_assistant.allow_locks` and `modules.desktop.allow_actions` in
`config.yaml`.

> **Keep `server.host` at `127.0.0.1`.** The web page has no password and can
> run every command Wony has. On any other address, anyone who can reach the
> port gets all of it.

---

## Features you can switch on

Tick these during `install.bat`, or on the Settings page. Anything whose setup
is incomplete simply stays off — nothing crashes, and `doctor` says what is
missing.

| Feature | Extra setup |
| --- | --- |
| Everyday basics — time, date, daily briefing | none |
| Timers, alarms and reminders | none |
| Weather | free key from [openweathermap.org/api](https://openweathermap.org/api) |
| Web search and page reading | none (optional `TAVILY_API_KEY` for better results) |
| Voice — speech in and out | none; downloads its speech models once |
| Wake word | needs Voice |
| Spotify | a free app at [developer.spotify.com](https://developer.spotify.com/dashboard) |
| Gmail | Google OAuth file (below) |
| Google Calendar | the same OAuth file |
| Multiple Google accounts | needs Gmail or Calendar |
| Home Assistant | a long-lived token from your Home Assistant profile |
| Desktop control | none |
| Screen reading | none; downloads OCR models once |
| Song recognition | none |
| League of Legends | none |
| MCP tool servers | none; add servers by asking Wony |

### Spotify

1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. Set the Redirect URI to `http://127.0.0.1:8888/callback`.
3. Put the id and secret in `.env`:
   ```env
   SPOTIFY_CLIENT_ID="..."
   SPOTIFY_CLIENT_SECRET="..."
   ```

A browser opens once to connect your account. Spotify must be open somewhere for
playback to have a target; if it was closed, open it and ask again.

### Gmail and Google Calendar

1. In [Google Cloud Console](https://console.cloud.google.com/), create an OAuth
   client of type **Desktop**, with the Gmail and Calendar APIs enabled.
2. Download it and save it as `credentials/google_credentials.json`.
3. Tick Gmail and/or Calendar in `install.bat`.
4. Say **"add google account work"** — a browser opens for consent.

Google expires tokens on its own, and changing your password expires all of
them. Say **"authorize work"** to sign in again. You can connect several
accounts; ask for one by name ("what's in my work inbox") or let it search all.

### Home Assistant

1. Home Assistant → your profile → **Security** → **Long-lived access tokens** →
   create one.
2. Put it in `.env` as `HOME_ASSISTANT_TOKEN="..."`.
3. Set the Home Assistant address on the Settings page — the same address you
   open in a browser.

Then: *"dim the bedroom lamp to 30"*, *"close the blinds"*, *"is the garage
open"*. Locks, alarms and the garage stay refused until you allow them.

### Ollama — no API key, runs locally

```powershell
ollama serve
```

Then set the AI provider to `ollama` on the Settings page. Replies are slower
and less capable than Claude or Gemini, but nothing leaves your machine.

### Voice

Speech recognition ([faster-whisper](https://github.com/SYSTRAN/faster-whisper))
and speech ([Kokoro](https://github.com/thewh1teagle/kokoro-onnx)) both run
locally — no key, no audio leaving the PC. An NVIDIA GPU is used automatically
if you have one; otherwise it runs on the processor, which works fine and is
slower. `python wony.py doctor` shows which.

Wony starts speaking as soon as the first sentence is ready rather than waiting
for the whole reply, and you can talk over it to interrupt.

### Wake word

Off by default. Switch it on in Settings and pick one of the built-in phrases:
`hey jarvis`, `alexa`, `hey mycroft`, `hey rhasspy`. If a configured phrase or
model is missing, Wony falls back to `hey jarvis` and says so in the
diagnostics banner rather than going quietly deaf.

Want it to answer to something else? That needs training a small model:

```powershell
python setup.py wakeword
```

It asks for your phrase, records you saying it a few times (the single biggest
accuracy win), wires up the config, and prints the one training command to run —
either `training/train_hey_wony.sh` (WSL, ~4–6h on your own GPU) or
`training/train_hey_wony.ipynb` (Colab, ~4–8h free). Both are resumable, and the
script pauses so you can listen to a few generated clips before committing to
the long part. Re-running after changing settings needs `--fresh`, or old clips
stay mixed in.

---

## When something goes wrong

| Problem | Fix |
| --- | --- |
| Tray icon never appears | Run `python wony.py tray` in a terminal and read the error |
| "AI provider not ready" | Put a key in `.env`, or set the provider to `ollama` |
| It answers but never speaks | Check **Mute** in the tray menu, and Voice is installed |
| It mishears or cuts you off | Raise **Pause before answering** in Settings |
| Wake word fires on its own | Raise **Wake sensitivity** in Settings |
| Wake word never fires | Lower it; check the mic in `python wony.py doctor` |
| Music commands fail | Open Spotify on some device, then ask again |
| "Google access expired" | Say "authorize <account name>" |
| Second copy exits silently | Only one Wony runs at a time — check the tray |
| Started at login but nothing happens | Task Scheduler → `WonyAssistant` → Last Run Result |

`python wony.py doctor` checks all of it at once and tells you what to fix.

---

## Running it other ways

`Wony.bat` is the everyday way in. From a terminal you can also run:

```powershell
python wony.py            # the same thing Wony.bat does: tray + web page
python wony.py text       # plain text conversation in the terminal
python wony.py voice      # voice only, no tray
python wony.py web        # web page only
python wony.py doctor     # check the setup and exit
```

Re-run `install.bat` (or `python setup.py`) any time to add or remove features.
It keeps your `.env` and `config.yaml` and only installs what is newly ticked.

---

## Privacy

Conversations, remembered facts and reminders are stored in `wony.db` in this
folder. Nothing is uploaded anywhere except the text of your requests, which
goes to the AI provider you chose (nowhere at all with Ollama). **Wipe data** in
the chat page deletes all of it. Speech recognition and speech are local.

Building on this? See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
