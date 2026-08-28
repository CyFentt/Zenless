import type { ZenlessAPI } from './types';
import type {
  AgentInfo,
  Asset,
  BootStep,
  ChangedFile,
  ChatMessage,
  ConnectionInfo,
  ContextItem,
  Diagnostic,
  Job,
  ModelInfo,
  ModelSettings,
  Review,
  Settings,
  StudioNode,
  StudioState,
  TaskOptions,
  TestLog,
  TestState,
  ViewTile,
} from '@/types';

const API_BASE = import.meta.env.VITE_ZENLESS_API_BASE || 'http://127.0.0.1:8787';
const DEFAULT_TIMEOUT = 15000;

interface RequestOptions {
  method?: string;
  body?: unknown;
  timeout?: number;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId?: string,
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

  const signal = opts.signal
    ? mergeSignals(opts.signal, timeoutSignal)
    : timeoutSignal;

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getStoredToken();
  if (token) headers['X-Zenless-Token'] = token;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal,
    });
  } catch (err) {
    cancel();
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'Request timeout');
    }
    throw new ApiError(0, 'Bridge unreachable');
  }
  cancel();

  const requestId = res.headers.get('X-Request-Id') ?? undefined;

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body.error ?? message;
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, message, requestId);
  }

  return res.json() as Promise<T>;
}

async function requestRaw<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const timeout = opts.timeout ?? DEFAULT_TIMEOUT;
  const { signal: timeoutSignal, cancel } = withTimeout(timeout);
  const signal = opts.signal ? mergeSignals(opts.signal, timeoutSignal) : timeoutSignal;

  const headers: Record<string, string> = {};
  const token = getStoredToken();
  if (token) headers['X-Zenless-Token'] = token;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'POST',
      headers,
      body: opts.body as BodyInit,
      signal,
    });
  } catch (err) {
    cancel();
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'Request timeout');
    }
    throw new ApiError(0, 'Bridge unreachable');
  }
  cancel();

  const requestId = res.headers.get('X-Request-Id') ?? undefined;
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try { const body = await res.json(); message = body.error ?? message; } catch { /* ignore */ }
    throw new ApiError(res.status, message, requestId);
  }
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
function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
export function setStoredToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

