import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { iconForModule } from './icons';
import { JobForm } from './JobForm';
import type { Job } from '../api';

interface Props {
  job: Job;
}

const MODULE_COLORS: Record<string, string> = {
  gmail: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
  calendar: 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
  weather: 'bg-sky-100 text-sky-600 dark:bg-sky-900/30 dark:text-sky-400',
  spotify: 'bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400',
  web: 'bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400',
  desktop: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
  basics: 'bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400',
  ai: 'bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400',
  scheduler: 'bg-yellow-100 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400',
  shelly: 'bg-teal-100 text-teal-600 dark:bg-teal-900/30 dark:text-teal-400',
  league: 'bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400',
  status: 'bg-cyan-100 text-cyan-600 dark:bg-cyan-900/30 dark:text-cyan-400',
};

function moduleColor(module: string): string {
  return MODULE_COLORS[module.toLowerCase()] ?? 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
}

function humanize(str: string): string {
  return str.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function typeBadge(type: string): string {
  const map: Record<string, string> = {
    integer: 'int',
    number: 'num',
    boolean: 'bool',
    array: 'list',
    object: 'obj',
  };
  return map[type] ?? type;
}

export function JobCard({ job }: Props) {
  const [open, setOpen] = useState(false);
  const Icon = iconForModule(job.module);
  const color = moduleColor(job.module);
  const props = job.parameters.properties;
  const required = new Set(job.parameters.required);
  const paramEntries = Object.entries(props);
  const displayText = job.summary || job.description;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={`group w-full text-left rounded-xl border bg-white dark:bg-gray-900 p-4 transition-all duration-150
          hover:shadow-md hover:-translate-y-0.5
          ${job.destructive
            ? 'border-amber-200 dark:border-amber-700/60 hover:border-amber-300 dark:hover:border-amber-600'
            : 'border-gray-200 dark:border-gray-700/60 hover:border-gray-300 dark:hover:border-gray-600'
          }`}
      >
        {/* Header row */}
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className={`shrink-0 rounded-lg p-2 ${color}`}>
            <Icon size={18} />
          </div>

          {/* Title + module chip */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm text-gray-900 dark:text-gray-100 leading-tight">
                {humanize(job.name)}
              </span>
              {job.module && (
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${color}`}>
                  {job.module}
                </span>
              )}
              {job.destructive && (
                <span className="flex items-center gap-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
                  <AlertTriangle size={11} />
                  destructive
                </span>
              )}
            </div>

            {/* Description */}
            {displayText && (
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 line-clamp-2 leading-relaxed">
                {displayText}
              </p>
            )}
          </div>
        </div>

        {/* Parameter pills */}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {paramEntries.length === 0 ? (
            <span className="text-[11px] text-gray-400 dark:text-gray-500 italic">No parameters</span>
          ) : (
            paramEntries.map(([key, param]) => (
              <span
                key={key}
                className="inline-flex items-center gap-1 rounded-md bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-[11px] text-gray-600 dark:text-gray-400 font-mono"
              >
                {key}
                {required.has(key) && <span className="text-red-400 font-sans">*</span>}
                <span className="text-gray-400 dark:text-gray-500 font-sans">
                  {typeBadge(param.type)}
                </span>
              </span>
            ))
          )}
        </div>
      </button>

      {open && <JobForm job={job} onClose={() => setOpen(false)} />}
    </>
  );
}
