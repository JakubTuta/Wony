import { invokeJob } from '../api'
import { useLive } from '../state/live-context'
import { useUi } from '../state/ui-context'
import { useWony } from '../state/wony-context'

const QUICK_TIMERS = [1, 5, 10, 15, 30, 60]

export function Macros() {
  const { runPrompt } = useWony()
  const { toast } = useUi()
  const { routines, reminders } = useLive()

  const runRoutine = (name: string) => {
    toast(`Running ${name}`)
    runPrompt(`run my ${name} routine`).then((res) => {
      if (!res.ok) toast(res.text || 'That did not work.')
    })
  }

  const startTimer = (minutes: number) => {
    const text = `${minutes} minute timer`
    invokeJob('add_reminder', { when: `in ${minutes} minutes`, text }).then(() =>
      reminders.refresh(),
    )
    toast(`${minutes} minute timer started`)
  }

  const list = routines.data?.routines ?? []

  return (
    <div className="h-full flex flex-col gap-3.5">
      <span className="t-label text-muted">Routines</span>

      {list.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[19px] text-muted">
            {routines.loaded ? 'No routines yet.' : 'Checking…'}
          </p>
        </div>
      ) : (
        <div
          className="scroll-y flex-1 min-h-0 grid grid-cols-3 gap-4"
          style={{ gridAutoRows: 'minmax(0, 1fr)' }}
        >
          {list.map((r) => (
            <button
              key={r.name}
              onClick={() => runRoutine(r.name)}
              className="press rounded-[28px] bg-surface px-6 py-[22px] flex flex-col justify-between text-left gap-2.5 min-h-[120px] overflow-hidden"
            >
              <span className="text-[28px] font-bold capitalize">{r.name}</span>
              <span className="text-[17px] text-muted leading-[1.35] line-clamp-2">{r.steps}</span>
            </button>
          ))}
        </div>
      )}

      <span className="t-label text-muted mt-1.5">Quick timers</span>
      <div className="grid grid-cols-6 gap-3 shrink-0">
        {QUICK_TIMERS.map((m) => (
          <button
            key={m}
            onClick={() => startTimer(m)}
            className="press h-22 rounded-3xl bg-surface-2 text-[26px] font-bold"
          >
            {m} min
          </button>
        ))}
      </div>
    </div>
  )
}
