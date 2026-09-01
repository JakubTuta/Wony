import { useEffect, useState } from 'react'

/** The current time, re-rendering once a minute.
 *
 *  Aligned to the minute boundary rather than a 1 Hz interval: nothing on this
 *  screen shows seconds, and a repaint every second on a Pi is a repaint every
 *  second for nothing.
 */
export function useClock(): Date {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      const next = 60_000 - (Date.now() % 60_000)
      timer = setTimeout(() => {
        setNow(new Date())
        schedule()
      }, next + 50)
    }
    schedule()
    return () => clearTimeout(timer)
  }, [])

  return now
}
