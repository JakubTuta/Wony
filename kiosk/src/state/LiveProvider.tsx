import { useMemo } from 'react'
import type { ReactNode } from 'react'
import {
  fetchAgenda,
  fetchDevices,
  fetchLibrary,
  fetchMusic,
  fetchReminders,
  fetchRoutines,
  fetchWeather,
} from '../api'
import { LiveContext } from './live-context'
import type { LiveContextValue } from './live-context'
import { usePanel } from './usePanel'

const MINUTE = 60_000

/** One poll per live panel, shared by the header, Home, Rooms, Music and
 *  Macros — each screen used to run its own interval for the same data, so a
 *  reload of Home while Rooms was open used to mean two Home Assistant polls
 *  running side by side for no reason. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const weather = usePanel(fetchWeather, 10 * MINUTE)
  const agenda = usePanel(fetchAgenda, 5 * MINUTE)
  const reminders = usePanel(fetchReminders, 30_000)
  const devices = usePanel(fetchDevices, 30_000)
  const music = usePanel(fetchMusic, 5_000)
  const library = usePanel(fetchLibrary, 5 * MINUTE)
  const routines = usePanel(fetchRoutines, 5 * MINUTE)

  const value = useMemo<LiveContextValue>(
    () => ({ weather, agenda, reminders, devices, music, library, routines }),
    [weather, agenda, reminders, devices, music, library, routines],
  )

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
}
