import { CheckCircle, AlertCircle, InfoIcon } from 'lucide-react';
import { clsx } from 'clsx';

interface ToastProps {
  message: string;
  type: 'success' | 'error' | 'info';
}

export default function Toast({ message, type }: ToastProps) {
  const typeConfig = {
    success: {
      bg: 'bg-green-50 dark:bg-green-900/30',
      border: 'border-green-200 dark:border-green-800',
      text: 'text-green-700 dark:text-green-400',
      icon: CheckCircle,
    },
    error: {
      bg: 'bg-red-50 dark:bg-red-900/30',
      border: 'border-red-200 dark:border-red-800',
      text: 'text-red-700 dark:text-red-400',
      icon: AlertCircle,
    },
    info: {
      bg: 'bg-blue-50 dark:bg-blue-900/30',
      border: 'border-blue-200 dark:border-blue-800',
      text: 'text-blue-700 dark:text-blue-400',
      icon: InfoIcon,
    },
  };

  const config = typeConfig[type];
  const Icon = config.icon;

  return (
    <div
      className={clsx(
        'flex items-center gap-3 px-4 py-3 rounded-full border shadow-xl backdrop-blur-md',
        'animate-in slide-in-from-top-2 fade-in duration-300',
        type === 'success' && 'bg-emerald-50/90 border-emerald-200 text-emerald-700 dark:bg-emerald-900/50 dark:border-emerald-700 dark:text-emerald-100',
        type === 'error' && 'bg-red-50/90 border-red-200 text-red-700 dark:bg-red-900/50 dark:border-red-700 dark:text-red-100',
        type === 'info' && 'bg-blue-50/90 border-blue-200 text-blue-700 dark:bg-blue-900/50 dark:border-blue-700 dark:text-blue-100',
      )}
    >
      <Icon size={18} strokeWidth={2.5} />
      <span className="text-sm font-semibold tracking-wide">{message}</span>
    </div>
  );
}
