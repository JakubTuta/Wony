import { useEffect, useState } from 'react'
import { Check, Download, RotateCw, TriangleAlert } from 'lucide-react'
import { checkUpdates, fetchSettings, saveSettings } from '../api'
import type { SettingField, SettingsResponse } from '../api'
import { Keyboard } from '../components/Keyboard'
import { useWony } from '../state/wony-context'

type Draft = Record<string, string | number | boolean | null>

/** Everything in config.yaml that a person should be able to change, on the
 *  screen itself.
 *
 *  The Pi has no keyboard and no text editor. Without this, switching the AI
 *  provider or allowing Wony to send email means finding another computer and
 *  editing a file over SSH.
 */
export function Settings() {
  const [data, setData] = useState<SettingsResponse | null>(null)
  const [draft, setDraft] = useState<Draft>({})
  const [modules, setModules] = useState<string[]>([])
  const [modulesTouched, setModulesTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<'none' | 'ok' | 'restart'>('none')
  const [update, setUpdate] = useState<string | null>(null)
  // Which text field the on-screen keyboard is currently typing into.
  const [typing, setTyping] = useState<SettingField | null>(null)

  useEffect(() => {
    fetchSettings()
      .then((loaded) => {
        setData(loaded)
        setModules(loaded.modules.filter((m) => m.enabled).map((m) => m.key))
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  if (error && !data) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-2 px-8">
        <TriangleAlert size={40} className="text-muted" />
        <p className="t-body text-muted">{error}</p>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="t-body text-muted">Reading settings…</p>
      </div>
    )
  }

  const dirty = Object.keys(draft).length > 0 || modulesTouched

  const set = (key: string, value: string | number | boolean | null) => {
    setSaved('none')
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const toggleModule = (key: string) => {
    setSaved('none')
    setModulesTouched(true)
    setModules((prev) =>
      prev.includes(key) ? prev.filter((m) => m !== key) : [...prev, key],
    )
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const result = await saveSettings(draft, modulesTouched ? modules : undefined)
      const fresh = await fetchSettings()
      setData(fresh)
      setModules(fresh.modules.filter((m) => m.enabled).map((m) => m.key))
      setDraft({})
      setModulesTouched(false)
      setSaved(result.restart_required ? 'restart' : 'ok')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const valueOf = (field: SettingField) =>
    field.key in draft ? draft[field.key] : field.value

  if (typing) {
    return (
      <TypeInto
        field={typing}
        value={String(valueOf(typing) ?? '')}
        onDone={(text) => {
          set(typing.key, text)
          setTyping(null)
        }}
        onCancel={() => setTyping(null)}
      />
    )
  }

  return (
    <div className="scroll-y flex-1 px-4 py-4 flex flex-col gap-5">
      {data.sections.map((section) => (
        <section key={section.title} className="flex flex-col gap-2">
          <h2 className="t-small text-muted uppercase tracking-wide px-1">
            {section.title}
          </h2>
          <div className="rounded-xl bg-surface border border-line divide-y divide-line">
            {section.fields.map((field) => (
              <Row
                key={field.key}
                field={field}
                value={valueOf(field)}
                onChange={set}
                onType={() => setTyping(field)}
              />
            ))}
          </div>
        </section>
      ))}

      <section className="flex flex-col gap-2">
        <h2 className="t-small text-muted uppercase tracking-wide px-1">Features</h2>
        <p className="t-small text-muted px-1">
          Switching one on needs its packages installed — run{' '}
          <code>python setup.py</code> if something stays unavailable. These take
          effect after a restart.
        </p>
        <div className="rounded-xl bg-surface border border-line divide-y divide-line">
          {data.modules.map((module) => (
            <button
              key={module.key}
              onClick={() => toggleModule(module.key)}
              className="w-full flex items-center gap-3 px-4 py-3 text-left active:scale-[0.99]"
            >
              <Switch checked={modules.includes(module.key)} />
              <span className="min-w-0">
                <span className="block t-body truncate">{module.label}</span>
                <span className="block t-small text-muted">{module.help}</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="t-small text-muted uppercase tracking-wide px-1">Updates</h2>
        <div className="rounded-xl bg-surface border border-line px-4 py-3 flex flex-col gap-2">
          <button
            onClick={async () => {
              setUpdate('Checking…')
              setUpdate(await checkUpdates())
            }}
            className="self-start flex items-center gap-2 px-4 py-2 rounded-xl
                       border border-line t-body active:scale-95"
          >
            <Download size={18} /> Check for updates
          </button>
          {update && <p className="t-small text-muted whitespace-pre-line">{update}</p>}
        </div>
      </section>

      {error && <p className="t-small text-red-500 px-1">{error}</p>}

      <div className="sticky bottom-0 -mx-4 px-4 py-3 bg-bg flex items-center gap-3">
        <button
          onClick={save}
          disabled={!dirty || saving}
          className="px-5 py-3 rounded-xl bg-accent text-bg t-body
                     disabled:opacity-40 active:scale-95"
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        {saved === 'ok' && (
          <span className="flex items-center gap-1.5 t-small text-muted">
            <Check size={16} /> Saved.
          </span>
        )}
        {saved === 'restart' && (
          <span className="flex items-center gap-1.5 t-small text-muted">
            <RotateCw size={16} /> Saved — restart Wony for all of it to apply.
          </span>
        )}
      </div>

      <p className="t-small text-muted px-1">
        These are stored in {data.config_file}, which you can still edit by hand.
      </p>
    </div>
  )
}

function Row({
  field,
  value,
  onChange,
  onType,
}: {
  field: SettingField
  value: string | number | boolean | null
  onChange: (key: string, value: string | number | boolean | null) => void
  onType: () => void
}) {
  const label = (
    <span className="min-w-0">
      <span className="block t-body">
        {field.label}
        {field.restart && (
          <span className="ml-2 t-small text-muted uppercase">needs restart</span>
        )}
      </span>
      {field.help && <span className="block t-small text-muted">{field.help}</span>}
    </span>
  )

  if (field.kind === 'toggle') {
    return (
      <button
        onClick={() => onChange(field.key, !value)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left active:scale-[0.99]"
      >
        <Switch checked={Boolean(value)} />
        {label}
      </button>
    )
  }

  if (field.kind === 'choice') {
    // A row of buttons, not a <select>: a native dropdown on a 7" touch screen
    // opens a list too small to hit reliably.
    return (
      <div className="px-4 py-3 flex flex-col gap-2">
        {label}
        <div className="flex flex-wrap gap-2">
          {field.choices.map((choice) => (
            <button
              key={choice}
              onClick={() => onChange(field.key, choice)}
              className={`px-4 py-2 rounded-xl border t-body active:scale-95 ${
                String(value ?? '') === choice
                  ? 'border-accent text-accent'
                  : 'border-line text-muted'
              }`}
            >
              {choice}
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (field.kind === 'number') {
    const step = field.step ?? 1
    const current = typeof value === 'number' ? value : Number(value ?? 0)
    const clamp = (next: number) => {
      const low = field.min ?? Number.NEGATIVE_INFINITY
      const high = field.max ?? Number.POSITIVE_INFINITY
      return Math.min(high, Math.max(low, Number(next.toFixed(3))))
    }
    return (
      <div className="px-4 py-3 flex items-center gap-3">
        {label}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          <Stepper label="−" onPress={() => onChange(field.key, clamp(current - step))} />
          <span className="t-body w-16 text-center tabular-nums">{current}</span>
          <Stepper label="+" onPress={() => onChange(field.key, clamp(current + step))} />
        </div>
      </div>
    )
  }

  return (
    <button
      onClick={onType}
      className="w-full px-4 py-3 flex items-center gap-3 text-left active:scale-[0.99]"
    >
      {label}
      <span className="ml-auto t-body text-muted truncate max-w-[40%]">
        {String(value ?? '') || 'not set'}
      </span>
    </button>
  )
}

function Stepper({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <button
      onClick={onPress}
      className="w-11 h-11 rounded-xl border border-line grid place-items-center
                 t-body active:scale-95"
    >
      {label}
    </button>
  )
}

function Switch({ checked }: { checked: boolean }) {
  return (
    <span
      role="switch"
      aria-checked={checked}
      className={`shrink-0 w-12 h-7 rounded-full relative transition-colors ${
        checked ? 'bg-accent' : 'bg-line'
      }`}
    >
      <span
        className="absolute top-1 w-5 h-5 rounded-full bg-bg transition-all"
        style={{ left: checked ? '1.75rem' : '0.25rem' }}
      />
    </span>
  )
}

/** The on-screen keyboard, filling the screen, for one text field. */
function TypeInto({
  field,
  value,
  onDone,
  onCancel,
}: {
  field: SettingField
  value: string
  onDone: (text: string) => void
  onCancel: () => void
}) {
  const { config } = useWony()
  const [text, setText] = useState(value)

  return (
    <div className="flex-1 flex flex-col">
      <div className="px-4 py-4 flex flex-col gap-1">
        <span className="t-body">{field.label}</span>
        {field.help && <span className="t-small text-muted">{field.help}</span>}
        <div className="mt-2 px-4 py-3 rounded-xl bg-surface border border-line min-h-[3.5rem]">
          <span className="t-body break-words">{text || '\u00a0'}</span>
        </div>
        <button
          onClick={onCancel}
          className="self-start mt-2 px-4 py-2 rounded-xl border border-line t-small text-muted active:scale-95"
        >
          Cancel
        </button>
      </div>
      <div className="mt-auto">
        <Keyboard
          value={text}
          language={config?.assistant.language || 'en'}
          onChange={setText}
          onSubmit={() => onDone(text)}
        />
      </div>
    </div>
  )
}
