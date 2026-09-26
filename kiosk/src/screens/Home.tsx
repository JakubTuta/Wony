import { useEffect, useState } from 'react'
import { Music as MusicIcon, Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import {
  controlDevice,
  fetchDevices,
  fetchKioskTiles,
  fetchRoutines,
  invokeJob,
  saveKioskTiles,
} from '../api'
import type { Reminder } from '../api'
import { SleepSheet } from '../components/SleepSheet'
import { AddTileSheet } from '../components/AddTileSheet'
import {
  cap,
  confirmPhrase,
  findControl,
  primaryAction,
  shapeFor,
  stateText,
} from '../lib/devices'
import { signature } from '../lib/jobs'
import { candidateTiles, parseTileId, seedTiles } from '../lib/tiles'
import { upcomingTime } from '../lib/time'
import { useLive } from '../state/live-context'
import { useUi } from '../state/ui-context'
import { useWony } from '../state/wony-context'

interface ResolvedTile {
  id: string
  kindLabel: string
  title: string
  sub: string
  active: boolean
  onTap: () => void
}

function truncate(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text
}

export function Home({ editing }: { editing: boolean }) {
  const { config, runPrompt } = useWony()
  const { toast, confirm } = useUi()
  const live = useLive()
  const { reminders, devices, routines, music, agenda } = live

  const [tileIds, setTileIds] = useState<string[] | null | undefined>(undefined)
  const [addOpen, setAddOpen] = useState(false)
  const [sleepOpen, setSleepOpen] = useState(false)
  const [, setTick] = useState(0)

  const cols = config?.kiosk.home_columns ?? 3
  const confirmAllDevices = config?.kiosk.confirm_all_devices ?? false
  const locksAllowed = devices.data?.locks_allowed ?? false

  // First run: nobody has arranged a layout yet — seed one from whatever this
  // house actually has, using one-off fetches rather than the live poll state
  // so this only ever runs once, on mount.
  useEffect(() => {
    fetchKioskTiles().then(async (saved) => {
      if (saved !== null) {
        setTileIds(saved)
        return
      }
      const [devicesResult, routinesResult] = await Promise.all([fetchDevices(), fetchRoutines()])
      const seed = seedTiles(routinesResult.data?.routines ?? [], devicesResult.data)
      setTileIds(seed)
      saveKioskTiles(seed)
    })
  }, [])

  // Countdown text on a timer tile changes every second without the reminders
  // panel itself changing — this just forces those tiles to re-render.
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  const persist = (next: string[]) => {
    setTileIds(next)
    saveKioskTiles(next)
  }

  const removeTile = (id: string) => persist((tileIds ?? []).filter((t) => t !== id))
  const addTile = (id: string) => {
    persist([...(tileIds ?? []), id])
    setAddOpen(false)
  }

  const resolve = (id: string): ResolvedTile => {
    const { kind, arg } = parseTileId(id)

    if (kind === 'routine') {
      const routine = routines.data?.routines.find(
        (r) => r.name.toLowerCase() === arg.toLowerCase(),
      )
      const title = routine?.name ?? arg
      return {
        id,
        kindLabel: 'Routine',
        title,
        sub: routine ? truncate(routine.steps, 42) : 'Routine not found',
        active: false,
        onTap: () => {
          toast(`Running ${title}`)
          runPrompt(`run my ${title} routine`).then((res) => {
            if (!res.ok) toast(res.text || 'That did not work.')
          })
        },
      }
    }

    if (kind === 'device') {
      const found = findControl(devices.data, arg)
      if (!found) {
        return {
          id,
          kindLabel: 'Device',
          title: arg,
          sub: 'Unavailable',
          active: false,
          onTap: () => toast('That device is no longer available.'),
        }
      }
      const { device, control } = found
      const shape = shapeFor(control)
      const blocked = control.guarded && !locksAllowed
      const action = primaryAction(control)

      return {
        id,
        kindLabel: cap(control.domain),
        title: device.name,
        sub: blocked ? 'Locks off in Settings' : stateText(control, shape),
        active: control.on,
        onTap: () => {
          if (!control.available) {
            toast(`${device.name} is unavailable.`)
            return
          }
          if (blocked) {
            toast('Locks are off in Settings.')
            return
          }
          const gated = control.guarded || confirmAllDevices
          const run = () =>
            controlDevice(control.entity_id, action).then((r) => {
              devices.refresh()
              if (gated) toast(r.text || `${device.name} ${action}.`)
            })
          if (gated) {
            confirm({
              title: confirmPhrase(action, device.name.toLowerCase(), control.on),
              sig: signature('control_home_device', {
                target: device.name.toLowerCase(),
                action,
              }),
              yesLabel: cap(action),
              onConfirm: run,
            })
          } else {
            run()
          }
        },
      }
    }

    if (kind === 'timer') {
      const minutes = Number(arg) || 10
      const text = `${minutes} minute timer`
      const running = (reminders.data?.reminders ?? []).find(
        (r): r is Reminder & { next_run: string } => r.text === text && !!r.next_run,
      )
      return {
        id,
        kindLabel: 'Timer',
        title: text,
        sub: running
          ? `${upcomingTime(running.next_run)} left · tap to cancel`
          : 'Tap to start',
        active: !!running,
        onTap: () => {
          if (running) {
            confirm({
              title: 'Cancel the timer?',
              sig: signature('manage_reminders', { action: 'cancel', id_or_text: text }),
              yesLabel: 'Cancel timer',
              onConfirm: () =>
                invokeJob('manage_reminders', {
                  action: 'cancel',
                  id_or_text: running.id,
                }).then(() => reminders.refresh()),
            })
          } else {
            invokeJob('add_reminder', { when: `in ${minutes} minutes`, text }).then(() =>
              reminders.refresh(),
            )
            toast(`${minutes} minute timer started`)
          }
        },
      }
    }

    if (kind === 'volume') {
      const level = music.data?.volume ?? null
      return {
        id,
        kindLabel: 'Volume',
        title: 'Volume',
        sub: level === null ? '—' : `${level}%`,
        // Rendered as its own widget below, not a whole-tile tap.
        active: false,
        onTap: () => {},
      }
    }

    if (kind === 'music') {
      const np = music.data
      return {
        id,
        kindLabel: 'Music',
        title: 'Play / pause',
        sub: np?.active ? `${np.title} · ${np.is_playing ? 'playing' : 'paused'}` : 'Nothing playing',
        active: !!np?.is_playing,
        onTap: () => invokeJob('control_playback', { action: 'toggle' }).then(() => music.refresh()),
      }
    }

    // 'sleep'
    return {
      id,
      kindLabel: 'Sleep',
      title: 'Sleep',
      sub: 'Tap to sleep',
      active: false,
      onTap: () => setSleepOpen(true),
    }
  }

  const tiles = (tileIds ?? []).map(resolve)
  const loaded = Array.isArray(tileIds)

  const upcoming = [
    ...(reminders.data?.reminders ?? [])
      .filter((r) => r.next_run)
      .map((r) => ({
        key: `r-${r.id}`,
        whenMs: new Date(r.next_run!).getTime(),
        time: upcomingTime(r.next_run!),
        title: r.text || (r.action_job ? `Run ${r.action_job}` : 'Timer'),
        meta: 'Reminder',
      })),
    ...(agenda.data?.events ?? []).map((e) => ({
      key: `e-${e.id}`,
      whenMs: new Date(e.start).getTime(),
      time: upcomingTime(e.start),
      title: e.title,
      meta: e.location || e.account || 'Calendar',
    })),
  ]
    .sort((a, b) => a.whenMs - b.whenMs)
    .slice(0, 3)

  const np = music.data

  return (
    <div className="h-full grid gap-5" style={{ gridTemplateColumns: '1fr 360px' }}>
      <div className="min-h-0 flex flex-col">
        {loaded && tiles.length === 0 && !editing ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center">
            <p className="t-display">No tiles yet</p>
            <p className="text-[18px] text-muted">
              Tap Edit, then + Add tile, to build your home screen.
            </p>
          </div>
        ) : (
          <div
            className="scroll-y flex-1 min-h-0 grid gap-4"
            style={{ gridTemplateColumns: `repeat(${cols}, 1fr)`, gridAutoRows: 'minmax(0, 1fr)' }}
          >
            {tiles.map((tile) =>
              tile.id === 'volume' ? (
                <VolumeTile
                  key="volume"
                  volume={music.data?.volume ?? null}
                  editing={editing}
                  onStep={(direction) =>
                    invokeJob('set_volume', { direction }).then(() => music.refresh())
                  }
                  onRemove={() => removeTile('volume')}
                />
              ) : (
              <button
                key={tile.id}
                onClick={editing ? undefined : tile.onTap}
                className={`press relative rounded-[28px] p-6 flex flex-col justify-between text-left min-h-[140px] ${
                  tile.active ? 'bg-accent text-on-accent' : 'bg-surface text-text'
                }`}
              >
                <div className="flex items-center justify-between w-full">
                  <span className="text-[15px] font-semibold tracking-[0.1em] uppercase opacity-80">
                    {tile.kindLabel}
                  </span>
                  <span
                    className="w-4 h-4 rounded-full"
                    style={{ background: tile.active ? 'var(--wony-on-accent)' : 'var(--wony-off)' }}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <span className="text-[30px] font-bold leading-[1.1] tracking-[-0.01em]">
                    {tile.title}
                  </span>
                  <span className="text-[19px] font-medium opacity-85 tabular-nums">
                    {tile.sub}
                  </span>
                </div>
                {editing && (
                  <span
                    onClick={(e) => {
                      e.stopPropagation()
                      removeTile(tile.id)
                    }}
                    className="absolute -top-1.5 -right-1.5 w-[52px] h-[52px] rounded-full bg-accent text-on-accent text-[28px] font-bold flex items-center justify-center border-4 border-panel"
                  >
                    ×
                  </span>
                )}
              </button>
              ),
            )}
            {editing && (
              <button
                onClick={() => setAddOpen(true)}
                className="press rounded-[28px] border-[3px] border-dashed border-line text-[26px] font-semibold text-muted"
              >
                + Add tile
              </button>
            )}
          </div>
        )}
      </div>

      <div className="min-h-0 flex flex-col gap-4">
        <div className="bg-surface rounded-[28px] p-[22px] flex flex-col gap-[18px]">
          <div className="flex items-center gap-4">
            <div className="w-[84px] h-[84px] shrink-0 rounded-2xl bg-surface-2 overflow-hidden flex items-center justify-center">
              {np?.art_url ? (
                <img src={np.art_url} alt="" className="w-full h-full object-cover" draggable={false} />
              ) : (
                <MusicIcon size={28} className="text-muted opacity-50" />
              )}
            </div>
            <div className="flex flex-col gap-1 min-w-0">
              <span className="text-[24px] font-bold truncate">{np?.title || 'Nothing playing'}</span>
              <span className="text-[18px] text-muted truncate">{np?.artist || ''}</span>
            </div>
          </div>
          <div className="grid gap-2.5" style={{ gridTemplateColumns: '1fr 1.3fr 1fr' }}>
            <button
              onClick={() => invokeJob('control_playback', { action: 'previous' }).then(() => music.refresh())}
              className="press h-[72px] rounded-[20px] bg-surface-2 flex items-center justify-center"
            >
              <SkipBack size={22} />
            </button>
            <button
              onClick={() => invokeJob('control_playback', { action: 'toggle' }).then(() => music.refresh())}
              className="press h-[72px] rounded-[20px] bg-accent text-on-accent flex items-center justify-center"
            >
              {np?.is_playing ? <Pause size={24} fill="currentColor" /> : <Play size={24} fill="currentColor" />}
            </button>
            <button
              onClick={() => invokeJob('control_playback', { action: 'next' }).then(() => music.refresh())}
              className="press h-[72px] rounded-[20px] bg-surface-2 flex items-center justify-center"
            >
              <SkipForward size={22} />
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 bg-surface rounded-[28px] p-[22px] flex flex-col gap-4">
          <span className="t-label text-muted">Coming up</span>
          <div className="scroll-y flex-1 min-h-0 flex flex-col gap-3">
            {upcoming.length === 0 && <span className="text-[17px] text-muted">Nothing on the way.</span>}
            {upcoming.map((item) => (
              <div key={item.key} className="grid gap-3 items-baseline" style={{ gridTemplateColumns: '76px 1fr' }}>
                <span className="text-[20px] font-bold text-accent tabular-nums">{item.time}</span>
                <div className="flex flex-col gap-0.5 min-w-0">
                  <span className="text-[20px] font-semibold truncate">{item.title}</span>
                  <span className="text-[16px] text-muted truncate">{item.meta}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {addOpen && (
        <AddTileSheet
          items={candidateTiles(routines.data?.routines ?? [], devices.data).filter(
            (item) => !(tileIds ?? []).includes(item.id),
          )}
          onPick={addTile}
          onClose={() => setAddOpen(false)}
        />
      )}
      {sleepOpen && (
        <SleepSheet onSleeping={() => setSleepOpen(false)} onClose={() => setSleepOpen(false)} />
      )}
    </div>
  )
}

/** A tile with a widget in it rather than a single tap — the one exception
 *  to "whole tile is one button", because a slider has no sensible single
 *  gesture. Its own −/+ presses stop propagation so a tap that lands on them
 *  while editing does not also try to remove the tile. */
function VolumeTile({
  volume,
  editing,
  onStep,
  onRemove,
}: {
  volume: number | null
  editing: boolean
  onStep: (direction: 'up' | 'down') => void
  onRemove: () => void
}) {
  return (
    <div className="relative rounded-[28px] p-6 flex flex-col justify-between gap-3 bg-surface text-text min-h-[140px]">
      <div className="flex items-center justify-between w-full">
        <span className="text-[15px] font-semibold tracking-[0.1em] uppercase opacity-80">
          Volume
        </span>
        <span className="w-4 h-4 rounded-full" style={{ background: 'var(--wony-off)' }} />
      </div>

      <div className="flex flex-col gap-2.5">
        <span className="text-[30px] font-bold leading-[1.1] tracking-[-0.01em] tabular-nums">
          {volume === null ? '—' : `${volume}%`}
        </span>
        <div
          className="grid gap-2.5 items-center"
          style={{ gridTemplateColumns: '52px 1fr 52px' }}
        >
          <button
            onClick={() => onStep('down')}
            disabled={editing}
            className="press h-12 rounded-2xl bg-surface-2 text-[22px] font-medium disabled:opacity-40"
          >
            −
          </button>
          <div className="h-2.5 rounded-full bg-panel overflow-hidden">
            <div className="h-full bg-accent rounded-full" style={{ width: `${volume ?? 0}%` }} />
          </div>
          <button
            onClick={() => onStep('up')}
            disabled={editing}
            className="press h-12 rounded-2xl bg-surface-2 text-[22px] font-medium disabled:opacity-40"
          >
            +
          </button>
        </div>
      </div>

      {editing && (
        <span
          onClick={onRemove}
          className="absolute -top-1.5 -right-1.5 w-[52px] h-[52px] rounded-full bg-accent text-on-accent text-[28px] font-bold flex items-center justify-center border-4 border-panel"
        >
          ×
        </span>
      )}
    </div>
  )
}
