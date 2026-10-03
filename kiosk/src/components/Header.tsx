import { Settings as SettingsIcon, WifiOff } from 'lucide-react'
import { useLive } from '../state/live-context'
import { useClock } from '../state/useClock'
import { useWony } from '../state/wony-context'
import type { Tab } from '../lib/tabs'

export function Header({
  tab,
  editing,
  onToggleEdit,
  onOpenNotifications,
  onOpenSystem,
}: {
  tab: Tab
  editing: boolean
  onToggleEdit: () => void
  onOpenNotifications: () => void
  onOpenSystem: () => void
}) {
  const { connected, unreadCount } = useWony()
  const { weather, agenda } = useLive()
  const now = useClock()
  const locale = 'en'

  const summary: string[] = []
  const w = weather.data
  if (w && !w.error && w.temperature !== null) {
    summary.push(`${Math.round(w.temperature)}°${w.description ? ` · ${w.description}` : ''}`)
  }
  const next = agenda.data?.events?.[0]
  if (next) {
    const time = new Date(next.start).toLocaleTimeString(locale, {
      hour: '2-digit',
      minute: '2-digit',
    })
    summary.push(`Next: ${next.title} ${time}`)
  }

  return (
    <header className="h-24 shrink-0 flex items-center justify-between px-8 gap-6">
      <div className="flex items-center gap-7 min-w-0">
        <span className="t-clock shrink-0">
          {now.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}
        </span>
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-[20px] font-semibold">
            {now.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' })}
          </span>
          {summary.length > 0 && (
            <span className="text-[18px] text-muted truncate">{summary.join(' · ')}</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {!connected && (
          <span
            title="Not connected to Wony"
            className="w-16 h-16 rounded-full flex items-center justify-center text-warn"
          >
            <WifiOff size={22} />
          </span>
        )}

        {tab === 'home' && (
          <button
            onClick={onToggleEdit}
            className={`press h-16 px-[26px] rounded-[32px] border-2 border-line text-[20px] font-semibold ${
              editing ? 'bg-surface-2' : 'bg-transparent'
            }`}
          >
            {editing ? 'Done' : 'Edit'}
          </button>
        )}

        <button
          onClick={onOpenSystem}
          aria-label="Settings, accounts and sleep"
          className="press w-16 h-16 rounded-full flex items-center justify-center text-muted bg-surface"
        >
          <SettingsIcon size={22} />
        </button>

        <button
          onClick={onOpenNotifications}
          aria-label={`Notifications${unreadCount ? ` (${unreadCount})` : ''}`}
          className={`press h-16 min-w-16 px-[22px] rounded-[32px] flex items-center gap-2.5 text-[20px] font-bold ${
            unreadCount ? 'bg-accent text-on-accent' : 'bg-surface text-muted'
          }`}
        >
          <span
            className="w-3 h-3 rounded-full"
            style={{ background: unreadCount ? 'var(--wony-on-accent)' : 'var(--wony-off)' }}
          />
          {unreadCount || 0}
        </button>
      </div>
    </header>
  )
}
