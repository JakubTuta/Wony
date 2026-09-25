import { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, Plus, RotateCw, Star } from 'lucide-react';
import { fetchPanel, fetchSettings, invokeJob, saveSettings } from '../api';
import type { AccountsPanel, GoogleAccount, SettingField, SettingsResponse } from '../api';
import { useWony } from '../lib/wonyContext';
import { CARD, SectionLabel, Switch } from '../components/ui';

type Draft = Record<string, string | number | boolean | null>;

export function Settings() {
  const { requestConfirm, wipeAllData } = useWony();
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<'none' | 'ok' | 'restart'>('none');

  useEffect(() => {
    fetchSettings().then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error && !data) return <p className="px-8 text-sm text-red">{error}</p>;
  if (!data) return <p className="px-8 text-sm text-muted">…</p>;

  const dirty = Object.keys(draft).length > 0;
  const set = (key: string, value: string | number | boolean | null) => {
    setSaved('none');
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const result = await saveSettings(draft);
      setData(await fetchSettings());
      setDraft({});
      setSaved(result.restart_required ? 'restart' : 'ok');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const valueOf = (field: SettingField) => (field.key in draft ? draft[field.key] : field.value);

  return (
    <div className="px-8 pb-10 flex flex-col gap-6 max-w-2xl">
      {data.sections.map((section) => (
        <div key={section.title} className="flex flex-col gap-2">
          <SectionLabel>{section.title}</SectionLabel>
          <div className={`${CARD} divide-y`} style={{ borderColor: 'var(--color-border)' }}>
            {section.fields.map((field) => (
              <Row key={field.key} field={field} value={valueOf(field)} onChange={set} />
            ))}
          </div>
        </div>
      ))}

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
          <span className="flex items-center gap-1.5 text-xs text-red">
            <RotateCw size={13} /> Saved — restart Wony for all of it to take effect.
          </span>
        )}
      </div>

      <p className="text-[11px] text-muted">These are stored in {data.config_file}, which you can still edit by hand.</p>

      <Accounts />

      <div className="flex flex-col gap-2">
        <SectionLabel>Data</SectionLabel>
        <div className={`${CARD} p-4 flex items-center justify-between gap-3`}>
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold">Wipe all data</span>
            <span className="text-xs text-muted">Messages, saved facts, reminders, connected accounts and embeddings — gone for good.</span>
          </div>
          <button
            onClick={() =>
              requestConfirm({
                title: 'Wipe all data?',
                sig: 'wipe_data()',
                onConfirm: wipeAllData,
              })
            }
            className="border-0 bg-transparent text-red rounded-[9px] px-3.5 py-2 text-sm font-semibold shrink-0"
          >
            Wipe data
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({
  field,
  value,
  onChange,
}: {
  field: SettingField;
  value: string | number | boolean | null;
  onChange: (key: string, value: string | number | boolean | null) => void;
}) {
  const label = (
    <span className="min-w-0">
      <span className="block text-sm">
        {field.label}
        {field.restart && <span className="ml-1.5 text-[10px] uppercase tracking-wide text-muted">needs restart</span>}
      </span>
      {field.help && <span className="block text-xs text-muted">{field.help}</span>}
    </span>
  );

  if (field.kind === 'toggle') {
    return (
      <label className="flex items-start gap-3 px-3.5 py-3 cursor-pointer">
        <Switch checked={Boolean(value)} onChange={() => onChange(field.key, !value)} />
        {label}
      </label>
    );
  }

  return (
    <div className="px-3.5 py-3 flex flex-col gap-1.5">
      {label}
      {field.kind === 'choice' ? (
        <select value={String(value ?? '')} onChange={(e) => onChange(field.key, e.target.value)} className={inputClass}>
          {field.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : field.kind === 'longtext' ? (
        <textarea value={String(value ?? '')} rows={4} onChange={(e) => onChange(field.key, e.target.value)} className={`${inputClass} resize-y`} />
      ) : (
        <input
          type={field.kind === 'number' ? 'number' : 'text'}
          value={value === null || value === undefined ? '' : String(value)}
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.step ?? undefined}
          onChange={(e) => onChange(field.key, field.kind === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)}
          className={inputClass}
        />
      )}
    </div>
  );
}

const inputClass = 'w-full rounded-[9px] border px-2.5 py-2 text-sm bg-surface';

function Accounts() {
  const [panel, setPanel] = useState<AccountsPanel | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [working, setWorking] = useState('');
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetchPanel<AccountsPanel>('accounts').then((result) => {
      setPanel(result.data);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const run = async (name: string, args: Record<string, string>, waiting: string) => {
    setWorking(waiting);
    setNote(null);
    const result = await invokeJob(name, args);
    setWorking('');
    setNote(result.error ?? result.result);
    refresh();
  };

  if (loading || !panel) return null;

  return (
    <div className="flex flex-col gap-2">
      <SectionLabel>Google accounts</SectionLabel>
      <div className="flex flex-col gap-2.5">
        {!panel.credentials_ready && (
          <p className="text-xs text-red bg-pink-faint rounded-lg px-3 py-2">
            credentials/google_credentials.json is missing — download the OAuth client from Google Cloud Console first.
          </p>
        )}
        {working && <p className="text-xs text-muted bg-page rounded-lg px-3 py-2">{working}</p>}
        {note && (
          <button onClick={() => setNote(null)} className={`${CARD} text-left px-3 py-2`}>
            <p className="text-xs whitespace-pre-wrap">{note}</p>
          </button>
        )}

        {panel.accounts.map((account) => (
          <AccountRow
            key={account.name}
            account={account}
            services={panel.services}
            expanded={open === account.name}
            busy={!!working}
            onToggle={() => setOpen(open === account.name ? null : account.name)}
            onRun={run}
          />
        ))}

        {adding ? (
          <AddForm
            busy={!!working}
            onCancel={() => setAdding(false)}
            onAdd={async (name) => {
              setAdding(false);
              await run('manage_google_accounts', { action: 'add', name }, `Adding ${name} — finish signing in with Google in the browser window.`);
            }}
          />
        ) : (
          <button onClick={() => setAdding(true)} disabled={!!working} className={`${CARD} flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm text-teal disabled:opacity-40`}>
            <Plus size={15} />
            Add account
          </button>
        )}
      </div>
    </div>
  );
}

function AccountRow({
  account,
  services,
  expanded,
  busy,
  onToggle,
  onRun,
}: {
  account: GoogleAccount;
  services: { gmail: boolean; calendar: boolean };
  expanded: boolean;
  busy: boolean;
  onToggle: () => void;
  onRun: (name: string, args: Record<string, string>, waiting: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [rename, setRename] = useState('');
  const missing = (['gmail', 'calendar'] as const).filter((s) => services[s] && !account.tokens[s]);

  return (
    <div className={CARD}>
      <button onClick={onToggle} className="w-full text-left px-3 py-2.5 flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-sm flex items-center gap-1.5">
            {account.primary && <Star size={12} className="text-accent fill-accent shrink-0" />}
            {account.name}
          </div>
          <div className="text-xs text-muted truncate">
            {missing.length > 0 ? `Not signed in for ${missing.join(' and ')}` : account.email || 'Signed in'}
          </div>
        </div>
      </button>
      {expanded && (
        <div className="px-3 pb-3 flex flex-col gap-1.5" style={{ borderTop: '1px solid var(--color-divider)', paddingTop: 10 }}>
          <SmallAction busy={busy} onClick={() => onRun('manage_google_accounts', { action: 'authorize', name: account.name }, `Signing in ${account.name} — finish in the browser window.`)}>
            Sign in again
          </SmallAction>
          {!account.primary && (
            <SmallAction busy={busy} onClick={() => onRun('manage_google_accounts', { action: 'set_primary', name: account.name }, 'Setting default…')}>
              Make this the default account
            </SmallAction>
          )}
          <div className="flex gap-1.5">
            <input value={rename} onChange={(e) => setRename(e.target.value)} placeholder="New name" className={`${inputClass} flex-1`} />
            <SmallAction
              busy={busy || !rename.trim()}
              onClick={() => {
                onRun('manage_google_accounts', { action: 'rename', name: account.name, new_name: rename.trim() }, 'Renaming…');
                setRename('');
              }}
            >
              Rename
            </SmallAction>
          </div>
          {confirming ? (
            <div className="flex gap-1.5">
              <SmallAction
                busy={busy}
                danger
                onClick={() => {
                  setConfirming(false);
                  onRun('manage_google_accounts', { action: 'remove', name: account.name }, 'Removing…');
                }}
              >
                Yes, remove it
              </SmallAction>
              <SmallAction busy={busy} onClick={() => setConfirming(false)}>Cancel</SmallAction>
            </div>
          ) : (
            <SmallAction busy={busy} danger onClick={() => setConfirming(true)}>Remove account</SmallAction>
          )}
        </div>
      )}
    </div>
  );
}

function AddForm({ busy, onAdd, onCancel }: { busy: boolean; onAdd: (name: string) => void; onCancel: () => void }) {
  const [name, setName] = useState('');
  return (
    <div className={`${CARD} p-3 flex flex-col gap-2`}>
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Short label — work, personal" className={inputClass} />
      <p className="text-xs text-muted">A browser window opens for you to sign in with Google.</p>
      <div className="flex gap-1.5">
        <SmallAction busy={busy || !name.trim()} onClick={() => onAdd(name.trim())}>Add and sign in</SmallAction>
        <SmallAction busy={busy} onClick={onCancel}>Cancel</SmallAction>
      </div>
    </div>
  );
}

function SmallAction({ children, onClick, busy, danger = false }: { children: React.ReactNode; onClick: () => void; busy: boolean; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="px-3 py-1.5 rounded-lg border text-xs disabled:opacity-40"
      style={{ borderColor: danger ? 'var(--color-pink-border-2)' : 'var(--color-border)', color: danger ? 'var(--color-red)' : 'var(--color-muted)' }}
    >
      {children}
    </button>
  );
}
