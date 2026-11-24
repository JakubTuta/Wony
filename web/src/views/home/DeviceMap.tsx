// Map mode: devices as tappable markers on a picture of the home.
// Viewing is one tap to switch a device. Editing is where the user uploads the
// picture and puts each device where it is. Positions are fractions (0-1) of
// the picture, so they hold at any window size and across a replaced image.
import { useEffect, useRef, useState } from 'react';
import { Check, Loader2, Lock, Pencil, Search, Trash2, X } from 'lucide-react';
import { deleteDeviceMap, saveMapPlacements } from '../../api';
import type { Control, Device, DeviceMap as DeviceMapData, DevicesPanel, MapPlacement } from '../../api';
import { Button, CARD, Modal } from '../../components/ui';
import { DeviceIcon } from '../../components/DeviceIcon';
import { stateText } from '../../lib/devices';
import type { Devices } from '../../lib/devices';
import { MapStart } from './MapStart';
import { IMAGE_TYPES, useMapUpload } from './mapUpload';

// Pixels a press must travel before it counts as a drag, so a tap with a
// shaky finger is still a tap.
const DRAG_THRESHOLD = 5;
const SAVE_DELAY_MS = 400;
const NUDGE = 0.01;
const TIP_KEY = 'wony.home.mapTip';

type MapImage = NonNullable<DeviceMapData['image']>;
type SaveState = 'idle' | 'saving' | 'saved' | 'error';

// Only devices a tap can operate go on the map; the rest live in the list.
const tappable = (control: Control) => control.toggle || control.press;

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

function fractionIn(rect: DOMRect, clientX: number, clientY: number) {
  return { x: clamp01((clientX - rect.left) / rect.width), y: clamp01((clientY - rect.top) / rect.height) };
}

function isInside(rect: DOMRect, clientX: number, clientY: number) {
  return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
}

/** Follows one pointer until it lifts. `dragged` is false for a plain tap. */
function trackPointer(
  start: { clientX: number; clientY: number },
  on: { move: (e: PointerEvent) => void; end: (e: PointerEvent, dragged: boolean) => void; cancel: () => void },
) {
  let dragged = false;
  const move = (e: PointerEvent) => {
    if (!dragged && Math.hypot(e.clientX - start.clientX, e.clientY - start.clientY) < DRAG_THRESHOLD) return;
    dragged = true;
    on.move(e);
  };
  const stop = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    window.removeEventListener('pointercancel', cancel);
  };
  const up = (e: PointerEvent) => {
    stop();
    on.end(e, dragged);
  };
  const cancel = () => {
    stop();
    on.cancel();
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
  window.addEventListener('pointercancel', cancel);
}

function devicesById(panel: DevicesPanel): Map<string, Device> {
  const byId = new Map<string, Device>();
  for (const area of panel.areas) {
    for (const device of area.devices) byId.set(device.primary.entity_id, device);
  }
  return byId;
}

function readTip(): boolean {
  try {
    return localStorage.getItem(TIP_KEY) === null;
  } catch {
    return false;
  }
}

function dismissTip() {
  try {
    localStorage.setItem(TIP_KEY, '1');
  } catch {
    // Private mode: the tip just shows again next time.
  }
}

export function DeviceMap(props: {
  panel: DevicesPanel;
  devices: Devices;
  map: DeviceMapData;
  onMap: (map: DeviceMapData) => void;
  onPlacements: (placements: MapPlacement[]) => void;
}) {
  const { map, onMap } = props;
  if (!map.image) return <MapStart onUploaded={onMap} />;
  return <MapBoard {...props} image={map.image} />;
}

