import { useEffect, useState } from 'react';
import { fetchPanel } from '../../api';
import type { InboxPanel } from '../../api';
import { CARD, SectionLabel } from '../../components/ui';

const REFRESH_MS = 60 * 1000;

function relativeDay(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  const today = new Date();
  const sameDay = at.toDateString() === today.toDateString();
  return sameDay
    ? at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : at.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

export function Inbox() {
  const [panel, setPanel] = useState<InboxPanel | null>(null);

  useEffect(() => {
    const load = () => fetchPanel<InboxPanel>('inbox').then((r) => setPanel(r.data));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  if (!panel || panel.error) {
    return (
      <div className={`${CARD} p-4.5 flex flex-col gap-3.5`}>
        <SectionLabel>Inbox</SectionLabel>
        <span className="text-sm text-muted">{panel?.error ?? 'Checking your inbox…'}</span>
      </div>
    );
  }

  return (
    <div className={`${CARD} p-4.5 flex flex-col gap-3`}>
      <div className="flex justify-between items-center">
        <SectionLabel>Inbox</SectionLabel>
        <span className="text-xs text-muted">{panel.unread_total} unread</span>
      </div>
      {panel.messages.length === 0 ? (
        <span className="text-sm text-muted">Nothing unread.</span>
      ) : (
        panel.messages.slice(0, 5).map((m) => (
          <div key={m.id} className="flex justify-between gap-2.5 items-baseline">
            <div className="flex flex-col gap-px min-w-0">
              <span className="text-[15px] font-medium truncate">{m.subject}</span>
              <span className="text-xs text-muted truncate">{m.sender}</span>
            </div>
            <span className="font-mono text-xs text-muted whitespace-nowrap">{relativeDay(m.date)}</span>
          </div>
        ))
      )}
    </div>
  );
}
