import { useEffect, useState } from 'react';
import { Lock } from 'lucide-react';
import { controlDevice, fetchPanel } from '../../api';
import type { Control, DevicesPanel } from '../../api';
import { useWony } from '../../lib/wonyContext';
import { Gated } from '../../components/ModuleGate';
import { CARD, SectionLabel, Switch } from '../../components/ui';

const PLACEHOLDER_DEVICES = ['Living room lamp', 'Kitchen switch', 'Thermostat'];

const REFRESH_MS = 30 * 1000;

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

function domainLabel(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain.replace(/_/g, ' ');
}

export function Home() {
  const { requestConfirm } = useWony();
  const [panel, setPanel] = useState<DevicesPanel | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [domain, setDomain] = useState('');
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      fetchPanel<DevicesPanel>('devices').then((r) => {
        setPanel(r.data);
        setFetchError(r.error);
        setLoaded(true);
      });
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  if (!panel) {
    return (
      <Gated
        blocked
        fullRow
        message={!loaded ? 'Finding your devices…' : fetchError || "Home Assistant isn't responding."}
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

  const act = async (control: Control, action: string, value?: number, option?: string) => {
    setBusy(control.entity_id);
    setNote(null);
    const result = await controlDevice(control.entity_id, action, value, option);
    const next = await fetchPanel<DevicesPanel>('devices');
    setPanel(next.data);
    setBusy(null);
    if (!result.ok) setNote(result.text);
  };

  const toggle = (control: Control, deviceName: string) => {
    const nextAction = control.on ? 'off' : 'on';
    const sig = `control_home_device(target="${deviceName.toLowerCase()}", action="${control.guarded ? (control.on ? 'lock' : 'unlock') : nextAction}")`;
    if (control.guarded) {
      if (!panel!.locks_allowed) {
        setNote('Locked off in config.yaml — set modules.home_assistant.allow_locks to change it.');
        return;
      }
      requestConfirm({
        title: `${control.on ? 'Unlock' : 'Lock'} ${deviceName.toLowerCase()}?`,
        sig,
        onConfirm: () => act(control, 'toggle'),
      });
      return;
    }
    act(control, 'toggle');
  };

  const domains = [...new Set(panel.areas.flatMap((a) => a.devices.map((d) => d.primary.domain)))].sort();
  const areas = panel.areas
    .map((area) => ({ ...area, devices: domain ? area.devices.filter((d) => d.primary.domain === domain) : area.devices }))
    .filter((area) => area.devices.length > 0);

  const allDevices = areas.flatMap((a) => a.devices);

  return (
    <div className={`${CARD} p-4.5 flex flex-col gap-2.5`} style={{ gridColumn: '1 / -1', minWidth: 0 }}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <SectionLabel>Home</SectionLabel>
        {domains.length > 1 && (
          <div className="flex gap-1.5 flex-wrap">
            <DomainChip label="All" active={domain === ''} onClick={() => setDomain('')} />
            {domains.map((d) => (
              <DomainChip key={d} label={domainLabel(d)} active={domain === d} onClick={() => setDomain(d)} />
            ))}
          </div>
        )}
      </div>

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
            const blocked = main.guarded && !panel.locks_allowed;
            const disabled = busy === main.entity_id || !main.available || blocked;
            const stateText = blocked
              ? 'Locked off in config.yaml'
              : !main.available
                ? 'Unavailable'
                : main.level !== null
                  ? `${main.state} · ${main.level}%`
                  : main.state;

            return (
              <div key={main.entity_id} className="flex items-center justify-between gap-2.5 px-3 py-2.5 rounded-[10px] bg-page">
                <div className="flex flex-col gap-px min-w-0">
                  <span className="text-sm font-semibold flex items-center gap-1.5 truncate">
                    {main.guarded && <Lock size={11} className="text-muted shrink-0" />}
                    {device.name}
                  </span>
                  <span className="text-xs text-muted truncate">{stateText}</span>
                </div>
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

function DomainChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
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
