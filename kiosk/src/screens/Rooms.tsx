import { useState } from 'react'
import { Lock } from 'lucide-react'
import { controlDevice } from '../api'
import type { Control, Device } from '../api'
import { confirmPhrase, shapeFor, stateColor, stateText } from '../lib/devices'
import { signature } from '../lib/jobs'
import { useLive } from '../state/live-context'
import { useUi } from '../state/ui-context'
import { useWony } from '../state/wony-context'

export function Rooms() {
  const { config } = useWony()
  const { confirm, toast } = useUi()
  const { devices } = useLive()
  const [room, setRoom] = useState<string | null>(null)

  const confirmAllDevices = config?.kiosk.confirm_all_devices ?? false
  const locksAllowed = devices.data?.locks_allowed ?? false
  const areas = devices.data?.areas ?? []
  const activeArea = areas.find((a) => (a.name || 'Other') === room) ?? areas[0]

  const act = (control: Control, action: string, value?: number, option?: string) => {
    controlDevice(control.entity_id, action, value, option).then((r) => {
      devices.refresh()
      if (!r.ok) toast(r.text)
    })
  }

  const guardedAct = (
    device: Device,
    control: Control,
    action: string,
    yesLabel: string,
    value?: number,
    option?: string,
  ) => {
    const gated = control.guarded || confirmAllDevices
    if (!gated) {
      act(control, action, value, option)
      return
    }
    confirm({
      title: confirmPhrase(action, device.name.toLowerCase(), control.on),
      sig: signature('control_home_device', { target: device.name.toLowerCase(), action }),
      yesLabel,
      onConfirm: () => act(control, action, value, option),
    })
  }

  if (devices.error && !devices.data) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-[20px] text-muted">{devices.error}</p>
      </div>
    )
  }

  if (areas.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-[20px] text-muted">
          {devices.loaded ? 'No devices found.' : 'Finding your devices…'}
        </p>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col gap-[18px]">
      <div className="scroll-x flex gap-3 shrink-0">
        {areas.map((a) => {
          const name = a.name || 'Other'
          const active = name === (activeArea?.name || 'Other')
          return (
            <button
              key={name}
              onClick={() => setRoom(name)}
              className={`press shrink-0 h-17 px-7 rounded-[34px] text-[21px] font-semibold ${
                active ? 'bg-text text-panel' : 'bg-surface text-text'
              }`}
            >
              {name}
            </button>
          )
        })}
      </div>

      <div
        className="scroll-y flex-1 min-h-0 grid grid-cols-2 gap-4"
        style={{ gridAutoRows: 'minmax(0, 1fr)' }}
      >
        {(activeArea?.devices ?? []).map((device) => (
          <DeviceCard
            key={device.primary.entity_id}
            device={device}
            locksAllowed={locksAllowed}
            onAct={(action, value, option) => act(device.primary, action, value, option)}
            onGuardedAct={(action, yesLabel, value, option) =>
              guardedAct(device, device.primary, action, yesLabel, value, option)
            }
          />
        ))}
      </div>
    </div>
  )
}

