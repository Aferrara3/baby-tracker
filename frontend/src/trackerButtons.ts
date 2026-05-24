export interface TrackerButtonConfig {
  id: string;
  label: string;
  icon_key: string;
  color_key: string;
  position: number;
  emoji: string;
  title: string;
  emoji_override?: string | null;
  icon_kind?: 'lucide' | 'custom';
  image_url?: string | null;
}

export interface TrackerButtonUpdate {
  id: string;
  label: string;
  icon_key: string;
  color_key: string;
  position: number;
  emoji_override?: string | null;
}

export interface TrackerSymbolOption {
  key: string;
  label: string;
  emoji: string;
  keywords: string[];
  category?: string | null;
  icon_kind?: 'lucide' | 'custom';
  image_url?: string | null;
  is_public?: boolean | null;
  can_delete?: boolean | null;
}

export interface TrackerButtonsResponse {
  buttons: TrackerButtonConfig[];
  available_symbols: TrackerSymbolOption[];
}

export const TRACKER_BUTTONS_PER_PAGE = 8;
export const MAX_TRACKER_BUTTON_PAGES = 3;
const PLACEHOLDER_PAGE_PREFIX = 'extra_page';
export const TRACKER_BUTTON_COLOR_KEYS = ['blue', 'amber', 'cyan', 'pink', 'indigo', 'rose', 'orange', 'slate'] as const;
export const TRACKER_BUTTON_COLOR_OPTIONS = [
  { key: 'blue', label: 'Blue' },
  { key: 'amber', label: 'Amber' },
  { key: 'cyan', label: 'Cyan' },
  { key: 'pink', label: 'Pink' },
  { key: 'indigo', label: 'Indigo' },
  { key: 'rose', label: 'Rose' },
  { key: 'orange', label: 'Orange' },
  { key: 'slate', label: 'Slate' },
] as const;
const FALLBACK_SYMBOLS: TrackerSymbolOption[] = [
  { key: 'help-circle', label: 'Other', emoji: '❓', keywords: ['other'], icon_kind: 'lucide' },
];

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

export function getTrackerButtonColorClass(colorKey: string): string {
  return COLOR_CLASS_BY_KEY[colorKey] ?? COLOR_CLASS_BY_KEY.slate;
}

export function getTrackerSymbol(symbols: TrackerSymbolOption[], iconKey: string): TrackerSymbolOption | undefined {
  return symbols.find((symbol) => symbol.key === iconKey) ?? FALLBACK_SYMBOLS.find((symbol) => symbol.key === iconKey);
}

export function isValidEmojiValue(value: string): boolean {
  const normalized = value.trim();
  if (!normalized || normalized.length > 16) {
    return false;
  }
  if (/\s/u.test(normalized)) {
    return false;
  }
  return /[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}]/u.test(normalized);
}

export function resolveTrackerButtonEmoji(button: TrackerButtonUpdate | TrackerButtonConfig, symbols: TrackerSymbolOption[]): string {
  const emojiOverride = button.emoji_override?.trim();
  if (emojiOverride) {
    return emojiOverride;
  }
  return getTrackerSymbol(symbols, button.icon_key)?.emoji ?? '🏷️';
}

export function deriveTrackerButton(button: TrackerButtonUpdate | TrackerButtonConfig, symbols: TrackerSymbolOption[]): TrackerButtonConfig {
  const rawLabel = button.label;
  const label = rawLabel.trim() || 'Untitled';
  const symbol = getTrackerSymbol(symbols, button.icon_key);
  const emoji = resolveTrackerButtonEmoji(button, symbols);

  return {
    id: button.id,
    label: rawLabel,
    icon_key: button.icon_key,
    color_key: button.color_key,
    position: button.position,
    emoji,
    title: `${emoji} ${label}`,
    emoji_override: button.emoji_override?.trim() || null,
    icon_kind: symbol?.icon_kind ?? 'lucide',
    image_url: symbol?.image_url ?? null,
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
  return candidateId;
}

function pagePlaceholderButtonId(pageIndex: number, slotIndex: number) {
  return `${PLACEHOLDER_PAGE_PREFIX}_${pageIndex + 1}_${slotIndex + 1}`;
}

export function createTrackerButtonsForPage(
  buttons: TrackerButtonConfig[],
  pageIndex: number,
  placeholderLabelPrefix: string,
): TrackerButtonConfig[] {
  const normalizedButtons = normalizeTrackerButtons(buttons, FALLBACK_SYMBOLS);
  const start = pageIndex * TRACKER_BUTTONS_PER_PAGE;
  const existingPageButtons = normalizedButtons.slice(start, start + TRACKER_BUTTONS_PER_PAGE);
  const existingIds = new Set(normalizedButtons.map((button) => button.id));

  const placeholders = Array.from({ length: TRACKER_BUTTONS_PER_PAGE - existingPageButtons.length }, (_, offset) => {
    const slotIndex = existingPageButtons.length + offset;
    const placeholderId = createUniqueTrackerButtonId(pagePlaceholderButtonId(pageIndex, slotIndex), existingIds);
    existingIds.add(placeholderId);
    return deriveTrackerButton(
      {
        id: placeholderId,
        label: `${placeholderLabelPrefix} ${pageIndex + 1}-${slotIndex + 1}`,
        icon_key: 'help-circle',
        color_key: TRACKER_BUTTON_COLOR_KEYS[(start + slotIndex) % TRACKER_BUTTON_COLOR_KEYS.length],
        position: start + slotIndex,
      },
      FALLBACK_SYMBOLS,
    );
  });

  return normalizeTrackerButtons([...normalizedButtons.slice(0, start), ...existingPageButtons, ...placeholders], FALLBACK_SYMBOLS);
}

export function getTrackerButtonPageCount(buttons: TrackerButtonConfig[]): number {
  return Math.max(1, Math.ceil(buttons.length / TRACKER_BUTTONS_PER_PAGE));
}

export function getTrackerButtonsForPage(buttons: TrackerButtonConfig[], pageIndex: number): TrackerButtonConfig[] {
  const start = pageIndex * TRACKER_BUTTONS_PER_PAGE;
  return sortTrackerButtons(buttons).slice(start, start + TRACKER_BUTTONS_PER_PAGE);
}
