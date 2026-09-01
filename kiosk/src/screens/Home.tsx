import { useEffect, useState } from 'react'
import { Keyboard as KeyboardIcon } from 'lucide-react'
import { fetchTiles, runTile } from '../api'
import type { Tile as TileData } from '../api'
import { Tile } from '../components/Tile'
import { AnswerSheet } from '../components/AnswerSheet'
import { useWony } from '../state/wony-context'

export function Home({
  onAsk,
  onPrompt,
  onScreen,
}: {
  onAsk: () => void
  onPrompt: (prompt: string) => void
  onScreen: (screen: string | null) => void
}) {
  const { config, noteLocalAnswer } = useWony()
  const [tiles, setTiles] = useState<TileData[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [answer, setAnswer] = useState<{ title: string; text: string; ok: boolean } | null>(
    null,
  )

  useEffect(() => {
    fetchTiles()
      .then(setTiles)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const press = async (tile: TileData) => {
    // A prompt tile is a sentence for the agent, so it belongs in the chat
    // where it can stream. A job tile answers before a screen change would
    // finish painting, so it stays here. A screen tile runs nothing at all.
    if (tile.kind === 'screen') {
      onScreen(tile.screen)
      return
    }
    if (tile.kind === 'prompt') {
      onPrompt(tile.prompt ?? '')
      return
    }

    setBusyId(tile.id)
    try {
      const result = await runTile(tile.id)
      setAnswer({ title: tile.label, text: result.text, ok: result.ok })
      if (result.ok && result.text) noteLocalAnswer(tile.label, result.text)
    } catch {
      setAnswer({ title: tile.label, text: 'Wony is not responding.', ok: false })
    } finally {
      setBusyId(null)
    }
  }

  const name = config?.assistant.name ?? 'Wony'

  return (
    <div className="relative flex-1 flex flex-col min-h-0">
      <div className="scroll-y flex-1 px-3 pt-3 pb-3">
        {loading ? (
          <div className="tile-grid">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="aspect-square rounded-tile bg-surface border border-line opacity-50"
              />
            ))}
          </div>
        ) : tiles.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center gap-2 px-8">
            <p className="t-display">No tiles yet</p>
            <p className="t-body text-muted">
              Enable a module in config.yaml, or write your own <code>tiles:</code> list.
              Typing works either way.
            </p>
          </div>
        ) : (
          <div className="tile-grid">
            {tiles.map((tile) => (
              <Tile key={tile.id} tile={tile} busy={busyId === tile.id} onPress={press} />
            ))}
          </div>
        )}
      </div>

      <div className="px-3 pb-3 shrink-0">
        <button
          onClick={onAsk}
          className="press w-full flex items-center gap-3 px-5 h-14 rounded-full
                     bg-surface border border-line text-muted"
          style={{ boxShadow: 'var(--wony-shadow)' }}
        >
          <span className="t-body flex-1 text-left">Ask {name}…</span>
          <KeyboardIcon size={20} />
        </button>
      </div>

      {answer && (
        <AnswerSheet
          title={answer.title}
          text={answer.text}
          ok={answer.ok}
          onClose={() => setAnswer(null)}
        />
      )}
    </div>
  )
}
