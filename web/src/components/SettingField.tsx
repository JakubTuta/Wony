import type { SettingField as SettingFieldData } from '../api';
import { Switch } from './ui';

export type Draft = Record<string, string | number | boolean | null>;

export const inputClass = 'w-full rounded-[9px] border px-2.5 py-2 text-sm bg-surface';

/** One editable row for a SettingField — shared by the global Settings page
 * and a module's own config panel on Modules & jobs, so the two never grow
 * two different renderings of the same field kinds. */
export function SettingRow({
  field,
  value,
  onChange,
}: {
  field: SettingFieldData;
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

  if (field.kind === 'secret') {
    // The server never sends the real secret back — `value` is `true`/`false`
    // for whether one is set. Anything else is a new value waiting to be saved.
    const configured = value === true;
    const draftValue = typeof value === 'string' ? value : '';
    return (
      <div className="px-3.5 py-3 flex flex-col gap-1.5">
        {label}
        <input
          type="password"
          autoComplete="off"
          value={draftValue}
          placeholder={configured ? 'Set — enter a new value to replace it' : 'Not set'}
          onChange={(e) => onChange(field.key, e.target.value)}
          className={inputClass}
        />
      </div>
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
