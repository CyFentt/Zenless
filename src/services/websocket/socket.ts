import type { SocketStatus, ZenlessEvent, ZenlessEventHandler } from '@/types';

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
  private maxReconnect = 5;
  private shouldReconnect = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private wsBase: string) {}

  connect() {
    if (this.ws && (this.status === 'CONNECTING' || this.status === 'CONNECTED')) return;
    this.shouldReconnect = true;
    this.setStatus('CONNECTING');

    try {
      this.ws = new WebSocket(`${this.wsBase}/ws`);
    } catch {
      this.setStatus('DISCONNECTED');
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setStatus('CONNECTED');
    };

    this.ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data) as ZenlessEvent;
        this.eventHandlers.forEach((h) => h(event));
      } catch {
        // ignore malformed
      }
    };

    this.ws.onclose = () => {
      this.setStatus('DISCONNECTED');
      if (this.shouldReconnect) this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.onclose = null;
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

  getStatus() {
    return this.status;
  }

  private setStatus(s: SocketStatus) {
    this.status = s;
    this.statusHandlers.forEach((h) => h(s));
  }

  private scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnect) return;
    this.reconnectAttempts++;
    this.setStatus('RECONNECTING');
    const backoff = Math.min(1000 * 2 ** this.reconnectAttempts, 8000);
    this.reconnectTimer = setTimeout(() => this.connect(), backoff);
  }
}
