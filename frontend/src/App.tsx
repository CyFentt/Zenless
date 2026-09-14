import { lazy } from 'react';
import { useStore } from '@/store';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { AppShell } from '@/components/AppShell';
import { SplashScreen } from '@/features/boot/SplashScreen';
import { AppRuntime } from '@/runtime/AppRuntime';

const ChatPage = lazy(() => import('@/features/chat/ChatPage').then((m) => ({ default: m.ChatPage })));
const BuildPage = lazy(() => import('@/features/build/BuildPage').then((m) => ({ default: m.BuildPage })));
const VisualPage = lazy(() => import('@/features/visual/VisualPage').then((m) => ({ default: m.VisualPage })));
const StudioPage = lazy(() => import('@/features/studio/StudioPage').then((m) => ({ default: m.StudioPage })));
const TestPage = lazy(() => import('@/features/test/TestPage').then((m) => ({ default: m.TestPage })));
const LogsPage = lazy(() => import('@/features/logs/LogsPage').then((m) => ({ default: m.LogsPage })));

function PageRouter() {
  const activePage = useStore((s) => s.activePage);

  switch (activePage) {
    case 'chat': return <ChatPage />;
    case 'build': return <BuildPage />;
    case 'visual': return <VisualPage />;
    case 'studio': return <StudioPage />;
    case 'test': return <TestPage />;
    case 'logs': return <LogsPage />;
    case 'settings': return <LogsPage />;
    default: return <ChatPage />;
  }
}

function App() {
  const booted = useStore((s) => s.booted);

  return (
    <ErrorBoundary>
      <AppRuntime />
      {booted ? (
        <AppShell>
          <PageRouter />
        </AppShell>
      ) : <SplashScreen />}
    </ErrorBoundary>
  );
}

export default App;
