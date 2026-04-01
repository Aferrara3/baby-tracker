import { useState } from 'react';
import {
  BottleWine,
  Utensils,
  Baby,
  Moon,
  User2,
  Milk,
  HelpCircle,
  X,
  Send,
  type LucideIcon,
} from 'lucide-react';
import axios from 'axios';
import ActivityButton from './components/ActivityButton';
import Toast from './components/Toast';
import { clsx } from 'clsx';

const API_BASE = 'http://localhost:8090';

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

export default function App() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [runningActivity, setRunningActivity] = useState<{ id: string; startTime: number } | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [showInput, setShowInput] = useState(false);
  const [pendingLog, setPendingLog] = useState<{ eventId: number; activityId: string; type: 'log' | 'stop' } | null>(null);

  const addToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = Date.now().toString();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  };

  const handleTap = async (activityId: string) => {
    try {
      const response = await axios.post(`${API_BASE}/events`, {
        type: activityId,
        start_time: new Date().toISOString(),
      });
      addToast('Event logged', 'success');
      setPendingLog({ eventId: response.data.id, activityId, type: 'log' });
      setShowInput(true);
    } catch (error) {
      addToast('Failed to log event', 'error');
      console.error('Error logging event:', error);
    }
  };

  const handleLongPress = async (activityId: string) => {
    if (runningActivity?.id === activityId) {
      // Stop the activity
      try {
        const response = await axios.post(`${API_BASE}/activities/stop`, {
          type: activityId,
        });
        const duration = response.data.duration_seconds;
        addToast(`Stopped (${formatDuration(duration)})`, 'success');
        setRunningActivity(null);
        setPendingLog({ eventId: response.data.event_id, activityId, type: 'stop' });
        setShowInput(true);
      } catch (error) {
        addToast('Failed to stop activity', 'error');
        console.error('Error stopping activity:', error);
      }
    } else {
      // Start the activity
      try {
        await axios.post(`${API_BASE}/activities/start`, {
          type: activityId,
        });
        setRunningActivity({
          id: activityId,
          startTime: Date.now(),
        });
        // Feedback via button state, no toast needed for start
      } catch (error) {
        addToast('Failed to start activity', 'error');
        console.error('Error starting activity:', error);
      }
    }
  };

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s}s`;
  };

  const handleInputSubmit = async () => {
    if (!pendingLog) {
      resetInput();
      return;
    }

    try {
      await axios.post(`${API_BASE}/events/${pendingLog.eventId}/finalize`, {
        details: inputValue.trim() || undefined,
      });
      if (inputValue.trim()) {
        addToast('Note saved', 'success');
      }
    } catch (error) {
      addToast('Failed to sync event', 'error');
      console.error('Error finalizing event:', error);
      return;
    }
    resetInput();
  };

  const handleInputDismiss = async () => {
    if (!pendingLog) {
      resetInput();
      return;
    }

    try {
      await axios.post(`${API_BASE}/events/${pendingLog.eventId}/finalize`, {});
    } catch (error) {
      addToast('Failed to sync event', 'error');
      console.error('Error finalizing event:', error);
      return;
    }
    resetInput();
  };

  const resetInput = () => {
    setShowInput(false);
    setPendingLog(null);
    setInputValue('');
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 font-sans selection:bg-blue-100 dark:selection:bg-blue-900">
      
      {/* Header */}
      <header className="fixed top-0 inset-x-0 h-16 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 z-10 flex items-center justify-center">
        <h1 className="text-xl font-bold bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent">
          Baby Tracker
        </h1>
      </header>

      {/* Main Content */}
      <main className="pt-24 pb-32 px-6 max-w-md mx-auto min-h-screen flex flex-col justify-center">
        
        {/* Intro Text */}
        <div className="text-center mb-10">
          <p className="text-slate-500 dark:text-slate-400 font-medium">
            What's happening right now?
          </p>
        </div>

        {/* Grid */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-10 justify-items-center">
          {ACTIVITIES.map((activity) => (
            <ActivityButton
              key={activity.id}
              activity={activity}
              isRunning={runningActivity?.id === activity.id}
              onTap={() => handleTap(activity.id)}
              onLongPress={() => handleLongPress(activity.id)}
            />
          ))}
        </div>

        {/* Floating Input Bar (Bottom Sheet style) */}
        <div className={clsx(
          "fixed inset-x-0 bottom-0 p-4 z-50 transition-transform duration-500 ease-spring",
          showInput ? "translate-y-0" : "translate-y-[120%]"
        )}>
          <div className="max-w-md mx-auto bg-white dark:bg-slate-800 rounded-3xl shadow-2xl border border-slate-100 dark:border-slate-700 p-4 ring-1 ring-black/5">
            <div className="flex items-center gap-3">
              <input
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder={`Add note for ${ACTIVITIES.find(a => a.id === pendingLog?.activityId)?.label}...`}
                className="flex-1 bg-slate-100 dark:bg-slate-900 border-0 rounded-xl px-4 py-3 text-base focus:ring-2 focus:ring-blue-500 outline-none placeholder:text-slate-400"
                 autoFocus={showInput}
                 onKeyDown={(e) => {
                   if (e.key === 'Enter') void handleInputSubmit();
                   if (e.key === 'Escape') void handleInputDismiss();
                 }}
               />
               <button
                 onClick={() => void handleInputSubmit()}
                 className="p-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 active:scale-95 transition-all"
               >
                 <Send size={20} strokeWidth={2.5} />
               </button>
               <button
                 onClick={() => void handleInputDismiss()}
                 className="p-3 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 active:scale-95 transition-all"
               >
                <X size={24} />
              </button>
            </div>
          </div>
        </div>

      </main>

      {/* Toasts - Top Center */}
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
