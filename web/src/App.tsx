import { useCallback, useEffect, useState } from 'react';
import { WonyProvider } from './lib/wony';
import { useWony } from './lib/wonyContext';
import { TopBar, type View } from './components/TopBar';
import { ChatPanel } from './components/ChatPanel';
import { ConfirmModal } from './components/ConfirmModal';
import { Dashboard } from './views/Dashboard';
import { Modules } from './views/Modules';
import { Macros } from './views/Macros';
import { Settings } from './views/Settings';

const TITLES: Record<View, [string, string]> = {
  dashboard: ['Dashboard', 'Pinned controls and live data'],
  modules: ['Modules & jobs', 'Run any job directly'],
  macros: ['Macros', 'Routines in plain words, run on tap or on a schedule'],
  settings: ['Settings', 'Voice, integrations, accounts, and what Wony may do on its own'],
};

function parseHash(): { view: View; module: string | null } {
  const raw = location.hash.replace(/^#/, '');
  const [view, module] = raw.split('/');
  const known: View[] = ['dashboard', 'modules', 'macros', 'settings'];
  return {
    view: known.includes(view as View) ? (view as View) : 'dashboard',
    module: module ? decodeURIComponent(module) : null,
  };
}

function AppShell() {
  const { jobs, routinesCount, pins } = useWony();
  const [{ view, module }, setRoute] = useState(parseHash);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const navigate = useCallback((next: View) => {
    location.hash = next;
  }, []);

  const openModule = useCallback((key: string) => {
    location.hash = `modules/${encodeURIComponent(key)}`;
  }, []);

  const [title, subtitle] = TITLES[view];

  return (
    <div className="h-screen grid min-w-0" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(360px,500px)' }}>
      <main className="overflow-auto min-w-0">
        <TopBar
          view={view}
          onNavigate={navigate}
          onOpenModule={openModule}
          counts={{ dashboard: pins?.length ?? 0, modules: jobs.length, macros: routinesCount }}
        />

        <header className="flex items-end justify-between gap-4 flex-wrap px-8 pt-6.5 pb-4.5">
          <div className="flex flex-col gap-0.5">
            <h1 className="m-0 text-[28px] font-bold tracking-tight">{title}</h1>
            <span className="text-sm text-muted">{subtitle}</span>
          </div>
          {view === 'dashboard' && (
            <button
              onClick={() => setEditing((v) => !v)}
              className="border rounded-full px-4 py-2 text-sm font-semibold"
              style={{
                borderColor: 'var(--color-pink-border-2)',
                background: editing ? 'var(--color-pink-soft)' : 'var(--color-surface)',
                color: 'var(--color-red)',
              }}
            >
              {editing ? 'Done' : 'Customize'}
            </button>
          )}
        </header>

        {view === 'dashboard' && <Dashboard editing={editing} />}
        {view === 'modules' && (
          <Modules selectedModule={module} onSelectModule={(key) => (location.hash = `modules/${encodeURIComponent(key)}`)} />
        )}
        {view === 'macros' && <Macros />}
        {view === 'settings' && <Settings />}
      </main>

      <ChatPanel />
      <ConfirmModal />
    </div>
  );
}

export default function App() {
  return (
    <WonyProvider>
      <AppShell />
    </WonyProvider>
  );
}
