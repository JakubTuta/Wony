import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  ackAllNotifications,
  ackNotification,
  connectSocket,
  endSleep,
  fetchConfig,
  fetchNotifications,
  fetchSleep,
} from '../api'
import type {
  AppConfig,
  ChatSocket,
  HistoryTurn,
  NotificationRecord,
  SleepState,
  WsEvent,
} from '../api'
import { WonyContext } from './wony-context'
import type { PromptResult, WonyContextValue } from './wony-context'

const AWAKE: SleepState = {
  asleep: false,
  since: null,
  wake_at: null,
  display: '',
  paused_jobs: [],
  last_wake: null,
}

export function WonyProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [connected, setConnected] = useState(false)
  const [notifications, setNotifications] = useState<NotificationRecord[]>([])
  const [sleep, setSleep] = useState<SleepState>(AWAKE)

  const socket = useRef<ChatSocket | null>(null)
  // Every runPrompt() in flight, keyed by its own session id — a tile tap and
  // a routine run from Macros can be waiting at the same time, and turn/error
  // frames are broadcast to every client, so only the id says which is whose.
  const pending = useRef<Map<string, (result: PromptResult) => void>>(new Map())

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {})
  }, [])

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case 'turn': {
        const turn = event as HistoryTurn & { session_id?: string }
        const sid = turn.session_id
        const resolve = sid ? pending.current.get(sid) : undefined
        if (resolve && sid) {
          pending.current.delete(sid)
          resolve({ ok: true, text: turn.assistant })
        }
        break
      }

      case 'error': {
        const resolve = pending.current.get(event.session_id)
        if (resolve) {
          pending.current.delete(event.session_id)
          resolve({ ok: false, text: event.data })
        }
        break
      }

      case 'sleep':
        setSleep(event)
        break

      case 'notification':
        setNotifications((current) => [event as NotificationRecord, ...current])
        break

      default:
        // 'delta', 'state', 'cancel' and diagnostics: nothing here needs them —
        // the panel shows no live transcript and no thinking indicator.
        break
    }
  }, [])

  useEffect(() => {
    const s = connectSocket({
      onEvent: handleEvent,
      onConnect: () => {
        setConnected(true)
        fetchNotifications().then(setNotifications).catch(() => {})
        // A screen that reloaded — or was opened second — has to find out it
        // is meant to be dark. The sleep event only reaches clients that were
        // connected when it fired.
        fetchSleep().then(setSleep).catch(() => {})
      },
      onDisconnect: () => setConnected(false),
    })
    socket.current = s
    return () => {
      s.disconnect()
      socket.current = null
    }
  }, [handleEvent])

  const runPrompt = useCallback((message: string): Promise<PromptResult> => {
    const text = message.trim()
    if (!text || !socket.current) {
      return Promise.resolve({ ok: false, text: 'Not connected.' })
    }
    return new Promise((resolve) => {
      const sid = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      pending.current.set(sid, resolve)
      socket.current!.send(text, sid)
    })
  }, [])

  const ack = useCallback(async (id: number) => {
    setNotifications((current) => current.filter((n) => n.id !== id))
    await ackNotification(id)
  }, [])

  const ackAll = useCallback(async () => {
    setNotifications([])
    await ackAllNotifications()
  }, [])

  /** Optimistic: the overlay comes off on the touch, not on the round trip,
   *  because the panel is already lighting up by then and a screen that stays
   *  black for another 200ms reads as a device that did not hear you. */
  const wakeUp = useCallback(() => {
    setSleep(AWAKE)
    endSleep().then(setSleep).catch(() => {})
  }, [])

  const value = useMemo<WonyContextValue>(
    () => ({
      config,
      connected,
      notifications,
      unreadCount: notifications.length,
      ack,
      ackAll,
      runPrompt,
      sleep,
      wakeUp,
    }),
    [config, connected, notifications, ack, ackAll, runPrompt, sleep, wakeUp],
  )

  return <WonyContext.Provider value={value}>{children}</WonyContext.Provider>
}
