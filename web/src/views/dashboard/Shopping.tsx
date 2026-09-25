import { useCallback, useEffect, useState } from 'react';
import { fetchPanel } from '../../api';
import type { NotesPanel } from '../../api';
import { useWony } from '../../lib/wonyContext';
import { CARD, SectionLabel } from '../../components/ui';

const POLL_MS = 15000;

export function Shopping() {
  const { runJob, jobRanAt } = useWony();
  const [notes, setNotes] = useState<NotesPanel | null>(null);

  const refresh = useCallback(() => {
    fetchPanel<NotesPanel>('notes').then((r) => setNotes(r.data));
  }, []);

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, POLL_MS);
    return () => clearInterval(poll);
  }, [refresh, jobRanAt]);

  const shopping = notes?.lists.find((l) => l.name === 'shopping');
  const items = shopping?.items ?? [];

  return (
    <div className={`${CARD} p-4.5 flex flex-col gap-3`}>
      <SectionLabel>Shopping</SectionLabel>
      <div className="flex gap-1.5 flex-wrap">
        {items.map((item, i) => (
          <button
            key={`${item}-${i}`}
            onClick={() => runJob('note', { action: 'remove', text: item, list_name: 'shopping' }, { from: 'Dashboard' }).then(refresh)}
            className="border-0 bg-pink-soft text-red rounded-lg px-2.5 py-1.5 text-[13px] font-medium"
          >
            {item} ×
          </button>
        ))}
        {items.length === 0 && <span className="text-sm text-muted">Nothing on the list.</span>}
      </div>
    </div>
  );
}
