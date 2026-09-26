import { useCallback, useEffect, useState } from 'react'
import type { PanelResult } from '../api'

/** Polls one panel fetcher on an interval, exposing a manual refresh for
 *  right after an action (Home Assistant confirms a service call before the
 *  state settles, so acting is always followed by a refetch rather than a
 *  guess). `intervalMs <= 0` fetches once and never repeats. */
export function usePanel<T>(
  fetcher: () => Promise<PanelResult<T>>,
  intervalMs: number,
): PanelResult<T> & { loaded: boolean; refresh: () => void } {
  const [result, setResult] = useState<PanelResult<T>>({ data: null, error: null })
  const [loaded, setLoaded] = useState(false)

  const refresh = useCallback(() => {
    fetcher().then((next) => {
      setResult(next)
      setLoaded(true)
    })
  }, [fetcher])

  useEffect(() => {
    refresh()
    if (intervalMs <= 0) return
    const timer = setInterval(refresh, intervalMs)
    return () => clearInterval(timer)
  }, [refresh, intervalMs])

  return { ...result, loaded, refresh }
}
