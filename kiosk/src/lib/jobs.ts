import { fetchJobs } from '../api'
import type { Job } from '../api'

let cache: Job[] | null = null
let inflight: Promise<Job[]> | null = null

/** The job catalog, fetched once and reused — it only changes when Wony
 *  restarts, which a page load already implies. */
export async function loadJobs(): Promise<Job[]> {
  if (cache) return cache
  if (!inflight) {
    inflight = fetchJobs().then((jobs) => {
      cache = jobs
      return jobs
    })
  }
  return inflight
}

/** Whether this call needs the confirm sheet, per the job catalog's `confirms`
 *  flag and gate words — the generic rule for anything invoked through
 *  /api/invoke. Device controls on this panel are a deliberate exception: see
 *  needsDeviceConfirm in lib/devices.ts. */
export function needsConfirm(job: Job | undefined, args: Record<string, unknown> = {}): boolean {
  if (!job || !job.confirms) return false
  if (job.confirm_words === null) return true
  const action = String(args.action ?? '').trim().toLowerCase()
  return job.confirm_words.includes(action)
}

/** The mono signature shown on the confirm sheet, e.g. routine(name="briefing"). */
export function signature(name: string, args: Record<string, unknown> = {}): string {
  const parts = Object.entries(args)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${key}=${typeof value === 'string' ? `"${value}"` : String(value)}`)
  return `${name}(${parts.join(', ')})`
}
