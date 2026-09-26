import { useState } from 'react'
import { Frame } from './components/Frame'
import { Header } from './components/Header'
import { NavBar } from './components/NavBar'
import { NotificationsSheet } from './components/NotificationsSheet'
import { SleepOverlay } from './components/SleepOverlay'
import type { Tab } from './lib/tabs'
import { Ambient } from './screens/Ambient'
import { Home } from './screens/Home'
import { Macros } from './screens/Macros'
import { Music } from './screens/Music'
import { Rooms } from './screens/Rooms'
import { System } from './screens/System'
import { useIdle } from './state/useIdle'
import { useWakeLock } from './state/useWakeLock'
import { LiveProvider } from './state/LiveProvider'
import { UiProvider } from './state/UiProvider'
import { WonyProvider } from './state/WonyProvider'
import { useWony } from './state/wony-context'

export default function App() {
  return (
    <WonyProvider>
      <LiveProvider>
        <Frame>
          <UiProvider>
            <Shell />
          </UiProvider>
        </Frame>
      </LiveProvider>
    </WonyProvider>
  )
}

function Shell() {
  const { config, notifications, ack, sleep, wakeUp } = useWony()
  // Dropped while asleep: the lock exists to stop the compositor blanking a
  // screen we want lit, and holding it through a deliberate blackout would be
  // arguing with ourselves.
  useWakeLock(!sleep.asleep)

  const [tab, setTab] = useState<Tab>('home')
  const [editing, setEditing] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)

  const idleMinutes = config?.kiosk.idle_minutes ?? 15
  const { idle, wake } = useIdle(idleMinutes)

  const changeTab = (next: Tab) => {
    setTab(next)
    setEditing(false)
  }

  return (
    <>
      <Header
        tab={tab}
        editing={editing}
        onToggleEdit={() => setEditing((e) => !e)}
        onOpenNotifications={() => setNotifOpen(true)}
        onOpenSystem={() => changeTab('system')}
      />

      <main className="flex-1 min-h-0 px-8 pb-6 pt-1">
        {tab === 'home' && <Home editing={editing} />}
        {tab === 'rooms' && <Rooms />}
        {tab === 'music' && <Music />}
        {tab === 'macros' && <Macros />}
        {tab === 'system' && <System onSleeping={() => changeTab('home')} />}
      </main>

      <NavBar tab={tab} onChange={changeTab} />

      {notifOpen && (
        <NotificationsSheet
          notifications={notifications}
          onDismiss={ack}
          onClose={() => setNotifOpen(false)}
        />
      )}

      {/* Never over a sheet in progress, and outranked only by sleep. */}
      {idle && !sleep.asleep && !notifOpen && <Ambient onWake={wake} />}

      {/* Above everything — asleep outranks idle. */}
      {sleep.asleep && (
        <SleepOverlay
          state={sleep}
          onWake={() => {
            wakeUp()
            wake()
          }}
        />
      )}
    </>
  )
}
