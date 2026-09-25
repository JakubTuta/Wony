import { useEffect, useState } from 'react';
import { Search, X } from 'lucide-react';
import { fetchPanel } from '../../api';
import { useWony } from '../../lib/wonyContext';
import { humanize, isWidgetCovered } from '../../lib/jobs';
import { moduleHealthState, moduleMessage } from '../../lib/moduleHealth';
import { Gated } from '../../components/ModuleGate';
import { Modal, SectionLabel, Switch } from '../../components/ui';
import type { NowPlaying, Pin } from '../../api';
import { isBackgroundJobOn } from './seed';

const PRESET_MINUTES = [5, 10, 25];
const SPOTIFY_POLL_MS = 5000;

export function QuickControls({ editing }: { editing: boolean }) {
  const { pins, setPins } = useWony();
  const [picker, setPicker] = useState(false);
  const [status, setStatus] = useState<Record<string, string>>({});

  if (pins === null) return null;

  const remove = (id: string) => setPins(pins.filter((p) => p.id !== id));
  const note = (id: string, text: string) => setStatus((prev) => ({ ...prev, [id]: text }));

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <SectionLabel>Quick controls</SectionLabel>
        {editing && <span className="text-[13px] text-red">Remove controls or add any job from the catalog</span>}
      </div>
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
        {pins.map((pin) => (
          <PinCard
            key={pin.id}
            pin={pin}
            editing={editing}
            status={status[pin.id]}
            onNote={(text) => note(pin.id, text)}
            onRemove={() => remove(pin.id)}
          />
        ))}
        {editing && (
          <button
            onClick={() => setPicker(true)}
            className="border-[1.5px] border-dashed rounded-[14px] min-h-[148px] text-teal text-[15px] font-semibold bg-transparent"
            style={{ borderColor: 'var(--color-dashed-border)' }}
          >
            + Add control
          </button>
        )}
      </div>
      {picker && (
        <JobPicker
          existing={pins}
          onClose={() => setPicker(false)}
          onPick={(job, module) => {
            setPicker(false);
            setPins([...pins, { id: `${job}-${Date.now()}`, kind: 'run', job, module, title: humanize(job), args: {} }]);
          }}
        />
      )}
    </section>
  );
}

