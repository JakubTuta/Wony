import { useCallback, useEffect, useState } from 'react';
import { AlarmClock, Repeat, X } from 'lucide-react';
import { fetchPanel, invokeJob } from '../api';
import type { RemindersPanel } from '../api';
import { CARD, MUTED, Resting } from './ui';

// Timers are the one panel where being a few seconds stale is obvious, so it
// refreshes often; the countdown itself ticks locally in between.
const POLL_MS = 15000;

function countdown(iso: string | null): string {
  if (!iso) return 'repeating';
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (seconds <= 0) return 'due now';
  if (seconds < 60) return `in ${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `in ${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `in ${hours}h ${minutes % 60}m`;
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function Reminders() {
  const [data, setData] = useState<RemindersPanel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [, forceTick] = useState(0);

  const refresh = useCallback(() => {
    fetchPanel<RemindersPanel>('reminders').then((result) => {
      setData(result.data);
      setError(result.error);
      setLoaded(true);
    });
  }, []);

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, POLL_MS);
    return () => clearInterval(poll);
  }, [refresh]);

  useEffect(() => {
    const tick = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(tick);
  }, []);

  const cancel = (id: string) => {
    setBusy(id);
    invokeJob('cancel_reminder', { id_or_text: id }).finally(() => {
      setBusy(null);
      refresh();
    });
  };

  if (!loaded) return <Resting title="…" />;
  if (error) return <Resting icon={<AlarmClock size={30} />} title={error} />;

  const reminders = data?.reminders ?? [];
  if (reminders.length === 0) {
    return (
      <Resting icon={<AlarmClock size={32} />} title="No timers running">
        Ask for one — "set a timer for 10 minutes", "remind me at 3pm to call mum",
        or "every weekday at 9am say good morning".
      </Resting>
    );
  }

  return (
    <div className="p-4 space-y-2">
      {reminders.map((reminder) => (
        <div
          key={reminder.id}
          className={`${CARD} px-3 py-2.5 flex items-center gap-3`}
        >
          <AlarmClock size={16} className="shrink-0 text-violet-500" />
          <div className="min-w-0 flex-1">
            <div className="text-sm text-gray-900 dark:text-gray-100 truncate">
              {reminder.text || (reminder.action_job
                ? `Run ${reminder.action_job.replace(/_/g, ' ')}`
                : 'Timer')}
            </div>
            <div className={`text-xs ${MUTED} flex items-center gap-1.5`}>
              <span className="tabular-nums">{countdown(reminder.next_run)}</span>
              {reminder.repeating && (
                <>
                  <Repeat size={11} />
                  <span className="truncate">{reminder.when_str}</span>
                </>
              )}
            </div>
          </div>
          <button
            onClick={() => cancel(reminder.id)}
            disabled={busy === reminder.id}
            aria-label="Cancel this timer"
            title="Cancel this timer"
            className={`shrink-0 w-7 h-7 rounded-lg flex items-center justify-center
                        transition-colors disabled:opacity-40 ${MUTED}
                        hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20`}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
