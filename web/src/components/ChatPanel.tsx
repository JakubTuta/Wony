import { useEffect, useRef, useState } from 'react';
import { fetchConfig, transcribeAudio } from '../api';
import type { AppConfig, ChatCall } from '../api';
import { useWony } from '../lib/wonyContext';
import type { ChatMessage } from '../lib/wonyContext';
import { signature } from '../lib/jobs';
import { Markdown } from './Markdown';

const SUGGESTION_BY_MODULE: Record<string, string> = {
  weather: "What's the weather?",
  calendar: "What's on today?",
  gmail: 'Any important email?',
  spotify: "What's playing?",
  shazam: 'What song is this?',
  maps: 'Pharmacy near me',
  drive: 'What changed in my Drive lately?',
  contacts: "What's Anna's email?",
  home_assistant: 'Turn off the lights',
  notes: "What's on my shopping list?",
  scheduler: 'Set a 10 minute timer',
  routines: 'Run my morning briefing',
  system: 'How is my computer doing?',
};

const FALLBACK_SUGGESTIONS = ['What can you do?', 'What time is it?', 'How are you doing?'];

export function ChatPanel() {
  const {
    messages,
    loading,
    historyLoading,
    sendText,
    stopGeneration,
    clearChat,
    resolveInlineConfirm,
    settings,
  } = useWony();

  const [input, setInput] = useState('');
  const [recording, setRecording] = useState(false);
  const [micWarning, setMicWarning] = useState<string | null>(null);
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  const micWarningTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const silenceRafRef = useRef<number | null>(null);

  useEffect(() => {
    fetchConfig().then(setAppConfig).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const suggestions = (() => {
    const enabled = settings?.modules.filter((m) => m.enabled).map((m) => m.key) ?? [];
    const picked = enabled.map((key) => SUGGESTION_BY_MODULE[key]).filter(Boolean) as string[];
    const out = [...new Set(picked)].slice(0, 3);
    for (const filler of FALLBACK_SUGGESTIONS) {
      if (out.length >= 3) break;
      if (!out.includes(filler)) out.push(filler);
    }
    return out;
  })();

  function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    if (inputRef.current) inputRef.current.style.height = 'auto';
    sendText(text);
  }

  function showMicWarning(message: string) {
    if (micWarningTimerRef.current) clearTimeout(micWarningTimerRef.current);
    setMicWarning(message);
    micWarningTimerRef.current = setTimeout(() => setMicWarning(null), 8000);
  }

  function stopRecording() {
    if (silenceRafRef.current !== null) {
      cancelAnimationFrame(silenceRafRef.current);
      silenceRafRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    mediaRecorderRef.current?.stop();
  }

  async function toggleMic() {
    if (recording) {
      stopRecording();
      return;
    }
    try {
      fetch('/api/ack', { method: 'POST' }).catch(() => {});

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      audioChunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(audioChunksRef.current, { type: mr.mimeType || 'audio/webm' });
        try {
          const { text, warning } = await transcribeAudio(blob);
          if (warning) showMicWarning(warning);
          if (text) sendText(text);
        } catch {
          showMicWarning('Transcription failed — check your connection and try again.');
        }
      };
      mediaRecorderRef.current = mr;
      mr.start();
      setRecording(true);

      const SILENCE_THRESHOLD = 0.015;
      const SILENCE_MS = appConfig?.voice.stt.silence_ms ?? 1500;
      const MAX_RECORD_MS = (appConfig?.voice.stt.max_seconds ?? 12) * 1000;
      const MIN_RECORD_MS = Math.min(700, SILENCE_MS);
      const startedAt = Date.now();
      let silenceStart: number | null = null;

      const ctx = new AudioContext();
      audioContextRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const buf = new Float32Array(analyser.fftSize);

      function tick() {
        analyser.getFloatTimeDomainData(buf);
        const rms = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length);
        const elapsed = Date.now() - startedAt;

        if (elapsed >= MAX_RECORD_MS) {
          stopRecording();
          return;
        }
        if (elapsed > MIN_RECORD_MS) {
          if (rms < SILENCE_THRESHOLD) {
            if (silenceStart === null) silenceStart = Date.now();
            else if (Date.now() - silenceStart > SILENCE_MS) {
              stopRecording();
              return;
            }
          } else {
            silenceStart = null;
          }
        }
        silenceRafRef.current = requestAnimationFrame(tick);
      }
      silenceRafRef.current = requestAnimationFrame(tick);
    } catch {
      showMicWarning("Could not access the microphone — check the browser's mic permission.");
    }
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const MAX_INPUT_HEIGHT = 120;
  function autoGrow(el: HTMLTextAreaElement) {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }

  return (
    <aside className="bg-surface border-l flex flex-col min-h-0 min-w-0" style={{ borderColor: 'var(--color-pink-border)' }}>
      <div className="flex items-center justify-between px-5 pt-5 pb-3.5" style={{ borderBottom: '1px solid var(--color-divider)' }}>
        <span className="text-lg font-bold">Chat</span>
        <button onClick={clearChat} className="border-0 bg-transparent text-muted text-[13px] font-semibold">
          Clear
        </button>
      </div>

      <div className="flex-1 overflow-auto px-5 py-4.5 flex flex-col gap-3.5">
        {historyLoading && <span className="text-sm text-muted">Loading…</span>}

        {messages.map((msg, idx) => (
          <MessageRow key={idx} msg={msg} index={idx} onResolve={resolveInlineConfirm} />
        ))}

        {loading && !messages.some((m) => m.streamKey) && (
          <span className="text-[13px] text-muted">Wony is thinking…</span>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="px-4 pt-3 pb-4 flex flex-col gap-2.5" style={{ borderTop: '1px solid var(--color-divider)' }}>
        {micWarning && (
          <div className="text-xs text-red bg-pink-faint rounded-lg px-3 py-2">{micWarning}</div>
        )}
        <div className="flex gap-1.5 flex-wrap">
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => sendText(s)}
              className="border rounded-full px-2.5 py-1.5 text-[13px] bg-surface"
              style={{ borderColor: 'var(--color-border)' }}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex gap-2 items-end border rounded-xl py-1.5 pr-1.5 pl-3" style={{ borderColor: 'var(--color-border)' }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              autoGrow(e.target);
            }}
            onKeyDown={handleKey}
            placeholder="Message Wony"
            disabled={loading}
            rows={1}
            className="flex-1 min-w-0 border-0 outline-none text-[15px] bg-transparent resize-none py-1.5 leading-snug"
            style={{ maxHeight: MAX_INPUT_HEIGHT }}
          />
          <button
            onClick={toggleMic}
            disabled={loading}
            title={recording ? 'Stop recording' : 'Record voice input'}
            className="border-0 w-9 h-9 rounded-[9px] text-xs font-bold disabled:opacity-40 shrink-0"
            style={{
              background: recording ? 'var(--color-accent)' : 'var(--color-teal-soft)',
              color: recording ? 'var(--color-on-accent)' : 'var(--color-teal)',
            }}
          >
            {recording ? '●' : 'MIC'}
          </button>
          {loading ? (
            <button
              onClick={stopGeneration}
              className="border-0 h-9 px-3.5 rounded-[9px] bg-accent text-on-accent text-sm font-semibold shrink-0"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={send}
              disabled={!input.trim()}
              className="border-0 h-9 px-3.5 rounded-[9px] bg-accent text-on-accent text-sm font-semibold disabled:opacity-40 shrink-0"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}

function MessageRow({
  msg,
  index,
  onResolve,
}: {
  msg: ChatMessage;
  index: number;
  onResolve: (msgIndex: number, callIndex: number, call: ChatCall, ok: boolean) => void;
}) {
  if (msg.role === 'user') {
    return (
      <div
        className="self-end max-w-[85%] rounded-[14px_14px_4px_14px] px-3.5 py-2.5 text-sm leading-relaxed"
        style={{ background: 'var(--color-pink-soft)', color: '#4A1A17' }}
      >
        {msg.text}
      </div>
    );
  }

  const calls = msg.calls ?? [];
  const chips = calls.filter((c) => !c.needs_confirm);
  const confirmCalls = calls
    .map((c, i) => ({ call: c, index: i }))
    .filter(({ call }) => call.needs_confirm);

  return (
    <div className="flex flex-col gap-1.5">
      {msg.tag && (
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-red">{msg.tag}</span>
      )}
      {msg.text && (
        <div
          className="self-start max-w-[90%] rounded-[14px_14px_14px_4px] px-3.5 py-2.5 text-sm leading-relaxed"
          style={{ background: 'var(--color-page)' }}
        >
          <Markdown text={msg.text} />
        </div>
      )}
      {chips.length > 0 && (
        <div className="flex gap-1 flex-wrap">
          {chips.map((c, i) => (
            <span key={i} className="font-mono text-[11px] text-teal bg-teal-soft rounded px-1.5 py-1">
              {signature(c.name, c.args)}
            </span>
          ))}
        </div>
      )}
      {confirmCalls.map(({ call, index: callIndex }) => (
        <ConfirmCard
          key={callIndex}
          call={call}
          outcome={msg.callOutcomes?.[callIndex]}
          inert={!!msg.fromHistory}
          onResolve={(ok) => onResolve(index, callIndex, call, ok)}
        />
      ))}
    </div>
  );
}

function ConfirmCard({
  call,
  outcome,
  inert,
  onResolve,
}: {
  call: ChatCall;
  outcome?: 'confirmed' | 'cancelled';
  inert: boolean;
  onResolve: (ok: boolean) => void;
}) {
  return (
    <div className="border-[1.5px] rounded-xl p-3 flex flex-col gap-2.5" style={{ borderColor: 'var(--color-accent)' }}>
      <span className="text-sm font-semibold">{call.result}</span>
      <span className="font-mono text-[11px] text-muted">{signature(call.name, call.args)}</span>
      {inert ? (
        <span className="text-[13px] text-muted">Needed confirmation</span>
      ) : outcome ? (
        <span className="text-[13px] text-muted">{outcome === 'confirmed' ? 'Confirmed · done' : 'Cancelled'}</span>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={() => onResolve(true)}
            className="border-0 bg-accent text-on-accent rounded-[9px] px-3.5 py-1.5 text-[13px] font-semibold"
          >
            Confirm
          </button>
          <button
            onClick={() => onResolve(false)}
            className="border-0 bg-teal-soft text-teal rounded-[9px] px-3.5 py-1.5 text-[13px] font-semibold"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
