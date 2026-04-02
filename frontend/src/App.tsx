import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BottleWine,
  Utensils,
  Baby,
  Moon,
  User2,
  Milk,
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

const TOKEN_STORAGE_KEY = 'baby-tracker-auth-token';
const INTERACTION_TIP_STORAGE_KEY = 'baby-tracker-interaction-tip-hidden';
const NOTE_SHEET_AUTO_DISMISS_MS = 5000;
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

const ACTIVITIES: Activity[] = [
  { id: 'bottle', icon: BottleWine, label: 'Bottle', colorClass: 'bg-gradient-to-br from-blue-400 to-blue-600 dark:from-blue-500 dark:to-blue-700 shadow-blue-200 dark:shadow-blue-900/30' },
  { id: 'food', icon: Utensils, label: 'Food', colorClass: 'bg-gradient-to-br from-amber-400 to-amber-600 dark:from-amber-500 dark:to-amber-700 shadow-amber-200 dark:shadow-amber-900/30' },
  { id: 'diaper_pee', icon: Baby, label: 'Pee', colorClass: 'bg-gradient-to-br from-cyan-400 to-cyan-600 dark:from-cyan-500 dark:to-cyan-700 shadow-cyan-200 dark:shadow-cyan-900/30' },
  { id: 'diaper_poop', icon: Baby, label: 'Poop', colorClass: 'bg-gradient-to-br from-pink-400 to-pink-600 dark:from-pink-500 dark:to-pink-700 shadow-pink-200 dark:shadow-pink-900/30' },
  { id: 'sleep', icon: Moon, label: 'Sleep', colorClass: 'bg-gradient-to-br from-indigo-400 to-indigo-600 dark:from-indigo-500 dark:to-indigo-700 shadow-indigo-200 dark:shadow-indigo-900/30' },
  { id: 'breastfeeding', icon: User2, label: 'Nursing', colorClass: 'bg-gradient-to-br from-rose-400 to-rose-600 dark:from-rose-500 dark:to-rose-700 shadow-rose-200 dark:shadow-rose-900/30' },
  { id: 'pump', icon: Milk, label: 'Pump', colorClass: 'bg-gradient-to-br from-orange-400 to-orange-600 dark:from-orange-500 dark:to-orange-700 shadow-orange-200 dark:shadow-orange-900/30' },
  { id: 'help', icon: HelpCircle, label: 'Other', colorClass: 'bg-gradient-to-br from-slate-400 to-slate-600 dark:from-slate-500 dark:to-slate-700 shadow-slate-200 dark:shadow-slate-900/30' },
];

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
  const [settingsBabyName, setSettingsBabyName] = useState('');
  const [settingsShareEmails, setSettingsShareEmails] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [showInteractionTip, setShowInteractionTip] = useState(() => localStorage.getItem(INTERACTION_TIP_STORAGE_KEY) !== 'true');
  const autoSyncInFlightRef = useRef(false);

  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : undefined),
    [token],
  );
  const activePendingLog = pendingLogs[0] ?? null;
  const pendingActivityLabel = ACTIVITIES.find((activity) => activity.id === activePendingLog?.activityId)?.label ?? 'event';

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
  };

  const clearAuth = () => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken('');
    setAccount(null);
    setActiveView('tracker');
    setRunningActivities({});
    setPendingLogs([]);
    setInputValue('');
  };

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
        const response = await axios.get<Account>(`${API_BASE}/auth/me`, {
          headers: authHeaders,
        });
        setAccount(response.data);
        setSettingsBabyName(response.data.baby_name ?? '');
        setSettingsShareEmails(response.data.share_emails.join(', '));
      } catch {
        clearAuth();
      } finally {
        setAuthLoading(false);
      }
    };

    void fetchAccount();
  }, [authHeaders, token]);

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
          <div>
            <h1 className="text-xl font-bold bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent">Baby Tracker</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {account.baby_name ? `${account.baby_name}'s household` : `${account.username}'s household`}
              </p>
              <button
                type="button"
                onClick={() => setActiveView('settings')}
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
                <h2 className="text-xl font-bold">Calendar settings</h2>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                  Manage your household calendar, baby label, and shared Gmail addresses.
                </p>
              </div>

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
              {ACTIVITIES.map((activity) => (
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
