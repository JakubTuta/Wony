import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  ackAllNotifications,
  ackNotification,
  clearChat as clearChatRequest,
  connectSocket,
  fetchConfig,
  fetchHistory,
  fetchNotifications,
} from '../api'
import type {
  AppConfig,
  AssistantState,
  ChatSocket,
  HistoryTurn,
  NotificationRecord,
  WsEvent,
} from '../api'
import { WonyContext } from './wony-context'
import type { WonyContextValue } from './wony-context'

/** How many exchanges stay in the DOM. The rest live in the database and come
 *  back from /api/chat/history; keeping them all mounted is what makes a long
 *  session feel slow on a Pi. */
const MAX_TRANSCRIPT_TURNS = 40

export function WonyProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [connected, setConnected] = useState(false)
  const [assistantState, setAssistantState] = useState<AssistantState>('idle')
  const [turns, setTurns] = useState<HistoryTurn[]>([])
  const [streaming, setStreaming] = useState<string | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)
  const [notifications, setNotifications] = useState<NotificationRecord[]>([])
  const [arrival, setArrival] = useState<NotificationRecord | null>(null)

  const socket = useRef<ChatSocket | null>(null)
  // Which request the deltas currently arriving belong to. Turn frames are
  // broadcast to every client, so without this a second screen's reply would
  // land in this one's streaming buffer.
  const session = useRef<string>('')

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {})
  }, [])

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case 'state':
        setAssistantState(event.state)
        break

      case 'delta':
        if (event.session_id === session.current) {
          setStreaming((current) => (current ?? '') + event.data)
        }
        break

      case 'turn': {
        const turn = event as HistoryTurn & { session_id?: string }
        if (turn.session_id === session.current) {
          session.current = ''
          setStreaming(null)
        }
        setTurns((current) => {
          // A turn can arrive twice (own reply plus the broadcast); id is the
          // only thing that identifies it.
          if (turn.id !== null && current.some((t) => t.id === turn.id)) return current
          return [...current, turn].slice(-MAX_TRANSCRIPT_TURNS)
        })
        break
      }

      case 'error':
        if (event.session_id === session.current) {
          session.current = ''
          setStreaming(null)
        }
        setLastError(event.data)
        break

      case 'notification': {
        const record = event as NotificationRecord
        setNotifications((current) => [record, ...current])
        // Raised here rather than from an effect watching the list: this is the
        // moment it arrived, and only an arrival should interrupt anyone. The
        // backlog fetched on connect is not news.
        setArrival(record)
        break
      }

      default:
        // 'cancel' and diagnostics: nothing for the screen to do with them.
        break
    }
  }, [])

  useEffect(() => {
    const s = connectSocket({
      onEvent: handleEvent,
      onConnect: () => {
        setConnected(true)
        // Anything that fired while the socket was down is still in the
        // database, and so is anything another client said.
        fetchNotifications().then(setNotifications).catch(() => {})
        fetchHistory(MAX_TRANSCRIPT_TURNS).then(setTurns).catch(() => {})
      },
      onDisconnect: () => {
        setConnected(false)
        // A reply in flight when the socket dropped will never finish
        // streaming; the completed turn is refetched on reconnect.
        setStreaming(null)
        setAssistantState('idle')
      },
    })
    socket.current = s
    return () => {
      s.disconnect()
      socket.current = null
    }
  }, [handleEvent])

  const send = useCallback((message: string) => {
    const text = message.trim()
    if (!text || !socket.current) return
    session.current = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setLastError(null)
    setStreaming('')
    socket.current.send(text, session.current)
  }, [])

  const stop = useCallback(() => {
    socket.current?.stop()
  }, [])

  const clearTranscript = useCallback(async () => {
    await clearChatRequest()
    setTurns([])
    setStreaming(null)
  }, [])

  const ack = useCallback(async (id: number) => {
    setNotifications((current) => current.filter((n) => n.id !== id))
    await ackNotification(id)
  }, [])

  const ackAll = useCallback(async () => {
    setNotifications([])
    await ackAllNotifications()
  }, [])

  /** A job tile answers over HTTP, not the socket, so nothing broadcasts it.
   *  Recording it here keeps the transcript honest about what the screen
   *  actually showed. */
  const noteLocalAnswer = useCallback((question: string, answer: string) => {
    setTurns((current) =>
      [
        ...current,
        {
          id: null,
          user: question,
          assistant: answer,
          ts: new Date().toISOString(),
        },
      ].slice(-MAX_TRANSCRIPT_TURNS),
    )
  }, [])

  const dismissArrival = useCallback(() => setArrival(null), [])
  const dismissError = useCallback(() => setLastError(null), [])

  const value = useMemo<WonyContextValue>(
    () => ({
      config,
      connected,
      assistantState,
      turns,
      streaming,
      lastError,
      notifications,
      unreadCount: notifications.length,
      arrival,
      dismissArrival,
      send,
      stop,
      clearTranscript,
      dismissError,
      ack,
      ackAll,
      noteLocalAnswer,
    }),
    [
      config,
      connected,
      assistantState,
      turns,
      streaming,
      lastError,
      notifications,
      arrival,
      dismissArrival,
      send,
      stop,
      clearTranscript,
      dismissError,
      ack,
      ackAll,
      noteLocalAnswer,
    ],
  )

  return <WonyContext.Provider value={value}>{children}</WonyContext.Provider>
}
