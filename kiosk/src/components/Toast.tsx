import { useEffect } from 'react'
import { AlertTriangle, Bell, Info, X } from 'lucide-react'
import type { NotificationRecord } from '../api'

const ICONS = {
  info: Info,
  reminder: Bell,
  alert: AlertTriangle,
  error: AlertTriangle,
}

const TONES = {
  info: 'text-muted',
  reminder: 'text-accent',
  alert: 'text-warn',
  error: 'text-danger',
}

/** A proactive message, the moment it arrives.
 *
 *  It disappears on its own, but the message itself does not: it stays in the
 *  database until acknowledged. Nobody has to be watching when it fires. */
export function Toast({
  notification,
  onOpen,
  onDismiss,
}: {
  notification: NotificationRecord
  onOpen: () => void
  onDismiss: () => void
}) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 8000)
    return () => clearTimeout(timer)
  }, [notification, onDismiss])

  const Icon = ICONS[notification.kind] ?? Info
  const tone = TONES[notification.kind] ?? 'text-muted'

  return (
    <div className="fade-up absolute top-3 left-3 right-3 z-40">
      <div
        onClick={onOpen}
        className="press flex items-start gap-3 px-4 py-3 rounded-2xl bg-surface-2 border border-line"
        style={{ boxShadow: 'var(--wony-shadow)' }}
      >
        <Icon size={20} className={`${tone} mt-0.5 shrink-0`} />
        <div className="flex-1 min-w-0">
          {notification.source && (
            <div className="t-small text-muted uppercase tracking-wide">
              {notification.source}
            </div>
          )}
          <div className="t-body line-clamp-3">{notification.text}</div>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDismiss()
          }}
          aria-label="Dismiss"
          className="press flex items-center justify-center w-9 h-9 -mr-1 -mt-1 rounded-full text-muted shrink-0"
        >
          <X size={18} />
        </button>
      </div>
    </div>
  )
}
