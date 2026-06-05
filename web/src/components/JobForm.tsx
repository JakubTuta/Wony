import { useState } from 'react';
import { AlertTriangle, Loader2, X } from 'lucide-react';
import type { Job } from '../api';
import { invokeJob } from '../api';

interface Props {
  job: Job;
  onClose: () => void;
}

export function JobForm({ job, onClose }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const props = job.parameters.properties;
  const required = new Set(job.parameters.required);
  const hasParams = Object.keys(props).length > 0;

  function set(key: string, val: string) {
    setValues(prev => ({ ...prev, [key]: val }));
    setResult(null);
  }

  async function submit() {
    setLoading(true);
    setResult(null);
    try {
      const res = await invokeJob(job.name, values);
      setResult({ ok: res.ok, text: res.ok ? res.result : (res.error ?? 'Unknown error') });
    } finally {
      setLoading(false);
    }
    setConfirming(false);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (job.destructive) {
      setConfirming(true);
    } else {
      submit();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-lg border border-gray-200 dark:border-gray-700">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-800">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {humanize(job.name)}
            </h2>
            {job.description && (
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">
                {job.description}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors ml-4 shrink-0"
          >
            <X size={18} />
          </button>
        </div>

        {/* Destructive warning */}
        {job.destructive && (
          <div className="mx-6 mt-4 flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 px-3 py-2.5 text-sm text-amber-800 dark:text-amber-300">
            <AlertTriangle size={15} className="shrink-0 mt-0.5" />
            <span>This action may be irreversible or affect the host system. A confirmation is required.</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {!hasParams && (
            <p className="text-sm text-gray-500 dark:text-gray-400 italic">No parameters required.</p>
          )}
          {Object.entries(props).map(([key, param]) => {
            const isRequired = required.has(key);
            const inputId = `param-${key}`;
            return (
              <div key={key} className="space-y-1">
                <label htmlFor={inputId} className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  {humanize(key)}
                  {isRequired && <span className="text-red-500 ml-1">*</span>}
                  <span className="ml-2 text-xs font-normal text-gray-400 dark:text-gray-500">
                    {param.type}
                  </span>
                </label>
                {param.description && param.description !== 'No description available' && (
                  <p className="text-xs text-gray-400 dark:text-gray-500">{param.description}</p>
                )}
                {param.type === 'boolean' ? (
                  <div className="flex items-center gap-2">
                    <input
                      id={inputId}
                      type="checkbox"
                      checked={values[key] === 'true'}
                      onChange={e => set(key, e.target.checked ? 'true' : 'false')}
                      className="rounded border-gray-300 dark:border-gray-600 text-violet-600 focus:ring-violet-500"
                    />
                    <span className="text-sm text-gray-600 dark:text-gray-400">
                      {values[key] === 'true' ? 'Yes' : 'No'}
                    </span>
                  </div>
                ) : (
                  <input
                    id={inputId}
                    type={param.type === 'integer' || param.type === 'number' ? 'number' : 'text'}
                    step={param.type === 'number' ? 'any' : undefined}
                    value={values[key] ?? ''}
                    onChange={e => set(key, e.target.value)}
                    required={isRequired}
                    placeholder={isRequired ? 'Required' : 'Optional'}
                    className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent transition"
                  />
                )}
              </div>
            );
          })}

          {/* Result */}
          {result && (
            <div
              className={`rounded-lg px-3 py-2.5 text-sm font-mono whitespace-pre-wrap break-all max-h-40 overflow-y-auto ${
                result.ok
                  ? 'bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-300 border border-green-200 dark:border-green-700'
                  : 'bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-300 border border-red-200 dark:border-red-700'
              }`}
            >
              {result.text || '(no output)'}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
            >
              Close
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm rounded-lg bg-violet-600 text-white font-medium hover:bg-violet-700 disabled:opacity-60 disabled:cursor-not-allowed transition flex items-center gap-1.5"
            >
              {loading && <Loader2 size={14} className="animate-spin" />}
              Run
            </button>
          </div>
        </form>
      </div>

      {/* Destructive confirm dialog */}
      {confirming && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60">
          <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl max-w-sm w-full mx-4 p-6 border border-amber-200 dark:border-amber-700">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle size={20} className="text-amber-500" />
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Confirm action</h3>
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              <strong className="text-gray-900 dark:text-gray-100">{humanize(job.name)}</strong> is
              a destructive operation. This may be irreversible. Proceed?
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirming(false)}
                className="px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
              >
                Cancel
              </button>
              <button
                onClick={submit}
                className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white font-medium hover:bg-red-700 transition"
              >
                Yes, proceed
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function humanize(str: string): string {
  return str.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
