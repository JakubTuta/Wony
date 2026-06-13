import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Trash2, Database, ChevronDown, ChevronRight, Loader2, Bot, User } from 'lucide-react';
import { streamChat, clearChat, wipeData, fetchHistory, connectTurnsSocket } from '../api';
import type { ChatCall, HistoryTurn } from '../api';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  calls?: ChatCall[];
  turnId?: number | null;
  streamKey?: string; // present only while streaming; removed on finalization
}

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [expandedCalls, setExpandedCalls] = useState<Set<number>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Turn ids whose assistant reply is already on screen — the single source of
  // truth for dedup. A turn arrives from up to two paths (HTTP /chat response
  // and the WS broadcast); whichever lands first claims the id, the other skips.
  const seenTurnIds = useRef<Set<number>>(new Set());

  useEffect(() => {
    fetchHistory(50).then(turns => {
      const msgs: Message[] = [];
      for (const t of turns) {
        msgs.push({ role: 'user', text: t.user });
        if (t.assistant) {
          msgs.push({ role: 'assistant', text: t.assistant, calls: t.calls ?? [], turnId: t.id });
        }
        if (t.id != null) seenTurnIds.current.add(t.id);
      }
      setMessages(msgs);
    }).finally(() => setHistoryLoading(false));
  }, []);

  const handleIncomingTurn = useCallback((turn: HistoryTurn) => {
    // Already rendered (e.g. HTTP response beat the WS frame) — ignore.
    if (turn.id != null && seenTurnIds.current.has(turn.id)) return;
    if (turn.id != null) seenTurnIds.current.add(turn.id);

    setMessages(prev => {
      const n = prev.length;
      const assistantMsg: Message = {
        role: 'assistant',
        text: turn.assistant,
        calls: turn.calls ?? [],
        turnId: turn.id,
      };
      // Look in the last 2 positions for a matching user bubble.
      // The streaming path adds [user, empty-assistant(streamKey)] atomically,
      // so the user bubble may be at n-2 when there's a live streaming bubble.
      for (let i = n - 1; i >= Math.max(0, n - 2); i--) {
        if (prev[i].role === 'user' && prev[i].text === turn.user) {
          if (!turn.assistant) return prev.slice(0, i + 1);
          // Drop everything after the user bubble (removes in-flight streaming bubble)
          // and append the final assistant message.
          return [...prev.slice(0, i + 1), assistantMsg];
        }
      }
      // External / proactive turn (voice, desktop) — add both bubbles.
      return [
        ...prev,
        { role: 'user' as const, text: turn.user },
        ...(turn.assistant ? [assistantMsg] : []),
      ];
    });
  }, []);

  useEffect(() => {
    const disconnect = connectTurnsSocket(handleIncomingTurn);
    return disconnect;
  }, [handleIncomingTurn]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setLoading(true);

    // Use a stable key so the streaming bubble can be found by identity
    // rather than a stale index — avoids both the "Empty response" flash and
    // the duplicate-user-message race with the WS broadcast.
    const key = `s${Date.now()}`;
    setMessages(prev => [
      ...prev,
      { role: 'user', text },
      { role: 'assistant', text: '', streamKey: key },
    ]);

    try {
      const res = await streamChat(text, chunk => {
        setMessages(prev => {
          const idx = prev.findIndex(m => m.streamKey === key);
          if (idx === -1) return prev; // WS already claimed this turn
          const next = [...prev];
          next[idx] = { ...next[idx], text: next[idx].text + chunk };
          return next;
        });
      });
      // WS frame may have already rendered this turn — dedup by id, not text.
      if (res.id != null && seenTurnIds.current.has(res.id)) {
        setMessages(prev => prev.filter(m => m.streamKey !== key));
        return;
      }
      if (res.id != null) seenTurnIds.current.add(res.id);
      setMessages(prev => {
        const idx = prev.findIndex(m => m.streamKey === key);
        if (idx === -1) return prev; // WS handled it while we were finalizing
        const next = [...prev];
        next[idx] = {
          role: 'assistant',
          text: res.text || next[idx].text || '',
          calls: res.calls,
          turnId: res.id,
          // streamKey intentionally omitted — message is finalized
        };
        return next;
      });
    } catch (e) {
      setMessages(prev => {
        const idx = prev.findIndex(m => m.streamKey === key);
        if (idx === -1) return prev;
        const next = [...prev];
        next[idx] = {
          role: 'assistant',
          text: `Error: ${e instanceof Error ? e.message : String(e)}`,
        };
        return next;
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleClear() {
    await clearChat();
    setMessages([]);
    setExpandedCalls(new Set());
    seenTurnIds.current.clear();
  }

  async function handleWipe() {
    const ok = window.confirm(
      'Permanently delete ALL your data — messages, profile facts, reminders, connected accounts, and embeddings? This cannot be undone.',
    );
    if (!ok) return;
    try {
      await wipeData();
      setMessages([]);
      setExpandedCalls(new Set());
      seenTurnIds.current.clear();
    } catch (e) {
      window.alert(`Wipe failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  function toggleCalls(idx: number) {
    setExpandedCalls(prev => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
          {messages.length === 0 ? 'Start a conversation' : `${messages.length} messages`}
        </span>
        <div className="flex items-center gap-3">
          {messages.length > 0 && (
            <button
              onClick={handleClear}
              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
            >
              <Trash2 size={13} />
              Clear
            </button>
          )}
          <button
            onClick={handleWipe}
            title="Permanently delete all stored data"
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-red-600 dark:hover:text-red-500 transition-colors"
          >
            <Database size={13} />
            Wipe data
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {historyLoading && (
          <div className="flex items-center justify-center py-8 text-gray-400 dark:text-gray-500 text-sm gap-2">
            <Loader2 size={14} className="animate-spin" />
            Loading history…
          </div>
        )}

        {!historyLoading && messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center py-12 space-y-2">
            <Bot size={40} className="text-gray-300 dark:text-gray-600" />
            <p className="text-gray-400 dark:text-gray-500 text-sm">
              Ask anything, or use the Jobs panel to run a tool directly.
            </p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex gap-2.5 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
          >
            {/* Avatar */}
            <div
              className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-bold ${
                msg.role === 'user'
                  ? 'bg-violet-500'
                  : 'bg-gray-200 dark:bg-gray-700'
              }`}
            >
              {msg.role === 'user' ? (
                <User size={14} />
              ) : (
                <Bot size={14} className="text-gray-600 dark:text-gray-300" />
              )}
            </div>

            <div className={`flex flex-col gap-1 max-w-[85%] ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
              {/* Bubble */}
              <div
                className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'bg-violet-600 text-white rounded-tr-sm'
                    : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-tl-sm'
                }`}
              >
                {msg.text || (!msg.streamKey && <span className="italic text-gray-400">Empty response</span>)}
              </div>

              {/* Tool calls trace */}
              {msg.calls && msg.calls.length > 0 && (
                <button
                  onClick={() => toggleCalls(idx)}
                  className="flex items-center gap-1 text-[11px] text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
                >
                  {expandedCalls.has(idx) ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  {msg.calls.length} tool{msg.calls.length !== 1 ? 's' : ''} used
                </button>
              )}

              {expandedCalls.has(idx) && msg.calls && (
                <div className="w-full space-y-1.5 text-[11px] font-mono">
                  {msg.calls.map((call, ci) => (
                    <div
                      key={ci}
                      className="rounded-lg bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 px-3 py-2 space-y-1"
                    >
                      <div className="font-semibold text-violet-600 dark:text-violet-400">
                        {call.name}
                      </div>
                      {Object.keys(call.args).length > 0 && (
                        <div className="text-gray-500 dark:text-gray-400">
                          args: {JSON.stringify(call.args)}
                        </div>
                      )}
                      {call.result && (
                        <div className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-all max-h-20 overflow-y-auto">
                          → {call.result.length > 200 ? call.result.slice(0, 200) + '…' : call.result}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && !messages.some(m => m.streamKey) && (
          <div className="flex gap-2.5">
            <div className="shrink-0 w-7 h-7 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
              <Bot size={14} className="text-gray-600 dark:text-gray-300" />
            </div>
            <div className="rounded-2xl rounded-tl-sm bg-gray-100 dark:bg-gray-800 px-4 py-2.5 flex items-center gap-2">
              <Loader2 size={14} className="animate-spin text-gray-400" />
              <span className="text-sm text-gray-400">Thinking…</span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-3">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Message Wony… (Enter to send, Shift+Enter for newline)"
            rows={1}
            disabled={loading}
            className="flex-1 resize-none rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2.5 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent transition max-h-32 overflow-y-auto disabled:opacity-60"
            style={{ minHeight: '42px' }}
            onInput={e => {
              const t = e.currentTarget;
              t.style.height = 'auto';
              t.style.height = `${Math.min(t.scrollHeight, 128)}px`;
            }}
          />
          <button
            onClick={send}
            disabled={!input.trim() || loading}
            className="shrink-0 w-10 h-10 rounded-xl bg-violet-600 text-white flex items-center justify-center hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}
