import type { ZenlessAPI } from './api/types';
import type { ZenlessSocket } from './websocket/socket';
import { RealZenlessAPI } from './api/realApi';
import { RealZenlessSocket } from './websocket/socket';
import { MockZenlessAPI } from './mock/mockApi';
import { MockZenlessSocket } from './websocket/mockSocket';

const isMock = import.meta.env.VITE_ZENLESS_MOCK === 'true';

let apiInstance: ZenlessAPI | null = null;
let socketInstance: ZenlessSocket | null = null;
let mockApiInstance: MockZenlessAPI | null = null;

export function getApi(): ZenlessAPI {
  if (apiInstance) return apiInstance;
  if (isMock) {
    mockApiInstance = new MockZenlessAPI();
    apiInstance = mockApiInstance;
  } else {
    apiInstance = new RealZenlessAPI();
  }
  return apiInstance;
}

export function getMockApi(): MockZenlessAPI | null {
  if (!isMock) return null;
  if (!mockApiInstance) getApi();
  return mockApiInstance;
}

export function getSocket(): ZenlessSocket {
  if (socketInstance) return socketInstance;
  if (isMock) {
    const mockApi = getMockApi();
    if (!mockApi) throw new Error('Mock API not initialized');
    socketInstance = new MockZenlessSocket(mockApi);
  } else {
    const wsBase = resolveWsBase(import.meta.env.VITE_ZENLESS_WS_BASE);
    socketInstance = new RealZenlessSocket(wsBase);
  }
  return socketInstance;
}

export function resolveWsBase(override?: string): string {
  const configured = override?.trim();
  if (configured) return configured.replace(/\/$/, '');
  if (typeof window === 'undefined') return '';
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}`;
}

export function isMockMode() {
  return isMock;
}
