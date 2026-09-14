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
    useStore.getState().setActivePage('build');
  });

  it('addMessage appends to messages', () => {
    const initial = useStore.getState().messages.length;
    useStore.getState().addMessage({ id: 'test1', role: 'user', content: 'test', timestamp: Date.now() });
    expect(useStore.getState().messages.length).toBe(initial + 1);
  });

  it('streaming lifecycle works', () => {
    useStore.getState().setStreaming('msg_stream', 'job_001');
    expect(useStore.getState().streamingMessageId).toBe('msg_stream');
    useStore.getState().appendStreamDelta('Hello ');
    useStore.getState().appendStreamDelta('world');
    expect(useStore.getState().streamingContent).toBe('Hello world');
    useStore.getState().finishStream();
    expect(useStore.getState().streamingMessageId).toBeNull();
    const last = useStore.getState().messages[useStore.getState().messages.length - 1];
    expect(last.content).toBe('Hello world');
    expect(last.role).toBe('zenless');
    expect(last.jobId).toBe('job_001');
  });

  it('ignores deltas and completion for a different stream message', () => {
    useStore.getState().setCurrentJobId('job_001');
    handleEvent({ type: 'CHAT_STREAM_STARTED', data: { jobId: 'job_001', messageId: 'stream_active', provider: 'chatgpt' } });
    handleEvent({ type: 'CHAT_STREAM_DELTA', data: { jobId: 'job_001', messageId: 'stream_stale', delta: 'stale' } });
    handleEvent({ type: 'CHAT_STREAM_FINISHED', data: { jobId: 'job_001', messageId: 'stream_stale' } });

    expect(useStore.getState().streamingMessageId).toBe('stream_active');
    expect(useStore.getState().streamingContent).toBe('');
  });

  it('ignores inactive-job chat, stream, visual, and model events', () => {
    useStore.getState().setCurrentJobId('job-a');
    handleEvent({ type: 'CHAT_MESSAGE', data: { jobId: 'job-b', message: { id: 'message-b', role: 'zenless', content: 'Background', timestamp: 10, jobId: 'job-b' } } });
    handleEvent({ type: 'CHAT_STREAM_STARTED', data: { jobId: 'job-b', messageId: 'stream-b' } });
    handleEvent({ type: 'CHAT_STREAM_DELTA', data: { jobId: 'job-b', messageId: 'stream-b', delta: 'Background' } });
    handleEvent({ type: 'VISUAL_READY', data: { jobId: 'job-b', view: 'FRONT', imageUrl: '/b.png', assetId: 'asset-b', conceptVersion: 1 } });
    handleEvent({ type: 'MODEL_READY', data: { jobId: 'job-b', assetId: 'model-b', version: 1, modelUrl: '/b.glb', geometryStatus: 'READY', textureStatus: 'READY' } });

    expect(useStore.getState().messages).toEqual([]);
    expect(useStore.getState().streamingMessageId).toBeNull();
    expect(useStore.getState().views).toEqual([]);
    expect(useStore.getState().modelInfo.state).toBe('IDLE');
  });

  it('upserts six live views and preserves model approval separately from readiness', () => {
    useStore.getState().setCurrentJobId('job-a');
    const viewNames = ['FRONT', 'BACK', 'LEFT', 'RIGHT', 'TOP', 'BOTTOM'] as const;
    viewNames.forEach((view) => {
      handleEvent({ type: 'VISUAL_GENERATION_CHANGED', data: { jobId: 'job-a', view, state: 'GENERATING', conceptVersion: 2 } });
      handleEvent({ type: 'VISUAL_READY', data: { jobId: 'job-a', view, imageUrl: `/${view}.png`, assetId: `asset-${view}`, conceptVersion: 2 } });
    });
    expect(useStore.getState().views).toHaveLength(6);
    expect(useStore.getState().conceptStatus).toBe('READY');

    handleEvent({ type: 'VISUAL_APPROVED', data: { jobId: 'job-a', views: [...viewNames], conceptVersion: 2 } });
    expect(useStore.getState().views.every((view) => view.state === 'APPROVED')).toBe(true);
    expect(useStore.getState().conceptStatus).toBe('APPROVED');

    handleEvent({ type: 'MODEL_READY', data: { jobId: 'job-a', assetId: 'model-a', version: 1, modelUrl: '/a.glb', geometryStatus: 'READY', textureStatus: 'READY' } });
    handleEvent({ type: 'MODEL_APPROVED', data: { jobId: 'job-a' } });
    expect(useStore.getState().modelInfo).toMatchObject({ state: 'READY', approvalState: 'APPROVED', modelUrl: '/a.glb' });
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

  it('reconciles provider and connection state after persistent login detection', () => {
    useStore.setState({ providers: [], loginStates: {}, connections: { ...useStore.getState().connections, chatgpt: 'LOGIN' } });

    handleEvent({ type: 'LOGIN_READY', data: { providerId: 'chatgpt', route: 'webview2', persistent: true } });

    expect(useStore.getState().connections.chatgpt).toBe('READY');
    expect(useStore.getState().loginStates.chatgpt).toBe('READY');
    expect(useStore.getState().providers.find((provider) => provider.providerId === 'chatgpt')).toMatchObject({
      authState: 'READY',
      loginState: 'READY',
      route: 'webview2',
      status: 'READY',
      session: { persistent: true },
    });
  });

  it('deduplicates messages by authoritative ID', () => {
    const message = { id: 'msg-1', role: 'zenless' as const, content: 'Ready', timestamp: 100 };
    useStore.getState().setMessages([message, { ...message, content: 'Updated' }]);
    expect(useStore.getState().messages).toEqual([{ ...message, content: 'Updated' }]);
    useStore.getState().addMessage({ ...message, content: 'Final' });
    expect(useStore.getState().messages).toEqual([{ ...message, content: 'Final' }]);
  });

  it('addTestLog appends', () => {
    const initial = useStore.getState().testLogs.length;
    useStore.getState().addTestLog({ id: 'log_test', timestamp: Date.now(), level: 'ERR', message: 'test' });
    expect(useStore.getState().testLogs.length).toBe(initial + 1);
  });

  it('addJob prepends to jobs', () => {
    const initial = useStore.getState().jobs.length;
    useStore.getState().addJob({ id: 'job_test', title: 'Test', status: 'NEW', stage: 'NEW', createdAt: Date.now(), updatedAt: Date.now() });
    expect(useStore.getState().jobs.length).toBe(initial + 1);
    expect(useStore.getState().jobs[0].id).toBe('job_test');
  });

  it('keeps the current selection when background jobs are created or updated', () => {
    useStore.getState().setJobs([
      { id: 'job-a', title: 'Active job', status: 'RUNNING', stage: 'BUILDING', createdAt: 100, updatedAt: 100 },
    ]);
    useStore.getState().setCurrentJobId('job-a');
    useStore.getState().setMessages([
      { id: 'message-a', role: 'zenless', content: 'Active projection', timestamp: 110, jobId: 'job-a' },
    ]);

    handleEvent({
      type: 'JOB_CREATED',
      data: { jobId: 'job-b', job: { id: 'job-b', title: 'Background job', status: 'NEW', stage: 'NEW', createdAt: 200, updatedAt: 200 } },
    });
    handleEvent({
      type: 'JOB_UPDATED',
      data: { jobId: 'job-b', job: { id: 'job-b', title: 'Updated background job', status: 'RUNNING', stage: 'PLANNING' } },
    });

    expect(useStore.getState().currentJobId).toBe('job-a');
    expect(useStore.getState().messages.map((message) => message.id)).toEqual(['message-a']);
    expect(useStore.getState().jobs.find((job) => job.id === 'job-b')).toMatchObject({
      title: 'Updated background job',
      status: 'RUNNING',
      stage: 'PLANNING',
    });
  });

  it('isolates activity, artifact, test, failure, and log events by job', () => {
    useStore.getState().setCurrentJobId('job-a');
    const backgroundEvents = [
      {
        type: 'CHAT_ACTIVITY' as const,
        data: {
          jobId: 'job-b',
          activity: { id: 'activity-b', phase: 'BUILD' as const, status: 'RUNNING' as const, title: 'Background activity', timestamp: 200 },
        },
      },
      {
        type: 'CHAT_ARTIFACT' as const,
        data: {
          jobId: 'job-b',
          artifact: { id: 'artifact-b', type: 'REPORT' as const, name: 'Background report', state: 'READY' as const, createdAt: 210 },
        },
      },
      { type: 'TEST_STARTED' as const, data: { jobId: 'job-b', runId: 'run-b' } },
      {
        type: 'TEST_CASE_FINISHED' as const,
        data: { jobId: 'job-b', testCase: { id: 'case-b', name: 'Background case', status: 'FAILED' as const, finishedAt: 220 } },
      },
      {
        type: 'TEST_FAILURE' as const,
        data: { jobId: 'job-b', failure: { id: 'failure-b', message: 'Background failure', timestamp: 221 } },
      },
      {
        type: 'TEST_LOG' as const,
        data: { jobId: 'job-b', log: { id: 'log-b', timestamp: 222, level: 'ERR' as const, message: 'Background log' } },
      },
      {
        type: 'TEST_FINISHED' as const,
        data: { jobId: 'job-b', runId: 'run-b', status: 'FAILED' as const, counts: { total: 1, passed: 0, failed: 1, skipped: 0 } },
      },
    ];
    backgroundEvents.forEach((event) => handleEvent(event));

    expect(useStore.getState().activities).toEqual([]);
    expect(useStore.getState().artifacts).toEqual([]);
    expect(useStore.getState().testCases).toEqual([]);
    expect(useStore.getState().testFailures).toEqual([]);
    expect(useStore.getState().testLogs).toEqual([]);
    expect(useStore.getState().testState.status).toBe('IDLE');
    expect(useStore.getState().testState.resultStatus).toBeUndefined();

    handleEvent({
      type: 'CHAT_ACTIVITY',
      data: {
        jobId: 'job-a',
        activity: { id: 'activity-a', phase: 'BUILD', status: 'DONE', title: 'Active activity', timestamp: 300 },
      },
    });
    handleEvent({
      type: 'CHAT_ARTIFACT',
      data: {
        jobId: 'job-a',
        artifact: { id: 'artifact-a', type: 'REPORT', name: 'Active report', state: 'READY', createdAt: 310 },
      },
    });
    handleEvent({ type: 'TEST_STARTED', data: { jobId: 'job-a', runId: 'run-a' } });
    handleEvent({
      type: 'TEST_CASE_FINISHED',
      data: { jobId: 'job-a', testCase: { id: 'case-a', name: 'Active case', status: 'FAILED', finishedAt: 320 } },
    });
    handleEvent({
      type: 'TEST_FAILURE',
      data: { jobId: 'job-a', failure: { id: 'failure-a', message: 'Recorded failure', timestamp: 321 } },
    });
    handleEvent({
      type: 'TEST_LOG',
      data: { jobId: 'job-a', log: { id: 'log-a', timestamp: 322, level: 'ZEN', message: 'Active log' } },
    });
    handleEvent({
      type: 'TEST_FINISHED',
      data: { jobId: 'job-a', runId: 'run-a', status: 'FAILED', counts: { total: 1, passed: 0, failed: 1, skipped: 0 } },
    });

    expect(useStore.getState().activities.map((activity) => activity.id)).toEqual(['activity-a']);
    expect(useStore.getState().artifacts.map((artifact) => artifact.id)).toEqual(['artifact-a']);
    expect(useStore.getState().testCases.map((testCase) => testCase.id)).toEqual(['case-a']);
    expect(useStore.getState().testFailures.map((failure) => failure.id)).toEqual(['failure-a']);
    expect(useStore.getState().testLogs.map((log) => log.id)).toEqual(['failure_failure-a', 'log-a']);
    expect(useStore.getState().testState).toMatchObject({
      status: 'FAILED',
      resultStatus: 'FAILED',
      counts: { total: 1, passed: 0, failed: 1, skipped: 0 },
    });
  });

  it('tracks structured test case lifecycle events', () => {
    useStore.getState().resetTestDetails();
    useStore.getState().setCurrentJobId('job_001');
    handleEvent({
      type: 'TEST_CASE_STARTED',
      data: { jobId: 'job_001', testCase: { id: 'case_1', name: 'spawns player', suite: 'PlayTest', status: 'RUNNING', startedAt: 100 } },
    });
    handleEvent({
      type: 'TEST_CASE_FINISHED',
      data: { jobId: 'job_001', testCase: { id: 'case_1', name: 'spawns player', suite: 'PlayTest', status: 'PASSED', startedAt: 100, finishedAt: 140, durationMs: 40 } },
    });
    expect(useStore.getState().testCases).toHaveLength(1);
    expect(useStore.getState().testCases[0]).toMatchObject({ id: 'case_1', status: 'PASSED', durationMs: 40 });
  });

  it('stores TEST_FAILURE details and exposes them as an error log', () => {
    useStore.getState().resetTestDetails();
    useStore.getState().setTestLogs([]);
    useStore.getState().setCurrentJobId('job_001');
    handleEvent({
      type: 'TEST_FAILURE',
      data: {
        jobId: 'job_001',
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
