import { useLayoutEffect, useRef, useState } from 'react'
import { ChevronDown, Eraser, Keyboard as KeyboardIcon, Send, Square } from 'lucide-react'
import { Keyboard } from '../components/Keyboard'
import { useWony } from '../state/wony-context'

export function Chat({
  draft,
  setDraft,
  keyboardOpen,
  setKeyboardOpen,
}: {
  draft: string
  setDraft: (value: string) => void
  keyboardOpen: boolean
  setKeyboardOpen: (open: boolean) => void
}) {
  const {
    config,
    turns,
    streaming,
    assistantState,
    lastError,
    dismissError,
    send,
    stop,
    clearTranscript,
  } = useWony()

  const [asked, setAsked] = useState<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)

  // The question the user just typed is echoed from here until its answer lands
  // as a turn. Derived rather than cleared from an effect: once the reply is in
  // and nothing is streaming, the recorded turn is the one to show.
  const thinking = assistantState === 'thinking'
  const pending = streaming !== null || thinking ? asked : null

  useLayoutEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [turns, streaming, pending, keyboardOpen])

  const submit = () => {
    const text = draft.trim()
    if (!text) return
    setAsked(text)
    send(text)
    setDraft('')
  }

  const language = config?.assistant.language || 'en'

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div
        ref={scroller}
        className={`scroll-y flex-1 px-4 py-4 flex flex-col gap-4 ${
          keyboardOpen ? 'short:hidden' : ''
        }`}
      >
        {turns.length === 0 && !pending && (
          <div className="flex-1 flex items-center justify-center">
            <p className="t-body text-muted text-center px-8">
              Nothing said yet. Type something.
            </p>
          </div>
        )}

        {turns.map((turn, i) => (
          <Exchange
            key={turn.id ?? `local-${i}`}
            question={turn.user}
            answer={turn.assistant}
          />
        ))}

        {pending && <Exchange question={pending} answer={streaming ?? ''} streaming />}

        {thinking && !streaming && (
          <div className="flex gap-1 pl-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="thinking-dot w-1.5 h-1.5 rounded-full bg-accent"
                style={{ animationDelay: `${i * 160}ms` }}
              />
            ))}
          </div>
        )}

        {lastError && (
          <button
            onClick={dismissError}
            className="press text-left px-4 py-3 rounded-2xl border border-danger/40 bg-danger/10"
          >
            <span className="t-body text-danger">{lastError}</span>
          </button>
        )}
      </div>

      <div className="shrink-0 px-3 py-2 flex items-center gap-2 border-t border-line">
        <button
          onClick={() => setKeyboardOpen(!keyboardOpen)}
          aria-label={keyboardOpen ? 'Hide keyboard' : 'Show keyboard'}
          className="press flex items-center justify-center w-11 h-11 rounded-full text-muted shrink-0"
        >
          {keyboardOpen ? <ChevronDown size={22} /> : <KeyboardIcon size={22} />}
        </button>

        {/* Both ways in at once. A plugged-in USB keyboard types here directly;
            inputMode=none only stops a platform virtual keyboard from opening
            on top of ours, and does not block physical keys. autoFocus means
            someone with a keyboard can start typing without finding the field
            first. The on-screen keyboard stays in sync because Keyboard.tsx
            pushes `value` back into it. */}
        <input
          value={draft}
          inputMode="none"
          autoFocus
          placeholder={`Ask ${config?.assistant.name ?? 'Wony'}…`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              submit()
            }
          }}
          onClick={() => setKeyboardOpen(true)}
          className="flex-1 min-w-0 h-12 px-4 rounded-full bg-surface border border-line
                     t-body outline-none placeholder:text-muted"
        />

        {turns.length > 0 && !thinking && (
          <button
            onClick={clearTranscript}
            aria-label="Clear conversation"
            className="press flex items-center justify-center w-11 h-11 rounded-full text-muted shrink-0"
          >
            <Eraser size={20} />
          </button>
        )}

        {thinking ? (
          <button
            onClick={stop}
            aria-label="Stop"
            className="press flex items-center justify-center w-12 h-12 rounded-full
                       bg-surface-2 border border-line text-danger shrink-0"
          >
            <Square size={18} fill="currentColor" />
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!draft.trim()}
            aria-label="Send"
            className="press flex items-center justify-center w-12 h-12 rounded-full
                       bg-accent text-on-accent disabled:opacity-30 shrink-0"
          >
            <Send size={20} />
          </button>
        )}
      </div>

      {keyboardOpen && (
        <Keyboard
          value={draft}
          language={language}
          onChange={setDraft}
          onSubmit={submit}
        />
      )}
    </div>
  )
}

function Exchange({
  question,
  answer,
  streaming = false,
}: {
  question: string
  answer: string
  streaming?: boolean
}) {
  return (
    <div className="flex flex-col gap-2 fade-up">
      <div className="self-end max-w-[85%] px-4 py-2.5 rounded-2xl rounded-br-md bg-accent text-on-accent">
        <p className="t-body selectable whitespace-pre-wrap">{question}</p>
      </div>
      {(answer || !streaming) && (
        <div className="self-start max-w-[92%] px-4 py-2.5 rounded-2xl rounded-bl-md bg-surface border border-line">
          <p className="t-body selectable whitespace-pre-wrap">{answer}</p>
        </div>
      )}
    </div>
  )
}
