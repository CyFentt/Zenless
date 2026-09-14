import { useEffect } from 'react';
import { getApi, getSocket } from '@/services';
import { ApplicationRuntime } from '@/runtime/ApplicationRuntime';
import { useStore } from '@/store';

export function AppRuntime() {
  useEffect(() => {
    const runtime = new ApplicationRuntime(getApi(), getSocket());
    const selectNativeJob = (event: Event) => {
      if (!(event instanceof CustomEvent) || typeof event.detail !== 'string') return;
      useStore.getState().setCurrentJobId(event.detail || null);
      useStore.getState().setActivePage('chat');
    };
    window.addEventListener('zenless-native-selection', selectNativeJob);
    const selectNativeWorkspace = (event: Event) => {
      if (!(event instanceof CustomEvent) || !['chat', 'build', 'visual', 'studio', 'test', 'logs'].includes(event.detail)) return;
      useStore.getState().setActivePage(event.detail);
    };
    window.addEventListener('zenless-native-workspace', selectNativeWorkspace);
    void runtime.start();
    return () => {
      window.removeEventListener('zenless-native-selection', selectNativeJob);
      window.removeEventListener('zenless-native-workspace', selectNativeWorkspace);
      runtime.stop();
    };
  }, []);
  return null;
}
