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

describe('transport failure recovery', () => {
  afterEach(() => vi.useRealTimers());

  it.each([false, true])('keeps timeout active while reading an error=%s body', async (errorResponse) => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url, init) => Promise.resolve({
      ok: !errorResponse, status: errorResponse ? 503 : 200, headers: new Headers(),
      json: () => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))),
    })));
    const assertion = expect(new RealZenlessAPI().getStatus()).rejects.toMatchObject({ code: 'TIMEOUT' });
    await vi.advanceTimersByTimeAsync(15001);
    await assertion;
    expect(vi.getTimerCount()).toBe(0);
  });

  it('bounds the initial session request', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const assertion = expect(new RealZenlessAPI().bootstrap()).rejects.toMatchObject({ code: 'TIMEOUT' });
    await vi.advanceTimersByTimeAsync(15001);
    await assertion;
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([null, {}, { token: 42 }, { token: '' }, { token: ' ' }])('rejects invalid session %j', async (payload) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
    await expect(new RealZenlessAPI().bootstrap()).rejects.toThrow();
    expect(localStorage.getItem('rubra_token')).toBeNull();
  });

  it('reports malformed JSON and releases the timer', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{broken')));
    await expect(new RealZenlessAPI().getStatus()).rejects.toMatchObject({ code: 'INVALID_RESPONSE', status: 200 });
    expect(vi.getTimerCount()).toBe(0);
  });

  it('preserves backend error details and request identity', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Offline', code: 'STUDIO_UNAVAILABLE', details: { retry: true } }), { status: 503, headers: { 'X-Request-Id': 'server-id' } })));
    await expect(new RealZenlessAPI().getStatus()).rejects.toMatchObject({ status: 503, message: 'Offline', code: 'STUDIO_UNAVAILABLE', requestId: 'server-id', details: { retry: true } });
  });

  it('accepts no-content success without parsing JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(new RealZenlessAPI().cancelJob('job')).resolves.toBeUndefined();
  });
});
