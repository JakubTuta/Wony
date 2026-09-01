import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ChevronRight, Play, X } from 'lucide-react'
import { fetchJobs, invokeJob } from '../api'
import type { Job } from '../api'
import { Keyboard } from '../components/Keyboard'
import { useWony } from '../state/wony-context'

/** Every registered command, with its arguments.
 *
 *  Not a tile and not on the home screen: this is the surface for the thing
 *  you do twice a year, and for finding out why a module is quiet.
 */
export function Commands() {
  const { config } = useWony()
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState<Job | null>(null)

  useEffect(() => {
    fetchJobs()
      .then(setJobs)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const grouped = useMemo(() => {
    const byModule = new Map<string, Job[]>()
    for (const job of jobs) {
      const key = job.module || 'other'
      const list = byModule.get(key)
      if (list) list.push(job)
      else byModule.set(key, [job])
    }
    return [...byModule.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [jobs])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="t-body text-muted">Loading commands…</p>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="scroll-y flex-1 px-3 py-3 flex flex-col gap-5">
        {grouped.map(([module, list]) => (
          <div key={module}>
            <div className="t-small text-muted uppercase tracking-wide px-2 pb-2">
              {module}
            </div>
            <div className="flex flex-col gap-1.5">
              {list.map((job) => (
                <button
                  key={job.name}
                  onClick={() => setOpen(job)}
                  className="press list-row flex items-center gap-3 px-4 py-3 rounded-xl
                             bg-surface border border-line text-left"
                >
                  <div className="flex-1 min-w-0">
                    <div className="t-body truncate">{job.name.replace(/_/g, ' ')}</div>
                    {job.summary && (
                      <div className="t-small text-muted truncate">{job.summary}</div>
                    )}
                  </div>
                  {job.destructive && (
                    <AlertTriangle size={16} className="text-warn shrink-0" />
                  )}
                  <ChevronRight size={18} className="text-muted shrink-0" />
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {open && (
        <RunSheet
          job={open}
          language={config?.assistant.language || 'en'}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  )
}

function RunSheet({
  job,
  language,
  onClose,
}: {
  job: Job
  language: string
  onClose: () => void
}) {
  const fields = Object.entries(job.parameters.properties)
  const [values, setValues] = useState<Record<string, string>>({})
  const [activeField, setActiveField] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null)
  const [running, setRunning] = useState(false)

  const run = async () => {
    if (job.destructive && !confirming) {
      setConfirming(true)
      return
    }
    setRunning(true)
    setActiveField(null)
    try {
      const response = await invokeJob(job.name, values)
      setResult({
        text: response.ok ? response.result || 'Done.' : response.error || 'Failed.',
        ok: response.ok,
      })
    } finally {
      setRunning(false)
      setConfirming(false)
    }
  }

  return (
    <div className="absolute inset-0 z-30 flex flex-col justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/45" />

      <div
        className="sheet-in relative rounded-t-3xl bg-surface border-t border-line
                   max-h-[85%] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 px-5 pt-5 pb-2 shrink-0">
          <div className="flex-1 min-w-0">
            <div className="t-display truncate">{job.name.replace(/_/g, ' ')}</div>
            {job.summary && <p className="t-small text-muted">{job.summary}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="press flex items-center justify-center w-11 h-11 -mr-2 -mt-2 rounded-full text-muted"
          >
            <X size={22} />
          </button>
        </div>

        <div className="scroll-y flex-1 px-5 pb-3 flex flex-col gap-3">
          {fields.map(([name, spec]) => (
            <label key={name} className="flex flex-col gap-1">
              <span className="t-small text-muted">
                {name}
                {job.parameters.required.includes(name) ? ' *' : ''}
                {spec.type !== 'string' ? ` (${spec.type})` : ''}
              </span>
              {/* Typeable with a real keyboard as well as the on-screen one.
                  onFocus rather than onClick alone, so tabbing between fields
                  moves the on-screen keyboard with the caret. */}
              <input
                value={values[name] ?? ''}
                inputMode="none"
                onChange={(e) =>
                  setValues((current) => ({ ...current, [name]: e.target.value }))
                }
                onFocus={() => setActiveField(name)}
                onKeyDown={(e) => {
                  // Same as the on-screen Enter in this sheet: commit the
                  // field, do not fire the command. Running is one deliberate
                  // press of Run, which a destructive job asks about twice.
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    e.currentTarget.blur()
                    setActiveField(null)
                  }
                }}
                placeholder={spec.description || ''}
                className={`h-12 px-4 rounded-xl bg-surface-2 border t-body outline-none
                            placeholder:text-muted ${
                              activeField === name ? 'border-accent' : 'border-line'
                            }`}
              />
            </label>
          ))}

          {result && (
            <p
              className={`t-body selectable whitespace-pre-wrap pt-1 ${
                result.ok ? '' : 'text-danger'
              }`}
            >
              {result.text}
            </p>
          )}
        </div>

        <div className="px-5 pb-4 pt-1 shrink-0">
          <button
            onClick={run}
            disabled={running}
            className={`press w-full flex items-center justify-center gap-2 h-14 rounded-full
                        disabled:opacity-50 ${
                          confirming
                            ? 'bg-danger text-white'
                            : 'bg-accent text-on-accent'
                        }`}
          >
            <Play size={20} fill="currentColor" />
            <span className="t-body">
              {running ? 'Running…' : confirming ? 'Yes, really run it' : 'Run'}
            </span>
          </button>
        </div>

        {activeField && (
          <Keyboard
            value={values[activeField] ?? ''}
            language={language}
            onChange={(value) =>
              setValues((current) => ({ ...current, [activeField]: value }))
            }
            onSubmit={() => setActiveField(null)}
          />
        )}
      </div>
    </div>
  )
}
