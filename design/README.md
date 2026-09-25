# Handoff: Wony Desktop web app

## Overview
The desktop control surface for Wony, a modular AI assistant. It has three views (Dashboard, Modules & jobs, Macros), a permanently docked chat panel, and a notifications menu that collects errors, warnings and proactive messages.

## About the design files
The files in this bundle are **design references created in HTML**. They are prototypes that show the intended look and behavior. They are not production code to copy. The job is to **recreate these designs in the Wony web app's existing frontend environment**, using its patterns and libraries. If no frontend exists yet, choose an appropriate framework (for example React + Vite) and build the designs there.

To view a design, open the `.dc.html` file in a browser with `support.js` next to it. The markup is inline-styled HTML with `{{ }}` template holes. The `class Component` block at the bottom holds all state, the mock data and the handlers. Read it to see exactly how each control behaves.

## Fidelity
**High fidelity.** Colors, type, spacing, radii and interactions are final. Recreate them pixel-accurately. All data shown is mock data. Wire every control to the real backend described in `web-app-capability-inventory.md` (included in this bundle) (the Wony capability inventory: 52 jobs, module status, live-data snapshots, notifications/diagnostics feeds, confirmation flags).

## Backend mapping principles
- Every control calls exactly one job from the inventory (§2). The job signature shown in the UI (e.g. `routine(name="briefing")`) is the call to make.
- Confirmation is driven generically by the job catalog's `destructive` flag and gate words (§10). Do not hardcode the list.
- Live cards read the structured snapshots (§3): weather.snapshot/forecast, calendar.agenda_snapshot, scheduler.reminders_snapshot, notes.snapshot, routines.snapshot, Spotify.playback_snapshot, home_assistant.snapshot.
- Use the streaming socket (§5) for chat, so every surface stays in sync.

## Design tokens
Fonts: **Figtree** (400/500/600/700) for UI. **IBM Plex Mono** (400/500) for job names, signatures, timestamps and counts. Both come from Google Fonts.

Colors:
- Page background `#F1F5F5` · Surface `#FFFFFF` · Border `#DAE4E4` · Divider `#E6EDED`
- Ink `#102B2F` · Muted text `#56696C` · Body secondary `#3E5357`
- Main teal `#1E5A61` · Teal dark (logo text) `#17474D` · Teal soft `#E2EDED` · Status-ok dot `#3B8F8F`
- Accent light red `#EE8680` (primary buttons, switch ON, logo dot, progress) · Text on accent `#3B1311`
- Pink soft `#FCE9E7` (active nav, user chat bubble, confirm pills) · Pink faint `#FDF3F2` / `#FDF1F0` · Pink border `#F3D9D6` / `#F0CFCB`
- Red text `#9E3A34` · Section-label red `#B4524B` · Error badge `#D9534C`
- Switch OFF `#C5D3D4` · Modal scrim `rgba(16,43,47,0.45)`

Type scale: page title 28/700/-0.02em · card title 16–20/600–700 · body 14–15 · section labels 13/600 uppercase, 0.08em tracking, `#B4524B` · mono 11–14.
Radii: cards 14 · buttons 9–10 · pills/nav 20 · switch 13 (44×26, knob 20) · modal 16.
Spacing: page padding 32 horizontal · grid gaps 12 · card padding 16–20.
Shadow: notifications dropdown only, `0 18px 40px rgba(16,43,47,0.16)`.

## Layout
- Root: CSS grid `minmax(0,1fr) minmax(300px,360px)`, full viewport height. The left column is the scrolling main area. The right column is the chat. **The chat is always visible and has no toggle.**
- **Top bar** (sticky inside main, white, bottom border `#F3D9D6`, padding 10px 24px, wraps on narrow widths):
  - Logo (22px accent circle + "Wony" 19/700 teal-dark).
  - Nav pills: Dashboard · Modules & jobs · Macros, each with a mono count. Active = `#FCE9E7` bg with `#9E3A34` text. The nav scrolls horizontally if space runs out.
  - Right: a 40px round bell button (bg `#FDF3F2`, stroke `#9E3A34`) with a red count badge.
- **Page header**: title + subtitle. On Dashboard it also has a "Customize"/"Done" pill button.

## Screens
### 1. Dashboard
- **Quick controls**: grid `repeat(auto-fill,minmax(220px,1fr))`, gap 12. Each card is white, 14 radius, min-height 148. It shows the module id (mono 11), a title (16/600), a status line (13 muted) and a control at the bottom. Control types:
  - `run`: accent "Run" button. Examples: routine briefing, routine good night, computer_health.
  - `toggle`: switch in the top-right. Examples: living room lights → control_home_device; watch inbox → watch_inbox start/stop.
  - `presets`: teal-soft chips "5 min / 10 min / 25 min" → add_reminder(when="in N minutes").
  - `slider`: range 0–100 → set_volume(level).
  - `input`: text field + Add → note(action="add", list_name="shopping").
