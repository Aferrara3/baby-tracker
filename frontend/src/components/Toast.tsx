import { CheckCircle, AlertCircle, InfoIcon } from 'lucide-react';
import { clsx } from 'clsx';

interface ToastProps {
  message: string;
  type: 'success' | 'error' | 'info';
}

export default function Toast({ message, type }: ToastProps) {
  const Icon = type === 'success' ? CheckCircle : type === 'error' ? AlertCircle : InfoIcon;

  return (
    <div
      className={clsx(
        'flex items-center gap-3 px-4 py-3 rounded-full border shadow-xl backdrop-blur-md',
        'animate-in slide-in-from-top-2 fade-in duration-300',
        type === 'success' && 'bg-emerald-50/90 border-emerald-200 text-emerald-700 dark:bg-emerald-900/50 dark:border-emerald-700 dark:text-emerald-100',
        type === 'error' && 'bg-red-50/90 border-red-200 text-red-700 dark:bg-red-900/50 dark:border-red-700 dark:text-red-100',
        type === 'info' && 'app-accent-soft',
      )}
      style={type === 'info' ? { borderColor: 'var(--app-accent)' } : undefined}
    >
      <Icon size={18} strokeWidth={2.5} />
      <span className="text-sm font-semibold tracking-wide">{message}</span>
    </div>
  );
}
