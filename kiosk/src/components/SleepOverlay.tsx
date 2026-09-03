import { useEffect, useState } from 'react'
import type { SleepState } from '../api'

/** The black page that catches the tap that wakes the device.
 *
 *  With the panel powered down there is nothing to see here, and that is the
 *  point: the touchscreen is a separate input device and keeps reporting
 *  touches whether the backlight is on or not, so the page has to still be
 *  there to receive one. This covers everything so the touch cannot land on a
 *  tile the sleeper cannot see.
 *
 *  It is also the whole feature on a machine where no display backend worked —
 *  a desktop, or an SSH session with no compositor to talk to. Black page, same
 *  wake gesture, just a screen that stayed lit.
 */
export function SleepOverlay({
  state,
  onWake,
}: {
  state: SleepState
  onWake: () => void
}) {
  // A moment of visible text before it goes black, so a mistaken tap on the
  // Sleep tile has an obvious way out and does not look like a crash.
  const [hint, setHint] = useState(true)

  useEffect(() => {
    const timer = setTimeout(() => setHint(false), 4000)
    return () => clearTimeout(timer)
  }, [])

  const wakeClock = state.wake_at
    ? new Date(state.wake_at).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      })
    : null

  return (
    <button
      onClick={onWake}
      aria-label="Wake up"
      className="fixed inset-0 z-50 bg-black text-white flex flex-col items-center
                 justify-center gap-3 cursor-default"
    >
      <span
        className={`t-display transition-opacity duration-1000 ${
          hint ? 'opacity-60' : 'opacity-0'
        }`}
      >
        Sleeping
      </span>
      <span
        className={`t-small transition-opacity duration-1000 ${
          hint ? 'opacity-40' : 'opacity-0'
        }`}
      >
        {wakeClock ? `Waking at ${wakeClock} — or touch anywhere` : 'Touch anywhere'}
      </span>
    </button>
  )
}
