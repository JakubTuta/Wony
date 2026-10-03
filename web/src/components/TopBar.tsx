import { useState } from 'react';
import { Bell } from 'lucide-react';
import { useWony } from '../lib/wonyContext';
import { NotificationsMenu } from './NotificationsMenu';

export type View = 'dashboard' | 'modules' | 'macros' | 'settings';

const NAV: { id: View; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'modules', label: 'Features' },
  { id: 'macros', label: 'Routines' },
  { id: 'settings', label: 'Settings' },
];

export function TopBar({
  view,
  onNavigate,
  onOpenModule,
  counts,
}: {
  view: View;
  onNavigate: (view: View) => void;
  onOpenModule: (moduleKey: string) => void;
  counts: Partial<Record<View, number>>;
}) {
  const { health, unreadCount } = useWony();
  const [notifOpen, setNotifOpen] = useState(false);

  return (
    <div
      className="sticky top-0 z-20 bg-surface border-b flex items-center flex-wrap gap-x-5 gap-y-2 px-6 py-2.5"
      style={{ borderColor: 'var(--color-pink-border)' }}
    >
      <div className="flex items-center gap-2.5">
        <div className="w-[22px] h-[22px] rounded-full bg-accent" />
        <span className="text-[19px] font-bold tracking-tight text-teal-dark">Wony</span>
      </div>

      <nav className="flex gap-1 min-w-0 overflow-x-auto">
        {NAV.map((item) => {
          const active = view === item.id;
          const count = counts[item.id];
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className="flex items-center gap-1.5 border-0 rounded-full px-3.5 py-2 text-sm font-semibold whitespace-nowrap shrink-0 transition-colors"
              style={{
                background: active ? 'var(--color-pink-soft)' : 'transparent',
                color: active ? 'var(--color-red)' : 'var(--color-body2)',
              }}
            >
              <span>{item.label}</span>
              {count !== undefined && (
                <span className="font-mono text-[11px] opacity-70">{count}</span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="ml-auto flex items-center gap-3 relative">
        {health && (
          <span className="hidden sm:flex items-center gap-1.5 text-xs text-muted whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-full bg-ok shrink-0" />
            {health.provider}
            {health.model && <span className="font-mono">{health.model}</span>}
          </span>
        )}
        <button
          onClick={() => setNotifOpen((v) => !v)}
          className="relative w-10 h-10 shrink-0 rounded-full border-0 flex items-center justify-center"
          style={{ background: notifOpen ? 'var(--color-pink-soft)' : 'var(--color-pink-faint)' }}
          aria-label="Notifications"
        >
          <Bell size={18} color="#9E3A34" strokeWidth={2} />
          {unreadCount > 0 && (
            <span
              className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] rounded-full bg-badge text-white text-[11px] font-bold flex items-center justify-center px-1"
              style={{ border: '2px solid white' }}
            >
              {unreadCount}
            </span>
          )}
        </button>
        {notifOpen && (
          <NotificationsMenu
            onClose={() => setNotifOpen(false)}
            onOpenModule={(key) => {
              setNotifOpen(false);
              onOpenModule(key);
            }}
          />
        )}
      </div>
    </div>
  );
}
