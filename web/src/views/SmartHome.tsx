// The Smart home page: the same Home Assistant devices two ways. List is for
// everything a device can do; Map is for switching things where they are.
import { useEffect, useState } from 'react';
import { List, Map as MapIcon } from 'lucide-react';
import { fetchDeviceMap } from '../api';
import type { DeviceMap as DeviceMapData, MapPlacement } from '../api';
import { Resting } from '../components/ui';
import { useDevices } from '../lib/devices';
import { moduleHealthState, moduleMessage } from '../lib/moduleHealth';
import { useWony } from '../lib/wonyContext';
import { DeviceList } from './home/DeviceList';
import { DeviceMap } from './home/DeviceMap';

const REFRESH_MS = 15 * 1000;

type Mode = 'list' | 'map';

const MODES: { id: Mode; label: string; icon: typeof List }[] = [
  { id: 'list', label: 'List', icon: List },
  { id: 'map', label: 'Map', icon: MapIcon },
];

export function SmartHome({ mode }: { mode: string | null }) {
  const { health, settings } = useWony();
  if (health !== null && moduleHealthState('home_assistant', health) !== 'ok') {
    return <Resting title={moduleMessage('home_assistant', health, settings?.modules, 'Home Assistant')} />;
  }
  return <SmartHomeBody mode={mode} />;
}

function SmartHomeBody({ mode }: { mode: string | null }) {
  const devices = useDevices(REFRESH_MS);
  const { panel, error, loaded, note, setNote } = devices;
  const [map, setMap] = useState<DeviceMapData | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    fetchDeviceMap().then((result) => {
      if (result.ok) setMap(result.data);
      else setMapError(result.text);
    });
  }, []);

  // The map is the main view: with no image yet it shows how to make one.
  const view: Mode = mode === 'list' ? 'list' : 'map';

  const onPlacements = (placements: MapPlacement[]) =>
    setMap((prev) => (prev ? { ...prev, placements } : prev));

  let content;
  if (!panel) {
    content = <Resting title={!loaded ? 'Finding your devices…' : error || "Home Assistant isn't responding."} />;
  } else if (view === 'list') {
    content = <DeviceList panel={panel} devices={devices} placed={new Set(map?.placements.map((p) => p.entity_id))} />;
  } else if (view === 'map' && map) {
    content = <DeviceMap panel={panel} devices={devices} map={map} onMap={setMap} onPlacements={onPlacements} />;
  } else {
    content = <Resting title={mapError || 'Loading…'} />;
  }

  return (
    <div className="px-8 pb-8 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div role="tablist" aria-label="Smart home view" className="inline-flex gap-1 rounded-full border border-border bg-surface p-1">
          {MODES.map(({ id, label, icon: Icon }) => {
            const active = view === id;
            return (
              <button
                key={id}
                role="tab"
                type="button"
                aria-selected={active}
                onClick={() => {
                  location.hash = `home/${id}`;
                }}
                className="flex items-center gap-1.5 border-0 rounded-full px-3.5 py-1.5 text-sm font-semibold"
                style={{
                  background: active ? 'var(--color-pink-soft)' : 'transparent',
                  color: active ? 'var(--color-red)' : 'var(--color-body2)',
                }}
              >
                <Icon size={14} />
                {label}
              </button>
            );
          })}
        </div>
        {panel && error && <span className="text-xs text-muted">Could not refresh — showing the last known state.</span>}
      </div>

      {note && (
        <button type="button" onClick={() => setNote(null)} className="text-left text-xs text-red bg-pink-faint rounded-lg px-3 py-2 border-0">
          {note}
        </button>
      )}

      {content}
    </div>
  );
}