function Marker({
  x, y, device, editing, busy, locksAllowed, dragging, onTap, onRemove, onDragStart, onKey,
}: {
  x: number;
  y: number;
  /** Undefined when the device is no longer in Home Assistant. */
  device: Device | undefined;
  editing: boolean;
  busy: boolean;
  locksAllowed: boolean;
  dragging: boolean;
  onTap: () => void;
  onRemove: () => void;
  onDragStart: (e: React.PointerEvent) => void;
  onKey: (e: React.KeyboardEvent) => void;
}) {
  const control = device?.primary;
  const on = control?.on ?? false;
  const dead = !control || !control.available;
  const name = device?.name ?? 'Missing device';
  const label = control
    ? `${name}, ${stateText(control, locksAllowed)}`
    : 'Not in Home Assistant any more. Edit the map to remove it.';

  return (
    <div
      className="absolute w-10 h-10"
      style={{ left: `${x * 100}%`, top: `${y * 100}%`, transform: 'translate(-50%, -50%)', zIndex: dragging ? 30 : 10 }}
    >
      <button
        type="button"
        title={label}
        aria-label={label}
        disabled={!editing && !(control && tappable(control))}
        onClick={(e) => {
          // Editing never switches a device, and a click on a marker must not
          // also place the armed one underneath it.
          e.stopPropagation();
          if (!editing) onTap();
        }}
        onPointerDown={editing ? onDragStart : undefined}
        onKeyDown={editing ? onKey : undefined}
        className="relative w-10 h-10 rounded-full p-0 flex items-center justify-center shadow-md disabled:cursor-default"
        style={{
          background: on ? 'var(--color-accent)' : 'var(--color-surface)',
          color: on ? 'var(--color-on-accent)' : 'var(--color-muted)',
          border: `2px ${dead ? 'dashed' : 'solid'} ${on ? 'var(--color-accent)' : 'var(--color-border)'}`,
          opacity: dead && !editing ? 0.55 : 1,
          outline: editing ? '2px dashed var(--color-teal)' : undefined,
          outlineOffset: 2,
          cursor: editing ? (dragging ? 'grabbing' : 'grab') : 'pointer',
          touchAction: editing ? 'none' : 'manipulation',
        }}
      >
        {busy ? (
          <Loader2 size={18} className="animate-spin" />
        ) : control ? (
          <DeviceIcon control={control} />
        ) : (
          <span className="text-base font-bold">?</span>
        )}
        {control?.guarded && (
          <span className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-surface border border-border text-muted flex items-center justify-center">
            <Lock size={9} />
          </span>
        )}
      </button>

      <span className="absolute top-full left-1/2 -translate-x-1/2 mt-1 max-w-[140px] truncate whitespace-nowrap rounded-md bg-surface/90 px-1.5 py-0.5 text-[11px] font-semibold text-ink shadow-sm pointer-events-none">
        {name}
      </span>

      {editing && (
        <button
          type="button"
          aria-label={`Take ${name} off the map`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="absolute -top-2 -right-2 w-5 h-5 rounded-full p-0 border-0 bg-red text-white flex items-center justify-center shadow"
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}

/** The devices not on the map yet. Drag one out with a mouse, or tap it and
 * then tap the map, which is the way on a touch screen. */
function Tray({
  panel, placedIds, armed, onArm, onDragStart,
}: {
  panel: DevicesPanel;
  placedIds: ReadonlySet<string>;
  armed: string | null;
  onArm: (id: string) => void;
  onDragStart: (e: React.PointerEvent, id: string) => void;
}) {
  const [query, setQuery] = useState('');
  const needle = query.trim().toLowerCase();
  const all = panel.areas.flatMap((area) => area.devices).filter((d) => tappable(d.primary));
  const groups = panel.areas
    .map((area) => ({
      name: area.name || 'Elsewhere',
      devices: area.devices.filter(
        (d) =>
          tappable(d.primary) &&
          !placedIds.has(d.primary.entity_id) &&
          (!needle || `${d.name} ${area.name}`.toLowerCase().includes(needle)),
      ),
    }))
    .filter((group) => group.devices.length > 0);

  let empty = '';
  if (all.length === 0) empty = 'None of your devices can be switched with a tap.';
  else if (groups.length === 0) empty = needle ? `Nothing matches "${query.trim()}".` : 'Every device is on the map.';

  return (
    <aside
      className={`${CARD} p-3 flex flex-col gap-2.5 select-none`}
      style={{ flex: '0 1 260px', minWidth: 220, maxHeight: 'calc(100vh - 220px)' }}
    >
      <span className="text-[13px] font-semibold uppercase tracking-[0.08em] text-label-red">Devices to place</span>
      <label className="flex items-center gap-2 rounded-full border border-border bg-page px-3 py-1.5">
        <Search size={13} className="text-muted shrink-0" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a device"
          aria-label="Find a device to place"
          className="flex-1 min-w-0 bg-transparent border-0 outline-none text-sm text-ink"
        />
      </label>

      <div className="overflow-auto flex flex-col gap-3">
        {empty && <span className="text-xs text-muted">{empty}</span>}
        {groups.map((group) => (
          <div key={group.name} className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">{group.name}</span>
            {group.devices.map((device) => {
              const id = device.primary.entity_id;
              const isArmed = armed === id;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={isArmed}
                  onPointerDown={(e) => onDragStart(e, id)}
                  onClick={() => onArm(id)}
                  className="flex items-center gap-2.5 w-full text-left rounded-[10px] border px-2.5 py-2 text-sm text-ink cursor-grab"
                  style={{
                    borderColor: isArmed ? 'var(--color-teal)' : 'var(--color-border)',
                    background: isArmed ? 'var(--color-teal-soft)' : 'var(--color-surface)',
                  }}
                >
                  <DeviceIcon control={device.primary} size={16} className="text-muted shrink-0" />
                  <span className="truncate">{device.name}</span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </aside>
  );
}

function MapBoard({
  panel, devices, map, image, onMap, onPlacements,
}: {
  panel: DevicesPanel;
  devices: Devices;
  map: DeviceMapData;
  image: MapImage;
  onMap: (map: DeviceMapData) => void;
  onPlacements: (placements: MapPlacement[]) => void;
}) {
  const { placements } = map;
  const byId = devicesById(panel);
  const placedIds = new Set(placements.map((p) => p.entity_id));

  // A map with nothing on it has only one useful thing to do.
  const [editing, setEditing] = useState(() => placements.length === 0);
  const [armed, setArmed] = useState<string | null>(null);
  const [ghost, setGhost] = useState<{ id: string; x: number; y: number } | null>(null);
  const [moving, setMoving] = useState<{ id: string; x: number; y: number } | null>(null);
  const [save, setSave] = useState<SaveState>('idle');
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [tip, setTip] = useState(false);

  const surface = useRef<HTMLDivElement>(null);
  const pending = useRef<MapPlacement[] | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const justDragged = useRef(false);
  const replace = useMapUpload(onMap);

  const flush = async () => {
    const next = pending.current;
    pending.current = null;
    if (!next) return;
    const result = await saveMapPlacements(next);
    setSave(result.ok ? 'saved' : 'error');
  };

  const change = (next: MapPlacement[]) => {
    onPlacements(next);
    pending.current = next;
    setSave('saving');
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, SAVE_DELAY_MS);
  };

  // Leaving the page must not lose the last drag.
  useEffect(
    () => () => {
      clearTimeout(timer.current);
      if (pending.current) saveMapPlacements(pending.current);
    },
    [],
  );

  useEffect(() => {
    if (!armed) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setArmed(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [armed]);

  const place = (id: string, x: number, y: number) =>
    change([...placements.filter((p) => p.entity_id !== id), { entity_id: id, x, y }]);
  const remove = (id: string) => change(placements.filter((p) => p.entity_id !== id));

  const placeAt = (id: string, e: { clientX: number; clientY: number }) => {
    const rect = surface.current?.getBoundingClientRect();
    if (!rect) return;
    const at = fractionIn(rect, e.clientX, e.clientY);
    place(id, at.x, at.y);
  };

  // Mouse and pen only: a touch drag would fight the page scroll, so touch
  // uses tap-then-tap instead.
  const dragFromTray = (e: React.PointerEvent, id: string) => {
    if (e.pointerType === 'touch' || e.button !== 0) return;
    trackPointer(e, {
      move: (ev) => setGhost({ id, x: ev.clientX, y: ev.clientY }),
      end: (ev, dragged) => {
        setGhost(null);
        if (!dragged) return;
        // The click that follows a drag must not also arm the tray item.
        justDragged.current = true;
        setTimeout(() => {
          justDragged.current = false;
        }, 0);
        const rect = surface.current?.getBoundingClientRect();
        if (rect && isInside(rect, ev.clientX, ev.clientY)) placeAt(id, ev);
      },
      cancel: () => setGhost(null),
    });
  };

  const armFromTray = (id: string) => {
    if (justDragged.current) return;
    setArmed((current) => (current === id ? null : id));
  };

  const dragMarker = (e: React.PointerEvent, id: string) => {
    if (e.button !== 0) return;
    trackPointer(e, {
      move: (ev) => {
        const rect = surface.current?.getBoundingClientRect();
        if (rect) setMoving({ id, ...fractionIn(rect, ev.clientX, ev.clientY) });
      },
      end: (ev, dragged) => {
        setMoving(null);
        if (dragged) placeAt(id, ev);
      },
      cancel: () => setMoving(null),
    });
  };

  // Keyboard users get the same edits: arrows nudge, Delete takes it off.
  const keyMarker = (e: React.KeyboardEvent, placement: MapPlacement) => {
    const step: Record<string, [number, number]> = {
      ArrowLeft: [-NUDGE, 0], ArrowRight: [NUDGE, 0], ArrowUp: [0, -NUDGE], ArrowDown: [0, NUDGE],
    };
    if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      remove(placement.entity_id);
    } else if (step[e.key]) {
      e.preventDefault();
      const [dx, dy] = step[e.key];
      place(placement.entity_id, clamp01(placement.x + dx), clamp01(placement.y + dy));
    }
  };

  const onSurfaceClick = (e: React.MouseEvent) => {
    if (!editing || !armed) return;
    placeAt(armed, e);
    setArmed(null);
  };

  const finishEditing = () => {
    setEditing(false);
    setArmed(null);
    if (placements.length > 0 && readTip()) setTip(true);
  };

  const removeMap = async () => {
    const result = await deleteDeviceMap();
    setConfirmRemove(false);
    if (result.ok) onMap({ image: null, placements: [] });
    else setRemoveError(result.text);
  };

  const armedName = armed ? byId.get(armed)?.name : undefined;
  let coach = 'Drag a marker to move it, or use × to take it off. Changes save automatically.';
  if (armedName) coach = `Now tap the map where "${armedName}" goes. Esc cancels.`;
  else if (placements.length === 0) {
    coach = 'Drag a device from the list onto the map. On a touch screen, tap a device first, then tap the map.';
  }

  const saveText = { idle: '', saving: 'Saving…', saved: 'Saved', error: 'Could not save. It will try again on your next change.' }[save];
  const error = replace.error ?? removeError;
  const ghostControl = ghost ? byId.get(ghost.id)?.primary : undefined;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-end gap-2 flex-wrap">
        {editing ? (
          <>
            <span className="mr-auto text-xs" style={{ color: save === 'error' ? 'var(--color-red)' : 'var(--color-muted)' }}>
              {saveText}
            </span>
            <label className="border-0 rounded-[9px] px-4 py-2 text-sm font-semibold bg-teal-soft text-teal cursor-pointer focus-within:outline-2">
              {replace.uploading ? 'Uploading…' : 'Replace image'}
              <input
                type="file"
                accept={IMAGE_TYPES}
                className="sr-only"
                disabled={replace.uploading}
                onChange={(e) => {
                  replace.upload(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
            </label>
            <Button variant="ghost" className="inline-flex items-center gap-1.5" onClick={() => setConfirmRemove(true)}>
              <Trash2 size={14} /> Remove map
            </Button>
            <Button className="inline-flex items-center gap-1.5" onClick={finishEditing}>
              <Check size={14} /> Done
            </Button>
          </>
        ) : (
          <Button variant="soft" className="inline-flex items-center gap-1.5" onClick={() => setEditing(true)}>
            <Pencil size={14} /> Edit map
          </Button>
        )}
      </div>

      {editing && (
        <div role="status" className="flex items-start gap-2.5 rounded-xl bg-teal-soft px-3.5 py-2.5 text-sm text-teal">
          <Pencil size={15} className="mt-0.5 shrink-0" />
          <span>{coach}</span>
        </div>
      )}
      {!editing && tip && (
        <div className="flex items-start justify-between gap-3 rounded-xl bg-teal-soft px-3.5 py-2.5 text-sm text-teal">
          <span>Tap a device to switch it. Brightness, modes and more are in List.</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => {
              dismissTip();
              setTip(false);
            }}
            className="border-0 bg-transparent p-0 text-teal cursor-pointer"
          >
            <X size={14} />
          </button>
        </div>
      )}
      {error && <span className="text-sm text-red">{error}</span>}

      <div className="flex gap-4 items-start flex-wrap">
        <div className="min-w-0" style={{ flex: '1 1 420px' }}>
          <div
            ref={surface}
            onClick={onSurfaceClick}
            className="relative mx-auto select-none"
            style={{
              aspectRatio: `${image.width} / ${image.height}`,
              // As big as fits on screen without scrolling, never narrower than a phone.
              width: `min(100%, max(320px, calc((100vh - 300px) * ${image.width / image.height})))`,
              cursor: armed ? 'crosshair' : undefined,
            }}
          >
            <img
              src={image.url}
              alt="Floor plan of your home"
              draggable={false}
              className="absolute inset-0 w-full h-full rounded-[14px] border border-border bg-surface"
            />

            {placements.map((p) => {
              const at = moving?.id === p.entity_id ? moving : p;
              const device = byId.get(p.entity_id);
              return (
                <Marker
                  key={p.entity_id}
                  x={at.x}
                  y={at.y}
                  device={device}
                  editing={editing}
                  busy={devices.busy.has(p.entity_id)}
                  locksAllowed={devices.locksAllowed}
                  dragging={moving?.id === p.entity_id}
                  onTap={() => device && devices.toggle(device.primary, device.name)}
                  onRemove={() => remove(p.entity_id)}
                  onDragStart={(e) => dragMarker(e, p.entity_id)}
                  onKey={(e) => keyMarker(e, p)}
                />
              );
            })}

            {!editing && placements.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className={`${CARD} px-6 py-5 flex flex-col items-center gap-3 text-center shadow-md`}>
                  <span className="text-sm font-semibold">No devices on this map yet</span>
                  <Button onClick={() => setEditing(true)}>Add devices</Button>
                </div>
              </div>
            )}
          </div>
        </div>

        {editing && (
          <Tray panel={panel} placedIds={placedIds} armed={armed} onArm={armFromTray} onDragStart={dragFromTray} />
        )}
      </div>

      {ghost && ghostControl && (
        <div
          className="fixed z-50 pointer-events-none w-10 h-10 rounded-full bg-accent text-on-accent flex items-center justify-center shadow-lg"
          style={{ left: ghost.x, top: ghost.y, transform: 'translate(-50%, -50%)' }}
        >
          <DeviceIcon control={ghostControl} />
        </div>
      )}

      {confirmRemove && (
        <Modal onClose={() => setConfirmRemove(false)}>
          <span className="text-xl font-bold">Remove the map?</span>
          <span className="text-sm text-muted">
            The picture and the places you put devices are deleted. The devices themselves are not touched.
          </span>
          <div className="flex gap-2 justify-end mt-1.5">
            <Button variant="soft" onClick={() => setConfirmRemove(false)}>Cancel</Button>
            <Button onClick={removeMap}>Remove map</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
