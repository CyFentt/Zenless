import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { createMockAdapter, type MockAdapter } from './mockAdapter';

const PORT = parseInt(process.env.ZENLESS_PORT || '8787', 10);
const HOST = '127.0.0.1';
const ALLOWED_ORIGIN = process.env.ZENLESS_ALLOWED_ORIGIN || '*';

const adapter: MockAdapter = createMockAdapter();

interface RouteHandler {
  method: string;
  pattern: RegExp;
  handler: (req: IncomingMessage, res: ServerResponse, params: string[]) => void | Promise<void>;
}

function sendJson(res: ServerResponse, status: number, body: unknown) {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Zenless-Token, X-Client-Info',
    'X-Request-Id': `zen_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
  });
  res.end(json);
}

function readBody(req: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    let data = '';
    req.on('data', (chunk) => { data += chunk; });
    req.on('end', () => {
      try { resolve(data ? JSON.parse(data) : {}); }
      catch { resolve({}); }
    });
  });
}

const routes: RouteHandler[] = [
  // Boot
  { method: 'GET', pattern: /^\/api\/bootstrap$/, handler: (_q, r) => sendJson(r, 200, adapter.bootstrap()) },
  { method: 'GET', pattern: /^\/api\/status$/, handler: (_q, r) => sendJson(r, 200, adapter.getStatus()) },

  // Connections
  { method: 'GET', pattern: /^\/api\/connections$/, handler: (_q, r) => sendJson(r, 200, adapter.getConnections()) },
  { method: 'GET', pattern: /^\/api\/agents$/, handler: (_q, r) => sendJson(r, 200, adapter.getAgents()) },

  // Jobs
  { method: 'GET', pattern: /^\/api\/jobs$/, handler: (_q, r) => sendJson(r, 200, adapter.getJobs()) },
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)$/, handler: (_q, r, p) => {
    const job = adapter.getJob(p[0]);
    if (!job) return sendJson(r, 404, { error: 'Job not found' });
    sendJson(r, 200, job);
  }},
  { method: 'POST', pattern: /^\/api\/jobs$/, handler: async (q, r) => {
    const body = await readBody(q);
    sendJson(r, 200, adapter.createJob(body.title as string, body.options as Record<string, unknown>));
  }},
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/pause$/, handler: (_q, r, p) => sendJson(r, 200, adapter.pauseJob(p[0])) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/resume$/, handler: (_q, r, p) => sendJson(r, 200, adapter.resumeJob(p[0])) },
  { method: 'DELETE', pattern: /^\/api\/jobs\/([^/]+)$/, handler: (_q, r, p) => sendJson(r, 200, adapter.cancelJob(p[0])) },

  // Chat
  { method: 'POST', pattern: /^\/api\/chat$/, handler: async (q, r) => {
    const body = await readBody(q);
    sendJson(r, 200, adapter.sendMessage(body.content as string, body.jobId as string | undefined));
  }},
  { method: 'POST', pattern: /^\/api\/chat\/([^/]+)\/cancel$/, handler: (_q, r) => sendJson(r, 200, adapter.cancelGeneration()) },

  // Context
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/context$/, handler: (_q, r) => sendJson(r, 200, adapter.getContext()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/context\/refresh$/, handler: (_q, r) => sendJson(r, 200, adapter.refreshContext()) },
  { method: 'POST', pattern: /^\/api\/context\/([^/]+)\/include$/, handler: (_q, r, p) => sendJson(r, 200, adapter.includeContext(p[0])) },
  { method: 'POST', pattern: /^\/api\/context\/([^/]+)\/exclude$/, handler: (_q, r, p) => sendJson(r, 200, adapter.excludeContext(p[0])) },
  { method: 'POST', pattern: /^\/api\/context\/([^/]+)\/lock$/, handler: (_q, r, p) => sendJson(r, 200, adapter.lockContext(p[0])) },
  { method: 'POST', pattern: /^\/api\/context\/([^/]+)\/unlock$/, handler: (_q, r, p) => sendJson(r, 200, adapter.unlockContext(p[0])) },
  { method: 'GET', pattern: /^\/api\/context\/([^/]+)$/, handler: (_q, r, p) => {
    const item = adapter.inspectContext(p[0]);
    if (!item) return sendJson(r, 404, { error: 'Context item not found' });
    sendJson(r, 200, item);
  }},

  // Changes
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/changes$/, handler: (_q, r) => sendJson(r, 200, adapter.getChanges()) },
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/review$/, handler: (_q, r) => sendJson(r, 200, adapter.getReview()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/changes\/approve$/, handler: (_q, r) => sendJson(r, 200, adapter.approveChanges()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/changes\/reject$/, handler: (_q, r) => sendJson(r, 200, adapter.rejectChanges()) },
  { method: 'PUT', pattern: /^\/api\/jobs\/([^/]+)\/changes\/([^/]+)$/, handler: async (q, r) => {
    const body = await readBody(q);
    sendJson(r, 200, adapter.editChanges(body.content as string));
  }},

  // Visual
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/visual$/, handler: (_q, r) => sendJson(r, 200, adapter.getVisual()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/visual\/approve$/, handler: (_q, r) => sendJson(r, 200, adapter.approveVisual()) },
  { method: 'PUT', pattern: /^\/api\/jobs\/([^/]+)\/visual\/concept$/, handler: (_q, r) => sendJson(r, 200, adapter.editConcept()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/visual\/regenerate$/, handler: (_q, r) => sendJson(r, 200, adapter.regenerateVisual()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/visual\/views\/([^/]+)\/regenerate$/, handler: (_q, r) => sendJson(r, 200, adapter.regenerateView()) },

  // Model
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/model$/, handler: (_q, r) => sendJson(r, 200, adapter.getModel()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/model\/approve$/, handler: (_q, r) => sendJson(r, 200, adapter.approveModel()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/model\/geometry\/regenerate$/, handler: (_q, r) => sendJson(r, 200, adapter.regenerateGeometry()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/model\/texture\/regenerate$/, handler: (_q, r) => sendJson(r, 200, adapter.regenerateTexture()) },

  // Assets
  { method: 'GET', pattern: /^\/api\/assets$/, handler: (_q, r) => sendJson(r, 200, adapter.getAssets()) },

  // Studio
  { method: 'GET', pattern: /^\/api\/studio\/state$/, handler: (_q, r) => sendJson(r, 200, adapter.getStudioState()) },
  { method: 'GET', pattern: /^\/api\/studio\/tree$/, handler: (_q, r) => sendJson(r, 200, adapter.getStudioTree()) },
  { method: 'GET', pattern: /^\/api\/studio\/search$/, handler: (q, r) => {
    const url = new URL(q.url || '', 'http://localhost');
    sendJson(r, 200, adapter.searchStudio(url.searchParams.get('q') || ''));
  }},
  { method: 'POST', pattern: /^\/api\/studio\/refresh$/, handler: (_q, r) => sendJson(r, 200, adapter.refreshStudio()) },
  { method: 'GET', pattern: /^\/api\/studio\/([^/]+)$/, handler: (_q, r, p) => {
    const node = adapter.inspectStudio(p[0]);
    if (!node) return sendJson(r, 404, { error: 'Node not found' });
    sendJson(r, 200, node);
  }},

  // Test
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/test$/, handler: (_q, r) => sendJson(r, 200, adapter.startTest()) },
  { method: 'POST', pattern: /^\/api\/jobs\/([^/]+)\/test\/stop$/, handler: (_q, r) => sendJson(r, 200, adapter.stopTest()) },
  { method: 'GET', pattern: /^\/api\/jobs\/([^/]+)\/test\/state$/, handler: (_q, r) => sendJson(r, 200, adapter.getTestState()) },

  // Settings
  { method: 'GET', pattern: /^\/api\/settings$/, handler: (_q, r) => sendJson(r, 200, adapter.getSettings()) },
  { method: 'PATCH', pattern: /^\/api\/settings$/, handler: async (q, r) => {
    const body = await readBody(q);
    sendJson(r, 200, adapter.updateSettings(body));
  }},
  { method: 'GET', pattern: /^\/api\/settings\/models$/, handler: (_q, r) => sendJson(r, 200, adapter.getModels()) },
  { method: 'PUT', pattern: /^\/api\/settings\/models$/, handler: async (q, r) => {
    const body = await readBody(q);
    sendJson(r, 200, adapter.setModel(body.agent as string, body.model as string));
  }},
  { method: 'PUT', pattern: /^\/api\/settings\/smart-routing$/, handler: async (q, r) => {
    const body = await readBody(q);
    sendJson(r, 200, adapter.setSmartRouting(body.enabled as boolean));
  }},

  // Diagnostics
  { method: 'GET', pattern: /^\/api\/diagnostics$/, handler: (_q, r) => sendJson(r, 200, adapter.getDiagnostics()) },
];

const server = createServer(async (req, res) => {
  // CORS preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(200, {
      'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
      'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Zenless-Token, X-Client-Info',
    });
    res.end();
    return;
  }

  const url = new URL(req.url || '/', 'http://localhost');
  const path = url.pathname;

  for (const route of routes) {
    if (route.method !== req.method) continue;
    const match = route.pattern.exec(path);
    if (!match) continue;
    try {
      await route.handler(req, res, match.slice(1));
      return;
    } catch (err) {
      sendJson(res, 500, { error: 'Internal bridge error' });
      return;
    }
  }

  sendJson(res, 404, { error: 'Not found' });
});

// WebSocket upgrade handling
server.on('upgrade', (req, socket) => {
  // Simple WebSocket handshake — in production use the `ws` package
  // For now, we emit a basic upgrade response
  const key = req.headers['sec-websocket-key'];
  if (!key) { socket.destroy(); return; }

  // Generate accept hash
  const crypto = require('node:crypto');
  const accept = crypto.createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');

  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
    'Upgrade: websocket\r\n' +
    'Connection: Upgrade\r\n' +
    `Sec-WebSocket-Accept: ${accept}\r\n` +
    '\r\n'
  );

  // Subscribe to mock adapter events and send them as WebSocket frames
  const unsub = adapter.subscribe((event) => {
    const data = JSON.stringify(event);
    // Simple text frame (opcode 1)
    const payload = Buffer.from(data);
    const mask = payload.length < 126 ? Buffer.alloc(2) : payload.length < 65536 ? Buffer.alloc(4) : Buffer.alloc(10);
    mask[0] = 0x81; // FIN + text
    if (payload.length < 126) {
      mask[1] = payload.length;
    } else if (payload.length < 65536) {
      mask[1] = 126;
      mask.writeUInt16BE(payload.length, 2);
    } else {
      mask[1] = 127;
      mask.writeBigUInt64BE(BigInt(payload.length), 2);
    }
    socket.write(Buffer.concat([mask.slice(0, payload.length < 126 ? 2 : payload.length < 65536 ? 4 : 10), payload]));
  });

  socket.on('close', () => unsub());
  socket.on('error', () => unsub());
});

server.listen(PORT, HOST, () => {
  console.log(`Zenless Bridge running at http://${HOST}:${PORT}`);
  console.log(`WebSocket: ws://${HOST}:${PORT}/ws`);
});
