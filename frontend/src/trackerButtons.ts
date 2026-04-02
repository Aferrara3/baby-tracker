import {
  Baby,
  Bath,
  BookOpen,
  BottleWine,
  Briefcase,
  CarFront,
  Droplet,
  Dumbbell,
  Heart,
  HelpCircle,
  House,
  Milk,
  Moon,
  Music4,
  Phone,
  Pill,
  ShoppingBag,
  Stethoscope,
  Timer,
  Toilet,
  User2,
  Utensils,
  type LucideIcon,
} from 'lucide-react';

export interface TrackerButtonConfig {
  id: string;
  label: string;
  icon_key: string;
  color_key: string;
  position: number;
  emoji: string;
  title: string;
}

export interface TrackerButtonUpdate {
  id: string;
  label: string;
  icon_key: string;
  color_key: string;
  position: number;
}

export interface TrackerSymbolOption {
  key: string;
  label: string;
  emoji: string;
  keywords: string[];
}

export interface TrackerButtonsResponse {
  buttons: TrackerButtonConfig[];
  available_symbols: TrackerSymbolOption[];
}

const ICONS_BY_KEY: Record<string, LucideIcon> = {
  baby: Baby,
  bath: Bath,
  'book-open': BookOpen,
  'bottle-wine': BottleWine,
  briefcase: Briefcase,
  'car-front': CarFront,
  droplet: Droplet,
  dumbbell: Dumbbell,
  heart: Heart,
  'help-circle': HelpCircle,
  house: House,
  milk: Milk,
  moon: Moon,
  'music-4': Music4,
  phone: Phone,
  pill: Pill,
  'shopping-bag': ShoppingBag,
  stethoscope: Stethoscope,
  timer: Timer,
  toilet: Toilet,
  'user-2': User2,
  utensils: Utensils,
};

const COLOR_CLASS_BY_KEY: Record<string, string> = {
  blue: 'bg-gradient-to-br from-blue-400 to-blue-600 dark:from-blue-500 dark:to-blue-700 shadow-blue-200 dark:shadow-blue-900/30',
  amber: 'bg-gradient-to-br from-amber-400 to-amber-600 dark:from-amber-500 dark:to-amber-700 shadow-amber-200 dark:shadow-amber-900/30',
  cyan: 'bg-gradient-to-br from-cyan-400 to-cyan-600 dark:from-cyan-500 dark:to-cyan-700 shadow-cyan-200 dark:shadow-cyan-900/30',
  pink: 'bg-gradient-to-br from-pink-400 to-pink-600 dark:from-pink-500 dark:to-pink-700 shadow-pink-200 dark:shadow-pink-900/30',
  indigo: 'bg-gradient-to-br from-indigo-400 to-indigo-600 dark:from-indigo-500 dark:to-indigo-700 shadow-indigo-200 dark:shadow-indigo-900/30',
  rose: 'bg-gradient-to-br from-rose-400 to-rose-600 dark:from-rose-500 dark:to-rose-700 shadow-rose-200 dark:shadow-rose-900/30',
  orange: 'bg-gradient-to-br from-orange-400 to-orange-600 dark:from-orange-500 dark:to-orange-700 shadow-orange-200 dark:shadow-orange-900/30',
  slate: 'bg-gradient-to-br from-slate-400 to-slate-600 dark:from-slate-500 dark:to-slate-700 shadow-slate-200 dark:shadow-slate-900/30',
};

