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
    void runtime.start();
    return () => {
      window.removeEventListener('zenless-native-selection', selectNativeJob);
      runtime.stop();
    };
  }, []);
  return null;
}
