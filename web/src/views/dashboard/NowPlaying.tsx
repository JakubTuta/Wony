import { useCallback, useEffect, useRef, useState } from 'react';
import { Music as MusicIcon, Pause, Play, SkipBack, SkipForward } from 'lucide-react';
import { fetchPanel } from '../../api';
import type { NowPlaying as NowPlayingData } from '../../api';
import { useWony } from '../../lib/wonyContext';
import { Gated } from '../../components/ModuleGate';
import { CARD, SectionLabel } from '../../components/ui';

const POLL_MS = 5000;

function clock(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export function NowPlaying() {
  const { runJob } = useWony();
  const [state, setState] = useState<NowPlayingData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [drift, setDrift] = useState(0);
  const lastFetch = useRef(0);

  const refresh = useCallback(() => {
    fetchPanel<NowPlayingData>('music').then((result) => {
      setState(result.data);
      setError(result.error);
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

  const act = (action: string) => {
    runJob('control_playback', { action }, { from: 'Dashboard' }).finally(() => setTimeout(refresh, 400));
  };

  const blocked = !loaded || !!error || !state?.active;
  const message = !loaded
    ? 'Checking Spotify…'
    : error || 'Nothing playing — open Spotify to see it here.';

  // Nothing live to show while blocked — a placeholder track fills the same
  // layout so Gated has real shape to blur instead of an empty card.
  const display = state?.active
    ? state
    : {
        title: 'Song title',
        artist: 'Artist name',
        device: null,
        art_url: null,
        is_playing: false,
        progress_ms: 90000,
        duration_ms: 210000,
      };

  const progress = state?.active
    ? Math.min((state.progress_ms ?? 0) + drift, state.duration_ms ?? 0)
    : (display.progress_ms ?? 0);
  const duration = display.duration_ms ?? 0;
  const pct = duration ? (progress / duration) * 100 : 0;

  return (
    <Gated blocked={blocked} message={message}>
      <div className={`${CARD} p-4.5 flex flex-col gap-3.5`}>
        <div className="flex justify-between items-center">
          <SectionLabel>Now playing</SectionLabel>
          {display.device && <span className="text-xs text-muted">{display.device}</span>}
        </div>
        <div className="flex gap-3.5 items-center">
          <div
            className="w-[84px] h-[84px] shrink-0 rounded-[10px] flex items-center justify-center overflow-hidden bg-teal-soft"
          >
            {display.art_url ? (
              <img src={display.art_url} alt="" className="w-full h-full object-cover" draggable={false} />
            ) : (
              <MusicIcon size={24} className="text-teal" />
            )}
          </div>
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-[17px] font-semibold truncate">{display.title}</span>
            <span className="text-sm text-muted truncate">{display.artist}</span>
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <div className="h-1 rounded-full bg-teal-soft overflow-hidden">
            <div className="h-full bg-accent" style={{ width: `${pct}%`, transition: 'width 500ms linear' }} />
          </div>
          <div className="flex justify-between font-mono text-[11px] text-muted">
            <span>{clock(progress)}</span>
            <span>{clock(duration)}</span>
          </div>
        </div>
        <div className="flex gap-2 items-center justify-center">
          <button
            onClick={() => act('previous')}
            className="border-0 bg-teal-soft text-teal rounded-full w-10 h-10 flex items-center justify-center"
          >
            <SkipBack size={15} />
          </button>
          <button
            onClick={() => act('toggle')}
            className="border-0 bg-accent text-on-accent rounded-full w-[52px] h-[52px] flex items-center justify-center"
          >
            {display.is_playing ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
          </button>
          <button
            onClick={() => act('next')}
            className="border-0 bg-teal-soft text-teal rounded-full w-10 h-10 flex items-center justify-center"
          >
            <SkipForward size={15} />
          </button>
        </div>
      </div>
    </Gated>
  );
}