export const DEFAULT_TRACKER_SYMBOLS: TrackerSymbolOption[] = [
  { key: 'bottle-wine', label: 'Bottle', emoji: '🍼', keywords: ['milk', 'feed', 'drink'] },
  { key: 'utensils', label: 'Food', emoji: '🥄', keywords: ['meal', 'eat', 'snack'] },
  { key: 'baby', label: 'Baby', emoji: '👶', keywords: ['kid', 'child', 'care'] },
  { key: 'droplet', label: 'Pee', emoji: '💧', keywords: ['diaper', 'wet', 'bathroom'] },
  { key: 'moon', label: 'Sleep', emoji: '😴', keywords: ['nap', 'rest', 'night'] },
  { key: 'toilet', label: 'Poop', emoji: '💩', keywords: ['diaper', 'bathroom', 'change'] },
  { key: 'user-2', label: 'Person', emoji: '🧍', keywords: ['personal', 'self', 'caregiver'] },
  { key: 'milk', label: 'Milk', emoji: '🥛', keywords: ['pump', 'drink', 'feed'] },
  { key: 'help-circle', label: 'Help', emoji: '❓', keywords: ['other', 'misc', 'question'] },
  { key: 'briefcase', label: 'Work', emoji: '💼', keywords: ['office', 'job', 'career'] },
  { key: 'dumbbell', label: 'Exercise', emoji: '🏋️', keywords: ['workout', 'gym', 'fitness'] },
  { key: 'bath', label: 'Bath', emoji: '🛁', keywords: ['wash', 'clean', 'shower'] },
  { key: 'car-front', label: 'Travel', emoji: '🚗', keywords: ['drive', 'trip', 'car'] },
  { key: 'shopping-bag', label: 'Errands', emoji: '🛍️', keywords: ['shop', 'store', 'buy'] },
  { key: 'house', label: 'Home', emoji: '🏠', keywords: ['household', 'chores', 'home'] },
  { key: 'book-open', label: 'Learning', emoji: '📚', keywords: ['reading', 'school', 'study'] },
  { key: 'stethoscope', label: 'Health', emoji: '🩺', keywords: ['doctor', 'medical', 'care'] },
  { key: 'phone', label: 'Call', emoji: '📞', keywords: ['phone', 'talk', 'contact'] },
  { key: 'music-4', label: 'Music', emoji: '🎵', keywords: ['song', 'audio', 'listen'] },
  { key: 'heart', label: 'Love', emoji: '❤️', keywords: ['care', 'family', 'connection'] },
  { key: 'pill', label: 'Medicine', emoji: '💊', keywords: ['meds', 'rx', 'health'] },
  { key: 'timer', label: 'Timer', emoji: '⏱️', keywords: ['track', 'duration', 'time'] },
];

export const DEFAULT_TRACKER_BUTTONS: TrackerButtonConfig[] = [
  { id: 'bottle', label: 'Bottle', icon_key: 'bottle-wine', color_key: 'blue', position: 0, emoji: '🍼', title: '🍼 Bottle' },
  { id: 'food', label: 'Food', icon_key: 'utensils', color_key: 'amber', position: 1, emoji: '🥄', title: '🥄 Food' },
  { id: 'diaper_pee', label: 'Pee', icon_key: 'droplet', color_key: 'cyan', position: 2, emoji: '💧', title: '💧 Pee' },
  { id: 'diaper_poop', label: 'Poop', icon_key: 'toilet', color_key: 'pink', position: 3, emoji: '💩', title: '💩 Poop' },
  { id: 'sleep', label: 'Sleep', icon_key: 'moon', color_key: 'indigo', position: 4, emoji: '😴', title: '😴 Sleep' },
  { id: 'breastfeeding', label: 'Nursing', icon_key: 'user-2', color_key: 'rose', position: 5, emoji: '🧍', title: '🧍 Nursing' },
  { id: 'pump', label: 'Pump', icon_key: 'milk', color_key: 'orange', position: 6, emoji: '🥛', title: '🥛 Pump' },
  { id: 'help', label: 'Other', icon_key: 'help-circle', color_key: 'slate', position: 7, emoji: '❓', title: '❓ Other' },
];

export function getTrackerButtonIcon(iconKey: string): LucideIcon {
  return ICONS_BY_KEY[iconKey] ?? HelpCircle;
}

export function getTrackerButtonColorClass(colorKey: string): string {
  return COLOR_CLASS_BY_KEY[colorKey] ?? COLOR_CLASS_BY_KEY.slate;
}

export function getTrackerSymbol(symbols: TrackerSymbolOption[], iconKey: string): TrackerSymbolOption | undefined {
  return symbols.find((symbol) => symbol.key === iconKey) ?? DEFAULT_TRACKER_SYMBOLS.find((symbol) => symbol.key === iconKey);
}

export function deriveTrackerButton(button: TrackerButtonUpdate | TrackerButtonConfig, symbols: TrackerSymbolOption[]): TrackerButtonConfig {
  const rawLabel = button.label;
  const label = rawLabel.trim() || 'Untitled';
  const symbol = getTrackerSymbol(symbols, button.icon_key);
  const emoji = symbol?.emoji ?? '🏷️';

  return {
    id: button.id,
    label: rawLabel,
    icon_key: button.icon_key,
    color_key: button.color_key,
    position: button.position,
    emoji,
    title: `${emoji} ${label}`,
  };
}

export function sortTrackerButtons<T extends { position: number }>(buttons: T[]): T[] {
  return [...buttons].sort((left, right) => left.position - right.position);
}

export function normalizeTrackerButtons(buttons: TrackerButtonConfig[], symbols: TrackerSymbolOption[]): TrackerButtonConfig[] {
  return sortTrackerButtons(buttons).map((button, index) => deriveTrackerButton({ ...button, position: index }, symbols));
}
