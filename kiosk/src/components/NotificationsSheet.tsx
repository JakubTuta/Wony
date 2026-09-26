import type { NotificationRecord } from '../api'

export function NotificationsSheet({
  notifications,
  onDismiss,
  onClose,
}: {
  notifications: NotificationRecord[]
  onDismiss: (id: number) => void
  onClose: () => void
}) {
  return (
    <div
      className="absolute inset-0 z-40 flex items-start justify-end"
      style={{ background: 'var(--wony-scrim)', padding: '100px 32px' }}
      onPointerDown={onClose}
    >
      <div
        className="w-[560px] rounded-[32px] bg-surface p-7 flex flex-col gap-4"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <span className="t-label text-muted">Notifications</span>

        {notifications.length === 0 && (
          <span className="text-[21px] text-muted py-3">All caught up.</span>
        )}

        {notifications.map((n) => (
          <div
            key={n.id ?? n.text}
            className="flex items-center justify-between gap-4 rounded-[22px] bg-surface-2 px-5 py-[18px]"
          >
            <div className="flex flex-col gap-1 min-w-0">
              <span className="text-[21px] font-semibold leading-[1.25]">{n.text}</span>
              <span className="text-[16px] text-muted truncate">{n.source}</span>
            </div>
            {n.id !== null && (
              <button
                onClick={() => onDismiss(n.id!)}
                className="press shrink-0 h-16 px-5 rounded-[20px] bg-panel text-[18px] font-semibold"
              >
                Dismiss
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