- **Customize mode**: every card gets a 24px red × badge (remove). A dashed "+ Add control" card opens the **job picker modal**: a searchable list of all 52 jobs from the job catalog (§4), excluding already-pinned jobs. Picking a job adds a generic `run` card. Persist pins per user.
- **Widgets**, grid `repeat(auto-fit,minmax(300px,1fr))`:
  - Now playing: art placeholder 84px (use art_url), title/artist, progress bar, prev / play-pause (52px accent) / next.
  - Agenda: time in red mono + title + meta.
  - Weather: 52px temperature, conditions, 5-day chips on pink-faint.
  - Home: full row (`grid-column:1/-1`), device rows with switches. **Guarded devices (locks) must confirm** before acting.
  - Timers & reminders + Shopping: shopping items are pink chips; tap × removes via note(action="remove").
- Every dashboard action also posts to the chat as an assistant message tagged "Ran from Dashboard", with the call chip.

### 2. Modules & jobs
- Two columns: a sticky module list (300px) and the detail.
- **List**: search input (filters modules by name, or by any job name they contain). Rows show a status dot (enabled `#3B8F8F`, misconfigured/error `#EE8680`, disabled `#B4C2C4`), the name and a job count.
- **Detail header**: name, mono id, status pill, on/off switch (hidden for the always-on modules ai/status/employer). When misconfigured, it adds a pink box with the reason, the mono hint and a "Retry" button → system_status(scope="retry").
- **Job cards**: mono signature and summary. A confirmation pill shows "Always confirms" or "Confirms on: …", and a "Pinned" pill appears when the job is on the dashboard. Expanding a card shows one input per parameter (required ones are labelled), plus Run and Pin to dashboard buttons. Build the forms from the typed parameter schema. Use selects for enum params such as scope and when.

### 3. Macros
- Card grid `repeat(auto-fill,minmax(300px,1fr))` showing routines (routines.snapshot). Each card has the name, an optional schedule chip (mono, teal-soft) and the steps in plain words.
- Buttons: Run → routine(name). Edit (inline textarea) → Save, which **confirms** routine(action="add"). Delete **confirms** routine(action="remove").
- The "New macro" card has name, steps and an optional schedule (e.g. "every weekday at 7am"). Save confirms. A schedule creates add_reminder(when, action_job="routine", action_args={name}).

### Chat panel (always visible)
- Header: "Chat" + "Clear" → clear_conversation().
- Messages:
  - User: right-aligned, `#FCE9E7` bg, `#4A1A17` text, radius 14/14/4/14.
  - Assistant: left-aligned, `#F1F5F5` bg, with mono call chips (`calls[]`) below.
  - Proactive messages show a red uppercase tag, e.g. "Spoke up · event_soon".
  - A confirmation request renders inline as an accent-bordered card with the signature and Confirm/Cancel. After resolving it shows "Confirmed · done" or "Cancelled".
- Composer: 3 suggestion chips, a text input (Enter sends), a MIC button (voice upload per §5; active state = accent) and Send. Show "Wony is thinking…" while waiting, and stream tokens from the socket. Auto-scroll to the bottom on new messages.

### Notifications menu (bell)
- Dropdown 420px, anchored to the top-right of the top bar.
- Header (pink-faint): "Notifications" + "Dismiss all", then a system line (online/provider, model in mono, speech device, modules-on count), then filter pills: All · Errors & warnings · Messages.
- Rows: a level pill (error = `#D9534C`/white, warning = pink-soft/red, info = teal-soft/teal, message = pink-faint/`#B4524B`), the message, an optional mono hint, then mono "ts · source". Some rows have an "Open module" link that jumps to the module detail. Each row has Dismiss.
- Sources: the diagnostics feed (level/source/message/hint/ts) plus the notifications feed (proactive triggers, `acknowledged`). Dismiss = acknowledge. The badge shows the unacknowledged count.

### Confirmation modal
Used for every always-confirm job or gate word triggered outside chat. Scrim, 420px white card, red uppercase "Needs confirmation", 20/700 title, mono signature box, and Cancel (teal-soft) / Confirm (accent) buttons.

## State
view · editing · pins[] (persist) · toggles/device states (from snapshots) · module enabled map · selected module / open job · job arg drafts · routines[] · chat messages[] + thinking · notifications[] + filter + open · modal {title, sig, onConfirm} · picker open + query.

## Responsive
The top bar wraps. The widget and quick-control grids reflow with auto-fill. The chat column stays between 300 and 360px.

## Files
- `Wony Desktop.dc.html`: the design reference (template + logic with all mock data)
- `support.js`: runtime needed only to open the reference in a browser
- `web-app-capability-inventory.md`: the backend capability inventory
