import {
  AlarmClock,
  Apple,
  Baby,
  Banknote,
  Bath,
  Bed,
  Bike,
  Bird,
  Bone,
  BookOpen,
  BottleWine,
  Briefcase,
  Bus,
  Cake,
  CalendarCheck,
  CalendarHeart,
  CarFront,
  Camera,
  Carrot,
  Cat,
  ClipboardList,
  Coffee,
  CookingPot,
  Dog,
  Droplet,
  Dumbbell,
  Fish,
  ForkKnife,
  Frown,
  Gamepad2,
  Gift,
  HandHeart,
  Heart,
  HeartPulse,
  HelpCircle,
  House,
  Leaf,
  Milk,
  Moon,
  MoonStar,
  Music4,
  NotebookPen,
  PawPrint,
  Phone,
  Pill,
  PillBottle,
  Plane,
  Popcorn,
  Rabbit,
  Salad,
  Sandwich,
  ScanHeart,
  ShoppingCart,
  ShoppingBag,
  ShowerHead,
  Smile,
  Sparkles,
  Stethoscope,
  Sun,
  Syringe,
  TentTree,
  Thermometer,
  Timer,
  TrainFront,
  Toilet,
  User2,
  Utensils,
  Wallet,
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

export const TRACKER_BUTTONS_PER_PAGE = 8;
export const MAX_TRACKER_BUTTON_PAGES = 3;
const PLACEHOLDER_PAGE_PREFIX = 'extra_page';

const ICONS_BY_KEY: Record<string, LucideIcon> = {
  'alarm-clock': AlarmClock,
  apple: Apple,
  baby: Baby,
  banknote: Banknote,
  bath: Bath,
  bed: Bed,
  bike: Bike,
  bird: Bird,
  bone: Bone,
  'book-open': BookOpen,
  'bottle-wine': BottleWine,
  briefcase: Briefcase,
  bus: Bus,
  cake: Cake,
  'calendar-check': CalendarCheck,
  'calendar-heart': CalendarHeart,
  'car-front': CarFront,
  camera: Camera,
  carrot: Carrot,
  cat: Cat,
  'clipboard-list': ClipboardList,
  coffee: Coffee,
  'cooking-pot': CookingPot,
  dog: Dog,
  droplet: Droplet,
  dumbbell: Dumbbell,
  fish: Fish,
  'fork-knife': ForkKnife,
  frown: Frown,
  'gamepad-2': Gamepad2,
  gift: Gift,
  'hand-heart': HandHeart,
  heart: Heart,
  'heart-pulse': HeartPulse,
  'help-circle': HelpCircle,
  house: House,
  leaf: Leaf,
  milk: Milk,
  moon: Moon,
  'moon-star': MoonStar,
  'music-4': Music4,
  'notebook-pen': NotebookPen,
  'paw-print': PawPrint,
  phone: Phone,
  pill: Pill,
  'pill-bottle': PillBottle,
  plane: Plane,
  popcorn: Popcorn,
  rabbit: Rabbit,
  salad: Salad,
  sandwich: Sandwich,
  'scan-heart': ScanHeart,
  'shopping-cart': ShoppingCart,
  'shopping-bag': ShoppingBag,
  'shower-head': ShowerHead,
  smile: Smile,
  sparkles: Sparkles,
  stethoscope: Stethoscope,
  sun: Sun,
  syringe: Syringe,
  'tent-tree': TentTree,
  thermometer: Thermometer,
  timer: Timer,
  'train-front': TrainFront,
  toilet: Toilet,
  'user-2': User2,
  utensils: Utensils,
  wallet: Wallet,
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
  { key: 'paw-print', label: 'Pet', emoji: '🐾', keywords: ['pet', 'animal', 'walk'] },
  { key: 'bone', label: 'Pet food', emoji: '🦴', keywords: ['dog', 'pet', 'treat'] },
  { key: 'cat', label: 'Cat', emoji: '🐱', keywords: ['pet', 'animal', 'feline'] },
  { key: 'dog', label: 'Dog', emoji: '🐶', keywords: ['pet', 'animal', 'canine'] },
  { key: 'fish', label: 'Fish', emoji: '🐟', keywords: ['pet', 'tank', 'aquarium'] },
  { key: 'bird', label: 'Bird', emoji: '🐦', keywords: ['pet', 'animal', 'avian'] },
  { key: 'rabbit', label: 'Rabbit', emoji: '🐰', keywords: ['pet', 'animal', 'bunny'] },
  { key: 'syringe', label: 'Shot', emoji: '💉', keywords: ['vaccine', 'medical', 'medicine'] },
  { key: 'thermometer', label: 'Temperature', emoji: '🌡️', keywords: ['fever', 'check', 'health'] },
  { key: 'heart-pulse', label: 'Vitals', emoji: '🫀', keywords: ['heart', 'pulse', 'health'] },
  { key: 'apple', label: 'Fruit', emoji: '🍎', keywords: ['snack', 'food', 'nutrition'] },
  { key: 'salad', label: 'Salad', emoji: '🥗', keywords: ['meal', 'greens', 'nutrition'] },
  { key: 'sandwich', label: 'Lunch', emoji: '🥪', keywords: ['meal', 'food', 'sandwich'] },
  { key: 'carrot', label: 'Veggies', emoji: '🥕', keywords: ['vegetable', 'food', 'nutrition'] },
  { key: 'coffee', label: 'Coffee', emoji: '☕', keywords: ['drink', 'caffeine', 'break'] },
  { key: 'cake', label: 'Treat', emoji: '🎂', keywords: ['dessert', 'celebration', 'snack'] },
  { key: 'alarm-clock', label: 'Reminder', emoji: '⏰', keywords: ['alarm', 'wake', 'time'] },
  { key: 'calendar-check', label: 'Appointment', emoji: '🗓️', keywords: ['calendar', 'meeting', 'scheduled'] },
  { key: 'calendar-heart', label: 'Special day', emoji: '💗', keywords: ['date', 'anniversary', 'celebration'] },
  { key: 'clipboard-list', label: 'Checklist', emoji: '📋', keywords: ['tasks', 'todo', 'notes'] },
  { key: 'sun', label: 'Daytime', emoji: '☀️', keywords: ['morning', 'day', 'outside'] },
  { key: 'moon-star', label: 'Night', emoji: '🌙', keywords: ['evening', 'bedtime', 'night'] },
  { key: 'bed', label: 'Rest', emoji: '🛏️', keywords: ['sleep', 'nap', 'bed'] },
  { key: 'plane', label: 'Flight', emoji: '✈️', keywords: ['travel', 'airport', 'trip'] },
  { key: 'train-front', label: 'Train', emoji: '🚆', keywords: ['commute', 'travel', 'rail'] },
  { key: 'bus', label: 'Bus', emoji: '🚌', keywords: ['commute', 'school', 'transport'] },
  { key: 'fork-knife', label: 'Meal', emoji: '🍽️', keywords: ['dinner', 'restaurant', 'food'] },
  { key: 'laptop', label: 'Laptop', emoji: '💻', keywords: ['computer', 'work', 'study'] },
  { key: 'notebook-pen', label: 'Notes', emoji: '📝', keywords: ['journal', 'write', 'study'] },
  { key: 'shower-head', label: 'Shower', emoji: '🚿', keywords: ['bath', 'wash', 'clean'] },
  { key: 'sparkles', label: 'Self care', emoji: '✨', keywords: ['beauty', 'care', 'reset'] },
  { key: 'smile', label: 'Good mood', emoji: '🙂', keywords: ['happy', 'mood', 'emotion'] },
  { key: 'frown', label: 'Low mood', emoji: '☹️', keywords: ['sad', 'mood', 'emotion'] },
  { key: 'popcorn', label: 'Movie', emoji: '🍿', keywords: ['show', 'movie', 'fun'] },
  { key: 'gamepad-2', label: 'Gaming', emoji: '🎮', keywords: ['game', 'play', 'hobby'] },
  { key: 'leaf', label: 'Outdoors', emoji: '🍃', keywords: ['walk', 'nature', 'outside'] },
  { key: 'pill-bottle', label: 'Meds', emoji: '💊', keywords: ['medicine', 'rx', 'dose'] },
  { key: 'bike', label: 'Ride', emoji: '🚴', keywords: ['bike', 'exercise', 'commute'] },
  { key: 'tent-tree', label: 'Adventure', emoji: '🏕️', keywords: ['camp', 'trip', 'outdoors'] },
  { key: 'shopping-cart', label: 'Shopping', emoji: '🛒', keywords: ['groceries', 'store', 'errands'] },
  { key: 'wallet', label: 'Money', emoji: '👛', keywords: ['spending', 'budget', 'wallet'] },
  { key: 'banknote', label: 'Cash', emoji: '💵', keywords: ['money', 'finance', 'pay'] },
  { key: 'gift', label: 'Gift', emoji: '🎁', keywords: ['present', 'birthday', 'celebration'] },
  { key: 'camera', label: 'Photo', emoji: '📷', keywords: ['picture', 'memory', 'camera'] },
  { key: 'cooking-pot', label: 'Cooking', emoji: '🍲', keywords: ['kitchen', 'meal', 'cook'] },
  { key: 'scan-heart', label: 'Checkup', emoji: '🩺', keywords: ['scan', 'health', 'medical'] },
  { key: 'hand-heart', label: 'Care', emoji: '🫶', keywords: ['support', 'care', 'love'] },
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

export const SECOND_PAGE_DEFAULT_TRACKER_BUTTONS: TrackerButtonConfig[] = [
  { id: 'medicine', label: 'Medicine', icon_key: 'pill-bottle', color_key: 'rose', position: 8, emoji: '💊', title: '💊 Medicine' },
  { id: 'temperature', label: 'Temp', icon_key: 'thermometer', color_key: 'amber', position: 9, emoji: '🌡️', title: '🌡️ Temp' },
  { id: 'bath', label: 'Bath', icon_key: 'bath', color_key: 'cyan', position: 10, emoji: '🛁', title: '🛁 Bath' },
  { id: 'outside', label: 'Outside', icon_key: 'leaf', color_key: 'blue', position: 11, emoji: '🍃', title: '🍃 Outside' },
  { id: 'tummy_time', label: 'Tummy', icon_key: 'baby', color_key: 'pink', position: 12, emoji: '👶', title: '👶 Tummy' },
  { id: 'play', label: 'Play', icon_key: 'gamepad-2', color_key: 'indigo', position: 13, emoji: '🎮', title: '🎮 Play' },
  { id: 'doctor', label: 'Doctor', icon_key: 'stethoscope', color_key: 'orange', position: 14, emoji: '🩺', title: '🩺 Doctor' },
  { id: 'notes', label: 'Notes', icon_key: 'notebook-pen', color_key: 'slate', position: 15, emoji: '📝', title: '📝 Notes' },
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

export function createTrackerButtonsForPage(pageIndex: number, symbols: TrackerSymbolOption[]): TrackerButtonConfig[] {
  const pageStart = pageIndex * TRACKER_BUTTONS_PER_PAGE;
  if (pageIndex === 0) {
    return DEFAULT_TRACKER_BUTTONS.map((button, index) => deriveTrackerButton({ ...button, position: pageStart + index }, symbols));
  }

  if (pageIndex === 1) {
    return SECOND_PAGE_DEFAULT_TRACKER_BUTTONS.map((button, index) =>
      deriveTrackerButton({ ...button, position: pageStart + index }, symbols),
    );
  }

  return Array.from({ length: TRACKER_BUTTONS_PER_PAGE }, (_, slotIndex) =>
    deriveTrackerButton(
      {
        id: `${PLACEHOLDER_PAGE_PREFIX}_${pageIndex + 1}_${slotIndex + 1}`,
        label: `Other ${slotIndex + 1}`,
        icon_key: 'help-circle',
        color_key: 'slate',
        position: pageStart + slotIndex,
      },
      symbols,
    ),
  );
}

export function getTrackerButtonPageCount(buttons: { position: number }[]): number {
  return Math.max(1, Math.ceil(buttons.length / TRACKER_BUTTONS_PER_PAGE));
}

export function getTrackerButtonsForPage<T extends { position: number }>(buttons: T[], pageIndex: number): T[] {
  const orderedButtons = sortTrackerButtons(buttons);
  const start = pageIndex * TRACKER_BUTTONS_PER_PAGE;
  return orderedButtons.slice(start, start + TRACKER_BUTTONS_PER_PAGE);
}
