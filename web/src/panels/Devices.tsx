import { useEffect, useState } from 'react';
import { Lightbulb, Lock } from 'lucide-react';
import { controlDevice, fetchPanel } from '../api';
import type { Device, DevicesPanel } from '../api';
import { CARD, Chip, MUTED, Resting, SectionLabel } from './ui';

// Someone else flips a switch, or an automation runs.
const REFRESH_MS = 30 * 1000;

// Home Assistant will happily report a hundred entities. A filter row is the
// difference between a usable panel and a very long scroll.
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
};

function label(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain.replace(/_/g, ' ');
}

export function Devices() {
  const [panel, setPanel] = useState<DevicesPanel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [domain, setDomain] = useState('');

  useEffect(() => {
    const load = () => {
      fetchPanel<DevicesPanel>('devices').then((result) => {
        setPanel(result.data);
        setError(result.error);
        setLoading(false);
      });
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  const act = async (device: Device, action: string, brightness?: number) => {
    setBusy(device.entity_id);
    setNote(null);
    const result = await controlDevice(device.entity_id, action, brightness);
    // Home Assistant confirms the service call before the state settles, so
    // the list is re-read rather than guessed at.
    const next = await fetchPanel<DevicesPanel>('devices');
    setPanel(next.data);
    setBusy(null);
    if (!result.ok) setNote(result.text);
  };

  if (loading) return <Resting title="Finding your devices…" />;
  if (error || !panel) {
    return <Resting icon={<Lightbulb size={32} />} title={error ?? 'No devices right now.'} />;
  }

  const domains = [
    ...new Set(panel.areas.flatMap((a) => a.devices.map((d) => d.domain))),
  ].sort();

  const areas = panel.areas
    .map((area) => ({
      ...area,
      devices: domain ? area.devices.filter((d) => d.domain === domain) : area.devices,
    }))
    .filter((area) => area.devices.length > 0);

  return (
    <div className="p-4 space-y-4">
      {domains.length > 1 && (
        <div className="flex gap-1.5 flex-wrap">
          <Chip label="All" active={domain === ''} onClick={() => setDomain('')} />
          {domains.map((name) => (
            <Chip
              key={name}
              label={label(name)}
              active={domain === name}
              onClick={() => setDomain(name)}
            />
          ))}
        </div>
      )}

      {note && (
        <button
          onClick={() => setNote(null)}
          className="w-full text-left px-3 py-2 rounded-lg border border-amber-300
                     dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20"
        >
          <p className="text-xs text-amber-700 dark:text-amber-300 whitespace-pre-wrap">
            {note}
          </p>
        </button>
      )}

      {areas.length === 0 ? (
        <p className={`text-sm ${MUTED}`}>Nothing of that kind here.</p>
      ) : (
        areas.map((area) => (
          <div key={area.name || 'other'}>
            <SectionLabel>{area.name || 'Elsewhere'}</SectionLabel>
            <div className="space-y-1.5">
              {area.devices.map((device) => (
                <Row
                  key={device.entity_id}
                  device={device}
                  busy={busy === device.entity_id}
                  locksAllowed={panel.locks_allowed}
                  onAct={act}
                />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

function Row({
  device,
  busy,
  locksAllowed,
  onAct,
}: {
  device: Device;
  busy: boolean;
  locksAllowed: boolean;
  onAct: (device: Device, action: string, brightness?: number) => void;
}) {
  // A lock or garage door is shown either way — hiding the front door makes
  // the panel look broken. It just refuses until config says otherwise.
  const blocked = device.guarded && !locksAllowed;
  const disabled = busy || !device.available || blocked;

  return (
    <div className={`${CARD} flex items-center gap-3 px-3 py-2.5`}>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-gray-900 dark:text-gray-100 truncate flex items-center gap-1.5">
          {device.guarded && <Lock size={12} className={`${MUTED} shrink-0`} />}
          {device.name}
        </div>
        <div className={`text-xs ${MUTED} truncate`}>
          {blocked
            ? 'Locked off in config.yaml'
            : !device.available
              ? 'Unavailable'
              : device.brightness !== null
                ? `${device.state} · ${device.brightness}%`
                : device.state}
        </div>

        {device.dimmable && device.on && !disabled && (
          <input
            type="range"
            min={1}
            max={100}
            defaultValue={device.brightness ?? 100}
            aria-label={`${device.name} brightness`}
            // On change, not input: dragging fires input continuously, and
            // every one of those would be a service call.
            onChange={(e) => onAct(device, 'on', Number(e.target.value))}
            className="w-full mt-1.5 accent-violet-600"
          />
        )}
      </div>

      <Toggle
        on={device.on}
        disabled={disabled}
        busy={busy}
        label={device.name}
        onClick={() => onAct(device, 'toggle')}
      />
    </div>
  );
}

function Toggle({
  on,
  disabled,
  busy,
  label,
  onClick,
}: {
  on: boolean;
  disabled: boolean;
  busy: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`relative w-11 h-6 shrink-0 rounded-full border transition-colors
                  disabled:opacity-40 ${
                    on
                      ? 'bg-violet-600 border-violet-600'
                      : 'bg-gray-200 dark:bg-gray-700 border-gray-300 dark:border-gray-600'
                  }`}
    >
      {/* left-0.5 is load-bearing: without a horizontal anchor the knob falls
          back to its static position, which a button centres. Travel is the
          track's inner width less both gaps and the knob: 44 - 2 - 4 - 18 = 20. */}
      <span
        className={`absolute top-1/2 left-0.5 w-[18px] h-[18px] rounded-full
                    -translate-y-1/2 transition-transform ${
                      on ? 'translate-x-5 bg-white' : 'translate-x-0 bg-gray-400 dark:bg-gray-400'
                    } ${busy ? 'opacity-50' : ''}`}
      />
    </button>
  );
}