function PinCard({
  pin,
  editing,
  status,
  onNote,
  onRemove,
}: {
  pin: Pin;
  editing: boolean;
  status?: string;
  onNote: (text: string) => void;
  onRemove: () => void;
}) {
  const { jobsByName, health, settings, runJob } = useWony();
  const job = jobsByName.get(pin.job);
  const [shopDraft, setShopDraft] = useState('');
  const [volume, setVolume] = useState<number>(typeof pin.args.level === 'number' ? pin.args.level : 50);
  const [toggledOn, setToggledOn] = useState<boolean | null>(null);

  // A volume slider's "50" was never a live reading — it was the seed's
  // placeholder. For Spotify specifically, read the real level (and whether
  // anything is even playing) the same way the Now playing widget does.
  const isSpotifyVolume = pin.job === 'set_volume';
  const [spotify, setSpotify] = useState<NowPlaying | null>(null);
  useEffect(() => {
    if (!isSpotifyVolume) return;
    const load = () =>
      fetchPanel<NowPlaying>('music').then((r) => {
        setSpotify(r.data);
        if (r.data?.active && typeof r.data.volume === 'number') {
          setVolume(r.data.volume);
        }
      });
    load();
    const poll = setInterval(load, SPOTIFY_POLL_MS);
    return () => clearInterval(poll);
  }, [isSpotifyVolume]);
  const spotifyInactive = isSpotifyVolume && !spotify?.active;

  const backgroundOn = isBackgroundJobOn(pin.job, health?.background ?? []);
  const isOn = toggledOn ?? backgroundOn ?? pin.args.action === 'start';

  const broken = moduleHealthState(pin.module, health) !== 'ok';

  const run = () => {
    runJob(pin.job, pin.args, { from: 'Dashboard' }).then((res) => {
      onNote(res.error ? `Failed: ${res.error}` : `Ran at ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
    });
  };

  return (
    <div className="relative">
      <Gated blocked={spotifyInactive} message="Nothing playing — open Spotify to see it here.">
      <div
        className={`bg-surface border border-border rounded-[14px] p-4 flex flex-col gap-3 min-h-[148px] ${broken ? 'opacity-55' : ''}`}
      >
      <div className="flex justify-between items-start gap-2">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="font-mono text-[11px] text-muted">{pin.module}</span>
          <span className="text-base font-semibold">{pin.title}</span>
        </div>
        {pin.kind === 'toggle' && !broken && (
          <Switch
            checked={isOn}
            onChange={() => {
              const next = !isOn;
              setToggledOn(next);
              runJob(pin.job, { ...pin.args, action: next ? 'start' : 'stop' }, { from: 'Dashboard' });
            }}
          />
        )}
      </div>

      <span className="text-[13px] text-muted">
        {broken ? moduleMessage(pin.module, health, settings?.modules, pin.module) : (status ?? job?.summary ?? '')}
      </span>

      {broken ? null : (
      <div className="mt-auto flex gap-1.5 flex-wrap items-center">
        {pin.kind === 'run' && (
          <button onClick={run} className="border-0 bg-accent text-on-accent rounded-[9px] px-3.5 py-2 text-sm font-semibold">
            Run
          </button>
        )}
        {pin.kind === 'presets' &&
          PRESET_MINUTES.map((n) => (
            <button
              key={n}
              onClick={() => {
                runJob('add_reminder', { when: `in ${n} minutes`, text: 'Quick timer' }, { from: 'Dashboard' });
                onNote(`${n} min timer running`);
              }}
              className="border-0 bg-teal-soft text-teal rounded-[9px] px-3 py-2 text-sm font-semibold"
            >
              {n} min
            </button>
          ))}
        {pin.kind === 'slider' && (
          <>
            <input
              type="range"
              min={0}
              max={100}
              value={volume}
              onChange={(e) => setVolume(Number(e.target.value))}
              onMouseUp={() => runJob('set_volume', { level: volume }, { from: 'Dashboard' })}
              onTouchEnd={() => runJob('set_volume', { level: volume }, { from: 'Dashboard' })}
              className="flex-1 accent-accent"
            />
            <span className="font-mono text-[13px] w-8 text-right">{volume}</span>
          </>
        )}
        {pin.kind === 'input' && (
          <>
            <input
              value={shopDraft}
              onChange={(e) => setShopDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && shopDraft.trim()) {
                  runJob('note', { ...pin.args, action: 'add', text: shopDraft.trim() }, { from: 'Dashboard' });
                  setShopDraft('');
                }
              }}
              placeholder="Item"
              className="flex-1 min-w-0 border rounded-[9px] px-2.5 py-2 text-sm"
              style={{ borderColor: 'var(--color-border)' }}
            />
            <button
              onClick={() => {
                if (!shopDraft.trim()) return;
                runJob('note', { ...pin.args, action: 'add', text: shopDraft.trim() }, { from: 'Dashboard' });
                setShopDraft('');
              }}
              className="border-0 bg-accent text-on-accent rounded-[9px] px-3 py-2 text-sm font-semibold"
            >
              Add
            </button>
          </>
        )}
      </div>
      )}
      </div>
      </Gated>
      {editing && (
        <button
          onClick={onRemove}
          aria-label={`Remove ${pin.title}`}
          className="absolute -top-2 -right-2 w-6 h-6 rounded-full border-0 bg-accent text-on-accent font-bold leading-none"
        >
          ×
        </button>
      )}
    </div>
  );
}

function JobPicker({
  existing,
  onClose,
  onPick,
}: {
  existing: Pin[];
  onClose: () => void;
  onPick: (job: string, module: string) => void;
}) {
  const { jobs } = useWony();
  const [q, setQ] = useState('');
  const pinnedJobs = new Set(existing.map((p) => p.job));
  const query = q.toLowerCase();
  const list = jobs.filter(
    (j) =>
      !pinnedJobs.has(j.name) &&
      !isWidgetCovered(j.name) &&
      (!query || j.name.includes(query) || j.summary.toLowerCase().includes(query)),
  );

  return (
    <Modal onClose={onClose}>
      <div className="flex justify-between items-center">
        <span className="text-lg font-bold">Add a control</span>
        <button onClick={onClose} className="border-0 bg-transparent text-sm text-muted font-semibold">
          <X size={16} />
        </button>
      </div>
      <div className="relative">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={`Search ${jobs.length} jobs`}
          className="w-full border rounded-[9px] pl-8 pr-2.5 py-2 text-sm"
          style={{ borderColor: 'var(--color-border)' }}
        />
      </div>
      <div className="overflow-auto max-h-[50vh] -mx-2">
        {list.map((j) => (
          <button
            key={j.name}
            onClick={() => onPick(j.name, j.module)}
            className="w-full flex justify-between gap-2.5 border-0 bg-transparent rounded-[9px] px-3 py-2.5 text-left hover:bg-page"
          >
            <div className="flex flex-col gap-0.5 min-w-0">
              <span className="font-mono text-[13px]">{j.name}</span>
              <span className="text-[13px] text-muted">{j.summary}</span>
            </div>
            <span className="font-mono text-[11px] text-muted shrink-0">{j.module}</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}
