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

// Streams the assistant reply. `onDelta` fires for each text chunk as it
// arrives; the resolved value is the final turn (id + full text + calls).
export async function streamChat(
  message: string,
  onDelta: (chunk: string) => void,
): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  if (!res.ok || !res.body) throw new Error(`Chat failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let final: ChatResponse = { id: null, text: '', calls: [] };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith('data:')) continue;
      const evt = JSON.parse(line.slice(5).trim()) as
        | { type: 'delta'; data: string }
        | { type: 'final'; data: ChatResponse }
        | { type: 'error'; data: string };
      if (evt.type === 'delta') onDelta(evt.data);
      else if (evt.type === 'final') final = evt.data;
      else if (evt.type === 'error') throw new Error(evt.data);
    }
  }
  return final;
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

export type WsEvent =
  | ({ type: 'turn' } & HistoryTurn)
  | Diagnostic;

export function connectEventSocket(handlers: {
  onTurn?: (turn: HistoryTurn) => void;
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
        } else {
          handlers.onTurn?.(data as HistoryTurn);
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

export function connectTurnsSocket(
  onTurn: (turn: HistoryTurn) => void,
): () => void {
  return connectEventSocket({ onTurn });
}
