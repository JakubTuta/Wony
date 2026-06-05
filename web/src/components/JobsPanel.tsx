import { useState, useMemo } from 'react';
import { Search } from 'lucide-react';
import { JobCard } from './JobCard';
import type { Job } from '../api';

interface Props {
  jobs: Job[];
  loading: boolean;
}

export function JobsPanel({ jobs, loading }: Props) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    if (!query.trim()) return jobs;
    const q = query.toLowerCase();
    return jobs.filter(
      j =>
        j.name.toLowerCase().includes(q) ||
        j.summary.toLowerCase().includes(q) ||
        j.description.toLowerCase().includes(q) ||
        j.module.toLowerCase().includes(q),
    );
  }, [jobs, query]);

  const grouped = useMemo(() => {
    const map = new Map<string, Job[]>();
    for (const job of filtered) {
      const mod = job.module || 'general';
      if (!map.has(mod)) map.set(mod, []);
      map.get(mod)!.push(job);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [filtered]);

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="px-4 pb-3 pt-4 border-b border-gray-100 dark:border-gray-800">
        <div className="relative">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
          />
          <input
            type="text"
            placeholder="Search jobs…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent transition"
          />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-5">
        {loading && (
          <div className="flex items-center justify-center py-12 text-gray-400 dark:text-gray-500 text-sm">
            Loading jobs…
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="flex items-center justify-center py-12 text-gray-400 dark:text-gray-500 text-sm">
            {query ? 'No jobs match your search.' : 'No jobs available.'}
          </div>
        )}

        {!loading &&
          grouped.map(([module, moduleJobs]) => (
            <section key={module}>
              <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2 px-0.5">
                {module}
              </h3>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {moduleJobs.map(job => (
                  <JobCard key={job.name} job={job} />
                ))}
              </div>
            </section>
          ))}
      </div>
    </div>
  );
}
