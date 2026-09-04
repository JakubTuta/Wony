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

After the packages are installed, the installer asks for everything the features
you ticked need — API keys, the Google credentials file, permissions — checks
each key against the service, and opens the browser for the Spotify and Google
sign-ins. Press Enter to skip anything you do not have yet; it lists what is
left and how to come back to it:

```powershell
python setup.py configure     # just the keys and sign-ins, any time later
```

You need one AI key:

| Provider           | Where to get a key                                        | Cost         |
| ------------------ | --------------------------------------------------------- | ------------ |
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com)    | paid         |
| Google Gemini      | [aistudio.google.com](https://aistudio.google.com/apikey) | free tier    |
| Ollama             | nothing to get — it runs on your own PC                   | free, slower |

Prefer the terminal? `python setup.py`, then `python wony.py`.

**Something not working?** Run `python wony.py doctor` for a checklist with
fixes, or ask Wony "check setup".

---

## Using it

**Type** in the chat page, or **talk**:

| Way in    | How                                                                 |
| --------- | ------------------------------------------------------------------- |
| Wake word | Say the wake phrase, then your request. Off until you switch it on. |
| Hotkey    | `Ctrl + Alt + W` anywhere in Windows.                               |
| Tray icon | Right-click → **Listen now**.                                       |
| Browser   | The microphone button in the chat page.                             |

Things to try: _"what's the weather"_, _"set a timer for 10 minutes"_, _"read my
last email"_, _"what's on my calendar tomorrow"_, _"play some jazz"_, _"turn off
the kitchen light"_, _"remember I prefer metric"_, _"what did we talk about on
Monday"_.

A timer can also run something else when it fires, which is how you get a daily
briefing: _"every weekday at 8am run greeting"_ reads out the time, weather,
unread email and today's meetings. Others: _"in 10 minutes pause the music"_,
_"every day at 7am turn on the bedroom light"_.

Say _"thanks"_, _"stop"_ or _"that's all"_ to end a spoken conversation.

### The chat page

Two halves: the conversation on the left, and on the right the things worth
looking at rather than asking about.

| Panel    | Appears when you enable | Shows                                                 |
| -------- | ----------------------- | ----------------------------------------------------- |
| Weather  | Weather                 | Temperature, wind, humidity, sunrise and sunset       |
| Today    | Google Calendar         | Today's and tomorrow's events                         |
| Timers   | Timers & reminders      | Everything counting down, with a cancel button        |
| Devices  | Home Assistant          | Every device by room, one card each, with its switches and settings |
| Music    | Spotify                 | Cover art, transport and volume                       |
| Accounts | Google accounts         | Add, sign in to and switch Google accounts            |
| Settings | always                  | Everything below, without touching a config file      |

The **bell** in the header holds anything Wony said while you were away — a
timer that fired, new email it spotted. **All commands** at the bottom opens
every command it knows, with a form for each.

### The tray icon

Right-click it for: **Open in web**, **Listen now**, **Stop speaking**,
**Mute**, **Wake word on/off**, **Settings**, **Check for updates**,
**Pause assistant**, **Exit**.

Setup offers to start Wony when you log in. To change your mind later:

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

| Switch                           | Off (the default)                       | On                                |
| -------------------------------- | --------------------------------------- | --------------------------------- |
| Send and delete email            | Writes a draft in Gmail for you to send | Sends and deletes for you         |
| Change my calendar               | Tells you what to add                   | Creates, edits and deletes events |
| Unlock doors and open the garage | Lights and blinds still work            | Locks, garage and alarms too      |
| Type and click for me            | Can look at the screen                  | Can type, click and open files    |

They are `modules.gmail.allow_write`, `modules.calendar.allow_write`,
`modules.home_assistant.allow_locks` and `modules.desktop.allow_actions` in
`config.yaml`.

> **Keep `server.host` at `127.0.0.1`.** The web page has no password and can
> run every command Wony has. On any other address, anyone who can reach the
> port gets all of it.

---

## Features you can switch on

Tick these during `install.bat`, or on the Settings page. The installer then
asks for whatever the ticked ones need. Anything left incomplete simply stays
off — nothing crashes, and `doctor` says what is missing.

| Feature                                      | What you need to bring                                                         |
| -------------------------------------------- | ------------------------------------------------------------------------------ |
| Everyday basics — time, date, daily briefing | none                                                                           |
| Timers, alarms and reminders                 | none                                                                           |
| Weather                                      | free key from [openweathermap.org/api](https://openweathermap.org/api)         |
| Web search and page reading                  | none (optional `TAVILY_API_KEY` for better results)                            |
| Voice — speech in and out                    | none; downloads its speech models once                                         |
| Wake word                                    | needs Voice                                                                    |
| Spotify                                      | a free app at [developer.spotify.com](https://developer.spotify.com/dashboard) |
| Gmail                                        | Google OAuth file (below)                                                      |
| Google Calendar                              | the same OAuth file                                                            |
| Multiple Google accounts                     | needs Gmail or Calendar                                                        |
| Home Assistant                               | a long-lived token from your Home Assistant profile                            |
| Desktop control                              | none                                                                           |
| Screen reading                               | none; downloads OCR models once                                                |
| Song recognition                             | none                                                                           |
| League of Legends                            | none                                                                           |
| MCP tool servers                             | none; add servers by asking Wony                                               |

### Spotify

1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. Set the Redirect URI to `http://127.0.0.1:8888/callback`.
3. Paste the client ID and secret when setup asks for them.

Setup then opens a browser once to connect your account. Spotify must be open
somewhere for playback to have a target; if it was closed, open it and ask again.

### Gmail and Google Calendar

1. In [Google Cloud Console](https://console.cloud.google.com/), create an OAuth
   client of type **Desktop**, with the Gmail and Calendar APIs enabled, and add
   your own address as a test user on the consent screen.
2. Download the JSON. Setup offers the one it finds in your Downloads folder, or
   takes the path — it files it away and opens the browser for consent.

Want a second mailbox? Say **"add google account work"** — the same consent, and
you can then ask for one by name.

Google expires tokens on its own, and changing your password expires all of
them. Say **"authorize work"** to sign in again. You can connect several
accounts; ask for one by name ("what's in my work inbox") or let it search all.

### Home Assistant

1. Home Assistant → your profile → **Security** → **Long-lived access tokens** →
   create one.
2. Paste it when setup asks, along with the address you open Home Assistant at.
   Setup checks both before saving them.

Then: _"dim the bedroom lamp to 30"_, _"close the blinds"_, _"is the garage
open"_, _"start the vacuum"_, _"send the vacuum home"_, _"set the suction to
turbo"_, _"turn all the lights off"_. Anything your Home Assistant can do, Wony
can ask it to do — including devices added through HACS. Ask _"what can the
vacuum do"_ if a device does not respond to the word you used.

A room or a device type has to be named before Wony will change a whole set of
things at once, and anything you have hidden in Home Assistant stays hidden
here.

Locks, alarms and the garage stay refused until you allow them.

### Ollama — no API key, runs locally

```powershell
ollama serve
```

Pick **Ollama** when setup asks which service should answer — it lists the
models you have pulled — or set the provider on the Settings page. Replies are slower
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

| Problem                              | Fix                                                        |
| ------------------------------------ | ---------------------------------------------------------- |
| Tray icon never appears              | Run `python wony.py tray` in a terminal and read the error |
| "AI provider not ready"              | `python setup.py configure` and give it a key              |
| It answers but never speaks          | Check **Mute** in the tray menu, and Voice is installed    |
| It mishears or cuts you off          | Raise **Pause before answering** in Settings               |
| Wake word fires on its own           | Raise **Wake sensitivity** in Settings                     |
| Wake word never fires                | Lower it; check the mic in `python wony.py doctor`         |
| Music commands fail                  | Open Spotify on some device, then ask again                |
| "Google access expired"              | Say "authorize <account name>"                             |
| Second copy exits silently           | Only one Wony runs at a time — check the tray              |
| Started at login but nothing happens | Task Scheduler → `WonyAssistant` → Last Run Result         |

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
python setup.py configure # add a key or sign in again, without installing
```

Re-run `install.bat` (or `python setup.py`) any time to add or remove features.
It keeps your `.env` and `config.yaml` and only installs what is newly ticked.

---

## Privacy

Conversations, remembered facts and reminders are stored in `wony.db` in this
folder. Nothing is uploaded anywhere except the text of your requests, which
goes to the AI provider you chose (nowhere at all with Ollama). **Wipe data** in
the chat page deletes all of it. Speech recognition and speech are local.
