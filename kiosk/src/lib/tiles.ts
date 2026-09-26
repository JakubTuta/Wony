import type { DevicesPanel, RoutineSummary } from '../api'
import { domainLabel } from './devices'

export interface TileDescriptor {
  id: string
  kind: string
  title: string
}

const STATIC_TILES: TileDescriptor[] = [
  { id: 'timer:10', kind: 'Timer', title: '10 minute timer' },
  { id: 'music', kind: 'Music', title: 'Play / pause' },
  { id: 'volume', kind: 'Volume', title: 'Volume' },
  { id: 'sleep', kind: 'Sleep', title: 'Sleep' },
]

/** Everything worth offering as a tile, built fresh from live data rather
 *  than a fixed list — a routine or a device the user just added must show up
 *  in "+ Add tile" without a code change. */
export function candidateTiles(
  routines: RoutineSummary[],
  devices: DevicesPanel | null,
): TileDescriptor[] {
  const out: TileDescriptor[] = []
  for (const r of routines) {
    out.push({ id: `routine:${r.name}`, kind: 'Routine', title: r.name })
  }
  for (const area of devices?.areas ?? []) {
    for (const device of area.devices) {
      out.push({
        id: `device:${device.primary.entity_id}`,
        kind: domainLabel(device.primary.domain),
        title: device.name,
      })
    }
  }
  out.push(...STATIC_TILES)
  return out
}

export function parseTileId(id: string): { kind: string; arg: string } {
  const i = id.indexOf(':')
  return i === -1 ? { kind: id, arg: '' } : { kind: id.slice(0, i), arg: id.slice(i + 1) }
}

/** Up to 6 tiles for a first run — whichever of these actually exist, in this
 *  order, so a house with no locks just gets a shorter starter grid instead of
 *  a dead tile. */
export function seedTiles(routines: RoutineSummary[], devices: DevicesPanel | null): string[] {
  const allDevices = (devices?.areas ?? []).flatMap((a) => a.devices)
  const byDomain = (domain: string) => allDevices.find((d) => d.primary.domain === domain)

  const out: string[] = []
  const light = byDomain('light') ?? byDomain('switch')
  if (light) out.push(`device:${light.primary.entity_id}`)
  const cover = byDomain('cover')
  if (cover) out.push(`device:${cover.primary.entity_id}`)
  const lock = byDomain('lock')
  if (lock) out.push(`device:${lock.primary.entity_id}`)
  for (const r of routines.slice(0, 2)) out.push(`routine:${r.name}`)
  out.push('timer:10')
  // Not 'music': the Now Playing card on the right is always on screen and
  // already has play/pause, so a tile for the same tap would be a second
  // button for one action. Volume has no control anywhere else.
  out.push('volume')
  return out.slice(0, 6)
}
