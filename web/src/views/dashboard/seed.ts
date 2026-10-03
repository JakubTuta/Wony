import type { Job, Pin, PinKind } from '../../api';
import { isWidgetCovered } from '../../lib/jobs';

interface Seed {
  id: string;
  job: string;
  kind: PinKind;
  title: string;
  args: Record<string, unknown>;
  /** Only offered when this module is on — a watcher job lives in `status`,
   * but watching the inbox means nothing without Gmail. */
  needs?: string;
}

// Offered the first time a user opens the dashboard (server has no saved pins
// yet). Deliberately more than the bare minimum: an empty-looking dashboard on
// day one is also the day someone never discovers Features has 50 more
// of these. Each only appears if this install actually registered the job —
// a module can be switched on in config but still missing its Python deps.
// A job also covered by a static dashboard widget (Now playing, Agenda,
// Weather, Home, Inbox) is deliberately left out here — the widget already
// shows it, and pinning it too would be a second copy of the same panel.
// Every switchable module gets at least one entry here, or is already fully
// represented by a static widget (weather, spotify's now-playing, gmail's
// inbox, home_assistant's device list) — `web` is the one exception, because
// every one of its jobs needs a query/URL argument with no sane default.
const SEEDS: Seed[] = [
  { id: 'time', job: 'get_datetime', kind: 'run', title: 'What time is it', args: {} },
  { id: 'briefing', job: 'routine', kind: 'run', title: 'Morning briefing', args: { name: 'briefing' } },
  { id: 'timer', job: 'add_reminder', kind: 'presets', title: 'Quick timer', args: {} },
  { id: 'shop', job: 'note', kind: 'input', title: 'Add to shopping', args: { list_name: 'shopping' } },
  { id: 'health', job: 'computer_health', kind: 'run', title: 'Computer health', args: {} },
  { id: 'vol', job: 'set_volume', kind: 'slider', title: 'Spotify volume', args: { level: 50 } },
  { id: 'inbox', job: 'manage_triggers', kind: 'toggle', title: 'Watch inbox', args: { name: 'new_email' }, needs: 'gmail' },
  { id: 'watchcal', job: 'manage_triggers', kind: 'toggle', title: 'Watch calendar', args: { name: 'new_event' }, needs: 'calendar' },
  { id: 'accounts', job: 'manage_google_accounts', kind: 'run', title: 'List Google accounts', args: {} },
  { id: 'windows', job: 'manage_window', kind: 'run', title: 'List open windows', args: {} },
  { id: 'screen', job: 'look_at_screen', kind: 'run', title: 'Look at the screen', args: {} },
  { id: 'song', job: 'identify_song', kind: 'run', title: 'What song is playing', args: {} },
  { id: 'league', job: 'league', kind: 'run', title: 'Launch League of Legends', args: {} },
  { id: 'mcp', job: 'manage_mcp_server', kind: 'run', title: 'List tool servers', args: { action: 'list' } },
  { id: 'status', job: 'system_status', kind: 'run', title: 'What can Wony do', args: {} },
];

export function defaultPins(jobsByName: Map<string, Job>): Pin[] {
  const seeds: Pin[] = [];
  const modulesOn = new Set([...jobsByName.values()].map((j) => j.module));
  for (const s of SEEDS) {
    if (isWidgetCovered(s.job)) continue;
    if (s.needs && !modulesOn.has(s.needs)) continue;
    const job = jobsByName.get(s.job);
    if (!job) continue;
    seeds.push({ id: s.id, kind: s.kind, job: s.job, module: job.module, title: s.title, args: s.args });
  }
  return seeds;
}

/** A toggle pin turns one watcher (helpers/triggers.py) on or off; its live
 * state comes from health.triggers. */
export function isToggleOn(pin: Pin, triggers: Record<string, boolean> | undefined): boolean {
  return Boolean(triggers?.[String(pin.args.name ?? '')]);
}
