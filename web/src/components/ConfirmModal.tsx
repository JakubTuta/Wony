import { useWony } from '../lib/wonyContext';
import { Button, Modal } from './ui';

export function ConfirmModal() {
  const { confirmRequest, cancelConfirm } = useWony();
  if (!confirmRequest) return null;

  return (
    <Modal onClose={cancelConfirm}>
      <span className="text-[13px] font-semibold uppercase tracking-[0.08em] text-red">
        Needs confirmation
      </span>
      <span className="text-xl font-bold">{confirmRequest.title}</span>
      <span className="font-mono text-xs text-muted bg-page rounded-lg px-2.5 py-2 break-all">
        {confirmRequest.sig}
      </span>
      <div className="flex gap-2 justify-end mt-1.5">
        <Button variant="soft" onClick={cancelConfirm}>Cancel</Button>
        <Button variant="accent" onClick={confirmRequest.onConfirm}>Confirm</Button>
      </div>
    </Modal>
  );
}
