import { useEffect } from 'react';
import { useNotices } from '@/services/notifications';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { X } from 'lucide-react';

export function Notifications() {
  const { items, remove } = useNotices();
  const reduced = useReducedMotion();
  useEffect(() => {
    if (!items.length) return;
    const timer = window.setTimeout(() => remove(items[0].id), 10000);
    return () => window.clearTimeout(timer);
  }, [items, remove]);
  return <div className="fixed bottom-5 right-5 z-[90] w-80 space-y-2" aria-live="polite">
    <AnimatePresence>
      {items.map((item) => <motion.div key={item.id} initial={{ opacity: 0, y: reduced ? 0 : 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
        className={`flex gap-3 p-4 bg-ink-900 border shadow-xl ${item.kind === 'error' ? 'border-zen-red' : 'border-ink-500'}`}>
        <p className="flex-1 text-xs text-ink-50">{item.title}</p>
        <button aria-label="Dismiss notification" onClick={() => remove(item.id)} className="text-ink-300 hover:text-white"><X size={14} /></button>
      </motion.div>)}
    </AnimatePresence>
  </div>;
}
