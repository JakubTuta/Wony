import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  Calendar,
  Check,
  Mail,
  RefreshCw,
  Star,
  Trash2,
  UserPlus,
  X,
} from 'lucide-react'
import { fetchGoogleAccounts, invokeJob } from '../api'
import type { GoogleAccount, GoogleAccountsSnapshot } from '../api'
import { Keyboard } from '../components/Keyboard'
import { useWony } from '../state/wony-context'

/** Add, rename, re-authorize and remove Google accounts by hand.
 *
 *  All of this can be said to Wony in a sentence, but signing in cannot: it
 *  needs a browser window and a label typed in, and asking for that in prose
 *  is a worse version of a form. Every action here runs the same job the chat
 *  would have run — nothing about accounts is implemented twice.
 */
export function Accounts() {
  const { config } = useWony()
  const [snapshot, setSnapshot] = useState<GoogleAccountsSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<GoogleAccount | null>(null)
  const [adding, setAdding] = useState(false)

  const language = config?.assistant.language || 'en'

  useEffect(() => {
    fetchGoogleAccounts()
      .then((result) => {
        setSnapshot(result.data)
        setError(result.error)
      })
      .finally(() => setLoading(false))
  }, [])

  // Re-read after any change. Only ever called from a press, so the list never
  // polls — accounts change when someone changes them, not on their own.
  const refresh = () => {
    fetchGoogleAccounts().then((result) => setSnapshot(result.data))
  }

  const close = (changed: boolean) => {
    setEditing(null)
    setAdding(false)
    if (changed) refresh()
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="t-body text-muted">Loading accounts…</p>
      </div>
    )
  }

  if (!snapshot) {
    return (
      <Empty
        title="Accounts are switched off"
        body={
          error ??
          'Add google_accounts to enabled_modules in config.yaml, then restart Wony.'
        }
      />
    )
  }

  if (!snapshot.credentials_ready) {
    return (
      <Empty
        title="Google isn't set up yet"
        body={
          'Create an OAuth client in Google Cloud Console, download it, and save it ' +
          'as credentials/google_credentials.json. Then come back here.'
        }
      />
    )
  }

  const { accounts } = snapshot

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="scroll-y flex-1 px-3 pt-3 pb-1 flex flex-col gap-1.5">
        {accounts.length === 0 ? (
          <Empty
            title="No accounts yet"
            body="Add one to let Wony read your mail and calendar."
          />
        ) : (
          accounts.map((account) => (
            <AccountRow
              key={account.name}
              account={account}
              services={snapshot.services}
              onPress={() => setEditing(account)}
            />
          ))
        )}
      </div>

      <div className="px-3 pb-3 pt-2 shrink-0">
        <button
          onClick={() => setAdding(true)}
          className="press w-full flex items-center justify-center gap-2 h-14 rounded-full
                     bg-accent text-on-accent"
        >
          <UserPlus size={20} />
          <span className="t-body">Add account</span>
        </button>
      </div>

      {adding && <AddSheet language={language} onClose={close} />}
      {editing && (
        <AccountSheet
          account={editing}
          services={snapshot.services}
          language={language}
          onClose={close}
        />
      )}
    </div>
  )
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center gap-2 px-8">
      <p className="t-display">{title}</p>
      <p className="t-body text-muted">{body}</p>
    </div>
  )
}

type Services = GoogleAccountsSnapshot['services']

function AccountRow({
  account,
  services,
  onPress,
}: {
  account: GoogleAccount
  services: Services
  onPress: () => void
}) {
  return (
    <button
      onClick={onPress}
      className="press list-row flex items-center gap-3 px-4 py-3 rounded-xl
                 bg-surface border border-line text-left"
    >
      <span
        aria-hidden
        className="flex items-center justify-center w-10 h-10 shrink-0 rounded-full
                   bg-surface-2 border border-line t-body uppercase"
      >
        {account.name.slice(0, 1)}
      </span>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="t-body truncate">{account.name}</span>
          {account.primary && (
            <Star size={14} className="text-accent shrink-0" fill="currentColor" />
          )}
        </div>
        <div className="t-small text-muted truncate">
          {account.email || 'Not signed in yet'}
        </div>
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {services.gmail && <TokenChip icon={<Mail size={14} />} ok={account.tokens.gmail} />}
        {services.calendar && (
          <TokenChip icon={<Calendar size={14} />} ok={account.tokens.calendar} />
        )}
      </div>
    </button>
  )
}

