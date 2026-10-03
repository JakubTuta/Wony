import { useState } from 'react';
import { Loader2, Check, RotateCw } from 'lucide-react';
import { saveSettings } from '../api';
import { useWony } from '../lib/wonyContext';
import { confirmLabel, humanize, isWidgetCovered } from '../lib/jobs';
import { CARD, Pill, SectionLabel, Switch } from '../components/ui';
import { SettingRow, type Draft } from '../components/SettingField';
import { RestartButton } from '../components/RestartButton';
import type { Job, SettingField } from '../api';

const STATUS_LABEL: Record<string, string> = {
  enabled: 'Enabled',
  disabled: 'Disabled',
  misconfigured: 'Misconfigured',
  unavailable: 'Unavailable',
  error: 'Error',
};

export function Modules({
  selectedModule,
  onSelectModule,
}: {
  selectedModule: string | null;
  onSelectModule: (key: string) => void;
}) {
  const { jobs, settings, health, reloadHealth, reloadSettings, runJob } = useWony();
  const [query, setQuery] = useState('');
  const [restartNoticeFor, setRestartNoticeFor] = useState<string | null>(null);

  const modules = settings?.modules ?? [];
  const q = query.trim().toLowerCase();

  const filtered = modules.filter((m) => {
    if (!q) return true;
    if (m.label.toLowerCase().includes(q) || m.key.includes(q)) return true;
    return jobs.some((j) => j.module === m.key && j.name.includes(q));
  });

  const active = modules.find((m) => m.key === selectedModule) ?? modules[0];
  const status = active ? health?.modules[active.key]?.status ?? 'disabled' : 'disabled';
  const jobsForModule = active ? jobs.filter((j) => j.module === active.key) : [];
  const moduleFields = active
    ? (settings?.sections ?? []).flatMap((s) => s.fields).filter((f) => f.module === active.key)
    : [];

  const dotColor = (m: (typeof modules)[number]) => {
    if (m.always_on) return 'var(--color-ok)';
    const st = health?.modules[m.key]?.status ?? 'disabled';
    if (st === 'enabled') return 'var(--color-ok)';
    if (st === 'disabled') return '#B4C2C4';
    return 'var(--color-accent)';
  };

  const toggleModule = (key: string) => {
    const enabledKeys = modules.filter((m) => !m.always_on && m.enabled).map((m) => m.key);
    const next = enabledKeys.includes(key) ? enabledKeys.filter((k) => k !== key) : [...enabledKeys, key];
    setRestartNoticeFor(key);
    saveSettings({}, next).then(reloadSettings);
  };

  const retry = () => {
    if (!active) return;
    runJob('system_status', { scope: 'retry' }, { from: 'Features' }).then(reloadHealth);
  };

  return (
    <div className="px-8 pb-10 grid gap-4 items-start" style={{ gridTemplateColumns: 'minmax(220px, 300px) minmax(0, 1fr)' }}>
      <div
        className="bg-surface border border-border rounded-[14px] p-2.5 flex flex-col gap-0.5 sticky overflow-auto"
        style={{ top: 76, maxHeight: 'calc(100vh - 96px)' }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search features or commands"
          className="border rounded-[9px] px-2.5 py-2 text-sm mb-2"
          style={{ borderColor: 'var(--color-border)' }}
        />
        {filtered.map((m) => (
          <button
            key={m.key}
            onClick={() => onSelectModule(m.key)}
            className="grid gap-2.5 items-center border-0 rounded-[9px] px-2.5 py-2.5 text-left"
            style={{
              gridTemplateColumns: '10px 1fr auto',
              background: active?.key === m.key ? 'var(--color-teal-soft)' : 'transparent',
            }}
          >
            <span className="w-2 h-2 rounded-full" style={{ background: dotColor(m) }} />
            <span className="text-sm font-medium truncate">{m.label}</span>
            <span className="font-mono text-[11px] text-muted">{jobs.filter((j) => j.module === m.key).length}</span>
          </button>
        ))}
      </div>

      {active && (
        <div className="flex flex-col gap-3 min-w-0">
          <div className={`${CARD} p-5 flex flex-col gap-3`}>
            <div className="flex justify-between items-start gap-4 flex-wrap">
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl font-bold">{active.label}</span>
                </div>
                <span className="text-sm text-muted max-w-[560px]">{active.help}</span>
              </div>
              <div className="flex items-center gap-2.5">
                <Pill tone={active.always_on || status === 'enabled' ? 'teal' : status === 'disabled' ? 'neutral' : 'pink'}>
                  {active.always_on ? 'Always on' : STATUS_LABEL[status] ?? status}
                </Pill>
                {!active.always_on && (
                  <Switch checked={active.enabled} onChange={() => toggleModule(active.key)} label={`Turn ${active.label} on or off`} />
                )}
              </div>
            </div>
            {restartNoticeFor === active.key && (
              <div className="flex items-center gap-2.5">
                <Pill tone="pink">Restart to apply</Pill>
                <RestartButton />
              </div>
            )}
            {!active.always_on && (status === 'misconfigured' || status === 'error' || status === 'unavailable') && (
              <div className="flex justify-between items-center gap-3 flex-wrap px-3.5 py-3 rounded-[10px] bg-pink-soft">
                <div className="flex flex-col gap-1">
                  <span className="text-sm font-semibold text-red">{health?.modules[active.key]?.reason}</span>
                  {health?.modules[active.key]?.hint && (
                    <span className="font-mono text-xs text-red">{health.modules[active.key].hint}</span>
                  )}
                </div>
                <button onClick={retry} className="border-0 bg-accent text-on-accent rounded-[9px] px-3.5 py-2 text-sm font-semibold">
                  Retry
                </button>
              </div>
            )}
          </div>

          {active.enabled && <ModuleConfigFields key={active.key} fields={moduleFields} />}

          {jobsForModule.length === 0 ? (
            <p className="text-sm text-muted px-1">
              {active.always_on || active.enabled ? 'No commands available.' : 'Turn this feature on to use its commands.'}
            </p>
          ) : (
            jobsForModule.map((job) => <JobRow key={job.name} job={job} />)
          )}
        </div>
      )}
    </div>
  );
}

/** A module's own settings fields (see helpers/settings.py's `module=`),
 * so turning a module on and configuring what it needs both happen on this
 * one page instead of sending the user to Settings for half of it. */
function ModuleConfigFields({ fields }: { fields: SettingField[] }) {
  const { reloadSettings } = useWony();
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<'none' | 'ok' | 'restart'>('none');

  if (fields.length === 0) return null;

  const dirty = Object.keys(draft).length > 0;
  const set = (key: string, value: string | number | boolean | null) => {
    setSaved('none');
    setDraft((prev) => ({ ...prev, [key]: value }));
  };
  const valueOf = (field: SettingField) => (field.key in draft ? draft[field.key] : field.value);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const result = await saveSettings(draft);
      setDraft({});
      setSaved(result.restart_required ? 'restart' : 'ok');
      reloadSettings();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`${CARD} p-5 flex flex-col gap-3`}>
      <SectionLabel>Configuration</SectionLabel>
      <div className="divide-y" style={{ borderColor: 'var(--color-border)' }}>
        {fields.map((field) => (
          <SettingRow key={field.key} field={field} value={valueOf(field)} onChange={set} />
        ))}
      </div>
      {error && <p className="text-xs text-red">{error}</p>}
      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={!dirty || saving}
          className="border-0 bg-accent text-on-accent rounded-[9px] px-4 py-2.5 text-sm font-semibold disabled:opacity-40 flex items-center gap-2"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : null}
          Save changes
        </button>
        {saved === 'ok' && (
          <span className="flex items-center gap-1.5 text-xs text-ok">
            <Check size={13} /> Saved.
          </span>
        )}
        {saved === 'restart' && (
          <>
            <span className="flex items-center gap-1.5 text-xs text-red">
              <RotateCw size={13} /> Saved — restart Wony for all of it to take effect.
            </span>
            <RestartButton />
          </>
        )}
      </div>
    </div>
  );
}

