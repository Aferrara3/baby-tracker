import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  ImagePlus,
  HelpCircle,
  InfoIcon,
  LogOut,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Trash2,
  Undo2,
  X,
} from 'lucide-react';
import axios from 'axios';
import { clsx } from 'clsx';

import ActivityButton from './components/ActivityButton';
import TrackerSymbolIcon from './components/TrackerSymbolIcon';
import { FALLBACK_APP_CONFIG, type AppConfig } from './appConfig';
import Toast from './components/Toast';
import { ACTIVE_TIMER_STATUS_POLL_INTERVAL_MS, API_BASE, GOOGLE_SYNC_POLL_INTERVAL_MS } from './config';
import { THEME_PALETTE_OPTIONS, type ThemePaletteKey } from './theme';
import {
  createTrackerButtonsForPage,
  deriveTrackerButton,
  getTrackerButtonPageCount,
  getTrackerButtonsForPage,
  getTrackerButtonColorClass,
  getTrackerSymbol,
  isValidEmojiValue,
  normalizeTrackerButtons,
  sortTrackerButtons,
  TRACKER_BUTTON_COLOR_OPTIONS,
  TRACKER_BUTTONS_PER_PAGE,
  type TrackerButtonConfig,
  type TrackerButtonsResponse,
  type TrackerButtonUpdate,
  type TrackerSymbolOption,
} from './trackerButtons';

const TOKEN_STORAGE_KEY = 'baby-tracker-auth-token';
const INTERACTION_TIP_STORAGE_KEY = 'baby-tracker-interaction-tip-hidden';
const TRACKER_PAGE_STORAGE_KEY = 'baby-tracker-selected-page';
const NOTE_SHEET_AUTO_DISMISS_MS = 5000;
const TRACKER_BUTTON_AUTOSAVE_DELAY_MS = 600;
const PALETTE_AUTOSAVE_DELAY_MS = 500;
const BROWSER_TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const CUSTOM_ICON_MIN_ZOOM = 0.75;
const CUSTOM_ICON_MAX_ZOOM = 2.5;
const CUSTOM_ICON_ZOOM_STEP = 0.15;

interface Activity {
  id: string;
  symbol?: TrackerSymbolOption;
  label: string;
  colorClass: string;
}

interface CustomIconDraft {
  label: string;
  emoji: string;
  keywords: string;
  isPublic: boolean;
  sourceFile: File | null;
  preparedFile: File | null;
  previewUrl: string | null;
  zoom: number;
}

interface ToastItem {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info';
}

interface Account {
  id: number;
  username: string;
  baby_name: string | null;
  color_palette: ThemePaletteKey;
  share_emails: string[];
  google_calendar_id: string | null;
  google_calendar_summary: string | null;
  calendar_connected: boolean;
  service_managed_calendar: boolean;
  calendar_url: string | null;
  google_last_synced_at: string | null;
  google_last_sync_status: string | null;
}

interface AuthResponse {
  token: string;
  account: Account;
}

interface EventSummary {
  id: number;
  type: string;
  title: string | null;
  start_time: string;
  end_time: string | null;
  duration: number | null;
  details: string | null;
  is_active: boolean;
  calendar_sync_state: 'local_only' | 'pending' | 'queued' | 'synced' | 'failed';
  calendar_sync_message: string | null;
}

interface PendingLogItem {
  eventId: number;
  activityId: string;
}

function getApiErrorDetail(error: unknown): string | null {
  return axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string'
    ? error.response.data.detail
    : null;
}

function buildTrackerButtonsPayload(buttons: TrackerButtonConfig[]) {
  return {
    buttons: sortTrackerButtons(buttons).map((button, position) => ({
      id: button.id,
      label: button.label.trim(),
      icon_key: button.icon_key,
      color_key: button.color_key,
      position,
      emoji_override: button.emoji_override?.trim() || null,
    })),
  };
}

function serializeTrackerButtonsPayload(buttons: TrackerButtonConfig[]) {
  return JSON.stringify(buildTrackerButtonsPayload(buttons).buttons);
}

function getStoredTrackerPageIndex() {
  const storedValue = Number(localStorage.getItem(TRACKER_PAGE_STORAGE_KEY) ?? '0');
  return Number.isFinite(storedValue) && storedValue >= 0 ? storedValue : 0;
}

function parseEmails(input: string): string[] {
  return Array.from(
    new Set(
      input
        .split(',')
        .map((value) => value.trim().toLowerCase())
        .filter(Boolean),
    ),
  );
}

function runningActivitiesEqual(left: Record<string, number>, right: Record<string, number>) {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) {
    return false;
  }
  return leftKeys.every((key) => left[key] === right[key]);
}

function symbolSourceLabel(symbol: TrackerSymbolOption): string {
  if (symbol.icon_kind === 'custom') {
    if (symbol.can_delete) {
      return symbol.is_public ? 'Your public icon' : 'Your icon';
    }
    return 'Community';
  }
  return 'Lucide';
}

async function prepareCustomIconFile(file: File, zoom: number): Promise<{ preparedFile: File; previewUrl: string }> {
  const isSupportedType = file.type === 'image/png' || file.type === 'image/svg+xml' || /\.png$|\.svg$/i.test(file.name);
  if (!isSupportedType) {
    throw new Error('Custom icons must be PNG or SVG');
  }

  const imageUrl = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const nextImage = new Image();
      nextImage.onload = () => resolve(nextImage);
      nextImage.onerror = () => reject(new Error('Could not read that image file'));
      nextImage.src = imageUrl;
    });

    const canvas = document.createElement('canvas');
    const size = 256;
    const padding = 16;
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext('2d');
    if (!context) {
      throw new Error('Could not prepare that image');
    }

    const sourceCanvas = document.createElement('canvas');
    sourceCanvas.width = image.naturalWidth;
    sourceCanvas.height = image.naturalHeight;
    const sourceContext = sourceCanvas.getContext('2d', { willReadFrequently: true });
    if (!sourceContext) {
      throw new Error('Could not prepare that image');
    }
    sourceContext.clearRect(0, 0, sourceCanvas.width, sourceCanvas.height);
    sourceContext.drawImage(image, 0, 0);

    const sourceImageData = sourceContext.getImageData(0, 0, sourceCanvas.width, sourceCanvas.height);
    const { data } = sourceImageData;
    let minX = sourceCanvas.width;
    let minY = sourceCanvas.height;
    let maxX = -1;
    let maxY = -1;
    const alphaThreshold = 8;

    for (let y = 0; y < sourceCanvas.height; y += 1) {
      for (let x = 0; x < sourceCanvas.width; x += 1) {
        const alpha = data[(y * sourceCanvas.width + x) * 4 + 3];
        if (alpha <= alphaThreshold) {
          continue;
        }
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
    }

    const cropX = maxX >= minX ? minX : 0;
    const cropY = maxY >= minY ? minY : 0;
    const cropWidth = maxX >= minX ? maxX - minX + 1 : sourceCanvas.width;
    const cropHeight = maxY >= minY ? maxY - minY + 1 : sourceCanvas.height;

    context.clearRect(0, 0, size, size);
    const maxSize = size - padding * 2;
    const scale = Math.min(maxSize / cropWidth, maxSize / cropHeight) * zoom;
    const drawWidth = cropWidth * scale;
    const drawHeight = cropHeight * scale;
    const drawX = (size - drawWidth) / 2;
    const drawY = (size - drawHeight) / 2;
    context.drawImage(sourceCanvas, cropX, cropY, cropWidth, cropHeight, drawX, drawY, drawWidth, drawHeight);

    const normalizedImage = context.getImageData(0, 0, canvas.width, canvas.height);
    for (let index = 0; index < normalizedImage.data.length; index += 4) {
      const alpha = normalizedImage.data[index + 3];
      if (alpha <= alphaThreshold) {
        continue;
      }
      normalizedImage.data[index] = 255;
      normalizedImage.data[index + 1] = 255;
      normalizedImage.data[index + 2] = 255;
    }
    context.putImageData(normalizedImage, 0, 0);

    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((nextBlob) => {
        if (nextBlob) {
          resolve(nextBlob);
          return;
        }
        reject(new Error('Could not export the prepared icon'));
      }, 'image/png');
    });

    const preparedFile = new File([blob], `${file.name.replace(/\.[^.]+$/, '') || 'custom-icon'}.png`, {
      type: 'image/png',
    });
    return {
      preparedFile,
      previewUrl: URL.createObjectURL(blob),
    };
  } finally {
    URL.revokeObjectURL(imageUrl);
  }
}

interface SortableDraftButtonCardProps {
  button: TrackerButtonConfig;
  symbol?: TrackerSymbolOption;
  isSelected: boolean;
  onSelect: () => void;
}

function SortableDraftButtonCard({ button, symbol, isSelected, onSelect }: SortableDraftButtonCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: button.id });

  return (
    <button
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      type="button"
      onClick={onSelect}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        touchAction: 'none',
      }}
      className={clsx(
        'flex flex-col items-center gap-2 rounded-2xl border p-2 text-center transition cursor-grab active:cursor-grabbing',
        isSelected ? 'app-page-button-active' : 'app-surface hover:opacity-90',
        isDragging && 'shadow-xl opacity-90',
      )}
    >
      <div className={clsx('flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-2xl shadow-md md:h-24 md:w-24', getTrackerButtonColorClass(button.color_key))}>
        <TrackerSymbolIcon symbol={symbol} iconKey={button.icon_key} size={30} className="text-white" strokeWidth={2.4} />
      </div>
      <p className="app-text max-w-full truncate text-[11px] font-bold uppercase tracking-wide md:text-sm">
        {button.label.trim() || 'Untitled'}
      </p>
    </button>
  );
}

