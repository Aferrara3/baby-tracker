import { createElement } from 'react';

import iconNodesCatalog from 'lucide-static/icon-nodes.json';

import { API_BASE } from '../config';
import { getTrackerSymbol, type TrackerSymbolOption } from '../trackerButtons';

type LucideNode = [string, Record<string, string>];
const ICON_NODES_BY_KEY = iconNodesCatalog as unknown as Record<string, LucideNode[]>;
const FALLBACK_SYMBOL: TrackerSymbolOption = {
  key: 'help-circle',
  label: 'Other',
  emoji: '❓',
  keywords: ['other'],
  icon_kind: 'lucide',
};
const CUSTOM_ICON_SCALE_MULTIPLIER = 1.2;
const LEGACY_ICON_KEY_ALIASES: Record<string, string> = {
  'help-circle': 'circle-question-mark',
  'user-2': 'user-round',
};

function resolveCustomIconUrl(imageUrl: string): string {
  if (/^(?:https?:)?\/\//.test(imageUrl) || imageUrl.startsWith('data:') || imageUrl.startsWith('blob:')) {
    return imageUrl;
  }
  if (!imageUrl.startsWith('/')) {
    return imageUrl;
  }
  const base = API_BASE.endsWith('/') ? API_BASE.slice(0, -1) : API_BASE;
  return `${base}${imageUrl}`;
}

export default function TrackerSymbolIcon({
  symbol,
  iconKey,
  size = 24,
  className,
  strokeWidth = 2.25,
}: {
  symbol?: TrackerSymbolOption;
  iconKey?: string;
  size?: number;
  className?: string;
  strokeWidth?: number;
}) {
  const resolvedSymbol = symbol ?? (iconKey ? getTrackerSymbol([FALLBACK_SYMBOL], iconKey) : FALLBACK_SYMBOL);
  const resolvedIconKey = resolvedSymbol?.key ?? iconKey ?? FALLBACK_SYMBOL.key;
  const renderIconKey = ICON_NODES_BY_KEY[resolvedIconKey]
    ? resolvedIconKey
    : LEGACY_ICON_KEY_ALIASES[resolvedIconKey] ?? resolvedIconKey;

  if (resolvedSymbol?.icon_kind === 'custom' && resolvedSymbol.image_url) {
    const customRenderSize = size * CUSTOM_ICON_SCALE_MULTIPLIER;
    return (
      <img
        src={resolveCustomIconUrl(resolvedSymbol.image_url)}
        alt={resolvedSymbol.label}
        width={customRenderSize}
        height={customRenderSize}
        className={className}
        style={{
          width: customRenderSize,
          height: customRenderSize,
          maxWidth: '100%',
          maxHeight: '100%',
          objectFit: 'contain',
        }}
      />
    );
  }

  const iconNodes =
    ICON_NODES_BY_KEY[renderIconKey] ??
    ICON_NODES_BY_KEY[LEGACY_ICON_KEY_ALIASES[FALLBACK_SYMBOL.key] ?? FALLBACK_SYMBOL.key] ??
    [];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {iconNodes.map(([tagName, attrs], index) => createElement(tagName, { key: `${resolvedIconKey}-${index}`, ...attrs }))}
    </svg>
  );
}
