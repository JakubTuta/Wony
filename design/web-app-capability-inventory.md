# Wony — Web App Capability Inventory

*Compiled directly from the backend source (job registry, settings schema, panel
snapshots, web API) for the web app redesign. This is a raw capability list, not
a description of any current screen — nothing here says how it's shown today.*

**At a glance:** 52 callable jobs · 17 switchable modules + 3 always-on · 34
settings fields · 8 structured live-data feeds · 4 proactive triggers · 19 jobs
requiring confirmation.

---

## 1. Modules

A module is a capability area a user switches on or off. Three modules run
underneath everything and cannot be switched off; the other seventeen are
opt-in, each unlocking its own jobs, settings and data.

**Always on**

| Module | What it covers |
|---|---|
| `ai` | Answers questions, remembers facts, recalls past context, indexes documents for semantic search. |
| `status` | Reports on Wony itself — what works, what's broken, the full command list, the proactive watch list. |
| `employer` | Runs the assistant's turn loop, tracks background watchers, can shut the whole app down. |

**Switchable — off by default unless noted**

| Module | What it gives you |
|---|---|
| Everyday basics (`basics`) | Time, date, shut down the PC. |
| Routines (`routines`) | Named sets of steps run by name, like a morning briefing. |
| Timers & reminders (`scheduler`) | Timers and alarms that survive a restart. |
| Lists (`notes`) | Shopping and todo lists added to by voice. |
| Weather (`weather`) | Now and the next few days, here or any city. |
| Web search (`web`) | Search the web and read pages. |
| Computer health (`system`) | Battery, disk space, memory and network. |
| Spotify (`spotify`) | Play, pause, skip, search, volume, playlists, queue. |
| Gmail (`gmail`) | Read, search, send, organize and watch an inbox. |
| Google Calendar (`calendar`) | Events, availability, free slots, creating/editing. |
| Google accounts (`google_accounts`) | Use more than one Google account for Gmail/Calendar. |
| Home Assistant (`home_assistant`) | Lights, blinds, thermostats, vacuums, locks, scenes. |
| Desktop control (`desktop`) | Open apps/windows, clipboard, read/write files, type, click. |
| Screen reading (`screen`) | Screenshot the screen and read/locate text on it. |
| Song recognition (`shazam`) | Name the song currently playing through the speakers. |
| League of Legends (`league`) | Launch/close the client, auto-accept queue pop-ups. |
| MCP tool servers (`mcp`) | Connect external Model Context Protocol tool servers. |

> **Module state is itself data.** Every module reports a status —
> `enabled`, `disabled`, `misconfigured`, `unavailable`, or `error` — plus a
> plain-English reason and, when relevant, a fix hint (e.g. a missing API key
> or a `pip install` command). A module can be re-tried live without a
> restart.

---

## 2. Jobs — every callable action

