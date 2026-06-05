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

export interface HealthResponse {
  provider: string;
  model: string | null;
  modules: Record<string, HealthModule>;
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

export async function clearChat(): Promise<void> {
  await fetch(`${BASE}/chat/clear`, { method: 'POST' });
}

export interface HistoryTurn {
  user: string;
  assistant: string;
  ts: string;
}

export async function fetchHistory(limit = 50): Promise<HistoryTurn[]> {
  const res = await fetch(`${BASE}/chat/history?limit=${limit}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.turns ?? [];
}