export class RealZenlessAPI implements ZenlessAPI {
  async bootstrap(): Promise<{ steps: BootStep[] }> {
    return request('/api/bootstrap', { timeout: 30000 });
  }
  async getStatus(): Promise<{ ready: boolean }> {
    return request('/api/status');
  }
  async getConnections(): Promise<ConnectionInfo> {
    return request('/api/connections');
  }
  async getAgents(): Promise<AgentInfo[]> {
    return request('/api/agents');
  }
  async getJobs(): Promise<Job[]> {
    return request('/api/jobs');
  }
  async getJob(id: string): Promise<Job> {
    return request(`/api/jobs/${id}`);
  }
  async createJob(title: string, options?: Partial<TaskOptions>): Promise<Job> {
    return request('/api/jobs', { method: 'POST', body: { title, options } });
  }
  async pauseJob(id: string): Promise<Job> {
    return request(`/api/jobs/${id}/pause`, { method: 'POST' });
  }
  async resumeJob(id: string): Promise<Job> {
    return request(`/api/jobs/${id}/resume`, { method: 'POST' });
  }
  async cancelJob(id: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${id}`, { method: 'DELETE' });
  }
  async sendMessage(content: string, jobId?: string, attachments?: ChatMessage['attachments']): Promise<{ messageId: string; jobId?: string }> {
    if (attachments && attachments.length > 0) {
      const formData = new FormData();
      formData.append('content', content);
      if (jobId) formData.append('jobId', jobId);
      for (const att of attachments) {
        if (att.file) formData.append('files', att.file, att.name);
      }
      return requestRaw(`/api/chat`, { method: 'POST', body: formData });
    }
    return request('/api/chat', { method: 'POST', body: { content, jobId } });
  }
  async cancelGeneration(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/chat/${jobId}/cancel`, { method: 'POST' });
  }
  async getContext(jobId: string): Promise<ContextItem[]> {
    return request(`/api/jobs/${jobId}/context`);
  }
  async refreshContext(jobId: string): Promise<ContextItem[]> {
    return request(`/api/jobs/${jobId}/context/refresh`, { method: 'POST' });
  }
  async includeContext(itemId: string): Promise<{ ok: boolean }> {
    return request(`/api/context/${itemId}/include`, { method: 'POST' });
  }
  async excludeContext(itemId: string): Promise<{ ok: boolean }> {
    return request(`/api/context/${itemId}/exclude`, { method: 'POST' });
  }
  async lockContext(itemId: string): Promise<{ ok: boolean }> {
    return request(`/api/context/${itemId}/lock`, { method: 'POST' });
  }
  async unlockContext(itemId: string): Promise<{ ok: boolean }> {
    return request(`/api/context/${itemId}/unlock`, { method: 'POST' });
  }
  async inspectContext(itemId: string): Promise<ContextItem> {
    return request(`/api/context/${itemId}`);
  }
  async getChanges(jobId: string): Promise<ChangedFile[]> {
    return request(`/api/jobs/${jobId}/changes`);
  }
  async getReview(jobId: string): Promise<{ files: ChangedFile[]; review: Review; ready: boolean }> {
    return request(`/api/jobs/${jobId}/review`);
  }
  async approveChanges(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/changes/approve`, { method: 'POST' });
  }
  async rejectChanges(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/changes/reject`, { method: 'POST' });
  }
  async editChanges(jobId: string, fileId: string, content: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/changes/${fileId}`, { method: 'PUT', body: { content } });
  }
  async getVisual(jobId: string): Promise<{ views: ViewTile[]; concept: { version: number; status: string; prompt?: string } }> {
    return request(`/api/jobs/${jobId}/visual`);
  }
  async approveVisual(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/visual/approve`, { method: 'POST' });
  }
  async editConcept(jobId: string, prompt: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/visual/concept`, { method: 'PUT', body: { prompt } });
  }
  async regenerateVisual(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/visual/regenerate`, { method: 'POST' });
  }
  async regenerateView(jobId: string, view: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/visual/views/${view}/regenerate`, { method: 'POST' });
  }
  async getModel(jobId: string): Promise<ModelInfo> {
    return request(`/api/jobs/${jobId}/model`);
  }
  async approveModel(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/model/approve`, { method: 'POST' });
  }
  async regenerateGeometry(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/model/geometry/regenerate`, { method: 'POST' });
  }
  async regenerateTexture(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/model/texture/regenerate`, { method: 'POST' });
  }
  async getAssets(): Promise<Asset[]> {
    return request('/api/assets');
  }
  async getStudioState(): Promise<{ state: StudioState }> {
    return request('/api/studio/state');
  }
  async getStudioTree(): Promise<StudioNode[]> {
    return request('/api/studio/tree');
  }
  async searchStudio(query: string): Promise<StudioNode[]> {
    return request(`/api/studio/search?q=${encodeURIComponent(query)}`);
  }
  async refreshStudio(): Promise<{ ok: boolean }> {
    return request('/api/studio/refresh', { method: 'POST' });
  }
  async inspectStudio(nodeId: string): Promise<StudioNode> {
    return request(`/api/studio/${nodeId}`);
  }
  async lockStudioReference(nodeId: string): Promise<{ ok: boolean }> {
    return request(`/api/studio/${nodeId}/lock`, { method: 'POST' });
  }
  async unlockStudioReference(nodeId: string): Promise<{ ok: boolean }> {
    return request(`/api/studio/${nodeId}/unlock`, { method: 'POST' });
  }
  async useStudioAsContext(nodeId: string): Promise<{ ok: boolean }> {
    return request(`/api/studio/${nodeId}/use`, { method: 'POST' });
  }
  async startTest(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/test`, { method: 'POST' });
  }
  async stopTest(jobId: string): Promise<{ ok: boolean }> {
    return request(`/api/jobs/${jobId}/test/stop`, { method: 'POST' });
  }
  async getTestState(jobId: string): Promise<TestState> {
    return request(`/api/jobs/${jobId}/test/state`);
  }
  async getSettings(): Promise<Settings> {
    return request('/api/settings');
  }
  async updateSettings(partial: Partial<Settings>): Promise<Settings> {
    return request('/api/settings', { method: 'PATCH', body: partial });
  }
  async getModels(): Promise<ModelSettings> {
    return request('/api/settings/models');
  }
  async setModel(agent: 'chatgpt' | 'deepseek', model: string): Promise<{ ok: boolean }> {
    return request('/api/settings/models', { method: 'PUT', body: { agent, model } });
  }
  async setSmartRouting(enabled: boolean): Promise<{ ok: boolean }> {
    return request('/api/settings/smart-routing', { method: 'PUT', body: { enabled } });
  }
  async getDiagnostics(): Promise<Diagnostic[]> {
    return request('/api/diagnostics');
  }
}
