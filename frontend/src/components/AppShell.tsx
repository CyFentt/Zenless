import { type ReactNode, Suspense } from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex h-screen flex-col bg-ink-950 overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <main className="flex-1 overflow-hidden min-h-0">
          <Suspense fallback={<ShellLoader />}>
            {children}
          </Suspense>
        </main>
      </div>
    </div>
  );
}

function ShellLoader() {
  return (
    <div className="flex h-full items-center justify-center bg-ink-950" aria-label="Loading workspace">
      <div className="relative flex h-16 w-16 items-center justify-center">
        <span className="absolute inset-0 border border-ink-650 animate-loader-frame" />
        <span className="absolute inset-2 border border-ink-400 animate-loader-frame-reverse" />
        <span className="text-2xs tracking-[0.2em] text-ink-0 translate-x-[0.1em]">Z</span>
      </div>
    </div>
  );
}
