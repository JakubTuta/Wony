import { useEffect, useMemo, useRef, useState } from 'react';
import { useWony } from '../lib/wonyContext';
import { Pill } from './ui';

type Filter = 'all' | 'issues' | 'messages';

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'issues', label: 'Errors & warnings' },
  { id: 'messages', label: 'Messages' },
];

type Level = 'error' | 'warning' | 'info' | 'reminder' | 'alert';

interface Row {
  key: string;
  level: Level;
  message: string;
  hint?: string;
  ts: string;
  source: string;
  moduleKey?: string;
  dismiss: () => void;
}

export function NotificationsMenu({
  onClose,
  onOpenModule,
}: {
  onClose: () => void;
  onOpenModule: (moduleKey: string) => void;
}) {
  const { health, settings, jobs, notifications, diagnostics, ackOne, dismissDiagnostic } = useWony();
  const [filter, setFilter] = useState<Filter>('all');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [onClose]);

  const moduleKeys = useMemo(() => {
    const keys = new Set<string>(jobs.map((j) => j.module).filter(Boolean));
    settings?.modules.forEach((m) => keys.add(m.key));
    return keys;
  }, [jobs, settings]);

  const moduleFor = (source: string): string | undefined => {
    const stripped = source.replace(/^trigger:/, '').toLowerCase();
    return moduleKeys.has(stripped) ? stripped : undefined;
  };

  const rows: Row[] = useMemo(() => {
    const diagRows: Row[] = diagnostics.map((d, i) => ({
      key: `d${i}`,
      level: d.level,
      message: d.message,
      hint: d.hint || undefined,
      ts: d.ts,
      source: d.source,
      moduleKey: moduleFor(d.source),
      dismiss: () => dismissDiagnostic(i),
    }));
    const notifRows: Row[] = notifications
      .filter((n) => !n.acknowledged)
      .map((n) => ({
        key: `n${n.id}`,
        level: n.kind,
        message: n.text,
        ts: n.ts,
        source: n.source,
        moduleKey: moduleFor(n.source),
        dismiss: () => ackOne(n.id ?? undefined),
      }));
    return [...diagRows, ...notifRows];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diagnostics, notifications, jobs, settings]);

  const filtered = rows.filter((r) => {
    if (filter === 'issues') return r.level === 'error' || r.level === 'warning';
    if (filter === 'messages') return r.level === 'info' || r.level === 'reminder' || r.level === 'alert';
    return true;
  });

  const dismissAll = () => {
    diagnostics.forEach(() => dismissDiagnostic(0));
    notifications.filter((n) => !n.acknowledged).forEach((n) => ackOne(n.id ?? undefined));
  };

  const enabledCount = settings?.modules.filter((m) => !m.always_on && m.enabled).length ?? 0;
  const switchableCount = settings?.modules.filter((m) => !m.always_on).length ?? 0;
  const speechDevice = health?.compute?.stt_device;

  const pillTone = (level: Level) =>
    level === 'error' ? 'error' : level === 'warning' || level === 'alert' ? 'pink' : level === 'info' ? 'teal' : 'message';

  return (
    <div
      ref={ref}
      className="absolute top-[52px] right-0 w-[420px] max-w-[calc(100vw-48px)] bg-surface border rounded-2xl flex flex-col overflow-hidden"
      style={{ borderColor: 'var(--color-pink-border-2)', boxShadow: '0 18px 40px rgba(16,43,47,0.16)' }}
    >
      <div className="px-4.5 pt-4 pb-3 flex flex-col gap-2.5" style={{ background: 'var(--color-pink-faint)', borderBottom: '1px solid var(--color-pink-border)' }}>
        <div className="flex justify-between items-center">
          <span className="text-base font-bold">Notifications</span>
          <button onClick={dismissAll} className="border-0 bg-transparent text-red text-[13px] font-semibold">
            Dismiss all
          </button>
        </div>
        <div className="flex flex-wrap gap-x-3.5 gap-y-1.5 text-xs text-muted">
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-ok" />
            {health ? `Online · ${health.provider}` : 'Connecting…'}
          </span>
          {health?.model && <span className="font-mono">{health.model}</span>}
          {speechDevice && <span>Speech on {speechDevice}</span>}
          <span>{enabledCount} of {switchableCount} modules on</span>
        </div>
        <div className="flex gap-1">
          {FILTERS.map((f) => {
            const active = filter === f.id;
            return (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className="border-0 rounded-full px-2.5 py-1 text-[13px] font-semibold"
                style={{ background: active ? 'var(--color-accent)' : 'white', color: active ? 'var(--color-on-accent)' : 'var(--color-muted)' }}
              >
                {f.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="max-h-[420px] overflow-auto flex flex-col">
        {filtered.length === 0 && (
          <span className="px-4.5 py-6 text-sm text-muted">Nothing here.</span>
        )}
        {filtered.map((row) => (
          <div key={row.key} className="grid grid-cols-[auto_1fr] gap-3 px-4.5 py-3.5" style={{ borderBottom: '1px solid var(--color-divider)' }}>
            <Pill tone={pillTone(row.level)}>
              <span className="uppercase tracking-wide">{row.level}</span>
            </Pill>
            <div className="flex flex-col gap-1 min-w-0">
              <span className="text-sm font-medium leading-snug">{row.message}</span>
              {row.hint && <span className="font-mono text-[11px] text-muted">{row.hint}</span>}
              <div className="flex items-center gap-2.5 text-xs text-muted">
                <span className="font-mono">{row.ts} · {row.source}</span>
                {row.moduleKey && (
                  <button
                    onClick={() => onOpenModule(row.moduleKey!)}
                    className="border-0 bg-transparent p-0 text-red text-xs font-semibold"
                  >
                    Open module
                  </button>
                )}
                <button onClick={row.dismiss} className="border-0 bg-transparent p-0 ml-auto text-muted text-xs font-semibold">
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
