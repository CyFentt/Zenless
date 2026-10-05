import { type ReactNode, Suspense } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { useStore } from '@/store';
import { Notifications } from './Notifications';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const page = useStore((s) => s.activePage);
  const reduced = useReducedMotion();
  return (
    <div className="flex h-screen bg-ink-950 overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <motion.main key={page} initial={{ opacity: reduced ? 1 : 0, y: reduced ? 0 : 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="flex-1 overflow-hidden min-h-0">
          <Suspense fallback={<div className="flex items-center justify-center h-full text-xs text-ink-300 uppercase tracking-wider animate-pulse-soft">Loading</div>}>
            {children}
          </Suspense>
        </motion.main>
      </div>
      <Notifications />
    </div>
  );
}
