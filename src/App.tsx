import { lazy } from 'react';
import { useStore } from '@/store';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { AppShell } from '@/components/AppShell';
import { SplashScreen } from '@/features/boot/SplashScreen';

const HomePage = lazy(() => import('@/features/home/HomePage').then((m) => ({ default: m.HomePage })));
const ChatPage = lazy(() => import('@/features/chat/ChatPage').then((m) => ({ default: m.ChatPage })));
const BuildPage = lazy(() => import('@/features/build/BuildPage').then((m) => ({ default: m.BuildPage })));
const VisualPage = lazy(() => import('@/features/visual/VisualPage').then((m) => ({ default: m.VisualPage })));
const StudioPage = lazy(() => import('@/features/studio/StudioPage').then((m) => ({ default: m.StudioPage })));
const TestPage = lazy(() => import('@/features/test/TestPage').then((m) => ({ default: m.TestPage })));
const SettingsPage = lazy(() => import('@/features/settings/SettingsPage').then((m) => ({ default: m.SettingsPage })));

function PageRouter() {
  const activePage = useStore((s) => s.activePage);

  switch (activePage) {
    case 'home': return <HomePage />;
    case 'chat': return <ChatPage />;
    case 'build': return <BuildPage />;
    case 'visual': return <VisualPage />;
    case 'studio': return <StudioPage />;
    case 'test': return <TestPage />;
    case 'settings': return <SettingsPage />;
    default: return <HomePage />;
  }
}

function App() {
  const booted = useStore((s) => s.booted);

  if (!booted) {
    return (
      <ErrorBoundary>
        <SplashScreen />
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary>
      <AppShell>
        <PageRouter />
      </AppShell>
    </ErrorBoundary>
  );
}

export default App;
