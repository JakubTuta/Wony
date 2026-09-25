import { useEffect, useState } from 'react';
import { fetchPanel } from '../../api';
import type { ForecastPanel, WeatherPanel } from '../../api';
import { CARD, SectionLabel } from '../../components/ui';

const REFRESH_MS = 10 * 60 * 1000;

export function Weather() {
  const [panel, setPanel] = useState<WeatherPanel | null>(null);
  const [forecast, setForecast] = useState<ForecastPanel | null>(null);

  useEffect(() => {
    const load = () => {
      fetchPanel<WeatherPanel>('weather').then((r) => setPanel(r.data));
      fetchPanel<ForecastPanel>('forecast').then((r) => setForecast(r.data));
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  if (!panel || panel.error) {
    return (
      <div className={`${CARD} p-4.5 flex flex-col gap-3.5`}>
        <SectionLabel>Weather</SectionLabel>
        <span className="text-sm text-muted">{panel?.error ?? 'Checking the sky…'}</span>
      </div>
    );
  }

  return (
    <div className={`${CARD} p-4.5 flex flex-col gap-3.5`}>
      <div className="flex justify-between items-center">
        <SectionLabel>Weather</SectionLabel>
        <span className="text-xs text-muted">{panel.city}</span>
      </div>
      <div className="flex items-end gap-3.5">
        <span className="text-[52px] font-semibold tracking-tight leading-none">
          {panel.temperature === null ? '—' : Math.round(panel.temperature)}°
        </span>
        <div className="flex flex-col gap-0.5 pb-1">
          <span className="text-base font-medium capitalize">{panel.description}</span>
          <span className="text-[13px] text-muted">
            Feels {panel.feels_like === null ? '—' : Math.round(panel.feels_like)}° · {panel.humidity ?? '—'}%
            {panel.wind !== null ? ` · ${panel.wind} ${panel.wind_unit}` : ''}
          </span>
        </div>
      </div>
      {forecast && forecast.days.length > 0 && (
        <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${forecast.days.length}, 1fr)` }}>
          {forecast.days.map((day) => (
            <div key={day.date} className="flex flex-col items-center gap-0.5 py-2 rounded-[9px] bg-pink-faint-2">
              <span className="text-xs text-muted">{day.label.slice(0, 3)}</span>
              <span className="text-[15px] font-semibold">{day.high}°</span>
              <span className="text-xs text-muted">{day.low}°</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
