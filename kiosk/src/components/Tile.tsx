import type { Tile as TileData } from '../api'

/** One home-screen button.
 *
 *  A job tile is instant and free; a prompt tile costs a model call. The dot in
 *  the corner is the only hint of that difference — enough to learn from, not
 *  enough to explain.
 */
export function Tile({
  tile,
  busy,
  onPress,
}: {
  tile: TileData
  busy: boolean
  onPress: (tile: TileData) => void
}) {
  return (
    <button
      onClick={() => onPress(tile)}
      disabled={busy}
      className="press relative flex flex-col items-center justify-center gap-2 aspect-square
                 rounded-tile bg-surface border border-line
                 disabled:opacity-60 min-h-26"
      style={{ boxShadow: 'var(--wony-shadow)' }}
    >
      {tile.kind === 'prompt' && (
        <span
          aria-hidden
          className="absolute top-2.5 right-2.5 w-1.5 h-1.5 rounded-full bg-accent opacity-70"
        />
      )}

      <span className="text-[clamp(1.6rem,4.5vw,2.4rem)] leading-none">
        {tile.icon || '•'}
      </span>
      <span className="t-small text-muted px-2 text-center leading-tight line-clamp-2">
        {tile.label}
      </span>

      {busy && (
        <span className="absolute inset-x-0 bottom-3 flex justify-center gap-1">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="thinking-dot w-1 h-1 rounded-full bg-accent"
              style={{ animationDelay: `${i * 160}ms` }}
            />
          ))}
        </span>
      )}
    </button>
  )
}
