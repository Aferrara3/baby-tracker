export type ThemePaletteKey = 'default' | 'blossom' | 'meadow' | 'twilight';

export interface ThemePaletteOption {
  key: ThemePaletteKey;
  label: string;
  description: string;
  swatches: [string, string, string];
}

export const THEME_PALETTE_OPTIONS: ThemePaletteOption[] = [
  { key: 'default', label: 'Classic', description: 'Dark navy with the original blue-forward feel', swatches: ['#0b1220', '#60a5fa', '#818cf8'] },
  { key: 'blossom', label: 'Blossom', description: 'Dark plum with rosy, violet, and sunset buttons', swatches: ['#170f16', '#db2777', '#7c3aed'] },
  { key: 'meadow', label: 'Meadow', description: 'Dark evergreen with mint, lime, and teal buttons', swatches: ['#0d1713', '#059669', '#65a30d'] },
  { key: 'twilight', label: 'Twilight', description: 'Dark indigo with violet, cyan, and magenta buttons', swatches: ['#111322', '#7c3aed', '#0891b2'] },
];
