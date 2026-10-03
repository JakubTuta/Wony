export interface JobParameter {
  type: string;
  description: string;
  items?: { type: string };
  enum?: (string | number | boolean)[];
}

/** `true` = always confirms, `false` = never, a list = confirms when its
 * `action` argument matches one of these words (see helpers/confirm.py). */
export type Confirms = boolean | string[];

export interface Job {
  name: string;
  module: string;
  summary: string;
  description: string;
  confirms: Confirms;
  parameters: {
    properties: Record<string, JobParameter>;
    required: string[];
  };
}

export interface HealthModule {
  status: string;
  reason: string;
  hint: string;
}

export interface Compute {
  stt_device: 'GPU' | 'CPU' | string;
  tts_device: 'GPU' | 'CPU' | string;
  cuda_ok: boolean;
  hint: string;
}

export interface Diagnostic {
  type: 'diagnostic';
  level: 'info' | 'warning' | 'error';
  source: string;
  message: string;
  hint: string;
  ts: string;
}

export interface HealthResponse {
  provider: string;
  model: string | null;
  modules: Record<string, HealthModule>;
  compute?: Compute;
  diagnostics?: Diagnostic[];
  background: string[];
  /** Whether each watcher (helpers/triggers.py) is on, by trigger name. */
  triggers: Record<string, boolean>;
}

export interface JobsResponse {
  jobs: Job[];
}

export interface InvokeResponse {
  ok: boolean;
  result: string;
  error?: string;
}

export interface ChatCall {
  name: string;
  args: Record<string, unknown>;
  result: string;
  needs_confirm?: boolean;
}

export interface ChatResponse {
  id: number | null;
  text: string;
  calls: ChatCall[];
}

const BASE = '/api';

// ── Panels ─────────────────────────────────────────────────────────────────
// A panel is what a job would have said, handed over before it became a
// sentence. Reading one never involves the model.

export interface PanelInfo {
  key: string;
  label: string;
  module: string;
}

export interface WeatherPanel {
  city: string;
  description: string;
  temperature: number | null;
  feels_like: number | null;
  unit: string;
  humidity: number | null;
  wind: number | null;
  wind_unit: string;
  icon: string;
  condition: number;
  sunrise: number | null;
  sunset: number | null;
  error: string | null;
}

export interface ForecastDay {
  date: string;
  label: string;
  high: number;
  low: number;
  description: string;
}

export interface ForecastPanel {
  city: string;
  today: string;
  unit: string;
  days: ForecastDay[];
  error: string | null;
}

export interface AgendaEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  account: string;
}

export interface AgendaPanel {
  events: AgendaEvent[];
  today: string;
  days: string[];
  timezone: string;
}

// One entity, already decided to be exactly one widget.
export interface Control {
  entity_id: string;
  name: string;
  domain: string;
  state: string;
  on: boolean;
  available: boolean;
  level: number | null;
  options: string[];
  press: boolean;
  number: boolean;
  toggle: boolean;
  slider: boolean;
  guarded: boolean;
}

export interface Device {
  name: string;
  primary: Control;
  extras: Control[];
}

export interface DevicesPanel {
  areas: { name: string; devices: Device[] }[];
  locks_allowed: boolean;
}

export interface NowPlaying {
  active: boolean;
  is_playing?: boolean;
  title?: string;
  artist?: string;
  album?: string;
  art_url?: string | null;
  progress_ms?: number;
  duration_ms?: number;
  shuffle?: boolean;
  device?: string;
  volume?: number | null;
}

/** One sign-in per account covers every Google module (helpers/google_auth.py). */
export interface GoogleAccount {
  name: string;
  email: string;
  primary: boolean;
  signed_in: boolean;
  /** Google signed Wony out (weekly in Testing mode), or a switch needs a new OK. */
  needs_sign_in: boolean;
  /** Which Google modules the current sign-in covers. */
  modules: Record<string, boolean>;
  signed_in_at: string;
}

export interface AccountsPanel {
  accounts: GoogleAccount[];
  primary: string | null;
  /** Which Google modules are switched on. */
  services: Record<string, boolean>;
  credentials_ready: boolean;
}

export interface InboxMessage {
  id: string;
  sender: string;
  subject: string;
  snippet: string;
  date: string;
}

export interface InboxPanel {
  unread_total: number;
  messages: InboxMessage[];
  error: string | null;
}

/** A panel read that never throws — every caller wants to show the failure. */
export interface PanelResult<T> {
  data: T | null;
  error: string | null;
}

