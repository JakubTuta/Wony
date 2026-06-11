import { useState } from 'react';
import { AlertTriangle, AlertCircle, X, ChevronDown, ChevronUp } from 'lucide-react';
import type { Diagnostic } from '../api';

interface Props {
  diagnostics: Diagnostic[];
}

export function DiagnosticsBanner({ diagnostics }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const visible = diagnostics.filter(
    (d) =>
      (d.level === 'warning' || d.level === 'error') &&
      !dismissed.has(`${d.source}:${d.message}`),
  );

  if (visible.length === 0) return null;

  function dismiss(d: Diagnostic) {
    setDismissed((prev) => new Set(prev).add(`${d.source}:${d.message}`));
  }

  function toggleExpand(d: Diagnostic) {
    const key = `${d.source}:${d.message}`;
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-1 px-3 pt-2 pb-1">
      {visible.map((d) => {
        const key = `${d.source}:${d.message}`;
        const isError = d.level === 'error';
        const isExpanded = expanded.has(key);

        return (
          <div
            key={key}
            className={`rounded-lg border text-xs ${
              isError
                ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-700 text-red-800 dark:text-red-200'
                : 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-700 text-amber-800 dark:text-amber-200'
            }`}
          >
            <div className="flex items-start gap-2 px-3 py-2">
              {isError ? (
                <AlertCircle size={13} className="mt-0.5 shrink-0" />
              ) : (
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <span className="font-medium">{d.source}: </span>
                <span>{d.message}</span>
                {d.hint && (
                  <button
                    onClick={() => toggleExpand(d)}
                    className="ml-2 inline-flex items-center gap-0.5 opacity-70 hover:opacity-100 transition-opacity"
                  >
                    {isExpanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                    fix
                  </button>
                )}
                {d.hint && isExpanded && (
                  <p className="mt-1 opacity-80 font-mono text-[11px] break-words">{d.hint}</p>
                )}
              </div>
              <button
                onClick={() => dismiss(d)}
                className="shrink-0 opacity-50 hover:opacity-100 transition-opacity ml-1"
                aria-label="Dismiss"
              >
                <X size={12} />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
