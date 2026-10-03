import type { Job } from '../api';

type Gate = Pick<Job, 'confirms' | 'confirm_words'>;

/** Mirrors helpers/confirm.py's `_applies`: a gated job with no word list asks
 * on every call, otherwise only on the listed values of its `action` argument.
 * Kept in sync with the backend on purpose — this must never invent its own rule. */
export function needsConfirm(job: Gate, args: Record<string, unknown>): boolean {
  if (!job.confirms) return false;
  if (job.confirm_words === null) return true;
  const action = String(args.action ?? '').trim().toLowerCase();
  return job.confirm_words.includes(action);
}

export function confirmLabel(job: Gate): string {
  if (!job.confirms) return '';
  if (job.confirm_words === null) return 'Always confirms';
  return `Confirms on: ${job.confirm_words.join(', ')}`;
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

/** "action: delete, id: abc123" — a confirm card's args in prose, not code.
 * Mirrors signature()'s filtering (only args with a value) but drops the
 * quotes and parens that make sense in a call chip, not in a sentence. */
export function readableArgs(args: Record<string, unknown> = {}): string {
  return Object.entries(args)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${humanize(k)}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(', ');
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