export async function fetchPanels(): Promise<PanelInfo[]> {
  const res = await fetch(`${BASE}/panels`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.panels ?? [];
}

export async function fetchPanel<T>(key: string): Promise<PanelResult<T>> {
  try {
    const res = await fetch(`${BASE}/panel/${key}`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { data: null, error: body.detail ?? `Could not load ${key}.` };
    }
    return { data: await res.json(), error: null };
  } catch {
    return { data: null, error: 'Wony is not responding.' };
  }
}

export async function controlDevice(
  entity_id: string,
  action: string,
  value?: number,
  option?: string,
): Promise<{ ok: boolean; text: string }> {
  try {
    const res = await fetch(`${BASE}/devices/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entity_id, action, value, option }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, text: body.detail ?? 'That did not work.' };
    }
    return res.json();
  } catch {
    return { ok: false, text: 'Wony is not responding.' };
  }
}

// ── Notifications ──────────────────────────────────────────────────────────

export interface Notification {
  id: number | null;
  ts: string;
  kind: 'info' | 'reminder' | 'alert' | 'error';
  source: string;
  text: string;
  acknowledged: boolean;
}

export async function fetchNotifications(): Promise<Notification[]> {
  try {
    const res = await fetch(`${BASE}/notifications`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.notifications ?? [];
  } catch {
    return [];
  }
}

/** Omit the id to clear everything unread. */
export async function ackNotifications(id?: number): Promise<void> {
  await fetch(`${BASE}/notifications/ack`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(id === undefined ? {} : { id }),
  }).catch(() => {});
}

export interface AppConfig {
  assistant: { name: string };
  /** False when the server was started on its own (no tray to relaunch it). */
  can_restart: boolean;
  voice: { stt: { silence_ms: number; max_seconds: number } };
}

export interface Capability {
  key: string;
  label: string;
  description: string;
  example: string;
}

export interface Capabilities {
  working: Capability[];
  available: Capability[];
}

// ── Settings ───────────────────────────────────────────────────────────────
// Everything a user may change without opening config.yaml. The server owns
// the list; the UI only renders what it is given.

export interface SettingField {
  key: string;
  label: string;
  kind: 'text' | 'longtext' | 'number' | 'toggle' | 'choice' | 'secret';
  help: string;
  choices: string[];
  /** Display text for a choice whose raw value (a voice name like "af_heart")
   * means nothing on its own. Choices absent here just show their own value. */
  choice_labels: Record<string, string>;
  min: number | null;
  max: number | null;
  step: number | null;
  restart: boolean;
  /** Which module this field only applies to, or '' for a global setting.
   * Module-scoped fields render on that module's page instead of Settings. */
  module: string;
  /** For kind 'secret': true/false means whether it's set in .env — the
   * actual value is never sent to the browser. A typed string is a new
   * value waiting to be saved. */
  value: string | number | boolean | null;
}

export interface SettingsModule {
  key: string;
  label: string;
  help: string;
  example: string;
  enabled: boolean;
  always_on: boolean;
}

export interface SettingsResponse {
  sections: { title: string; fields: SettingField[] }[];
  modules: SettingsModule[];
  config_file: string;
}

export interface SettingsSaveResult {
  written: string[];
  restart_required: boolean;
}

export async function fetchSettings(): Promise<SettingsResponse> {
  const res = await fetch(`${BASE}/settings`);
  if (!res.ok) throw new Error(`Could not load settings: ${res.status}`);
  return res.json();
}

export async function saveSettings(
  updates: Record<string, unknown>,
  modules?: string[],
): Promise<SettingsSaveResult> {
  const res = await fetch(`${BASE}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ updates, modules: modules ?? null }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? 'Could not save settings.');
  }
  return res.json();
}

export interface Reminder {
  id: string;
  text: string;
  action_job: string;
  action_args: Record<string, unknown>;
  when_str: string;
  repeating: boolean;
  next_run: string | null;
}

export interface RemindersPanel {
  reminders: Reminder[];
}

export interface NoteList {
  name: string;
  count: number;
  items: string[];
}

export interface NotesPanel {
  lists: NoteList[];
}

export interface RoutineSummary {
  name: string;
  steps: string;
}

export interface RoutinesPanel {
  routines: RoutineSummary[];
}

export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch(`${BASE}/config`);
  if (!res.ok) throw new Error(`Config fetch failed: ${res.status}`);
  return res.json();
}

export async function restartApp(): Promise<void> {
  const res = await fetch(`${BASE}/restart`, { method: 'POST' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `Restart failed (${res.status}).`);
  }
}

