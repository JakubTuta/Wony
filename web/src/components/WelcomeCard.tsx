import type { SettingsResponse } from '../api';
import { useWony } from '../lib/wonyContext';
import { CARD } from './ui';

function fieldValue(settings: SettingsResponse | null, key: string): string | number | boolean | null {
  for (const section of settings?.sections ?? []) {
    const field = section.fields.find((f) => f.key === key);
    if (field) return field.value;
  }
  return null;
}

function providerLabel(provider: string | undefined): string {
  if (provider === 'anthropic') return 'Anthropic (Claude)';
  if (provider === 'gemini') return 'Google Gemini';
  if (provider === 'ollama') return 'nowhere — Ollama runs on this PC';
  return 'your AI provider';
}

/** Shown in place of the chat history when there are no messages yet — an
 * app-drawn greeting rather than a model-written one, so it reads the same
 * for everyone and still shows the setup step before an AI key exists, when
 * there is no model to ask. */
export function WelcomeCard({ onExample }: { onExample: (text: string) => void }) {
  const { settings, capabilities, health } = useWony();

  const ownerName = String(fieldValue(settings, 'assistant.owner_name') || 'User');
  const greeting = ownerName && ownerName !== 'User' ? `Hi ${ownerName}` : 'Hi there';

  const noKey = health?.provider === 'unknown';
  const working = capabilities?.working ?? [];
  const available = capabilities?.available ?? [];

  const hotkey = String(fieldValue(settings, 'voice.hotkeys.push_to_talk') || '');
  const wakeOn = Boolean(fieldValue(settings, 'voice.wake_word.enabled'));
  const wakePhrase = String(fieldValue(settings, 'voice.wake_word.phrase') || 'hey jarvis');

  const ways = ['typing here', hotkey && `pressing ${hotkey}`, wakeOn && `saying "${wakePhrase}"`, 'the mic button']
    .filter(Boolean)
    .join(', ');

  return (
    <div className={`${CARD} p-5 flex flex-col gap-4`}>
      <span className="text-lg font-bold">{greeting}, I'm Wony.</span>

      {noKey ? (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm">I need an AI key before I can answer anything.</p>
          <p className="text-sm text-muted">
            Open Settings → AI and paste a key from Anthropic or Google Gemini, or set the
            provider to Ollama to run fully on this PC — no key needed, just slower.
          </p>
        </div>
      ) : (
        <>
          {working.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-[0.06em] text-muted">Try me</span>
              <div className="flex flex-wrap gap-1.5">
                {working.slice(0, 6).map((cap) => (
                  <button
                    key={cap.key}
                    onClick={() => onExample(cap.example)}
                    className="border rounded-full px-2.5 py-1.5 text-[13px] bg-surface"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    {cap.example}
                  </button>
                ))}
              </div>
            </div>
          )}
          {available.length > 0 && (
            <p className="text-xs text-muted">
              {available.length} more feature{available.length === 1 ? '' : 's'} you can switch on in
              Features: {available.slice(0, 4).map((c) => c.label).join(', ')}
              {available.length > 4 ? ', …' : '.'}
            </p>
          )}
        </>
      )}

      <div className="flex flex-col gap-1 text-xs text-muted">
        <span>Talk to me by {ways}.</span>
        <span>I always ask before sending, deleting or unlocking anything.</span>
        <span>Your requests go to {providerLabel(health?.provider)}; voice recognition and speech stay on this PC.</span>
      </div>
    </div>
  );
}