A job is one discrete thing Wony can be told to do. Every job takes named
parameters and returns a result; some are read-only, some change something
and require confirmation first (see [§10](#10-confirmation-gates)). Each is
independently invocable — by voice, by typed chat, or directly by the web
app — so any job here is a candidate for its own control, not only something
reachable through a chat sentence.

### ai *(always on)*

**`ask_question(question)`** — no confirmation
Answers a general knowledge question — facts, definitions, explanations — using the AI model.
- `question` (str, required): the question to ask.

**`clear_conversation()`** — no confirmation
Wipes the current conversation history so the assistant starts fresh.

**`remember(action="save", fact="", topic="")`** — confirms on: forget, remove, delete
Saves a personal fact or preference so the assistant remembers it in future sessions, or deletes a previously saved one.
- `action` (str, default "save"): "save" or "forget".
- `fact` (str): the fact text; required when saving.
- `topic` (str): a short label (e.g. "boss"); reused labels update rather than duplicate, and pick which fact to forget.

**`recall(query="", scope="all", date="", limit=5)`** — no confirmation
Searches everything the assistant remembers — past conversations, saved facts, indexed documents.
- `query` (str): what to search for; empty returns the most recent exchanges.
- `scope` (str, default "all"): "all", "conversations", "facts", or "documents".
- `date` (str): restrict to one day, e.g. "yesterday" or "2024-12-25".
- `limit` (int, default 5): how many results to return.

**`manage_documents(action="list", path="")`** — confirms on: forget, remove, delete
Adds a file so its contents become searchable, lists which files are indexed, or removes one.
- `action` (str, default "list"): "list", "add", or "forget".
- `path` (str): path to the file; required for add/forget.

### basics

**`get_datetime(part="both")`** — no confirmation
Tells the current time, today's date, or both.
- `part` (str, default "both"): "time", "date", or "both".

**`close_computer()`** — **always confirms**
Completely shuts down the computer, closing all open programs.

### routines

**`routine(action="run", name="", steps="")`** — confirms on: add, save, create, edit, remove, delete, forget
Runs a saved routine — a named sequence of steps in plain words (e.g. "good night" turning off lights and setting an alarm) — or manages the list: view all, add/update one, remove one.
- `action` (str, default "run"): "run", "list", "add", or "remove".
- `name` (str): which routine, e.g. "briefing" or "good night"; required except for "list".
- `steps` (str): what the routine should do, in plain words; required for add, replaces any existing steps.

A default "briefing" routine is auto-created the first time, unless the user has deleted it.

### scheduler

**`add_reminder(when, text="", action_job="", action_args=None)`** — no confirmation
Sets a timer, alarm, reminder, or recurring notification — from "in 10 minutes" to a daily 8am alarm to "every 2 hours". Can speak a message, trigger another job (device control, playing music…), or both. Survives app restarts.
- `when` (str, required): everyday phrasing — "in 10 seconds", "at 3pm", "tomorrow at 9am", "every day at 8am", "every weekday at 9am", "every Monday at 10am", "every 2 hours".
- `text` (str): message announced when it fires; optional if `action_job` is set.
- `action_job` (str): name of another job to run when it fires, e.g. "control_home_device", "play_songs".
- `action_args` (dict): parameters for that triggered job.

**`manage_reminders(action="list", id_or_text="", new_when="", new_text="", new_action_job="", new_action_args=None)`** — confirms on: edit, cancel, delete, remove, stop
Lists every running timer/alarm/reminder with time left, or changes/cancels one.
- `action` (str, default "list"): "list", "edit", or "cancel".
- `id_or_text` (str): which reminder — its id, part of its text, or "all"; required for edit/cancel.
- `new_when` / `new_text` / `new_action_job` / `new_action_args`: new values to apply when editing.

### notes

**`note(action="add", text="", list_name="")`** — confirms on: clear, empty
Manages written lists such as shopping or to-do: adds an item, reads a list back, removes an item, clears a whole list, or shows every list name that has something on it.
- `action` (str, default "add"): "add", "list", "remove", "clear", or "lists".
- `text` (str): item text; multiple items can be comma-separated; required for add/remove.
- `list_name` (str): which list, e.g. "shopping", "todo"; defaults to a general "notes" list.

### weather

**`weather(city="", when="now")`** — no confirmation
Reports the weather for a named city or the current location: conditions right now, or the forecast for today, tomorrow, or the next several days.
- `city` (str): which city; empty uses current location.
- `when` (str, default "now"): "now", "today", "tomorrow", or "week".

### web

**`web_search(query)`** — no confirmation
Searches the web for current information, news, or facts on any topic.
- `query` (str, required): what to search for.

**`fetch_url(url, offset=0)`** — no confirmation
Fetches and reads the main text of a specific web page.
- `url` (str, required): full address, http(s)://…
- `offset` (int, default 0): character position to continue reading a page that was cut off.

### system

**`computer_health(what="all")`** — no confirmation
Reports battery level and charging state, free disk space, memory and processor load, and network status.
- `what` (str, default "all"): "all", "battery", "disk", "memory", "cpu", or "network".

### spotify

**`play_songs(title, artist, content_type="")`** — no confirmation
Plays a specific song, a full album, everything by an artist, or one of the user's playlists. With nothing specified, resumes whatever was paused.
- `title` (str): song/album/playlist title, or artist name if none given.
- `artist` (str): narrows the search.
- `content_type` (str): "track", "album", "artist", or "playlist"; blank uses the first result.

**`add_to_queue(title, artist)`** — no confirmation
Adds a song, album, or an artist's music to the play queue without interrupting current playback.

**`control_playback(action="toggle", value="")`** — no confirmation
Everyday playback control: play, pause, skip forward/back, restart, seek, shuffle, cycle repeat, like/unlike the current song, or transfer to a different speaker.
- `action` (str, default "toggle"): toggle, play, pause, next, previous, restart, seek, shuffle, repeat, like, unlike, transfer.
- `value` (str): position in seconds for "seek"; device name for "transfer".

**`set_volume(level=-1, direction="")`** — no confirmation
Sets, nudges, or reports Spotify volume. Always reads the live level rather than trusting anything discussed earlier.
- `level` (int, 0–100): exact target volume.
- `direction` (str): up/down (10% steps), max, min, or get (report only).

**`spotify_info(what="current", query="")`** — no confirmation
Reports: the song playing now, what's queued next, the user's playlists, available playback devices, or a search result.
- `what` (str, default "current"): current, queue, playlists, devices, or search.

**`manage_playlist(action="add", playlist_name="", title="", artist="")`** — **always confirms**
Adds a song to a playlist, removes one, creates a new playlist, or deletes one. With no song named, uses whatever is playing now.
- `action` (str, default "add"): add, remove, create, or delete.
- `playlist_name` (str, required): full or partial playlist name.

### gmail

Every job below can target a specific account via a shared `account` parameter — see [§9](#9-accounts--external-tools).

**`find_emails(query="", sender="", subject="", label="", folder="", days_back=0, unread_only=False, starred=False, important=False, has_attachment=False, max_results=0, view="list", account="")`** — no confirmation
All-in-one email lookup — unread, recent, from someone, by label, starred, important, with attachments.
- `view` (str, default "list"): "list" (previews), "full" (whole body of best match), "thread" (full conversation), "overview" (unread counts + top senders).
- `folder` (str): inbox (default), sent, drafts, etc.
- `unread_only` / `starred` / `important` / `has_attachment` (bool): filters.
- `days_back` / `max_results` (int): recency and result cap (default 20).

**`list_labels(account="")`** — no confirmation
Lists all Gmail labels and folders.

**`watch_inbox(action="start", interval_minutes=0, account="")`** — no confirmation
Turns background inbox monitoring on/off so new mail gets announced as it arrives (default check interval: 15 min).

**`send_email(to="", subject="", body="", reply_to_query="", account="")`** — **always confirms**
Sends a new message, or a reply to an email found by search text. If sending is switched off in settings, saves a draft instead.
- `reply_to_query` (str): set instead of `to` to reply to a found email.

**`modify_emails(action="read", query="", sender="", subject="", label="", account="")`** — **always confirms**
Bulk-changes matching emails: mark read/unread, star/unstar, archive, add/remove a label, or move to trash.
- `action` (str, default "read"): read, unread, star, unstar, archive, label, unlabel, delete.

**`manage_drafts(action="list", draft_id="", to="", subject="", body="", account="")`** — confirms on: delete
Lists, creates, edits, or deletes drafts. Editing leaves blank fields unchanged.

> Sending and bulk-modifying mail can be switched off entirely by the
> **gmail.allow_write** safety gate — while off, drafting still works as the
> fallback.

### calendar

**`find_events(query="", date="", start_date="", end_date="", days_back=0, hours_ahead=0, calendar_name="", limit=0, account="")`** — no confirmation
The all-in-one event lookup: what's coming up, a specific day, a date range, past events, a keyword search, or one named calendar.

**`watch_calendar(action="start", interval_minutes=0, account="")`** — no confirmation
Turns background calendar monitoring on/off so new events get announced.

**`list_calendars(account="")`** — no confirmation
Lists every calendar available on the account, with name and ID.

**`check_free_time(date_str="", start_time="", end_time="", min_minutes=30)`** — no confirmation
Checks availability across every connected account — busy/free for a window, or a list of open gaps in the working day.

**`manage_event(action="create", title="", query="", date="", start_time="", end_time="", description="", location="", calendar_name="", account="")`** — **always confirms**
Creates, edits, or deletes an event. Edit/delete find the event by search text and/or date and refuse to act if more than one matches.

> Creating/editing/deleting events can be switched off entirely by the
> **calendar.allow_write** safety gate — while off, the assistant describes
> what to enter manually instead.

### google_accounts

**`manage_google_accounts(action="list", name="", new_name="")`** — confirms on: add, authorize, remove, rename, set_primary
Manages which Google accounts feed Gmail/Calendar: view, add, sign in/re-authorize, rename, remove, or set the default. Adding and authorizing open a browser window to grant access.

### home_assistant

**`list_home_devices(query="", area="", domain="")`** — no confirmation
Shows devices matching a search with current state and capabilities — browsing ("what's in the kitchen") or a specific reading ("what's the bedroom temperature"). Empty finds list the whole house.
- `domain` (str): device type, e.g. light, switch, sensor, climate, cover, lock, media_player, vacuum — any Home Assistant domain, read-only sensors included.

**`control_home_device(target="", action="on", area="", domain="", value=None, temperature=None, option="")`** — **always confirms**
Operates lights, switches, blinds, thermostats, vacuums, locks, media players, scenes and scripts. At least one of target/area/domain is required.
- `action` (str, default "on"): on, off, toggle, open, close, stop, start, pause, dock, locate, play, next, previous, lock, unlock, arm, disarm, press, run.
- `value` (float): percent for lights/blinds/fans/volume, or a raw number.
- `temperature` (float): target temperature (climate/water_heater).
- `option` (str): a named mode/preset/source, e.g. "Turbo", "heat".

Full device-domain and capability breakdown is in [§3 · Home Assistant devices](#home-assistant-devices).

### desktop

Everything below except listing/reading requires the separate `desktop.allow_actions` setting to be on.

**`manage_window(action="list", title="")`** — confirms on: close
Lists open windows, or focuses/minimizes/maximizes/closes one by partial title.

**`clipboard(action="read", text="")`** — confirms on: write, set, copy
Reads the clipboard, or writes new text to it.

**`find_file(name, search_path="")`** — no confirmation
Searches the computer for files/folders matching a name; defaults to common folders (Desktop, Documents, Downloads, home).

**`file(action="read", path="", content="", offset=0)`** — confirms on: write, append
Reads a text file, writes/appends text to one, or lists a folder's contents.

**`open(target)`** — no confirmation
Opens an application by name, or a file/folder in whatever program normally handles it.

**`type_text(text)`** — **always confirms**
Types the given text into whichever app currently has focus.

**`click_at(x, y)`** — **always confirms**
Clicks the mouse at a specific pixel position.

**`click_text(text, double=False)`** — **always confirms**
Finds visible on-screen words (a button, a link) and clicks them instead of clicking by coordinates.

### screen

**`look_at_screen(question="", save=False)`** — no confirmation
Looks at whatever is on screen and answers a question about it (an error message, an image, a form field), or just describes the screen. Can save a copy of the screenshot.

### shazam

**`identify_song(queue=False)`** — no confirmation
Listens to a few seconds of audio playing through the computer's speakers/headphones and identifies title and artist. Can also add it to the Spotify queue.

### league

**`league(action="launch")`** — confirms on: close, quit, exit
Starts the client, closes it, or watches the screen and auto-accepts a match when the queue pops up (self-stops after 30 minutes or once accepted).

### mcp

**`list_mcp_servers()`** — no confirmation
Lists every configured external tool-server connection and whether each is currently connected.

**`manage_mcp_server(action="add", name="", transport="", command="", url="", args="", env="", enabled="")`** — **always confirms**
Adds, edits, removes, connects, or disconnects an external MCP tool server that gives Wony extra abilities.
- `transport` (str): "stdio" (default), "sse", or "http".
- `command` / `url` (str): executable command for stdio; base address for sse/http.
- `args` / `env` (str, JSON): JSON list of args; JSON object of extra env vars.

> Gated by **mcp.allow_install** — while off, it states the command instead
> of running it (an MCP server runs on this computer with the user's
> privileges).

### status *(always on)*

**`system_status(scope="modules")`** — no confirmation
Reports on Wony itself.
- `scope` (str, default "modules"): "modules" (each feature's status + fix), "setup" (full diagnostics checklist), "commands" (everything Wony can do), "retry" (attempt to restart broken features).

**`manage_triggers(action="list", name="")`** — no confirmation
Lists the things Wony watches for on its own (see [§7](#7-proactive-triggers)), and turns one off/on for the rest of the session.

### employer *(always on)*

**`background_jobs(action="list")`** — confirms on: stop, cancel, stop all
Lists things running in the background (inbox/calendar watchers, proactive triggers), or stops all of them. Does not cover timers/reminders.

**`exit()`** — **always confirms**
Shuts the Wony application down completely.

---

## 3. Live structured data

Eight areas return data as typed fields rather than a sentence — the raw
material for gauges, toggles, sliders, cards and lists instead of chat
bubbles. Every field below exists today and is available to read.

**Weather** — `weather.snapshot(city)`
`city, description, temperature, feels_like, unit ("°C"/"°F"/"K"), humidity, wind, wind_unit, icon, condition, sunrise, sunset (unix timestamps), utc_offset`.
A parallel `forecast(city)` returns up to 5 days: `{city, today, unit, days:[{date, label, low, high, description}]}`.

**Agenda** — `calendar.agenda_snapshot(days=2)`
`events[]` each `{id, title, location, start, end, all_day, account, attendees}`, plus `today, days[], timezone`.

**Reminders** — `scheduler.reminders_snapshot()`
`{id, text ("" if action-only), action_job ("" if message-only), when_str (original phrasing), repeating (bool), next_run (ISO datetime or null)}`. Rows pre-sorted, soonest first.

**Lists** — `notes.snapshot()`
`lists[]` each `{name, count, items[] (up to 20 shown)}`.

**Routines** — `routines.snapshot()`
`routines[]` each `{name, steps}`.

**Music** — `Spotify.playback_snapshot()`
`active` (bool, false = nothing playing); when active: `is_playing, title, artist (comma-joined), album, art_url (300px, or null), progress_ms, duration_ms, shuffle, device, volume (0–100 or null)`.

**Google accounts** — `accounts_snapshot()`
`accounts[]` each `{name, email, primary, tokens}`, plus `primary` (default account name), `services {gmail, calendar}`, `credentials_ready` (bool — OAuth client file exists). Reads local files only — never triggers a sign-in prompt on its own.

### Home Assistant devices — `home_assistant.snapshot()`

Grouped by room, each room a list of devices, each device one primary
control plus any extra controls/buttons it exposes.

Per-control fields: `entity_id, name, domain, state, on, available, level
(0–100 or null — slider value), options[] (allowed named values), press,
number, toggle, slider (bool — which control shape applies), guarded (bool
— locks/alarms/garage-gate-door covers, needs the locks-allowed gate)`.

| Domain | Verbs beyond on/off/toggle | Value / slider | Named options |
|---|---|---|---|
| `light` | — | brightness % | — |
| `cover` / `valve` | open, close, stop | position % | — |
| `lock` **(guarded)** | lock, unlock | — | — |
| `alarm_control_panel` **(guarded)** | arm (away), disarm | — | — |
| `climate` | — | temperature setpoint | HVAC mode |
| `water_heater` | on, off | temperature setpoint | operation mode |
| `fan` | — | speed % | preset mode |
| `humidifier` | — | target humidity % | mode |
| `media_player` | play, pause, stop, next, previous | volume % | source |
| `vacuum` | start/clean, dock/return, pause, stop, locate | — | fan speed preset |
| `lawn_mower` | start/mow, dock/home, pause | — | — |
| `scene` | activate (one-shot, no toggle) | — | — |
| `script` / `automation` | run/trigger | — | — |
| `button` | press only — stateless | — | — |
| `select` / `input_select` | no on/off — value only | — | arbitrary named option |
| `number` / `input_number` | no on/off — value only | raw value, device-defined range | — |
| any other domain | falls back to plain on / off / toggle | — | — |

`list_home_devices` can also surface read-only domains (`sensor`,
`binary_sensor`) that the controllable-device data deliberately excludes —
those exist as data too, just not as something to switch.

---

## 4. System & diagnostics

Wony reports on its own health continuously, independent of any module's own data.

- **Model & provider**: `provider` (anthropic / gemini / ollama / unknown), `model` (resolved model name).
- **Per-module status**: `status` (enabled / disabled / misconfigured / unavailable / error), `reason` (plain-English cause), `hint` (fix, e.g. a pip install command).
- **Compute device**: `stt_device, tts_device` ("GPU" or "CPU"), `cuda_ok` (bool), `hint` (GPU setup guidance when not accelerated).
- **Diagnostics feed**: `level` (info/warning/error), `source, message, hint, ts` (HH:MM:SS). A rolling, deduplicated feed — repeat failures resurface every 10 minutes rather than spamming.
- **Notifications feed**: `id, ts, kind, source, text` (a proactive message Wony raised on its own), `acknowledged` (bool — dismiss one or all). Populated by [proactive triggers](#7-proactive-triggers).
- **Job catalog, introspectable**: `name, module, summary, description, parameters` (full docstring + typed schema per job), `destructive` (bool — same flag driving the confirmation gate). Every job in §2 is available this way at runtime — a generic job browser or invoker doesn't need a hardcoded list.

---

## 5. Conversation & voice

Text and voice both drive the same underlying turn — a message in, a reply
plus the list of jobs it ran, out.

- **A chat turn**: `id, ts, user, assistant, calls[]` (every job the turn invoked, sanitized — a visible reasoning trail per message).
- **Streaming**: a live socket delivers token-by-token text as it's generated, then the finished turn — broadcast to every connected tab/device at once, so multiple surfaces (voice UI, a phone tab, a desktop tab) stay in sync without polling.
- **Voice capture**: raw microphone audio can be uploaded and transcribed to text. Two distinct failure states are already surfaced: no audio captured (permission/device issue) vs. audio captured but silent — different problems, different messages.
- **History & search**: `recent_turns(limit)` (most recent exchanges), `search_turns(keyword)` (full-text search across all past turns), `turns_on_date(date)` (everything said on one day).

> Two distinct resets exist: clearing the active conversation (context only)
> is separate from wiping all stored data (history, facts, documents,
> notifications) — the latter is irreversible.

---

## 6. Memory & personalization

What Wony knows about the user, independent of any one conversation.

- **Facts**: `key, value, source` (source distinguishes user-told from self-learned facts). Self-learning from conversations — and, with Gmail on, from the user's own sent mail — is gated by **memory.learn_from_my_data**; off by default.
- **Indexed documents**: files added become semantically searchable — matched by meaning, not just keyword, via the same `recall` path as conversation history.
- **Seeded profile**: owner name, language, and preferred units seed the fact store automatically from settings, then evolve independently as more facts are saved.

---

## 7. Proactive triggers

Things Wony can notice and speak up about unprompted — entirely off by
default (**assistant.proactive.enabled**), and individually switchable once
on. At most one proactive interruption fires every 5 minutes, whichever
trigger it is.

| Trigger | Watches for | Check interval | Cooldown after firing |
|---|---|---|---|
| `battery_low` | Battery running low while unplugged. | 2 min | 30 min |
| `disk_low` | A drive nearly out of space. | 15 min | 6 hours |
| `event_soon` | A calendar event starting within 15 minutes. | 5 min | 5 min |
| `important_email` | Unread mail Gmail marked important. | 5 min | 15 min |

A trigger hands its finding to the AI as a fact rather than reading canned
text, so the reply is in the assistant's own voice and can offer to act.
`important_email` is flagged internally as carrying untrusted quoted text (a
subject line anyone can email the user) — every other trigger's wording is
Wony's own.

---

## 8. Settings

34 fields across six groups, each with a label, a plain-language help line,
and a control type. Fields marked **restart** only take effect after Wony
restarts; every other field applies immediately.

### Assistant

| Field | Type | Help text |
|---|---|---|
| Name | text | What you call it. |
| Your name | text | How it addresses you. |
| Personality | long text | Free text describing how it should talk to you. |

### Voice

| Field | Type | Range / choices | Help text |
|---|---|---|---|
| Voice | choice | af_heart, af_sarah, af_bella, am_michael, am_adam, bf_emma, bf_isabella, bm_george, bm_lewis | Which voice speaks the replies. |
| Speaking speed | number | 0.5–2.0 | 1.0 is normal. |
| Speaking volume | number | 0–1 | 0 is silent, 1 is loudest. |
| Pause before answering | number | 200–3000 ms | Silence that ends your sentence; raise if you get cut off. |
| Keep listening after a reply | toggle | — | Carry on back-and-forth without repeating the wake word. |
| Let me interrupt | toggle | — | Talking over a reply stops it. |
| Pause my music while talking | toggle | — | Pauses Spotify/video/other players, resumes after. |
| Push-to-talk key **(restart)** | text | e.g. "\<ctrl\>+\<alt\>+w" | Starts listening; empty switches it off. |

### Wake word *(all fields restart)*

| Field | Type | Range / choices | Help text |
|---|---|---|---|
| Listen for a wake word | toggle | — | Start a conversation hands-free. |
| Wake phrase | choice | hey jarvis, alexa, hey mycroft, hey rhasspy | Built-in phrases; a custom phrase needs a separate training step. |
| Wake sensitivity | number | 0.1–0.9 | Lower triggers more easily, and more often by mistake. |

### AI

| Field | Type | Range / choices | Help text |
|---|---|---|---|
| AI provider **(restart)** | choice | auto, anthropic, gemini, ollama | Which service answers; auto uses whichever key is configured. |
| Thinking | choice | on, off | "on" reasons harder on knowledge questions; "off" is fastest. |
| Conversation memory | number | 1–50 turns | How many past exchanges it keeps in mind during a chat. |

### Safety gates — what Wony may do on its own

| Field | Module | Help text |
|---|---|---|
| Change my mailbox | gmail | Send, reply, delete, mark read. Off: saved as drafts instead. |
| Change my calendar | calendar | Off: tells you what to add instead of adding it. |
| Unlock doors and open the garage | home_assistant | Off: lights/blinds still work, locks/alarms don't. |
| Type and click for me | desktop | Off: can look and read, not act — no typing, clicking, writing. |
| Install MCP tool servers | mcp | Off: states the command instead of running it. |
| Speak up on its own **(restart)** | — | Off: only answers. On: can start a conversation about a trigger. |
| Learn about me on its own **(restart)** | — | Off: remembers only what you tell it. On: also reads its own conversations (and sent mail, if Gmail is on). |
| Tell it what I'm looking at | desktop | Sends the front window's title to the AI provider with every message. |
| Summarise email with AI | gmail | Sends email text to the AI provider. |

### This computer

| Field | Module | Type | Range / choices | Help text |
|---|---|---|---|---|
| Home Assistant address | home_assistant | text | — | Same address you'd open in a browser. |
| Units | weather | choice | metric, imperial | Celsius or Fahrenheit. |
| Working day starts / ends | calendar | number ×2 | 0–23 / 1–24 | Used when finding free time. |
| Say hello at startup | — | toggle | — | Notification when Wony finishes starting. |
| Open the web page at startup | — | toggle | — | — |
| Load speech models at startup **(restart)** | — | toggle | — | Faster first reply, holds memory the whole run. |
| Web page port **(restart)** | — | number | 1024–65535 | Change only if something else already uses it. |

> Alongside the settings above, the seventeen switchable modules (§1) are
> themselves a settings surface: a plain on/off list, each with its
> one-line description, and each un-hiding its own rows in the tables above
> once switched on.

---

## 9. Accounts & external tools

**Multiple Google accounts** — Gmail and Calendar both work across any
number of named accounts (e.g. "work", "personal"). Every relevant job
takes an optional `account` parameter; left blank, it uses whichever
account is marked primary. Each account tracks its own sign-in/token status
independently.

**MCP tool servers** — external Model Context Protocol servers extend Wony
with extra tools. A server is defined by a name, a transport (stdio / sse /
http), a launch command or URL, JSON arguments, and JSON environment
variables — connected, disconnected, or edited independently of the other
52 jobs.

---

## 10. Confirmation gates

Every job that spends money, sends a message, deletes data, or moves
something physical requires confirmation before it runs — either always,
or only when a specific action word is used (e.g. deleting, not listing).
This flag is carried on the job data itself (§4), so it can drive a
confirmation step generically rather than by a hardcoded per-job list.

**Always confirms**
`close_computer`, `exit`, `type_text`, `click_at`, `click_text`,
`control_home_device`, `manage_event`, `send_email`, `modify_emails`,
`manage_playlist`, `manage_mcp_server`

**Confirms only on specific actions**

| Job | Gate words |
|---|---|
| `remember` | forget, remove, delete |
| `manage_documents` | forget, remove, delete |
| `manage_drafts` | delete |
| `manage_window` | close |
| `clipboard` | write, set, copy |
| `file` | write, append |
| `background_jobs` | stop, cancel, stop all |
| `note` | clear, empty |
| `routine` | add, save, create, edit, remove, delete, forget |
| `league` | close, quit, exit |
| `manage_google_accounts` | add, authorize, remove, rename, set_primary |
| `manage_reminders` | edit, cancel, delete, remove, stop |

Every other job listed in §2 runs without confirmation.
