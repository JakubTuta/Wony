import { useEffect, useState } from 'react';
import {
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  Cloud,
  Droplets,
  Sun,
  Sunrise,
  Sunset,
  Wind,
} from 'lucide-react';
import { fetchPanel } from '../api';
import type { WeatherPanel } from '../api';
import { CARD, MUTED, Resting } from './ui';

// OpenWeatherMap updates its own data every ten minutes or so; polling faster
// spends calls to redraw the same number.
const REFRESH_MS = 10 * 60 * 1000;

/** OpenWeatherMap condition codes: 2xx storm, 3xx drizzle, 5xx rain,
 *  6xx snow, 7xx atmosphere, 800 clear, 80x cloud. */
function ConditionIcon({ code, size = 44 }: { code: number; size?: number }) {
  const cls = 'text-violet-500';
  if (code >= 200 && code < 300) return <CloudLightning size={size} className={cls} />;
  if (code >= 300 && code < 400) return <CloudDrizzle size={size} className={cls} />;
  if (code >= 500 && code < 600) return <CloudRain size={size} className={cls} />;
  if (code >= 600 && code < 700) return <CloudSnow size={size} className={cls} />;
  if (code >= 700 && code < 800) return <CloudFog size={size} className={cls} />;
  if (code === 800) return <Sun size={size} className={cls} />;
  return <Cloud size={size} className={cls} />;
}

function time(epoch: number | null, locale: string): string {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleTimeString(locale, {
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function Weather({ locale }: { locale: string }) {
  const [panel, setPanel] = useState<WeatherPanel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => {
      fetchPanel<WeatherPanel>('weather').then((result) => {
        setPanel(result.data);
        setError(result.error);
        setLoading(false);
      });
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  if (loading) return <Resting title="Checking the sky…" />;

  const failure = error ?? panel?.error;
  if (failure || !panel) {
    return <Resting icon={<Cloud size={32} />} title={failure ?? 'No weather right now.'} />;
  }

  return (
    <div className="p-4 space-y-3">
      <div className={`${CARD} p-5 flex items-center gap-4`}>
        <ConditionIcon code={panel.condition} />
        <div className="min-w-0">
          <div className="text-3xl font-semibold text-gray-900 dark:text-gray-100 tabular-nums">
            {panel.temperature === null ? '—' : Math.round(panel.temperature)}
            {panel.unit}
          </div>
          <div className="text-sm text-gray-700 dark:text-gray-300 capitalize truncate">
            {panel.description}
          </div>
          <div className={`text-xs ${MUTED} truncate`}>{panel.city}</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          icon={<Sun size={14} />}
          label="Feels like"
          value={panel.feels_like === null ? '—' : `${Math.round(panel.feels_like)}${panel.unit}`}
        />
        <Stat
          icon={<Droplets size={14} />}
          label="Humidity"
          value={panel.humidity === null ? '—' : `${panel.humidity}%`}
        />
        <Stat
          icon={<Wind size={14} />}
          label="Wind"
          value={panel.wind === null ? '—' : `${panel.wind} ${panel.wind_unit}`}
        />
        <Stat
          icon={<Sunrise size={14} />}
          label="Sunrise"
          value={time(panel.sunrise, locale)}
        />
        <Stat icon={<Sunset size={14} />} label="Sunset" value={time(panel.sunset, locale)} />
      </div>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className={`${CARD} px-3 py-2.5`}>
      <div className={`flex items-center gap-1.5 text-[11px] ${MUTED}`}>
        {icon}
        {label}
      </div>
      <div className="text-sm font-medium text-gray-900 dark:text-gray-100 tabular-nums mt-0.5">
        {value}
      </div>
    </div>
  );
}
