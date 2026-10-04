import type { ReactNode } from 'react';
import { useWony } from '../lib/wonyContext';
import { moduleHealthState, moduleMessage } from '../lib/moduleHealth';
import { CARD } from './ui';

/** Blurs and dims whatever it wraps, with a reason overlaid on top, instead
 * of replacing it outright — the shape of the real widget (its own empty/
 * error layout included) stays visible so the page never looks broken.
 *
 * Shared by ModuleGate (config says the module is off/broken) and any widget
 * that also needs this look when config says "enabled" but the live check —
 * a fetch the config can't see, e.g. is the Spotify app actually open right
 * now — says otherwise. */
export function Gated({
  blocked,
  message,
  fullRow,
  children,
}: {
  blocked: boolean;
  message: string;
  fullRow?: boolean;
  children: ReactNode;
}) {
  // One tree shape whether blocked or not: swapping wrappers would unmount
  // the widget, and every widget fetches its panel on mount. `contents` keeps
  // the unblocked layout identical to having no wrapper at all.
  return (
    <div
      className={blocked ? 'relative' : 'contents'}
      style={blocked && fullRow ? { gridColumn: '1 / -1', minWidth: 0 } : undefined}
    >
      <div
        className={blocked ? 'pointer-events-none select-none opacity-40 blur-[2px]' : 'contents'}
        aria-hidden={blocked || undefined}
      >
        {children}
      </div>
      {blocked && (
        <div className="absolute inset-0 flex items-center justify-center p-4">
          <div className={`${CARD} px-4 py-3 text-center max-w-[85%] shadow-sm`}>
            <span className="text-sm font-medium">{message}</span>
          </div>
        </div>
      )}
    </div>
  );
}

/** Wraps a dashboard widget so it stays on the page (and discoverable) even
 * when its module is off or broken according to config/registration state. */
export function ModuleGate({
  moduleKey,
  label,
  fullRow,
  children,
}: {
  moduleKey: string;
  label: string;
  fullRow?: boolean;
  children: ReactNode;
}) {
  const { health, settings } = useWony();
  const state = moduleHealthState(moduleKey, health);

  // Until health arrives every module reads "off"; blocking on that would
  // flash "Turn on X in Features" over a working widget on every page load.
  return (
    <Gated blocked={health !== null && state !== 'ok'} message={moduleMessage(moduleKey, health, settings?.modules, label)} fullRow={fullRow}>
      {children}
    </Gated>
  );
}
