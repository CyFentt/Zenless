import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { randomBytes, randomUUID } from 'node:crypto';
import { WebSocket, WebSocketServer } from 'ws';
import { createMockAdapter } from './mockAdapter.ts';

const HOST = process.env.ZENLESS_HOST || '127.0.0.1';
const PORT = Number(process.env.ZENLESS_PORT || 8787);
const SESSION_TOKEN = process.env.ZENLESS_TOKEN || randomBytes(32).toString('hex');
const DEV_ORIGINS = [`http://${HOST}:${PORT}`, 'http://127.0.0.1:5173', 'http://localhost:5173'];
const ALLOWED_ORIGINS = new Set(
  (process.env.ZENLESS_ALLOWED_ORIGINS || DEV_ORIGINS.join(','))
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean),
);

const adapter = createMockAdapter();

function requestOrigin(req: IncomingMessage): string | undefined {
  return typeof req.headers.origin === 'string' ? req.headers.origin : undefined;
}

function originAllowed(req: IncomingMessage): boolean {
  const origin = requestOrigin(req);
  return !origin || ALLOWED_ORIGINS.has(origin);
}

function corsHeaders(req: IncomingMessage): Record<string, string> {
  const origin = requestOrigin(req);
  return origin && ALLOWED_ORIGINS.has(origin) ? { 'Access-Control-Allow-Origin': origin, Vary: 'Origin' } : {};
}

function sendJson(req: IncomingMessage, res: ServerResponse, status: number, body: unknown, requestId = randomUUID()) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(data),
    'X-Request-Id': requestId,
    ...corsHeaders(req),
  });
  res.end(data);
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  const contentType = String(req.headers['content-type'] || '');
  if (!contentType.includes('application/json')) return {};
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>;
}

function authorized(req: IncomingMessage): boolean {
  return req.headers['x-zenless-token'] === SESSION_TOKEN;
}

type RouteHandler = (req: IncomingMessage, res: ServerResponse, params: string[]) => void | Promise<void>;
interface Route { method: string; pattern: RegExp; handler: RouteHandler }

