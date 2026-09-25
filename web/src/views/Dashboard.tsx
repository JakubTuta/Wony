import { ModuleGate } from '../components/ModuleGate';
import { QuickControls } from './dashboard/QuickControls';
import { NowPlaying } from './dashboard/NowPlaying';
import { Agenda } from './dashboard/Agenda';
import { Weather } from './dashboard/Weather';
import { Home } from './dashboard/Home';
import { Reminders } from './dashboard/Reminders';
import { Shopping } from './dashboard/Shopping';
import { Inbox } from './dashboard/Inbox';

export function Dashboard({ editing }: { editing: boolean }) {
  return (
    <div className="px-8 pb-10 flex flex-col gap-7">
      <QuickControls editing={editing} />

      <section className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
        <ModuleGate moduleKey="spotify" label="Now playing">
          <NowPlaying />
        </ModuleGate>
        <ModuleGate moduleKey="calendar" label="Agenda">
          <Agenda />
        </ModuleGate>
        <ModuleGate moduleKey="weather" label="Weather">
          <Weather />
        </ModuleGate>
        <ModuleGate moduleKey="home_assistant" label="Home" fullRow>
          <Home />
        </ModuleGate>
        <ModuleGate moduleKey="scheduler" label="Timers & reminders">
          <Reminders />
        </ModuleGate>
        <ModuleGate moduleKey="notes" label="Shopping">
          <Shopping />
        </ModuleGate>
        <ModuleGate moduleKey="gmail" label="Inbox">
          <Inbox />
        </ModuleGate>
      </section>
    </div>
  );
}
