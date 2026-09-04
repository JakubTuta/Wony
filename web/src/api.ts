export interface JobParameter {
  type: string;
  description: string;
  items?: { type: string };
}

export interface Job {
  name: string;
  module: string;
  summary: string;
  description: string;
  destructive: boolean;
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

export interface GoogleAccount {
  name: string;
  email: string;
  primary: boolean;
  tokens: { gmail: boolean; calendar: boolean };
}

export interface AccountsPanel {
  accounts: GoogleAccount[];
  primary: string | null;
  services: { gmail: boolean; calendar: boolean };
  credentials_ready: boolean;
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
  assistant: { name: string; language: string };
  voice: { stt: { silence_ms: number; start_timeout: number; max_seconds: number } };
}

// ── Settings ───────────────────────────────────────────────────────────────
// Everything a user may change without opening config.yaml. The server owns
// the list; the UI only renders what it is given.

export interface SettingField {
  key: string;
  label: string;
  kind: 'text' | 'longtext' | 'number' | 'toggle' | 'choice';
  help: string;
  choices: string[];
  min: number | null;
  max: number | null;
  step: number | null;
  restart: boolean;
  value: string | number | boolean | null;
}

export interface SettingsResponse {
  sections: { title: string; fields: SettingField[] }[];
  modules: { key: string; label: string; help: string; enabled: boolean }[];
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
  when_str: string;
  repeating: boolean;
  next_run: string | null;
}

export interface RemindersPanel {
  reminders: Reminder[];
}

export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch(`${BASE}/config`);
  if (!res.ok) throw new Error(`Config fetch failed: ${res.status}`);
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

export async function invokeJob(name: string, args: Record<string, string>): Promise<InvokeResponse> {
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
  if (!res.ok) throw new Error(`STT failed: ${res.status}`);
  const data = await res.json();
  return { text: data.text ?? '', warning: data.warning };
}

export function connectEventSocket(handlers: {
  onTurn?: (turn: HistoryTurn, sessionId?: string) => void;
  onDelta?: (chunk: string, sessionId: string) => void;
  onError?: (message: string, sessionId: string) => void;
  onDiagnostic?: (d: Diagnostic) => void;
  onNotification?: (n: Notification) => void;
}): () => void {
  const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`;
  let ws: WebSocket | null = null;
  let closed = false;
  let retryTimeout: ReturnType<typeof setTimeout> | null = null;

  function connect() {
    if (closed) return;
    ws = new WebSocket(wsUrl);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as WsEvent;
        if (data.type === 'diagnostic') {
          handlers.onDiagnostic?.(data as Diagnostic);
        } else if (data.type === 'delta') {
          handlers.onDelta?.(data.data, data.session_id);
        } else if (data.type === 'error') {
          handlers.onError?.(data.data, data.session_id);
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
      if (!closed) {
        retryTimeout = setTimeout(connect, 3000);
      }
    };
    ws.onerror = () => ws?.close();
  }

  connect();

  return () => {
    closed = true;
    if (retryTimeout) clearTimeout(retryTimeout);
    ws?.close();
  };
}

export function connectChatSocket(handlers: {
  onTurn?: (turn: HistoryTurn, sessionId?: string) => void;
  onDelta?: (chunk: string, sessionId: string) => void;
  onError?: (message: string, sessionId: string) => void;
  onDiagnostic?: (d: Diagnostic) => void;
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
          // Swallowed here on purpose: the header owns notifications through
          // connectEventSocket. Without this branch it falls through and lands
          // in the transcript as a turn.
        } else if (data.type === 'turn') {
          // 'cancel'/'state' broadcasts must not fall through as phantom turns
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
