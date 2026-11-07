import { useRef } from 'react';
import type { HTMLAttributes } from 'react';
import { quarterAtPosition } from './forecastChart';

export function useQuarterInspection(count: number, selected: number, onSelect: (index: number) => void): HTMLAttributes<HTMLDivElement> {
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  function inspect(x: number, y: number, target: HTMLDivElement) {
    const box = target.getBoundingClientRect();
    const index = quarterAtPosition(x - box.left, y - box.top, Math.round(box.width), Math.round(box.height), count);
    if (index !== null && index !== selected) onSelect(index);
  }
  return {
    onMouseMove: (event) => inspect(event.clientX, event.clientY, event.currentTarget),
    onClick: (event) => inspect(event.clientX, event.clientY, event.currentTarget),
    onTouchStart: (event) => { const touch = event.touches[0]; touchStart.current = touch ? { x: touch.clientX, y: touch.clientY } : null; },
    onTouchCancel: () => { touchStart.current = null; },
    onTouchEnd: (event) => {
      const touch = event.changedTouches[0];
      const start = touchStart.current;
      touchStart.current = null;
      if (touch && start && Math.hypot(touch.clientX - start.x, touch.clientY - start.y) <= 8) inspect(touch.clientX, touch.clientY, event.currentTarget);
    },
    onKeyDown: (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? count - 1
        : Math.max(0, Math.min(count - 1, selected + (event.key === 'ArrowRight' ? 1 : -1)));
      if (next !== selected) onSelect(next);
    },
  };
}
