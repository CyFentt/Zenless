import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HomePage } from '@/features/home/HomePage';
import { ApplicationRuntime } from '@/runtime/AppRuntime';
import { MockZenlessAPI } from '@/services/mock/mockApi';
import type { ZenlessSocket } from '@/services/websocket/socket';
import { useStore } from '@/store';
import type { AgentInfo, ConnectionInfo, SocketStatus, ZenlessEvent, ZenlessEventHandler } from '@/types';

type StatusHandler = (status: SocketStatus) => void;

class RuntimeSocket implements ZenlessSocket {
  private status: SocketStatus = 'DISCONNECTED';
  private eventHandlers = new Set<ZenlessEventHandler>();
  private statusHandlers = new Set<StatusHandler>();
  disconnects = 0;

  connect(): void {
    this.emitStatus('CONNECTING');
    this.emitStatus('CONNECTED');
  }

  disconnect(): void {
    this.disconnects += 1;
    this.emitStatus('DISCONNECTED');
  }

  on(event: 'event', handler: ZenlessEventHandler): () => void;
  on(event: 'status', handler: StatusHandler): () => void;
  on(event: 'event' | 'status', handler: ZenlessEventHandler | StatusHandler): () => void {
    if (event === 'event') {
      this.eventHandlers.add(handler as ZenlessEventHandler);
      return () => this.eventHandlers.delete(handler as ZenlessEventHandler);
    }
    this.statusHandlers.add(handler as StatusHandler);
    return () => this.statusHandlers.delete(handler as StatusHandler);
  }

  getStatus(): SocketStatus {
    return this.status;
  }

  emit(event: ZenlessEvent): void {
    this.eventHandlers.forEach((handler) => handler(event));
  }

  emitStatus(status: SocketStatus): void {
    this.status = status;
    this.statusHandlers.forEach((handler) => handler(status));
  }
}

const initialState = useStore.getState();

beforeEach(() => useStore.setState(initialState, true));

describe('ApplicationRuntime', () => {
  it('finishes delayed hydration before leaving the splash and keeps the socket alive', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    let resolveConnections!: (value: ConnectionInfo) => void;
    let resolveAgents!: (value: AgentInfo[]) => void;
    const connections = new Promise<ConnectionInfo>((resolve) => { resolveConnections = resolve; });
    const agents = new Promise<AgentInfo[]>((resolve) => { resolveAgents = resolve; });
    vi.spyOn(api, 'bootstrap').mockResolvedValue({ steps: [{ stage: 'UI', state: 'READY' }] });
    vi.spyOn(api, 'getConnections').mockReturnValue(connections);
    vi.spyOn(api, 'getAgents').mockReturnValue(agents);
    vi.spyOn(api, 'getJobs').mockResolvedValue([]);
    const runtime = new ApplicationRuntime(api, socket);
    const started = runtime.start();

    await waitFor(() => expect(socket.getStatus()).toBe('CONNECTED'));
    expect(useStore.getState().booted).toBe(false);
    expect(socket.disconnects).toBe(0);

    resolveConnections({ bridge: 'READY', browser: 'READY', chatgpt: 'LOGIN', deepseek: 'LOGIN', gemini: 'LOGIN', hunyuan: 'OFF', studio: 'READY' });
    resolveAgents([
      { id: 'chatgpt', name: 'External Name', status: 'LOGIN' },
      { id: 'deepseek', name: 'External Name', status: 'LOGIN' },
      { id: 'hunyuan', name: 'External Name', status: 'OFF' },
      { id: 'studio', name: 'External Name', status: 'READY' },
    ]);
    await started;

    expect(useStore.getState().booted).toBe(true);
    expect(socket.disconnects).toBe(0);
    render(<HomePage />);
    expect(screen.getByText('Builder')).toBeInTheDocument();
    expect(screen.getByText('Reviewer')).toBeInTheDocument();
    expect(screen.getByText('3D Generator')).toBeInTheDocument();
    runtime.stop();
    expect(socket.disconnects).toBe(1);
  });

  it('rehydrates the authoritative snapshot after reconnect', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    vi.spyOn(api, 'bootstrap').mockResolvedValue({ steps: [{ stage: 'UI', state: 'READY' }] });
    vi.spyOn(api, 'getJobs').mockResolvedValue([]);
    const getAgents = vi.spyOn(api, 'getAgents');
    const runtime = new ApplicationRuntime(api, socket);
    await runtime.start();
    const initialCalls = getAgents.mock.calls.length;

    socket.emitStatus('DISCONNECTED');
    socket.emitStatus('CONNECTED');
    await waitFor(() => expect(getAgents.mock.calls.length).toBeGreaterThan(initialCalls));
    expect(useStore.getState().socketStatus).toBe('CONNECTED');
    runtime.stop();
  });

  it('preserves a new Studio connection when an older startup snapshot finishes later', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    vi.spyOn(api, 'bootstrap').mockResolvedValue({ steps: [{ stage: 'UI', state: 'READY' }] });
    vi.spyOn(api, 'getJobs').mockResolvedValue([]);
    let release!: (value: { state: 'OFFLINE'; projectName: string }) => void;
    const snapshot = vi.spyOn(api, 'getStudioState').mockReturnValue(new Promise((resolve) => { release = resolve; }));
    const runtime = new ApplicationRuntime(api, socket);
    const started = runtime.start();
    await waitFor(() => expect(snapshot).toHaveBeenCalled());
    socket.emit({ type: 'STUDIO_STATE_CHANGED', data: { state: 'ONLINE', projectName: 'New place' } });
    socket.emit({ type: 'STUDIO_TREE_UPDATED', data: { tree: [{ id: 'Workspace', name: 'Workspace', className: 'Workspace', path: 'Workspace' }] } });
    release({ state: 'OFFLINE', projectName: '' });
    await started;
    expect(useStore.getState().studioState).toBe('ONLINE');
    expect(useStore.getState().studioProjectName).toBe('New place');
    expect(useStore.getState().studioTree.map((node) => node.id)).toEqual(['Workspace']);
    runtime.stop();
  });
});

describe('startup failure isolation', () => {
  it('opens the shell when a saved task cannot be restored', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    vi.spyOn(api, 'bootstrap').mockResolvedValue({ steps: [{ stage: 'UI', state: 'READY' }] });
    vi.spyOn(api, 'getJobs').mockResolvedValue([{ id: 'broken', title: 'Saved task', status: 'RUNNING', stage: 'BUILDING' } as never]);
    vi.spyOn(api, 'getMessages').mockRejectedValue(new Error('Saved task unavailable'));
    const runtime = new ApplicationRuntime(api, socket);
    await runtime.start();
    expect(useStore.getState().booted).toBe(true);
    expect(useStore.getState().diagnostics.some((d) => d.message.includes('Failed to restore'))).toBe(true);
    runtime.stop();
  });

  it('does not connect after being stopped during bootstrap', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    const connect = vi.spyOn(socket, 'connect');
    let release!: (value: { steps: [] }) => void;
    vi.spyOn(api, 'bootstrap').mockReturnValue(new Promise((resolve) => { release = resolve; }));
    const runtime = new ApplicationRuntime(api, socket);
    const started = runtime.start();
    runtime.stop();
    release({ steps: [] });
    await started;
    expect(connect).not.toHaveBeenCalled();
    expect(useStore.getState().booted).toBe(false);
  });
});
