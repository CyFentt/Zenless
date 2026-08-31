import type { ZenlessAPI } from './types';
import { frontendDiagnostics } from '@/services/diagnostics';
import type {
  AgentInfo,
  Asset,
  BootStep,
  ChatMessage,
  ChangedFile,
  ConnectionInfo,
  ContextItem,
  Diagnostic,
  Job,
  ModelCatalog,
  ModelInfo,
  ProviderId,
  Review,
  Settings,
  StudioNode,
  StudioState,
  TaskOptions,
  TestState,
  ViewTile,
} from '@/types';

const API_BASE = (import.meta.env.VITE_ZENLESS_API_BASE?.trim() || '').replace(/\/$/, '');
const DEFAULT_TIMEOUT = 15000;

interface RequestOptions {
  method?: string;
  body?: unknown;
  timeout?: number;
  signal?: AbortSignal;
  rawBody?: BodyInit;
  idempotencyKey?: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId?: string,
    public code?: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function withTimeout(ms: number): { signal: AbortSignal; cancel: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return { signal: controller.signal, cancel: () => clearTimeout(timer) };
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const timeout = opts.timeout ?? DEFAULT_TIMEOUT;
  const { signal: timeoutSignal, cancel } = withTimeout(timeout);
  const signal = opts.signal ? mergeSignals(opts.signal, timeoutSignal) : timeoutSignal;

  const headers: Record<string, string> = {};
  if (opts.rawBody === undefined) headers['Content-Type'] = 'application/json';
  const token = getStoredToken();
  if (token) headers['X-Zenless-Token'] = token;
  const requestId = crypto.randomUUID?.() ?? `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  headers['X-Request-Id'] = requestId;
  if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.rawBody ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
      signal,
    });
  } catch (err) {
    cancel();
    const message = err instanceof DOMException && err.name === 'AbortError' ? 'Request timeout' : 'Bridge unreachable';
    frontendDiagnostics.report('error', 'api', message, undefined, undefined, { requestId, stack: err instanceof Error ? err.stack : undefined });
    throw new ApiError(0, message, requestId, err instanceof DOMException && err.name === 'AbortError' ? 'TIMEOUT' : 'UNREACHABLE');
  }
  cancel();

  const responseRequestId = res.headers.get('X-Request-Id') ?? requestId;
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    let code: string | undefined;
    let details: unknown;
    try {
      const body = (await res.json()) as { error?: string; message?: string; code?: string; details?: unknown };
      message = body.message ?? body.error ?? message;
      code = body.code;
      details = body.details;
    } catch (err) {
      frontendDiagnostics.report('warning', 'api', 'Failed to parse error response', undefined, undefined, {
        requestId: responseRequestId,
        stack: err instanceof Error ? err.stack : undefined,
      });
    }
    throw new ApiError(res.status, message, responseRequestId, code, details);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function mergeSignals(a: AbortSignal, b: AbortSignal): AbortSignal {
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  a.addEventListener('abort', onAbort, { once: true });
  b.addEventListener('abort', onAbort, { once: true });
  return controller.signal;
}

const TOKEN_KEY = 'zenless_token';
function operationKey(scope: string): string {
  const id = crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
  return `${scope}-${id}`;
}

function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch (err) {
    frontendDiagnostics.report('warning', 'storage', 'Unable to read local session token', undefined, undefined, {
      stack: err instanceof Error ? err.stack : undefined,
    });
    return null;
  }
}

export function setStoredToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (err) {
    frontendDiagnostics.report('warning', 'storage', 'Unable to update local session token', undefined, undefined, {
      stack: err instanceof Error ? err.stack : undefined,
    });
  }
}


async function ensureSessionToken(force = false): Promise<void> {
  if (!force && getStoredToken()) return;
  try {
    const response = await fetch(`${API_BASE}/api/session`, { method: 'GET' });
    if (!response.ok) throw new Error(`Session bootstrap failed (${response.status})`);
    const payload = (await response.json()) as { token?: string };
    if (!payload.token) throw new Error('Session bootstrap returned no token');
    setStoredToken(payload.token);
  } catch (error) {
    frontendDiagnostics.capture(error, 'api', 'Failed to establish Bridge session');
    throw error;
  }
}

export class RealZenlessAPI implements ZenlessAPI {
  async bootstrap(): Promise<{ steps: BootStep[] }> { await ensureSessionToken(true); return request('/api/bootstrap', { timeout: 30000 }); }
  getStatus(): Promise<{ ready: boolean }> { return request('/api/status'); }
  getConnections(): Promise<ConnectionInfo> { return request('/api/connections'); }
  getAgents(): Promise<AgentInfo[]> { return request('/api/agents'); }
  loginProvider(provider: ProviderId): Promise<{ ok: boolean }> {
    return request(`/api/providers/${encodeURIComponent(provider)}/login`, { method: 'POST', timeout: 30000 });
  }

  getJobs(): Promise<Job[]> { return request('/api/jobs'); }
  getJob(id: string): Promise<Job> { return request(`/api/jobs/${encodeURIComponent(id)}`); }
  createJob(title: string, options?: Partial<TaskOptions>): Promise<Job> {
    return request('/api/jobs', { method: 'POST', body: { title, options }, idempotencyKey: operationKey('create-job') });
  }
  pauseJob(id: string): Promise<Job> { return request(`/api/jobs/${encodeURIComponent(id)}/pause`, { method: 'POST' }); }
  resumeJob(id: string): Promise<Job> { return request(`/api/jobs/${encodeURIComponent(id)}/resume`, { method: 'POST' }); }
  cancelJob(id: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  getMessages(jobId: string): Promise<ChatMessage[]> { return request(`/api/jobs/${encodeURIComponent(jobId)}/messages`); }
  getTimeline(jobId: string): Promise<import('./types').JobTimelineSnapshot> { return request(`/api/jobs/${encodeURIComponent(jobId)}/timeline`); }

  sendMessage(content: string, jobId?: string, attachments: File[] = [], options?: TaskOptions): Promise<{ messageId: string; jobId?: string }> {
    const idempotencyKey = operationKey('send-chat');
    if (attachments.length === 0) return request('/api/chat', { method: 'POST', body: { content, jobId, options }, idempotencyKey });
    const form = new FormData();
    form.append('content', content);
    if (jobId) form.append('jobId', jobId);
    if (options) form.append('options', JSON.stringify(options));
    attachments.forEach((file) => form.append('attachments', file, file.name));
    return request('/api/chat', { method: 'POST', rawBody: form, timeout: 60000, idempotencyKey });
  }
  cancelGeneration(jobId: string): Promise<{ ok: boolean }> { return request(`/api/chat/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }); }

  getContext(jobId: string): Promise<ContextItem[]> { return request(`/api/jobs/${encodeURIComponent(jobId)}/context`); }
  refreshContext(jobId: string): Promise<ContextItem[]> { return request(`/api/jobs/${encodeURIComponent(jobId)}/context/refresh`, { method: 'POST' }); }
  includeContext(itemId: string): Promise<{ ok: boolean }> { return request(`/api/context/${encodeURIComponent(itemId)}/include`, { method: 'POST' }); }
  excludeContext(itemId: string): Promise<{ ok: boolean }> { return request(`/api/context/${encodeURIComponent(itemId)}/exclude`, { method: 'POST' }); }
  lockContext(itemId: string): Promise<{ ok: boolean }> { return request(`/api/context/${encodeURIComponent(itemId)}/lock`, { method: 'POST' }); }
  unlockContext(itemId: string): Promise<{ ok: boolean }> { return request(`/api/context/${encodeURIComponent(itemId)}/unlock`, { method: 'POST' }); }
  inspectContext(itemId: string): Promise<ContextItem> { return request(`/api/context/${encodeURIComponent(itemId)}`); }

  getChanges(jobId: string): Promise<ChangedFile[]> { return request(`/api/jobs/${encodeURIComponent(jobId)}/changes`); }
  getReview(jobId: string): Promise<Review> { return request(`/api/jobs/${encodeURIComponent(jobId)}/review`); }
  approveChanges(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/changes/approve`, { method: 'POST' }); }
  rejectChanges(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/changes/reject`, { method: 'POST' }); }
  editChanges(jobId: string, fileId: string, content: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${encodeURIComponent(jobId)}/changes/${encodeURIComponent(fileId)}`, { method: 'PUT', body: { content } });
  }

  getVisual(jobId: string): Promise<{ views: ViewTile[]; concept: { version: number; status: string; prompt?: string } }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/visual`); }
  approveVisual(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/visual/approve`, { method: 'POST' }); }
  editConcept(jobId: string, prompt: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/visual/concept`, { method: 'PUT', body: { prompt } }); }
  regenerateVisual(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/visual/regenerate`, { method: 'POST' }); }
  regenerateView(jobId: string, view: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/visual/views/${encodeURIComponent(view)}/regenerate`, { method: 'POST' }); }

  getModel(jobId: string): Promise<ModelInfo> { return request(`/api/jobs/${encodeURIComponent(jobId)}/model`); }
  approveModel(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/model/approve`, { method: 'POST' }); }
  regenerateGeometry(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/model/geometry/regenerate`, { method: 'POST' }); }
  regenerateTexture(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/model/texture/regenerate`, { method: 'POST' }); }

  getAssets(): Promise<Asset[]> { return request('/api/assets'); }

  getStudioState(): Promise<{ state: StudioState }> { return request('/api/studio/state'); }
  getStudioTree(): Promise<StudioNode[]> { return request('/api/studio/tree'); }
  searchStudio(query: string): Promise<StudioNode[]> { return request(`/api/studio/search?q=${encodeURIComponent(query)}`); }
  refreshStudio(): Promise<{ ok: boolean }> { return request('/api/studio/refresh', { method: 'POST' }); }
  inspectStudio(nodeId: string): Promise<StudioNode> { return request(`/api/studio/${encodeURIComponent(nodeId)}`); }
  lockStudioReference(nodeId: string): Promise<{ ok: boolean }> { return request(`/api/studio/${encodeURIComponent(nodeId)}/lock`, { method: 'POST' }); }
  unlockStudioReference(nodeId: string): Promise<{ ok: boolean }> { return request(`/api/studio/${encodeURIComponent(nodeId)}/unlock`, { method: 'POST' }); }
  useStudioAsContext(nodeId: string): Promise<{ ok: boolean }> { return request(`/api/studio/${encodeURIComponent(nodeId)}/context`, { method: 'POST' }); }

  startTest(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/test`, { method: 'POST' }); }
  stopTest(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/test/stop`, { method: 'POST' }); }
  getTestState(jobId: string): Promise<TestState> { return request(`/api/jobs/${encodeURIComponent(jobId)}/test/state`); }

  getSettings(): Promise<Settings> { return request('/api/settings'); }
  updateSettings(partial: Partial<Settings>): Promise<Settings> { return request('/api/settings', { method: 'PATCH', body: partial }); }
  getModels(): Promise<ModelCatalog> { return request('/api/settings/models'); }
  setModel(agent: 'chatgpt' | 'deepseek' | 'hunyuan', model: string): Promise<{ ok: boolean }> { return request('/api/settings/models', { method: 'PUT', body: { agent, model } }); }
  setSmartRouting(enabled: boolean): Promise<{ ok: boolean }> { return request('/api/settings/smart-routing', { method: 'PUT', body: { enabled } }); }

  getDiagnostics(): Promise<Diagnostic[]> { return request('/api/diagnostics'); }
}
