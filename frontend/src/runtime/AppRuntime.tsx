import { useEffect } from 'react';
import { getApi, getSocket } from '@/services';
import { ApplicationRuntime } from '@/runtime/ApplicationRuntime';

export function AppRuntime() {
  useEffect(() => {
    const runtime = new ApplicationRuntime(getApi(), getSocket());
    void runtime.start();
    return () => runtime.stop();
  }, []);
  return null;
}
