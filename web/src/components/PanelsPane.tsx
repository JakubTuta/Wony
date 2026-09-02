import { useEffect, useState } from 'react';
import {
  AlarmClock,
  CalendarDays,
  ChevronLeft,
  CloudSun,
  Lightbulb,
  Music,
  SlidersHorizontal,
  Terminal,
  UserRound,
} from 'lucide-react';
import { fetchPanels } from '../api';
import type { Job, PanelInfo } from '../api';
import { JobsPanel } from './JobsPanel';
import { Accounts } from '../panels/Accounts';
import { Agenda } from '../panels/Agenda';
import { Devices } from '../panels/Devices';
import { Music as MusicPanel } from '../panels/Music';
import { Reminders } from '../panels/Reminders';
import { Settings } from '../panels/Settings';
import { Weather } from '../panels/Weather';
import { MUTED } from '../panels/ui';

const PANEL_ICONS: Record<string, typeof CloudSun> = {
  weather: CloudSun,
  agenda: CalendarDays,
  reminders: AlarmClock,
  devices: Lightbulb,
  music: Music,
  accounts: UserRound,
  settings: SlidersHorizontal,
};

// Settings is not a module panel — it is always there, and it goes last so the
// things you look at every day stay first.
const SETTINGS_PANEL: PanelInfo = { key: 'settings', label: 'Settings', module: '' };

/** The right-hand pane: a few things worth looking at, and the full command
 *  list one click away.
 *
 *  It used to open on every registered job at once — 83 cards, alphabetical by
 *  module, most of them things nobody clicks. The jobs are still all there;
 *  they are just no longer the first thing you meet.
 */
export function PanelsPane({
  jobs,
  jobsLoading,
  locale,
}: {
  jobs: Job[];
  jobsLoading: boolean;
  locale: string;
}) {
  const [panels, setPanels] = useState<PanelInfo[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [showCommands, setShowCommands] = useState(false);

  useEffect(() => {
    fetchPanels().then((list) => {
      setPanels([...list, SETTINGS_PANEL]);
      // Open the first one rather than an empty pane: a blank right half reads
      // as broken, and the top tile is one click away regardless.
      setActive((current) => current ?? list[0]?.key ?? SETTINGS_PANEL.key);
    });
  }, []);

  if (showCommands) {
    return (
      <div className="flex flex-col h-full">
        <div className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800">
          <button
            onClick={() => setShowCommands(false)}
            className={`flex items-center gap-1 text-xs ${MUTED} hover:text-gray-700 dark:hover:text-gray-300`}
          >
            <ChevronLeft size={14} />
            Back
          </button>
        </div>
        <JobsPanel jobs={jobs} loading={jobsLoading} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {panels.length > 0 && (
        <div className="flex gap-1.5 px-4 pt-3 pb-2.5 flex-wrap border-b border-gray-100 dark:border-gray-800">
          {panels.map((panel) => {
            const Icon = PANEL_ICONS[panel.key] ?? CloudSun;
            const on = active === panel.key;
            return (
              <button
                key={panel.key}
                onClick={() => setActive(panel.key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs
                            transition-colors ${
                              on
                                ? 'border-violet-500 text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/20'
                                : `border-gray-200 dark:border-gray-700 ${MUTED} hover:border-gray-300 dark:hover:border-gray-600`
                            }`}
              >
                <Icon size={14} />
                {panel.label}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        <ActivePanel which={active ?? SETTINGS_PANEL.key} locale={locale} />
      </div>

      <button
        onClick={() => setShowCommands(true)}
        className={`px-4 py-2.5 border-t border-gray-100 dark:border-gray-800 text-left
                    text-xs ${MUTED} hover:text-gray-700 dark:hover:text-gray-300 flex items-center gap-1.5`}
      >
        <Terminal size={13} />
        All commands{jobs.length > 0 && ` (${jobs.length})`}
      </button>
    </div>
  );
}

function ActivePanel({ which, locale }: { which: string; locale: string }) {
  // Keyed on `which` so switching panels remounts rather than reusing the
  // previous panel's loading/error state.
  switch (which) {
    case 'weather':
      return <Weather key="weather" locale={locale} />;
    case 'agenda':
      return <Agenda key="agenda" locale={locale} />;
    case 'devices':
      return <Devices key="devices" />;
    case 'music':
      return <MusicPanel key="music" />;
    case 'accounts':
      return <Accounts key="accounts" />;
    case 'reminders':
      return <Reminders key="reminders" />;
    case 'settings':
      return <Settings key="settings" />;
    default:
      return null;
  }
}
