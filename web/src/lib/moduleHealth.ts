import type { HealthResponse, SettingsModule } from '../api';

export type ModuleHealthState = 'ok' | 'off' | 'broken';

/** 'off' covers both "never turned on" and "no status yet" (same message to
 * the user either way); 'broken' covers misconfigured/unavailable/error. */
export function moduleHealthState(key: string, health: HealthResponse | null): ModuleHealthState {
  const status = health?.modules[key]?.status;
  if (status === 'enabled') return 'ok';
  if (!status || status === 'disabled') return 'off';
  return 'broken';
}

export function moduleMessage(
  key: string,
  health: HealthResponse | null,
  modules: SettingsModule[] | undefined,
  fallbackLabel: string,
): string {
  const label = modules?.find((m) => m.key === key)?.label ?? fallbackLabel;
  if (moduleHealthState(key, health) === 'off') return `Turn on ${label} in Features to see this.`;
  return health?.modules[key]?.reason || `${label} isn't working right now.`;
}
