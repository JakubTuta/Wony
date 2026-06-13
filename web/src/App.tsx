import { useEffect, useState, useCallback } from 'react';
import { Bot, Cpu, AlertCircle, MessageSquare, Wrench } from 'lucide-react';
import { fetchHealth, fetchJobs, connectEventSocket } from './api';
import type { HealthResponse, Job, Diagnostic } from './api';
import { ChatPanel } from './components/ChatPanel';
import { JobsPanel } from './components/JobsPanel';
import { DiagnosticsBanner } from './components/DiagnosticsBanner';

type Tab = 'chat' | 'jobs';

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>('chat');
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setHealth(h);
        if (h.diagnostics && h.diagnostics.length > 0) {
          setDiagnostics(h.diagnostics);
        }
      })
      .catch(() => setHealthError(true));

    fetchJobs()
      .then(setJobs)
      .catch(() => {})
      .finally(() => setJobsLoading(false));
  }, []);

  // Merge incoming live diagnostics (dedup by source+message).
  const handleDiagnostic = useCallback((d: Diagnostic) => {
    setDiagnostics((prev) => {
      const key = `${d.source}:${d.message}`;
      if (prev.some((x) => `${x.source}:${x.message}` === key)) return prev;
      return [...prev, d];
    });
  }, []);

  useEffect(() => {
    return connectEventSocket({ onDiagnostic: handleDiagnostic });
  }, [handleDiagnostic]);

  const compute = health?.compute;
  const hasCpuFallback = compute && !compute.cuda_ok;

  const providerLabel = health?.provider
    ? `${health.provider}${health.model ? ` · ${health.model}` : ''}`
    : null;

  const enabledCount = health
    ? Object.values(health.modules).filter(m => m.status === 'enabled').length
    : 0;

  const computeLabel = compute
    ? `STT:${compute.stt_device} TTS:${compute.tts_device}`
    : null;

  return (
    <div className="h-screen overflow-hidden bg-gray-50 dark:bg-gray-950 flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 px-4 py-3 flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-violet-600 flex items-center justify-center">
            <Bot size={18} className="text-white" />
          </div>
          <span className="font-semibold text-gray-900 dark:text-gray-100 text-base">Wony</span>
        </div>

        <div className="flex-1" />

        {/* Provider/status pill */}
        {healthError ? (
          <div className="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-full px-3 py-1">
            <AlertCircle size={12} />
            Server unreachable
          </div>
        ) : health ? (
          <div className="flex items-center gap-3">
            <div className={`hidden sm:flex items-center gap-1.5 text-xs rounded-full px-3 py-1 ${
              hasCpuFallback
                ? 'text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700'
                : 'text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800'
            }`}>
              <Cpu size={12} />
              <span>{providerLabel ?? 'Unknown provider'}</span>
              {computeLabel && (
                <span className="opacity-70 ml-1">· {computeLabel}</span>
              )}
            </div>
            <div className="text-xs text-gray-400 dark:text-gray-500">
              {enabledCount} module{enabledCount !== 1 ? 's' : ''} active
            </div>
          </div>
        ) : (
          <div className="h-6 w-32 bg-gray-100 dark:bg-gray-800 rounded-full animate-pulse" />
        )}
      </header>

      {/* Diagnostics banner — amber/red alerts with fix hints */}
      <DiagnosticsBanner diagnostics={diagnostics} />

      {/* Mobile tab bar */}
      <div className="lg:hidden flex border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <TabButton active={activeTab === 'chat'} onClick={() => setActiveTab('chat')}>
          <MessageSquare size={14} />
          Chat
        </TabButton>
        <TabButton active={activeTab === 'jobs'} onClick={() => setActiveTab('jobs')}>
          <Wrench size={14} />
          Jobs {jobs.length > 0 && <span className="ml-1 text-xs opacity-60">({jobs.length})</span>}
        </TabButton>
      </div>

      {/* Main content */}
      <main className="flex-1 flex overflow-hidden">
        {/* Desktop: two-pane side by side */}
        <div className="hidden lg:flex w-full h-full">
          <Pane title="Chat" icon={<MessageSquare size={15} />} className="w-[45%] min-w-0 border-r border-gray-200 dark:border-gray-800">
            <ChatPanel />
          </Pane>
          <Pane
            title={`Jobs${jobs.length ? ` (${jobs.length})` : ''}`}
            icon={<Wrench size={15} />}
            className="flex-1 min-w-0"
          >
            <JobsPanel jobs={jobs} loading={jobsLoading} />
          </Pane>
        </div>

        {/* Mobile: single active tab */}
        <div className="lg:hidden w-full h-full">
          {activeTab === 'chat' ? (
            <Pane title="Chat" icon={<MessageSquare size={15} />} className="h-full">
              <ChatPanel />
            </Pane>
          ) : (
            <Pane title={`Jobs${jobs.length ? ` (${jobs.length})` : ''}`} icon={<Wrench size={15} />} className="h-full">
              <JobsPanel jobs={jobs} loading={jobsLoading} />
            </Pane>
          )}
        </div>
      </main>
    </div>
  );
}

function Pane({
  title,
  icon,
  children,
  className = '',
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col bg-white dark:bg-gray-900 ${className}`}>
      <div className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 flex items-center gap-2">
        <span className="text-gray-400 dark:text-gray-500">{icon}</span>
        <span className="text-sm font-medium text-gray-600 dark:text-gray-400">{title}</span>
      </div>
      <div className="flex-1 overflow-hidden flex flex-col">
        {children}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 text-sm font-medium transition-colors border-b-2 ${
        active
          ? 'border-violet-500 text-violet-600 dark:text-violet-400'
          : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
      }`}
    >
      {children}
    </button>
  );
}
