import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

// Authored at a fixed 1280×800 and scaled as one object so it fits 800×480
// and 1280×720 panels too, per design/README.md.
const WIDTH = 1280
const HEIGHT = 800

/** The wall panel's outer shell: an always-black backdrop holding one
 *  1280×800 surface, scaled and centred to fill whatever screen it is on. */
export function Frame({ children }: { children: ReactNode }) {
  const [scale, setScale] = useState(1)

  useEffect(() => {
    const fit = () => setScale(Math.min(window.innerWidth / WIDTH, window.innerHeight / HEIGHT))
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [])

  return (
    <div className="fixed inset-0 overflow-hidden bg-bg">
      <div
        className="absolute top-1/2 left-1/2 bg-panel text-text flex flex-col overflow-hidden"
        style={{
          width: WIDTH,
          height: HEIGHT,
          transform: `translate(-50%, -50%) scale(${scale})`,
        }}
      >
        {children}
      </div>
    </div>
  )
}
