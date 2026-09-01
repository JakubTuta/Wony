/** Typed client for the Wony kiosk API.
 *
 *  Everything the screen can do goes through here. The WebSocket is the only
 *  stateful part; useWony owns the single connection and this file only knows
 *  how to open one and keep it open.
 */

const BASE = '/api'

// ── Shapes ──────────────────────────────────────────────────────────────────

export interface Tile {
  id: string
  label: string
  icon: string
  /** A screen tile runs nothing — it names a place in this app to go. */
  kind: 'job' | 'prompt' | 'screen'
  job: string | null
  prompt: string | null
  screen: string | null
  args: Record<string, unknown>
}

export interface TileResult {
  ok: boolean
  text: string
  source: string
}

export interface NotificationRecord {
  id: number | null
  ts?: string
  kind: 'info' | 'reminder' | 'alert' | 'error'
  source: string
  text: string
  acknowledged?: boolean
}

export interface AmbientCard {
  key: string
  label: string
  text: string
}

export interface NowPlaying {
  active: boolean
  is_playing?: boolean
  title?: string
  artist?: string
  album?: string
  art_url?: string | null
  progress_ms?: number
  duration_ms?: number
  shuffle?: boolean
  device?: string
  volume?: number | null
}

export interface WeatherPanel {
  city: string
  description: string
  temperature: number | null
  feels_like: number | null
  unit: string
  humidity: number | null
  wind: number | null
  wind_unit: string
  /** OpenWeatherMap icon code, e.g. "04n" — the trailing d/n is day/night. */
  icon: string
  /** OpenWeatherMap condition id; the hundreds digit is the weather family. */
  condition: number
  sunrise: number | null
  sunset: number | null
  error: string | null
}

export interface AgendaEvent {
  id: string
  title: string
  /** ISO datetime, or a bare ISO date when all_day. */
  start: string
  end: string
  all_day: boolean
  location: string
  account: string
}

export interface AgendaPanel {
  events: AgendaEvent[]
  today: string
  /** The days that were actually queried, so an empty one reads as "nothing
   *  on" rather than "not loaded yet". */
  days: string[]
  timezone: string
}

export interface Device {
  entity_id: string
  name: string
  domain: string
  state: string
  on: boolean
  available: boolean
  brightness: number | null
  dimmable: boolean
  /** Locks, alarms and garage doors. Shown, but refused unless
   *  modules.home_assistant.allow_locks is on. */
  guarded: boolean
}

export interface DevicesPanel {
  areas: { name: string; devices: Device[] }[]
  locks_allowed: boolean
}

export interface GoogleAccount {
  name: string
  email: string
  primary: boolean
  /** A stored token per service. True means signed in at some point, not that
   *  Google still accepts it — only using it can prove that. */
  tokens: { gmail: boolean; calendar: boolean }
}

export interface GoogleAccountsSnapshot {
  accounts: GoogleAccount[]
  primary: string | null
  /** Which Google services are switched on, so the screen only reports on
   *  those. An account has no calendar token to be missing if calendar is off. */
  services: { gmail: boolean; calendar: boolean }
  credentials_ready: boolean
}

export interface JobParameter {
  type: string
  description: string
  items?: { type: string }
}

export interface Job {
  name: string
  module: string
  summary: string
  description: string
  destructive: boolean
  parameters: {
    properties: Record<string, JobParameter>
    required: string[]
  }
}

export interface HealthModule {
  status: string
  reason: string
  hint: string
}

export interface Diagnostic {
  type: 'diagnostic'
  level: 'info' | 'warning' | 'error'
  source: string
  message: string
  hint: string
  ts: string
}

export interface HealthResponse {
  provider: string
  model: string | null
  modules: Record<string, HealthModule>
  diagnostics?: Diagnostic[]
}

export interface AppConfig {
  assistant: { name: string; language: string }
  kiosk: { idle_minutes: number }
}

export interface ChatCall {
  name: string
  args: Record<string, unknown>
  result: string
}

export interface HistoryTurn {
  id: number | null
  user: string
  assistant: string
  ts: string
  calls?: ChatCall[]
}

export interface InvokeResponse {
  ok: boolean
  result: string
  error?: string
}

export type AssistantState = 'idle' | 'thinking'

export type WsEvent =
  | ({ type: 'turn'; session_id?: string } & HistoryTurn)
  | { type: 'delta'; session_id: string; data: string }
  | { type: 'error'; session_id: string; data: string }
  | { type: 'state'; state: AssistantState }
  | { type: 'cancel' }
  | ({ type: 'notification' } & NotificationRecord)
  | Diagnostic

// ── Requests ────────────────────────────────────────────────────────────────

async function getJson<T>(path: string, fallback?: T): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    if (fallback !== undefined) return fallback
    throw new Error(`${path} failed: ${res.status}`)
  }
  return res.json()
}

export async function fetchConfig(): Promise<AppConfig> {
  return getJson<AppConfig>('/config')
}

export async function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/health')
}

export async function fetchTiles(): Promise<Tile[]> {
  const data = await getJson<{ tiles: Tile[] }>('/tiles', { tiles: [] })
  return data.tiles ?? []
}

