import { useEffect, useState } from 'react'
import { Minus, Moon, Plus } from 'lucide-react'
import { fetchSleep, startSleep } from '../api'

const PRESETS = ['06:00', '07:00', '08:00'] as const

/** Move a HH:MM by some minutes, wrapping at midnight in both directions. */
function shift(time: string, minutes: number): string {
  const [h, m] = time.split(':').map(Number)
  if (Number.isNaN(h) || Number.isNaN(m)) return time
  const total = (((h * 60 + m + minutes) % 1440) + 1440) % 1440
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`
}

/** Choosing how the night goes — a sheet, not a one-tap tile, because sending
 *  the panel dark is the one thing on it that looks broken if it was not
 *  meant, and the wake time is worth asking: "until someone touches it" is
 *  not always the right answer at 23:00 on a work night. */
export function SleepSheet({ onSleeping, onClose }: { onSleeping: () => void; onClose: () => void }) {
  const [wakeAt, setWakeAt] = useState('')
  const [scheduled, setScheduled] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
    onSleeping()
  }

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center"
      style={{ background: 'var(--wony-scrim)' }}
      onPointerDown={onClose}
    >
      <div
        className="w-[600px] rounded-[32px] bg-surface p-9 flex flex-col gap-5"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <div className="flex flex-col items-center gap-2 text-center">
          <Moon size={36} className="text-muted" />
          <span className="text-[26px] font-bold">Sleep</span>
          <p className="text-[17px] text-muted">
            The screen goes dark and nothing shuts down — your timers still go
            off, and it comes back the moment you touch the glass.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <button
            onClick={() => setScheduled(false)}
            className={`press flex items-center justify-between px-5 h-16 rounded-[20px] bg-surface-2 border-2 ${
              scheduled ? 'border-transparent' : 'border-accent'
            }`}
          >
            <span className="text-[19px] font-medium">Until I touch the screen</span>
            {!scheduled && <span className="w-3 h-3 rounded-full bg-accent" />}
          </button>

          <button
            onClick={() => {
              setScheduled(true)
              if (!wakeAt) setWakeAt('07:00')
            }}
            className={`press flex items-center justify-between px-5 h-16 rounded-[20px] bg-surface-2 border-2 ${
              scheduled ? 'border-accent' : 'border-transparent'
            }`}
          >
            <span className="text-[19px] font-medium">Wake me at a time</span>
            {scheduled && <span className="w-3 h-3 rounded-full bg-accent" />}
          </button>
        </div>

        {scheduled && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-center gap-5">
              <button
                onClick={() => setWakeAt((t) => shift(t || '07:00', -15))}
                aria-label="Fifteen minutes earlier"
                className="press w-16 h-16 rounded-full bg-surface-2 flex items-center justify-center"
              >
                <Minus size={22} />
              </button>
              <span className="text-[34px] font-bold tabular-nums w-32 text-center">
                {wakeAt || '07:00'}
              </span>
              <button
                onClick={() => setWakeAt((t) => shift(t || '07:00', 15))}
                aria-label="Fifteen minutes later"
                className="press w-16 h-16 rounded-full bg-surface-2 flex items-center justify-center"
              >
                <Plus size={22} />
              </button>
            </div>
            <div className="flex justify-center gap-2">
              {PRESETS.map((time) => (
                <button
                  key={time}
                  onClick={() => setWakeAt(time)}
                  className={`press px-4 h-12 rounded-full bg-surface-2 border-2 tabular-nums text-[16px] font-semibold ${
                    wakeAt === time ? 'border-accent' : 'border-transparent'
                  }`}
                >
                  {time}
                </button>
              ))}
            </div>
          </div>
        )}

        {error && <p className="text-[16px] text-danger text-center">{error}</p>}

        <button
          onClick={go}
          disabled={busy}
          className="press h-16 rounded-[24px] bg-accent text-on-accent text-[20px] font-bold flex items-center justify-center gap-2 disabled:opacity-60"
        >
          <Moon size={18} />
          {busy ? 'Going dark…' : 'Sleep now'}
        </button>
      </div>
    </div>
  )
}
