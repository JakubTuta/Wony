import { useState } from 'react'
import { Moon } from 'lucide-react'
import { SleepSheet } from '../components/SleepSheet'
import { Accounts } from './Accounts'
import { Settings } from './Settings'

type Section = 'settings' | 'accounts'

export function System({ onSleeping }: { onSleeping: () => void }) {
  const [section, setSection] = useState<Section>('settings')
  const [sleepOpen, setSleepOpen] = useState(false)

  return (
    <div className="h-full flex flex-col gap-4 min-h-0">
      <div className="flex gap-3 shrink-0">
        <Pill label="Settings" active={section === 'settings'} onClick={() => setSection('settings')} />
        <Pill label="Accounts" active={section === 'accounts'} onClick={() => setSection('accounts')} />
        <button
          onClick={() => setSleepOpen(true)}
          className="press h-16 px-7 rounded-[34px] bg-surface text-text text-[19px] font-semibold flex items-center gap-2"
        >
          <Moon size={18} />
          Sleep
        </button>
      </div>

      <div className="flex-1 min-h-0 bg-surface rounded-[28px] flex flex-col overflow-hidden">
        {section === 'settings' ? <Settings /> : <Accounts />}
      </div>

      {sleepOpen && (
        <SleepSheet onSleeping={() => { setSleepOpen(false); onSleeping() }} onClose={() => setSleepOpen(false)} />
      )}
    </div>
  )
}

function Pill({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`press h-16 px-7 rounded-[34px] text-[19px] font-semibold ${
        active ? 'bg-text text-panel' : 'bg-surface text-text'
      }`}
    >
      {label}
    </button>
  )
}
