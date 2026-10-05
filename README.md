# Wony

A personal AI assistant that runs on your own Windows PC. Talk to it or type to
it, and it can handle your email, calendar, Drive, contacts, music, smart home,
timers, maps and the web — using whatever you switch on, and nothing you don't.

- **Say "hey jarvis"**, press a hotkey, or just type in the browser.
- **Everything is off by default.** It cannot send an email, change your
  calendar or unlock a door until you allow it.
- **It asks before it acts.** Sending, deleting, cancelling or shutting down is
  read back to you first, and only happens once you say yes.
- **Your data stays on your machine** — history, notes and reminders live in a
  file next to the app. Only what you ask goes to your AI provider.

---

## Install

1. **Get the code.** Download this folder, or `git clone` it.
2. **Double-click `install.bat`.** It checks for Python and Node.js (and offers to
   install them), then asks which features you want (arrow keys to move, space to
   tick, Enter to confirm), then for the keys and sign-ins those features need
   and how you want Wony to behave (its personality, whether it may speak up on
   its own or learn about you, its voice). Press Enter to skip anything you do
   not have yet; it lists what is left. Every answer can be changed later on the
   Settings page.
3. **Double-click `Wony.bat`.** A tray icon appears near the clock and the chat
   page opens the first time. Later, right-click the icon → **Open in web**.

`Wony.bat` is how you start it every time — keep a shortcut to it somewhere
handy. Setup also offers to start Wony when you log in.

Want a feature you skipped? Double-click `install.bat` again: it keeps your keys
and settings and only installs what is new. To redo just the keys and sign-ins,
open a terminal in this folder and run `python setup.py configure`.

You need one AI service:

