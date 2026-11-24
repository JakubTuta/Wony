// What the dashboard tile and both Smart home modes share: one live copy of the
// devices panel, and the one way a click turns into a device command.
import { useCallback, useEffect, useState } from 'react';
import { controlDevice, fetchPanel } from '../api';
import type { Control, DevicesPanel } from '../api';
import { useWony } from './wonyContext';

const DOMAIN_LABELS: Record<string, string> = {
  light: 'Lights',
  switch: 'Switches',
  cover: 'Blinds',
  climate: 'Heating',
  media_player: 'Media',
  lock: 'Locks',
  scene: 'Scenes',
  script: 'Scripts',
  fan: 'Fans',
  vacuum: 'Vacuum',
  lawn_mower: 'Mowers',
  button: 'Buttons',
};

export function domainLabel(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain.replace(/_/g, ' ');
}

const LOCKS_OFF_NOTE =
  'Locks are switched off. Turn on "Unlock doors and open the garage" in Settings to allow them.';

/** One line saying how a device is doing, as a person would read it. */
export function stateText(control: Control, locksAllowed: boolean): string {
  if (control.guarded && !locksAllowed) return 'Locks are off in Settings';
  if (!control.available) return 'Unavailable';
  if (control.current !== null) return `${control.state} · now ${control.current}°`;
  if (control.level !== null) return `${control.state} · ${control.level}%`;
  return control.state;
}

/** The word for what flipping this device does next. */
export function toggleAction(control: Control): string {
  // A lock's state is "off" while locked, so `on` means unlocked.
  if (control.domain === 'lock') return control.on ? 'lock' : 'unlock';
  if (control.domain === 'alarm_control_panel') return control.state === 'disarmed' ? 'arm' : 'disarm';
  if (control.domain === 'cover') return control.on ? 'close' : 'open';
  return control.on ? 'off' : 'on';
}

function actionLabel(action: string): string {
  if (action === 'on' || action === 'off') return `Turn ${action}`;
  return action.charAt(0).toUpperCase() + action.slice(1);
}

export type Act = (control: Control, action: string, value?: number, option?: string) => Promise<void>;

export type Devices = ReturnType<typeof useDevices>;

export function useDevices(refreshMs: number) {
  const { requestConfirm } = useWony();
  const [panel, setPanel] = useState<DevicesPanel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [note, setNote] = useState<string | null>(null);

  const reload = useCallback(
    () =>
      fetchPanel<DevicesPanel>('devices').then((result) => {
        // A failed refresh keeps what was on screen; blanking the house for one
        // dropped request would be worse than a stale state.
        if (result.data) setPanel(result.data);
        setError(result.error);
        setLoaded(true);
      }),
    [],
  );

  useEffect(() => {
    reload();
    const timer = setInterval(() => {
      if (!document.hidden) reload();
    }, refreshMs);
    return () => clearInterval(timer);
  }, [reload, refreshMs]);

  const act: Act = useCallback(
    async (control, action, value, option) => {
      const id = control.entity_id;
      setBusy((prev) => new Set(prev).add(id));
      setNote(null);
      const result = await controlDevice(id, action, value, option);
      await reload();
      setBusy((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      if (!result.ok) setNote(result.text);
    },
    [reload],
  );

  const locksAllowed = panel?.locks_allowed ?? false;

  const toggle = useCallback(
    (control: Control, deviceName: string) => {
      if (!control.guarded) {
        act(control, 'toggle');
        return;
      }
      if (!locksAllowed) {
        setNote(LOCKS_OFF_NOTE);
        return;
      }
      const action = toggleAction(control);
      const name = deviceName.toLowerCase();
      requestConfirm({
        title: `${actionLabel(action)} ${name}?`,
        sig: `control_home_device(target="${name}", action="${action}")`,
        onConfirm: () => act(control, 'toggle'),
      });
    },
    [act, locksAllowed, requestConfirm],
  );

  return { panel, error, loaded, busy, note, setNote, act, toggle, reload, locksAllowed };
}
