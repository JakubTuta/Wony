import { useEffect, useState } from 'react';
import { CalendarDays, MapPin } from 'lucide-react';
import { fetchPanel } from '../api';
import type { AgendaEvent, AgendaPanel } from '../api';
import { CARD, MUTED, Resting, SectionLabel } from './ui';

// Someone accepts an invitation while this is open. Slow enough not to matter
// to Google's quota, fast enough not to be wrong all afternoon.
const REFRESH_MS = 5 * 60 * 1000;

/** The ISO date an event falls on, in local terms.
 *
 *  An all-day event arrives as a bare "2026-09-01" with no zone; putting that
 *  through Date() reads it as UTC and slides it a day either way depending on
 *  the offset. Its first ten characters are already the answer.
 */
function dayOf(event: AgendaEvent): string {
  if (event.all_day) return event.start.slice(0, 10);
  const at = new Date(event.start);
  const local = new Date(at.getTime() - at.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function heading(day: string, today: string, locale: string): string {
  const days = Math.round(
    (Date.parse(`${day}T00:00:00`) - Date.parse(`${today}T00:00:00`)) / 86400000,
  );
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  return new Date(`${day}T00:00:00`).toLocaleDateString(locale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}

function clock(value: string, locale: string): string {
  const at = new Date(value);
  return Number.isNaN(at.getTime())
    ? ''
    : at.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
}

export function Agenda({ locale }: { locale: string }) {
  const [panel, setPanel] = useState<AgendaPanel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => {
      fetchPanel<AgendaPanel>('agenda').then((result) => {
        setPanel(result.data);
        setError(result.error);
        setLoading(false);
      });
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  if (loading) return <Resting title="Reading your calendar…" />;
  if (error || !panel) {
    return (
      <Resting icon={<CalendarDays size={32} />} title={error ?? 'No calendar right now.'} />
    );
  }

  const multipleAccounts = new Set(panel.events.map((e) => e.account)).size > 1;

  return (
    <div className="p-4 space-y-5">
      {panel.days.map((day) => {
        const events = panel.events.filter((event) => dayOf(event) === day);
        return (
          <div key={day}>
            <SectionLabel>{heading(day, panel.today, locale)}</SectionLabel>
            {events.length === 0 ? (
              <p className={`text-sm ${MUTED} px-0.5`}>Nothing on.</p>
            ) : (
              <div className="space-y-1.5">
                {events.map((event) => (
                  <Row
                    key={`${event.account}:${event.id}`}
                    event={event}
                    locale={locale}
                    showAccount={multipleAccounts}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Row({
  event,
  locale,
  showAccount,
}: {
  event: AgendaEvent;
  locale: string;
  showAccount: boolean;
}) {
  return (
    <div className={`${CARD} flex items-start gap-3 px-3 py-2.5`}>
      <div className="w-14 shrink-0">
        {event.all_day ? (
          <span className={`text-xs ${MUTED}`}>All day</span>
        ) : (
          <>
            <div className="text-sm text-gray-900 dark:text-gray-100 tabular-nums leading-tight">
              {clock(event.start, locale)}
            </div>
            {event.end && (
              <div className={`text-xs ${MUTED} tabular-nums leading-tight`}>
                {clock(event.end, locale)}
              </div>
            )}
          </>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="text-sm text-gray-900 dark:text-gray-100">{event.title}</div>
        {event.location && (
          <div className={`text-xs ${MUTED} flex items-center gap-1 min-w-0`}>
            <MapPin size={11} className="shrink-0" />
            <span className="truncate">{event.location}</span>
          </div>
        )}
      </div>

      {showAccount && event.account && (
        <span
          className={`text-[11px] ${MUTED} shrink-0 px-2 py-0.5 rounded-full
                      border border-gray-200 dark:border-gray-700`}
        >
          {event.account}
        </span>
      )}
    </div>
  );
}
