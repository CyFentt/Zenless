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

  it('reuses the same idempotency key across transport retry and pending reconciliation', async () => {
    vi.useFakeTimers();
    const calls: Array<{ key: string | null; url: string }> = [];
    const fetchMock = vi.fn()
      .mockImplementationOnce((url, init) => {
        calls.push({ key: new Headers(init.headers).get('Idempotency-Key'), url: String(url) });
        return Promise.reject(new TypeError('socket reset'));
      })
      .mockImplementationOnce((url, init) => {
        calls.push({ key: new Headers(init.headers).get('Idempotency-Key'), url: String(url) });
        return Promise.resolve(new Response(JSON.stringify({
          message: 'The idempotent operation is still running.',
          code: 'IDEMPOTENCY_PENDING',
        }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
      })
      .mockImplementationOnce((url, init) => {
        calls.push({ key: new Headers(init.headers).get('Idempotency-Key'), url: String(url) });
        return Promise.resolve(new Response(JSON.stringify({ id: 'job-1', title: 'Build' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }));
      });
    vi.stubGlobal('fetch', fetchMock);

    const pending = new RealZenlessAPI().createJob('Build');
    await vi.advanceTimersByTimeAsync(500);
    await expect(pending).resolves.toMatchObject({ id: 'job-1' });

    expect(calls).toHaveLength(3);
    expect(calls.every((entry) => entry.url === '/api/jobs')).toBe(true);
    expect(calls[0].key).toBeTruthy();
    expect(new Set(calls.map((entry) => entry.key)).size).toBe(1);
  });

  it('recovers a completed idempotent operation after the final transport failure', async () => {
    vi.useFakeTimers();
    let operationUrl = '';
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('socket reset'))
      .mockRejectedValueOnce(new TypeError('socket reset'))
      .mockRejectedValueOnce(new TypeError('socket reset'))
      .mockImplementationOnce((url) => {
        operationUrl = String(url);
        return Promise.resolve(new Response(JSON.stringify({
          state: 'complete',
          kind: 'create-job',
          resourceId: '',
          response: { id: 'job-late', title: 'Recovered build' },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
      });
    vi.stubGlobal('fetch', fetchMock);

    const pending = new RealZenlessAPI().createJob('Recovered build');
    await vi.advanceTimersByTimeAsync(1000);

    await expect(pending).resolves.toMatchObject({ id: 'job-late' });
    expect(operationUrl).toMatch(/^\/api\/operations\/create-job-/);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('surfaces an uncertain idempotent result instead of encouraging a blind resend', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('socket reset'))
      .mockRejectedValueOnce(new TypeError('socket reset'))
      .mockRejectedValueOnce(new TypeError('socket reset'))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        state: 'uncertain',
        kind: 'create-job',
        resourceId: '',
        response: {
          code: 'IDEMPOTENCY_UNCERTAIN',
          message: 'Verify Recent Tasks before repeating it.',
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    const pending = new RealZenlessAPI().createJob('Uncertain build');
    await vi.advanceTimersByTimeAsync(1000);

    await expect(pending).rejects.toMatchObject({
      code: 'IDEMPOTENCY_UNCERTAIN',
      message: 'Verify Recent Tasks before repeating it.',
    });
  });

  it('accepts no-content success without parsing JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(new RealZenlessAPI().cancelJob('job')).resolves.toBeUndefined();
  });
});
