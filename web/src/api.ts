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

export interface AppConfig {
  assistant: { name: string; language: string };
  voice: { stt: { silence_ms: number; start_timeout: number; max_seconds: number } };
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
  | Diagnostic;

export async function transcribeAudio(blob: Blob): Promise<string> {
  const res = await fetch(`${BASE}/stt`, {
    method: 'POST',
    body: blob,
    headers: { 'Content-Type': blob.type || 'audio/webm' },
  });
  if (!res.ok) throw new Error(`STT failed: ${res.status}`);
  const data = await res.json();
  return data.text ?? '';
}

export function connectEventSocket(handlers: {
  onTurn?: (turn: HistoryTurn, sessionId?: string) => void;
  onDelta?: (chunk: string, sessionId: string) => void;
  onError?: (message: string, sessionId: string) => void;
  onDiagnostic?: (d: Diagnostic) => void;
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
        } else {
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
        } else {
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
