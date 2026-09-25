import { createContext, useContext } from 'react';
import type {
  ChatCall,
  Diagnostic,
  HealthResponse,
  Job,
  Notification,
  PanelInfo,
  Pin,
  SettingsResponse,
} from '../api';

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  tag?: string;
  calls?: ChatCall[];
  turnId?: number | null;
  streamKey?: string;
  /** callIndex -> what the user did with that call's inline confirm card. */
  callOutcomes?: Record<number, 'confirmed' | 'cancelled'>;
  /** Loaded from chat history on page load — its confirmation window (5 min,
   * see helpers/confirm.py) has long since expired, so it renders inert. */
  fromHistory?: boolean;
}

export interface ConfirmRequest {
  title: string;
  sig: string;
  onConfirm: () => void;
}

export interface RunResult {
  ok: boolean;
  result: string;
  error?: string;
}

export interface WonyContextValue {
  jobs: Job[];
  jobsByName: Map<string, Job>;
  jobsLoading: boolean;

  health: HealthResponse | null;
  reloadHealth: () => void;

  settings: SettingsResponse | null;
  reloadSettings: () => void;

  panels: PanelInfo[];
  reloadPanels: () => void;

  routinesCount: number;
  reloadRoutinesCount: () => void;

  /** Bumped to Date.now() every time runJob completes — widgets that poll a
   * panel add this to their effect deps so a run from elsewhere (chat, a
   * different pin) reflects immediately instead of waiting for the next
   * poll tick. */
  jobRanAt: number;

  pins: Pin[] | null;
  setPins: (pins: Pin[]) => void;

  notifications: Notification[];
  diagnostics: Diagnostic[];
  unreadCount: number;
  ackOne: (id?: number) => void;
  dismissDiagnostic: (index: number) => void;

  messages: ChatMessage[];
  loading: boolean;
  historyLoading: boolean;
  sendText: (text: string) => void;
  stopGeneration: () => void;
  clearChat: () => void;
  wipeAllData: () => Promise<void>;
  resolveInlineConfirm: (msgIndex: number, callIndex: number, call: ChatCall, ok: boolean) => void;

  runJob: (name: string, args: Record<string, unknown>, opts: { from: string; title?: string }) => Promise<RunResult>;

  confirmRequest: ConfirmRequest | null;
  requestConfirm: (req: ConfirmRequest) => void;
  cancelConfirm: () => void;
}

export const WonyContext = createContext<WonyContextValue | null>(null);

export function useWony(): WonyContextValue {
  const ctx = useContext(WonyContext);
  if (!ctx) throw new Error('useWony must be used inside <WonyProvider>');
  return ctx;
}
