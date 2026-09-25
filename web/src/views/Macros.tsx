import { useCallback, useEffect, useState } from 'react';
import { fetchPanel, invokeJob } from '../api';
import type { Reminder, RemindersPanel, RoutinesPanel } from '../api';
import { useWony } from '../lib/wonyContext';
import { CARD } from '../components/ui';

function scheduleFor(name: string, reminders: Reminder[]): string | null {
  const match = reminders.find(
    (r) => r.action_job === 'routine' && String(r.action_args?.name ?? '').toLowerCase() === name.toLowerCase(),
  );
  return match ? match.when_str : null;
}

export function Macros() {
  const { runJob, reloadRoutinesCount, panels } = useWony();
  const [routines, setRoutines] = useState<RoutinesPanel | null>(null);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [stepsDraft, setStepsDraft] = useState('');
  const [newName, setNewName] = useState('');
  const [newSteps, setNewSteps] = useState('');
  const [newSchedule, setNewSchedule] = useState('');

  const hasReminders = panels.some((p) => p.key === 'reminders');

  const refresh = useCallback(() => {
    fetchPanel<RoutinesPanel>('routines').then((r) => setRoutines(r.data));
    if (hasReminders) fetchPanel<RemindersPanel>('reminders').then((r) => setReminders(r.data?.reminders ?? []));
    reloadRoutinesCount();
  }, [hasReminders, reloadRoutinesCount]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const items = routines?.routines ?? [];

  const run = (name: string) => {
    runJob('routine', { name: name.toLowerCase() }, { from: 'Macros' }).then(refresh);
  };

  const save = (name: string, steps: string) => {
    setEditingName(null);
    runJob(
      'routine',
      { action: 'add', name: name.toLowerCase(), steps },
      { from: 'Macros', title: `Save changes to ${name}?` },
    ).then(refresh);
  };

  const remove = (name: string) => {
    runJob('routine', { action: 'remove', name: name.toLowerCase() }, { from: 'Macros', title: `Delete ${name}?` }).then(refresh);
  };

  const saveNew = () => {
    if (!newName.trim() || !newSteps.trim()) return;
    const name = newName.trim();
    const steps = newSteps.trim();
    const schedule = newSchedule.trim();
    runJob(
      'routine',
      { action: 'add', name: name.toLowerCase(), steps },
      { from: 'Macros', title: `Create macro "${name}"?` },
    ).then((res) => {
      if (!res.ok && res.error) return;
      if (schedule) {
        invokeJob('add_reminder', { when: schedule, action_job: 'routine', action_args: { name: name.toLowerCase() } });
      }
      setNewName('');
      setNewSteps('');
      setNewSchedule('');
      refresh();
    });
  };

  return (
    <div className="px-8 pb-10 grid gap-3 items-start" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
      {items.map((routine) => {
        const schedule = hasReminders ? scheduleFor(routine.name, reminders) : null;
        const editing = editingName === routine.name;
        return (
          <div key={routine.name} className={`${CARD} p-4.5 flex flex-col gap-3`}>
            <div className="flex justify-between items-baseline gap-2.5">
              <span className="text-lg font-bold">{routine.name}</span>
              {schedule && (
                <span className="font-mono text-xs text-teal bg-teal-soft px-2 py-1 rounded-md whitespace-nowrap">{schedule}</span>
              )}
            </div>
            {editing ? (
              <textarea
                defaultValue={routine.steps}
                rows={4}
                onChange={(e) => setStepsDraft(e.target.value)}
                className="border rounded-[9px] p-2.5 text-sm resize-y"
                style={{ borderColor: 'var(--color-border)' }}
              />
            ) : (
              <span className="text-sm text-body2 leading-relaxed">{routine.steps}</span>
            )}
            <div className="flex gap-2 mt-1">
              <button onClick={() => run(routine.name)} className="border-0 bg-accent text-on-accent rounded-[9px] px-4 py-2 text-sm font-semibold">
                Run
              </button>
              <button
                onClick={() => {
                  if (editing) save(routine.name, stepsDraft || routine.steps);
                  else {
                    setStepsDraft(routine.steps);
                    setEditingName(routine.name);
                  }
                }}
                className="border-0 bg-teal-soft text-teal rounded-[9px] px-3.5 py-2 text-sm font-semibold"
              >
                {editing ? 'Save' : 'Edit'}
              </button>
              <button onClick={() => remove(routine.name)} className="border-0 bg-transparent text-red rounded-[9px] px-2.5 py-2 text-sm font-semibold ml-auto">
                Delete
              </button>
            </div>
          </div>
        );
      })}

      <div className={`${CARD} p-4.5 flex flex-col gap-2.5`} style={{ border: '1.5px dashed var(--color-dashed-border)' }}>
        <span className="text-lg font-bold">New macro</span>
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Name, e.g. leaving home"
          className="border rounded-[9px] px-2.5 py-2 text-sm"
          style={{ borderColor: 'var(--color-border)' }}
        />
        <textarea
          value={newSteps}
          onChange={(e) => setNewSteps(e.target.value)}
          rows={3}
          placeholder="Steps in plain words"
          className="border rounded-[9px] px-2.5 py-2 text-sm resize-y"
          style={{ borderColor: 'var(--color-border)' }}
        />
        {hasReminders && (
          <input
            value={newSchedule}
            onChange={(e) => setNewSchedule(e.target.value)}
            placeholder="Schedule (optional), e.g. every weekday at 7am"
            className="border rounded-[9px] px-2.5 py-2 text-sm"
            style={{ borderColor: 'var(--color-border)' }}
          />
        )}
        <button
          onClick={saveNew}
          disabled={!newName.trim() || !newSteps.trim()}
          className="self-start border-0 bg-accent text-on-accent rounded-[9px] px-4 py-2 text-sm font-semibold disabled:opacity-40"
        >
          Save macro
        </button>
      </div>
    </div>
  );
}
