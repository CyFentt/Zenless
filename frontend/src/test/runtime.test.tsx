import { waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApplicationRuntime } from '@/runtime/ApplicationRuntime';
import { MockZenlessAPI } from '@/services/mock/mockApi';
import type { JobTimelineSnapshot, ZenlessAPI } from '@/services/api/types';
import type { ZenlessSocket } from '@/services/websocket/socket';
import { useStore } from '@/store';
import type { AgentInfo, ConnectionInfo, Job, SocketStatus, ZenlessEvent, ZenlessEventHandler } from '@/types';

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
  it('preserves a job created and selected while reconnect jobs are loading', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    vi.spyOn(api, 'bootstrap').mockResolvedValue({ steps: [{ stage: 'UI', state: 'READY' }] });
    const getJobs = vi.spyOn(api, 'getJobs').mockResolvedValue([]);
    const runtime = new ApplicationRuntime(api, socket);
    await runtime.start();
    let resolveJobs!: (jobs: Job[]) => void;
    getJobs.mockImplementationOnce(() => new Promise((resolve) => { resolveJobs = resolve; }));
    const hydration = runtime.rehydrate();
    const job: Job = { id: 'new-job', title: 'New job', status: 'NEW', stage: 'NEW', createdAt: 1, updatedAt: 1 };
    socket.emit({ type: 'JOB_CREATED', data: { jobId: job.id, job } });
    useStore.getState().setCurrentJobId(job.id);
    resolveJobs([]);
    await hydration;
    expect(useStore.getState().currentJobId).toBe(job.id);
    expect(useStore.getState().jobs).toContainEqual(job);
    runtime.stop();
  });

  it('preserves an existing stream and replays only new deltas during reconnect', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    vi.spyOn(api, 'bootstrap').mockResolvedValue({ steps: [{ stage: 'UI', state: 'READY' }] });
    const job: Job = { id: 'job-a', title: 'A', status: 'RUNNING', stage: 'PLANNING', createdAt: 1, updatedAt: 1 };
    vi.spyOn(api, 'getJobs').mockResolvedValue([job]);
    const timeline: JobTimelineSnapshot = {
      jobId: job.id, messages: [], activities: [], artifacts: [],
      test: { testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 }, cases: [], failures: [], logs: [] },
    };
    const getTimeline = vi.spyOn(api as ZenlessAPI, 'getTimeline').mockResolvedValue(timeline);
    const runtime = new ApplicationRuntime(api, socket);
    await runtime.start();
    socket.emit({ type: 'CHAT_STREAM_STARTED', data: { jobId: job.id, messageId: 'stream-a' } });
    socket.emit({ type: 'CHAT_STREAM_DELTA', data: { jobId: job.id, messageId: 'stream-a', delta: 'Before ' } });
    let resolveTimeline!: (value: JobTimelineSnapshot) => void;
    getTimeline.mockImplementationOnce(() => new Promise((resolve) => { resolveTimeline = resolve; }));
    const hydration = runtime.rehydrate();
    await waitFor(() => expect(resolveTimeline).toBeDefined());
    socket.emit({ type: 'CHAT_STREAM_DELTA', data: { jobId: job.id, messageId: 'stream-a', delta: 'after' } });
    resolveTimeline(timeline);
    await hydration;
    expect(useStore.getState().streamingContent).toBe('Before after');
    socket.emit({ type: 'CHAT_STREAM_FINISHED', data: { jobId: job.id, messageId: 'stream-a' } });
    expect(useStore.getState().messages.find((message) => message.id === 'stream-a')?.content).toBe('Before after');

    socket.emit({ type: 'CHAT_STREAM_STARTED', data: { jobId: job.id, messageId: 'stream-b' } });
    socket.emit({ type: 'CHAT_STREAM_DELTA', data: { jobId: job.id, messageId: 'stream-b', delta: 'Partial' } });
    getTimeline.mockImplementationOnce(() => new Promise((resolve) => { resolveTimeline = resolve; }));
    const completedHydration = runtime.rehydrate();
    await waitFor(() => expect(getTimeline).toHaveBeenCalledTimes(3));
    socket.emit({ type: 'CHAT_STREAM_FINISHED', data: { jobId: job.id, messageId: 'stream-b' } });
    resolveTimeline({ ...timeline, messages: [{ id: 'stream-b', jobId: job.id, role: 'zenless', content: 'Authoritative final', timestamp: 123 }] });
    await completedHydration;
    expect(useStore.getState().messages).toHaveLength(1);
    expect(useStore.getState().messages[0]).toMatchObject({ content: 'Authoritative final', timestamp: 123 });
    expect(useStore.getState().streamingMessageId).toBeNull();
    runtime.stop();
  });

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

    resolveConnections({ bridge: 'READY', browser: 'READY', chatgpt: 'LOGIN', deepseek: 'LOGIN', hunyuan: 'OFF', studio: 'READY' });
    resolveAgents([
      { id: 'chatgpt', name: 'ChatGPT', status: 'LOGIN' },
      { id: 'deepseek', name: 'DeepSeek', status: 'LOGIN' },
      { id: 'hunyuan', name: 'Hunyuan', status: 'OFF' },
      { id: 'studio', name: 'Roblox Studio', status: 'READY' },
    ]);
    await started;

    expect(useStore.getState().booted).toBe(true);
    expect(socket.disconnects).toBe(0);
    expect(useStore.getState().providers.map((provider) => provider.displayName)).toEqual(['ChatGPT']);
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

  it('keeps only the newest snapshot during an A to B to A selection race', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    vi.spyOn(api, 'bootstrap').mockResolvedValue({ steps: [{ stage: 'UI', state: 'READY' }] });
    vi.spyOn(api, 'getJobs').mockResolvedValue([]);
    const pending: Array<{
      jobId: string;
      signal?: AbortSignal;
      resolve: (snapshot: JobTimelineSnapshot) => void;
    }> = [];
    const runtime = new ApplicationRuntime(api, socket);
    await runtime.start();
    vi.spyOn(api as ZenlessAPI, 'getTimeline').mockImplementation((jobId, signal) => new Promise<JobTimelineSnapshot>((resolve) => {
      pending.push({ jobId, signal, resolve });
    }));

    useStore.getState().setCurrentJobId('job-a');
    useStore.getState().setCurrentJobId('job-b');
    useStore.getState().setCurrentJobId('job-a');
    const finalHydration = runtime.selectAndHydrateJob('job-a');

    expect(pending.map((request) => request.jobId)).toEqual(['job-a', 'job-b', 'job-a']);
    expect(pending[0].signal?.aborted).toBe(true);
    expect(pending[1].signal?.aborted).toBe(true);
    expect(pending[2].signal?.aborted).toBe(false);

    pending[2].resolve({
      jobId: 'job-a',
      messages: [{ id: 'message-a-final', role: 'zenless', content: 'Newest A snapshot', timestamp: 300, jobId: 'job-a' }],
      activities: [],
      artifacts: [],
      test: {
        testState: { status: 'STOPPED', elapsedMs: 30, fixAttempt: 0, maxFixAttempts: 3, resultStatus: 'PASSED' },
        cases: [],
        failures: [],
        logs: [],
      },
    });
    await finalHydration;
    expect(useStore.getState().messages.map((message) => message.id)).toEqual(['message-a-final']);

    pending[0].resolve({
      jobId: 'job-a',
      messages: [{ id: 'message-a-stale', role: 'zenless', content: 'Stale A snapshot', timestamp: 100, jobId: 'job-a' }],
      activities: [],
      artifacts: [],
      test: { testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 }, cases: [], failures: [], logs: [] },
    });
    pending[1].resolve({
      jobId: 'job-b',
      messages: [{ id: 'message-b-stale', role: 'zenless', content: 'Stale B snapshot', timestamp: 200, jobId: 'job-b' }],
      activities: [],
      artifacts: [],
      test: { testState: { status: 'FAILED', elapsedMs: 20, fixAttempt: 1, maxFixAttempts: 3 }, cases: [], failures: [], logs: [] },
    });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(useStore.getState().currentJobId).toBe('job-a');
    expect(useStore.getState().messages.map((message) => message.id)).toEqual(['message-a-final']);
    expect(useStore.getState().testState.resultStatus).toBe('PASSED');
    runtime.stop();
  });

  it('replays current-job WebSocket deltas received during REST hydration', async () => {
    const api = new MockZenlessAPI();
    const socket = new RuntimeSocket();
    vi.spyOn(api, 'bootstrap').mockResolvedValue({ steps: [{ stage: 'UI', state: 'READY' }] });
    vi.spyOn(api, 'getJobs').mockResolvedValue([]);
    let resolveTimeline!: (snapshot: JobTimelineSnapshot) => void;
    vi.spyOn(api as ZenlessAPI, 'getTimeline').mockImplementation(() => new Promise<JobTimelineSnapshot>((resolve) => {
      resolveTimeline = resolve;
    }));
    const runtime = new ApplicationRuntime(api, socket);
    await runtime.start();

    useStore.getState().setCurrentJobId('job-a');
    const hydration = runtime.selectAndHydrateJob('job-a');
    socket.emit({
      type: 'CHAT_MESSAGE',
      data: {
        jobId: 'job-a',
        message: { id: 'message-live', role: 'zenless', content: 'Live update', timestamp: 200, jobId: 'job-a' },
      },
    });
    resolveTimeline({
      jobId: 'job-a',
      messages: [{ id: 'message-snapshot', role: 'user', content: 'Snapshot', timestamp: 100, jobId: 'job-a' }],
      activities: [],
      artifacts: [],
      test: { testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 }, cases: [], failures: [], logs: [] },
    });
    await hydration;

    expect(useStore.getState().messages.map((message) => message.id)).toEqual(['message-snapshot', 'message-live']);
    runtime.stop();
  });
});
