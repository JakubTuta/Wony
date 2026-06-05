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
  shelly: Home,
  league: BarChart2,
  status: Zap,
};

export function iconForModule(module: string): LucideIcon {
  return MODULE_ICONS[module.toLowerCase()] ?? Wrench;
}

export type { LucideIcon };
