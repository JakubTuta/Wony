/* Shared skin for the panels. Five files repeating the same six-class
   light/dark string is how they drift apart. */
import type { ReactNode } from 'react';

export const CARD =
  'rounded-xl border border-gray-200 dark:border-gray-700/60 bg-white dark:bg-gray-900';
export const MUTED = 'text-gray-500 dark:text-gray-400';

/** Loading, failed, or nothing-to-show — the three states every panel has. */
export function Resting({
  icon,
  title,
  children,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-2 px-8 py-10 text-center">
      {icon && <span className={MUTED}>{icon}</span>}
      <p className={`text-sm ${MUTED}`}>{title}</p>
      {children && <p className={`text-xs ${MUTED}`}>{children}</p>}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div
      className={`text-[11px] font-semibold uppercase tracking-wider mb-2 px-0.5 ${MUTED}`}
    >
      {children}
    </div>
  );
}

export function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`shrink-0 px-3 py-1 rounded-full border text-xs whitespace-nowrap transition-colors ${
        active
          ? 'border-violet-500 text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/20'
          : `border-gray-200 dark:border-gray-700 ${MUTED} hover:border-gray-300 dark:hover:border-gray-600`
      }`}
    >
      {label}
    </button>
  );
}

export function RoundButton({
  children,
  label,
  onClick,
  disabled,
  primary = false,
  active = false,
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  active?: boolean;
}) {
  const size = primary ? 'w-12 h-12' : 'w-9 h-9';
  const skin = primary
    ? 'bg-violet-600 text-white hover:bg-violet-500'
    : active
      ? 'border border-violet-500 text-violet-600 dark:text-violet-400'
      : `border border-gray-200 dark:border-gray-700 ${MUTED} hover:border-gray-300 dark:hover:border-gray-600`;

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`flex items-center justify-center rounded-full transition-colors
                  disabled:opacity-40 ${size} ${skin}`}
    >
      {children}
    </button>
  );
}
