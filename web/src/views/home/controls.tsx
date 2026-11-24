// The small controls a device can carry. Shared by the dashboard tile and the
// Smart home list so a thermostat or a dropdown is drawn the same everywhere.
import { useState } from 'react';
import { Minus, Plus } from 'lucide-react';
import type { Control } from '../../api';
import type { Act } from '../../lib/devices';
import { Switch } from '../../components/ui';

// Degrees per tap on a thermostat. Home Assistant refuses a value outside the
// device's own limits, and the refusal is shown like any other device error.
const TEMPERATURE_STEP = 0.5;

const FIELD =
  'text-xs rounded-lg px-2.5 py-1.5 border border-border bg-surface text-ink disabled:opacity-40';

export function StepButton({
  label, disabled, onClick, children,
}: { label: string; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="w-7 h-7 rounded-full border border-border text-muted flex items-center justify-center disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export function DomainChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 px-2.5 py-1 rounded-full border text-xs whitespace-nowrap"
      style={{
        borderColor: active ? 'var(--color-teal)' : 'var(--color-border)',
        color: active ? 'var(--color-teal)' : 'var(--color-muted)',
        background: active ? 'var(--color-teal-soft)' : 'transparent',
      }}
    >
      {label}
    </button>
  );
}

export function ThermostatSteps({
  control, label, disabled, onAct,
}: { control: Control; label: string; disabled: boolean; onAct: Act }) {
  if (control.target === null) return null;
  const target = control.target;
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <StepButton label={`Colder: ${label}`} disabled={disabled} onClick={() => onAct(control, 'set', target - TEMPERATURE_STEP)}>
        <Minus size={13} />
      </StepButton>
      <span className="text-sm font-semibold tabular-nums">{target.toFixed(1)}°</span>
      <StepButton label={`Warmer: ${label}`} disabled={disabled} onClick={() => onAct(control, 'set', target + TEMPERATURE_STEP)}>
        <Plus size={13} />
      </StepButton>
    </div>
  );
}

/** A brightness, position or volume. Sends once the user lets go: dragging
 * fires continuously and every step would be a command to the device. */
export function LevelSlider({
  control, label, disabled, onAct,
}: { control: Control; label: string; disabled: boolean; onAct: Act }) {
  const [draft, setDraft] = useState<number | null>(null);
  const shown = draft ?? control.level ?? 100;

  const commit = async () => {
    if (draft === null) return;
    // act() resolves after the panel reloads, so the slider never snaps back.
    await onAct(control, 'on', draft);
    setDraft(null);
  };

  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={0}
        max={100}
        value={shown}
        disabled={disabled}
        aria-label={`${label} level`}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        className="flex-1 accent-accent"
      />
      <span className="w-10 text-right text-xs tabular-nums text-muted">{shown}%</span>
    </div>
  );
}

export function NumberField({
  control, label, disabled, onAct,
}: { control: Control; label: string; disabled: boolean; onAct: Act }) {
  const send = (raw: string) => {
    const value = Number(raw);
    if (raw.trim() !== '' && Number.isFinite(value) && raw !== control.state) onAct(control, 'set', value);
  };
  return (
    <input
      // The key re-seeds the box when the device reports a new value.
      key={control.state}
      type="number"
      defaultValue={control.state}
      disabled={disabled}
      aria-label={label}
      onBlur={(e) => send(e.target.value)}
      onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      className={`${FIELD} shrink-0 w-20`}
    />
  );
}

export function OptionSelect({
  control, label, disabled, onAct,
}: { control: Control; label: string; disabled: boolean; onAct: Act }) {
  // A source list reads as a mode list, but a playing media player's state is
  // never one of its sources, so nothing is preselected.
  const selected = control.options.includes(control.state) ? control.state : '';
  return (
    <select
      value={selected}
      disabled={disabled}
      aria-label={label}
      onChange={(e) => onAct(control, 'set', undefined, e.target.value)}
      className={`${FIELD} shrink-0 max-w-40`}
    >
      {selected === '' && <option value="">Choose…</option>}
      {control.options.map((name) => (
        <option key={name} value={name}>{name}</option>
      ))}
    </select>
  );
}

/** Whatever one entity is: a press button, a mode list, a number, a switch. */
export function ControlWidget({
  control, label, disabled, onAct, onToggle,
}: {
  control: Control;
  label: string;
  disabled: boolean;
  onAct: Act;
  onToggle: (control: Control) => void;
}) {
  if (control.press) {
    return (
      <button
        type="button"
        onClick={() => onAct(control, 'toggle')}
        disabled={disabled}
        className={`${FIELD} shrink-0 hover:bg-page`}
      >
        {label}
      </button>
    );
  }

  // Not a chain: a vacuum is a switch that also has a speed, and showing one
  // of the two would cost the user the other.
  return (
    <>
      {control.options.length > 0 && (
        <OptionSelect control={control} label={label} disabled={disabled} onAct={onAct} />
      )}
      {control.number && <NumberField control={control} label={label} disabled={disabled} onAct={onAct} />}
      {control.toggle && (
        <Switch checked={control.on} disabled={disabled} onChange={() => onToggle(control)} label={label} />
      )}
    </>
  );
}
