import { createContext, useContext } from 'react'
import type { AppConfig, NotificationRecord, SleepState } from '../api'

export interface PromptResult {
  ok: boolean
  text: string
}

export interface WonyContextValue {
  config: AppConfig | null
  connected: boolean
  notifications: NotificationRecord[]
  unreadCount: number
  ack: (id: number) => Promise<void>
  ackAll: () => Promise<void>
  /** Sends a sentence through the agent — the only way a routine or a typed
   *  sentence runs on a panel with no keyboard of its own — and resolves once
   *  the reply (or a turn error) comes back on this session's own socket
   *  round trip. */
  runPrompt: (message: string) => Promise<PromptResult>
  /** Deep sleep, kept here because every client is asleep together — the
   *  server broadcasts it, and a second screen must not stay lit. */
  sleep: SleepState
  wakeUp: () => void
}

export const WonyContext = createContext<WonyContextValue | null>(null)

export function useWony(): WonyContextValue {
  const value = useContext(WonyContext)
  if (!value) throw new Error('useWony must be used inside <WonyProvider>')
  return value
}
