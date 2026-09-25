import { useEffect, useState } from 'react';
import { fetchPanel } from '../../api';
import type { AgendaPanel } from '../../api';
import { CARD, SectionLabel } from '../../components/ui';

const REFRESH_MS = 5 * 60 * 1000;

function clock(value: string): string {
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? '' : at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function Agenda() {
  const [panel, setPanel] = useState<AgendaPanel | null>(null);

  useEffect(() => {
    const load = () => fetchPanel<AgendaPanel>('agenda').then((r) => setPanel(r.data));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  const today = panel?.events.filter((e) => e.start.slice(0, 10) === panel.today).slice(0, 4) ?? [];

  return (
    <div className={`${CARD} p-4.5 flex flex-col gap-3.5`}>
      <SectionLabel>Agenda</SectionLabel>
      {today.length === 0 ? (
        <span className="text-sm text-muted">Nothing on today.</span>
      ) : (
        today.map((event) => (
          <div key={`${event.account}:${event.id}`} className="grid gap-2.5 items-baseline" style={{ gridTemplateColumns: '64px 1fr' }}>
            <span className="font-mono text-[13px] font-medium text-red">
              {event.all_day ? 'All day' : clock(event.start)}
            </span>
            <div className="flex flex-col gap-px min-w-0">
              <span className="text-[15px] font-medium truncate">{event.title}</span>
              {event.location && <span className="text-[13px] text-muted truncate">{event.location}</span>}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