function TokenChip({ icon, ok }: { icon: React.ReactNode; ok: boolean }) {
  return (
    <span
      className={`flex items-center gap-1 px-2 h-7 rounded-full border ${
        ok ? 'border-line text-muted' : 'border-warn text-warn'
      }`}
    >
      {icon}
      {ok ? <Check size={12} /> : <AlertTriangle size={12} />}
    </span>
  )
}

/** The shell both sheets sit in — same geometry as the Commands run sheet. */
function Sheet({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string
  subtitle?: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div className="absolute inset-0 z-30 flex flex-col justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/45" />
      <div
        className="sheet-in relative rounded-t-3xl bg-surface border-t border-line
                   max-h-[85%] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 px-5 pt-5 pb-2 shrink-0">
          <div className="flex-1 min-w-0">
            <div className="t-display truncate">{title}</div>
            {subtitle && <p className="t-small text-muted truncate">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="press flex items-center justify-center w-11 h-11 -mr-2 -mt-2 rounded-full text-muted"
          >
            <X size={22} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

/** A text field that takes physical keys and drives the on-screen keyboard. */
function NameField({
  value,
  focused,
  onChange,
  onFocus,
  onCommit,
  placeholder,
}: {
  value: string
  focused: boolean
  onChange: (value: string) => void
  onFocus: () => void
  onCommit: () => void
  placeholder: string
}) {
  return (
    <input
      value={value}
      inputMode="none"
      autoFocus
      onChange={(e) => onChange(e.target.value)}
      onFocus={onFocus}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          onCommit()
        }
      }}
      placeholder={placeholder}
      className={`h-12 px-4 rounded-xl bg-surface-2 border t-body outline-none
                  placeholder:text-muted ${focused ? 'border-accent' : 'border-line'}`}
    />
  )
}

/** Shown while a consent flow is open. The browser window can land behind the
 *  kiosk on a Pi, so the screen has to say where the sign-in actually went. */
function SigningIn() {
  return (
    <div className="flex flex-col items-center gap-2 py-4 text-center">
      <RefreshCw size={22} className="text-accent animate-spin" />
      <p className="t-body">Finish signing in in the browser window.</p>
      <p className="t-small text-muted">
        Pick the Google account you want, then come back here.
      </p>
    </div>
  )
}

function AddSheet({
  language,
  onClose,
}: {
  language: string
  onClose: (changed: boolean) => void
}) {
  const [name, setName] = useState('')
  const [keyboard, setKeyboard] = useState(true)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null)

  const add = async () => {
    const label = name.trim()
    if (!label || busy) return
    setBusy(true)
    setKeyboard(false)
    setResult(null)
    const response = await invokeJob('add_google_account', { name: label })
    setResult({
      text: response.ok ? response.result || 'Done.' : response.error || 'Failed.',
      ok: response.ok,
    })
    setBusy(false)
  }

  // The account exists the moment add returns, whatever the sign-in did, so
  // the list behind is out of date either way.
  return (
    <Sheet title="Add account" subtitle="Give it a short name" onClose={() => onClose(true)}>
      <div className="scroll-y flex-1 px-5 pb-3 flex flex-col gap-3">
        <NameField
          value={name}
          focused={keyboard}
          onChange={setName}
          onFocus={() => setKeyboard(true)}
          onCommit={add}
          placeholder="work, personal, …"
        />
        <p className="t-small text-muted">
          A label for you — the email address is filled in after you sign in.
        </p>

        {busy && <SigningIn />}
        {result && (
          <p
            className={`t-body selectable whitespace-pre-wrap ${
              result.ok ? '' : 'text-danger'
            }`}
          >
            {result.text}
          </p>
        )}
      </div>

      <div className="px-5 pb-4 pt-1 shrink-0">
        <button
          onClick={result ? () => onClose(true) : add}
          disabled={busy || (!result && !name.trim())}
          className="press w-full flex items-center justify-center gap-2 h-14 rounded-full
                     bg-accent text-on-accent disabled:opacity-50"
        >
          <span className="t-body">
            {busy ? 'Signing in…' : result ? 'Done' : 'Add and sign in'}
          </span>
        </button>
      </div>

      {keyboard && !busy && (
        <Keyboard
          value={name}
          language={language}
          onChange={setName}
          onSubmit={add}
        />
      )}
    </Sheet>
  )
}

