/** mm:ss, for a track's progress or a timer's countdown while it is under an
 *  hour. */
export function clockFromMs(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** Seconds remaining until an ISO datetime, floored at 0. */
export function secondsUntil(iso: string): number {
  return Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 1000))
}

/** The "Coming up" list shows an urgent countdown for what's about to happen
 *  and a plain clock time for what's further out — a reminder due in nine
 *  hours does not need to be read down to the second. */
export function upcomingTime(iso: string): string {
  const seconds = secondsUntil(iso)
  if (seconds < 3600) return clockFromMs(seconds * 1000)
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
