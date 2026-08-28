import { useState, useRef, useCallback, type ReactNode } from 'react';

interface TooltipProps {
  content: string;
  children: ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
}

export function Tooltip({ content, children, side = 'right' }: TooltipProps) {
  const [show, setShow] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onEnter = useCallback(() => {
    timer.current = setTimeout(() => setShow(true), 400);
  }, []);

  const onLeave = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setShow(false);
  }, []);

  const pos =
    side === 'top'
      ? 'bottom-full left-1/2 -translate-x-1/2 mb-1.5'
      : side === 'bottom'
        ? 'top-full left-1/2 -translate-x-1/2 mt-1.5'
        : side === 'left'
          ? 'right-full top-1/2 -translate-y-1/2 mr-1.5'
          : 'left-full top-1/2 -translate-y-1/2 ml-1.5';

  return (
    <span className="relative inline-flex" onMouseEnter={onEnter} onMouseLeave={onLeave}>
      {children}
      {show && (
        <span
          className={`absolute z-50 ${pos} whitespace-nowrap px-2 py-1 text-2xs font-medium text-ink-100 bg-ink-700 border border-ink-600 animate-fade-in pointer-events-none`}
        >
          {content}
        </span>
      )}
    </span>
  );
}