function AccountSheet({
  account,
  services,
  language,
  onClose,
}: {
  account: GoogleAccount
  services: Services
  language: string
  onClose: (changed: boolean) => void
}) {
  const [newName, setNewName] = useState(account.name)
  const [keyboard, setKeyboard] = useState(false)
  const [busy, setBusy] = useState<'rename' | 'primary' | 'authorize' | 'remove' | null>(
    null,
  )
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null)
  // Renaming or removing invalidates the name every other action here uses, so
  // those close the sheet rather than leaving it pointing at nothing.
  const [changed, setChanged] = useState(false)

  const run = async (
    kind: NonNullable<typeof busy>,
    job: string,
    args: Record<string, unknown>,
    thenClose: boolean,
  ) => {
    setBusy(kind)
    setKeyboard(false)
    setResult(null)
    const response = await invokeJob(job, args)
    setBusy(null)
    setChanged(true)
    if (response.ok && thenClose) {
      onClose(true)
      return
    }
    setResult({
      text: response.ok ? response.result || 'Done.' : response.error || 'Failed.',
      ok: response.ok,
    })
  }

  const rename = () => {
    const next = newName.trim()
    if (!next || next === account.name) return
    run('rename', 'edit_google_account', { name: account.name, new_name: next }, true)
  }

  const missing =
    (services.gmail && !account.tokens.gmail) ||
    (services.calendar && !account.tokens.calendar)

  return (
    <Sheet
      title={account.name}
      subtitle={account.email || 'Not signed in yet'}
      onClose={() => onClose(changed)}
    >
      <div className="scroll-y flex-1 px-5 pb-3 flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="t-small text-muted">Name</span>
          <NameField
            value={newName}
            focused={keyboard}
            onChange={setNewName}
            onFocus={() => setKeyboard(true)}
            onCommit={rename}
            placeholder={account.name}
          />
        </label>

        {newName.trim() !== account.name && newName.trim() !== '' && (
          <Action
            label="Save new name"
            busy={busy === 'rename'}
            onClick={rename}
            disabled={busy !== null}
          />
        )}

        {!account.primary && (
          <Action
            icon={<Star size={18} />}
            label="Make this the default account"
            busy={busy === 'primary'}
            onClick={() => run('primary', 'set_primary_account', { name: account.name }, true)}
            disabled={busy !== null}
          />
        )}

        <Action
          icon={<RefreshCw size={18} />}
          label={missing ? 'Sign in' : 'Sign in again'}
          busy={busy === 'authorize'}
          onClick={() =>
            run('authorize', 'authorize_google_account', { name: account.name }, false)
          }
          disabled={busy !== null}
        />
        {missing && (
          <p className="t-small text-warn">
            Something here isn't signed in. Wony will skip this account until it is.
          </p>
        )}

        <Action
          icon={<Trash2 size={18} />}
          label={confirmRemove ? 'Yes, remove it' : 'Remove account'}
          danger
          busy={busy === 'remove'}
          disabled={busy !== null}
          onClick={() => {
            if (!confirmRemove) {
              setConfirmRemove(true)
              return
            }
            run('remove', 'remove_google_account', { name: account.name }, true)
          }}
        />
        {confirmRemove && busy === null && (
          <p className="t-small text-muted">
            This deletes the saved sign-in. Wony stops reading this account's mail and
            calendar.
          </p>
        )}

        {busy === 'authorize' && <SigningIn />}
        {result && (
          <p
            className={`t-body selectable whitespace-pre-wrap ${
              result.ok ? '' : 'text-danger'
            }`}
          >
            {result.text}
          </p>
        )}
      </div>

      {keyboard && busy === null && (
        <Keyboard
          value={newName}
          language={language}
          onChange={setNewName}
          onSubmit={rename}
        />
      )}
    </Sheet>
  )
}

function Action({
  icon,
  label,
  busy,
  danger,
  disabled,
  onClick,
}: {
  icon?: React.ReactNode
  label: string
  busy: boolean
  danger?: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`press flex items-center justify-center gap-2 h-14 rounded-full
                  border disabled:opacity-50 ${
                    danger
                      ? 'border-danger text-danger'
                      : 'border-line bg-surface-2 text-text'
                  }`}
    >
      {busy ? <RefreshCw size={18} className="animate-spin" /> : icon}
      <span className="t-body">{busy ? 'Working…' : label}</span>
    </button>
  )
}
