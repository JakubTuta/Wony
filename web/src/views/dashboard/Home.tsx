import { useState } from 'react';
import { ArrowRight, Lock } from 'lucide-react';
import { Gated } from '../../components/ModuleGate';
import { CARD, SectionLabel, Switch } from '../../components/ui';
import { domainLabel, stateText, useDevices } from '../../lib/devices';
import { DomainChip, ThermostatSteps } from '../home/controls';

const PLACEHOLDER_DEVICES = ['Living room lamp', 'Kitchen switch', 'Thermostat'];

const REFRESH_MS = 30 * 1000;

export function Home() {
  const { panel, error, loaded, busy, note, setNote, act, toggle, locksAllowed } = useDevices(REFRESH_MS);
  const [domain, setDomain] = useState('');

  if (!panel) {
    return (
      <Gated
        blocked
        fullRow
        message={!loaded ? 'Finding your devices…' : error || "Home Assistant isn't responding."}
      >
        <div className={`${CARD} p-4.5 flex flex-col gap-2.5`} style={{ minWidth: 0, minHeight: 120 }}>
          <SectionLabel>Home</SectionLabel>
          <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
            {PLACEHOLDER_DEVICES.map((name) => (
              <div key={name} className="flex items-center justify-between gap-2.5 px-3 py-2.5 rounded-[10px] bg-page">
                <div className="flex flex-col gap-px min-w-0">
                  <span className="text-sm font-semibold truncate">{name}</span>
                  <span className="text-xs text-muted truncate">off</span>
                </div>
                <Switch checked={false} disabled onChange={() => {}} label={name} />
              </div>
            ))}
          </div>
        </div>
      </Gated>
    );
  }

  const domains = [...new Set(panel.areas.flatMap((a) => a.devices.map((d) => d.primary.domain)))].sort();
  const allDevices = panel.areas
    .flatMap((area) => area.devices)
    .filter((d) => !domain || d.primary.domain === domain);

  return (
    <div className={`${CARD} p-4.5 flex flex-col gap-2.5`} style={{ gridColumn: '1 / -1', minWidth: 0 }}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <SectionLabel>Home</SectionLabel>
          <a href="#home" className="flex items-center gap-1 text-xs font-semibold text-teal no-underline">
            Open Smart home <ArrowRight size={12} />
          </a>
        </div>
        {domains.length > 1 && (
          <div className="flex gap-1.5 flex-wrap">
            <DomainChip label="All" active={domain === ''} onClick={() => setDomain('')} />
            {domains.map((d) => (
              <DomainChip key={d} label={domainLabel(d)} active={domain === d} onClick={() => setDomain(d)} />
            ))}
          </div>
        )}
      </div>

      {error && <span className="text-xs text-muted">Could not refresh — showing the last known state.</span>}
      {note && (
        <button onClick={() => setNote(null)} className="text-left text-xs text-red bg-pink-faint rounded-lg px-3 py-2">
          {note}
        </button>
      )}

      {allDevices.length === 0 ? (
        <span className="text-sm text-muted">Nothing of that kind here.</span>
      ) : (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
          {allDevices.map((device) => {
            const main = device.primary;
            const disabled = busy.has(main.entity_id) || !main.available || (main.guarded && !locksAllowed);

            return (
              <div key={main.entity_id} className="flex items-center justify-between gap-2.5 px-3 py-2.5 rounded-[10px] bg-page">
                <div className="flex flex-col gap-px min-w-0">
                  <span className="text-sm font-semibold flex items-center gap-1.5 truncate">
                    {main.guarded && <Lock size={11} className="text-muted shrink-0" />}
                    {device.name}
                  </span>
                  <span className="text-xs text-muted truncate">{stateText(main, locksAllowed)}</span>
                </div>
                <ThermostatSteps control={main} label={device.name} disabled={disabled} onAct={act} />
                {main.toggle && (
                  <Switch checked={main.on} disabled={disabled} onChange={() => toggle(main, device.name)} label={device.name} />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
