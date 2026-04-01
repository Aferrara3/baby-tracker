import { useRef, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';

interface ActivityButtonProps {
  activity: {
    id: string;
    icon: LucideIcon;
    label: string;
    colorClass: string;
  };
  isRunning: boolean;
  onTap: () => void;
  onLongPress: () => void;
}

export default function ActivityButton({
  activity,
  isRunning,
  onTap,
  onLongPress,
}: ActivityButtonProps) {
  const [isPressed, setIsPressed] = useState(false);
  const pressTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [timerDuration, setTimerDuration] = useState(0);

  const Icon = activity.icon;

  useEffect(() => {
    if (!isRunning) {
      return undefined;
    }

    const interval = setInterval(() => {
      setTimerDuration((value) => value + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, [isRunning]);

  const startPress = () => {
    setIsPressed(true);
    pressTimeoutRef.current = setTimeout(() => {
      onLongPress();
      setIsPressed(false);
    }, 600);
  };

  const endPress = (shouldTap: boolean) => {
    if (pressTimeoutRef.current) {
      clearTimeout(pressTimeoutRef.current);
      pressTimeoutRef.current = null;
    }
    if (isPressed && shouldTap) {
      onTap();
    }
    setIsPressed(false);
  };

  const formatTime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="flex flex-col items-center gap-3">
      <button
        onMouseDown={startPress}
        onMouseUp={() => endPress(true)}
        onMouseLeave={() => endPress(false)}
        onTouchStart={(e) => {
          e.preventDefault(); 
          startPress();
        }}
        onTouchEnd={(e) => {
          e.preventDefault();
          endPress(true);
        }}
        className={clsx(
          'relative w-20 h-20 md:w-24 md:h-24 rounded-2xl flex items-center justify-center transition-all duration-300',
          'shadow-lg hover:shadow-xl active:scale-95',
          activity.colorClass,
          isPressed ? 'scale-90 brightness-90' : 'hover:-translate-y-1',
          isRunning && 'ring-4 ring-offset-2 ring-blue-400 dark:ring-blue-500 animate-pulse'
        )}
      >
        <Icon 
          size={32} 
          className="text-white drop-shadow-sm" 
          strokeWidth={2.5}
        />
        {isRunning && (
          <div className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full border-2 border-white animate-ping" />
        )}
      </button>

      <div className="flex flex-col items-center">
        <span className="text-xs md:text-sm font-bold text-slate-700 dark:text-slate-200 tracking-wide uppercase">
          {activity.label}
        </span>
        {isRunning && (
          <span className="text-xs font-mono font-medium text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/30 px-2 py-0.5 rounded-full mt-1">
            {formatTime(timerDuration)}
          </span>
        )}
      </div>
    </div>
  );
}
