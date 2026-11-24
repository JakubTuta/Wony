import {
  Blinds, Bot, Clapperboard, Droplets, Fan, Lightbulb, Lock, Plug, Power, ShieldCheck, Siren,
  SlidersHorizontal, Thermometer, Tv, Warehouse, Workflow, CircleDot,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { Control } from '../api';

const ICONS: Record<string, LucideIcon> = {
  light: Lightbulb,
  switch: Power,
  input_boolean: Power,
  cover: Blinds,
  climate: Thermometer,
  media_player: Tv,
  remote: Tv,
  lock: Lock,
  alarm_control_panel: ShieldCheck,
  fan: Fan,
  vacuum: Bot,
  lawn_mower: Bot,
  scene: Clapperboard,
  script: Workflow,
  automation: Workflow,
  siren: Siren,
  humidifier: Droplets,
  water_heater: Droplets,
  valve: Droplets,
  button: CircleDot,
  select: SlidersHorizontal,
  input_select: SlidersHorizontal,
  number: SlidersHorizontal,
  input_number: SlidersHorizontal,
};

/** The glyph for what a device is, so a row or a map marker reads at a glance. */
export function DeviceIcon({
  control, size = 18, className,
}: { control: Pick<Control, 'domain' | 'guarded'>; size?: number; className?: string }) {
  // A garage door or gate is a cover, but a blind icon would be the wrong promise.
  const Icon = control.domain === 'cover' && control.guarded ? Warehouse : (ICONS[control.domain] ?? Plug);
  return <Icon size={size} className={className} aria-hidden />;
}
