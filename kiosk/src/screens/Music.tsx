import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Heart,
  Music as MusicIcon,
  Pause,
  Play,
  Shuffle,
  SkipBack,
  SkipForward,
  Volume1,
  Volume2,
} from 'lucide-react'
import { fetchNowPlaying, invokeJob } from '../api'
import type { NowPlaying } from '../api'

// Fast enough that the progress bar does not visibly jump, slow enough that a
// screen left on this view is not hammering the Spotify API.
const POLL_MS = 5000

function clock(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export function Music() {
  const [state, setState] = useState<NowPlaying | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  // Advanced locally between polls so the bar moves at one second per second.
  const [drift, setDrift] = useState(0)
  // Set on the first response, not during render — Date.now() is impure.
  const lastFetch = useRef(0)

  const refresh = useCallback(() => {
    fetchNowPlaying().then((next) => {
      setState(next)
      setLoaded(true)
      lastFetch.current = Date.now()
      setDrift(0)
    })
  }, [])

  useEffect(() => {
    refresh()
    const poll = setInterval(refresh, POLL_MS)
    return () => clearInterval(poll)
  }, [refresh])

  useEffect(() => {
    if (!state?.is_playing) return
    const tick = setInterval(() => setDrift(Date.now() - lastFetch.current), 500)
    return () => clearInterval(tick)
  }, [state?.is_playing, state?.title])

  const act = (name: string, args: Record<string, unknown>) => {
    setBusy(true)
    invokeJob(name, args).finally(() => {
      setBusy(false)
      // Spotify's own state lags the command by a beat.
      setTimeout(refresh, 400)
    })
  }

  if (!loaded) {
    return <Resting label="…" />
  }

  if (!state || !state.active) {
    return (
      <Resting label="Nothing playing">
        Start something on any Spotify device — or say “play something” — and it shows up
        here.
      </Resting>
    )
  }

  const progress = Math.min((state.progress_ms ?? 0) + drift, state.duration_ms ?? 0)
  const pct = state.duration_ms ? (progress / state.duration_ms) * 100 : 0

  return (
    <div className="scroll-y flex-1 flex flex-col items-center px-6 py-4 gap-5">
      <div
        className="w-full max-w-[min(52vh,320px)] aspect-square rounded-2xl overflow-hidden
                   bg-surface-2 border border-line flex items-center justify-center shrink-0"
        style={{ boxShadow: 'var(--wony-shadow)' }}
      >
        {state.art_url ? (
          <img
            src={state.art_url}
            alt=""
            className="w-full h-full object-cover"
            draggable={false}
          />
        ) : (
          <MusicIcon size={48} className="text-muted opacity-40" />
        )}
      </div>

      <div className="w-full max-w-xl text-center min-w-0">
        <div className="t-display truncate">{state.title}</div>
        <div className="t-body text-muted truncate">{state.artist}</div>
      </div>

      <div className="w-full max-w-xl">
        <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
          <div
            className="h-full bg-accent"
            style={{ width: `${pct}%`, transition: 'width 500ms linear' }}
          />
        </div>
        <div className="flex justify-between t-small text-muted pt-1.5 tabular-nums">
          <span>{clock(progress)}</span>
          <span>{clock(state.duration_ms ?? 0)}</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Round
          label="Shuffle"
          active={state.shuffle}
          onClick={() => act('control_playback', { action: 'shuffle' })}
          disabled={busy}
        >
          <Shuffle size={20} />
        </Round>
        <Round
          label="Previous"
          onClick={() => act('control_playback', { action: 'previous' })}
          disabled={busy}
        >
          <SkipBack size={24} />
        </Round>
        <Round
          label={state.is_playing ? 'Pause' : 'Play'}
          primary
          onClick={() => act('control_playback', { action: 'toggle' })}
          disabled={busy}
        >
          {state.is_playing ? (
            <Pause size={28} fill="currentColor" />
          ) : (
            <Play size={28} fill="currentColor" />
          )}
        </Round>
        <Round
          label="Next"
          onClick={() => act('control_playback', { action: 'next' })}
          disabled={busy}
        >
          <SkipForward size={24} />
        </Round>
        <Round
          label="Like"
          onClick={() => act('set_like', { action: 'toggle' })}
          disabled={busy}
        >
          <Heart size={20} />
        </Round>
      </div>

      <div className="flex items-center gap-3">
        <Round
          label="Quieter"
          onClick={() => act('set_volume', { direction: 'down' })}
          disabled={busy}
        >
          <Volume1 size={20} />
        </Round>
        <span className="t-small text-muted tabular-nums w-16 text-center">
          {state.volume === null || state.volume === undefined ? '—' : `${state.volume}%`}
        </span>
        <Round
          label="Louder"
          onClick={() => act('set_volume', { direction: 'up' })}
          disabled={busy}
        >
          <Volume2 size={20} />
        </Round>
      </div>

      {state.device && <div className="t-small text-muted pb-2">on {state.device}</div>}
    </div>
  )
}

function Resting({ label, children }: { label: string; children?: React.ReactNode }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 px-10 text-center">
      <MusicIcon size={32} className="text-muted opacity-40" />
      <p className="t-display">{label}</p>
      {children && <p className="t-body text-muted">{children}</p>}
    </div>
  )
}

function Round({
  children,
  label,
  onClick,
  disabled,
  primary = false,
  active = false,
}: {
  children: React.ReactNode
  label: string
  onClick: () => void
  disabled?: boolean
  primary?: boolean
  active?: boolean
}) {
  const size = primary ? 'w-[72px] h-[72px]' : 'w-14 h-14'
  const skin = primary
    ? 'bg-accent text-on-accent'
    : active
      ? 'bg-accent-soft text-accent border border-accent'
      : 'bg-surface border border-line text-muted'

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={`press flex items-center justify-center rounded-full disabled:opacity-40 ${size} ${skin}`}
    >
      {children}
    </button>
  )
}