export async function runTile(id: string): Promise<TileResult> {
  const res = await fetch(`${BASE}/tiles/${encodeURIComponent(id)}`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    return { ok: false, text: err.detail ?? 'That tile is not available.', source: id }
  }
  return res.json()
}

export async function fetchAmbient(): Promise<AmbientCard[]> {
  const data = await getJson<{ cards: AmbientCard[] }>('/ambient', { cards: [] })
  return data.cards ?? []
}

export async function fetchNotifications(
  includeAcknowledged = false,
): Promise<NotificationRecord[]> {
  const data = await getJson<{ notifications: NotificationRecord[] }>(
    `/notifications?include_acknowledged=${includeAcknowledged}`,
    { notifications: [] },
  )
  return data.notifications ?? []
}

export async function ackNotification(id: number): Promise<void> {
  await fetch(`${BASE}/notifications/${id}/ack`, { method: 'POST' })
}

export async function ackAllNotifications(): Promise<void> {
  await fetch(`${BASE}/notifications/ack-all`, { method: 'POST' })
}

export interface PanelResult<T> {
  data: T | null
  /** What went wrong, for a screen to show in place of its content. null when
   *  data is present. */
  error: string | null
}

/** Read one panel. Never throws: a screen always has something to render, and
 *  "Home Assistant is not enabled" is as much an answer as a device list. */
async function fetchPanel<T>(key: string): Promise<PanelResult<T>> {
  try {
    const res = await fetch(`${BASE}/panel/${key}`)
    if (res.ok) return { data: await res.json(), error: null }
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    return { data: null, error: body.detail ?? 'That did not work.' }
  } catch {
    return { data: null, error: 'Wony is not responding.' }
  }
}

export const fetchWeather = () => fetchPanel<WeatherPanel>('weather')
export const fetchAgenda = () => fetchPanel<AgendaPanel>('agenda')
export const fetchDevices = () => fetchPanel<DevicesPanel>('devices')
export const fetchGoogleAccounts = () => fetchPanel<GoogleAccountsSnapshot>('accounts')

/** null when Spotify is off or unreachable — the caller shows a resting state
 *  rather than an error, because "no music" is the normal case. */
export async function fetchNowPlaying(): Promise<NowPlaying | null> {
  const { data } = await fetchPanel<NowPlaying>('music')
  return data
}

export async function controlDevice(
  entity_id: string,
  action: string,
  brightness_percent?: number,
): Promise<{ ok: boolean; text: string }> {
  try {
    const res = await fetch(`${BASE}/devices/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entity_id, action, brightness_percent }),
    })
    if (res.ok) return res.json()
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    return { ok: false, text: body.detail ?? 'That did not work.' }
  } catch {
    return { ok: false, text: 'Wony is not responding.' }
  }
}

export async function fetchJobs(): Promise<Job[]> {
  const data = await getJson<{ jobs: Job[] }>('/jobs', { jobs: [] })
  return data.jobs ?? []
}

export async function invokeJob(
  name: string,
  args: Record<string, unknown>,
): Promise<InvokeResponse> {
  const res = await fetch(`${BASE}/invoke`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, args }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    return { ok: false, result: '', error: err.detail ?? 'Request failed' }
  }
  return res.json()
}

export async function fetchHistory(limit = 40): Promise<HistoryTurn[]> {
  const data = await getJson<{ turns: HistoryTurn[] }>(`/chat/history?limit=${limit}`, {
    turns: [],
  })
  return data.turns ?? []
}

export async function clearChat(): Promise<void> {
  await fetch(`${BASE}/chat/clear`, { method: 'POST' })
}

// ── WebSocket ───────────────────────────────────────────────────────────────

export interface ChatSocket {
  send: (message: string, sessionId: string) => void
  stop: () => void
  disconnect: () => void
}

/** One connection, reconnecting with backoff. The Pi outlives its router. */
export function connectSocket(handlers: {
  onEvent: (event: WsEvent) => void
  onConnect?: () => void
  onDisconnect?: () => void
}): ChatSocket {
  let ws: WebSocket | null = null
  let closed = false
  let retryTimeout: ReturnType<typeof setTimeout> | null = null
  let retryDelay = 1000

  const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`

  function connect() {
    if (closed) return
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      retryDelay = 1000
      handlers.onConnect?.()
    }

    ws.onmessage = (ev) => {
      try {
        handlers.onEvent(JSON.parse(ev.data) as WsEvent)
      } catch {
        // malformed frame — nothing useful to do with it
      }
    }

    ws.onclose = () => {
      ws = null
      handlers.onDisconnect?.()
      if (closed) return
      retryTimeout = setTimeout(() => {
        retryDelay = Math.min(retryDelay * 2, 20000)
        connect()
      }, retryDelay)
    }

    ws.onerror = () => ws?.close()
  }

  connect()

  return {
    send(message, sessionId) {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'chat', message, session_id: sessionId }))
      }
    },
    stop() {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'stop' }))
      }
    },
    disconnect() {
      closed = true
      if (retryTimeout) clearTimeout(retryTimeout)
      ws?.close()
    },
  }
}