const routes: Route[] = [
  { method: 'GET', pattern: /^\/api\/bootstrap$/, handler: (q, r) => sendJson(q, r, 200, adapter.bootstrap()) },
  { method: 'GET', pattern: /^\/api\/status$/, handler: (q, r) => sendJson(q, r, 200, adapter.getStatus()) },
  { method: 'GET', pattern: /^\/api\/connections$/, handler: (q, r) => sendJson(q, r, 200, adapter.getConnections()) },
  { method: 'GET', pattern: /^\/api\/agents$/, handler: (q, r) => sendJson(q, r, 200, adapter.getAgents()) },

  { method: 'GET', pattern: /^\/api\/jobs$/, handler: (q, r) => sendJson(q, r, 200, adapter.getJobs()) },
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)$/, handler: (q, r, p) => {
    const job = adapter.getJob(decodeURIComponent(p[0]));
    if (!job) return sendJson(q, r, 404, { code: 'NOT_FOUND', message: 'Job not found' });
    sendJson(q, r, 200, job);
  }},
  { method: 'POST', pattern: /^\/api\/jobs$/, handler: async (q, r) => {
    const body = await readJson(q);
    sendJson(q, r, 200, adapter.createJob(String(body.title || 'Untitled'), body.options as Record<string, unknown> | undefined));
  }},
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/pause$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.pauseJob(decodeURIComponent(p[0]))) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/resume$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.resumeJob(decodeURIComponent(p[0]))) },
  { method: 'DELETE', pattern: /^\/api\/jobs\/([^/]+)$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.cancelJob(decodeURIComponent(p[0]))) },

  { method: 'POST', pattern: /^\/api\/chat$/, handler: async (q, r) => {
    const contentType = String(q.headers['content-type'] || '');
    if (!contentType.includes('application/json')) {
      return sendJson(q, r, 415, { code: 'MOCK_MULTIPART_UNSUPPORTED', message: 'Development bridge accepts JSON chat only; frontend Mock Mode supports attachment UI.' });
    }
    const body = await readJson(q);
    sendJson(q, r, 200, adapter.sendMessage(String(body.content || ''), body.jobId ? String(body.jobId) : undefined));
  }},
  { method: 'POST', pattern: /^\/api\/chat\/([^/]+)\/cancel$/, handler: (q, r) => sendJson(q, r, 200, adapter.cancelGeneration()) },

  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/context$/, handler: (q, r) => sendJson(q, r, 200, adapter.getContext()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/context\/refresh$/, handler: (q, r) => sendJson(q, r, 200, adapter.refreshContext()) },
  { method: 'POST', pattern: /^\/api\/context\/([^/]+)\/include$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.includeContext(decodeURIComponent(p[0]))) },
  { method: 'POST', pattern: /^\/api\/context\/([^/]+)\/exclude$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.excludeContext(decodeURIComponent(p[0]))) },
  { method: 'POST', pattern: /^\/api\/context\/([^/]+)\/lock$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.lockContext(decodeURIComponent(p[0]))) },
  { method: 'POST', pattern: /^\/api\/context\/([^/]+)\/unlock$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.unlockContext(decodeURIComponent(p[0]))) },
  { method: 'GET', pattern: /^\/api\/context\/([^/]+)$/, handler: (q, r, p) => {
    const item = adapter.inspectContext(decodeURIComponent(p[0]));
    if (!item) return sendJson(q, r, 404, { code: 'NOT_FOUND', message: 'Context item not found' });
    sendJson(q, r, 200, item);
  }},

  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/changes$/, handler: (q, r) => sendJson(q, r, 200, adapter.getChanges()) },
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/review$/, handler: (q, r) => sendJson(q, r, 200, adapter.getReview()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/changes\/approve$/, handler: (q, r) => sendJson(q, r, 200, adapter.approveChanges()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/changes\/reject$/, handler: (q, r) => sendJson(q, r, 200, adapter.rejectChanges()) },
  { method: 'PUT', pattern: /^\/api\/jobs\/([^/]+)\/changes\/([^/]+)$/, handler: async (q, r) => { const body = await readJson(q); sendJson(q, r, 200, adapter.editChanges(String(body.content || ''))); } },

  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/visual$/, handler: (q, r) => sendJson(q, r, 200, adapter.getVisual()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/visual\/approve$/, handler: (q, r) => sendJson(q, r, 200, adapter.approveVisual()) },
  { method: 'PUT', pattern: /^\/api\/jobs\/([^/]+)\/visual\/concept$/, handler: async (q, r) => { const body = await readJson(q); sendJson(q, r, 200, adapter.editConcept(String(body.prompt || ''))); } },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/visual\/regenerate$/, handler: (q, r) => sendJson(q, r, 200, adapter.regenerateVisual()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/visual\/views\/([^/]+)\/regenerate$/, handler: (q, r) => sendJson(q, r, 200, adapter.regenerateView()) },

  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/model$/, handler: (q, r) => sendJson(q, r, 200, adapter.getModel()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/model\/approve$/, handler: (q, r) => sendJson(q, r, 200, adapter.approveModel()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/model\/geometry\/regenerate$/, handler: (q, r) => sendJson(q, r, 200, adapter.regenerateGeometry()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/model\/texture\/regenerate$/, handler: (q, r) => sendJson(q, r, 200, adapter.regenerateTexture()) },
  { method: 'GET', pattern: /^\/api\/assets$/, handler: (q, r) => sendJson(q, r, 200, adapter.getAssets()) },

  { method: 'GET', pattern: /^\/api\/studio\/state$/, handler: (q, r) => sendJson(q, r, 200, adapter.getStudioState()) },
  { method: 'GET', pattern: /^\/api\/studio\/tree$/, handler: (q, r) => sendJson(q, r, 200, adapter.getStudioTree()) },
  { method: 'GET', pattern: /^\/api\/studio\/search$/, handler: (q, r) => { const url = new URL(q.url || '', `http://${HOST}:${PORT}`); sendJson(q, r, 200, adapter.searchStudio(url.searchParams.get('q') || '')); } },
  { method: 'POST', pattern: /^\/api\/studio\/refresh$/, handler: (q, r) => sendJson(q, r, 200, adapter.refreshStudio()) },
  { method: 'POST', pattern: /^\/api\/studio\/([^/]+)\/lock$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.lockStudioReference(decodeURIComponent(p[0]))) },
  { method: 'POST', pattern: /^\/api\/studio\/([^/]+)\/unlock$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.unlockStudioReference(decodeURIComponent(p[0]))) },
  { method: 'POST', pattern: /^\/api\/studio\/([^/]+)\/context$/, handler: (q, r, p) => sendJson(q, r, 200, adapter.useStudioAsContext(decodeURIComponent(p[0]))) },
  { method: 'GET', pattern: /^\/api\/studio\/([^/]+)$/, handler: (q, r, p) => {
    const node = adapter.inspectStudio(decodeURIComponent(p[0]));
    if (!node) return sendJson(q, r, 404, { code: 'NOT_FOUND', message: 'Node not found' });
    sendJson(q, r, 200, node);
  }},

  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/test$/, handler: (q, r) => sendJson(q, r, 200, adapter.startTest()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/test\/stop$/, handler: (q, r) => sendJson(q, r, 200, adapter.stopTest()) },
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/test\/state$/, handler: (q, r) => sendJson(q, r, 200, adapter.getTestState()) },

  { method: 'GET', pattern: /^\/api\/settings$/, handler: (q, r) => sendJson(q, r, 200, adapter.getSettings()) },
  { method: 'PATCH', pattern: /^\/api\/settings$/, handler: async (q, r) => { const body = await readJson(q); sendJson(q, r, 200, adapter.updateSettings(body)); } },
  { method: 'GET', pattern: /^\/api\/settings\/models$/, handler: (q, r) => sendJson(q, r, 200, adapter.getModels()) },
  { method: 'PUT', pattern: /^\/api\/settings\/models$/, handler: async (q, r) => { const body = await readJson(q); sendJson(q, r, 200, adapter.setModel(String(body.agent || ''), String(body.model || ''))); } },
  { method: 'PUT', pattern: /^\/api\/settings\/smart-routing$/, handler: async (q, r) => { const body = await readJson(q); sendJson(q, r, 200, adapter.setSmartRouting(Boolean(body.enabled))); } },
  { method: 'GET', pattern: /^\/api\/diagnostics$/, handler: (q, r) => sendJson(q, r, 200, adapter.getDiagnostics()) },
];

