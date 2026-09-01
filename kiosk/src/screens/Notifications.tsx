import { AlertTriangle, Bell, Check, CheckCheck, Info } from 'lucide-react'
import { useWony } from '../state/wony-context'

const ICONS = {
  info: Info,
  reminder: Bell,
  alert: AlertTriangle,
  error: AlertTriangle,
}

const TONES = {
  info: 'text-muted',
  reminder: 'text-accent',
  alert: 'text-warn',
  error: 'text-danger',
}

function when(ts: string | undefined, locale: string): string {
  if (!ts) return ''
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return ''

  const sameDay = date.toDateString() === new Date().toDateString()
  return sameDay
    ? date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleString(locale, {
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
}

export function Notifications() {
  const { notifications, ack, ackAll, config } = useWony()
  const locale = config?.assistant.language || 'en'

  if (notifications.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 px-8 text-center">
        <Bell size={32} className="text-muted opacity-40" />
        <p className="t-body text-muted">Nothing waiting.</p>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="scroll-y flex-1 px-3 py-3 flex flex-col gap-2">
        {notifications.map((n, i) => {
          const Icon = ICONS[n.kind] ?? Info
          const tone = TONES[n.kind] ?? 'text-muted'
          return (
            <div
              key={n.id ?? `local-${i}`}
              className="list-row flex items-start gap-3 px-4 py-3.5 rounded-2xl bg-surface border border-line"
            >
              <Icon size={20} className={`${tone} mt-0.5 shrink-0`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 t-small text-muted">
                  {n.source && <span className="uppercase tracking-wide">{n.source}</span>}
                  <span>{when(n.ts, locale)}</span>
                </div>
                <p className="t-body selectable whitespace-pre-wrap">{n.text}</p>
              </div>
              {n.id !== null && (
                <button
                  onClick={() => ack(n.id as number)}
                  aria-label="Acknowledge"
                  className="press flex items-center justify-center w-11 h-11 -mr-2 rounded-full text-muted shrink-0"
                >
                  <Check size={20} />
                </button>
              )}
            </div>
          )
        })}
      </div>

      <div className="shrink-0 px-3 pb-3">
        <button
          onClick={ackAll}
          className="press w-full flex items-center justify-center gap-2 h-13 py-3.5
                     rounded-full bg-surface border border-line t-body text-muted"
        >
          <CheckCheck size={20} />
          Clear all
        </button>
      </div>
    </div>
  )
}
