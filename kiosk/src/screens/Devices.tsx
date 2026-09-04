import { useEffect, useState } from 'react'
import { Lightbulb, Lock } from 'lucide-react'
import { controlDevice, fetchDevices } from '../api'
import type { Control, Device, DevicesPanel } from '../api'

// Someone else flips a switch, or an automation runs. Long enough not to
// hammer Home Assistant from a screen left open all day.
const REFRESH_MS = 30 * 1000

// Home Assistant will happily report a hundred devices. A filter row is the
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
  lawn_mower: 'Mowers',
  button: 'Buttons',
}

function label(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain.replace(/_/g, ' ')
}

type Act = (control: Control, action: string, value?: number, option?: string) => void

/** Every controllable device in the house, one card each, grouped by room.
 *
 *  A card is a device, not an entity: a robot vacuum is a vacuum with a
 *  suction setting and three buttons, not six switches in a row. What a
 *  device reports — battery, filter life — is not here; the screen is for
 *  changing things, and asking is what the chat is for.
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

  const act: Act = async (control, action, value, option) => {
    setBusy(control.entity_id)
    setNote(null)
    const result = await controlDevice(control.entity_id, action, value, option)
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
    ...new Set(panel.areas.flatMap((a) => a.devices.map((d) => d.primary.domain))),
  ].sort()

  const areas = panel.areas
    .map((area) => ({
      ...area,
      devices: domain
        ? area.devices.filter((d) => d.primary.domain === domain)
        : area.devices,
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

function Card({
  device,
  busy,
  locksAllowed,
  onAct,
}: {
  device: Device
  busy: string | null
  locksAllowed: boolean
  onAct: Act
}) {
  const main = device.primary
  // A lock or a garage door is shown either way — hiding the front door makes
  // the screen look broken. It just refuses until config says otherwise.
  const blocked = main.guarded && !locksAllowed
  const disabled = busy === main.entity_id || !main.available || blocked

  return (
    // No list-row here: its contain-intrinsic-size guesses a uniform 84px row,
    // and a card carrying settings and buttons is several times that, so the
    // scroll height would jump on first paint. The list is short now anyway —
    // one card per device, not one row per entity.
    <div className="px-4 py-3 rounded-xl bg-surface border border-line">
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="t-body truncate flex items-center gap-1.5">
            {main.guarded && <Lock size={13} className="text-muted shrink-0" />}
            {device.name}
          </div>
          <div className="t-small text-muted truncate">
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
              className="w-full mt-2 accent-[var(--wony-accent)]"
            />
          )}
        </div>

        {main.press ? (
          <PressButton control={main} label={device.name} disabled={disabled} onAct={onAct} />
        ) : (
          main.toggle && (
            <Toggle
              on={main.on}
              disabled={disabled}
              busy={busy === main.entity_id}
              label={device.name}
              onPress={() => onAct(main, 'toggle')}
            />
          )
        )}
      </div>

      {/* The device's own modes, unlabelled: the card is already its name. */}
      {main.options.length > 0 && (
        <div className="mt-3">
          <Choices control={main} disabled={disabled} onAct={onAct} />
        </div>
      )}

      {device.extras.length > 0 && (
        <div className="mt-3 pt-3 border-t border-line flex flex-col gap-3">
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
  )
}

function Extra({
  control,
  busy,
  locksAllowed,
  onAct,
}: {
  control: Control
  busy: string | null
  locksAllowed: boolean
  onAct: Act
}) {
  const blocked = control.guarded && !locksAllowed
  const disabled = busy === control.entity_id || !control.available || blocked

  // A press button says what it does, so it needs no second label.
  if (control.press) {
    return (
      <div className="flex">
        <PressButton
          control={control}
          label={control.name}
          disabled={disabled}
          onAct={onAct}
        />
      </div>
    )
  }

  if (control.options.length > 0) {
    return (
      <div className="flex flex-col gap-2">
        <span className="t-small text-muted">{control.name}</span>
        <Choices control={control} disabled={disabled} onAct={onAct} />
      </div>
    )
  }

  if (control.number) {
    return (
      <div className="flex items-center gap-3">
        <span className="t-small text-muted min-w-0 truncate">{control.name}</span>
        <div className="ml-auto flex items-center gap-2 shrink-0">
          <Stepper
            label="−"
            disabled={disabled}
            onPress={() => onAct(control, 'set', Number(control.state) - 1)}
          />
          <span className="t-body w-16 text-center tabular-nums">{control.state}</span>
          <Stepper
            label="+"
            disabled={disabled}
            onPress={() => onAct(control, 'set', Number(control.state) + 1)}
          />
        </div>
      </div>
    )
  }

  if (control.toggle) {
    return (
      <div className="flex items-center gap-3">
        <span className="t-small text-muted min-w-0 truncate">{control.name}</span>
        <div className="ml-auto shrink-0">
          <Toggle
            on={control.on}
            disabled={disabled}
            busy={busy === control.entity_id}
            label={control.name}
            onPress={() => onAct(control, 'toggle')}
          />
        </div>
      </div>
    )
  }

  return null
}

/** A row of buttons, not a <select>: a native dropdown on a 7" touch screen
 *  opens a list too small to hit reliably. */
function Choices({
  control,
  disabled,
  onAct,
}: {
  control: Control
  disabled: boolean
  onAct: Act
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {control.options.map((option) => (
        <button
          key={option}
          onClick={() => onAct(control, 'set', undefined, option)}
          disabled={disabled}
          className={`px-4 py-2 rounded-xl border t-body active:scale-95 disabled:opacity-40 ${
            control.state === option
              ? 'border-accent text-accent'
              : 'border-line text-muted'
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  )
}

function PressButton({
  control,
  label,
  disabled,
  onAct,
}: {
  control: Control
  label: string
  disabled: boolean
  onAct: Act
}) {
  return (
    <button
      onClick={() => onAct(control, 'toggle')}
      disabled={disabled}
      className="press shrink-0 px-4 h-10 rounded-xl border border-line
                 t-body text-muted disabled:opacity-40"
    >
      {label}
    </button>
  )
}

function Stepper({
  label,
  disabled,
  onPress,
}: {
  label: string
  disabled: boolean
  onPress: () => void
}) {
  return (
    <button
      onClick={onPress}
      disabled={disabled}
      className="w-11 h-11 rounded-xl border border-line grid place-items-center
                 t-body active:scale-95 disabled:opacity-40"
    >
      {label}
    </button>
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
