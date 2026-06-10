import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Trash2, ChevronDown, ChevronRight, Loader2, Bot, User } from 'lucide-react';
import { sendChat, clearChat, fetchHistory, connectTurnsSocket } from '../api';
import type { ChatCall, HistoryTurn } from '../api';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  calls?: ChatCall[];
}

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [expandedCalls, setExpandedCalls] = useState<Set<number>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Track the last optimistically-shown (user, assistant) pair to avoid WS duplication
  const lastSentRef = useRef<{ user: string; assistant: string } | null>(null);

  useEffect(() => {
    fetchHistory(50).then(turns => {
      const msgs: Message[] = [];
      for (const t of turns) {
        msgs.push({ role: 'user', text: t.user });
        if (t.assistant) msgs.push({ role: 'assistant', text: t.assistant, calls: t.calls ?? [] });
      }
      setMessages(msgs);
    }).finally(() => setHistoryLoading(false));
  }, []);

  const handleIncomingTurn = useCallback((turn: HistoryTurn) => {
    // Skip turns that were sent by this tab (already shown optimistically)
    const last = lastSentRef.current;
    if (last && last.user === turn.user && last.assistant === turn.assistant) {
      lastSentRef.current = null;
      return;
    }
    setMessages(prev => [
      ...prev,
      { role: 'user' as const, text: turn.user },
      ...(turn.assistant ? [{ role: 'assistant' as const, text: turn.assistant, calls: turn.calls ?? [] }] : []),
    ]);
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
    setMessages(prev => [...prev, { role: 'user', text }]);
    setLoading(true);
    try {
      const res = await sendChat(text);
      // Mark this pair so the WebSocket echo is skipped
      lastSentRef.current = { user: text, assistant: res.text };
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: res.text, calls: res.calls },
      ]);
    } catch (e) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: `Error: ${e instanceof Error ? e.message : String(e)}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function handleClear() {
    await clearChat();
    setMessages([]);
    setExpandedCalls(new Set());
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
        {messages.length > 0 && (
          <button
            onClick={handleClear}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
          >
            <Trash2 size={13} />
            Clear
          </button>
        )}
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
                {msg.text || <span className="italic text-gray-400">Empty response</span>}
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

        {loading && (
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
