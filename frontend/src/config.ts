const parsePositiveInt = (value: string | undefined, fallback: number) => {
  const parsed = Number.parseInt(value ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? 'http://localhost:8090' : '');

export const GOOGLE_SYNC_POLL_INTERVAL_MS = parsePositiveInt(
  import.meta.env.VITE_GOOGLE_SYNC_POLL_INTERVAL_MS,
  60 * 60 * 1000,
);