function DeviceCard({
  device,
  locksAllowed,
  onAct,
  onGuardedAct,
}: {
  device: Device
  locksAllowed: boolean
  onAct: (action: string, value?: number, option?: string) => void
  onGuardedAct: (action: string, yesLabel: string, value?: number, option?: string) => void
}) {
  const control = device.primary
  const shape = shapeFor(control)
  const blocked = control.guarded && !locksAllowed
  const disabled = !control.available || blocked

  return (
    <div className="bg-surface rounded-[28px] px-6 py-[22px] flex flex-col justify-between gap-3.5 min-h-0">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1 min-w-0">
          <span className="text-[26px] font-bold truncate flex items-center gap-1.5">
            {control.guarded && <Lock size={16} className="text-muted shrink-0" />}
            {device.name}
          </span>
          <span className={`text-[19px] font-medium truncate ${stateColor(control)}`}>
            {blocked ? 'Locked off in Settings' : disabled ? 'Unavailable' : stateText(control, shape)}
          </span>
        </div>

        {(shape === 'toggle' || shape === 'toggle-level') && (
          <button
            onClick={() => onAct('toggle')}
            disabled={disabled}
            className="press shrink-0 w-28 h-16 rounded-[32px] p-1.5 flex disabled:opacity-40"
            style={{
              background: control.on ? 'var(--wony-accent)' : 'var(--wony-off)',
              justifyContent: control.on ? 'flex-end' : 'flex-start',
            }}
          >
            <span className="w-13 h-13 rounded-full bg-text" />
          </button>
        )}
      </div>

      {shape === 'toggle-level' && !disabled && (
        <div className="grid gap-3.5 items-center" style={{ gridTemplateColumns: '80px 1fr 80px' }}>
          <button
            onClick={() => onAct('on', Math.max(0, (control.level ?? 0) - 10))}
            className="press h-18 rounded-[20px] bg-surface-2 text-[34px] font-medium"
          >
            −
          </button>
          <div className="h-4 rounded-full bg-panel overflow-hidden">
            <div
              className="h-full bg-accent rounded-full"
              style={{ width: `${control.on ? (control.level ?? 0) : 0}%` }}
            />
          </div>
          <button
            onClick={() => onAct('on', Math.min(100, (control.level ?? 0) + 10))}
            className="press h-18 rounded-[20px] bg-surface-2 text-[34px] font-medium"
          >
            +
          </button>
        </div>
      )}

      {shape === 'cover' && !disabled && (
        <div className="grid grid-cols-3 gap-3">
          <button onClick={() => onAct('open')} className="press h-18 rounded-[20px] bg-surface-2 text-[21px] font-semibold">
            Open
          </button>
          <button onClick={() => onAct('stop')} className="press h-18 rounded-[20px] bg-surface-2 text-[21px] font-semibold">
            Stop
          </button>
          <button onClick={() => onAct('close')} className="press h-18 rounded-[20px] bg-surface-2 text-[21px] font-semibold">
            Close
          </button>
        </div>
      )}

      {shape === 'climate' && !disabled && (
        <div className="grid gap-3.5 items-center" style={{ gridTemplateColumns: '80px 1fr 80px' }}>
          <button
            onClick={() => onAct('set', (control.target ?? 20) - 0.5)}
            className="press h-18 rounded-[20px] bg-surface-2 text-[34px]"
          >
            −
          </button>
          <span className="text-center text-[44px] font-bold tabular-nums">
            {control.target !== null ? `${control.target.toFixed(1)}°` : '—'}
          </span>
          <button
            onClick={() => onAct('set', (control.target ?? 20) + 0.5)}
            className="press h-18 rounded-[20px] bg-surface-2 text-[34px]"
          >
            +
          </button>
        </div>
      )}

      {shape === 'lock' && !disabled && (
        <button
          onClick={() => onGuardedAct(control.on ? 'lock' : 'unlock', control.on ? 'Lock' : 'Unlock')}
          className="press h-18 rounded-[20px] bg-surface-2 text-[21px] font-semibold"
        >
          {control.on ? 'Lock' : 'Unlock'}
        </button>
      )}

      {shape === 'vacuum' && !disabled && (
        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={() => onAct('start')}
            className="press h-18 rounded-[20px] bg-accent text-on-accent text-[21px] font-bold"
          >
            Start cleaning
          </button>
          <button onClick={() => onAct('dock')} className="press h-18 rounded-[20px] bg-surface-2 text-[21px] font-semibold">
            Send to dock
          </button>
        </div>
      )}

      {shape === 'press' && !disabled && (
        <button onClick={() => onAct('on')} className="press h-18 rounded-[20px] bg-surface-2 text-[21px] font-semibold">
          Activate
        </button>
      )}

      {shape === 'options' && !disabled && (
        <div className="flex flex-wrap gap-2">
          {control.options.map((option) => (
            <button
              key={option}
              onClick={() => onAct('set', undefined, option)}
              className={`press px-4 h-12 rounded-xl text-[18px] font-semibold ${
                control.state === option ? 'bg-accent text-on-accent' : 'bg-surface-2 text-muted'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {shape === 'number' && !disabled && (
        <div className="flex items-center justify-end gap-3">
          <button
            onClick={() => onAct('set', Number(control.state) - 1)}
            className="press w-12 h-12 rounded-xl bg-surface-2 text-[22px]"
          >
            −
          </button>
          <span className="text-[20px] w-16 text-center tabular-nums">{control.state}</span>
          <button
            onClick={() => onAct('set', Number(control.state) + 1)}
            className="press w-12 h-12 rounded-xl bg-surface-2 text-[22px]"
          >
            +
          </button>
        </div>
      )}
    </div>
  )
}
