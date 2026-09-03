import { createContext, useContext } from 'react'
import type {
  AppConfig,
  AssistantState,
  HistoryTurn,
  NotificationRecord,
  SleepState,
} from '../api'

export interface WonyContextValue {
  config: AppConfig | null
  connected: boolean
  assistantState: AssistantState
  turns: HistoryTurn[]
  streaming: string | null
  lastError: string | null
  notifications: NotificationRecord[]
  unreadCount: number
  /** The most recent arrival, for the toast. Null once dismissed. */
  arrival: NotificationRecord | null
  dismissArrival: () => void
  send: (message: string) => void
  stop: () => void
  clearTranscript: () => Promise<void>
  dismissError: () => void
  ack: (id: number) => Promise<void>
  ackAll: () => Promise<void>
  noteLocalAnswer: (question: string, answer: string) => void
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
