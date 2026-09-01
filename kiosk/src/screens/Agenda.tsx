import { useEffect, useState } from 'react'
import { CalendarDays, MapPin } from 'lucide-react'
import { fetchAgenda } from '../api'
import type { AgendaEvent, AgendaPanel } from '../api'
import { useWony } from '../state/wony-context'

// Someone accepts an invitation while the screen is showing it. Slow enough
// not to matter to Google's quota, fast enough not to be wrong all afternoon.
const REFRESH_MS = 5 * 60 * 1000

/** The ISO date an event falls on, in local terms.
 *
 *  An all-day event arrives as a bare "2026-09-01" with no zone, and putting
 *  that through Date() would read it as UTC and slide it a day in either
 *  direction depending on the offset. Its first ten characters are already
 *  the answer.
 */
function dayOf(event: AgendaEvent): string {
  if (event.all_day) return event.start.slice(0, 10)
  const at = new Date(event.start)
  const local = new Date(at.getTime() - at.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}

function heading(day: string, today: string, locale: string): string {
  const days = Math.round(
    (Date.parse(`${day}T00:00:00`) - Date.parse(`${today}T00:00:00`)) / 86400000,
  )
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return new Date(`${day}T00:00:00`).toLocaleDateString(locale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

function clock(value: string, locale: string): string {
  const at = new Date(value)
  return Number.isNaN(at.getTime())
    ? ''
    : at.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
}

/** Today's calendar as a list.
 *
 *  This used to ask the agent "what's on my calendar today?" and print the
 *  paragraph it wrote back. The events were always a list; only the rendering
 *  went through a language model.
 */
export function Agenda() {
  const { config } = useWony()
  const [panel, setPanel] = useState<AgendaPanel | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const locale = config?.assistant.language || 'en'

  useEffect(() => {
    const load = () => {
      fetchAgenda().then((result) => {
        setPanel(result.data)
        setError(result.error)
        setLoading(false)
      })
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="t-body text-muted">Reading your calendar…</p>
      </div>
    )
  }

  if (error || !panel) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-2 px-8">
        <CalendarDays size={40} className="text-muted" />
        <p className="t-body text-muted">{error ?? 'No calendar right now.'}</p>
      </div>
    )
  }

  const multipleAccounts = new Set(panel.events.map((e) => e.account)).size > 1

  return (
    <div className="scroll-y flex-1 px-3 py-3 flex flex-col gap-5">
      {panel.days.map((day) => {
        const events = panel.events.filter((event) => dayOf(event) === day)
        return (
          <div key={day}>
            <div className="t-small text-muted uppercase tracking-wide px-2 pb-2">
              {heading(day, panel.today, locale)}
            </div>
            {events.length === 0 ? (
              <p className="t-body text-muted px-2">Nothing on.</p>
            ) : (
              <div className="flex flex-col gap-1.5">
                {events.map((event) => (
                  <Row
                    key={`${event.account}:${event.id}`}
                    event={event}
                    locale={locale}
                    showAccount={multipleAccounts}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function Row({
  event,
  locale,
  showAccount,
}: {
  event: AgendaEvent
  locale: string
  showAccount: boolean
}) {
  return (
    <div className="list-row flex items-start gap-3 px-4 py-3 rounded-xl bg-surface border border-line">
      <div className="w-16 shrink-0 pt-0.5">
        {event.all_day ? (
          <span className="t-small text-muted">All day</span>
        ) : (
          <>
            <div className="t-body tabular-nums leading-tight">
              {clock(event.start, locale)}
            </div>
            {event.end && (
              <div className="t-small text-muted tabular-nums leading-tight">
                {clock(event.end, locale)}
              </div>
            )}
          </>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="t-body">{event.title}</div>
        {event.location && (
          <div className="t-small text-muted flex items-center gap-1 min-w-0">
            <MapPin size={12} className="shrink-0" />
            <span className="truncate">{event.location}</span>
          </div>
        )}
      </div>

      {showAccount && event.account && (
        <span className="t-small text-muted shrink-0 px-2 h-6 leading-6 rounded-full border border-line">
          {event.account}
        </span>
      )}
    </div>
  )
}
