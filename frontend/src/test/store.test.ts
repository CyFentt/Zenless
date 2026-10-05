import { beforeEach, describe, it, expect } from 'vitest';
import { useStore } from '@/store';
import { MockZenlessAPI } from '@/services/mock/mockApi';
import { MockZenlessSocket } from '@/services/websocket/mockSocket';
import { handleEvent } from '@/store/eventHandler';

const initialState = useStore.getState();

beforeEach(() => useStore.setState(initialState, true));

describe('Store', () => {
  it('starts with boot false', () => {
    expect(useStore.getState().booted).toBe(false);
  });

  it('boots only after backend readiness and frontend hydration', () => {
    useStore.getState().setBackendReady(true);
    expect(useStore.getState().booted).toBe(false);
    useStore.getState().setRuntimeHydrated(true);
    expect(useStore.getState().booted).toBe(true);
    useStore.getState().setRuntimeHydrated(false);
  });

  it('preserves a boot stage received before the bootstrap snapshot', () => {
    useStore.getState().setBootSteps([]);
    handleEvent({ type: 'BOOT_STAGE_CHANGED', data: { stage: 'STATE', state: 'READY' } });
    expect(useStore.getState().bootSteps).toEqual([{ stage: 'STATE', state: 'READY' }]);
  });

  it('setActivePage changes page', () => {
    useStore.getState().setActivePage('chat');
    expect(useStore.getState().activePage).toBe('chat');
    useStore.getState().setActivePage('home');
  });

  it('addMessage appends to messages', () => {
    const initial = useStore.getState().messages.length;
    useStore.getState().addMessage({ id: 'test1', role: 'user', content: 'test', timestamp: Date.now() });
    expect(useStore.getState().messages.length).toBe(initial + 1);
  });

  it('streaming lifecycle works', () => {
    useStore.getState().setStreaming('msg_stream');
    expect(useStore.getState().streamingMessageId).toBe('msg_stream');
    useStore.getState().appendStreamDelta('Hello ');
    useStore.getState().appendStreamDelta('world');
    expect(useStore.getState().streamingContent).toBe('Hello world');
    useStore.getState().finishStream();
    expect(useStore.getState().streamingMessageId).toBeNull();
    const last = useStore.getState().messages[useStore.getState().messages.length - 1];
    expect(last.content).toBe('Hello world');
    expect(last.role).toBe('zenless');
  });

  it('setConnections merges partial updates', () => {
    useStore.getState().setConnections({ chatgpt: 'READY' });
    expect(useStore.getState().connections.chatgpt).toBe('READY');
    useStore.getState().setConnections({ deepseek: 'ERR' });
    expect(useStore.getState().connections.deepseek).toBe('ERR');
    expect(useStore.getState().connections.chatgpt).toBe('READY');
  });

  it('upserts agent status events without an initial snapshot', () => {
    useStore.setState({ agents: [] });
    handleEvent({ type: 'AGENT_STATUS_CHANGED', data: { agent: 'chatgpt', status: 'LOGIN' } });
    expect(useStore.getState().agents.find((agent) => agent.id === 'chatgpt')).toMatchObject({ name: 'ChatGPT', status: 'LOGIN' });
    handleEvent({ type: 'AGENT_STATUS_CHANGED', data: { agent: 'chatgpt', status: 'READY' } });
    expect(useStore.getState().agents.filter((agent) => agent.id === 'chatgpt')).toEqual([
      expect.objectContaining({ name: 'ChatGPT', status: 'READY' }),
    ]);
  });

  it('deduplicates messages by authoritative ID', () => {
    const message = { id: 'msg-1', role: 'zenless' as const, content: 'Ready', timestamp: 100 };
    useStore.getState().setMessages([message, { ...message, content: 'Updated' }]);
    expect(useStore.getState().messages).toEqual([{ ...message, content: 'Updated' }]);
    useStore.getState().addMessage({ ...message, content: 'Final' });
    expect(useStore.getState().messages).toEqual([{ ...message, content: 'Final' }]);
  });

  it('releases a completed standalone test when switching jobs but preserves a running one', () => {
    useStore.setState({
      activeTestJobId: 'manual-test',
      testState: { status: 'STOPPED', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 },
    });
    useStore.getState().setCurrentJobId('other-job');
    expect(useStore.getState().activeTestJobId).toBeNull();

    useStore.setState({
      activeTestJobId: 'manual-test',
      testState: { status: 'RUNNING', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 },
    });
    useStore.getState().setCurrentJobId('another-job');
    expect(useStore.getState().activeTestJobId).toBe('manual-test');
  });

  it('addTestLog appends', () => {
    const initial = useStore.getState().testLogs.length;
    useStore.getState().addTestLog({ id: 'log_test', timestamp: Date.now(), level: 'ERR', message: 'test' });
    expect(useStore.getState().testLogs.length).toBe(initial + 1);
  });

  it('ignores chat stream and message events from an unselected job', () => {
    useStore.setState({
      currentJobId: 'job-a',
      messages: [],
      activities: [],
      streamingMessageId: null,
      streamingContent: '',
    });

    handleEvent({ type: 'CHAT_STREAM_STARTED', data: { messageId: 'stream-b', jobId: 'job-b' } });
    handleEvent({ type: 'CHAT_STREAM_DELTA', data: { messageId: 'stream-b', jobId: 'job-b', delta: 'stale' } });
    handleEvent({
      type: 'CHAT_MESSAGE',
      data: { message: { id: 'msg-b', role: 'zenless', content: 'stale', timestamp: 10, jobId: 'job-b' } },
    });

    expect(useStore.getState().streamingMessageId).toBeNull();
    expect(useStore.getState().streamingContent).toBe('');
    expect(useStore.getState().messages).toHaveLength(0);
  });

  it('ignores QA events from a different active test job', () => {
    useStore.getState().resetTestDetails();
    useStore.getState().setTestLogs([]);
    useStore.setState({ activeTestJobId: 'job-a' });

    handleEvent({
      type: 'TEST_CASE_STARTED',
      data: {
        jobId: 'job-b',
        testCase: { id: 'case-stale', name: 'stale', suite: 'PlayTest', status: 'RUNNING', startedAt: 100 },
      },
    });
    handleEvent({
      type: 'TEST_LOG',
      data: {
        jobId: 'job-b',
        log: { id: 'log-stale', timestamp: 100, level: 'ERR', message: 'stale' },
      },
    });

    expect(useStore.getState().testCases).toHaveLength(0);
    expect(useStore.getState().testLogs).toHaveLength(0);
  });

  it('addJob prepends to jobs', () => {
    const initial = useStore.getState().jobs.length;
    useStore.getState().addJob({ id: 'job_test', title: 'Test', status: 'NEW', stage: 'NEW', createdAt: Date.now(), updatedAt: Date.now() });
    expect(useStore.getState().jobs.length).toBe(initial + 1);
    expect(useStore.getState().jobs[0].id).toBe('job_test');
  });

  it('tracks structured test case lifecycle events', () => {
    useStore.getState().resetTestDetails();
    handleEvent({
      type: 'TEST_CASE_STARTED',
      data: { testCase: { id: 'case_1', name: 'spawns player', suite: 'PlayTest', status: 'RUNNING', startedAt: 100 } },
    });
    handleEvent({
      type: 'TEST_CASE_FINISHED',
      data: { testCase: { id: 'case_1', name: 'spawns player', suite: 'PlayTest', status: 'PASSED', startedAt: 100, finishedAt: 140, durationMs: 40 } },
    });
    expect(useStore.getState().testCases).toHaveLength(1);
    expect(useStore.getState().testCases[0]).toMatchObject({ id: 'case_1', status: 'PASSED', durationMs: 40 });
  });

  it('stores TEST_FAILURE details and exposes them as an error log', () => {
    useStore.getState().resetTestDetails();
    useStore.getState().setTestLogs([]);
    handleEvent({
      type: 'TEST_FAILURE',
      data: {
        failure: {
          id: 'failure_1',
          testCaseId: 'case_1',
          suite: 'PlayTest',
          message: 'Expected humanoid to spawn',
          timestamp: 200,
          expected: { count: 1 },
          actual: { count: 0 },
          file: 'Spawn.spec.luau',
          line: 12,
        },
      },
    });
    expect(useStore.getState().testFailures[0].actual).toEqual({ count: 0 });
    expect(useStore.getState().testLogs[0]).toMatchObject({
      level: 'ERR',
      testCaseId: 'case_1',
      expected: { count: 1 },
      actual: { count: 0 },
    });
  });
});

