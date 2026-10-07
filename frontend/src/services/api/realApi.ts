import type { LocalAIState } from '@/types';
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
  PromptQueueConfig,
  PromptQueueItem,
  PromptQueueSnapshot,
  ProjectIndexStatus,
  ProjectSearchResult,
  Review,
  Settings,
  StudioNode,
  StudioState,
  TaskOptions,
  TestState,
  ToolDescriptor,
  ViewTile,
} from '@/types';

const API_BASE = (import.meta.env.VITE_RUBRA_API_BASE?.trim() || '').replace(/\/$/, '');
const DEFAULT_TIMEOUT = 15000;

interface RequestOptions {
  method?: string;
  body?: unknown;
  timeout?: number;
  signal?: AbortSignal;
  rawBody?: BodyInit;
  idempotencyKey?: string;
  reportFailure?: boolean;
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
  const attempts = opts.idempotencyKey ? 3 : 1;
  const requestId = crypto.randomUUID?.() ?? `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  let finalTransportError: ApiError | null = null;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const { signal, cancel } = withTimeout(opts.timeout ?? DEFAULT_TIMEOUT);
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal.addEventListener('abort', abort, { once: true });
    opts.signal?.addEventListener('abort', abort, { once: true });
    if (opts.signal?.aborted) abort();

    const headers: Record<string, string> = { 'X-Request-Id': requestId };
    if (opts.rawBody === undefined) headers['Content-Type'] = 'application/json';
    const token = getStoredToken();
    if (token) headers['X-Rubra-Token'] = token;
    if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;

    try {
      const res = await fetch(`${API_BASE}${path}`, {
        method: opts.method ?? 'GET',
        headers,
        body: opts.rawBody ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
        signal: controller.signal,
      });
      const responseRequestId = res.headers.get('X-Request-Id') ?? requestId;
      if (res.status === 204) return undefined as T;
      let body: unknown;
      try {
        body = await res.json();
      } catch (error) {
        if (controller.signal.aborted) throw error;
        throw new ApiError(
          res.status,
          res.ok ? 'Invalid bridge response' : `HTTP ${res.status}`,
          responseRequestId,
          'INVALID_RESPONSE',
        );
      }
      if (!res.ok) {
        const failure = body && typeof body === 'object' ? body as Record<string, unknown> : {};
        const message = typeof failure.message === 'string'
          ? failure.message
          : typeof failure.error === 'string'
            ? failure.error
            : `HTTP ${res.status}`;
        const code = typeof failure.code === 'string' ? failure.code : undefined;
        if (
          opts.idempotencyKey
          && res.status === 409
          && code === 'IDEMPOTENCY_PENDING'
          && attempt + 1 < attempts
          && !opts.signal?.aborted
        ) {
          await new Promise((resolve) => window.setTimeout(resolve, 150 * (attempt + 1)));
          continue;
        }
        throw new ApiError(res.status, message, responseRequestId, code, failure.details);
      }
      return body as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      const timedOut = signal.aborted;
      const externallyCancelled = Boolean(opts.signal?.aborted);
      const code = timedOut ? 'TIMEOUT' : externallyCancelled ? 'CANCELLED' : 'UNREACHABLE';
      const message = timedOut ? 'Request timeout' : externallyCancelled ? 'Request cancelled' : 'Bridge unreachable';
      finalTransportError = new ApiError(0, message, requestId, code);
      if (opts.idempotencyKey && !externallyCancelled && attempt + 1 < attempts) {
        await new Promise((resolve) => window.setTimeout(resolve, 150 * (attempt + 1)));
        continue;
      }
      if (opts.reportFailure !== false) {
        frontendDiagnostics.report('error', 'api', message, undefined, undefined, {
          requestId,
          stack: error instanceof Error ? error.stack : undefined,
        });
      }
      throw finalTransportError;
    } finally {
      cancel();
      signal.removeEventListener('abort', abort);
      opts.signal?.removeEventListener('abort', abort);
    }
  }

  throw finalTransportError ?? new ApiError(0, 'Bridge unreachable', requestId, 'UNREACHABLE');
}

const TOKEN_KEY = 'rubra_token';
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
    const payload = await request<{ token?: unknown }>('/api/session');
    if (!payload || typeof payload.token !== 'string' || !payload.token.trim()) throw new Error('Session bootstrap returned no token');
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
  getTools(): Promise<ToolDescriptor[]> { return request('/api/tools'); }
  loginProvider(provider: ProviderId): Promise<{ ok: boolean }> {
    return request(`/api/providers/${encodeURIComponent(provider)}/login`, { method: 'POST', timeout: 30000 });
  }
  cancelProviderLogin(provider: ProviderId): Promise<{ ok: boolean }> {
    return request(`/api/providers/${encodeURIComponent(provider)}/login/cancel`, { method: 'POST', timeout: 10000 });
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
  getPromptQueue(): Promise<PromptQueueSnapshot> { return request('/api/prompt-queue'); }
  enqueuePrompt(content: string, jobId?: string, options?: TaskOptions): Promise<PromptQueueItem> {
    return request('/api/prompt-queue', {
      method: 'POST',
      body: { content, jobId, options },
      idempotencyKey: operationKey('prompt-queue'),
    });
  }
  updatePromptQueueItem(id: string, patch: { content?: string; options?: TaskOptions }): Promise<PromptQueueItem> {
    return request(`/api/prompt-queue/${encodeURIComponent(id)}`, { method: 'PATCH', body: patch });
  }
  retryPromptQueueItem(id: string): Promise<PromptQueueItem> {
    return request(`/api/prompt-queue/${encodeURIComponent(id)}/retry`, { method: 'POST' });
  }
  confirmPromptQueueItem(id: string): Promise<PromptQueueItem> {
    return request(`/api/prompt-queue/${encodeURIComponent(id)}/confirm`, { method: 'POST' });
  }
  movePromptQueueItem(id: string, direction: -1 | 1): Promise<PromptQueueSnapshot> {
    return request(`/api/prompt-queue/${encodeURIComponent(id)}/move`, { method: 'POST', body: { direction } });
  }
  deletePromptQueueItem(id: string): Promise<{ ok: boolean }> {
    return request(`/api/prompt-queue/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }
  updatePromptQueueConfig(patch: Partial<PromptQueueConfig>): Promise<PromptQueueConfig> {
    return request('/api/prompt-queue/config', { method: 'PATCH', body: patch });
  }

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

  getStudioState(): Promise<{ state: StudioState; projectName?: string; treeError?: string }> { return request('/api/studio/state'); }
  getStudioTree(): Promise<StudioNode[]> { return request('/api/studio/tree'); }
  searchStudio(query: string): Promise<StudioNode[]> { return request(`/api/studio/search?q=${encodeURIComponent(query)}`); }
  refreshStudio(): Promise<{ ok: boolean }> { return request('/api/studio/refresh', { method: 'POST', timeout: 60000 }); }
  inspectStudio(nodeId: string): Promise<StudioNode> { return request(`/api/studio/${encodeURIComponent(nodeId)}`); }
  lockStudioReference(nodeId: string): Promise<{ ok: boolean }> { return request(`/api/studio/${encodeURIComponent(nodeId)}/lock`, { method: 'POST' }); }
  unlockStudioReference(nodeId: string): Promise<{ ok: boolean }> { return request(`/api/studio/${encodeURIComponent(nodeId)}/unlock`, { method: 'POST' }); }
  useStudioAsContext(nodeId: string): Promise<{ ok: boolean }> { return request(`/api/studio/${encodeURIComponent(nodeId)}/context`, { method: 'POST' }); }

  startStudioTest(): Promise<{ ok: boolean; jobId: string }> { return request('/api/studio/test', { method: 'POST', timeout: 60000 }); }
  startTest(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/test`, { method: 'POST' }); }
  stopTest(jobId: string): Promise<{ ok: boolean }> { return request(`/api/jobs/${encodeURIComponent(jobId)}/test/stop`, { method: 'POST' }); }
  getTestState(jobId: string): Promise<TestState> { return request(`/api/jobs/${encodeURIComponent(jobId)}/test/state`); }

  getProjectIndexStatus(): Promise<ProjectIndexStatus> { return request('/api/project/index'); }
  reindexProject(incremental = true): Promise<{ projectRoot: string; result: string; indexed: boolean }> {
    return request('/api/project/index', { method: 'POST', body: { incremental }, timeout: 900000 });
  }
  searchProject(query: string, semantic = true, limit = 12): Promise<ProjectSearchResult> {
    return request(`/api/project/search?q=${encodeURIComponent(query)}&semantic=${semantic ? '1' : '0'}&limit=${Math.max(1, Math.min(30, limit))}`, { timeout: 120000 });
  }

  getLocalAIState(): Promise<LocalAIState> { return request('/api/local-ai'); }
  prepareLocalAI(): Promise<{ ok: boolean }> { return request('/api/local-ai/prepare', { method: 'POST' }); }
  prepareLocalAIItem(id: string): Promise<{ ok: boolean }> {
    return request(`/api/local-ai/${encodeURIComponent(id)}/prepare`, { method: 'POST' });
  }
  getSettings(): Promise<Settings> { return request('/api/settings'); }
  updateSettings(partial: Partial<Settings>): Promise<Settings> { return request('/api/settings', { method: 'PATCH', body: partial }); }
  getModels(): Promise<ModelCatalog> { return request('/api/settings/models'); }
  setModel(agent: 'chatgpt' | 'deepseek' | 'gemini' | 'hunyuan', model: string): Promise<{ ok: boolean }> { return request('/api/settings/models', { method: 'PUT', body: { agent, model } }); }
  setSmartRouting(enabled: boolean): Promise<{ ok: boolean }> { return request('/api/settings/smart-routing', { method: 'PUT', body: { enabled } }); }

  getDiagnostics(): Promise<Diagnostic[]> { return request('/api/diagnostics'); }
  reportFrontendDiagnostic(diagnostic: Diagnostic): Promise<{ ok: boolean }> {
    return request('/api/diagnostics/frontend', {
      method: 'POST',
      body: diagnostic,
      timeout: 4000,
      reportFailure: false,
    });
  }
}
