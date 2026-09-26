import type { Control, Device, DevicesPanel } from '../api'

/** Which widget a domain draws as, in the order the design decides it: locks
 *  and vacuums are never generic switches, whatever flags they also carry. */
export type DeviceShape =
  | 'lock'
  | 'vacuum'
  | 'cover'
  | 'climate'
  | 'toggle-level'
  | 'toggle'
  | 'press'
  | 'options'
  | 'number'
  | 'plain'

export function shapeFor(control: Control): DeviceShape {
  if (control.domain === 'lock' || control.domain === 'alarm_control_panel') return 'lock'
  if (control.domain === 'vacuum') return 'vacuum'
  if (control.domain === 'cover' || control.domain === 'valve') return 'cover'
  if (control.domain === 'climate' || control.domain === 'water_heater') return 'climate'
  if (control.press) return 'press'
  if (control.toggle) return control.slider ? 'toggle-level' : 'toggle'
  if (control.options.length > 0) return 'options'
  if (control.number) return 'number'
  return 'plain'
}

const DOMAIN_LABELS: Record<string, string> = {
  light: 'Light',
  switch: 'Switch',
  fan: 'Fan',
  cover: 'Blinds',
  valve: 'Valve',
  lock: 'Lock',
  climate: 'Climate',
  water_heater: 'Water heater',
  media_player: 'Media',
  vacuum: 'Vacuum',
  lawn_mower: 'Mower',
  scene: 'Scene',
  script: 'Script',
  automation: 'Automation',
  button: 'Button',
  alarm_control_panel: 'Alarm',
  humidifier: 'Humidifier',
}

export function domainLabel(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain.charAt(0).toUpperCase() + domain.slice(1)
}

export function cap(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1).replace(/_/g, ' ') : text
}

/** The state line under a device's name — one rule for every domain: what
 *  Home Assistant reports, plus a level or a setpoint when there is one. */
export function stateText(control: Control, shape: DeviceShape): string {
  switch (shape) {
    case 'cover':
      if (control.level === null) return cap(control.state)
      if (control.level <= 0) return 'Closed'
      if (control.level >= 100) return 'Open'
      return `Open ${control.level}%`
    case 'climate':
      return control.current !== null
        ? `Now ${control.current}° · ${cap(control.state)}`
        : cap(control.state)
    case 'lock':
      return control.on ? 'Unlocked' : 'Locked'
    case 'toggle-level':
      return control.on && control.level !== null
        ? `${cap(control.state)} · ${control.level}%`
        : cap(control.state)
    default:
      return cap(control.state)
  }
}

/** Accent when the device is "on" in the broadest sense — playing, unlocked,
 *  cleaning, lit — since home_assistant.py already folds all of that into one
 *  boolean per domain. */
export function stateColor(control: Control): 'text-accent' | 'text-muted' {
  return control.on ? 'text-accent' : 'text-muted'
}

/** One tap's worth of action for a Home tile — the sensible default per
 *  domain, since a tile has room for exactly one gesture. Rooms screen cards
 *  use their own per-shape buttons instead. */
export function primaryAction(control: Control): string {
  switch (control.domain) {
    case 'cover':
    case 'valve':
      return control.level !== null && control.level > 0 ? 'close' : 'open'
    case 'lock':
    case 'alarm_control_panel':
      return control.on ? 'lock' : 'unlock'
    case 'vacuum':
      return control.on ? 'dock' : 'start'
    default:
      return control.press ? 'on' : 'toggle'
  }
}

/** The confirm sheet's question for a device action — phrased for the verb,
 *  not the entity id. */
export function confirmPhrase(action: string, name: string, currentlyOn: boolean): string {
  switch (action) {
    case 'toggle':
      return `Turn ${currentlyOn ? 'off' : 'on'} ${name}?`
    case 'lock':
      return `Lock ${name}?`
    case 'unlock':
      return `Unlock ${name}?`
    case 'dock':
      return `Send ${name} to dock?`
    case 'start':
      return `Start ${name}?`
    case 'open':
      return `Open ${name}?`
    case 'close':
      return `Close ${name}?`
    default:
      return `${cap(action)} ${name}?`
  }
}

/** Finds one device's primary control by entity id, searching every room —
 *  a Home tile only knows the id it was configured with. */
export function findControl(
  panel: DevicesPanel | null,
  entityId: string,
): { device: Device; control: Control } | null {
  for (const area of panel?.areas ?? []) {
    for (const device of area.devices) {
      if (device.primary.entity_id === entityId) return { device, control: device.primary }
    }
  }
  return null
}
