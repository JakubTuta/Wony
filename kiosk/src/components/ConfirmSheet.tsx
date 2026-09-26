import type { ConfirmRequest } from '../state/ui-context'

export function ConfirmSheet({
  request,
  onCancel,
}: {
  request: ConfirmRequest
  onCancel: () => void
}) {
  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center"
      style={{ background: 'var(--wony-scrim)' }}
    >
      <div className="w-[680px] rounded-[32px] bg-surface p-9 flex flex-col gap-[18px]">
        <span className="t-label text-accent">Confirm</span>
        <span className="text-[38px] font-bold leading-[1.15]">{request.title}</span>
        <span className="font-mono text-[16px] text-muted">{request.sig}</span>
        <div className="grid grid-cols-2 gap-4 mt-2.5">
          <button
            onClick={onCancel}
            className="press h-[100px] rounded-[24px] bg-surface-2 text-[26px] font-bold"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              request.onConfirm()
              onCancel()
            }}
            className="press h-[100px] rounded-[24px] bg-accent text-on-accent text-[26px] font-bold"
          >
            {request.yesLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
