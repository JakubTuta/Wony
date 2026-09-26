import { createContext, useContext } from 'react'
import type {
  AgendaPanel,
  DevicesPanel,
  LibraryPanel,
  NowPlaying,
  PanelResult,
  RemindersPanel,
  RoutinesPanel,
  WeatherPanel,
} from '../api'

export interface LivePanel<T> extends PanelResult<T> {
  loaded: boolean
  refresh: () => void
}

export interface LiveContextValue {
  weather: LivePanel<WeatherPanel>
  agenda: LivePanel<AgendaPanel>
  reminders: LivePanel<RemindersPanel>
  devices: LivePanel<DevicesPanel>
  music: LivePanel<NowPlaying>
  library: LivePanel<LibraryPanel>
  routines: LivePanel<RoutinesPanel>
}

export const LiveContext = createContext<LiveContextValue | null>(null)

export function useLive(): LiveContextValue {
  const value = useContext(LiveContext)
  if (!value) throw new Error('useLive must be used inside <LiveProvider>')
  return value
}
