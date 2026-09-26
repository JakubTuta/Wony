import { useEffect, useRef, useState } from 'react'
import {
  Heart,
  Music as MusicIcon,
  Pause,
  Play,
  Shuffle,
  SkipBack,
  SkipForward,
} from 'lucide-react'
import { invokeJob } from '../api'
import { clockFromMs } from '../lib/time'
import { useLive } from '../state/live-context'

export function Music() {
  const { music, library } = useLive()
  const [busy, setBusy] = useState(false)
  // Advances the progress bar between 5s polls, one second per second.
  const [drift, setDrift] = useState(0)
  const lastFetch = useRef(0)

  const state = music.data

  // Ref-only: the next 500ms tick recomputes drift from this, so there is
  // nothing here for React to render — just where "now" resets from.
  useEffect(() => {
    lastFetch.current = Date.now()
  }, [state])

  useEffect(() => {
    if (!state?.is_playing) return
    const tick = setInterval(() => setDrift(Date.now() - lastFetch.current), 500)
    return () => clearInterval(tick)
  }, [state?.is_playing, state?.title])

  const act = (name: string, args: Record<string, unknown> = {}) => {
    setBusy(true)
    invokeJob(name, args).finally(() => {
      setBusy(false)
      setTimeout(music.refresh, 400)
    })
  }

  if (!music.loaded) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-[20px] text-muted">…</p>
      </div>
    )
  }

  if (!state || !state.active) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-10">
        <MusicIcon size={40} className="text-muted opacity-40" />
        <p className="t-display">Nothing playing</p>
        <p className="text-[19px] text-muted">
          Start something on any Spotify device — or run a routine that does —
          and it shows up here.
        </p>
      </div>
    )
  }

  const progress = Math.min((state.progress_ms ?? 0) + drift, state.duration_ms ?? 0)
  const pct = state.duration_ms ? (progress / state.duration_ms) * 100 : 0
  const devices = library.data?.devices ?? []
  const playlists = (library.data?.playlists ?? []).slice(0, 4)

  return (
    <div className="h-full grid gap-8" style={{ gridTemplateColumns: '340px 1fr' }}>
      <div className="flex flex-col gap-4 min-h-0">
        <div className="w-[340px] h-[340px] shrink-0 rounded-[28px] bg-surface-2 overflow-hidden flex items-center justify-center">
          {state.art_url ? (
            <img src={state.art_url} alt="" className="w-full h-full object-cover" draggable={false} />
          ) : (
            <MusicIcon size={48} className="text-muted opacity-40" />
          )}
        </div>
        <span className="t-label text-muted">Playing on</span>
        <div className="flex flex-wrap gap-2.5">
          {devices.map((d) => (
            <button
              key={d.name}
              onClick={() => act('control_playback', { action: 'transfer', value: d.name })}
              className={`press h-15 px-5 rounded-full text-[18px] font-semibold ${
                d.active ? 'bg-text text-panel' : 'bg-surface text-text'
              }`}
            >
              {d.name}
            </button>
          ))}
          {devices.length === 0 && (
            <span className="text-[16px] text-muted">No devices found.</span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-[22px] min-w-0">
        <div className="flex flex-col gap-1.5 min-w-0">
          <span className="text-[48px] font-bold tracking-[-0.02em] truncate">{state.title}</span>
          <span className="text-[24px] text-muted truncate">
            {state.artist}
            {state.album ? ` · ${state.album}` : ''}
          </span>
        </div>

        <div className="flex flex-col gap-2">
          <div className="h-2.5 rounded-full bg-surface overflow-hidden">
            <div
              className="h-full bg-accent"
              style={{ width: `${pct}%`, transition: 'width 500ms linear' }}
            />
          </div>
          <div className="flex justify-between text-[17px] text-muted tabular-nums">
            <span>{clockFromMs(progress)}</span>
            <span>{clockFromMs(state.duration_ms ?? 0)}</span>
          </div>
        </div>

        <div
          className="grid gap-3 items-center"
          style={{ gridTemplateColumns: '1fr 1.2fr 1.6fr 1.2fr 1fr' }}
        >
          <button
            onClick={() => act('control_playback', { action: 'shuffle' })}
            disabled={busy}
            className={`press h-22 rounded-3xl text-[18px] font-semibold disabled:opacity-40 ${
              state.shuffle ? 'bg-accent text-on-accent' : 'bg-surface-2 text-text'
            }`}
          >
            <Shuffle size={20} className="mx-auto" />
          </button>
          <button
            onClick={() => act('control_playback', { action: 'previous' })}
            disabled={busy}
            className="press h-25 rounded-3xl bg-surface-2 flex items-center justify-center disabled:opacity-40"
          >
            <SkipBack size={28} />
          </button>
          <button
            onClick={() => act('control_playback', { action: 'toggle' })}
            disabled={busy}
            className="press h-28 rounded-[28px] bg-accent text-on-accent flex items-center justify-center disabled:opacity-40"
          >
            {state.is_playing ? <Pause size={34} fill="currentColor" /> : <Play size={34} fill="currentColor" />}
          </button>
          <button
            onClick={() => act('control_playback', { action: 'next' })}
            disabled={busy}
            className="press h-25 rounded-3xl bg-surface-2 flex items-center justify-center disabled:opacity-40"
          >
            <SkipForward size={28} />
          </button>
          <button
            onClick={() => act('control_playback', { action: state.liked ? 'unlike' : 'like' })}
            disabled={busy}
            className={`press h-22 rounded-3xl text-[18px] font-semibold disabled:opacity-40 ${
              state.liked ? 'bg-accent text-on-accent' : 'bg-surface-2 text-text'
            }`}
          >
            <Heart size={20} className="mx-auto" fill={state.liked ? 'currentColor' : 'none'} />
          </button>
        </div>

        <div className="grid gap-4 items-center" style={{ gridTemplateColumns: '88px 1fr 88px' }}>
          <button
            onClick={() => act('set_volume', { direction: 'down' })}
            className="press h-18 rounded-[20px] bg-surface-2 text-[34px]"
          >
            −
          </button>
          <div className="flex flex-col gap-1.5">
            <div className="h-3.5 rounded-full bg-surface overflow-hidden">
              <div className="h-full bg-text rounded-full" style={{ width: `${state.volume ?? 0}%` }} />
            </div>
            <span className="text-[16px] text-muted">Volume {state.volume ?? 0}</span>
          </div>
          <button
            onClick={() => act('set_volume', { direction: 'up' })}
            className="press h-18 rounded-[20px] bg-surface-2 text-[34px]"
          >
            +
          </button>
        </div>

        <div className="grid grid-cols-4 gap-3">
          {playlists.map((p) => (
            <button
              key={p.name}
              onClick={() => act('play_songs', { title: p.name, content_type: 'playlist' })}
              className="press h-19 rounded-[20px] bg-surface text-[19px] font-semibold text-left px-[18px] truncate"
            >
              {p.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
