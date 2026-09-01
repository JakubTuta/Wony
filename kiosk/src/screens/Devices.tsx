import { useEffect, useState } from 'react'
import { Lightbulb, Lock } from 'lucide-react'
import { controlDevice, fetchDevices } from '../api'
import type { Device, DevicesPanel } from '../api'

// Someone else flips a switch, or an automation runs. Long enough not to
// hammer Home Assistant from a screen left open all day.
const REFRESH_MS = 30 * 1000

// Home Assistant will happily report a hundred entities. A filter row is the
// difference between a usable screen and a very long scroll.
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
}

function label(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain.replace(/_/g, ' ')
}

/** Every controllable device in the house, grouped by room.
 *
 *  This used to ask the agent "which lights are on?" and read back a
 *  paragraph you could not press. The states were always structured, and
 *  Home Assistant was always one call away.
 */
export function Devices() {
  const [panel, setPanel] = useState<DevicesPanel | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [domain, setDomain] = useState<string>('')

  useEffect(() => {
    const load = () => {
      fetchDevices().then((result) => {
        setPanel(result.data)
        setError(result.error)
        setLoading(false)
      })
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [])

  const act = async (device: Device, action: string, brightness?: number) => {
    setBusy(device.entity_id)
    setNote(null)
    const result = await controlDevice(device.entity_id, action, brightness)
    // Home Assistant confirms the service call before the state settles, so
    // the list is re-read rather than guessed at.
    const next = await fetchDevices()
    setPanel(next.data)
    setBusy(null)
    if (!result.ok) setNote(result.text)
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="t-body text-muted">Finding your devices…</p>
      </div>
    )
  }

  if (error || !panel) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-2 px-8">
        <Lightbulb size={40} className="text-muted" />
        <p className="t-body text-muted">{error ?? 'No devices right now.'}</p>
      </div>
    )
  }

  const domains = [
    ...new Set(panel.areas.flatMap((a) => a.devices.map((d) => d.domain))),
  ].sort()

  const areas = panel.areas
    .map((area) => ({
      ...area,
      devices: domain ? area.devices.filter((d) => d.domain === domain) : area.devices,
    }))
    .filter((area) => area.devices.length > 0)

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {domains.length > 1 && (
        <div className="scroll-x flex gap-1.5 px-3 pt-3 shrink-0">
          <Chip label="All" active={domain === ''} onPress={() => setDomain('')} />
          {domains.map((name) => (
            <Chip
              key={name}
              label={label(name)}
              active={domain === name}
              onPress={() => setDomain(name)}
            />
          ))}
        </div>
      )}

      <div className="scroll-y flex-1 px-3 py-3 flex flex-col gap-5">
        {areas.length === 0 ? (
          <p className="t-body text-muted px-2">Nothing of that kind here.</p>
        ) : (
          areas.map((area) => (
            <div key={area.name || 'other'}>
              <div className="t-small text-muted uppercase tracking-wide px-2 pb-2">
                {area.name || 'Elsewhere'}
              </div>
              <div className="flex flex-col gap-1.5">
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

      {note && (
        <button
          onClick={() => setNote(null)}
          className="press mx-3 mb-3 px-4 py-3 rounded-xl bg-surface border border-warn
                     text-left shrink-0"
        >
          <p className="t-small text-warn whitespace-pre-wrap">{note}</p>
        </button>
      )}
    </div>
  )
}

function Chip({
  label,
  active,
  onPress,
}: {
  label: string
  active: boolean
  onPress: () => void
}) {
  return (
    <button
      onClick={onPress}
      className={`press shrink-0 px-4 h-10 rounded-full border t-small whitespace-nowrap ${
        active ? 'border-accent text-accent' : 'border-line text-muted bg-surface'
      }`}
    >
      {label}
    </button>
  )
}

function Row({
  device,
  busy,
  locksAllowed,
  onAct,
}: {
  device: Device
  busy: boolean
  locksAllowed: boolean
  onAct: (device: Device, action: string, brightness?: number) => void
}) {
  // A lock or a garage door is shown either way — hiding the front door makes
  // the screen look broken. It just refuses until config says otherwise.
  const blocked = device.guarded && !locksAllowed
  const disabled = busy || !device.available || blocked

  return (
    <div className="list-row flex items-center gap-3 px-4 py-3 rounded-xl bg-surface border border-line">
      <div className="flex-1 min-w-0">
        <div className="t-body truncate flex items-center gap-1.5">
          {device.guarded && <Lock size={13} className="text-muted shrink-0" />}
          {device.name}
        </div>
        <div className="t-small text-muted truncate">
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
            className="w-full mt-2 accent-[var(--wony-accent)]"
          />
        )}
      </div>

      <Toggle
        on={device.on}
        disabled={disabled}
        busy={busy}
        label={device.name}
        onPress={() => onAct(device, 'toggle')}
      />
    </div>
  )
}

function Toggle({
  on,
  disabled,
  busy,
  label,
  onPress,
}: {
  on: boolean
  disabled: boolean
  busy: boolean
  label: string
  onPress: () => void
}) {
  return (
    <button
      onClick={onPress}
      disabled={disabled}
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`press relative w-16 h-10 shrink-0 rounded-full border transition-colors
                  disabled:opacity-40 ${
                    on ? 'bg-accent border-accent' : 'bg-surface-2 border-line'
                  }`}
    >
      {/* left-1 is load-bearing: without it the knob has no horizontal anchor
          and falls back to its static position, which a button centres. The
          travel is the track's inner width minus both gaps and the knob
          itself — 64 - 2 border - 8 gaps - 28 knob = 26. */}
      <span
        className={`absolute top-1/2 left-1 w-7 h-7 rounded-full
                    -translate-y-1/2 transition-transform ${
                      on ? 'translate-x-6.5 bg-on-accent' : 'translate-x-0 bg-muted'
                    } ${busy ? 'opacity-50' : ''}`}
      />
    </button>
  )
}
