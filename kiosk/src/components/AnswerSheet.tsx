import { X } from 'lucide-react'

/** A tile's answer, over the home screen rather than instead of it.
 *
 *  A job tile answers in about the time it takes to lift a finger. Navigating
 *  to a result screen and back would take longer than the answer did. */
export function AnswerSheet({
  title,
  text,
  ok,
  onClose,
}: {
  title: string
  text: string
  ok: boolean
  onClose: () => void
}) {
  return (
    <div className="absolute inset-0 z-30 flex flex-col justify-end" onClick={onClose}>
      <div
        className="absolute inset-0 bg-black/45"
        style={{ animation: 'wony-fade-up 180ms var(--ease-out-soft) both' }}
      />

      <div
        className="sheet-in relative rounded-t-3xl bg-surface border-t border-line
                   max-h-[70%] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 px-5 pt-5 pb-3">
          <div className="flex-1 min-w-0">
            <div className="t-small text-muted uppercase tracking-wide">{title}</div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="press flex items-center justify-center w-11 h-11 -mr-2 -mt-2 rounded-full text-muted"
          >
            <X size={22} />
          </button>
        </div>

        <div className="scroll-y px-5 pb-6">
          <p
            className={`t-body selectable whitespace-pre-wrap ${ok ? '' : 'text-danger'}`}
          >
            {text || 'Done.'}
          </p>
        </div>
      </div>
    </div>
  )
}
