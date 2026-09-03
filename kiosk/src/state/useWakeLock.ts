import { useEffect } from 'react'

/** Hold the screen on.
 *
 *  The whole point of the idle screen is that the panel shows a clock rather
 *  than going black, so the OS blanker has to be kept out of it. Doing that in
 *  the page rather than the system means no branching between X, wayfire and
 *  labwc — and it works because http://localhost counts as a secure context.
 *
 *  The lock is dropped whenever the page is hidden, so it has to be retaken on
 *  visibilitychange. Unsupported browsers degrade to nothing; the fallback is
 *  the documented `xset s off -dpms`.
 *
 *  `enabled` is false during deep sleep, when the panel is off on purpose.
 */
export function useWakeLock(enabled: boolean = true): void {
  useEffect(() => {
    if (!enabled) return
    if (!('wakeLock' in navigator)) return

    let sentinel: WakeLockSentinel | null = null
    let released = false

    const acquire = async () => {
      if (released || document.visibilityState !== 'visible') return
      try {
        sentinel = await navigator.wakeLock.request('screen')
      } catch {
        // Denied (no user gesture yet, battery saver). Retried on the next
        // visibility change or interaction.
      }
    }

    const onVisibility = () => {
      if (document.visibilityState === 'visible') void acquire()
    }

    void acquire()
    document.addEventListener('visibilitychange', onVisibility)
    // The first request can be refused before any interaction has happened.
    window.addEventListener('pointerdown', acquire, { once: true })

    return () => {
      released = true
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pointerdown', acquire)
      void sentinel?.release().catch(() => {})
    }
  }, [enabled])
}