function PrivacyNoticeWidget() {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="app-icon-button fixed bottom-[calc(env(safe-area-inset-bottom)+1rem)] left-4 z-40 rounded-full border px-3 py-3 shadow-lg backdrop-blur-md transition hover:scale-105"
        aria-label="Open privacy notice"
        aria-expanded={isOpen}
      >
        <InfoIcon size={18} />
      </button>

      <div
        className={clsx(
          'app-overlay fixed inset-0 z-40 flex items-end px-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] pt-6 transition-all duration-200',
          isOpen ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={() => setIsOpen(false)}
      >
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="privacy-notice-title"
          className={clsx(
            'app-surface relative w-full max-w-sm rounded-3xl border p-4 pr-12 shadow-2xl transition-transform duration-200',
            isOpen ? 'translate-y-0' : 'translate-y-8',
          )}
          onClick={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => setIsOpen(false)}
            className="app-icon-button absolute right-3 top-3 rounded-full p-2 transition"
            aria-label="Close privacy notice"
          >
            <X size={16} />
          </button>

          <div className="space-y-3">
            <div className="app-accent-soft inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold">
              <InfoIcon size={14} />
              Privacy notice
            </div>
            <div className="space-y-2">
              <h2 id="privacy-notice-title" className="text-base font-semibold">
                Casual-use app only
              </h2>
              <p className="app-muted text-sm leading-6">
                This app is not enterprise-grade and comes with no guarantee of privacy, security, uptime, or data retention.
              </p>
              <p className="app-muted text-sm leading-6">
                It is a vibe-coded project for casual or entertainment use, so please do not trust it with sensitive, regulated, or high-stakes information.
              </p>
              <p className="app-muted text-sm leading-6">
                By using it, you accept the risk of data leakage, theft, loss, or other failures.
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

export default function App() {
  const [appConfig, setAppConfig] = useState<AppConfig>(FALLBACK_APP_CONFIG);
  const [appConfigLoaded, setAppConfigLoaded] = useState(false);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [account, setAccount] = useState<Account | null>(null);
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? '');
  const [authLoading, setAuthLoading] = useState(true);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [registerBabyName, setRegisterBabyName] = useState('');
  const [runningActivities, setRunningActivities] = useState<Record<string, number>>({});
  const [currentTime, setCurrentTime] = useState(() => Date.now());
  const [inputValue, setInputValue] = useState('');
  const [pendingLogs, setPendingLogs] = useState<PendingLogItem[]>([]);
  const [activeView, setActiveView] = useState<'tracker' | 'settings'>('tracker');
  const [trackerPageIndex, setTrackerPageIndex] = useState(() => getStoredTrackerPageIndex());
  const [settingsTab, setSettingsTab] = useState<'calendar' | 'buttons' | 'app'>('calendar');
  const [settingsBabyName, setSettingsBabyName] = useState('');
  const [settingsPalette, setSettingsPalette] = useState<ThemePaletteKey>('default');
  const [settingsShareEmails, setSettingsShareEmails] = useState('');
  const [trackerButtons, setTrackerButtons] = useState<TrackerButtonConfig[]>([]);
  const [settingsButtonsDraft, setSettingsButtonsDraft] = useState<TrackerButtonConfig[]>([]);
  const [availableSymbols, setAvailableSymbols] = useState<TrackerSymbolOption[]>(FALLBACK_APP_CONFIG.available_symbols);
  const [selectedButtonId, setSelectedButtonId] = useState('');
  const [symbolSearch, setSymbolSearch] = useState('');
  const [customIconDraft, setCustomIconDraft] = useState<CustomIconDraft>({
    label: '',
    emoji: '',
    keywords: '',
    isPublic: false,
    sourceFile: null,
    preparedFile: null,
    previewUrl: null,
    zoom: 1,
  });
  const [isCreatingCustomIcon, setIsCreatingCustomIcon] = useState(false);
  const [isDeletingCustomIcon, setIsDeletingCustomIcon] = useState(false);
  const [customIconError, setCustomIconError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [isSavingButtons, setIsSavingButtons] = useState(false);
  const [buttonsSaveError, setButtonsSaveError] = useState<string | null>(null);
  const [isSavingPalette, setIsSavingPalette] = useState(false);
  const [paletteSaveError, setPaletteSaveError] = useState<string | null>(null);
  const [showInteractionTip, setShowInteractionTip] = useState(() => localStorage.getItem(INTERACTION_TIP_STORAGE_KEY) !== 'true');
  const autoSyncInFlightRef = useRef(false);
  const runningActivitiesRef = useRef<Record<string, number>>({});
  const localStopInFlightRef = useRef<Set<string>>(new Set());
  const pendingLogActionRef = useRef<number | null>(null);
  const buttonsAutosaveTimeoutRef = useRef<number | null>(null);
  const paletteAutosaveTimeoutRef = useRef<number | null>(null);
  const latestButtonsPayloadRef = useRef(serializeTrackerButtonsPayload([]));
  const savedButtonsPayloadRef = useRef(serializeTrackerButtonsPayload([]));
  const buttonsSaveRequestIdRef = useRef(0);
  const paletteSaveRequestIdRef = useRef(0);
  const toastIdRef = useRef(0);
  const dragSensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 6 },
    }),
  );

  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : undefined),
    [token],
  );
  const seededDefaultButtons = useMemo(
    () => normalizeTrackerButtons(getTrackerButtonsForPage(appConfig.button_templates, 0), appConfig.available_symbols),
    [appConfig.available_symbols, appConfig.button_templates],
  );
  const activities = useMemo<Activity[]>(
    () =>
      sortTrackerButtons(trackerButtons).map((button) => ({
        id: button.id,
        symbol: getTrackerSymbol(availableSymbols, button.icon_key),
        label: button.label,
        colorClass: getTrackerButtonColorClass(button.color_key),
      })),
    [availableSymbols, trackerButtons],
  );
  const trackerPageCount = useMemo(() => getTrackerButtonPageCount(trackerButtons), [trackerButtons]);
  const visibleActivities = useMemo(
    () => activities.slice(trackerPageIndex * TRACKER_BUTTONS_PER_PAGE, (trackerPageIndex + 1) * TRACKER_BUTTONS_PER_PAGE),
    [activities, trackerPageIndex],
  );
  const orderedDraftButtons = useMemo(
    () => sortTrackerButtons(settingsButtonsDraft),
    [settingsButtonsDraft],
  );
  const settingsButtonPageCount = useMemo(
    () => getTrackerButtonPageCount(settingsButtonsDraft),
    [settingsButtonsDraft],
  );
  const currentDraftButtonsPage = useMemo(
    () => getTrackerButtonsForPage(orderedDraftButtons, trackerPageIndex),
    [orderedDraftButtons, trackerPageIndex],
  );
  const displayedTrackerPageCount = Math.max(trackerPageCount, settingsButtonPageCount);
  const selectedDraftButton =
    currentDraftButtonsPage.find((button) => button.id === selectedButtonId) ?? currentDraftButtonsPage[0] ?? null;
  const selectedSymbol = useMemo(
    () => (selectedDraftButton ? getTrackerSymbol(availableSymbols, selectedDraftButton.icon_key) ?? null : null),
    [availableSymbols, selectedDraftButton],
  );
  const filteredSymbols = useMemo(() => {
    const query = symbolSearch.trim().toLowerCase();
    if (!query) {
      return availableSymbols.slice(0, 80);
    }
    const queryTokens = query.split(/\s+/).filter(Boolean);

    return [...availableSymbols]
      .map((symbol) => {
        const haystack = [symbol.label, symbol.key, symbol.category ?? '', symbol.emoji, ...symbol.keywords]
          .join(' ')
          .toLowerCase();
        let score = 0;
        if (symbol.label.toLowerCase() === query) score += 120;
        if (symbol.key.toLowerCase() === query) score += 100;
        if (symbol.label.toLowerCase().startsWith(query)) score += 48;
        if (symbol.key.toLowerCase().startsWith(query)) score += 36;
        if ((symbol.category ?? '').toLowerCase() === query) score += 28;
        for (const token of queryTokens) {
          if (symbol.label.toLowerCase().includes(token)) score += 16;
          if (symbol.key.toLowerCase().includes(token)) score += 12;
          if ((symbol.category ?? '').toLowerCase().includes(token)) score += 10;
          if (symbol.keywords.some((keyword) => keyword.toLowerCase().includes(token))) score += 8;
        }
        if (symbol.icon_kind === 'custom') score += 2;
        if (score === 0 && !haystack.includes(query)) {
          return null;
        }
        return { symbol, score };
      })
      .filter((entry): entry is { symbol: TrackerSymbolOption; score: number } => entry !== null)
      .sort((left, right) => {
        if (right.score !== left.score) {
          return right.score - left.score;
        }
        return left.symbol.label.localeCompare(right.symbol.label);
      })
      .slice(0, 80)
      .map((entry) => entry.symbol);
  }, [availableSymbols, symbolSearch]);
  const filteredSymbolGroups = useMemo(() => {
    const groups = new Map<string, { title: string; symbols: TrackerSymbolOption[] }>();
    for (const symbol of filteredSymbols) {
      const title =
        symbol.icon_kind === 'custom'
          ? symbolSourceLabel(symbol)
          : `Lucide${symbol.category ? ` > ${symbol.category}` : ''}`;
      const existing = groups.get(title);
      if (existing) {
        existing.symbols.push(symbol);
      } else {
        groups.set(title, { title, symbols: [symbol] });
      }
    }
    return [...groups.values()];
  }, [filteredSymbols]);
  const activePendingLog = pendingLogs[0] ?? null;
  const pendingActivityLabel = activities.find((activity) => activity.id === activePendingLog?.activityId)?.label ?? 'event';
  const serializedSettingsButtonsDraft = useMemo(
    () => serializeTrackerButtonsPayload(settingsButtonsDraft),
    [settingsButtonsDraft],
  );
  const buttonsHaveUnsavedChanges = serializedSettingsButtonsDraft !== savedButtonsPayloadRef.current;
  const invalidButtonEmojiOverride = useMemo(
    () => settingsButtonsDraft.find((button) => button.emoji_override && !isValidEmojiValue(button.emoji_override)),
    [settingsButtonsDraft],
  );
  const headerContextText = useMemo(() => {
    if (!account) {
      return '';
    }
    return account.baby_name
      ? appConfig.copy.header_context_with_name.replace('{tracked_name}', account.baby_name)
      : appConfig.copy.header_context_without_name.replace('{username}', account.username);
  }, [account, appConfig.copy.header_context_with_name, appConfig.copy.header_context_without_name]);

  const addToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    toastIdRef.current += 1;
    const id = `toast-${toastIdRef.current}`;
    setToasts((prev) => [...prev, { id, message, type }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, 3000);
  }, []);

  useEffect(() => () => {
    if (customIconDraft.previewUrl) {
      URL.revokeObjectURL(customIconDraft.previewUrl);
    }
  }, [customIconDraft.previewUrl]);

  const persistAuth = (nextToken: string, nextAccount: Account) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    setToken(nextToken);
    setAccount(nextAccount);
    setSettingsBabyName(nextAccount.baby_name ?? '');
    setSettingsPalette(nextAccount.color_palette ?? 'default');
    setSettingsShareEmails(nextAccount.share_emails.join(', '));
    setSettingsTab('calendar');
  };

  const clearAuth = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken('');
    setAccount(null);
    setActiveView('tracker');
    setSettingsTab('calendar');
    setRunningActivities({});
    setPendingLogs([]);
    setInputValue('');
    setTrackerButtons(seededDefaultButtons);
    setSettingsButtonsDraft(seededDefaultButtons);
    setAvailableSymbols(appConfig.available_symbols);
    setSettingsPalette('default');
    setSelectedButtonId(seededDefaultButtons[0]?.id ?? '');
    setSymbolSearch('');
    setIsSavingButtons(false);
    setButtonsSaveError(null);
    if (buttonsAutosaveTimeoutRef.current !== null) {
      window.clearTimeout(buttonsAutosaveTimeoutRef.current);
      buttonsAutosaveTimeoutRef.current = null;
    }
    const defaultButtonsPayload = serializeTrackerButtonsPayload(seededDefaultButtons);
    latestButtonsPayloadRef.current = defaultButtonsPayload;
    savedButtonsPayloadRef.current = defaultButtonsPayload;
  }, [appConfig.available_symbols, seededDefaultButtons]);

  const hideInteractionTip = useCallback(() => {
    localStorage.setItem(INTERACTION_TIP_STORAGE_KEY, 'true');
    setShowInteractionTip(false);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const fetchAppConfig = async () => {
      try {
        const response = await axios.get<AppConfig>(`${API_BASE}/app-config`);
        if (!cancelled) {
          setAppConfig(response.data);
          setAvailableSymbols(response.data.available_symbols);
        }
      } catch (error) {
        console.error('App config error:', error);
      } finally {
        if (!cancelled) {
          setAppConfigLoaded(true);
        }
      }
    };

    void fetchAppConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    document.title = appConfig.app_name;
  }, [appConfig.app_name]);

  useEffect(() => {
    if (account) {
      return;
    }

    setTrackerButtons(seededDefaultButtons);
    setSettingsButtonsDraft(seededDefaultButtons);
    setAvailableSymbols(appConfig.available_symbols);
    setSelectedButtonId(seededDefaultButtons[0]?.id ?? '');
    const defaultButtonsPayload = serializeTrackerButtonsPayload(seededDefaultButtons);
    latestButtonsPayloadRef.current = defaultButtonsPayload;
    savedButtonsPayloadRef.current = defaultButtonsPayload;
  }, [account, appConfig.available_symbols, seededDefaultButtons]);

  useEffect(() => {
    const fetchAccount = async () => {
      if (!token) {
        setAuthLoading(false);
        return;
      }

      try {
        const [accountResponse, trackerButtonsResponse] = await Promise.all([
          axios.get<Account>(`${API_BASE}/auth/me`, {
            headers: authHeaders,
          }),
          axios.get<TrackerButtonsResponse>(`${API_BASE}/tracker-buttons`, {
            headers: authHeaders,
          }),
        ]);
        setAccount(accountResponse.data);
        setSettingsBabyName(accountResponse.data.baby_name ?? '');
        setSettingsPalette(accountResponse.data.color_palette ?? 'default');
        setSettingsShareEmails(accountResponse.data.share_emails.join(', '));
        const nextButtons = normalizeTrackerButtons(
          trackerButtonsResponse.data.buttons,
          trackerButtonsResponse.data.available_symbols,
        );
        const nextButtonsPayload = serializeTrackerButtonsPayload(nextButtons);
        setTrackerButtons(nextButtons);
        setSettingsButtonsDraft(nextButtons);
        setAvailableSymbols(trackerButtonsResponse.data.available_symbols);
        setTrackerPageIndex(Math.min(getStoredTrackerPageIndex(), getTrackerButtonPageCount(nextButtons) - 1));
        setSelectedButtonId(nextButtons[0]?.id ?? '');
        setButtonsSaveError(null);
        latestButtonsPayloadRef.current = nextButtonsPayload;
        savedButtonsPayloadRef.current = nextButtonsPayload;
      } catch {
        clearAuth();
      } finally {
        setAuthLoading(false);
      }
    };

    void fetchAccount();
  }, [authHeaders, clearAuth, token]);

  useEffect(() => {
    runningActivitiesRef.current = runningActivities;
  }, [runningActivities]);

  useEffect(() => {
    if (authLoading) {
      return;
    }
    setTrackerPageIndex((current) => Math.min(current, trackerPageCount - 1));
  }, [authLoading, trackerPageCount]);

  useEffect(() => {
    localStorage.setItem(TRACKER_PAGE_STORAGE_KEY, trackerPageIndex.toString());
  }, [trackerPageIndex]);

  useEffect(() => {
    if (currentDraftButtonsPage.length === 0) {
      return;
    }

    if (!currentDraftButtonsPage.some((button) => button.id === selectedButtonId)) {
      setSelectedButtonId(currentDraftButtonsPage[0].id);
    }
  }, [currentDraftButtonsPage, selectedButtonId]);

  const refreshRunningActivities = useCallback(async (options?: { showStoppedElsewhereToast?: boolean }) => {
    if (!authHeaders) {
      setRunningActivities({});
      return;
    }

    const response = await axios.get<EventSummary[]>(`${API_BASE}/activities/active`, {
      headers: authHeaders,
    });

    const nextRunningActivities = response.data.reduce<Record<string, number>>((next, event) => {
      if (event.is_active) {
        next[event.type] = new Date(event.start_time).getTime();
      }
      return next;
    }, {});

    if (options?.showStoppedElsewhereToast) {
      const hadStoppedElsewhere = Object.keys(runningActivitiesRef.current).some(
        (activityId) => !nextRunningActivities[activityId] && !localStopInFlightRef.current.has(activityId),
      );
      if (hadStoppedElsewhere) {
        addToast('Event tracking ended on another active session.', 'info');
      }
    }

    if (Object.keys(nextRunningActivities).length > 0) {
      setCurrentTime(Date.now());
    }

    if (!runningActivitiesEqual(runningActivitiesRef.current, nextRunningActivities)) {
      setRunningActivities(nextRunningActivities);
    }
  }, [addToast, authHeaders]);

  useEffect(() => {
    if (!authHeaders) {
      setRunningActivities({});
      return;
    }

    void refreshRunningActivities();
  }, [authHeaders, refreshRunningActivities]);

  useEffect(() => {
    if (Object.keys(runningActivities).length === 0) {
      return undefined;
    }

    const interval = window.setInterval(() => {
      setCurrentTime(Date.now());
    }, 1000);

    const pollInterval = window.setInterval(() => {
      void refreshRunningActivities({ showStoppedElsewhereToast: true });
    }, ACTIVE_TIMER_STATUS_POLL_INTERVAL_MS);

    return () => {
      window.clearInterval(interval);
      window.clearInterval(pollInterval);
    };
  }, [refreshRunningActivities, runningActivities]);

  const finalizePendingEvent = useCallback(async (details?: string) => {
    if (!activePendingLog || !authHeaders) {
      return null;
    }

    const response = await axios.post<EventSummary>(
      `${API_BASE}/events/${activePendingLog.eventId}/finalize`,
      details !== undefined ? { details } : {},
      { headers: authHeaders },
    );
    return response.data;
  }, [activePendingLog, authHeaders]);

  const resetPendingInput = useCallback(() => {
    setPendingLogs((prev) => prev.slice(1));
    setInputValue('');
  }, []);

  const showCalendarSyncToast = useCallback((event: EventSummary | null) => {
    if (!event?.calendar_sync_message) {
      return;
    }

    if (event.calendar_sync_state === 'local_only' || event.calendar_sync_state === 'queued' || event.calendar_sync_state === 'failed') {
      addToast(event.calendar_sync_message, 'info');
    }
  }, [addToast]);

  const handleAuthSubmit = async () => {
    if (!username.trim() || !password.trim()) {
      addToast('Username and password are required', 'error');
      return;
    }
    if (authMode === 'register' && password.length < 6) {
      addToast('Password must be at least 6 characters', 'error');
      return;
    }

    setIsBusy(true);
    try {
      const endpoint = authMode === 'register' ? '/auth/register' : '/auth/login';
      const payload =
        authMode === 'register'
          ? { username, password, baby_name: registerBabyName || undefined, share_emails: [] }
          : { username, password };

      const response = await axios.post<AuthResponse>(`${API_BASE}${endpoint}`, payload);
      persistAuth(response.data.token, response.data.account);
      setUsername('');
      setPassword('');
      setRegisterBabyName('');
      setActiveView('tracker');
      addToast(authMode === 'register' ? 'Account created' : 'Signed in', 'success');
    } catch (error) {
      addToast(getApiErrorDetail(error) ?? (authMode === 'register' ? 'Failed to create account' : 'Failed to sign in'), 'error');
      console.error('Authentication error:', error);
    } finally {
      setIsBusy(false);
    }
  };

  const handleLogout = async () => {
    if (authHeaders) {
      try {
        await axios.post(`${API_BASE}/auth/logout`, {}, { headers: authHeaders });
      } catch (error) {
        console.error('Logout error:', error);
      }
    }
    clearAuth();
    addToast('Signed out', 'info');
  };

  const refreshAccount = useCallback(async (preserveSettingsDrafts = false) => {
    if (!authHeaders) {
      return;
    }

    const response = await axios.get<Account>(`${API_BASE}/account/settings`, {
      headers: authHeaders,
    });
    setAccount(response.data);
    if (!preserveSettingsDrafts) {
      setSettingsBabyName(response.data.baby_name ?? '');
      setSettingsPalette(response.data.color_palette ?? 'default');
      setSettingsShareEmails(response.data.share_emails.join(', '));
    }
  }, [authHeaders]);

  const completePendingLog = useCallback(async (details?: string) => {
    if (!activePendingLog) {
      return;
    }

    if (pendingLogActionRef.current === activePendingLog.eventId) {
      return;
    }

    pendingLogActionRef.current = activePendingLog.eventId;
    try {
      const finalizedEvent = await finalizePendingEvent(details);
      if (details) {
        addToast('Note saved', 'success');
      }
      showCalendarSyncToast(finalizedEvent);
      resetPendingInput();
      await refreshAccount();
    } finally {
      if (pendingLogActionRef.current === activePendingLog.eventId) {
        pendingLogActionRef.current = null;
      }
    }
  }, [activePendingLog, addToast, finalizePendingEvent, refreshAccount, resetPendingInput, showCalendarSyncToast]);

  const updateDraftButton = useCallback((buttonId: string, changes: Partial<TrackerButtonUpdate>) => {
    setSettingsButtonsDraft((currentButtons) =>
      currentButtons.map((button) => {
        if (button.id !== buttonId) {
          return button;
        }
        return deriveTrackerButton(
          {
            id: button.id,
            label: changes.label ?? button.label,
            icon_key: changes.icon_key ?? button.icon_key,
            color_key: changes.color_key ?? button.color_key,
            position: button.position,
            emoji_override: changes.emoji_override ?? button.emoji_override,
          },
          availableSymbols,
        );
      }),
    );
  }, [availableSymbols]);

  const handleAddButtonsPage = useCallback(() => {
    let nextPageIndex: number | null = null;
    let nextPageButtons: TrackerButtonConfig[] = [];

    setSettingsButtonsDraft((currentButtons) => {
      const orderedButtons = sortTrackerButtons(currentButtons);
      const currentPageCount = getTrackerButtonPageCount(orderedButtons);
      if (currentPageCount >= appConfig.max_tracker_button_pages) {
        return currentButtons;
      }

      nextPageIndex = currentPageCount;
      const templateButtons = getTrackerButtonsForPage(appConfig.button_templates, currentPageCount);
      if (templateButtons.length === TRACKER_BUTTONS_PER_PAGE) {
        nextPageButtons = normalizeTrackerButtons(templateButtons, availableSymbols).map((button, index) => ({
          ...button,
          position: currentPageCount * TRACKER_BUTTONS_PER_PAGE + index,
        }));
      } else {
        nextPageButtons = getTrackerButtonsForPage(
          createTrackerButtonsForPage(orderedButtons, currentPageCount, appConfig.placeholder_button_label_prefix),
          currentPageCount,
        ).map((button) => deriveTrackerButton(button, availableSymbols));
      }

      return [...orderedButtons, ...nextPageButtons].map((button, index) => ({
        ...button,
        position: index,
      }));
    });

    if (nextPageIndex !== null) {
      setTrackerPageIndex(nextPageIndex);
      setSelectedButtonId(nextPageButtons[0]?.id ?? selectedButtonId);
    }
  }, [appConfig.max_tracker_button_pages, appConfig.placeholder_button_label_prefix, availableSymbols, selectedButtonId]);

  const handleDeleteButtonsPage = useCallback(() => {
    if (settingsButtonPageCount <= 1) {
      return;
    }

    const pageStart = trackerPageIndex * TRACKER_BUTTONS_PER_PAGE;
    setSettingsButtonsDraft((currentButtons) =>
      sortTrackerButtons(currentButtons)
        .filter((_, index) => index < pageStart || index >= pageStart + TRACKER_BUTTONS_PER_PAGE)
        .map((button, index) => ({
          ...button,
          position: index,
        })),
    );
    setTrackerPageIndex((current) => Math.min(current, settingsButtonPageCount - 2));
  }, [settingsButtonPageCount, trackerPageIndex]);

  const handleResetButtonsToDefault = useCallback(() => {
    const defaultButtons = normalizeTrackerButtons(getTrackerButtonsForPage(appConfig.button_templates, 0), availableSymbols);
    setSettingsButtonsDraft(defaultButtons);
    setTrackerPageIndex(0);
    setSelectedButtonId(defaultButtons[0]?.id ?? '');
    setButtonsSaveError(null);
  }, [appConfig.button_templates, availableSymbols]);

  const handleCreateCustomIcon = useCallback(async () => {
    if (!authHeaders) {
      return;
    }
    if (!customIconDraft.preparedFile) {
      setCustomIconError('Choose a PNG or SVG file first');
      return;
    }
    if (!isValidEmojiValue(customIconDraft.emoji)) {
      setCustomIconError('Choose a real emoji for calendar titles');
      return;
    }

    setIsCreatingCustomIcon(true);
    setCustomIconError(null);
    try {
      const formData = new FormData();
      formData.append('label', customIconDraft.label.trim() || customIconDraft.preparedFile.name.replace(/\.[^.]+$/, ''));
      formData.append('emoji', customIconDraft.emoji.trim());
      formData.append('keywords', customIconDraft.keywords.trim());
      formData.append('is_public', String(customIconDraft.isPublic));
      formData.append('asset', customIconDraft.preparedFile);

      const response = await axios.post<TrackerSymbolOption>(`${API_BASE}/custom-icons`, formData, {
        headers: authHeaders,
      });
      setAvailableSymbols((prev) => [response.data, ...prev.filter((symbol) => symbol.key !== response.data.key)]);
      if (selectedDraftButton) {
        updateDraftButton(selectedDraftButton.id, { icon_key: response.data.key });
      }
      setSymbolSearch(response.data.label);
      setCustomIconDraft((current) => {
        if (current.previewUrl) {
          URL.revokeObjectURL(current.previewUrl);
        }
        return {
          label: '',
          emoji: '',
          keywords: '',
          isPublic: false,
          sourceFile: null,
          preparedFile: null,
          previewUrl: null,
          zoom: 1,
        };
      });
      addToast('Custom icon added', 'success');
    } catch (error) {
      const errorDetail = getApiErrorDetail(error);
      setCustomIconError(errorDetail ?? 'Failed to create custom icon');
      addToast(errorDetail ?? 'Failed to create custom icon', 'error');
      console.error('Custom icon error:', error);
    } finally {
      setIsCreatingCustomIcon(false);
    }
  }, [addToast, authHeaders, customIconDraft, selectedDraftButton, updateDraftButton]);

  const handleCustomIconFileChange = useCallback(async (file: File | null) => {
    if (!file) {
      setCustomIconDraft((current) => {
        if (current.previewUrl) {
          URL.revokeObjectURL(current.previewUrl);
        }
        return { ...current, sourceFile: null, preparedFile: null, previewUrl: null, zoom: 1 };
      });
      return;
    }

    try {
      const { preparedFile, previewUrl } = await prepareCustomIconFile(file, 1);
      setCustomIconDraft((current) => {
        if (current.previewUrl) {
          URL.revokeObjectURL(current.previewUrl);
        }
        return { ...current, sourceFile: file, preparedFile, previewUrl, zoom: 1 };
      });
      setCustomIconError(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to prepare icon';
      setCustomIconError(message);
      setCustomIconDraft((current) => {
        if (current.previewUrl) {
          URL.revokeObjectURL(current.previewUrl);
        }
        return { ...current, sourceFile: null, preparedFile: null, previewUrl: null, zoom: 1 };
      });
    }
  }, []);

  const handleCustomIconZoom = useCallback(async (direction: -1 | 1) => {
    if (!customIconDraft.sourceFile) {
      return;
    }
    const nextZoom = Math.max(
      CUSTOM_ICON_MIN_ZOOM,
      Math.min(
        CUSTOM_ICON_MAX_ZOOM,
        Number((customIconDraft.zoom + direction * CUSTOM_ICON_ZOOM_STEP).toFixed(2)),
      ),
    );
    if (nextZoom === customIconDraft.zoom) {
      return;
    }

    try {
      const { preparedFile, previewUrl } = await prepareCustomIconFile(customIconDraft.sourceFile, nextZoom);
      setCustomIconDraft((current) => {
        if (current.previewUrl) {
          URL.revokeObjectURL(current.previewUrl);
        }
        return {
          ...current,
          preparedFile,
          previewUrl,
          zoom: nextZoom,
        };
      });
      setCustomIconError(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update icon zoom';
      setCustomIconError(message);
    }
  }, [customIconDraft.sourceFile, customIconDraft.zoom]);

  const handleDeleteSelectedCustomIcon = useCallback(async () => {
    if (!authHeaders || !selectedSymbol?.can_delete) {
      return;
    }
    const customIconId = selectedSymbol.key.startsWith('custom:') ? Number(selectedSymbol.key.replace('custom:', '')) : NaN;
    if (!Number.isFinite(customIconId)) {
      return;
    }

    setIsDeletingCustomIcon(true);
    setCustomIconError(null);
    try {
      await axios.delete(`${API_BASE}/custom-icons/${customIconId}`, { headers: authHeaders });
      setAvailableSymbols((prev) => prev.filter((symbol) => symbol.key !== selectedSymbol.key));
      if (selectedDraftButton) {
        updateDraftButton(selectedDraftButton.id, { icon_key: 'help-circle', emoji_override: null });
      }
      addToast('Custom icon deleted', 'success');
    } catch (error) {
      const errorDetail = getApiErrorDetail(error);
      setCustomIconError(errorDetail ?? 'Failed to delete custom icon');
      addToast(errorDetail ?? 'Failed to delete custom icon', 'error');
    } finally {
      setIsDeletingCustomIcon(false);
    }
  }, [addToast, authHeaders, selectedDraftButton, selectedSymbol, updateDraftButton]);

  const handleButtonsDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }

    setSettingsButtonsDraft((currentButtons) => {
      const orderedButtons = sortTrackerButtons(currentButtons);
      const pageStart = trackerPageIndex * TRACKER_BUTTONS_PER_PAGE;
      const pageButtons = orderedButtons.slice(pageStart, pageStart + TRACKER_BUTTONS_PER_PAGE);
      const oldIndex = pageButtons.findIndex((button) => button.id === active.id);
      const newIndex = pageButtons.findIndex((button) => button.id === over.id);

      if (oldIndex < 0 || newIndex < 0) {
        return currentButtons;
      }

      const reorderedPage = arrayMove(pageButtons, oldIndex, newIndex).map((button, index) => ({
        ...button,
        position: pageStart + index,
      }));

      return [
        ...orderedButtons.slice(0, pageStart),
        ...reorderedPage,
        ...orderedButtons.slice(pageStart + TRACKER_BUTTONS_PER_PAGE),
      ].map((button, index) => ({
        ...button,
        position: index,
      }));
    });
  }, [trackerPageIndex]);

  const handleSaveButtons = useCallback(async (buttonsToSave: TrackerButtonConfig[], showSuccessToast = false) => {
    if (!authHeaders) {
      return;
    }

    if (buttonsAutosaveTimeoutRef.current !== null) {
      window.clearTimeout(buttonsAutosaveTimeoutRef.current);
      buttonsAutosaveTimeoutRef.current = null;
    }

    const payload = buildTrackerButtonsPayload(buttonsToSave);
    const payloadKey = JSON.stringify(payload.buttons);
    if (payloadKey === savedButtonsPayloadRef.current) {
      setButtonsSaveError(null);
      return;
    }

    const requestId = buttonsSaveRequestIdRef.current + 1;
    buttonsSaveRequestIdRef.current = requestId;
    setIsSavingButtons(true);
    setButtonsSaveError(null);

    try {
      const response = await axios.patch<TrackerButtonsResponse>(`${API_BASE}/tracker-buttons`, payload, {
        headers: authHeaders,
      });
      const nextButtons = normalizeTrackerButtons(response.data.buttons, response.data.available_symbols);
      savedButtonsPayloadRef.current = payloadKey;

      if (latestButtonsPayloadRef.current === payloadKey) {
        setTrackerButtons(nextButtons);
        setSettingsButtonsDraft(nextButtons);
        setAvailableSymbols(response.data.available_symbols);
        setSelectedButtonId((current) => {
          if (nextButtons.some((button) => button.id === current)) {
            return current;
          }
          return nextButtons[0]?.id ?? '';
        });
      }

      if (showSuccessToast) {
        addToast('Buttons saved', 'success');
      }
    } catch (error) {
      const errorDetail = getApiErrorDetail(error);

      if (latestButtonsPayloadRef.current === payloadKey) {
        setButtonsSaveError(errorDetail ?? 'Failed to save changes');
        addToast(errorDetail ?? 'Failed to save buttons', 'error');
      }
      console.error('Tracker button settings error:', error);
    } finally {
      if (requestId === buttonsSaveRequestIdRef.current) {
        setIsSavingButtons(false);
      }
    }
  }, [addToast, authHeaders]);

  useEffect(() => {
    latestButtonsPayloadRef.current = serializedSettingsButtonsDraft;
  }, [serializedSettingsButtonsDraft]);

  useEffect(() => {
    if (!authHeaders) {
      return undefined;
    }

    const payloadChanged = latestButtonsPayloadRef.current !== savedButtonsPayloadRef.current;
    if (!payloadChanged) {
      setButtonsSaveError(null);
      if (buttonsAutosaveTimeoutRef.current !== null) {
        window.clearTimeout(buttonsAutosaveTimeoutRef.current);
        buttonsAutosaveTimeoutRef.current = null;
      }
      return undefined;
    }

    if (invalidButtonEmojiOverride) {
      setButtonsSaveError(`Choose a valid emoji for ${invalidButtonEmojiOverride.label.trim() || 'that button'}`);
      if (buttonsAutosaveTimeoutRef.current !== null) {
        window.clearTimeout(buttonsAutosaveTimeoutRef.current);
        buttonsAutosaveTimeoutRef.current = null;
      }
      return undefined;
    }

    if (buttonsAutosaveTimeoutRef.current !== null) {
      window.clearTimeout(buttonsAutosaveTimeoutRef.current);
    }

    buttonsAutosaveTimeoutRef.current = window.setTimeout(() => {
      buttonsAutosaveTimeoutRef.current = null;
      void handleSaveButtons(settingsButtonsDraft);
    }, TRACKER_BUTTON_AUTOSAVE_DELAY_MS);

    return () => {
      if (buttonsAutosaveTimeoutRef.current !== null) {
        window.clearTimeout(buttonsAutosaveTimeoutRef.current);
        buttonsAutosaveTimeoutRef.current = null;
      }
    };
  }, [authHeaders, handleSaveButtons, invalidButtonEmojiOverride, serializedSettingsButtonsDraft, settingsButtonsDraft]);

  const handleUndoPendingLog = useCallback(async () => {
    if (!activePendingLog || !authHeaders) {
      return;
    }

    if (pendingLogActionRef.current === activePendingLog.eventId) {
      return;
    }

    pendingLogActionRef.current = activePendingLog.eventId;
    try {
      await axios.delete(`${API_BASE}/events/${activePendingLog.eventId}`, {
        headers: authHeaders,
      });
      addToast('Event undone', 'info');
      resetPendingInput();
      await refreshAccount();
    } catch (error) {
      addToast('Failed to undo event', 'error');
      console.error('Undo event error:', error);
    } finally {
      if (pendingLogActionRef.current === activePendingLog.eventId) {
        pendingLogActionRef.current = null;
      }
    }
  }, [activePendingLog, addToast, authHeaders, refreshAccount, resetPendingInput]);

  const saveSettingsRequest = async () => {
    if (!authHeaders) {
      return null;
    }

    const response = await axios.patch<Account>(
      `${API_BASE}/account/settings`,
      {
        baby_name: settingsBabyName || null,
        color_palette: settingsPalette,
        share_emails: parseEmails(settingsShareEmails),
      },
      { headers: authHeaders },
    );
    setAccount(response.data);
    return response.data;
  };

  const savePaletteRequest = useCallback(
    async (palette: ThemePaletteKey) => {
      if (!authHeaders) {
        return null;
      }

      const response = await axios.patch<Account>(
        `${API_BASE}/account/settings`,
        { color_palette: palette },
        { headers: authHeaders },
      );
      setAccount(response.data);
      return response.data;
    },
    [authHeaders],
  );

  const handleSaveSettings = async () => {
    if (!authHeaders) {
      return;
    }

    setIsBusy(true);
    try {
      await saveSettingsRequest();
      addToast('Settings saved', 'success');
    } catch (error) {
      addToast('Failed to save settings', 'error');
      console.error('Settings error:', error);
    } finally {
      setIsBusy(false);
    }
  };

  useEffect(() => {
    document.documentElement.dataset.palette = settingsPalette;
    return () => {
      delete document.documentElement.dataset.palette;
    };
  }, [settingsPalette]);

  useEffect(() => {
    if (!authHeaders || !account) {
      return undefined;
    }

    if ((account.color_palette ?? 'default') === settingsPalette) {
      setPaletteSaveError(null);
      if (paletteAutosaveTimeoutRef.current !== null) {
        window.clearTimeout(paletteAutosaveTimeoutRef.current);
        paletteAutosaveTimeoutRef.current = null;
      }
      return undefined;
    }

    if (paletteAutosaveTimeoutRef.current !== null) {
      window.clearTimeout(paletteAutosaveTimeoutRef.current);
    }

    paletteAutosaveTimeoutRef.current = window.setTimeout(() => {
      paletteAutosaveTimeoutRef.current = null;
      const requestId = paletteSaveRequestIdRef.current + 1;
      paletteSaveRequestIdRef.current = requestId;
      setIsSavingPalette(true);
      setPaletteSaveError(null);

      void (async () => {
        try {
          await savePaletteRequest(settingsPalette);
        } catch (error) {
          if (requestId === paletteSaveRequestIdRef.current) {
            setPaletteSaveError('Failed to save palette');
            addToast('Failed to save palette', 'error');
          }
          console.error('Palette settings error:', error);
        } finally {
          if (requestId === paletteSaveRequestIdRef.current) {
            setIsSavingPalette(false);
          }
        }
      })();
    }, PALETTE_AUTOSAVE_DELAY_MS);

    return () => {
      if (paletteAutosaveTimeoutRef.current !== null) {
        window.clearTimeout(paletteAutosaveTimeoutRef.current);
        paletteAutosaveTimeoutRef.current = null;
      }
    };
  }, [account, addToast, authHeaders, savePaletteRequest, settingsPalette]);

  const handleEnableSync = async () => {
    if (!authHeaders) {
      return;
    }

    setIsBusy(true);
    try {
      await saveSettingsRequest();
      const response = await axios.post<Account>(`${API_BASE}/calendar/enable-sync`, {}, { headers: authHeaders });
      setAccount(response.data);
      addToast('Calendar sync enabled', 'success');
    } catch (error) {
      addToast('Failed to provision calendar', 'error');
      console.error('Enable sync error:', error);
    } finally {
      setIsBusy(false);
    }
  };

  const handleReshare = async () => {
    if (!authHeaders) {
      return;
    }

    setIsBusy(true);
    try {
      const response = await axios.post<Account>(`${API_BASE}/calendar/reshare`, {}, { headers: authHeaders });
      setAccount(response.data);
      addToast('Calendar re-shared', 'success');
    } catch (error) {
      addToast('Failed to re-share calendar', 'error');
      console.error('Reshare error:', error);
    } finally {
      setIsBusy(false);
    }
  };

  const runGoogleSync = useCallback(async (showToast: boolean) => {
    if (!authHeaders) {
      return;
    }

    if (autoSyncInFlightRef.current) {
      return;
    }

    autoSyncInFlightRef.current = true;
    try {
      const response = await axios.post<{
        imported_count: number;
        updated_count: number;
        deleted_count: number;
      }>(`${API_BASE}/calendar/sync`, {}, { headers: authHeaders });
      await refreshAccount(true);
      if (showToast) {
        addToast(
          `Synced Google changes (+${response.data.imported_count} new, ${response.data.updated_count} updated, ${response.data.deleted_count} deleted)`,
          'success',
        );
      }
    } catch (error) {
      if (showToast) {
        addToast('Failed to sync from Google', 'error');
      }
      console.error('Google sync error:', error);
    } finally {
      autoSyncInFlightRef.current = false;
    }
  }, [addToast, authHeaders, refreshAccount]);

  const handleForceSyncFromGoogle = async () => {
    setIsBusy(true);
    try {
      await runGoogleSync(true);
    } finally {
      setIsBusy(false);
    }
  };

  const handleClearToday = async () => {
    if (!authHeaders) {
      return;
    }

    setIsBusy(true);
    try {
      const response = await axios.delete<{ deleted_count: number }>(`${API_BASE}/events/day`, {
        headers: authHeaders,
        params: { time_zone: BROWSER_TIME_ZONE },
      });
      setRunningActivities({});
      setPendingLogs([]);
      setInputValue('');
      addToast(`Deleted ${response.data.deleted_count} event(s) for today`, 'success');
    } catch (error) {
      addToast('Failed to clear today', 'error');
      console.error('Clear day error:', error);
    } finally {
      setIsBusy(false);
    }
  };

  const handleSimulateDay = async () => {
    if (!authHeaders) {
      return;
    }

    setIsBusy(true);
    try {
      const response = await axios.post<{ created_count: number }>(
        `${API_BASE}/events/simulate-day`,
        {},
        { headers: authHeaders, params: { time_zone: BROWSER_TIME_ZONE } },
      );
      addToast(`Created ${response.data.created_count} sample events`, 'success');
    } catch (error) {
      addToast('Failed to simulate day', 'error');
      console.error('Simulate day error:', error);
    } finally {
      setIsBusy(false);
    }
  };

  const handleTap = async (activityId: string) => {
    if (!authHeaders) {
      return;
    }

    try {
      const response = await axios.post<EventSummary>(
        `${API_BASE}/events`,
        {
          type: activityId,
          start_time: new Date().toISOString(),
        },
        { headers: authHeaders },
      );
      addToast('Event logged', 'success');
      setPendingLogs((prev) => [...prev, { eventId: response.data.id, activityId }]);
    } catch (error) {
      addToast('Failed to log event', 'error');
      console.error('Event logging error:', error);
    }
  };

  const handleLongPress = async (activityId: string) => {
    if (!authHeaders) {
      return;
    }

    if (runningActivities[activityId]) {
      localStopInFlightRef.current.add(activityId);
      try {
        const response = await axios.post<{
          status: 'success' | 'error';
          message: string;
          event_id?: number;
          duration_seconds?: number;
        }>(
          `${API_BASE}/activities/stop`,
          { type: activityId },
          { headers: authHeaders },
        );
        if (response.data.status !== 'success' || response.data.event_id === undefined || response.data.duration_seconds === undefined) {
          await refreshRunningActivities();
          if (response.data.message?.includes('No active timer')) {
            addToast('Event tracking ended on another active session.', 'info');
            return;
          }
          addToast(response.data.message || 'Failed to stop activity', 'error');
          return;
        }
        const { event_id: eventId, duration_seconds: durationSeconds } = response.data;
        hideInteractionTip();
        addToast(`Stopped (${formatDuration(durationSeconds)})`, 'success');
        setRunningActivities((prev) => {
          const next = { ...prev };
          delete next[activityId];
          return next;
        });
        setPendingLogs((prev) => [...prev, { eventId, activityId }]);
      } catch (error) {
        addToast('Failed to stop activity', 'error');
        console.error('Stop activity error:', error);
      } finally {
        localStopInFlightRef.current.delete(activityId);
      }
      return;
    }

    try {
      const response = await axios.post<{
        status: 'success' | 'error';
        message: string;
        start_time?: string;
      }>(`${API_BASE}/activities/start`, { type: activityId }, { headers: authHeaders });
      if (response.data.status !== 'success' || !response.data.start_time) {
        await refreshRunningActivities();
        addToast(response.data.message || 'Failed to start activity', 'error');
        return;
      }
      const { start_time: startTime } = response.data;
      hideInteractionTip();
      setCurrentTime(Date.now());
      setRunningActivities((prev) => ({
        ...prev,
        [activityId]: new Date(startTime).getTime(),
      }));
    } catch (error) {
      addToast('Failed to start activity', 'error');
      console.error('Start activity error:', error);
    }
  };

  const handleInputSubmit = useCallback(async () => {
    const trimmedInput = inputValue.trim();
    if (!trimmedInput) {
      try {
        await completePendingLog();
      } catch (error) {
        addToast('Failed to save event', 'error');
        console.error('Finalize event error:', error);
      }
      return;
    }

    try {
      await completePendingLog(trimmedInput);
    } catch (error) {
      addToast('Failed to save event', 'error');
      console.error('Finalize event error:', error);
    }
  }, [addToast, completePendingLog, inputValue]);

  const handleInputDismiss = useCallback(async () => {
    try {
      await completePendingLog();
    } catch (error) {
      addToast('Failed to save event', 'error');
      console.error('Finalize event error:', error);
    }
  }, [addToast, completePendingLog]);

  useEffect(() => {
    if (!authHeaders || !account?.calendar_connected) {
      return undefined;
    }

    void runGoogleSync(false);
    const interval = window.setInterval(() => {
      void runGoogleSync(false);
    }, GOOGLE_SYNC_POLL_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [authHeaders, account?.calendar_connected, account?.google_calendar_id, runGoogleSync]);

  useEffect(() => {
    if (!activePendingLog || inputValue.trim()) {
      return undefined;
    }

    const timeout = window.setTimeout(() => {
      void handleInputDismiss();
    }, NOTE_SHEET_AUTO_DISMISS_MS);

    return () => window.clearTimeout(timeout);
  }, [activePendingLog, handleInputDismiss, inputValue]);

  if (!appConfigLoaded || authLoading) {
    return <div className="app-shell min-h-screen grid place-items-center app-muted">Loading…</div>;
  }

  if (!account) {
    return (
      <div className="app-shell min-h-screen px-6 py-10">
        <div className="app-surface max-w-md mx-auto rounded-3xl border p-6 shadow-xl space-y-6">
          <div className="space-y-2 text-center">
            <div className="app-accent-soft inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold">
              <ShieldCheck size={16} />
              {appConfig.copy.auth_badge_label}
            </div>
            <h1 className="text-3xl font-bold">{appConfig.copy.auth_heading}</h1>
            <p className="app-muted text-sm">
              {appConfig.copy.auth_subheading}
            </p>
          </div>

          <div className="app-subtle flex rounded-2xl p-1">
            <button
              className={clsx('flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition', authMode === 'login' ? 'app-surface shadow app-text' : 'app-muted')}
              onClick={() => setAuthMode('login')}
            >
              Sign in
            </button>
            <button
              className={clsx('flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition', authMode === 'register' ? 'app-surface shadow app-text' : 'app-muted')}
              onClick={() => setAuthMode('register')}
            >
              Create account
            </button>
          </div>

          <div className="space-y-4">
            <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="Username"
                className="app-input app-focus w-full rounded-2xl border px-4 py-3"
              />
            <input
              type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Password"
                className="app-input app-focus w-full rounded-2xl border px-4 py-3"
              />
            {authMode === 'register' && <p className="app-muted -mt-2 text-xs">Password must be at least 6 characters.</p>}
            {authMode === 'register' && (
            <input
                value={registerBabyName}
                onChange={(event) => setRegisterBabyName(event.target.value)}
                  placeholder={appConfig.copy.register_name_placeholder}
                  className="app-input app-focus w-full rounded-2xl border px-4 py-3"
                />
              )}
              <button
                onClick={() => void handleAuthSubmit()}
                disabled={isBusy}
                className="app-primary-button w-full rounded-2xl px-4 py-3 font-semibold disabled:opacity-60"
              >
                {isBusy ? 'Working…' : authMode === 'register' ? appConfig.copy.create_account_label : 'Sign in'}
              </button>
          </div>
        </div>

        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 w-full max-w-sm px-4 pointer-events-none">
          {toasts.map((toast) => (
            <div key={toast.id} className="pointer-events-auto flex justify-center">
              <Toast message={toast.message} type={toast.type} />
            </div>
          ))}
        </div>
        <PrivacyNoticeWidget />
      </div>
    );
  }

  return (
    <div className="app-shell flex min-h-screen min-h-[100dvh] flex-col font-sans selection:bg-[var(--app-accent-soft)]">
      <header className="app-header sticky top-0 inset-x-0 z-10 shrink-0 border-b px-4 py-3 backdrop-blur-md">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="app-title bg-clip-text text-xl font-bold text-transparent">{appConfig.app_name}</h1>
              {displayedTrackerPageCount > 1 && (
                <div className="inline-flex items-center gap-1">
                  {Array.from({ length: displayedTrackerPageCount }, (_, pageIndex) => (
                    <button
                      key={pageIndex}
                      type="button"
                      onClick={() => setTrackerPageIndex(pageIndex)}
                      className={clsx(
                        'flex h-7 w-7 items-center justify-center rounded-lg border text-[11px] font-bold transition',
                        trackerPageIndex === pageIndex ? 'app-page-button-active' : 'app-page-button',
                      )}
                      aria-label={`Show tracker page ${pageIndex + 1}`}
                      title={`Page ${pageIndex + 1}`}
                    >
                      {pageIndex + 1}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p className="app-muted text-xs">
                {headerContextText}
              </p>
              <button
                type="button"
                onClick={() => {
                  setSettingsTab('calendar');
                  setActiveView('settings');
                }}
                className={clsx(
                  'app-status-pill inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold transition',
                  account.calendar_connected ? 'app-status-pill-connected' : 'app-status-pill-local',
                )}
                aria-label="Open calendar settings"
              >
                <ShieldCheck size={12} />
                {account.calendar_connected ? 'Sync active' : 'Local only'}
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveView(activeView === 'tracker' ? 'settings' : 'tracker')}
              className="app-icon-button rounded-xl p-2 transition"
              aria-label="Toggle settings"
            >
              {activeView === 'tracker' ? <Settings size={18} /> : <X size={18} />}
            </button>
            <button
              onClick={() => void handleLogout()}
              className="app-icon-button rounded-xl p-2 transition"
              aria-label="Sign out"
            >
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-3xl min-h-0 flex-1 flex-col px-4 pb-4 pt-3 sm:px-6">
        {activeView === 'settings' ? (
          <section className="mx-auto w-full max-w-xl pb-6">
            <div className="app-surface rounded-3xl border p-6 shadow-lg space-y-5">
              <div>
                <h2 className="text-xl font-bold">Settings</h2>
                <p className="app-muted mt-1 text-sm">
                  Manage calendar sync, tracked button pages, and app-wide appearance.
                </p>
              </div>
              <div className="app-subtle flex rounded-2xl p-1">
                <button
                  onClick={() => setSettingsTab('calendar')}
                  className={clsx(
                    'flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition',
                    settingsTab === 'calendar' ? 'app-surface shadow app-text' : 'app-muted',
                  )}
                >
                  Calendar
                </button>
                <button
                  onClick={() => setSettingsTab('buttons')}
                  className={clsx(
                    'flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition',
                    settingsTab === 'buttons' ? 'app-surface shadow app-text' : 'app-muted',
                  )}
                >
                  Buttons
                </button>
                <button
                  onClick={() => setSettingsTab('app')}
                  className={clsx(
                    'flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition',
                    settingsTab === 'app' ? 'app-surface shadow app-text' : 'app-muted',
                  )}
                >
                  App
                </button>
              </div>

              {settingsTab === 'calendar' ? (
                <>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-semibold mb-2">{appConfig.copy.settings_name_label}</label>
                      <input
                        value={settingsBabyName}
                        onChange={(event) => setSettingsBabyName(event.target.value)}
                        placeholder={appConfig.copy.settings_name_placeholder}
                        className="app-input app-focus w-full rounded-2xl border px-4 py-3"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold mb-2">Share with Gmail addresses</label>
                      <textarea
                        value={settingsShareEmails}
                        onChange={(event) => setSettingsShareEmails(event.target.value)}
                        placeholder="mom@example.com, dad@example.com"
                        rows={4}
                        className="app-input app-focus w-full rounded-2xl border px-4 py-3"
                      />
                      <p className="app-muted mt-2 text-xs">
                        {appConfig.copy.enable_sync_name_help}
                      </p>
                    </div>
                  </div>

                  <div className="app-subtle rounded-2xl border p-4 text-sm space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-semibold">Sync status</span>
                      <span className={clsx('app-status-pill px-3 py-1 rounded-full text-xs font-semibold', account.calendar_connected ? 'app-status-pill-connected' : 'app-status-pill-local')}>
                        {account.calendar_connected ? 'Connected' : 'Local only'}
                      </span>
                    </div>
                    {account.google_calendar_summary && <p>Calendar: {account.google_calendar_summary}</p>}
                    {account.calendar_url && (
                      <a href={account.calendar_url} target="_blank" rel="noreferrer" className="app-accent-text underline">
                        Open in Google Calendar
                      </a>
                    )}
                    <p className="app-muted">
                      {account.service_managed_calendar
                        ? 'This calendar is owned by the service account and shared back to your saved emails.'
                        : account.calendar_connected
                          ? 'You are still linked to the legacy shared calendar. Enabling sync will provision your own household calendar.'
                          : 'Provisioning creates a service-account-owned calendar for this household.'}
                    </p>
                    {account.google_last_synced_at && (
                      <p className="app-muted">
                        Last Google pull sync: {new Date(account.google_last_synced_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                      </p>
                    )}
                  </div>

                  <div className="grid gap-3 sm:grid-cols-3">
                    <button
                      onClick={() => void handleSaveSettings()}
                      disabled={isBusy}
                      className="app-primary-button rounded-2xl px-4 py-3 font-semibold disabled:opacity-60"
                    >
                      Save settings
                    </button>
                    <button
                      onClick={() => void handleEnableSync()}
                      disabled={isBusy}
                      className="app-primary-button rounded-2xl px-4 py-3 font-semibold disabled:opacity-60"
                    >
                      Enable sync
                    </button>
                    <button
                      onClick={() => void handleReshare()}
                      disabled={isBusy}
                      className="rounded-2xl bg-emerald-600 px-4 py-3 font-semibold text-white disabled:opacity-60"
                    >
                      Re-share calendar
                    </button>
                  </div>

                  <div className="rounded-2xl border border-dashed p-4 space-y-3 [border-color:var(--app-border)]">
                    <div>
                      <h3 className="app-muted text-sm font-bold uppercase tracking-wide">Quick tools</h3>
                      <p className="app-muted mt-1 text-sm">
                        Handy cleanup and visualization shortcuts scoped only to this signed-in household.
                      </p>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <button
                        onClick={() => void handleClearToday()}
                        disabled={isBusy}
                        className="rounded-2xl bg-rose-600 px-4 py-3 font-semibold text-white disabled:opacity-60"
                      >
                        Delete today's events
                      </button>
                      <button
                        onClick={() => void handleSimulateDay()}
                        disabled={isBusy || !account.calendar_connected}
                        className="rounded-2xl bg-violet-600 px-4 py-3 font-semibold text-white disabled:opacity-60"
                      >
                        Simulate sample day
                      </button>
                      <button
                        onClick={() => void handleForceSyncFromGoogle()}
                        disabled={isBusy || !account.calendar_connected}
                        className="rounded-2xl bg-violet-700 px-4 py-3 font-semibold text-white disabled:opacity-60"
                      >
                        Force sync now
                      </button>
                    </div>
                  </div>
                </>
              ) : settingsTab === 'buttons' ? (
                <div className="space-y-4">
                  <div className="app-subtle rounded-2xl border p-4">
                    <h3 className="app-muted text-sm font-bold uppercase tracking-wide">Tracked buttons</h3>
                    <p className="app-muted mt-1 text-sm">
                      Edit one page at a time. Drag to reorder and click a button to edit its label or icon below. Changes save automatically.
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="app-subtle inline-flex rounded-2xl p-1">
                      {Array.from({ length: settingsButtonPageCount }, (_, pageIndex) => (
                        <button
                          key={pageIndex}
                          type="button"
                          onClick={() => setTrackerPageIndex(pageIndex)}
                          className={clsx(
                            'flex h-9 w-9 items-center justify-center rounded-xl border text-sm font-semibold transition',
                            trackerPageIndex === pageIndex ? 'app-page-button-active shadow-sm' : 'app-page-button',
                          )}
                          aria-label={`Show tracker page ${pageIndex + 1}`}
                          title={`Page ${pageIndex + 1}`}
                        >
                          {pageIndex + 1}
                        </button>
                      ))}
                    </div>
                  <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={handleAddButtonsPage}
                        disabled={settingsButtonPageCount >= appConfig.max_tracker_button_pages}
                        className="app-primary-button rounded-xl px-3 py-2 text-sm font-semibold disabled:opacity-60"
                      >
                        Add page
                      </button>
                      <button
                        type="button"
                        onClick={handleDeleteButtonsPage}
                        disabled={settingsButtonPageCount <= 1}
                        className="app-page-button rounded-xl border px-3 py-2 text-sm font-semibold disabled:opacity-50"
                      >
                        Delete page
                      </button>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <DndContext sensors={dragSensors} collisionDetection={closestCenter} onDragEnd={handleButtonsDragEnd}>
                      <div className="grid justify-items-center gap-x-4 gap-y-4 sm:gap-x-6 sm:gap-y-6 grid-cols-2 md:grid-cols-4">
                        <SortableContext items={currentDraftButtonsPage.map((button) => button.id)} strategy={rectSortingStrategy}>
                          {currentDraftButtonsPage.map((button) => (
                            <SortableDraftButtonCard
                              key={button.id}
                              button={button}
                              symbol={getTrackerSymbol(availableSymbols, button.icon_key)}
                              isSelected={button.id === selectedDraftButton?.id}
                              onSelect={() => setSelectedButtonId(button.id)}
                            />
                          ))}
                        </SortableContext>
                      </div>
                    </DndContext>

                    {selectedDraftButton && (
                      <div className="app-surface space-y-4 rounded-2xl border p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <h3 className="font-semibold">{selectedDraftButton.label}</h3>
                            <p className="app-muted text-sm">
                              Calendar preview: {selectedDraftButton.title}
                            </p>
                          </div>
                          <div className={clsx('flex h-14 w-14 items-center justify-center rounded-2xl shadow-md', getTrackerButtonColorClass(selectedDraftButton.color_key))}>
                            <TrackerSymbolIcon
                              symbol={getTrackerSymbol(availableSymbols, selectedDraftButton.icon_key)}
                              iconKey={selectedDraftButton.icon_key}
                              size={24}
                              className="text-white"
                              strokeWidth={2.4}
                            />
                          </div>
                        </div>

                        <div>
                          <label className="mb-2 block text-sm font-semibold">Button label</label>
                          <input
                            value={selectedDraftButton.label}
                            onChange={(event) => updateDraftButton(selectedDraftButton.id, { label: event.target.value })}
                            maxLength={24}
                            placeholder="Button label"
                            className="app-input app-focus w-full rounded-2xl border px-4 py-3"
                          />
                          <p className="app-muted mt-2 text-xs">
                            Keep it short so it fits cleanly on the main grid.
                          </p>
                        </div>

                        <div>
                          <label className="mb-2 block text-sm font-semibold">Button color</label>
                          <div className="grid grid-cols-4 gap-2 sm:grid-cols-8">
                            {TRACKER_BUTTON_COLOR_OPTIONS.map((colorOption) => {
                              const isSelected = selectedDraftButton.color_key === colorOption.key;
                              return (
                                <button
                                  key={colorOption.key}
                                  type="button"
                                  onClick={() => updateDraftButton(selectedDraftButton.id, { color_key: colorOption.key })}
                                  className={clsx(
                                    'flex flex-col items-center gap-2 rounded-2xl border p-2 text-center transition',
                                    isSelected ? 'app-page-button-active' : 'app-surface hover:opacity-90',
                                  )}
                                  aria-label={`Use ${colorOption.label} color`}
                                  title={colorOption.label}
                                >
                                  <span
                                    className={clsx(
                                      'flex h-8 w-8 items-center justify-center rounded-full border border-white/20 shadow-sm',
                                      getTrackerButtonColorClass(colorOption.key),
                                    )}
                                  />
                                  <span className="text-[10px] font-semibold uppercase tracking-wide">{colorOption.label}</span>
                                </button>
                              );
                            })}
                          </div>
                          <p className="app-muted mt-2 text-xs">
                            New placeholder pages now rotate through the palette, and you can override any button color here.
                          </p>
                        </div>

                        <div>
                          <div className="mb-2 flex items-center justify-between gap-3">
                            <label className="block text-sm font-semibold">Calendar emoji</label>
                            <button
                              type="button"
                              onClick={() => updateDraftButton(selectedDraftButton.id, { emoji_override: null })}
                              className="app-muted text-xs font-semibold"
                            >
                              Use suggested
                            </button>
                          </div>
                          <input
                            value={selectedDraftButton.emoji_override ?? ''}
                            onChange={(event) => updateDraftButton(selectedDraftButton.id, { emoji_override: event.target.value })}
                            maxLength={16}
                            placeholder={selectedSymbol?.emoji ?? 'Emoji'}
                            className="app-input app-focus w-full rounded-2xl border px-4 py-3"
                          />
                          <p className="app-muted mt-2 text-xs">
                            {selectedDraftButton.emoji_override && !isValidEmojiValue(selectedDraftButton.emoji_override)
                              ? 'Enter a real emoji here, not plain text.'
                              : 'This overrides the emoji used in the calendar preview when the default symbol match is wrong.'}
                          </p>
                        </div>

                        <div>
                          <label className="mb-2 block text-sm font-semibold">Search symbols</label>
                          <div className="relative">
                            <Search className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 app-muted" size={18} />
                            <input
                              value={symbolSearch}
                              onChange={(event) => setSymbolSearch(event.target.value)}
                              placeholder="Search work, pizza, pasta, bowel, meal, custom..."
                              className="app-input app-focus w-full rounded-2xl border py-3 pl-11 pr-4"
                            />
                          </div>
                          <p className="app-muted mt-2 text-xs">
                            Searches Lucide plus your custom icons and public community icons.
                          </p>
                        </div>

                        {selectedSymbol && (
                          <div className="app-subtle space-y-2 rounded-2xl border px-4 py-3">
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="font-semibold">{selectedSymbol.label}</p>
                                <p className="app-muted text-xs">
                                  {symbolSourceLabel(selectedSymbol)}
                                  {selectedSymbol.category ? ` · ${selectedSymbol.category}` : ''}
                                  {selectedSymbol.emoji ? ` · default ${selectedSymbol.emoji}` : ''}
                                </p>
                              </div>
                              {selectedSymbol.can_delete && (
                                <button
                                  type="button"
                                  onClick={() => void handleDeleteSelectedCustomIcon()}
                                  disabled={isDeletingCustomIcon}
                                  className="rounded-xl border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-700 disabled:opacity-60 dark:border-rose-700 dark:text-rose-300"
                                >
                                  <span className="inline-flex items-center gap-2">
                                    <Trash2 size={14} />
                                    Delete icon
                                  </span>
                                </button>
                              )}
                            </div>
                          </div>
                        )}

                        <div className="space-y-4">
                          {filteredSymbolGroups.map((group) => (
                            <div key={group.title} className="space-y-2">
                              <p className="app-muted text-xs font-bold uppercase tracking-wide">{group.title}</p>
                              <div className="grid grid-cols-5 gap-2 sm:grid-cols-7 md:grid-cols-9 lg:grid-cols-10">
                                {group.symbols.map((symbol) => {
                                  const isSelected = symbol.key === selectedDraftButton.icon_key;

                                  return (
                                    <button
                                      key={symbol.key}
                                      type="button"
                                      onClick={() => updateDraftButton(selectedDraftButton.id, { icon_key: symbol.key })}
                                      className={clsx(
                                        'app-surface flex aspect-square items-center justify-center rounded-2xl border p-2 transition hover:opacity-90',
                                        isSelected && 'app-page-button-active',
                                      )}
                                      aria-label={symbol.label}
                                      title={`${symbol.label} · ${symbolSourceLabel(symbol)}`}
                                    >
                                      <TrackerSymbolIcon symbol={symbol} iconKey={symbol.key} size={20} />
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          ))}
                        </div>

                        {filteredSymbols.length === 0 && (
                          <p className="app-muted rounded-2xl border border-dashed px-4 py-3 text-sm [border-color:var(--app-border)]">
                            No symbols match that search yet.
                          </p>
                        )}

                        <div className="app-subtle space-y-4 rounded-2xl border p-4">
                          <div className="flex items-center gap-2">
                            <ImagePlus size={18} />
                            <h4 className="font-semibold">Add custom icon</h4>
                          </div>
                          <p className="app-muted text-sm">
                            Upload a square-ish PNG or SVG, choose the matching emoji for calendar titles, and optionally share it publicly.
                          </p>
                          <div className="grid gap-3 sm:grid-cols-2">
                            <div className="app-surface flex aspect-square flex-col items-center justify-center gap-3 rounded-2xl border sm:row-span-2">
                              {customIconDraft.previewUrl ? (
                                <>
                                  <img
                                    src={customIconDraft.previewUrl}
                                    alt="Custom icon preview"
                                    className="h-24 w-24 object-contain"
                                  />
                                  <div className="flex items-center gap-2">
                                    <button
                                      type="button"
                                      onClick={() => void handleCustomIconZoom(-1)}
                                      disabled={!customIconDraft.sourceFile || customIconDraft.zoom <= CUSTOM_ICON_MIN_ZOOM}
                                      className="app-page-button rounded-xl border px-3 py-1 text-sm font-semibold disabled:opacity-50"
                                    >
                                      -
                                    </button>
                                    <span className="app-muted min-w-14 text-center text-xs font-semibold">
                                      {Math.round(customIconDraft.zoom * 100)}%
                                    </span>
                                    <button
                                      type="button"
                                      onClick={() => void handleCustomIconZoom(1)}
                                      disabled={!customIconDraft.sourceFile || customIconDraft.zoom >= CUSTOM_ICON_MAX_ZOOM}
                                      className="app-page-button rounded-xl border px-3 py-1 text-sm font-semibold disabled:opacity-50"
                                    >
                                      +
                                    </button>
                                  </div>
                                </>
                              ) : (
                                <span className="app-muted text-xs">Preview</span>
                              )}
                            </div>
                            <input
                              value={customIconDraft.label}
                              onChange={(event) => setCustomIconDraft((current) => ({ ...current, label: event.target.value }))}
                              placeholder="Icon label"
                              className="app-input app-focus rounded-2xl border px-4 py-3"
                            />
                            <input
                              value={customIconDraft.emoji}
                              onChange={(event) => setCustomIconDraft((current) => ({ ...current, emoji: event.target.value }))}
                              placeholder="Emoji"
                              className="app-input app-focus rounded-2xl border px-4 py-3"
                            />
                            {customIconDraft.emoji && !isValidEmojiValue(customIconDraft.emoji) && (
                              <p className="text-sm text-rose-600 dark:text-rose-400">Enter a real emoji for calendar titles.</p>
                            )}
                            <input
                              value={customIconDraft.keywords}
                              onChange={(event) => setCustomIconDraft((current) => ({ ...current, keywords: event.target.value }))}
                              placeholder="Keywords (comma separated)"
                              className="app-input app-focus rounded-2xl border px-4 py-3 sm:col-span-2"
                            />
                            <label className="app-surface flex items-center gap-3 rounded-2xl border px-4 py-3 text-sm font-medium sm:col-span-2">
                              <input
                                type="file"
                                accept=".png,image/png,.svg,image/svg+xml"
                                onChange={(event) => void handleCustomIconFileChange(event.target.files?.[0] ?? null)}
                                className="block flex-1 text-sm"
                              />
                            </label>
                            <label className="app-muted flex items-center gap-2 text-sm sm:col-span-2">
                              <input
                                type="checkbox"
                                checked={customIconDraft.isPublic}
                                onChange={(event) => setCustomIconDraft((current) => ({ ...current, isPublic: event.target.checked }))}
                              />
                              Make public as a community icon
                            </label>
                          </div>
                          <p className="app-muted text-xs">
                            The upload is normalized into a square PNG before saving so it renders consistently across the picker and tracker grid.
                          </p>
                          {customIconError && <p className="text-sm text-rose-600 dark:text-rose-400">{customIconError}</p>}
                          <div className="flex justify-end">
                            <button
                              type="button"
                              onClick={() => void handleCreateCustomIcon()}
                              disabled={isCreatingCustomIcon}
                              className="app-primary-button rounded-xl px-3 py-2 text-sm font-semibold disabled:opacity-60"
                            >
                              {isCreatingCustomIcon ? 'Uploading...' : 'Create icon'}
                            </button>
                          </div>
                        </div>

                        <div className="app-subtle rounded-2xl border px-4 py-3 text-sm">
                          <p className={clsx('app-muted', buttonsSaveError && 'text-rose-600 dark:text-rose-400')}>
                            {buttonsSaveError
                              ? buttonsSaveError
                              : isSavingButtons
                                ? 'Saving changes...'
                                : buttonsHaveUnsavedChanges
                                  ? 'Saving automatically...'
                                  : 'Saved automatically.'}
                          </p>
                        </div>
                      </div>
                    )}

                    <div className="flex justify-end">
                      <button
                        type="button"
                        onClick={handleResetButtonsToDefault}
                        className="app-page-button rounded-xl border px-3 py-2 text-sm font-semibold"
                      >
                        Reset to default
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="app-subtle rounded-2xl border p-4">
                    <h3 className="text-sm font-bold uppercase tracking-wide">App look</h3>
                    <p className="app-muted mt-1 text-sm">
                      Pick the color palette used across the app shell, settings, and tracker surfaces.
                    </p>
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-semibold">Color palette</label>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {THEME_PALETTE_OPTIONS.map((palette) => (
                        <button
                          key={palette.key}
                          type="button"
                          onClick={() => setSettingsPalette(palette.key)}
                          className={clsx(
                            'rounded-2xl border p-4 text-left transition',
                            settingsPalette === palette.key ? 'app-page-button-active' : 'app-surface hover:opacity-90',
                          )}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="font-semibold">{palette.label}</p>
                              <p className="app-muted mt-1 text-xs">{palette.description}</p>
                            </div>
                            <div className="flex items-center gap-1">
                              {palette.swatches.map((swatch) => (
                                <span
                                  key={swatch}
                                  className="h-3 w-3 rounded-full border border-black/5"
                                  style={{ backgroundColor: swatch }}
                                />
                              ))}
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="app-subtle rounded-2xl border px-4 py-3 text-sm">
                    <p className={clsx('app-muted', paletteSaveError && 'text-rose-600 dark:text-rose-400')}>
                      {paletteSaveError
                        ? paletteSaveError
                        : isSavingPalette
                          ? 'Saving palette...'
                          : (account.color_palette ?? 'default') !== settingsPalette
                            ? 'Saving automatically...'
                            : 'Saved automatically.'}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </section>
        ) : (
          <section className="flex flex-1 min-h-0 flex-col gap-3 overflow-y-auto overscroll-contain pb-2">
            <div className="shrink-0 space-y-2 text-center">
              <p className="app-muted text-sm font-medium">What's happening right now?</p>

              {showInteractionTip && (
                <div className="app-accent-soft mx-auto flex max-w-md items-center gap-2 rounded-2xl border px-3 py-2 text-left shadow-sm [border-color:var(--app-accent)]">
                  <div
                    className="rounded-xl p-1.5"
                    style={{ backgroundColor: 'color-mix(in srgb, var(--app-accent) 12%, white)' }}
                  >
                    <HelpCircle size={14} />
                  </div>
                  <p className="min-w-0 flex-1 text-xs">
                    Tap to log. Hold to start or stop a timer.
                  </p>
                  <button
                    onClick={hideInteractionTip}
                    className="app-surface rounded-xl border px-2.5 py-1.5 text-[11px] font-semibold shadow-sm transition hover:opacity-90 [border-color:var(--app-border)]"
                  >
                    Got it
                  </button>
                </div>
              )}
            </div>

            <div className="grid flex-1 min-h-0 content-start justify-items-center gap-x-4 gap-y-4 pt-1 sm:content-center md:grid-cols-4 md:gap-x-6 md:gap-y-8 grid-cols-2">
              {visibleActivities.map((activity) => (
                <ActivityButton
                  key={`${activity.id}-${runningActivities[activity.id] ?? 'idle'}`}
                  activity={activity}
                  isRunning={Boolean(runningActivities[activity.id])}
                  runningSince={runningActivities[activity.id] ?? null}
                  currentTime={currentTime}
                  onTap={() => void handleTap(activity.id)}
                  onLongPress={() => void handleLongPress(activity.id)}
                />
              ))}
            </div>
          </section>
        )}

        <div
          className={clsx(
            'app-overlay fixed inset-0 z-50 flex items-end justify-center px-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] pt-6 transition-all duration-300',
            activePendingLog ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0',
          )}
          onClick={() => {
            if (activePendingLog) {
              void handleInputDismiss();
            }
          }}
        >
          <div
            className={clsx(
              'app-surface w-full max-w-sm rounded-3xl border p-4 shadow-2xl ring-1 ring-black/5 transition-transform duration-500 ease-spring',
              activePendingLog ? 'translate-y-0' : 'translate-y-[120%]',
            )}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <p className="app-text text-sm font-semibold">Add a note?</p>
                <p className="app-muted mt-1 text-xs">{pendingActivityLabel} · auto-skip {Math.floor(NOTE_SHEET_AUTO_DISMISS_MS / 1000)}s</p>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => void handleUndoPendingLog()}
                  className="app-icon-button rounded-xl p-2 transition"
                  aria-label="Undo event"
                  title="Undo event"
                >
                  <Undo2 size={16} />
                </button>
                <button
                  onClick={() => void handleInputDismiss()}
                  className="app-page-button rounded-xl border px-2.5 py-2 text-sm font-semibold transition"
                >
                  Skip
                </button>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <input
                type="text"
                value={inputValue}
                onChange={(event) => setInputValue(event.target.value)}
                placeholder={`Add note for ${pendingActivityLabel}...`}
                className="app-input app-focus min-w-0 flex-1 rounded-xl border px-4 py-3 text-base outline-none"
                autoFocus={Boolean(activePendingLog)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    void handleInputSubmit();
                  }
                  if (event.key === 'Escape') {
                    void handleInputDismiss();
                  }
                }}
              />
              <button
                onClick={() => void handleInputSubmit()}
                className="app-primary-button shrink-0 rounded-xl p-3 transition-all active:scale-95"
                aria-label="Save note"
              >
                <Send size={20} strokeWidth={2.5} />
              </button>
            </div>

          </div>
        </div>
      </main>

      <div className="fixed top-20 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 w-full max-w-sm px-4 pointer-events-none">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto flex justify-center">
            <Toast message={toast.message} type={toast.type} />
          </div>
        ))}
      </div>
      <PrivacyNoticeWidget />
    </div>
  );
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}
