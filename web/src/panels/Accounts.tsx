import { useCallback, useEffect, useState } from 'react';
import { Plus, Star, UserRound } from 'lucide-react';
import { fetchPanel, invokeJob } from '../api';
import type { AccountsPanel, GoogleAccount } from '../api';
import { CARD, MUTED, Resting } from './ui';

/** Google accounts, managed without a conversation.
 *
 *  Every write goes through the same jobs the chat would have called, so
 *  there is one implementation of "add an account" and not two.
 */
export function Accounts() {
  const [panel, setPanel] = useState<AccountsPanel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [working, setWorking] = useState('');
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    fetchPanel<AccountsPanel>('accounts')
      .then((result) => {
        setPanel(result.data);
        setError(result.error);
      })
      .finally(() => setLoading(false));
  }, []);

  // Only ever called from an event handler, never from an effect.
  const refresh = useCallback(async () => {
    const result = await fetchPanel<AccountsPanel>('accounts');
    setPanel(result.data);
    setError(result.error);
  }, []);

  /** Run one account job and show what it said. Sign-in blocks on a browser
   *  window, so the caller says what is happening while it waits. */
  const run = async (name: string, args: Record<string, string>, waiting: string) => {
    setWorking(waiting);
    setNote(null);
    const result = await invokeJob(name, args);
    setWorking('');
    setNote(result.error ?? result.result);
    await refresh();
  };

  if (loading) return <Resting title="Reading your accounts…" />;
  if (error || !panel) {
    return <Resting icon={<UserRound size={32} />} title={error ?? 'No accounts right now.'} />;
  }

  return (
    <div className="p-4 space-y-3">
      {!panel.credentials_ready && (
        <p
          className="text-xs text-amber-700 dark:text-amber-300 px-3 py-2 rounded-lg
                     border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20"
        >
          credentials/google_credentials.json is missing. Download the OAuth client from
          Google Cloud Console and put it there before adding an account.
        </p>
      )}

      {working && (
        <p className={`text-xs ${MUTED} px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-800`}>
          {working}
        </p>
      )}

      {note && (
        <button
          onClick={() => setNote(null)}
          className={`${CARD} w-full text-left px-3 py-2`}
        >
          <p className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{note}</p>
        </button>
      )}

      {panel.accounts.length === 0 ? (
        <p className={`text-sm ${MUTED}`}>No Google accounts yet.</p>
      ) : (
        <div className="space-y-1.5">
          {panel.accounts.map((account) => (
            <Row
              key={account.name}
              account={account}
              services={panel.services}
              expanded={open === account.name}
              busy={!!working}
              onToggle={() => setOpen(open === account.name ? null : account.name)}
              onRun={run}
            />
          ))}
        </div>
      )}

      {adding ? (
        <AddForm
          busy={!!working}
          onCancel={() => setAdding(false)}
          onAdd={async (name) => {
            setAdding(false);
            await run(
              'add_google_account',
              { name },
              `Adding ${name} — finish signing in with Google in the browser window.`,
            );
          }}
        />
      ) : (
        <button
          onClick={() => setAdding(true)}
          disabled={!!working}
          className={`${CARD} w-full flex items-center justify-center gap-1.5 px-3 py-2.5
                      text-sm text-violet-600 dark:text-violet-400 disabled:opacity-40
                      hover:border-violet-300 dark:hover:border-violet-700 transition-colors`}
        >
          <Plus size={15} />
          Add account
        </button>
      )}
    </div>
  );
}

function Row({
  account,
  services,
  expanded,
  busy,
  onToggle,
  onRun,
}: {
  account: GoogleAccount;
  services: { gmail: boolean; calendar: boolean };
  expanded: boolean;
  busy: boolean;
  onToggle: () => void;
  onRun: (name: string, args: Record<string, string>, waiting: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [rename, setRename] = useState('');

  // Only services that are switched on can have a token, so a missing calendar
  // token means nothing when the calendar module is off.
  const missing = (['gmail', 'calendar'] as const).filter(
    (service) => services[service] && !account.tokens[service],
  );

  return (
    <div className={CARD}>
      <button onClick={onToggle} className="w-full text-left px-3 py-2.5 flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-sm text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
            {account.primary && (
              <Star size={12} className="text-amber-500 fill-amber-500 shrink-0" />
            )}
            {account.name}
          </div>
          <div className={`text-xs ${MUTED} truncate`}>
            {missing.length > 0
              ? `Not signed in for ${missing.join(' and ')}`
              : account.email || 'Signed in'}
          </div>
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-1.5 border-t border-gray-100 dark:border-gray-800 pt-2.5">
          <Action
            busy={busy}
            onClick={() =>
              onRun(
                'authorize_google_account',
                { name: account.name },
                `Signing in ${account.name} — finish in the browser window.`,
              )
            }
          >
            Sign in again
          </Action>

          {!account.primary && (
            <Action
              busy={busy}
              onClick={() =>
                onRun('set_primary_account', { name: account.name }, 'Setting default…')
              }
            >
              Make this the default account
            </Action>
          )}

          <div className="flex gap-1.5">
            <input
              value={rename}
              onChange={(e) => setRename(e.target.value)}
              placeholder="New name"
              className="flex-1 min-w-0 px-2.5 py-1.5 text-sm rounded-lg border
                         border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800
                         text-gray-900 dark:text-gray-100 focus:outline-none
                         focus:ring-2 focus:ring-violet-500"
            />
            <Action
              busy={busy || !rename.trim()}
              onClick={() => {
                onRun(
                  'edit_google_account',
                  { name: account.name, new_name: rename.trim() },
                  'Renaming…',
                );
                setRename('');
              }}
            >
              Rename
            </Action>
          </div>

          {confirming ? (
            <div className="flex gap-1.5">
              <Action
                busy={busy}
                danger
                onClick={() => {
                  setConfirming(false);
                  onRun('remove_google_account', { name: account.name }, 'Removing…');
                }}
              >
                Yes, remove it
              </Action>
              <Action busy={busy} onClick={() => setConfirming(false)}>
                Cancel
              </Action>
            </div>
          ) : (
            <Action busy={busy} danger onClick={() => setConfirming(true)}>
              Remove account
            </Action>
          )}
        </div>
      )}
    </div>
  );
}

function AddForm({
  busy,
  onAdd,
  onCancel,
}: {
  busy: boolean;
  onAdd: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState('');

  return (
    <div className={`${CARD} p-3 space-y-2`}>
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Short label — work, personal"
        className="w-full px-2.5 py-1.5 text-sm rounded-lg border border-gray-200
                   dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900
                   dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
      />
      <p className={`text-xs ${MUTED}`}>
        A browser window opens for you to sign in with Google.
      </p>
      <div className="flex gap-1.5">
        <Action busy={busy || !name.trim()} onClick={() => onAdd(name.trim())}>
          Add and sign in
        </Action>
        <Action busy={busy} onClick={onCancel}>
          Cancel
        </Action>
      </div>
    </div>
  );
}

function Action({
  children,
  onClick,
  busy,
  danger = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  busy: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className={`px-3 py-1.5 rounded-lg border text-xs transition-colors disabled:opacity-40 ${
        danger
          ? 'border-red-200 dark:border-red-800 text-red-600 dark:text-red-400'
          : `border-gray-200 dark:border-gray-700 ${MUTED} hover:border-gray-300 dark:hover:border-gray-600`
      }`}
    >
      {children}
    </button>
  );
}
