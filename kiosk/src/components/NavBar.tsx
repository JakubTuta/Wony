import type { Tab } from '../lib/tabs'

const TABS: { id: Tab; label: string }[] = [
  { id: 'home', label: 'Home' },
  { id: 'rooms', label: 'Rooms' },
  { id: 'music', label: 'Music' },
  { id: 'macros', label: 'Macros' },
]

export function NavBar({ tab, onChange }: { tab: Tab; onChange: (next: Tab) => void }) {
  return (
    <nav className="h-28 shrink-0 grid grid-cols-4 gap-3 px-8 pb-5">
      {TABS.map((t) => {
        const active = tab === t.id
        return (
          <button
            key={t.id}
            onClick={() => onChange(t.id)}
            className={`press rounded-[24px] flex items-center justify-center gap-3 text-[23px] font-bold ${
              active ? 'bg-surface-2 text-text' : 'bg-transparent text-muted'
            }`}
          >
            <span
              className="w-3 h-3 rounded-full"
              style={{ background: active ? 'var(--wony-accent)' : 'transparent' }}
            />
            {t.label}
          </button>
        )
      })}
    </nav>
  )
}
