# Wony

A personal AI assistant that runs on your own Windows PC. Talk to it or type to
it, and it can handle your email, calendar, Drive, contacts, music, smart home, timers,
maps and the web — using whatever you switch on, and nothing you don't.

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
3. **Double-click `Wony.bat`.** A tray icon appears near the clock. Right-click
   it → **Open in web** for the chat page. (Wony picks a free address on your
   computer the first time and keeps it, so a bookmark keeps working.)

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

| Provider           | Where to get a key                                        | Cost         | Your requests                                  |
| ------------------ | --------------------------------------------------------- | ------------ | ----------------------------------------------- |
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com)    | paid         | not used to train Anthropic's models            |
| Google Gemini      | [aistudio.google.com](https://aistudio.google.com/apikey) | free tier    | free tier: reviewed and used to train Google's models. A paid key isn't. |
| Ollama             | nothing to get — it runs on your own PC                   | free, slower | never leave this computer                       |

With both a Claude and a Gemini key set and no provider chosen, Wony answers
with Claude.

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

Things to try: _"what's the weather"_, _"what's it doing tomorrow"_, _"set a
timer for 10 minutes"_, _"add milk to my shopping list"_, _"how much battery
have I got"_, _"read my last email"_, _"what's in the PDF Marta sent"_,
_"email Anna the notes"_, _"what's on my calendar tomorrow"_, _"invite Tom to
Friday's sync with a Meet link"_, _"pharmacy near me"_, _"how long to drive to
Warsaw"_, _"what does my lease doc say about notice"_, _"find the file about my
lease"_, _"go to this page and tell me the battery size"_, _"play some jazz"_,
_"turn off the kitchen light"_, _"remember I prefer Fahrenheit"_, _"what did we
talk about on Monday"_.

### Routines

Say _"good morning"_ and Wony runs your **briefing** — a routine that comes with
it, and that you own: _"add my shopping list to the briefing"_ rewrites it, and
_"what's in my briefing"_ reads it back.

Make your own the same way: _"save a routine called good night that turns off
the lights and sets an alarm for seven"_. Then _"run my good night routine"_.
A routine is just your own words, so it can use anything Wony can do. Saving or
deleting one is read back to you first.

A timer can run a routine when it fires: _"every weekday at 8am run my
briefing"_. Others: _"in 10 minutes pause the music"_, _"every day at 7am turn
on the bedroom light"_.

Say _"thanks"_, _"stop"_ or _"that's all"_ to end a spoken conversation.

### The chat page

Two halves: the conversation on the left, and on the right the things worth
looking at rather than asking about.

| Panel    | Appears when you enable | Shows                                                 |
| -------- | ----------------------- | ----------------------------------------------------- |
| Weather  | Weather                 | Temperature, wind, humidity, sunrise and sunset       |
| Today    | Google Calendar         | Today's and tomorrow's events                         |
| Timers   | Timers & reminders      | Everything counting down, with a cancel button        |
| Lists    | Lists                   | Your shopping and todo lists                          |
| Routines | Routines                | Every routine you have, and what each one does        |
| Devices  | Home Assistant          | Every device by room, one card each, with its switches and settings |
| Music    | Spotify                 | Cover art, transport and volume                       |
| Accounts | Google accounts         | Add, sign in to and switch Google accounts            |
| Settings | always                  | Everything below, without touching a config file      |

The **bell** in the header holds anything Wony said while you were away — a
timer that fired, new email it spotted. **All commands** at the bottom opens
every command it knows, with a form for each.

### The tray icon

Right-click it for: **Open in web**, **Listen now**, **Stop speaking**,
**Mute**, **Wake word on/off**, **Sign in to Google again** (only when Google
has signed Wony out), **Settings**, **Check for updates**, **Pause assistant**,
**Exit**.

Setup offers to start Wony when you log in. To change your mind later:

```powershell
python wony.py autostart install     # undo with: autostart uninstall
```

---

## Settings

Open the chat page → **Settings**. Everything there is also in `config.yaml`,
which you can still edit by hand; the page just means you don't have to.

You can change the assistant's name and personality, the voice and how fast it
speaks, the microphone and speakers, the wake word and hotkey, which AI provider
answers, and which features are switched on.

Claude and Gemini always use their fastest model (the newest Haiku or Flash) —
there is nothing to pick. Temperatures and distances follow your Windows region;
say _"remember I prefer Fahrenheit"_ (or miles, or metric) to change that.

### What Wony may do on its own

These nine start **off**. Nothing else can turn them on.

| Switch                           | Off (the default)                       | On                                          |
| -------------------------------- | --------------------------------------- | ------------------------------------------- |
| Change my mailbox                | Writes a draft in Gmail for you to send | Sends, deletes and marks mail read          |
| Change my calendar and send invitations | Tells you what to add            | Creates, edits and deletes events, and emails invitations |
| Change my Drive files            | Finds and reads your files              | Creates Docs, adds to Docs and Sheets, uploads |
| Unlock doors and open the garage | Lights and blinds still work            | Locks, garage and alarms too                |
| Type and click for me            | Can look at the screen                  | Can type, click, open and write files       |
| Install MCP tool servers         | Tells you the command                   | Starts the program on this computer         |
| Speak up on its own              | Only answers when asked                 | Can start a conversation about what it sees |
| Learn about me on its own        | Remembers only what you ask it to       | Keeps facts it works out from your own data |
| Tell it what I'm looking at      | Sees nothing unless you ask             | Sends the front window's title every message |

They are `modules.gmail.allow_write`, `modules.calendar.allow_write`,
`modules.drive.allow_write`, `modules.home_assistant.allow_locks`, `modules.desktop.allow_actions`,
`modules.mcp.allow_install`, `assistant.proactive.enabled`,
`assistant.memory.learn_from_my_data` and `modules.desktop.share_window_title`
in `config.yaml`.

**Speak up on its own** lets Wony watch for a low battery, a drive nearly full,
a meeting about to start and mail Gmail marked important — and say something in
its own words rather than a canned alert. Ask _"what do you watch for"_ to see
the list, or _"stop watching for important email"_ to switch one off. A meeting
about to start comes with who is coming, what you last wrote to them and
anything on your lists with the meeting's name on it.

Two more watchers stay off until you ask, whatever that switch says: _"watch my
inbox"_ tells you about new mail as it arrives, and _"watch my calendar"_ about
events someone adds. What you turn on or off is remembered after a restart.

**Learn about me on its own** lets Wony keep the things you mention in passing —
the dog's name, that you cycle to work — instead of only what you say
"remember that" about. With Gmail on it also reads your sent mail once a week to
describe how you write, so a drafted reply sounds like you. Ask _"what do you
know about me"_ to see everything it kept; the ones it worked out for itself say
so, and _"forget that"_ throws one away.

**Tell it what I'm looking at** puts the title of your front window into each
message, so _"what does this error mean"_ has something to point at. Titles name
documents, tabs and who you are chatting to, which is why it ships off.

Separately from those switches, anything that changes something you care about —
sending or deleting mail, changing your calendar, cancelling a timer, shutting
the PC down — is read back to you first and only happens once you say yes. In the
chat page you get a confirm dialog; by voice or by typing, Wony tells you what it
is about to do and waits for an answer.

The chat page has no password, so it only answers this computer, and it refuses
requests made by other websites you have open.

---

## Features you can switch on

Tick these during `install.bat`, or on the Settings page. The installer then
asks for whatever the ticked ones need. Anything left incomplete simply stays
off — nothing crashes, and `doctor` says what is missing.

| Feature                                      | What you need to bring                                                         |
| -------------------------------------------- | ------------------------------------------------------------------------------ |
| Everyday basics — time, date, shut down, restart, sleep, lock | none                                          |
| Routines — the briefing and your own         | none                                                                           |
| Timers, alarms and reminders                 | none                                                                           |
| Shopping and todo lists                      | none                                                                           |
| Computer health — battery, disk, memory      | none                                                                           |
| Weather — now and the next five days         | free key from [openweathermap.org/api](https://openweathermap.org/api)         |
| Maps & places — near me, travel times        | none (optional Google Maps key, below)                                         |
| Web search and page reading                  | none (optional `TAVILY_API_KEY` for better results)                            |
| Web browsing — clicks through pages for you  | none; uses Edge or Chrome, or downloads a small browser once                   |
| Voice — speech in and out                    | none; downloads its speech models once                                         |
| Wake word                                    | needs Voice                                                                    |
| Spotify                                      | a free app at [developer.spotify.com](https://developer.spotify.com/dashboard) |
| Gmail                                        | Google OAuth file (below)                                                      |
| Google Calendar                              | the same OAuth file                                                            |
| Google Drive, Docs & Sheets                  | the same OAuth file                                                            |
| Google Contacts                              | the same OAuth file                                                            |
| Multiple Google accounts                     | needs a Google feature                                                         |
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

### Google — Gmail, Calendar, Drive and Contacts

All four share **one sign-in per account**, and Wony asks Google only for what
your switches allow: read-only until you turn on a "Change my …" switch, which
then asks Google once more.

1. In [Google Cloud Console](https://console.cloud.google.com/), pick or create a
   project and enable the APIs for what you ticked (setup lists them: Gmail API,
   Google Calendar API, Drive/Docs/Sheets APIs, People API).
2. On the OAuth consent screen choose **External**, leave it in **Testing**, and
   add your own Google address under **Test users**.
3. Create an OAuth client of type **Desktop** and download the JSON. Setup offers
   the one it finds in your Downloads folder, files it away and opens the browser.

Google will say it **hasn't verified this app**. It is your own app: click
**Advanced**, then continue.

**Google signs Wony out every 7 days.** That is Google's rule for apps in
Testing, and publishing the app needs a public website, privacy policy and
terms. Wony tells you once when it happens, warns you the day before, and
**Sign in again** (Settings → Google accounts, or the tray menu) takes one click.
Updating from a version with separate Gmail and Calendar sign-ins also asks you
to sign in once.

Want a second account? Say **"add google account work"** — the same consent —
then ask for one by name ("what's in my work inbox") or let Wony search all.

### Maps & places

Works straight away, free, through [OpenStreetMap](https://www.openstreetmap.org):
places near you by type or name, addresses, travel time by car, bike or on foot,
and a Google Maps link for every route.

What OpenStreetMap can't do:

- no ratings, reviews or prices
- opening hours are often missing or out of date, so "open now" isn't possible
  (the recorded hours are shown when there are any)
- no live traffic: driving times assume empty roads
- no public transport routes
- coverage varies by country and town
- a kind of place ("pharmacy") works better than a vague wish ("somewhere nice")
- the public servers are run by volunteers, allow about one request a second and
  promise no uptime, so answers can be slow

**A Google Maps key** adds ratings, open-now, price level, live traffic and public
transport. It needs a Google Cloud **billing account with a card**. Google gives a
free allowance every month; Wony counts its own requests and goes back to
OpenStreetMap before the allowance runs out, so normal use costs nothing.

1. [Google Cloud Console](https://console.cloud.google.com/) → **Billing**: add a
   billing account.
2. **APIs & Services → Library**: enable **Places API (New)** and **Routes API**.
3. **Credentials → Create credentials → API key**. Restrict it to those two APIs.
4. Optional: **Quotas** → set a daily cap, so nothing can ever cost money.
5. Paste it into setup or Settings (`GOOGLE_MAPS_API_KEY`).

**Where "near me" is.** Windows' own location is the most accurate: Settings →
Privacy & security → **Location** → turn on **Location services** and **Let
desktop apps access your location**. Without it Wony uses the home address from
Settings, and failing that guesses from your internet connection — good to
roughly the city. Set how you usually get around (car, public transport,
walking, cycling) in Settings.

### Web browsing

With **Web browsing** ticked, give Wony a page and a job: _"go to this page, open
the Specs tab and tell me the battery size"_. It works through the page in a
browser in the background and tells you when it has the answer — you can keep
talking meanwhile, and _"stop background jobs"_ cancels it.

It is always logged out, so it can't see anything behind your sign-ins, and it
won't buy anything, fill in your details or download files. It only visits public
websites. If a link came from an email or a page rather than from you, Wony asks
before following it. Local Ollama models often can't drive a browser.

### Finding files

_"Find the file about my lease"_ searches names **and contents**, using the same
index as the Start menu search. Windows indexes your user folders (Desktop,
Documents, Downloads, Pictures…) by default; to add another folder, open
**Indexing Options** from the Start menu → **Modify**. Whether PDF contents are
searchable depends on the PDF filter installed on your PC. If Windows Search is
switched off, Wony still matches file names, and says so.

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
| "Google signed me out"               | Press **Sign in again** (Settings → Google accounts, or the tray), or say "authorize <account name>" |
| "Near me" is in the wrong place      | Turn on Windows location, or set your home address in Settings |
| A file search misses a file          | Add its folder to the Windows search index (below)         |
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

Changing Wony itself? See [docs/developers.md](docs/developers.md).

---

## Privacy

Conversations, remembered facts, lists and reminders are stored in `wony.db` in
this folder. Speech recognition, speech, the wake word and (when
[easyocr](https://github.com/JaidedAI/EasyOCR) is installed) screen reading
all run locally — nothing about your voice, your screen or what you asked
has to leave this computer for those to work.

**Wipe data** (Settings page) deletes `wony.db`, the Spotify sign-in cache and
every log file for good. It does **not** remove your API keys or sign you out
of Google — those are separate, deliberate steps: remove an account from
Settings → Google accounts, or delete a key by hand from `.env` (Settings →
Features can replace a key with a new one, but not clear it).

What leaves this computer, and only when a feature you switched on needs it:

| Goes to                                | What                                              | When                                       |
| --------------------------------------- | -------------------------------------------------- | ------------------------------------------- |
| Your AI provider                        | Your requests, the last few turns, facts it remembered, and whatever it reads to answer you (an email, a web page, a file, a Drive document, a screenshot) | Every request (nowhere at all with Ollama) |
| OpenStreetMap, or Google with a Maps key | Place and route searches. Your location itself stays here except as part of one | A maps request                             |
| ipinfo.io                               | Nothing identifying — just enough to guess your city when Windows location is off | Only if Windows can't say where you are    |
| OpenWeatherMap                          | City name or coordinates                           | A weather request                           |
| DuckDuckGo, or Tavily with a key        | Your search terms                                  | A web search                                |
| Whatever site you browse                | The URL, same as any browser                       | Reading or working through a page           |
| Google (Gmail, Calendar, Drive, Contacts) | Whatever the feature you're using needs         | A Google feature, once signed in            |
| Spotify                                 | Playback commands                                  | A music request                             |
| Home Assistant                          | Device commands, to the address you configured, not the internet | A smart-home request      |
| Shazam                                  | An audio fingerprint, not the recording itself     | Song recognition                            |

No telemetry: nothing is sent back to whoever made Wony.
