import {
  Mail,
  CalendarDays,
  CloudSun,
  Music,
  Globe,
  Monitor,
  Clock,
  Brain,
  Wrench,
  Zap,
  Bell,
  Home,
  BarChart2,
  type LucideIcon,
} from 'lucide-react';

const MODULE_ICONS: Record<string, LucideIcon> = {
  gmail: Mail,
  calendar: CalendarDays,
  weather: CloudSun,
  spotify: Music,
  web: Globe,
  desktop: Monitor,
  basics: Clock,
  ai: Brain,
  scheduler: Bell,
  home_assistant: Home,
  league: BarChart2,
  status: Zap,
};

/** A component, not a component *factory* — picking the icon inside a caller's
 *  render and rendering the result counts as creating a component per render. */
export function ModuleIcon({ module, size }: { module: string; size?: number }) {
  const Icon = MODULE_ICONS[module.toLowerCase()] ?? Wrench;
  return <Icon size={size} />;
}

export type { LucideIcon };
