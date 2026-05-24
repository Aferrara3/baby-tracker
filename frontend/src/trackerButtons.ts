import {
  AlarmClock,
  Apple,
  Baby,
  Banknote,
  Bath,
  Bed,
  Beef,
  Beer,
  BicepsFlexed,
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
  Cookie,
  CupSoda,
  Dog,
  Droplet,
  Drumstick,
  Dumbbell,
  Fish,
  Footprints,
  ForkKnife,
  Frown,
  Gamepad2,
  Gift,
  HandHeart,
  Heart,
  HeartPulse,
  HelpCircle,
  House,
  IceCreamBowl,
  Laptop,
  Leaf,
  Martini,
  Milk,
  Moon,
  MoonStar,
  Music4,
  NotebookPen,
  PawPrint,
  Phone,
  Pill,
  PillBottle,
  Pizza,
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
  Soup,
  Sparkles,
  Stethoscope,
  Sun,
  Syringe,
  TentTree,
  Thermometer,
  Timer,
  Toilet,
  TrainFront,
  User2,
  Utensils,
  UtensilsCrossed,
  Wallet,
  WavesLadder,
  Wine,
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
const FALLBACK_SYMBOLS: TrackerSymbolOption[] = [
  { key: 'help-circle', label: 'Other', emoji: '❓', keywords: ['other'] },
];

const ICONS_BY_KEY: Record<string, LucideIcon> = {
  'alarm-clock': AlarmClock,
  apple: Apple,
  baby: Baby,
  banknote: Banknote,
  bath: Bath,
  bed: Bed,
  beef: Beef,
  beer: Beer,
  'biceps-flexed': BicepsFlexed,
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
  cookie: Cookie,
  'cup-soda': CupSoda,
  dog: Dog,
  droplet: Droplet,
  drumstick: Drumstick,
  dumbbell: Dumbbell,
  fish: Fish,
  footprints: Footprints,
  'fork-knife': ForkKnife,
  frown: Frown,
  'gamepad-2': Gamepad2,
  gift: Gift,
  'hand-heart': HandHeart,
  heart: Heart,
  'heart-pulse': HeartPulse,
  'help-circle': HelpCircle,
  house: House,
  'ice-cream-bowl': IceCreamBowl,
  laptop: Laptop,
  leaf: Leaf,
  martini: Martini,
  milk: Milk,
  moon: Moon,
  'moon-star': MoonStar,
  'music-4': Music4,
  'notebook-pen': NotebookPen,
  'paw-print': PawPrint,
  phone: Phone,
  pill: Pill,
  'pill-bottle': PillBottle,
  pizza: Pizza,
  plane: Plane,
  popcorn: Popcorn,
  rabbit: Rabbit,
  salad: Salad,
  sandwich: Sandwich,
  'scan-heart': ScanHeart,
  'shopping-bag': ShoppingBag,
  'shopping-cart': ShoppingCart,
  'shower-head': ShowerHead,
  smile: Smile,
  soup: Soup,
  sparkles: Sparkles,
  stethoscope: Stethoscope,
  sun: Sun,
  syringe: Syringe,
  'tent-tree': TentTree,
  thermometer: Thermometer,
  timer: Timer,
  toilet: Toilet,
  'train-front': TrainFront,
  'user-2': User2,
  utensils: Utensils,
  'utensils-crossed': UtensilsCrossed,
  wallet: Wallet,
  'waves-ladder': WavesLadder,
  wine: Wine,
};

const COLOR_CLASS_BY_KEY: Record<string, string> = {
  blue: 'tracker-color-blue',
  amber: 'tracker-color-amber',
  cyan: 'tracker-color-cyan',
  pink: 'tracker-color-pink',
  indigo: 'tracker-color-indigo',
  rose: 'tracker-color-rose',
  orange: 'tracker-color-orange',
  slate: 'tracker-color-slate',
};

export function getTrackerButtonIcon(iconKey: string): LucideIcon {
  return ICONS_BY_KEY[iconKey] ?? HelpCircle;
}

export function getTrackerButtonColorClass(colorKey: string): string {
  return COLOR_CLASS_BY_KEY[colorKey] ?? COLOR_CLASS_BY_KEY.slate;
}

export function getTrackerSymbol(symbols: TrackerSymbolOption[], iconKey: string): TrackerSymbolOption | undefined {
  return symbols.find((symbol) => symbol.key === iconKey) ?? FALLBACK_SYMBOLS.find((symbol) => symbol.key === iconKey);
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

function createUniqueTrackerButtonId(baseId: string, existingIds: Set<string>): string {
  let candidateId = baseId;
  let suffix = 2;

  while (existingIds.has(candidateId)) {
    candidateId = `${baseId}_${suffix}`;
    suffix += 1;
  }

  existingIds.add(candidateId);
  return candidateId;
}

export function getTrackerButtonPageCount(buttons: { position: number }[]): number {
  return Math.max(1, Math.ceil(buttons.length / TRACKER_BUTTONS_PER_PAGE));
}

export function getTrackerButtonsForPage<T extends { position: number }>(buttons: T[], pageIndex: number): T[] {
  const orderedButtons = sortTrackerButtons(buttons);
  const start = pageIndex * TRACKER_BUTTONS_PER_PAGE;
  return orderedButtons.slice(start, start + TRACKER_BUTTONS_PER_PAGE);
}

export function createTrackerButtonsForPage(
  pageIndex: number,
  symbols: TrackerSymbolOption[],
  existingButtons: Pick<TrackerButtonConfig, 'id'>[] = [],
  buttonTemplates: Array<Pick<TrackerButtonConfig, 'id' | 'label' | 'icon_key' | 'color_key' | 'position'>> = [],
  placeholderButtonLabelPrefix = 'Other',
): TrackerButtonConfig[] {
  const pageStart = pageIndex * TRACKER_BUTTONS_PER_PAGE;
  const existingIds = new Set(existingButtons.map((button) => button.id));
  const templateButtons = getTrackerButtonsForPage(buttonTemplates, pageIndex);
  const baseButtons =
    templateButtons.length === TRACKER_BUTTONS_PER_PAGE
      ? templateButtons
      : Array.from({ length: TRACKER_BUTTONS_PER_PAGE }, (_, slotIndex) => ({
          id: `${PLACEHOLDER_PAGE_PREFIX}_${pageIndex + 1}_${slotIndex + 1}`,
          label: `${placeholderButtonLabelPrefix} ${slotIndex + 1}`,
          icon_key: 'help-circle',
          color_key: 'slate',
          position: pageStart + slotIndex,
        }));

  return baseButtons.map((button, index) =>
    deriveTrackerButton(
      {
        ...button,
        id: createUniqueTrackerButtonId(button.id, existingIds),
        position: pageStart + index,
      },
      symbols,
    ),
  );
}
