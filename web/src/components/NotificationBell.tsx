import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Bell, Clock, Info, Mail } from 'lucide-react';
import { ackNotifications, connectEventSocket, fetchNotifications } from '../api';
import type { Notification } from '../api';
import { MUTED } from '../panels/ui';

const KIND_ICONS = {
  reminder: Clock,
  alert: Mail,
  error: AlertTriangle,
  info: Info,
} as const;

/** Proactive messages, waiting until they are read.
 *
 *  These used to be spoken once and gone — and with audio off, not even that.
 *  A timer that fired while you were in another room is still here.
 */
export function NotificationBell() {
  const [items, setItems] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchNotifications().then(setItems);
    return connectEventSocket({
      onNotification: (n) => setItems((prev) => [n, ...prev]),
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);

  const clear = async (id?: number) => {
    await ackNotifications(id);
    setItems((prev) => (id === undefined ? [] : prev.filter((n) => n.id !== id)));
  };

  return (
    <div className="relative" ref={box}>
      <button
        onClick={() => setOpen(!open)}
        aria-label={`Notifications${items.length ? ` (${items.length} unread)` : ''}`}
        className={`relative flex items-center justify-center w-8 h-8 rounded-lg
                    hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors ${MUTED}`}
      >
        <Bell size={16} />
        {items.length > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full
                       bg-violet-600 text-white text-[10px] font-medium
                       flex items-center justify-center tabular-nums"
          >
            {items.length > 9 ? '9+' : items.length}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-10 z-50 w-80 max-h-96 overflow-y-auto rounded-xl
                     border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900
                     shadow-lg"
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 dark:border-gray-800">
            <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
              Notifications
            </span>
            {items.length > 0 && (
              <button
                onClick={() => clear()}
                className="text-xs text-violet-600 dark:text-violet-400"
              >
                Clear all
              </button>
            )}
          </div>

          {items.length === 0 ? (
            <p className={`text-xs ${MUTED} px-3 py-6 text-center`}>Nothing waiting.</p>
          ) : (
            items.map((n) => {
              const Icon = KIND_ICONS[n.kind] ?? Info;
              return (
                <button
                  key={n.id ?? n.ts}
                  onClick={() => n.id !== null && clear(n.id)}
                  className="w-full text-left px-3 py-2.5 flex gap-2.5 border-b
                             border-gray-100 dark:border-gray-800 last:border-0
                             hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
                >
                  <Icon
                    size={14}
                    className={`shrink-0 mt-0.5 ${
                      n.kind === 'error' ? 'text-red-500' : 'text-violet-500'
                    }`}
                  />
                  <div className="min-w-0">
                    <p className="text-xs text-gray-800 dark:text-gray-200 break-words">
                      {n.text}
                    </p>
                    <p className={`text-[11px] ${MUTED}`}>
                      {n.source || n.kind} · {n.ts.slice(11, 16)}
                    </p>
                  </div>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
