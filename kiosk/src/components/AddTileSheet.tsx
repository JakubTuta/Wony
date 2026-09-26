import type { TileDescriptor } from '../lib/tiles'

export function AddTileSheet({
  items,
  onPick,
  onClose,
}: {
  items: TileDescriptor[]
  onPick: (id: string) => void
  onClose: () => void
}) {
  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center"
      style={{ background: 'var(--wony-scrim)' }}
    >
      <div className="w-[760px] rounded-[32px] bg-surface p-8 flex flex-col gap-[18px]">
        <div className="flex items-center justify-between">
          <span className="text-[32px] font-bold">Add a tile</span>
          <button
            onClick={onClose}
            className="press h-16 px-6 rounded-[32px] bg-surface-2 text-[20px] font-semibold"
          >
            Close
          </button>
        </div>

        {items.length === 0 ? (
          <span className="text-[20px] text-muted">
            Every tile is already on the home screen.
          </span>
        ) : (
          <div className="grid grid-cols-2 gap-3 max-h-[420px] overflow-y-auto">
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => onPick(item.id)}
                className="press h-24 rounded-[22px] bg-surface-2 text-left px-[22px] flex flex-col justify-center gap-1"
              >
                <span className="text-[22px] font-bold truncate">{item.title}</span>
                <span className="text-[15px] text-muted uppercase tracking-[0.08em]">
                  {item.kind}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
