import { createElement, useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  HelpCircle,
  LogOut,
  Send,
  Settings,
  ShieldCheck,
  Undo2,
  X,
  type LucideIcon,
} from 'lucide-react';
import axios from 'axios';
import { clsx } from 'clsx';

import ActivityButton from './components/ActivityButton';
import Toast from './components/Toast';
import { API_BASE, GOOGLE_SYNC_POLL_INTERVAL_MS } from './config';
import {
  DEFAULT_TRACKER_BUTTONS,
  DEFAULT_TRACKER_SYMBOLS,
  createTrackerButtonsForPage,
  deriveTrackerButton,
  getTrackerButtonPageCount,
  getTrackerButtonsForPage,
  getTrackerButtonColorClass,
  getTrackerButtonIcon,
  MAX_TRACKER_BUTTON_PAGES,
  normalizeTrackerButtons,
  sortTrackerButtons,
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
const BROWSER_TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

interface Activity {
  id: string;
  icon: LucideIcon;
  label: string;
  colorClass: string;
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
}

interface PendingLogItem {
  eventId: number;
  activityId: string;
}

function buildTrackerButtonsPayload(buttons: TrackerButtonConfig[]) {
  return {
    buttons: sortTrackerButtons(buttons).map((button, position) => ({
      id: button.id,
      label: button.label.trim(),
      icon_key: button.icon_key,
      color_key: button.color_key,
      position,
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

interface SortableDraftButtonCardProps {
  button: TrackerButtonConfig;
  isSelected: boolean;
  onSelect: () => void;
}

function SortableDraftButtonCard({ button, isSelected, onSelect }: SortableDraftButtonCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: button.id });
  const iconComponent = getTrackerButtonIcon(button.icon_key);

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
        isSelected
          ? 'border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-950/30'
          : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800/40 dark:hover:border-slate-600',
        isDragging && 'shadow-xl opacity-90',
      )}
    >
      <div className={clsx('flex h-[4.5rem] w-[4.5rem] items-center justify-center rounded-2xl shadow-md md:h-24 md:w-24', getTrackerButtonColorClass(button.color_key))}>
        {createElement(iconComponent, { size: 30, className: 'text-white', strokeWidth: 2.4 })}
      </div>
      <p className="max-w-full truncate text-[11px] font-bold uppercase tracking-wide text-slate-700 dark:text-slate-200 md:text-sm">
        {button.label.trim() || 'Untitled'}
      </p>
    </button>
  );
}

export default function App() {
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
  const [settingsTab, setSettingsTab] = useState<'calendar' | 'buttons'>('calendar');
  const [settingsBabyName, setSettingsBabyName] = useState('');
  const [settingsShareEmails, setSettingsShareEmails] = useState('');
  const [trackerButtons, setTrackerButtons] = useState<TrackerButtonConfig[]>(DEFAULT_TRACKER_BUTTONS);
  const [settingsButtonsDraft, setSettingsButtonsDraft] = useState<TrackerButtonConfig[]>(DEFAULT_TRACKER_BUTTONS);
  const [availableSymbols, setAvailableSymbols] = useState<TrackerSymbolOption[]>(DEFAULT_TRACKER_SYMBOLS);
  const [selectedButtonId, setSelectedButtonId] = useState(DEFAULT_TRACKER_BUTTONS[0]?.id ?? 'bottle');
  const [symbolSearch, setSymbolSearch] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [isSavingButtons, setIsSavingButtons] = useState(false);
  const [buttonsSaveError, setButtonsSaveError] = useState<string | null>(null);
  const [showInteractionTip, setShowInteractionTip] = useState(() => localStorage.getItem(INTERACTION_TIP_STORAGE_KEY) !== 'true');
  const autoSyncInFlightRef = useRef(false);
  const buttonsAutosaveTimeoutRef = useRef<number | null>(null);
  const latestButtonsPayloadRef = useRef(serializeTrackerButtonsPayload(DEFAULT_TRACKER_BUTTONS));
  const savedButtonsPayloadRef = useRef(serializeTrackerButtonsPayload(DEFAULT_TRACKER_BUTTONS));
  const buttonsSaveRequestIdRef = useRef(0);
  const dragSensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 6 },
    }),
  );

  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : undefined),
    [token],
  );
  const activities = useMemo<Activity[]>(
    () =>
      sortTrackerButtons(trackerButtons).map((button) => ({
        id: button.id,
        icon: getTrackerButtonIcon(button.icon_key),
        label: button.label,
        colorClass: getTrackerButtonColorClass(button.color_key),
      })),
    [trackerButtons],
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
  const filteredSymbols = useMemo(() => {
    const query = symbolSearch.trim().toLowerCase();
    if (!query) {
      return availableSymbols;
    }

    return availableSymbols.filter((symbol) =>
      [symbol.label, symbol.key, symbol.emoji, ...symbol.keywords]
        .join(' ')
        .toLowerCase()
        .includes(query),
    );
  }, [availableSymbols, symbolSearch]);
  const activePendingLog = pendingLogs[0] ?? null;
  const pendingActivityLabel = activities.find((activity) => activity.id === activePendingLog?.activityId)?.label ?? 'event';
  const serializedSettingsButtonsDraft = useMemo(
    () => serializeTrackerButtonsPayload(settingsButtonsDraft),
    [settingsButtonsDraft],
  );
  const buttonsHaveUnsavedChanges = serializedSettingsButtonsDraft !== savedButtonsPayloadRef.current;

  const addToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = Date.now().toString();
    setToasts((prev) => [...prev, { id, message, type }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, 3000);
  }, []);

  const persistAuth = (nextToken: string, nextAccount: Account) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    setToken(nextToken);
    setAccount(nextAccount);
    setSettingsBabyName(nextAccount.baby_name ?? '');
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
    setTrackerButtons(DEFAULT_TRACKER_BUTTONS);
    setSettingsButtonsDraft(DEFAULT_TRACKER_BUTTONS);
    setAvailableSymbols(DEFAULT_TRACKER_SYMBOLS);
    setSelectedButtonId(DEFAULT_TRACKER_BUTTONS[0]?.id ?? 'bottle');
    setSymbolSearch('');
    setIsSavingButtons(false);
    setButtonsSaveError(null);
    if (buttonsAutosaveTimeoutRef.current !== null) {
      window.clearTimeout(buttonsAutosaveTimeoutRef.current);
      buttonsAutosaveTimeoutRef.current = null;
    }
    const defaultButtonsPayload = serializeTrackerButtonsPayload(DEFAULT_TRACKER_BUTTONS);
    latestButtonsPayloadRef.current = defaultButtonsPayload;
    savedButtonsPayloadRef.current = defaultButtonsPayload;
  }, []);

  const hideInteractionTip = useCallback(() => {
    localStorage.setItem(INTERACTION_TIP_STORAGE_KEY, 'true');
    setShowInteractionTip(false);
  }, []);

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
        setSelectedButtonId(nextButtons[0]?.id ?? 'bottle');
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

  const refreshRunningActivities = useCallback(async () => {
    if (!authHeaders) {
      setRunningActivities({});
      return;
    }

    const response = await axios.get<EventSummary[]>(`${API_BASE}/events`, {
      headers: authHeaders,
    });

    setRunningActivities(
      response.data.reduce<Record<string, number>>((next, event) => {
        if (event.is_active) {
          next[event.type] = new Date(event.start_time).getTime();
        }
        return next;
      }, {}),
    );
  }, [authHeaders]);

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

    return () => window.clearInterval(interval);
  }, [runningActivities]);

  const finalizePendingEvent = useCallback(async (details?: string) => {
    if (!activePendingLog || !authHeaders) {
      return;
    }

    await axios.post(
      `${API_BASE}/events/${activePendingLog.eventId}/finalize`,
      details !== undefined ? { details } : {},
      { headers: authHeaders },
    );
  }, [activePendingLog, authHeaders]);

  const resetPendingInput = useCallback(() => {
    setPendingLogs((prev) => prev.slice(1));
    setInputValue('');
  }, []);

  const handleAuthSubmit = async () => {
    if (!username.trim() || !password.trim()) {
      addToast('Username and password are required', 'error');
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
      addToast(authMode === 'register' ? 'Failed to create account' : 'Failed to sign in', 'error');
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
      setSettingsShareEmails(response.data.share_emails.join(', '));
    }
  }, [authHeaders]);

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
          },
          availableSymbols,
        );
      }),
    );
  }, [availableSymbols]);

  const handleAddButtonsPage = useCallback(() => {
    if (settingsButtonPageCount >= MAX_TRACKER_BUTTON_PAGES) {
      return;
    }

    const nextPageIndex = settingsButtonPageCount;
    const nextPageButtons = createTrackerButtonsForPage(nextPageIndex, availableSymbols);
    setSettingsButtonsDraft((currentButtons) =>
      [...sortTrackerButtons(currentButtons), ...nextPageButtons].map((button, index) => ({
        ...button,
        position: index,
      })),
    );
    setTrackerPageIndex(nextPageIndex);
    setSelectedButtonId(nextPageButtons[0]?.id ?? selectedButtonId);
  }, [availableSymbols, selectedButtonId, settingsButtonPageCount]);

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
          return nextButtons[0]?.id ?? 'bottle';
        });
      }

      if (showSuccessToast) {
        addToast('Buttons saved', 'success');
      }
    } catch (error) {
      if (latestButtonsPayloadRef.current === payloadKey) {
        setButtonsSaveError('Failed to save changes');
        addToast('Failed to save buttons', 'error');
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
  }, [authHeaders, handleSaveButtons, serializedSettingsButtonsDraft, settingsButtonsDraft]);

  const handleUndoPendingLog = useCallback(async () => {
    if (!activePendingLog || !authHeaders) {
      return;
    }

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
        share_emails: parseEmails(settingsShareEmails),
      },
      { headers: authHeaders },
    );
    setAccount(response.data);
    return response.data;
  };

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
    try {
      await finalizePendingEvent(inputValue.trim() || undefined);
      if (inputValue.trim()) {
        addToast('Note saved', 'success');
      }
      if (account && !account.calendar_connected) {
        addToast('Saved locally. Enable calendar sync in Settings when ready.', 'info');
      }
      resetPendingInput();
      await refreshAccount();
    } catch (error) {
      addToast('Failed to sync event', 'error');
      console.error('Finalize event error:', error);
    }
  }, [account, addToast, finalizePendingEvent, inputValue, refreshAccount, resetPendingInput]);

  const handleInputDismiss = useCallback(async () => {
    try {
      await finalizePendingEvent();
      if (account && !account.calendar_connected) {
        addToast('Saved locally. Enable calendar sync in Settings when ready.', 'info');
      }
      resetPendingInput();
      await refreshAccount();
    } catch (error) {
      addToast('Failed to sync event', 'error');
      console.error('Finalize event error:', error);
    }
  }, [account, addToast, finalizePendingEvent, refreshAccount, resetPendingInput]);

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

  if (authLoading) {
    return <div className="min-h-screen grid place-items-center bg-slate-50 text-slate-700">Loading…</div>;
  }

  if (!account) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 px-6 py-10">
        <div className="max-w-md mx-auto bg-white dark:bg-slate-900 rounded-3xl shadow-xl border border-slate-200 dark:border-slate-800 p-6 space-y-6">
          <div className="space-y-2 text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-sm font-semibold">
              <ShieldCheck size={16} />
              Household sign-in
            </div>
            <h1 className="text-3xl font-bold">Baby Tracker</h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">
              Create a household account to keep events and calendars separated.
            </p>
          </div>

          <div className="flex rounded-2xl bg-slate-100 dark:bg-slate-800 p-1">
            <button
              className={clsx('flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition', authMode === 'login' ? 'bg-white dark:bg-slate-700 shadow text-slate-900 dark:text-white' : 'text-slate-500')}
              onClick={() => setAuthMode('login')}
            >
              Sign in
            </button>
            <button
              className={clsx('flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition', authMode === 'register' ? 'bg-white dark:bg-slate-700 shadow text-slate-900 dark:text-white' : 'text-slate-500')}
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
              className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500"
            />
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password"
              className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500"
            />
            {authMode === 'register' && (
              <input
                value={registerBabyName}
                onChange={(event) => setRegisterBabyName(event.target.value)}
                placeholder="Baby name (optional)"
                className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500"
              />
            )}
            <button
              onClick={() => void handleAuthSubmit()}
              disabled={isBusy}
              className="w-full rounded-2xl bg-blue-600 text-white font-semibold px-4 py-3 hover:bg-blue-700 disabled:opacity-60"
            >
              {isBusy ? 'Working…' : authMode === 'register' ? 'Create household' : 'Sign in'}
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
      </div>
    );
  }

  return (
    <div className="flex min-h-screen min-h-[100dvh] flex-col bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 font-sans selection:bg-blue-100 dark:selection:bg-blue-900">
      <header className="sticky top-0 inset-x-0 shrink-0 bg-white/85 dark:bg-slate-900/85 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 z-10 px-4 py-3">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent">Baby Tracker</h1>
              {displayedTrackerPageCount > 1 && (
                <div className="inline-flex items-center gap-1">
                  {Array.from({ length: displayedTrackerPageCount }, (_, pageIndex) => (
                    <button
                      key={pageIndex}
                      type="button"
                      onClick={() => setTrackerPageIndex(pageIndex)}
                      className={clsx(
                        'flex h-7 w-7 items-center justify-center rounded-lg border text-[11px] font-bold transition',
                        trackerPageIndex === pageIndex
                          ? 'border-blue-500 bg-blue-50 text-blue-700 dark:border-blue-400 dark:bg-blue-950/30 dark:text-blue-300'
                          : 'border-slate-200 bg-white text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400',
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
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {account.baby_name ? `${account.baby_name}'s household` : `${account.username}'s household`}
              </p>
              <button
                type="button"
                onClick={() => {
                  setSettingsTab('calendar');
                  setActiveView('settings');
                }}
                className={clsx(
                  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold transition hover:opacity-90',
                  account.calendar_connected
                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                    : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
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
              className="p-2 rounded-xl bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700"
              aria-label="Toggle settings"
            >
              {activeView === 'tracker' ? <Settings size={18} /> : <X size={18} />}
            </button>
            <button
              onClick={() => void handleLogout()}
              className="p-2 rounded-xl bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700"
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
            <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-lg p-6 space-y-5">
              <div>
                <h2 className="text-xl font-bold">Settings</h2>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                  Manage your household calendar and the tracked button pages on the main grid.
                </p>
              </div>
              <div className="flex rounded-2xl bg-slate-100 dark:bg-slate-800 p-1">
                <button
                  onClick={() => setSettingsTab('calendar')}
                  className={clsx(
                    'flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition',
                    settingsTab === 'calendar'
                      ? 'bg-white dark:bg-slate-700 shadow text-slate-900 dark:text-white'
                      : 'text-slate-500 dark:text-slate-400',
                  )}
                >
                  Calendar
                </button>
                <button
                  onClick={() => setSettingsTab('buttons')}
                  className={clsx(
                    'flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition',
                    settingsTab === 'buttons'
                      ? 'bg-white dark:bg-slate-700 shadow text-slate-900 dark:text-white'
                      : 'text-slate-500 dark:text-slate-400',
                  )}
                >
                  Buttons
                </button>
              </div>

              {settingsTab === 'calendar' ? (
                <>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-semibold mb-2">Baby name</label>
                      <input
                        value={settingsBabyName}
                        onChange={(event) => setSettingsBabyName(event.target.value)}
                        placeholder="Baby name"
                        className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold mb-2">Share with Gmail addresses</label>
                      <textarea
                        value={settingsShareEmails}
                        onChange={(event) => setSettingsShareEmails(event.target.value)}
                        placeholder="mom@example.com, dad@example.com"
                        rows={4}
                        className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                        Enable sync will save the current baby name and share-email edits automatically first.
                      </p>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 dark:border-slate-700 p-4 bg-slate-50 dark:bg-slate-800/50 space-y-2 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-semibold">Sync status</span>
                      <span className={clsx('px-3 py-1 rounded-full text-xs font-semibold', account.calendar_connected ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300')}>
                        {account.calendar_connected ? 'Connected' : 'Local only'}
                      </span>
                    </div>
                    {account.google_calendar_summary && <p>Calendar: {account.google_calendar_summary}</p>}
                    {account.calendar_url && (
                      <a href={account.calendar_url} target="_blank" rel="noreferrer" className="text-blue-600 dark:text-blue-400 underline">
                        Open in Google Calendar
                      </a>
                    )}
                    <p className="text-slate-500 dark:text-slate-400">
                      {account.service_managed_calendar
                        ? 'This calendar is owned by the service account and shared back to your saved emails.'
                        : account.calendar_connected
                          ? 'You are still linked to the legacy shared calendar. Enabling sync will provision your own household calendar.'
                          : 'Provisioning creates a service-account-owned calendar for this household.'}
                    </p>
                    {account.google_last_synced_at && (
                      <p className="text-slate-500 dark:text-slate-400">
                        Last Google pull sync: {new Date(account.google_last_synced_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                      </p>
                    )}
                  </div>

                  <div className="grid gap-3 sm:grid-cols-3">
                    <button
                      onClick={() => void handleSaveSettings()}
                      disabled={isBusy}
                      className="rounded-2xl bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 font-semibold px-4 py-3 disabled:opacity-60"
                    >
                      Save settings
                    </button>
                    <button
                      onClick={() => void handleEnableSync()}
                      disabled={isBusy}
                      className="rounded-2xl bg-blue-600 text-white font-semibold px-4 py-3 disabled:opacity-60"
                    >
                      Enable sync
                    </button>
                    <button
                      onClick={() => void handleReshare()}
                      disabled={isBusy}
                      className="rounded-2xl bg-emerald-600 text-white font-semibold px-4 py-3 disabled:opacity-60"
                    >
                      Re-share calendar
                    </button>
                  </div>

                  <div className="rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 p-4 space-y-3">
                    <div>
                      <h3 className="text-sm font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Quick tools</h3>
                      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                        Handy cleanup and visualization shortcuts scoped only to this signed-in household.
                      </p>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <button
                        onClick={() => void handleClearToday()}
                        disabled={isBusy}
                        className="rounded-2xl bg-rose-600 text-white font-semibold px-4 py-3 disabled:opacity-60"
                      >
                        Delete today's events
                      </button>
                      <button
                        onClick={() => void handleSimulateDay()}
                        disabled={isBusy || !account.calendar_connected}
                        className="rounded-2xl bg-violet-600 text-white font-semibold px-4 py-3 disabled:opacity-60"
                      >
                        Simulate sample day
                      </button>
                      <button
                        onClick={() => void handleForceSyncFromGoogle()}
                        disabled={isBusy || !account.calendar_connected}
                        className="rounded-2xl bg-violet-700 text-white font-semibold px-4 py-3 disabled:opacity-60"
                      >
                        Force sync now
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <div className="space-y-4">
                  <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 p-4">
                    <h3 className="text-sm font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Tracked buttons</h3>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                      Edit one page at a time. Drag to reorder and click a button to edit its label or icon below. Changes save automatically.
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="inline-flex rounded-2xl bg-slate-100 p-1 dark:bg-slate-800">
                      {Array.from({ length: settingsButtonPageCount }, (_, pageIndex) => (
                        <button
                          key={pageIndex}
                          type="button"
                          onClick={() => setTrackerPageIndex(pageIndex)}
                          className={clsx(
                            'flex h-9 w-9 items-center justify-center rounded-xl text-sm font-semibold transition',
                            trackerPageIndex === pageIndex
                              ? 'bg-white text-slate-900 shadow dark:bg-slate-700 dark:text-white'
                              : 'text-slate-500 dark:text-slate-400',
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
                        disabled={settingsButtonPageCount >= MAX_TRACKER_BUTTON_PAGES}
                        className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white dark:bg-slate-100 dark:text-slate-900"
                      >
                        Add page
                      </button>
                      <button
                        type="button"
                        onClick={handleDeleteButtonsPage}
                        disabled={settingsButtonPageCount <= 1}
                        className="rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300"
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
                              isSelected={button.id === selectedDraftButton?.id}
                              onSelect={() => setSelectedButtonId(button.id)}
                            />
                          ))}
                        </SortableContext>
                      </div>
                    </DndContext>

                    {selectedDraftButton && (
                      <div className="space-y-4 rounded-2xl border border-slate-200 dark:border-slate-700 p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <h3 className="font-semibold">{selectedDraftButton.label}</h3>
                            <p className="text-sm text-slate-500 dark:text-slate-400">
                              Calendar preview: {selectedDraftButton.title}
                            </p>
                          </div>
                          <div className={clsx('flex h-14 w-14 items-center justify-center rounded-2xl shadow-md', getTrackerButtonColorClass(selectedDraftButton.color_key))}>
                            {createElement(getTrackerButtonIcon(selectedDraftButton.icon_key), {
                              size: 24,
                              className: 'text-white',
                              strokeWidth: 2.4,
                            })}
                          </div>
                        </div>

                        <div>
                          <label className="mb-2 block text-sm font-semibold">Button label</label>
                          <input
                            value={selectedDraftButton.label}
                            onChange={(event) => updateDraftButton(selectedDraftButton.id, { label: event.target.value })}
                            maxLength={24}
                            placeholder="Button label"
                            className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500"
                          />
                          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                            Keep it short so it fits cleanly on the main grid.
                          </p>
                        </div>

                        <div>
                          <label className="mb-2 block text-sm font-semibold">Search symbols</label>
                          <input
                            value={symbolSearch}
                            onChange={(event) => setSymbolSearch(event.target.value)}
                            placeholder="Search work, sleep, food, health..."
                            className="w-full rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>

                        <div className="grid grid-cols-4 gap-2 sm:grid-cols-5 md:grid-cols-6">
                          {filteredSymbols.map((symbol) => {
                            const isSelected = symbol.key === selectedDraftButton.icon_key;

                            return (
                              <button
                                key={symbol.key}
                                type="button"
                                onClick={() => updateDraftButton(selectedDraftButton.id, { icon_key: symbol.key })}
                                className={clsx(
                                  'flex aspect-square items-center justify-center rounded-2xl border p-3 transition',
                                  isSelected
                                    ? 'border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-950/30'
                                    : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800/40 dark:hover:border-slate-600',
                                )}
                                title={symbol.label}
                                aria-label={symbol.label}
                              >
                                {createElement(getTrackerButtonIcon(symbol.key), { size: 20 })}
                              </button>
                            );
                          })}
                        </div>

                        {filteredSymbols.length === 0 && (
                          <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-3 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                            No symbols match that search yet.
                          </p>
                        )}

                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-800/40">
                          <p className={clsx('text-slate-500 dark:text-slate-400', buttonsSaveError && 'text-rose-600 dark:text-rose-400')}>
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
                  </div>
                </div>
              )}
            </div>
          </section>
        ) : (
          <section className="flex flex-1 min-h-0 flex-col gap-3 overflow-y-auto overscroll-contain pb-2">
            <div className="shrink-0 space-y-2 text-center">
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400">What's happening right now?</p>

              {showInteractionTip && (
                <div className="mx-auto flex max-w-md items-center gap-2 rounded-2xl border border-blue-200/80 bg-blue-50/80 px-3 py-2 text-left shadow-sm dark:border-blue-800 dark:bg-blue-950/30">
                  <div className="rounded-xl bg-blue-100 p-1.5 text-blue-600 dark:bg-blue-900/40 dark:text-blue-300">
                    <HelpCircle size={14} />
                  </div>
                  <p className="min-w-0 flex-1 text-xs text-slate-600 dark:text-slate-300">
                    Tap to log. Hold to start or stop a timer.
                  </p>
                  <button
                    onClick={hideInteractionTip}
                    className="rounded-xl bg-white/90 px-2.5 py-1.5 text-[11px] font-semibold text-blue-700 shadow-sm ring-1 ring-blue-200 transition hover:bg-white dark:bg-slate-900/70 dark:text-blue-300 dark:ring-blue-800"
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
            'fixed inset-0 z-50 flex items-end justify-center bg-slate-950/10 px-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] pt-6 transition-all duration-300',
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
              'w-full max-w-sm rounded-3xl border border-slate-100 bg-white p-4 shadow-2xl ring-1 ring-black/5 transition-transform duration-500 ease-spring dark:border-slate-700 dark:bg-slate-800',
              activePendingLog ? 'translate-y-0' : 'translate-y-[120%]',
            )}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">Add a note?</p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{pendingActivityLabel} · auto-skip {Math.floor(NOTE_SHEET_AUTO_DISMISS_MS / 1000)}s</p>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => void handleUndoPendingLog()}
                  className="rounded-xl p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-100"
                  aria-label="Undo event"
                  title="Undo event"
                >
                  <Undo2 size={16} />
                </button>
                <button
                  onClick={() => void handleInputDismiss()}
                  className="rounded-xl px-2.5 py-2 text-sm font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-100"
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
                className="min-w-0 flex-1 bg-slate-100 dark:bg-slate-900 border-0 rounded-xl px-4 py-3 text-base focus:ring-2 focus:ring-blue-500 outline-none placeholder:text-slate-400"
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
                className="shrink-0 rounded-xl bg-blue-600 p-3 text-white transition-all hover:bg-blue-700 active:scale-95"
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
    </div>
  );
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}