describe('MockZenlessSocket', () => {
  it('connects and sets CONNECTED status', async () => {
    const api = new MockZenlessAPI();
    const socket = new MockZenlessSocket(api);
    expect(socket.getStatus()).toBe('DISCONNECTED');
    socket.connect();
    expect(socket.getStatus()).toBe('CONNECTING');
    await new Promise((r) => setTimeout(r, 700));
    expect(socket.getStatus()).toBe('CONNECTED');
    socket.disconnect();
  });

  it('disconnect sets DISCONNECTED', () => {
    const api = new MockZenlessAPI();
    const socket = new MockZenlessSocket(api);
    socket.connect();
    socket.disconnect();
    expect(socket.getStatus()).toBe('DISCONNECTED');
  });

  it('emits events to handlers', async () => {
    const api = new MockZenlessAPI();
    const socket = new MockZenlessSocket(api);
    const events: string[] = [];
    socket.on('event', (event: { type: string }) => events.push(event.type));
    socket.connect();
    await new Promise((r) => setTimeout(r, 700));
    await new Promise((r) => setTimeout(r, 3500));
    expect(events).toContain('CONNECTION_CHANGED');
    socket.disconnect();
  });
});

describe('Pipeline Stage Labels', () => {
  it('all stages have labels', () => {
    const stages = ['NEW', 'COLLECTING_CONTEXT', 'PLANNING', 'GENERATING_CONCEPT', 'WAITING_IMAGE_APPROVAL', 'GENERATING_3D', 'WAITING_3D_APPROVAL', 'BUILDING', 'REVIEWING', 'REVISING', 'WAITING_CHANGE_APPROVAL', 'APPLYING', 'TESTING', 'FIXING', 'FINAL_REVIEW', 'COMPLETE', 'PAUSED', 'BLOCKED', 'FAILED'];
    expect(stages.length).toBe(19);
    expect(stages).toContain('COMPLETE');
    expect(stages).toContain('FAILED');
  });
});


describe('Frontend diagnostics', () => {
  it('deduplicates the same diagnostic fingerprint', async () => {
    const { frontendDiagnostics } = await import('@/services/diagnostics');
    const marker = `dedup-${Date.now()}`;
    const first = frontendDiagnostics.report('warning', 'test', marker);
    const second = frontendDiagnostics.report('warning', 'test', marker);
    expect(second?.id).toBe(first?.id);
    expect(second?.occurrenceCount).toBe(2);
  });
});
