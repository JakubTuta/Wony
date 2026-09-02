import { useCallback, useEffect, useRef, useState } from 'react';
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
} from 'lucide-react';
import { fetchPanel, invokeJob } from '../api';
import type { NowPlaying } from '../api';
import { MUTED, Resting, RoundButton } from './ui';

// Fast enough that the progress bar does not visibly jump, slow enough that a
// tab left on this view is not hammering the Spotify API.
const POLL_MS = 5000;

function clock(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export function Music() {
  const [state, setState] = useState<NowPlaying | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  // Advanced locally between polls so the bar moves at one second per second.
  const [drift, setDrift] = useState(0);
  // Set on the first response, not during render — Date.now() is impure.
  const lastFetch = useRef(0);

  const refresh = useCallback(() => {
    fetchPanel<NowPlaying>('music').then((result) => {
      setState(result.data);
      setLoaded(true);
      lastFetch.current = Date.now();
      setDrift(0);
    });
  }, []);

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, POLL_MS);
    return () => clearInterval(poll);
  }, [refresh]);

  useEffect(() => {
    if (!state?.is_playing) return;
    const tick = setInterval(() => setDrift(Date.now() - lastFetch.current), 500);
    return () => clearInterval(tick);
  }, [state?.is_playing, state?.title]);

  const act = (name: string, args: Record<string, unknown>) => {
    setBusy(true);
    invokeJob(name, args as Record<string, string>).finally(() => {
      setBusy(false);
      // Spotify's own state lags the command by a beat.
      setTimeout(refresh, 400);
    });
  };

  if (!loaded) return <Resting title="…" />;

  if (!state || !state.active) {
    return (
      <Resting icon={<MusicIcon size={32} />} title="Nothing playing">
        Start something on any Spotify device — or ask Wony to play something — and it
        shows up here.
      </Resting>
    );
  }

  const progress = Math.min((state.progress_ms ?? 0) + drift, state.duration_ms ?? 0);
  const pct = state.duration_ms ? (progress / state.duration_ms) * 100 : 0;

  return (
    <div className="p-4 flex flex-col items-center gap-4">
      <div
        className="w-full max-w-[240px] aspect-square rounded-xl overflow-hidden
                   bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700
                   flex items-center justify-center"
      >
        {state.art_url ? (
          <img src={state.art_url} alt="" className="w-full h-full object-cover" draggable={false} />
        ) : (
          <MusicIcon size={40} className={MUTED} />
        )}
      </div>

      <div className="w-full text-center min-w-0">
        <div className="text-base font-medium text-gray-900 dark:text-gray-100 truncate">
          {state.title}
        </div>
        <div className={`text-sm ${MUTED} truncate`}>{state.artist}</div>
      </div>

      <div className="w-full max-w-sm">
        <div className="h-1 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
          <div
            className="h-full bg-violet-600"
            style={{ width: `${pct}%`, transition: 'width 500ms linear' }}
          />
        </div>
        <div className={`flex justify-between text-[11px] ${MUTED} pt-1 tabular-nums`}>
          <span>{clock(progress)}</span>
          <span>{clock(state.duration_ms ?? 0)}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <RoundButton
          label="Shuffle"
          active={state.shuffle}
          onClick={() => act('control_playback', { action: 'shuffle' })}
          disabled={busy}
        >
          <Shuffle size={15} />
        </RoundButton>
        <RoundButton
          label="Previous"
          onClick={() => act('control_playback', { action: 'previous' })}
          disabled={busy}
        >
          <SkipBack size={17} />
        </RoundButton>
        <RoundButton
          label={state.is_playing ? 'Pause' : 'Play'}
          primary
          onClick={() => act('control_playback', { action: 'toggle' })}
          disabled={busy}
        >
          {state.is_playing ? (
            <Pause size={20} fill="currentColor" />
          ) : (
            <Play size={20} fill="currentColor" />
          )}
        </RoundButton>
        <RoundButton
          label="Next"
          onClick={() => act('control_playback', { action: 'next' })}
          disabled={busy}
        >
          <SkipForward size={17} />
        </RoundButton>
        <RoundButton label="Like" onClick={() => act('set_like', { action: 'toggle' })} disabled={busy}>
          <Heart size={15} />
        </RoundButton>
      </div>

      <div className="flex items-center gap-2">
        <RoundButton
          label="Quieter"
          onClick={() => act('set_volume', { direction: 'down' })}
          disabled={busy}
        >
          <Volume1 size={15} />
        </RoundButton>
        <span className={`text-xs ${MUTED} tabular-nums w-12 text-center`}>
          {state.volume === null || state.volume === undefined ? '—' : `${state.volume}%`}
        </span>
        <RoundButton
          label="Louder"
          onClick={() => act('set_volume', { direction: 'up' })}
          disabled={busy}
        >
          <Volume2 size={15} />
        </RoundButton>
      </div>

      {state.device && <div className={`text-xs ${MUTED}`}>on {state.device}</div>}
    </div>
  );
}
