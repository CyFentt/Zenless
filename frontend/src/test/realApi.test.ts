import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RealZenlessAPI, setStoredToken } from '@/services/api/realApi';
import { resolveWsBase } from '@/services';

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
});

afterEach(() => {
  setStoredToken(null);
  vi.unstubAllGlobals();
});

describe('real transport defaults', () => {
  it('uses same-origin REST paths when no environment override is provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ready: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await new RealZenlessAPI().getStatus();

    expect(fetchMock).toHaveBeenCalledWith('/api/status', expect.objectContaining({ method: 'GET' }));
  });

  it('derives WebSocket origin and preserves an explicit override', () => {
    expect(resolveWsBase()).toBe(`${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`);
    expect(resolveWsBase(' ws://127.0.0.1:9000/ ')).toBe('ws://127.0.0.1:9000');
    expect(resolveWsBase()).not.toContain('8787');
  });

  it('requests a legitimate backend-managed provider login', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await new RealZenlessAPI().loginProvider('chatgpt');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/providers/chatgpt/login',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