function JobRow({ job }: { job: Job }) {
  const { pins, setPins, runJob } = useWony();
  const [open, setOpen] = useState(false);
  const [args, setArgs] = useState<Record<string, unknown>>({});

  const paramNames = Object.keys(job.parameters.properties);
  const sig = `${job.name}(${paramNames.join(', ')})`;
  const pinned = (pins ?? []).some((p) => p.job === job.name);
  const covered = isWidgetCovered(job.name);
  const label = confirmLabel(job.confirms);

  const set = (key: string, value: unknown) => setArgs((prev) => ({ ...prev, [key]: value }));

  const cleaned = (): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(args)) {
      if (v === '' || v === undefined) continue;
      out[k] = v;
    }
    return out;
  };

  return (
    <div className={`${CARD} overflow-hidden`}>
      <button onClick={() => setOpen((v) => !v)} className="w-full flex justify-between items-center gap-3 border-0 bg-transparent px-4.5 py-3.5 text-left">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="font-mono text-sm font-medium">{sig}</span>
          <span className="text-sm text-muted">{job.summary}</span>
        </div>
        <div className="flex gap-2 items-center shrink-0">
          {label && <Pill tone="pink">{label}</Pill>}
          {pinned && <Pill tone="teal">Pinned</Pill>}
          <span className="text-muted text-[13px]">{open ? '▲' : '▼'}</span>
        </div>
      </button>
      {open && (
        <div className="flex flex-col gap-3.5 px-4.5 py-4" style={{ borderTop: '1px solid var(--color-divider)', background: '#FAFCFC' }}>
          {paramNames.length > 0 && (
            <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
              {paramNames.map((name) => {
                const spec = job.parameters.properties[name];
                const required = job.parameters.required.includes(name);
                return (
                  <label key={name} className="flex flex-col gap-1.5">
                    <span className="font-mono text-xs text-muted">
                      {name}
                      {required ? ' · required' : ''}
                    </span>
                    <ParamInput spec={spec} value={args[name]} onChange={(v) => set(name, v)} />
                  </label>
                );
              })}
            </div>
          )}
          <div className="flex gap-2">
            <button
              onClick={() => runJob(job.name, cleaned(), { from: 'Features' })}
              className="border-0 bg-accent text-on-accent rounded-[9px] px-4 py-2.5 text-sm font-semibold"
            >
              Run
            </button>
            <button
              onClick={() => {
                if (pinned || !pins || covered) return;
                setPins([...pins, { id: `${job.name}-${Date.now()}`, kind: 'run', job: job.name, module: job.module, title: humanize(job.name), args: cleaned() }]);
              }}
              disabled={pinned || covered}
              title={covered ? 'Already shown on a dashboard widget' : undefined}
              className="border-0 bg-teal-soft text-teal rounded-[9px] px-4 py-2.5 text-sm font-semibold disabled:opacity-50"
            >
              {pinned ? 'Pinned to dashboard' : covered ? 'Already on dashboard' : 'Pin to dashboard'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ParamInput({
  spec,
  value,
  onChange,
}: {
  spec: Job['parameters']['properties'][string];
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const base = 'border rounded-[9px] px-2.5 py-2 text-sm bg-surface';
  const style = { borderColor: 'var(--color-border)' };

  if (spec.enum) {
    return (
      <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} className={base} style={style}>
        <option value="">Choose…</option>
        {spec.enum.map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {String(opt)}
          </option>
        ))}
      </select>
    );
  }
  if (spec.type === 'boolean') {
    return <Switch checked={Boolean(value)} onChange={() => onChange(!value)} />;
  }
  if (spec.type === 'integer' || spec.type === 'number') {
    return (
      <input
        type="number"
        value={value === undefined ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        className={base}
        style={style}
      />
    );
  }
  if (spec.type === 'object' || spec.type === 'array') {
    return (
      <input
        value={value === undefined ? '' : String(value)}
        placeholder={spec.type === 'array' ? 'comma,separated' : '{"key": "value"}'}
        onChange={(e) => onChange(e.target.value)}
        className={base}
        style={style}
      />
    );
  }
  return (
    <input
      value={value === undefined ? '' : String(value)}
      placeholder={spec.description}
      onChange={(e) => onChange(e.target.value)}
      className={base}
      style={style}
    />
  );
}
