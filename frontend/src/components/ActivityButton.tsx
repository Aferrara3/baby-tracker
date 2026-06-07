import { useRef, useState, type CSSProperties } from 'react';
import { clsx } from 'clsx';

import TrackerSymbolIcon from './TrackerSymbolIcon';
import type { TrackerSymbolOption } from '../trackerButtons';

interface ActivityButtonProps {
  activity: {
    id: string;
    symbol?: TrackerSymbolOption;
    label: string;
    colorClass: string;
  };
  isRunning: boolean;
  runningSince: number | null;
  currentTime: number;
  onTap: () => void;
  onLongPress: () => void;
}

export default function ActivityButton({
  activity,
  isRunning,
  runningSince,
  currentTime,
  onTap,
  onLongPress,
}: ActivityButtonProps) {
  const [isPressed, setIsPressed] = useState(false);
  const pressTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const touchStartPos = useRef<{ x: number; y: number } | null>(null);

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

  const timerDuration = isRunning && runningSince
    ? Math.max(0, Math.floor((currentTime - runningSince) / 1000))
    : 0;

  return (
    <div className="flex flex-col items-center gap-2 md:gap-3">
      <button
        ref={buttonRef}
        onMouseDown={startPress}
        onMouseUp={() => endPress(true)}
        onMouseLeave={() => endPress(false)}
        onTouchStart={(e) => {
          e.preventDefault(); 
          const touch = e.touches[0];
          touchStartPos.current = { x: touch.clientX, y: touch.clientY };
          startPress();
        }}
        onTouchMove={(e) => {
          const touch = e.touches[0];
          const rect = buttonRef.current?.getBoundingClientRect();
          if (!touch || !rect) {
            return;
          }

          if (touchStartPos.current) {
            const dx = touch.clientX - touchStartPos.current.x;
            const dy = touch.clientY - touchStartPos.current.y;
            if (Math.abs(dx) > 15 || Math.abs(dy) > 15) {
              endPress(false);
            }
          }

          const isInside = touch.clientX >= rect.left && touch.clientX <= rect.right && touch.clientY >= rect.top && touch.clientY <= rect.bottom;
          if (!isInside) {
            endPress(false);
          }
        }}
        onTouchEnd={(e) => {
          e.preventDefault();
          touchStartPos.current = null;
          endPress(true);
        }}
        onTouchCancel={() => {
          touchStartPos.current = null;
          endPress(false);
        }}
        className={clsx(
          'relative h-[4.5rem] w-[4.5rem] md:h-24 md:w-24 rounded-2xl flex items-center justify-center transition-all duration-300',
          'shadow-lg hover:shadow-xl active:scale-95',
          activity.colorClass,
          isPressed ? 'scale-90 brightness-90' : 'hover:-translate-y-1',
          isRunning && 'ring-4 ring-offset-2 animate-pulse'
        )}
        style={isRunning ? ({ '--tw-ring-color': 'var(--app-ring)' } as CSSProperties) : undefined}
      >
        <TrackerSymbolIcon symbol={activity.symbol} size={32} className="text-white drop-shadow-sm" strokeWidth={2.5} />
        {isRunning && (
          <div className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full border-2 border-white animate-ping" />
        )}
      </button>

      <div className="flex flex-col items-center">
        <span className="app-text text-[11px] md:text-sm font-bold tracking-wide uppercase">
          {activity.label}
        </span>
        {isRunning && (
          <span className="app-timer-pill mt-1 rounded-full px-2 py-0.5 text-xs font-mono font-medium">
            {formatTime(timerDuration)}
          </span>
        )}
      </div>
    </div>
  );
}
