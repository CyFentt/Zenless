import { type ReactNode, useEffect } from 'react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  width?: string;
}

export function Modal({ open, onClose, title, children, width = 'w-96' }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/70" onClick={onClose} />
      <div className={`relative ${width} bg-ink-900 border border-ink-600 animate-slide-up`}>
        {title && (
          <div className="flex items-center justify-between px-4 h-10 border-b border-ink-600">
            <span className="text-xs font-medium uppercase tracking-wider text-ink-0">{title}</span>
            <button onClick={onClose} className="text-ink-300 hover:text-ink-0 text-xs" aria-label="Close">✕</button>
          </div>
        )}
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  side?: 'left' | 'right';
  width?: string;
}

export function Drawer({ open, onClose, title, children, side = 'right', width = 'w-80' }: DrawerProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 animate-fade-in" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className={`absolute top-0 bottom-0 ${side === 'right' ? 'right-0' : 'left-0'} ${width} bg-ink-900 border-${side === 'right' ? 'l' : 'r'} border-ink-600 animate-slide-right flex flex-col`}>
        {title && (
          <div className="flex items-center justify-between px-4 h-10 border-b border-ink-600 shrink-0">
            <span className="text-xs font-medium uppercase tracking-wider text-ink-0">{title}</span>
            <button onClick={onClose} className="text-ink-300 hover:text-ink-0 text-xs" aria-label="Close">✕</button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto scrollbar-zen p-4">{children}</div>
      </div>
    </div>
  );
}
