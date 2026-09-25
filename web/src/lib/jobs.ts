import type { Confirms } from '../api';

/** Mirrors helpers/confirm.py's `_applies`: `true` covers every call, a list
 * covers only the listed values of the job's `action` argument. Kept in sync
 * with the backend on purpose — this must never invent its own rule. */
export function needsConfirm(confirms: Confirms, args: Record<string, unknown>): boolean {
  if (confirms === true) return true;
  if (!confirms || confirms.length === 0) return false;
  const action = String(args.action ?? '').trim().toLowerCase();
  return confirms.some((value) => String(value).toLowerCase() === action);
}

export function confirmLabel(confirms: Confirms): string {
  if (confirms === true) return 'Always confirms';
  if (Array.isArray(confirms) && confirms.length > 0) return `Confirms on: ${confirms.join(', ')}`;
  return '';
}

/** `note(action="add", text="milk")` — only args with a value are shown, the
 * same convention the design's mockup and the chat's call chips use. */
export function signature(name: string, args: Record<string, unknown> = {}): string {
  const parts = Object.entries(args)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}`);
  return `${name}(${parts.join(', ')})`;
}

export function humanize(name: string): string {
  return name.replace(/_/g, ' ');
}

/** Jobs whose entire job is reading or controlling something a dashboard
 * widget already shows live (Now playing, Agenda, Weather, Home, Inbox) —
 * pinning one as a Quick Control would just be a second copy of the same
 * panel. Jobs that *do* something a widget doesn't (play_songs, manage_event,
 * control_home_device for one specific device) stay pinnable. */
const WIDGET_COVERED_JOBS = new Set([
  'control_playback', // Now playing already has prev/play-pause/next
  'spotify_info', // ...and the current track's title/artist
  'find_events', // Agenda already lists today's events
  'weather', // Weather widget already shows current + 5-day forecast
  'list_home_devices', // Home widget already lists every device and its state
  'find_emails', // Inbox widget already lists unread mail
]);

export function isWidgetCovered(name: string): boolean {
  return WIDGET_COVERED_JOBS.has(name);
}
