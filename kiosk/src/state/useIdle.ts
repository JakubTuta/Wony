import { useEffect, useRef, useState } from 'react'

/** True once nobody has touched the screen for `minutes`.
 *
 *  Listens on the capture phase so a tap counts even when a child stops
 *  propagation, and re-arms on every interaction. Passing 0 disables it, which
 *  is what a config of 0 should mean rather than "go idle immediately".
 */
export function useIdle(minutes: number): { idle: boolean; wake: () => void } {
  const [timedOut, setTimedOut] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (minutes <= 0) return

    const ms = minutes * 60_000

    const arm = () => {
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setTimedOut(true), ms)
    }

    const onActivity = () => {
      setTimedOut(false)
      arm()
    }

    const events: (keyof WindowEventMap)[] = [
      'pointerdown',
      'touchstart',
      'keydown',
      'wheel',
    ]
    for (const name of events) {
      window.addEventListener(name, onActivity, { capture: true, passive: true })
    }
    arm()

    return () => {
      for (const name of events) {
        window.removeEventListener(name, onActivity, { capture: true })
      }
      if (timer.current) clearTimeout(timer.current)
    }
  }, [minutes])

  // Derived rather than reset: with minutes <= 0 the feature is simply off, and
  // clearing the flag from an effect would be a render cascade for nothing.
  return { idle: minutes > 0 && timedOut, wake: () => setTimedOut(false) }
}