export async function fetchCapabilities(): Promise<Capabilities> {
  const res = await fetch(`${BASE}/capabilities`);
  if (!res.ok) throw new Error(`Capabilities fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function fetchJobs(): Promise<Job[]> {
  const res = await fetch(`${BASE}/jobs`);
  if (!res.ok) throw new Error(`Failed to load jobs: ${res.status}`);
  const data: JobsResponse = await res.json();
  return data.jobs;
}

// ── Dashboard pins ───────────────────────────────────────────────────────
// Persisted server-side (memory_db kv) so Customize survives a reload and a
// second tab, unlike a browser-only setting the model never sees.

export type PinKind = 'run' | 'toggle' | 'presets' | 'slider' | 'input';

export interface Pin {
  id: string;
  kind: PinKind;
  job: string;
  /** The job's module at pin time, kept even if the job stops being
   * registered later (module turned off/broken) so the card can still say
   * what to turn back on. */
  module: string;
  title: string;
  args: Record<string, unknown>;
}

/** null means nothing saved yet — the caller should seed defaults. */
export async function fetchPins(): Promise<Pin[] | null> {
  const res = await fetch(`${BASE}/pins`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.pins ?? null;
}

export async function savePins(pins: Pin[]): Promise<void> {
  const res = await fetch(`${BASE}/pins`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pins }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? 'Could not save your dashboard.');
  }
}

export async function invokeJob(name: string, args: Record<string, unknown> = {}): Promise<InvokeResponse> {
  const res = await fetch(`${BASE}/invoke`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, args }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    return { ok: false, result: '', error: err.detail ?? 'Request failed' };
  }
  return res.json();
}

export async function sendChat(message: string): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
  return res.json();
}

export async function clearChat(): Promise<void> {
  await fetch(`${BASE}/chat/clear`, { method: 'POST' });
}

export async function wipeData(): Promise<void> {
  const res = await fetch(`${BASE}/data/wipe`, { method: 'POST' });
  if (!res.ok) throw new Error(`Wipe failed: ${res.status}`);
}

export interface HistoryTurn {
  id: number | null;
  user: string;
  assistant: string;
  ts: string;
  calls?: ChatCall[];
}

export async function fetchHistory(limit = 50): Promise<HistoryTurn[]> {
  const res = await fetch(`${BASE}/chat/history?limit=${limit}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.turns ?? [];
}

export type AssistantState = 'idle' | 'listening' | 'thinking' | 'speaking';

export type WsEvent =
  | ({ type: 'turn'; session_id?: string } & HistoryTurn)
  | ({ type: 'delta'; session_id: string; data: string })
  | ({ type: 'error'; session_id: string; data: string })
  | ({ type: 'state'; state: AssistantState })
  | ({ type: 'notification' } & Notification)
  | Diagnostic;

export interface TranscribeResult {
  text: string;
  warning?: string;
}

export async function transcribeAudio(blob: Blob): Promise<TranscribeResult> {
  const res = await fetch(`${BASE}/stt`, {
    method: 'POST',
    body: blob,
    headers: { 'Content-Type': blob.type || 'audio/webm' },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Voice input failed (${res.status}).`);
  return { text: data.text ?? '', warning: data.warning };
}

/** One socket for the whole app: chat streaming, the notification bell and
 * the diagnostics feed all ride it, so a lost connection is one reconnect
 * instead of three racing ones. */
export function connectSocket(handlers: {
  onTurn?: (turn: HistoryTurn, sessionId?: string) => void;
  onDelta?: (chunk: string, sessionId: string) => void;
  onError?: (message: string, sessionId: string) => void;
  onDiagnostic?: (d: Diagnostic) => void;
  onNotification?: (n: Notification) => void;
  onState?: (state: AssistantState) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}): { send: (message: string, sessionId: string) => void; stop: (sessionId: string) => void; disconnect: () => void } {
  let ws: WebSocket | null = null;
  let closed = false;
  let retryTimeout: ReturnType<typeof setTimeout> | null = null;
  let retryDelay = 3000;

  const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`;

  function connect() {
    if (closed) return;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      retryDelay = 3000;
      handlers.onConnect?.();
    };

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as WsEvent;
        if (data.type === 'diagnostic') {
          handlers.onDiagnostic?.(data as Diagnostic);
        } else if (data.type === 'delta') {
          handlers.onDelta?.(data.data, data.session_id);
        } else if (data.type === 'error') {
          handlers.onError?.(data.data, data.session_id);
        } else if (data.type === 'state') {
          handlers.onState?.((data as { type: 'state'; state: AssistantState }).state);
        } else if (data.type === 'notification') {
          handlers.onNotification?.(data as Notification);
        } else if (data.type === 'turn') {
          handlers.onTurn?.(data as HistoryTurn, (data as { session_id?: string }).session_id);
        }
      } catch {
        // ignore malformed
      }
    };

    ws.onclose = () => {
      ws = null;
      handlers.onDisconnect?.();
      if (!closed) {
        retryTimeout = setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 30000);
          connect();
        }, retryDelay);
      }
    };

    ws.onerror = () => ws?.close();
  }

  connect();

  return {
    send(message: string, sessionId: string) {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'chat', message, session_id: sessionId }));
      }
    },
    stop(sessionId: string) {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'stop', session_id: sessionId }));
      }
    },
    disconnect() {
      closed = true;
      if (retryTimeout) clearTimeout(retryTimeout);
      ws?.close();
    },
  };
}