| Provider           | Where to get a key                                        | Cost         | Your requests                                  |
| ------------------ | --------------------------------------------------------- | ------------ | ----------------------------------------------- |
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com)    | paid         | not used to train Anthropic's models            |
| Google Gemini      | [aistudio.google.com](https://aistudio.google.com/apikey) | free tier    | free tier: reviewed and used to train Google's models. A paid key isn't. |
| Ollama             | nothing to get — it runs on your own PC                   | free, slower | never leave this computer                       |

With both a Claude and a Gemini key set and no provider chosen, Wony answers
with Claude. No key yet? Wony still starts — the chat page tells you where to
paste one (Settings → AI).

**Something not working?** Ask Wony _"check setup"_, or open **Features** to see
which feature is off and why. Still stuck: [When something goes wrong](#when-something-goes-wrong).

---

## Using it

The chat page opens with a short hello that lists things you can try right now
and what you could switch on. Click one, or type your own.

**Talk** instead of typing:

| Way in    | How                                                                 |
| --------- | ------------------------------------------------------------------- |
| Wake word | Say the wake phrase, then your request. Off until you pick it in setup or Settings. |
| Hotkey    | `Ctrl + Alt + W` anywhere in Windows.                               |
| Tray icon | Right-click → **Listen now**.                                       |
| Browser   | The microphone button in the chat page.                             |

Things to try: _"what's the weather"_, _"set a timer for 10 minutes"_, _"add milk
to my shopping list"_, _"how much battery have I got"_, _"read my last email"_,
_"what's in the PDF Marta sent"_, _"email Anna the notes"_, _"what's on my
calendar tomorrow"_, _"pharmacy near me"_, _"find the file about my lease"_,
_"go to this page and tell me the battery size"_, _"play some jazz"_, _"turn off
the kitchen light"_, _"remember I prefer Fahrenheit"_, _"what did we talk about on
Monday"_. Ask _"what can you do"_ any time.

Say _"thanks"_, _"stop"_ or _"that's all"_ to end a spoken conversation.

### Asking Wony about itself

Try _"what's my speaking speed"_, _"how do I set up Gmail"_ or _"why is the
weather switched off"_. Wony looks the answer up in its own settings and in this
guide instead of guessing, and tells you where to change something. It cannot
change a setting for you, and it never shows your keys.

### Routines

Say _"good morning"_ and Wony runs your **briefing** — a routine that comes with
it, and that you own: _"add my shopping list to the briefing"_ rewrites it.

Make your own: _"save a routine called good night that turns off the lights and
sets an alarm for seven"_. Then _"run my good night routine"_. A routine is just
your own words, so it can use anything Wony can do. Saving or deleting one is
read back to you first. A timer can run one: _"every weekday at 8am run my
briefing"_.

### The chat page

| Tab        | What it is                                                                 |
| ---------- | -------------------------------------------------------------------------- |
| Dashboard  | Tiles for what is worth looking at: weather, today's events, timers, lists, music, your devices. Tiles appear when you switch the feature on. |
| Features   | Every feature, an on/off switch for each, what it needs, and every command it has. |
| Routines   | Your routines in plain words — run one, edit it, schedule it.              |
| Settings   | Name, voice, microphone, AI provider, Google accounts, and the safety switches. |

The chat is on the right. The **bell** holds anything Wony said while you were
away — a timer that fired, new email it spotted.

### The tray icon

Right-click it for: **Open in web**, **Listen now**, **Stop speaking**, **Mute**,
**Wake word on/off**, **Sign in to Google again** (only when Google has signed
Wony out), **Settings**, **Check for updates**, **Pause assistant**, **Restart**,
**Exit**.

---

## What Wony may do on its own

These nine start **off**. Nothing else can turn them on. Change them in
**Settings → What Wony may do on its own**.

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

**Speak up on its own** lets Wony watch for a low battery, a drive nearly full,
a meeting about to start and new mail Gmail marked important — and say something
in its own words. It mentions each email once; the email stays unread in Gmail.
Ask _"what do you watch for"_ to see the list, or _"stop watching my inbox"_ to
switch the mail watcher off. Say _"watch my inbox"_ to hear about all new mail,
not only the important kind. One more watcher stays off until you ask:
_"watch my calendar"_.

**Learn about me on its own** lets Wony keep the things you mention in passing —
the dog's name, that you cycle to work. With Gmail on it also reads your sent
mail once a week to describe how you write. Ask _"what do you know about me"_ to
see everything it kept, and _"forget that"_ throws one away.

**Tell it what I'm looking at** puts the title of your front window into each
message, so _"what does this error mean"_ has something to point at. Titles name
documents, tabs and who you are chatting to, which is why it ships off.

### Safe with what it reads

Emails, web pages, invites and files can contain text written to trick an
assistant. Wony treats everything it reads from someone else as data, never as
instructions. On top of that it asks before it:

- visits a page you did not name or search for;
- reads a file outside your Desktop, Documents and Downloads that you did not
  name, or opens a program or script by path;
- saves a fact, a note, a document or a watcher right after reading something it
  did not get from you;
- sets a timer that runs another command.

It never reads or writes its own keys, settings, logs or database. The chat page
has no password, so it only answers this computer and refuses requests made by
other websites you have open.

---

## Features you can switch on

Tick these during `install.bat`, or on the **Features** page. Anything left
incomplete simply stays off — nothing crashes, and Features says what is missing.

| Feature                                      | What you need to bring                                                         |
| -------------------------------------------- | ------------------------------------------------------------------------------ |
| Everyday basics — time, date, shut down, restart, sleep, lock | none                                          |
| Routines — the briefing and your own         | none                                                                           |
| Timers, alarms and reminders                 | none                                                                           |
| Shopping and todo lists                      | none                                                                           |
| Computer health — battery, disk, memory      | none                                                                           |
| Weather — now and the next five days         | free key from [openweathermap.org/api](https://openweathermap.org/api)         |
| Maps & places — near me, travel times        | none (optional Google Maps key, below)                                         |
| Web search and page reading                  | none (optional Tavily key for better results)                                  |
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
| Telegram — message Wony from your phone      | a free bot token from @BotFather in Telegram                                   |
| MCP tool servers                             | none; add servers by asking Wony                                               |

### Spotify

1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. Set the Redirect URI to `http://127.0.0.1:8888/callback`.
3. Paste the client ID and secret when setup (or the Features page) asks for them.

A browser opens once to connect your account. Spotify must be open somewhere for
playback to have a target; if it was closed, open it and ask again.

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

Want a second account? Say **"add google account work"** — the same consent —
then ask for one by name ("what's in my work inbox") or let Wony search all.

### Maps & places

Works straight away, free, through [OpenStreetMap](https://www.openstreetmap.org):
places near you by type or name, addresses, travel time by car, bike or on foot,
and a Google Maps link for every route.

What OpenStreetMap can't do:

- no ratings, reviews or prices
- opening hours are often missing or out of date, so "open now" isn't possible
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
5. Paste it under Features → Maps & places.

**Where "near me" is.** Windows' own location is the most accurate: Settings →
Privacy & security → **Location** → turn on **Location services** and **Let
desktop apps access your location**. Without it Wony uses the home address from
Settings, and failing that guesses from your internet connection — good to
roughly the city.

### Web browsing

With **Web browsing** ticked, give Wony a page and a job: _"go to this page, open
the Specs tab and tell me the battery size"_. It works through the page in a
browser in the background and tells you when it has the answer — you can keep
talking meanwhile, and _"stop background jobs"_ cancels it.

It is always logged out, so it can't see anything behind your sign-ins, and it
won't buy anything, fill in your details or download files. It only visits public
websites. Local Ollama models often can't drive a browser.

### Finding files

_"Find the file about my lease"_ searches names **and contents**, using the same
index as the Start menu search. Windows indexes your user folders by default; to
add another folder, open **Indexing Options** from the Start menu → **Modify**.
If Windows Search is switched off, Wony still matches file names, and says so.

### Home Assistant

1. Home Assistant → your profile → **Security** → **Long-lived access tokens** →
   create one.
2. Paste it when setup asks, along with the address you open Home Assistant at.

Then: _"dim the bedroom lamp to 30"_, _"close the blinds"_, _"is the garage
open"_, _"start the vacuum"_, _"turn all the lights off"_. A room or a device type
has to be named before Wony will change a whole set of things at once. Locks,
alarms and the garage stay refused until you allow them.

### Telegram — Wony on your phone

1. In Telegram, message **@BotFather**, send `/newbot`, and follow the questions.
   It gives you a token.
2. Paste the token when setup asks (or under Settings → Integration keys), and
   restart Wony.
3. Open **Settings → Telegram**: under **Paired chat** Wony shows what to send,
   like `/start 123456`. Send that to your new bot. The same line is in the bell
   menu (top right), and Wony says it when it starts. That chat is now the only one
   Wony answers; anyone else is ignored.

Then type or send a voice note, and Wony answers like it does on the chat page.
Timers and reminders arrive there too. A message that asks for something risky
("delete that email") gets the same question it would at the PC — reply _yes_.

What it can't do:

- **Wony must be running on your PC.** If the PC is off or asleep, nothing
  answers. Messages sent meanwhile wait up to a day; ones older than 10 minutes
  when Wony wakes are not acted on, and Wony tells you so — send them again.
- Google sign-in, typing and clicking on the PC only work when you ask at the PC.
- Telegram can read the conversation: bot chats are not end-to-end encrypted.
  Think twice before asking it to read out an email you would not want Telegram
  to see.
- The code stays the same, restarts included, until a chat uses it, so you can't
  miss it. Too many wrong guesses retire it: restart Wony for a new one. To pair
  another chat, clear **Paired chat** in Settings.

### Ollama — no API key, runs locally

Install [Ollama](https://ollama.com), pull a model, and pick **Ollama** when setup
asks which service should answer (or in Settings → AI). Replies are slower and
less capable than Claude or Gemini, but nothing leaves your machine.

### Voice

Speech recognition and speech both run on this PC — no key, no audio leaving it.
An NVIDIA GPU is used automatically if you have one; otherwise the processor does
the work, which is fine and slower. Wony is English-only for now. It starts
speaking as soon as the first sentence is ready, and you can talk over it to
interrupt.

### Wake word

On if you ticked it during setup, otherwise off. Switch it on in Settings and pick a built-in phrase: `hey
jarvis`, `alexa`, `hey mycroft`, `hey rhasspy`. A custom phrase needs training a
small model; see [docs/developers.md](docs/developers.md).

---

## When something goes wrong

| Problem                              | Fix                                                        |
| ------------------------------------ | ---------------------------------------------------------- |
| Nothing happens when I open Wony.bat | Double-click `install.bat` first                           |
| Tray icon never appears              | Check the hidden icons arrow next to the clock             |
| The chat page is blank               | Node.js was missing when you installed — install it, then run `install.bat` again |
| "No AI service is set up yet"        | Settings → AI, paste a key or pick Ollama                  |
| It answers but never speaks          | Check **Mute** in the tray menu, and that Voice is installed |
| It mishears or cuts you off          | Raise **Pause before answering** in Settings               |
| Wake word fires on its own           | Raise **Wake sensitivity** in Settings (higher = pickier)  |
| Wake word never fires                | Lower it; check the microphone in Settings                 |
| A feature says "Run install.bat again" | Do that and tick the feature it names                    |
| Music commands fail                  | Open Spotify on some device, then ask again                |
| "Google signed me out"               | **Sign in again** (Settings → Google accounts, or the tray) |
| "Near me" is in the wrong place      | Turn on Windows location, or set your home address in Settings |
| A file search misses a file          | Add its folder to the Windows search index                 |
| "Wony is already running"            | Only one runs at a time — exit the one in the tray, or close its window |

Ask Wony _"check setup"_ for a full checklist.

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
| Telegram                                | Your messages and voice notes, Wony's replies, and reminders sent to your chat | Once you pair a chat |

No telemetry: nothing is sent back to whoever made Wony.

---

Changing Wony itself? See [docs/developers.md](docs/developers.md).