const server = createServer(async (req, res) => {
  const requestId = randomUUID();
  if (!originAllowed(req)) return sendJson(req, res, 403, { code: 'ORIGIN_DENIED', message: 'Origin denied' }, requestId);

  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      ...corsHeaders(req),
      'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, X-Zenless-Token, X-Request-Id',
    });
    return res.end();
  }

  const url = new URL(req.url || '/', `http://${HOST}:${PORT}`);
  if (req.method === 'GET' && url.pathname === '/api/session') {
    return sendJson(req, res, 200, { token: SESSION_TOKEN }, requestId);
  }
  if (!authorized(req)) return sendJson(req, res, 401, { code: 'UNAUTHORIZED', message: 'Invalid Zenless session token' }, requestId);

  for (const route of routes) {
    if (route.method !== req.method) continue;
    const match = route.pattern.exec(url.pathname);
    if (!match) continue;
    try {
      await route.handler(req, res, match.slice(1));
    } catch (error) {
      console.error('[bridge]', error);
      if (!res.headersSent) sendJson(req, res, 500, { code: 'BRIDGE_ERROR', message: 'Internal bridge error' }, requestId);
    }
    return;
  }
  sendJson(req, res, 404, { code: 'NOT_FOUND', message: 'Not found' }, requestId);
});

const wss = new WebSocketServer({ noServer: true });
wss.on('connection', (ws) => {
  const unsubscribe = adapter.subscribe((event) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(event));
  });
  ws.on('close', unsubscribe);
  ws.on('error', (error) => console.error('[bridge/ws]', error));
});

server.on('upgrade', (req, socket, head) => {
  try {
    if (!originAllowed(req)) return socket.destroy();
    const url = new URL(req.url || '/', `http://${HOST}:${PORT}`);
    if (url.pathname !== '/ws' || url.searchParams.get('token') !== SESSION_TOKEN) return socket.destroy();
    wss.handleUpgrade(req, socket, head, (ws) => wss.emit('connection', ws, req));
  } catch (error) {
    console.error('[bridge/ws-upgrade]', error);
    socket.destroy();
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Zenless development Bridge: http://${HOST}:${PORT}`);
  console.log(`Allowed origins: ${[...ALLOWED_ORIGINS].join(', ')}`);
});
