import { useEffect, useState } from 'react'
import { Moon, Minus, Plus } from 'lucide-react'
import { fetchSleep, startSleep } from '../api'

/** Wake times worth one tap. Anything else is the +/- pair below them. */
const PRESETS = ['06:00', '07:00', '08:00'] as const

/** Move a HH:MM by some minutes, wrapping at midnight in both directions. */
function shift(time: string, minutes: number): string {
  const [h, m] = time.split(':').map(Number)
  if (Number.isNaN(h) || Number.isNaN(m)) return time
  const total = (((h * 60 + m + minutes) % 1440) + 1440) % 1440
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`
}

/** Choosing how the night goes.
 *
 *  Deliberately a screen and not a one-tap tile. Sending the panel dark is the
 *  only thing on the home screen that makes the device look broken if it was
 *  not meant, so it asks first — and the wake time is the question worth
 *  asking, because "until someone touches it" is not always what you want at
 *  23:00 on a work night.
 */
export function Sleep({ onSleeping }: { onSleeping: () => void }) {
  const [wakeAt, setWakeAt] = useState<string>('')
  const [scheduled, setScheduled] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Last night's answer, so the usual case is one tap. null means the question
  // has never been asked here, and picking a wake time for someone who has not
  // chosen one is worse than showing them the choice.
  useEffect(() => {
    fetchSleep()
      .then((state) => {
        if (!state.last_wake) return
        setWakeAt(state.last_wake)
        setScheduled(true)
      })
      .catch(() => {})
  }, [])

  const go = async () => {
    setBusy(true)
    setError(null)
    const { error: failed } = await startSleep(scheduled ? wakeAt : '')
    setBusy(false)
    if (failed) {
      setError(failed)
      return
    }
    // The overlay is driven by the socket's sleep event, which has already
    // been broadcast; this only takes the picker off the screen behind it.
    onSleeping()
  }

  return (
    <div className="scroll-y flex-1 px-3 py-3 flex flex-col gap-4">
      <div className="flex flex-col items-center gap-2 pt-4 pb-2 text-center px-6">
        <Moon size={40} className="text-muted" />
        <p className="t-body text-muted">
          The screen goes dark and I stop checking things. Nothing shuts down —
          your timers still go off, and I am back the moment you touch the
          glass.
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <button
          onClick={() => setScheduled(false)}
          className={`press flex items-center justify-between px-4 py-4 rounded-xl
                      bg-surface border ${scheduled ? 'border-line' : 'border-accent'}`}
        >
          <span className="t-body">Until I touch the screen</span>
          {!scheduled && <span className="w-2.5 h-2.5 rounded-full bg-accent" />}
        </button>

        <button
          onClick={() => {
            setScheduled(true)
            if (!wakeAt) setWakeAt('07:00')
          }}
          className={`press flex items-center justify-between px-4 py-4 rounded-xl
                      bg-surface border ${scheduled ? 'border-accent' : 'border-line'}`}
        >
          <span className="t-body">Wake me at a time</span>
          {scheduled && <span className="w-2.5 h-2.5 rounded-full bg-accent" />}
        </button>
      </div>

      {scheduled && (
        <div className="flex flex-col gap-3 px-2">
          <div className="flex items-center justify-center gap-5">
            <button
              onClick={() => setWakeAt((t) => shift(t || '07:00', -15))}
              aria-label="Fifteen minutes earlier"
              className="press w-14 h-14 rounded-full bg-surface border border-line
                         flex items-center justify-center"
            >
              <Minus size={22} />
            </button>
            <span className="t-display tabular-nums w-32 text-center">
              {wakeAt || '07:00'}
            </span>
            <button
              onClick={() => setWakeAt((t) => shift(t || '07:00', 15))}
              aria-label="Fifteen minutes later"
              className="press w-14 h-14 rounded-full bg-surface border border-line
                         flex items-center justify-center"
            >
              <Plus size={22} />
            </button>
          </div>

          <div className="flex justify-center gap-2">
            {PRESETS.map((time) => (
              <button
                key={time}
                onClick={() => setWakeAt(time)}
                className={`press px-4 h-10 rounded-full bg-surface border tabular-nums t-small
                            ${wakeAt === time ? 'border-accent' : 'border-line'}`}
              >
                {time}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && <p className="t-small text-center px-4">{error}</p>}

      <button
        onClick={go}
        disabled={busy}
        className="press mt-auto w-full h-14 rounded-full bg-surface border border-line
                   flex items-center justify-center gap-2 disabled:opacity-60"
        style={{ boxShadow: 'var(--wony-shadow)' }}
      >
        <Moon size={20} />
        <span className="t-body">{busy ? 'Going dark…' : 'Sleep now'}</span>
      </button>
    </div>
  )
}
