import { useEffect, useState } from 'react';
import { Lightbulb, Lock } from 'lucide-react';
import { controlDevice, fetchPanel } from '../api';
import type { Control, Device, DevicesPanel } from '../api';
import { CARD, Chip, MUTED, Resting, SectionLabel } from './ui';

// Someone else flips a switch, or an automation runs.
const REFRESH_MS = 30 * 1000;

// Home Assistant will happily report a hundred devices. A filter row is the
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
  lawn_mower: 'Mowers',
  button: 'Buttons',
};

function label(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain.replace(/_/g, ' ');
}

type Act = (control: Control, action: string, value?: number, option?: string) => void;

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

  const act: Act = async (control, action, value, option) => {
    setBusy(control.entity_id);
    setNote(null);
    const result = await controlDevice(control.entity_id, action, value, option);
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
    ...new Set(panel.areas.flatMap((a) => a.devices.map((d) => d.primary.domain))),
  ].sort();

  const areas = panel.areas
    .map((area) => ({
      ...area,
      devices: domain
        ? area.devices.filter((d) => d.primary.domain === domain)
        : area.devices,
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
                <Card
                  key={device.primary.entity_id}
                  device={device}
                  busy={busy}
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

function Card({
  device,
  busy,
  locksAllowed,
  onAct,
}: {
  device: Device;
  busy: string | null;
  locksAllowed: boolean;
  onAct: Act;
}) {
  const main = device.primary;
  // A lock or garage door is shown either way — hiding the front door makes
  // the panel look broken. It just refuses until config says otherwise.
  const blocked = main.guarded && !locksAllowed;
  const disabled = busy === main.entity_id || !main.available || blocked;

  return (
    <div className={`${CARD} px-3 py-2.5`}>
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm text-gray-900 dark:text-gray-100 truncate flex items-center gap-1.5">
            {main.guarded && <Lock size={12} className={`${MUTED} shrink-0`} />}
            {device.name}
          </div>
          <div className={`text-xs ${MUTED} truncate`}>
            {blocked
              ? 'Locked off in config.yaml'
              : !main.available
                ? 'Unavailable'
                : main.level !== null
                  ? `${main.state} · ${main.level}%`
                  : main.state}
          </div>

          {main.slider && !disabled && (
            <input
              type="range"
              min={0}
              max={100}
              defaultValue={main.level ?? 100}
              aria-label={`${device.name} level`}
              // On change, not input: dragging fires input continuously, and
              // every one of those would be a service call.
              onChange={(e) => onAct(main, 'on', Number(e.target.value))}
              className="w-full mt-1.5 accent-violet-600"
            />
          )}
        </div>

        <Widget control={main} label={device.name} busy={busy} disabled={disabled} onAct={onAct} />
      </div>

      {device.extras.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-700
                        flex flex-wrap items-center gap-x-3 gap-y-2">
          {device.extras.map((extra) => (
            <Extra
              key={extra.entity_id}
              control={extra}
              busy={busy}
              locksAllowed={locksAllowed}
              onAct={onAct}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Extra({
  control,
  busy,
  locksAllowed,
  onAct,
}: {
  control: Control;
  busy: string | null;
  locksAllowed: boolean;
  onAct: Act;
}) {
  const blocked = control.guarded && !locksAllowed;
  const disabled = busy === control.entity_id || !control.available || blocked;

  // A press button says what it does, so it needs no second label.
  if (control.press) {
    return (
      <Widget
        control={control}
        label={control.name}
        busy={busy}
        disabled={disabled}
        onAct={onAct}
      />
    );
  }

  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <span className={`text-xs ${MUTED} truncate`}>{control.name}</span>
      <Widget
        control={control}
        label={control.name}
        busy={busy}
        disabled={disabled}
        onAct={onAct}
      />
    </div>
  );
}

const FIELD =
  'text-xs rounded-lg px-2 py-1 border border-gray-300 dark:border-gray-600 ' +
  'bg-transparent text-gray-900 dark:text-gray-100 disabled:opacity-40';

function Widget({
  control,
  label,
  busy,
  disabled,
  onAct,
}: {
  control: Control;
  label: string;
  busy: string | null;
  disabled: boolean;
  onAct: Act;
}) {
  if (control.press) {
    return (
      <button
        onClick={() => onAct(control, 'toggle')}
        disabled={disabled}
        className={`${FIELD} shrink-0 hover:bg-gray-100 dark:hover:bg-gray-700`}
      >
        {label}
      </button>
    );
  }

  // A source list reads as a mode list, but a playing media player's state is
  // never one of its sources, so nothing is preselected.
  const selected = control.options.includes(control.state) ? control.state : '';

  // Not a chain: a vacuum is a switch that also has a speed, and picking one
  // of the two would cost the user the other.
  return (
    <>
      {control.options.length > 0 && (
        <select
          value={selected}
          disabled={disabled}
          aria-label={label}
          onChange={(e) => onAct(control, 'set', undefined, e.target.value)}
          className={`${FIELD} shrink-0 max-w-32`}
        >
          {selected === '' && <option value="">Choose…</option>}
          {control.options.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      )}

      {control.number && (
        <input
          type="number"
          defaultValue={control.state}
          disabled={disabled}
          aria-label={label}
          onChange={(e) => onAct(control, 'set', Number(e.target.value))}
          className={`${FIELD} shrink-0 w-20`}
        />
      )}

      {control.toggle && (
        <Toggle
          on={control.on}
          disabled={disabled}
          busy={busy === control.entity_id}
          label={label}
          onClick={() => onAct(control, 'toggle')}
        />
      )}
    </>
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
