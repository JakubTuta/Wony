import { useEffect, useState } from 'react'
import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudMoon,
  CloudRain,
  CloudSnow,
  CloudSun,
  Droplets,
  Moon,
  Sun,
  Sunrise,
  Sunset,
  Thermometer,
  Wind,
} from 'lucide-react'
import { fetchWeather } from '../api'
import type { WeatherPanel } from '../api'
import { useWony } from '../state/wony-context'

// A wall display sits on this for hours. Weather does not move faster than
// this, and OpenWeatherMap's free tier is metered.
const REFRESH_MS = 10 * 60 * 1000

/** OpenWeatherMap's condition id, by its documented families: 2xx storm,
 *  3xx drizzle, 5xx rain, 6xx snow, 7xx haze/fog, 800 clear, 80x cloud. The
 *  icon code's trailing letter is the only thing that says day or night.
 *
 *  Returns elements rather than a component so the choice happens inside one
 *  fixed component, not by picking a different component each render.
 */
function ConditionIcon({ condition, icon }: { condition: number; icon: string }) {
  const shared = { size: 72, strokeWidth: 1.25, className: 'text-accent' }
  const night = icon.endsWith('n')

  if (condition >= 200 && condition < 300) return <CloudLightning {...shared} />
  if (condition >= 300 && condition < 400) return <CloudDrizzle {...shared} />
  if (condition >= 500 && condition < 600) return <CloudRain {...shared} />
  if (condition >= 600 && condition < 700) return <CloudSnow {...shared} />
  if (condition >= 700 && condition < 800) return <CloudFog {...shared} />
  if (condition === 800) return night ? <Moon {...shared} /> : <Sun {...shared} />
  if (condition === 801 || condition === 802) {
    return night ? <CloudMoon {...shared} /> : <CloudSun {...shared} />
  }
  return <Cloud {...shared} />
}

function time(stamp: number | null, locale: string): string {
  if (!stamp) return '—'
  return new Date(stamp * 1000).toLocaleTimeString(locale, {
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Current conditions, read straight from the weather API.
 *
 *  This used to open the chat and ask the agent, which cost a model call to
 *  render one temperature it then had to describe in words.
 */
export function Weather() {
  const { config } = useWony()
  const [panel, setPanel] = useState<WeatherPanel | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const locale = config?.assistant.language || 'en'

  useEffect(() => {
    const load = () => {
      fetchWeather().then((result) => {
        setPanel(result.data)
        setError(result.error ?? result.data?.error ?? null)
        setLoading(false)
      })
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="t-body text-muted">Checking the sky…</p>
      </div>
    )
  }

  if (error || !panel) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center gap-2 px-8">
        <Cloud size={40} className="text-muted" />
        <p className="t-body text-muted">{error ?? 'No weather right now.'}</p>
      </div>
    )
  }

  const degrees = panel.temperature === null ? '—' : Math.round(panel.temperature)

  return (
    <div className="scroll-y flex-1 px-4 py-4 flex flex-col items-center justify-center gap-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <ConditionIcon condition={panel.condition} icon={panel.icon} />
        <div className="flex items-start gap-1">
          <span className="t-clock leading-none">{degrees}</span>
          <span className="t-body text-muted pt-1">{panel.unit}</span>
        </div>
        <p className="t-body capitalize">{panel.description}</p>
        <p className="t-small text-muted">{panel.city}</p>
      </div>

      <div className="w-full max-w-2xl grid grid-cols-2 gap-2">
        <Stat
          icon={<Thermometer size={18} />}
          label="Feels like"
          value={panel.feels_like === null ? '—' : `${Math.round(panel.feels_like)}${panel.unit}`}
        />
        <Stat
          icon={<Droplets size={18} />}
          label="Humidity"
          value={panel.humidity === null ? '—' : `${panel.humidity}%`}
        />
        <Stat
          icon={<Wind size={18} />}
          label="Wind"
          value={panel.wind === null ? '—' : `${Math.round(panel.wind)} ${panel.wind_unit}`}
        />
        <Stat
          icon={<Sunrise size={18} />}
          label="Sunrise"
          value={time(panel.sunrise, locale)}
        />
        <Stat icon={<Sunset size={18} />} label="Sunset" value={time(panel.sunset, locale)} />
      </div>
    </div>
  )
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-surface border border-line">
      <span className="text-muted shrink-0">{icon}</span>
      <div className="min-w-0">
        <div className="t-small text-muted truncate">{label}</div>
        <div className="t-body truncate">{value}</div>
      </div>
    </div>
  )
}
