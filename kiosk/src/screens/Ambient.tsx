import { useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import { fetchAmbient } from '../api'
import type { AmbientCard } from '../api'
import { useClock } from '../state/useClock'
import { useWony } from '../state/wony-context'

// The server caches these anyway; this is just how often the screen asks.
const REFRESH_MS = 10 * 60 * 1000

/** The screen when nobody has touched it.
 *
 *  Always dark, whatever the theme — this is the surface that stays lit all
 *  night, and a full cream panel in a dark room is a lamp. Any touch anywhere
 *  dismisses it, and that touch does not fall through to what was underneath.
 */
export function Ambient({ onWake }: { onWake: () => void }) {
  const { notifications, config } = useWony()
  const now = useClock()
  const [cards, setCards] = useState<AmbientCard[]>([])
  const locale = config?.assistant.language || 'en'

  useEffect(() => {
    const load = () => {
      fetchAmbient()
        .then(setCards)
        .catch(() => {})
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [])

  const newest = notifications[0]

  return (
    <div
      className="ambient-scope fade-up absolute inset-0 z-50 flex flex-col
                 items-center justify-center gap-8
                 bg-bg text-text px-8 py-8"
      onPointerDown={(e) => {
        // Consume the tap: waking the screen is the whole gesture. Letting it
        // through would also press whatever tile sat under the finger.
        e.preventDefault()
        e.stopPropagation()
        onWake()
      }}
    >
      <div className="text-center">
        <div className="t-clock">
          {now.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}
        </div>
        <div className="t-body text-muted mt-1">
          {now.toLocaleDateString(locale, {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
          })}
        </div>
      </div>

      {(cards.length > 0 || newest) && (
        <div className="flex flex-col items-center gap-3 max-w-2xl text-center">
          {cards.map((card) => (
            <div key={card.key}>
              <div className="t-small text-muted uppercase tracking-wide mb-1">
                {card.label}
              </div>
              <p className="t-body whitespace-pre-wrap line-clamp-3">{card.text}</p>
            </div>
          ))}

          {newest && (
            <div className="flex items-start gap-3 pt-1">
              <Bell size={18} className="text-accent mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="t-body line-clamp-2">{newest.text}</p>
                {notifications.length > 1 && (
                  <p className="t-small text-muted">
                    and {notifications.length - 1} more waiting
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Out of the centred stack: it belongs at the edge, not in the middle. */}
      <div className="absolute bottom-6 inset-x-0 text-center t-small text-muted opacity-50">
        Touch anywhere
      </div>
    </div>
  )
}
