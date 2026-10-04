import type { SocketStatus, ZenlessEvent, ZenlessEventHandler } from '@/types';
import { frontendDiagnostics } from '@/services/diagnostics';

type StatusHandler = (status: SocketStatus) => void;

export interface ZenlessSocket {
  connect(): void;
  disconnect(): void;
  on(event: 'event', handler: ZenlessEventHandler): () => void;
  on(event: 'status', handler: StatusHandler): () => void;
  getStatus(): SocketStatus;
}

export class RealZenlessSocket implements ZenlessSocket {
  private ws: WebSocket | null = null;
  private status: SocketStatus = 'DISCONNECTED';
  private eventHandlers = new Set<ZenlessEventHandler>();
  private statusHandlers = new Set<StatusHandler>();
  private reconnectAttempts = 0;
  private shouldReconnect = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private wsBase: string) {}

  connect() {
    if (this.ws) return;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.shouldReconnect = true;
    this.setStatus(this.reconnectAttempts > 0 ? 'RECONNECTING' : 'CONNECTING');

    try {
      const token = safeLocalStorage('rubra_token');
      const url = new URL(this.wsBase);
      url.pathname = `${url.pathname.replace(/\/$/, '')}/ws`;
      if (token) url.searchParams.set('token', token);
      this.ws = new WebSocket(url.toString());
    } catch (error) {
      frontendDiagnostics.capture(error, 'websocket', 'Failed to create WebSocket');
      this.ws = null;
      this.setStatus('DISCONNECTED');
      this.scheduleReconnect();
      return;
    }

    const socket = this.ws;
    socket.onopen = () => {
      if (this.ws !== socket) return;
      this.reconnectAttempts = 0;
      this.setStatus('CONNECTED');
    };

    socket.onmessage = (event) => {
      if (this.ws !== socket) return;
      try {
        const parsed: unknown = JSON.parse(String(event.data));
        if (!isZenlessEventShape(parsed)) {
          frontendDiagnostics.report('warning', 'websocket', 'Malformed event payload');
          return;
        }
        this.eventHandlers.forEach((handler) => handler(parsed as ZenlessEvent));
      } catch (error) {
        frontendDiagnostics.capture(error, 'websocket', 'Failed to parse WebSocket event');
      }
    };

    socket.onclose = () => {
      if (this.ws !== socket) return;
      this.ws = null;
      this.setStatus('DISCONNECTED');
      if (this.shouldReconnect) this.scheduleReconnect();
    };

    socket.onerror = () => {
      if (this.ws !== socket) return;
      frontendDiagnostics.report('warning', 'websocket', 'WebSocket transport error');
      socket.close();
    };
  }

  disconnect() {
    this.shouldReconnect = false;
    this.reconnectAttempts = 0;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.close();
      this.ws = null;
    }
    this.setStatus('DISCONNECTED');
  }

  on(event: 'event' | 'status', handler: ZenlessEventHandler | StatusHandler): () => void {
    if (event === 'event') {
      this.eventHandlers.add(handler as ZenlessEventHandler);
      return () => this.eventHandlers.delete(handler as ZenlessEventHandler);
    }
    this.statusHandlers.add(handler as StatusHandler);
    return () => this.statusHandlers.delete(handler as StatusHandler);
  }

  getStatus() { return this.status; }

  private setStatus(status: SocketStatus) {
    if (this.status === status) return;
    this.status = status;
    this.statusHandlers.forEach((handler) => handler(status));
  }

  private scheduleReconnect() {
    if (!this.shouldReconnect || this.reconnectTimer) return;
    this.reconnectAttempts += 1;
    this.setStatus('RECONNECTING');
    const base = Math.min(500 * 2 ** this.reconnectAttempts, 8000);
    const jitter = Math.floor(Math.random() * 250);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.shouldReconnect) this.connect();
    }, base + jitter);
  }
}

function isZenlessEventShape(value: unknown): value is { type: string; data: unknown } {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as { type?: unknown; data?: unknown };
  return typeof candidate.type === 'string' && 'data' in candidate;
}

function safeLocalStorage(key: string): string | null {
  try { return localStorage.getItem(key); }
  catch (error) {
    frontendDiagnostics.capture(error, 'storage', 'Unable to read WebSocket session token');
    return null;
  }
}
