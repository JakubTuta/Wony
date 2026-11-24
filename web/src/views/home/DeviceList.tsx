// List mode: every device by room, one row each. A row switches the device;
// opening it shows everything else it can do and what it reports.
import { useState } from 'react';
import { ChevronDown, Lock, MapPin, Search } from 'lucide-react';
import type { Control, Device, DevicesPanel } from '../../api';
import { CARD, SectionLabel, Switch } from '../../components/ui';
import { DeviceIcon } from '../../components/DeviceIcon';
import { domainLabel, stateText } from '../../lib/devices';
import type { Act, Devices } from '../../lib/devices';
import { ControlWidget, DomainChip, LevelSlider, NumberField, OptionSelect, ThermostatSteps } from './controls';

const LEVEL_LABELS: Record<string, string> = {
  light: 'Brightness',
  cover: 'Position',
  fan: 'Speed',
  media_player: 'Volume',
  humidifier: 'Humidity',
};

export function DeviceList({
  panel, devices, placed,
}: { panel: DevicesPanel; devices: Devices; placed: ReadonlySet<string> }) {
  const [query, setQuery] = useState('');
  const [domain, setDomain] = useState('');
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());

  const domains = [...new Set(panel.areas.flatMap((a) => a.devices.map((d) => d.primary.domain)))].sort();
  const needle = query.trim().toLowerCase();
  const areas = panel.areas
    .map((area) => ({
      name: area.name || 'Elsewhere',
      devices: area.devices.filter(
        (d) =>
          (!domain || d.primary.domain === domain) &&
          (!needle || `${d.name} ${area.name}`.toLowerCase().includes(needle)),
      ),
    }))
    .filter((area) => area.devices.length > 0);

  const flip = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  if (panel.areas.length === 0) {
    return <span className="text-sm text-muted">Home Assistant has no devices Wony can control.</span>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 min-w-[220px]">
          <Search size={14} className="text-muted shrink-0" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a device or room"
            aria-label="Find a device or room"
            className="flex-1 min-w-0 bg-transparent border-0 outline-none text-sm text-ink"
          />
        </label>
        {domains.length > 1 && (
          <div className="flex gap-1.5 flex-wrap">
            <DomainChip label="All" active={domain === ''} onClick={() => setDomain('')} />
            {domains.map((d) => (
              <DomainChip key={d} label={domainLabel(d)} active={domain === d} onClick={() => setDomain(d)} />
            ))}
          </div>
        )}
      </div>

      {areas.length === 0 ? (
        <span className="text-sm text-muted">
          {needle ? `Nothing matches "${query.trim()}".` : 'Nothing of that kind here.'}
        </span>
      ) : (
        areas.map((area) => (
          <section key={area.name} className="flex flex-col gap-2">
            <SectionLabel>
              {area.name} <span className="font-mono text-[11px] opacity-70">{area.devices.length}</span>
            </SectionLabel>
            <div className="flex flex-col gap-2">
              {area.devices.map((device) => (
                <DeviceRow
                  key={device.primary.entity_id}
                  device={device}
                  devices={devices}
                  isOpen={open.has(device.primary.entity_id)}
                  onFlip={() => flip(device.primary.entity_id)}
                  onMap={placed.has(device.primary.entity_id)}
                />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function DeviceRow({
  device, devices, isOpen, onFlip, onMap,
}: { device: Device; devices: Devices; isOpen: boolean; onFlip: () => void; onMap: boolean }) {
  const { busy, act, toggle, locksAllowed } = devices;
  const main = device.primary;
  const disabled = busy.has(main.entity_id) || !main.available || (main.guarded && !locksAllowed);

  return (
    <div className={`${CARD} overflow-hidden`}>
      <div className="flex items-center gap-3 px-3.5 py-3">
        <button
          type="button"
          aria-expanded={isOpen}
          aria-label={`${device.name}, ${isOpen ? 'hide' : 'show'} details`}
          onClick={onFlip}
          className="flex items-center gap-3 flex-1 min-w-0 p-0 border-0 bg-transparent text-left text-ink cursor-pointer"
        >
          <span
            className="w-9 h-9 shrink-0 rounded-full flex items-center justify-center"
            style={{
              background: main.on ? 'var(--color-teal-soft)' : 'var(--color-page)',
              color: main.on ? 'var(--color-teal)' : 'var(--color-muted)',
            }}
          >
            <DeviceIcon control={main} />
          </span>
          <span className="flex flex-col gap-px min-w-0">
            <span className="text-sm font-semibold flex items-center gap-1.5 truncate">
              {main.guarded && <Lock size={11} className="text-muted shrink-0" />}
              <span className="truncate">{device.name}</span>
              {onMap && <MapPin size={11} className="text-muted shrink-0" aria-label="On the map" />}
            </span>
            <span className="text-xs text-muted truncate">{stateText(main, locksAllowed)}</span>
          </span>
        </button>

        <ThermostatSteps control={main} label={device.name} disabled={disabled} onAct={act} />
        {main.press && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => act(main, 'toggle')}
            className="shrink-0 text-xs font-semibold rounded-lg px-3 py-1.5 border-0 bg-teal-soft text-teal disabled:opacity-40"
          >
            Run
          </button>
        )}
        {main.toggle && (
          <Switch checked={main.on} disabled={disabled} onChange={() => toggle(main, device.name)} label={device.name} />
        )}
        <button
          type="button"
          tabIndex={-1}
          aria-hidden
          onClick={onFlip}
          className="shrink-0 p-1 border-0 bg-transparent text-muted cursor-pointer"
        >
          <ChevronDown size={16} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </button>
      </div>

      {isOpen && <DeviceDetails device={device} devices={devices} />}
    </div>
  );
}

function DeviceDetails({ device, devices }: { device: Device; devices: Devices }) {
  const { busy, act, toggle, locksAllowed } = devices;
  const main = device.primary;
  const blocked = (c: Control) => busy.has(c.entity_id) || !c.available || (c.guarded && !locksAllowed);
  const hasMore =
    main.slider || main.options.length > 0 || main.number || device.extras.length > 0 || device.readings.length > 0;

  return (
    <div className="border-t border-divider px-3.5 py-3 flex flex-col gap-3">
      {main.slider && (
        <ControlRow label={LEVEL_LABELS[main.domain] ?? 'Level'} wide>
          <LevelSlider control={main} label={device.name} disabled={blocked(main)} onAct={act} />
        </ControlRow>
      )}
      {main.options.length > 0 && (
        <ControlRow label="Mode">
          <OptionSelect control={main} label={`${device.name} mode`} disabled={blocked(main)} onAct={act} />
        </ControlRow>
      )}
      {main.number && (
        <ControlRow label="Value">
          <NumberField control={main} label={device.name} disabled={blocked(main)} onAct={act} />
        </ControlRow>
      )}

      {device.extras.length > 0 && (
        <div className="grid gap-x-6 gap-y-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
          {device.extras.map((extra) => (
            <ExtraControl key={extra.entity_id} control={extra} disabled={blocked(extra)} act={act} onToggle={(c) => toggle(c, c.name)} />
          ))}
        </div>
      )}

      {device.readings.length > 0 && (
        <dl className="m-0 grid gap-x-6 gap-y-1" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
          {device.readings.map((reading, i) => (
            <div key={`${reading.name}-${i}`} className="flex justify-between gap-3 text-xs">
              <dt className="text-muted truncate">{reading.name}</dt>
              <dd className="m-0 font-semibold tabular-nums text-right">{reading.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {!hasMore && <span className="text-xs text-muted">Nothing else to set on this device.</span>}
      <span className="font-mono text-[11px] text-muted break-all">{main.entity_id}</span>
    </div>
  );
}

function ControlRow({ label, wide, children }: { label: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <div className={`flex items-center gap-3 ${wide ? '' : 'justify-between'}`}>
      <span className="w-24 shrink-0 text-xs text-muted truncate">{label}</span>
      <div className={`flex items-center gap-2 ${wide ? 'flex-1 min-w-0' : ''}`}>{children}</div>
    </div>
  );
}

function ExtraControl({
  control, disabled, act, onToggle,
}: { control: Control; disabled: boolean; act: Act; onToggle: (control: Control) => void }) {
  // A press button already says what it does in its own label.
  if (control.press) {
    return (
      <div>
        <ControlWidget control={control} label={control.name} disabled={disabled} onAct={act} onToggle={onToggle} />
      </div>
    );
  }
  if (control.slider) {
    return (
      <div className="flex items-center gap-3 col-span-full">
        <span className="w-24 shrink-0 text-xs text-muted truncate">{control.name}</span>
        <div className="flex-1 min-w-0">
          <LevelSlider control={control} label={control.name} disabled={disabled} onAct={act} />
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-2 min-w-0">
      <span className="text-xs text-muted truncate">{control.name}</span>
      <div className="flex items-center gap-2 shrink-0">
        <ControlWidget control={control} label={control.name} disabled={disabled} onAct={act} onToggle={onToggle} />
      </div>
    </div>
  );
}
