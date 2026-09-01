import { Bell, ChevronLeft, Moon, Music, Sun, Terminal, WifiOff } from 'lucide-react'
import { useClock } from '../state/useClock'
import { useWony } from '../state/wony-context'
import type { Theme } from '../state/useTheme'

export function StatusBar({
  title,
  onBack,
  onNotifications,
  onCommands,
  onMusic,
  theme,
  onToggleTheme,
}: {
  title: string
  onBack?: () => void
  onNotifications: () => void
  onCommands: () => void
  /** Omitted when the Spotify module is not enabled. */
  onMusic?: () => void
  theme: Theme
  onToggleTheme: () => void
}) {
  const { unreadCount, connected, config } = useWony()
  const now = useClock()
  const locale = config?.assistant.language || 'en'

  return (
    <header className="flex items-center gap-2 px-3 h-16 shrink-0 border-b border-line">
      {onBack ? (
        <button
          onClick={onBack}
          aria-label="Back"
          className="press flex items-center justify-center w-11 h-11 -ml-1 rounded-full text-muted"
        >
          <ChevronLeft size={26} />
        </button>
      ) : null}

      <span className="t-display truncate">{title}</span>

      <div className="flex-1" />

      {!connected && (
        <span
          title="Not connected to Wony"
          className="flex items-center justify-center w-11 h-11 text-warn"
        >
          <WifiOff size={20} />
        </span>
      )}

      {onMusic && (
        <button
          onClick={onMusic}
          aria-label="Music"
          className="press flex items-center justify-center w-11 h-11 rounded-full text-muted"
        >
          <Music size={20} />
        </button>
      )}

      <button
        onClick={onCommands}
        aria-label="All commands"
        className="press flex items-center justify-center w-11 h-11 rounded-full text-muted"
      >
        <Terminal size={20} />
      </button>

      <button
        onClick={onToggleTheme}
        aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
        className="press flex items-center justify-center w-11 h-11 rounded-full text-muted"
      >
        {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
      </button>

      <button
        onClick={onNotifications}
        aria-label={`Notifications${unreadCount ? ` (${unreadCount})` : ''}`}
        className="press relative flex items-center justify-center w-11 h-11 rounded-full text-muted"
      >
        <Bell size={20} />
        {unreadCount > 0 && (
          <span className="absolute top-1.5 right-1.5 min-w-5 h-5 px-1 rounded-full bg-accent text-on-accent text-[11px] font-semibold leading-5 text-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      <span className="t-body tabular-nums text-muted pl-1 pr-1">
        {now.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}
      </span>
    </header>
  )
}
