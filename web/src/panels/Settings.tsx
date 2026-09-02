import { useEffect, useState } from 'react';
import { AlertTriangle, Check, Loader2, RotateCw, Settings as SettingsIcon } from 'lucide-react';
import { fetchSettings, saveSettings } from '../api';
import type { SettingField, SettingsResponse } from '../api';
import { CARD, MUTED, Resting, SectionLabel } from './ui';

type Draft = Record<string, string | number | boolean | null>;

/** The settings page.
 *
 *  Every value here also lives in config.yaml and can still be edited there;
 *  this exists so that changing the voice or turning off email sending does not
 *  require knowing that the file exists.
 */
export function Settings() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [modules, setModules] = useState<string[]>([]);
  const [modulesTouched, setModulesTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<'none' | 'ok' | 'restart'>('none');

  useEffect(() => {
    fetchSettings()
      .then((loaded) => {
        setData(loaded);
        setModules(loaded.modules.filter((m) => m.enabled).map((m) => m.key));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error && !data) {
    return (
      <Resting icon={<AlertTriangle size={30} />} title="Settings are unavailable">
        {error}
      </Resting>
    );
  }
  if (!data) return <Resting title="…" />;

  const dirty = Object.keys(draft).length > 0 || modulesTouched;

  const set = (key: string, value: string | number | boolean | null) => {
    setSaved('none');
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const toggleModule = (key: string) => {
    setSaved('none');
    setModulesTouched(true);
    setModules((prev) =>
      prev.includes(key) ? prev.filter((m) => m !== key) : [...prev, key],
    );
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const result = await saveSettings(draft, modulesTouched ? modules : undefined);
      const fresh = await fetchSettings();
      setData(fresh);
      setModules(fresh.modules.filter((m) => m.enabled).map((m) => m.key));
      setDraft({});
      setModulesTouched(false);
      setSaved(result.restart_required ? 'restart' : 'ok');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const valueOf = (field: SettingField) =>
    field.key in draft ? draft[field.key] : field.value;

  return (
    <div className="p-4 space-y-5">
      {data.sections.map((section) => (
        <div key={section.title}>
          <SectionLabel>{section.title}</SectionLabel>
          <div className={`${CARD} divide-y divide-gray-100 dark:divide-gray-800`}>
            {section.fields.map((field) => (
              <Row key={field.key} field={field} value={valueOf(field)} onChange={set} />
            ))}
          </div>
        </div>
      ))}

      <div>
        <SectionLabel>Features</SectionLabel>
        <p className={`text-xs ${MUTED} mb-2 px-0.5`}>
          Switching one on needs its packages installed — run <code>python setup.py</code> if
          something stays unavailable. Changes here apply after a restart.
        </p>
        <div className={`${CARD} divide-y divide-gray-100 dark:divide-gray-800`}>
          {data.modules.map((module) => (
            <label
              key={module.key}
              className="flex items-start gap-3 px-3 py-2.5 cursor-pointer"
            >
              <Switch
                checked={modules.includes(module.key)}
                onChange={() => toggleModule(module.key)}
              />
              <span className="min-w-0">
                <span className="block text-sm text-gray-800 dark:text-gray-200">
                  {module.label}
                </span>
                <span className={`block text-xs ${MUTED}`}>{module.help}</span>
              </span>
            </label>
          ))}
        </div>
      </div>

      {error && (
        <p className="text-xs text-red-600 dark:text-red-400 px-0.5">{error}</p>
      )}

      <div className="flex items-center gap-3 sticky bottom-0 py-3 bg-white dark:bg-gray-900">
        <button
          onClick={save}
          disabled={!dirty || saving}
          className="px-4 py-2 rounded-xl bg-violet-600 text-white text-sm font-medium
                     hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed
                     flex items-center gap-2 transition"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <SettingsIcon size={14} />}
          Save changes
        </button>
        {saved === 'ok' && (
          <span className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
            <Check size={13} /> Saved.
          </span>
        )}
        {saved === 'restart' && (
          <span className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
            <RotateCw size={13} /> Saved — restart Wony for all of it to take effect.
          </span>
        )}
      </div>

      <p className={`text-[11px] ${MUTED}`}>
        These are stored in {data.config_file}, which you can still edit by hand.
      </p>
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
      <span className="block text-sm text-gray-800 dark:text-gray-200">
        {field.label}
        {field.restart && (
          <span className={`ml-1.5 text-[10px] uppercase tracking-wide ${MUTED}`}>
            needs restart
          </span>
        )}
      </span>
      {field.help && <span className={`block text-xs ${MUTED}`}>{field.help}</span>}
    </span>
  );

  if (field.kind === 'toggle') {
    return (
      <label className="flex items-start gap-3 px-3 py-2.5 cursor-pointer">
        <Switch checked={Boolean(value)} onChange={() => onChange(field.key, !value)} />
        {label}
      </label>
    );
  }

  return (
    <div className="px-3 py-2.5 space-y-1.5">
      {label}
      {field.kind === 'choice' ? (
        <select
          value={String(value ?? '')}
          onChange={(e) => onChange(field.key, e.target.value)}
          className={inputClass}
        >
          {field.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : field.kind === 'longtext' ? (
        <textarea
          value={String(value ?? '')}
          rows={4}
          onChange={(e) => onChange(field.key, e.target.value)}
          className={`${inputClass} resize-y`}
        />
      ) : (
        <input
          type={field.kind === 'number' ? 'number' : 'text'}
          value={value === null || value === undefined ? '' : String(value)}
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.step ?? undefined}
          onChange={(e) =>
            onChange(
              field.key,
              field.kind === 'number' && e.target.value !== ''
                ? Number(e.target.value)
                : e.target.value,
            )
          }
          className={inputClass}
        />
      )}
    </div>
  );
}

const inputClass =
  'w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 ' +
  'px-2.5 py-1.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none ' +
  'focus:ring-2 focus:ring-violet-500 focus:border-transparent';

function Switch({ checked, onChange }: { checked: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onChange}
      className={`shrink-0 mt-0.5 w-9 h-5 rounded-full transition-colors relative ${
        checked ? 'bg-violet-600' : 'bg-gray-300 dark:bg-gray-600'
      }`}
    >
      <span
        className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all"
        style={{ left: checked ? '1.125rem' : '0.125rem' }}
      />
    </button>
  );
}
