import { useCallback, useEffect, useState } from 'react'
import { fetchHealth } from './api'
import { SleepOverlay } from './components/SleepOverlay'
import { StatusBar } from './components/StatusBar'
import { Toast } from './components/Toast'
import { Accounts } from './screens/Accounts'
import { Agenda } from './screens/Agenda'
import { Ambient } from './screens/Ambient'
import { Chat } from './screens/Chat'
import { Commands } from './screens/Commands'
import { Devices } from './screens/Devices'
import { Home } from './screens/Home'
import { Music } from './screens/Music'
import { Notifications } from './screens/Notifications'
import { Reminders } from './screens/Reminders'
import { Settings } from './screens/Settings'
import { Sleep } from './screens/Sleep'
import { Weather } from './screens/Weather'
import { useIdle } from './state/useIdle'
import { useTheme } from './state/useTheme'
import { useTypeAnywhere } from './state/useTypeAnywhere'
import { useWakeLock } from './state/useWakeLock'
import { WonyProvider } from './state/WonyProvider'
import { useWony } from './state/wony-context'

type Screen =
  | 'home'
  | 'chat'
  | 'notifications'
  | 'commands'
  | 'music'
  | 'accounts'
  | 'weather'
  | 'agenda'
  | 'devices'
  | 'reminders'
  | 'settings'
  | 'sleep'

const TITLES: Record<Screen, string> = {
  home: '',
  chat: 'Chat',
  notifications: 'Waiting',
  commands: 'Commands',
  music: 'Music',
  accounts: 'Google accounts',
  weather: 'Weather',
  agenda: 'Today',
  devices: 'Devices',
  reminders: 'Timers',
  settings: 'Settings',
  sleep: 'Sleep',
}

/** Screens a tile is allowed to open. A tile naming anything else is ignored
 *  rather than trusted — the manifest comes from config.yaml, which the UI
 *  does not get to assume is in step with it. */
const TILE_SCREENS = new Set<Screen>([
  'accounts',
  'agenda',
  'commands',
  'devices',
  'music',
  'notifications',
  'reminders',
  'settings',
  'sleep',
  'weather',
])

function asScreen(name: string | null): Screen | null {
  return name && TILE_SCREENS.has(name as Screen) ? (name as Screen) : null
}

export default function App() {
  return (
    <WonyProvider>
      <Shell />
    </WonyProvider>
  )
}

function Shell() {
  const { config, assistantState, send, arrival, dismissArrival, sleep, wakeUp } =
    useWony()
  const { theme, toggle } = useTheme()
  // Dropped while asleep: the lock exists to stop the compositor blanking a
  // screen we want lit, and holding it through a deliberate blackout would be
  // arguing with ourselves.
  useWakeLock(!sleep.asleep)

  const [screen, setScreen] = useState<Screen>('home')
  const [draft, setDraft] = useState('')
  const [keyboardOpen, setKeyboardOpen] = useState(false)
  const [hasSpotify, setHasSpotify] = useState(false)

  const idleMinutes = config?.kiosk.idle_minutes ?? 15
  const { idle, wake } = useIdle(idleMinutes)

  useEffect(() => {
    fetchHealth()
      .then((health) => setHasSpotify(health.modules?.spotify?.status === 'enabled'))
      .catch(() => {})
  }, [])

  // A keyboard plugged into the Pi should work from anywhere, not only once
  // you have found the chat screen. The first character is kept, and Chat
  // autofocuses its field, so the rest lands there normally.
  const typeAnywhere = useCallback((char: string) => {
    setScreen('chat')
    setDraft((current) => current + char)
  }, [])
  useTypeAnywhere(typeAnywhere)

  const go = (next: Screen) => {
    setScreen(next)
    if (next !== 'chat') setKeyboardOpen(false)
  }

  const askFromTile = (prompt: string) => {
    setScreen('chat')
    setKeyboardOpen(false)
    send(prompt)
  }

  const title = screen === 'home' ? (config?.assistant.name ?? 'Wony') : TITLES[screen]

  return (
    <div className="relative h-full flex flex-col bg-bg text-text overflow-hidden">
      <StatusBar
        title={title}
        onBack={screen === 'home' ? undefined : () => go('home')}
        onNotifications={() => go('notifications')}
        onCommands={() => go('commands')}
        onMusic={hasSpotify ? () => go('music') : undefined}
        onSettings={() => go('settings')}
        theme={theme}
        onToggleTheme={toggle}
      />

      {screen === 'home' && (
        <Home
          onAsk={() => {
            setScreen('chat')
            setKeyboardOpen(true)
          }}
          onPrompt={askFromTile}
          onScreen={(name) => {
            const next = asScreen(name)
            if (next) go(next)
          }}
        />
      )}
      {screen === 'chat' && (
        <Chat
          draft={draft}
          setDraft={setDraft}
          keyboardOpen={keyboardOpen}
          setKeyboardOpen={setKeyboardOpen}
        />
      )}
      {screen === 'notifications' && <Notifications />}
      {screen === 'commands' && <Commands />}
      {screen === 'music' && <Music />}
      {screen === 'accounts' && <Accounts />}
      {screen === 'weather' && <Weather />}
      {screen === 'agenda' && <Agenda />}
      {screen === 'devices' && <Devices />}
      {screen === 'reminders' && <Reminders />}
      {screen === 'settings' && <Settings />}
      {screen === 'sleep' && <Sleep onSleeping={() => go('home')} />}

      {/* Nothing to interrupt with if the list is already what you are reading. */}
      {arrival && screen !== 'notifications' && (
        <Toast
          notification={arrival}
          onOpen={() => {
            dismissArrival()
            go('notifications')
          }}
          onDismiss={dismissArrival}
        />
      )}

      {/* Never over a reply in progress: someone is watching that. */}
      {idle && assistantState === 'idle' && !sleep.asleep && <Ambient onWake={wake} />}

      {/* Above everything, including the clock — asleep outranks idle. */}
      {sleep.asleep && (
        <SleepOverlay
          state={sleep}
          onWake={() => {
            wakeUp()
            wake()
          }}
        />
      )}
    </div>
  )
}
