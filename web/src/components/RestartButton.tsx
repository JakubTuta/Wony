import { useEffect, useState } from 'react';
import { fetchConfig, restartApp } from '../api';

/** "Restart now" next to a "needs a restart" notice. Renders nothing when the
 * server cannot relaunch itself (started without the tray), rather than a
 * button that can only fail. */
export function RestartButton() {
  const [canRestart, setCanRestart] = useState(false);
  const [state, setState] = useState<'idle' | 'restarting' | 'failed'>('idle');
  const [error, setError] = useState('');

  useEffect(() => {
    fetchConfig().then((c) => setCanRestart(c.can_restart)).catch(() => {});
  }, []);

  if (!canRestart) return null;

  if (state === 'restarting') {
    return <span className="text-xs text-muted">Restarting — reload this page in a few seconds.</span>;
  }

  return (
    <span className="flex items-center gap-2">
      <button
        onClick={() => {
          setState('restarting');
          restartApp().catch((e: unknown) => {
            setError(e instanceof Error ? e.message : String(e));
            setState('failed');
          });
        }}
        className="border-0 bg-accent text-on-accent rounded-[9px] px-3 py-1.5 text-[13px] font-semibold"
      >
        Restart now
      </button>
      {state === 'failed' && <span className="text-xs text-red">{error}</span>}
    </span>
  );
}
