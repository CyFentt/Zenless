import { type ReactNode, Suspense } from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex h-screen bg-ink-950 overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <main className="flex-1 overflow-hidden min-h-0">
          <Suspense fallback={<div className="flex items-center justify-center h-full text-xs text-ink-300 uppercase tracking-wider animate-pulse-soft">Loading</div>}>
            {children}
          </Suspense>
        </main>
      </div>
    </div>
  );
}
