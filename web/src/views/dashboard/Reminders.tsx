import { useEffect, useState } from 'react';
import { fetchPanel } from '../../api';
import type { RemindersPanel } from '../../api';
import { useWony } from '../../lib/wonyContext';
import { CARD, SectionLabel } from '../../components/ui';

const POLL_MS = 15000;

function countdown(iso: string | null): string {
  if (!iso) return 'repeating';
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (seconds <= 0) return 'due now';
  if (seconds < 60) return `in ${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `in ${hours}h`;
  return new Date(iso).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
}

export function Reminders() {
  const { jobRanAt } = useWony();
  const [reminders, setReminders] = useState<RemindersPanel | null>(null);

  useEffect(() => {
    const load = () => fetchPanel<RemindersPanel>('reminders').then((r) => setReminders(r.data));
    load();
    const poll = setInterval(load, POLL_MS);
    return () => clearInterval(poll);
  }, [jobRanAt]);

  const items = reminders?.reminders ?? [];

  return (
    <div className={`${CARD} p-4.5 flex flex-col gap-3`}>
      <SectionLabel>Timers &amp; reminders</SectionLabel>
      {items.length === 0 ? (
        <span className="text-sm text-muted">Nothing scheduled.</span>
      ) : (
        items.slice(0, 3).map((r) => (
          <div key={r.id} className="flex justify-between gap-2.5 items-baseline">
            <div className="flex flex-col gap-px min-w-0">
              <span className="text-[15px] font-medium truncate">
                {r.text || (r.action_job ? `Run ${r.action_job.replace(/_/g, ' ')}` : 'Timer')}
              </span>
              <span className="text-xs text-muted truncate">{r.when_str}</span>
            </div>
            <span className="font-mono text-xs text-red whitespace-nowrap">{countdown(r.next_run)}</span>
          </div>
        ))
      )}
    </div>
  );
}
