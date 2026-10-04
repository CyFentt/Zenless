import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RealZenlessSocket } from '@/services/websocket/socket';

class TestSocket {
  static instances: TestSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  close = vi.fn();
  constructor(readonly url: string) { TestSocket.instances.push(this); }
}

beforeEach(() => {
  vi.useFakeTimers();
  TestSocket.instances = [];
  vi.stubGlobal('WebSocket', TestSocket);
  vi.stubGlobal('localStorage', { getItem: () => 'session token' });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('WebSocket lifecycle', () => {
  it('preserves query parameters and appends the websocket path before the query', () => {
    const socket = new RealZenlessSocket('ws://127.0.0.1:8000/bridge?mode=desktop');
    socket.connect();
    const url = new URL(TestSocket.instances[0].url);
    expect(url.pathname).toBe('/bridge/ws');
    expect(url.searchParams.get('mode')).toBe('desktop');
    expect(url.searchParams.get('token')).toBe('session token');
    socket.disconnect();
  });

  it('does not open duplicate connections while a reconnect is pending', () => {
    const socket = new RealZenlessSocket('ws://127.0.0.1:8000');
    socket.connect();
    TestSocket.instances[0].onclose?.();
    vi.advanceTimersByTime(2000);
    socket.connect();
    expect(TestSocket.instances).toHaveLength(2);
    socket.disconnect();
  });

  it('ignores stale callbacks from a replaced socket', () => {
    const socket = new RealZenlessSocket('ws://127.0.0.1:8000');
    const events = vi.fn();
    socket.on('event', events);
    socket.connect();
    const old = TestSocket.instances[0];
    old.onclose?.();
    vi.advanceTimersByTime(2000);
    const current = TestSocket.instances[1];
    current.onopen?.();
    old.onclose?.();
    old.onerror?.();
    old.onmessage?.({ data: '{"type":"BOOT_COMPLETE","data":{}}' });
    expect(socket.getStatus()).toBe('CONNECTED');
    expect(current.close).not.toHaveBeenCalled();
    expect(events).not.toHaveBeenCalled();
    socket.disconnect();
    expect(current.onopen).toBeNull();
    expect(current.onmessage).toBeNull();
  });
});
