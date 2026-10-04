import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  ackNotifications,
  clearChat as apiClearChat,
  connectSocket,
  fetchCapabilities,
  fetchHealth,
  fetchHistory,
  fetchJobs,
  fetchNotifications,
  fetchPanel,
  fetchPanels,
  fetchPins,
  fetchSettings,
  invokeJob,
  savePins as apiSavePins,
  wipeData as apiWipeData,
} from '../api';
import type {
  Capabilities,
  ChatCall,
  Diagnostic,
  HealthResponse,
  HistoryTurn,
  Job,
  Notification,
  PanelInfo,
  Pin,
  RoutinesPanel,
  SettingsResponse,
} from '../api';
import { humanize, needsConfirm, signature } from './jobs';
import { defaultPins } from '../views/dashboard/seed';
import { WonyContext, type ChatMessage, type ConfirmRequest, type RunResult, type WonyContextValue } from './wonyContext';

export type { ChatMessage } from './wonyContext';

interface PendingSession {
  sessionId: string;
  streamKey: string;
}

export function WonyProvider({ children }: { children: ReactNode }) {
  // ---------------------------------------------------------------- catalog
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [panels, setPanels] = useState<PanelInfo[]>([]);

  const jobsByName = useMemo(() => new Map(jobs.map((j) => [j.name, j])), [jobs]);

  // Declared up front (ahead of reloadHealth, which seeds it) because it also
  // lives independently after that: dismissed locally, appended to by the
  // socket. Seeded once, not kept in sync with `health` on every reload, or a
  // Retry on the Modules page would wipe out dismissals.
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const seededDiagnostics = useRef(false);
  const reloadHealth = useCallback(() => {
    fetchHealth()
      .then((h) => {
        setHealth(h);
        if (!seededDiagnostics.current && h.diagnostics) {
          seededDiagnostics.current = true;
          setDiagnostics(h.diagnostics);
        }
      })
      .catch(() => {});
  }, []);
  const reloadSettings = useCallback(() => {
    fetchSettings().then(setSettings).catch(() => {});
  }, []);
  const reloadPanels = useCallback(() => {
    fetchPanels().then(setPanels).catch(() => {});
  }, []);

  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const reloadCapabilities = useCallback(() => {
    fetchCapabilities().then(setCapabilities).catch(() => {});
  }, []);

  const [routinesCount, setRoutinesCount] = useState(0);
  const reloadRoutinesCount = useCallback(() => {
    fetchPanel<RoutinesPanel>('routines').then((r) => setRoutinesCount(r.data?.routines.length ?? 0));
  }, []);

  useEffect(() => {
    fetchJobs().then(setJobs).finally(() => setJobsLoading(false));
    reloadHealth();
    reloadSettings();
    reloadPanels();
    reloadCapabilities();
    reloadRoutinesCount();
  }, [reloadHealth, reloadSettings, reloadPanels, reloadCapabilities, reloadRoutinesCount]);

  // ---------------------------------------------------------------- pins
  const [pins, setPinsState] = useState<Pin[] | null>(null);
  const setPins = useCallback((next: Pin[]) => {
    setPinsState(next);
    apiSavePins(next).catch(() => {});
  }, []);

  // Waits for the job catalog so a first-ever run can seed defaults only from
  // jobs this install actually registered (defaultPins checks jobsByName).
  useEffect(() => {
    if (jobsLoading) return;
    fetchPins()
      .then((saved) => {
        if (saved) {
          setPinsState(saved);
          return;
        }
        const seeded = defaultPins(jobsByName);
        setPins(seeded);
      })
      .catch(() => setPinsState([]));
  }, [jobsLoading, jobsByName, setPins]);

  // ---------------------------------------------------------------- notifications + diagnostics
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const reloadNotifications = useCallback(() => {
    fetchNotifications().then(setNotifications);
  }, []);
  useEffect(() => {
    reloadNotifications();
  }, [reloadNotifications]);

  const ackOne = useCallback((id?: number) => {
    if (id === undefined) {
      setNotifications((prev) => prev.map((n) => ({ ...n, acknowledged: true })));
    } else {
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, acknowledged: true } : n)));
    }
    ackNotifications(id).catch(() => {});
  }, []);

  const dismissDiagnostic = useCallback((index: number) => {
    setDiagnostics((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const unreadCount = useMemo(
    // Info diagnostics ("Engine loaded", "Using GPU") are log lines, not
    // something that needs a person — counting them put a badge on every start.
    () =>
      notifications.filter((n) => !n.acknowledged).length +
      diagnostics.filter((d) => d.level !== 'info').length,
    [notifications, diagnostics],
  );

  // ---------------------------------------------------------------- confirm modal (outside chat)
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const requestConfirm = useCallback((req: ConfirmRequest) => setConfirmRequest(req), []);
  const cancelConfirm = useCallback(() => {
    confirmRequest?.onCancel?.();
    setConfirmRequest(null);
  }, [confirmRequest]);

  // ---------------------------------------------------------------- chat
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);

  const socketRef = useRef<ReturnType<typeof connectSocket> | null>(null);
  const pendingRef = useRef<PendingSession | null>(null);
  const seenTurnIds = useRef<Set<number>>(new Set());

  const handleTurn = useCallback((turn: HistoryTurn, sessionId?: string) => {
    if (pendingRef.current && sessionId === pendingRef.current.sessionId) {
      const { streamKey } = pendingRef.current;
      pendingRef.current = null;
      if (turn.id != null) seenTurnIds.current.add(turn.id);
      setLoading(false);
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.streamKey === streamKey);
        if (idx === -1) return prev;
        const next = [...prev];
        next[idx] = {
          role: 'assistant',
          text: turn.assistant || next[idx].text || '',
          calls: turn.calls ?? [],
          turnId: turn.id,
        };
        return next;
      });
      return;
    }

    if (turn.id != null && seenTurnIds.current.has(turn.id)) return;
    if (turn.id != null) seenTurnIds.current.add(turn.id);

    setMessages((prev) => {
      const n = prev.length;
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        text: turn.assistant,
        calls: turn.calls ?? [],
        turnId: turn.id,
      };
      for (let i = n - 1; i >= 0; i--) {
        if (prev[i].role === 'user' && prev[i].text === turn.user) {
          if (!turn.assistant) return prev.slice(0, i + 1);
          return [...prev.slice(0, i + 1), assistantMsg];
        }
      }
      return [
        ...prev,
        { role: 'user' as const, text: turn.user },
        ...(turn.assistant ? [assistantMsg] : []),
      ];
    });
  }, []);

  const handleDelta = useCallback((chunk: string, sessionId: string) => {
    if (pendingRef.current?.sessionId !== sessionId) return;
    const { streamKey } = pendingRef.current;
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.streamKey === streamKey);
      if (idx === -1) return prev;
      const next = [...prev];
      next[idx] = { ...next[idx], text: next[idx].text + chunk };
      return next;
    });
  }, []);

  const handleError = useCallback((message: string, sessionId: string) => {
    if (pendingRef.current?.sessionId !== sessionId) return;
    const { streamKey } = pendingRef.current;
    pendingRef.current = null;
    setLoading(false);
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.streamKey === streamKey);
      if (idx === -1) return prev;
      const next = [...prev];
      next[idx] = { role: 'assistant', text: `Error: ${message}` };
      return next;
    });
  }, []);

  const handleDisconnect = useCallback(() => {
    if (!pendingRef.current) return;
    const { streamKey } = pendingRef.current;
    pendingRef.current = null;
    setLoading(false);
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.streamKey === streamKey);
      if (idx === -1) return prev;
      const next = [...prev];
      next[idx] = { role: 'assistant', text: 'Connection lost. Please try again.' };
      return next;
    });
  }, []);

  const handleNotification = useCallback((n: Notification) => {
    setNotifications((prev) => [n, ...prev]);
    // A proactive message is also something Wony "said", so it belongs in the
    // transcript, tagged as unprompted rather than a reply to something asked.
    if (n.source?.startsWith('trigger:')) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: n.text, tag: `Spoke up · ${n.source.slice('trigger:'.length)}` },
      ]);
    }
  }, []);

  useEffect(() => {
    fetchHistory(50)
      .then((turns) => {
        const msgs: ChatMessage[] = [];
        for (const t of turns) {
          msgs.push({ role: 'user', text: t.user, fromHistory: true });
          if (t.assistant) {
            msgs.push({
              role: 'assistant',
              text: t.assistant,
              calls: t.calls ?? [],
              turnId: t.id,
              fromHistory: true,
            });
          }
          if (t.id != null) seenTurnIds.current.add(t.id);
        }
        setMessages(msgs);
      })
      .finally(() => setHistoryLoading(false));
  }, []);

  useEffect(() => {
    const socket = connectSocket({
      onTurn: handleTurn,
      onDelta: handleDelta,
      onError: handleError,
      onDisconnect: handleDisconnect,
      onNotification: handleNotification,
      onDiagnostic: (d) => setDiagnostics((prev) => [...prev, d]),
    });
    socketRef.current = socket;
    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [handleTurn, handleDelta, handleError, handleDisconnect, handleNotification]);

  const sendText = useCallback((text: string) => {
    if (!text || !socketRef.current) return;

    const sessionId = `s${Date.now()}`;
    const streamKey = sessionId;

    pendingRef.current = { sessionId, streamKey };
    setLoading(true);
    setMessages((prev) => [
      ...prev,
      { role: 'user', text },
      { role: 'assistant', text: '', streamKey },
    ]);

    try {
      socketRef.current.send(text, sessionId);
    } catch {
      pendingRef.current = null;
      setLoading(false);
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.streamKey === streamKey);
        if (idx === -1) return prev;
        const next = [...prev];
        next[idx] = { role: 'assistant', text: 'Failed to send. Please try again.' };
        return next;
      });
    }
  }, []);

  const stopGeneration = useCallback(() => {
    if (!socketRef.current || !pendingRef.current) return;
    socketRef.current.stop(pendingRef.current.sessionId);
  }, []);

  const clearChat = useCallback(() => {
    apiClearChat();
    setMessages([]);
    seenTurnIds.current.clear();
    pendingRef.current = null;
  }, []);

  const wipeAllData = useCallback(async () => {
    await apiWipeData();
    setMessages([]);
    seenTurnIds.current.clear();
    pendingRef.current = null;
  }, []);

  const resolveInlineConfirm = useCallback(
    (msgIndex: number, callIndex: number, call: ChatCall, ok: boolean) => {
      const apply = (resultText?: string) => {
        setMessages((cur) => {
          const target = cur[msgIndex];
          if (!target) return cur;
          const calls = [...(target.calls ?? [])];
          if (resultText !== undefined) calls[callIndex] = { ...calls[callIndex], result: resultText };
          const next = [...cur];
          next[msgIndex] = {
            ...target,
            calls,
            callOutcomes: { ...target.callOutcomes, [callIndex]: ok ? 'confirmed' : 'cancelled' },
          };
          return next;
        });
      };

      if (ok) {
        invokeJob(call.name, call.args).then((res) => apply(res.error ?? res.result));
      } else {
        apply();
      }
    },
    [],
  );

  // ---------------------------------------------------------------- generic job runner
  const [jobRanAt, setJobRanAt] = useState(0);
  const runJob = useCallback(
    (name: string, args: Record<string, unknown>, opts: { from: string; title?: string }): Promise<RunResult> => {
      const job = jobsByName.get(name);
      const sig = signature(name, args);

      const execute = async (): Promise<RunResult> => {
        const res = await invokeJob(name, args);
        setJobRanAt(Date.now());
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            text: res.error ?? res.result,
            tag: `Ran from ${opts.from}`,
            calls: [{ name, args, result: res.error ?? res.result }],
          },
        ]);
        return res;
      };

      if (job && needsConfirm(job, args)) {
        return new Promise((resolve) => {
          setConfirmRequest({
            title: opts.title ?? `Run ${humanize(name)}?`,
            sig,
            onConfirm: () => {
              setConfirmRequest(null);
              execute().then(resolve);
            },
            onCancel: () => resolve({ ok: false, result: '', cancelled: true }),
          });
        });
      }

      return execute();
    },
    [jobsByName],
  );

  const value: WonyContextValue = {
    jobs,
    jobsByName,
    jobsLoading,
    health,
    reloadHealth,
    settings,
    reloadSettings,
    panels,
    reloadPanels,
    capabilities,
    routinesCount,
    reloadRoutinesCount,
    jobRanAt,
    pins,
    setPins,
    notifications,
    diagnostics,
    unreadCount,
    ackOne,
    dismissDiagnostic,
    messages,
    loading,
    historyLoading,
    sendText,
    stopGeneration,
    clearChat,
    wipeAllData,
    resolveInlineConfirm,
    runJob,
    confirmRequest,
    requestConfirm,
    cancelConfirm,
  };

  return <WonyContext.Provider value={value}>{children}</WonyContext.Provider>;
}
