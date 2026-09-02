import { useCallback, useEffect, useState } from 'react'
import { AlarmClock, Repeat, X } from 'lucide-react'
import { fetchReminders, invokeJob } from '../api'
import type { Reminder } from '../api'

// The list itself only changes when a timer is set or fires; the countdowns on
// it change every second, and that is a re-render, not a fetch.
const REFRESH_MS = 30 * 1000

function countdown(next: string | null): string {
  if (!next) return 'not scheduled'
  const seconds = Math.round((new Date(next).getTime() - Date.now()) / 1000)
  if (seconds <= 0) return 'any moment'
  if (seconds < 60) return `in ${seconds}s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `in ${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours < 24) return rest ? `in ${hours}h ${rest}m` : `in ${hours}h`
  return `in ${Math.round(hours / 24)} days`
}

/** Everything counting down, with a button to call one off.
 *
 *  list_reminders says the same thing in a sentence; a sentence has nowhere to
 *  put a cancel button, and its countdown is stale the moment it is written.
 */
export function Reminders() {
  const [reminders, setReminders] = useState<Reminder[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  // Re-renders the countdowns without refetching the list.
  const [, setTick] = useState(0)

  const load = useCallback(() => {
    fetchReminders().then((result) => {
      setReminders(result.data?.reminders ?? [])
      setError(result.error)
    })
  }, [])

  useEffect(() => {
    load()
    const refresh = setInterval(load, REFRESH_MS)
    const tick = setInterval(() => setTick((n) => n + 1), 1000)
    return () => {
      clearInterval(refresh)
      clearInterval(tick)
    }
  }, [load])

  const cancel = async (id: string) => {
    setBusy(id)
    await invokeJob('cancel_reminder', { id_or_text: id })
    setBusy(null)
    load()
  }

  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-2 px-8">
        <AlarmClock size={40} className="text-muted" />
        <p className="t-body text-muted">{error}</p>
      </div>
    )
  }

  if (reminders === null) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="t-body text-muted">Checking…</p>
      </div>
    )
  }

  if (reminders.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-2 px-8">
        <AlarmClock size={40} className="text-muted" />
        <p className="t-body text-muted">Nothing is counting down.</p>
        <p className="t-small text-muted">Ask for "set a timer for 10 minutes".</p>
      </div>
    )
  }

  return (
    <div className="scroll-y flex-1 px-4 py-4 flex flex-col gap-2">
      {reminders.map((reminder) => (
        <div
          key={reminder.id}
          className="flex items-center gap-3 px-4 py-3 rounded-xl bg-surface border border-line"
        >
          <span className="text-accent shrink-0">
            {reminder.repeating ? <Repeat size={20} /> : <AlarmClock size={20} />}
          </span>
          <div className="min-w-0 flex-1">
            <div className="t-body truncate">
              {reminder.text || `run ${reminder.action_job}` || 'Timer'}
            </div>
            <div className="t-small text-muted truncate">
              {countdown(reminder.next_run)}
              {reminder.when_str ? ` · ${reminder.when_str}` : ''}
            </div>
          </div>
          <button
            onClick={() => cancel(reminder.id)}
            disabled={busy === reminder.id}
            aria-label={`Cancel ${reminder.text || 'timer'}`}
            className="shrink-0 w-11 h-11 rounded-full grid place-items-center
                       text-muted hover:text-text active:scale-95 disabled:opacity-40"
          >
            <X size={20} />
          </button>
        </div>
      ))}
    </div>
  )
}
