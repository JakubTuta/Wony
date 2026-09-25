/* Shared skin matching design/README.md's tokens. One file so every view's
   card, pill and switch come from the same place instead of six copies
   drifting apart. */
import type { ReactNode } from 'react';

export const CARD = 'rounded-[14px] border border-border bg-surface';
export const MUTED = 'text-muted';

/** Loading, failed, or nothing-to-show — the three states every panel has.
 * (CLAUDE.md: "Every ending of an operation needs something to show for it.") */
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
    <h2 className="m-0 text-[13px] font-semibold uppercase tracking-[0.08em] text-label-red">
      {children}
    </h2>
  );
}

export function MonoChip({ children }: { children: ReactNode }) {
  return (
    <span className="font-mono text-[11px] rounded-md bg-teal-soft text-teal px-1.5 py-1">
      {children}
    </span>
  );
}

export function Pill({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'pink' | 'teal' | 'error' | 'message';
}) {
  const tones: Record<string, string> = {
    neutral: 'bg-[#EEF2F2] text-muted',
    pink: 'bg-pink-soft text-red',
    teal: 'bg-teal-soft text-teal',
    error: 'bg-badge text-white',
    message: 'bg-pink-faint-2 text-label-red',
  };
  return (
    <span className={`text-xs font-semibold rounded-full px-2.5 py-1 ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Switch({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onChange}
      className="shrink-0 w-11 h-[26px] rounded-full border-0 p-[3px] flex disabled:opacity-40 transition-colors"
      style={{
        background: checked ? 'var(--color-accent)' : 'var(--color-switch-off)',
        justifyContent: checked ? 'flex-end' : 'flex-start',
      }}
    >
      <span className="w-5 h-5 rounded-full bg-white" />
    </button>
  );
}

type ButtonVariant = 'accent' | 'soft' | 'ghost';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  accent: 'bg-accent text-on-accent hover:brightness-95',
  soft: 'bg-teal-soft text-teal hover:brightness-95',
  ghost: 'bg-transparent text-red hover:bg-pink-faint',
};

export function Button({
  children,
  onClick,
  variant = 'accent',
  disabled,
  type = 'button',
  className = '',
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  type?: 'button' | 'submit';
  className?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`border-0 rounded-[9px] px-4 py-2 text-sm font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed ${BUTTON_VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Modal({ children, onClose }: { children: ReactNode; onClose?: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: 'rgba(16,43,47,0.45)' }}
      onClick={onClose}
    >
      <div
        className="bg-surface rounded-2xl w-full max-w-[420px] flex flex-col gap-3.5 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
