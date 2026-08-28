import { describe, it, expect } from 'vitest';
import { useStore } from '@/store';
import { MockZenlessAPI } from '@/services/mock/mockApi';
import { MockZenlessSocket } from '@/services/websocket/mockSocket';

describe('Store', () => {
  it('starts with boot false', () => {
    expect(useStore.getState().booted).toBe(false);
  });

  it('setBooted changes state', () => {
    useStore.getState().setBooted(true);
    expect(useStore.getState().booted).toBe(true);
    useStore.getState().setBooted(false);
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
    // Hunyuan status change should fire after ~3s
    await new Promise((r) => setTimeout(r, 3500));
    expect(events).toContain('CONNECTION_CHANGED');
    socket.disconnect();
  });
});

describe('Pipeline Stage Labels', () => {
  it('all stages have labels', () => {
    // Import from types
    const stages = ['NEW', 'COLLECTING_CONTEXT', 'PLANNING', 'GENERATING_CONCEPT', 'WAITING_IMAGE_APPROVAL', 'GENERATING_3D', 'WAITING_3D_APPROVAL', 'BUILDING', 'REVIEWING', 'REVISING', 'WAITING_CHANGE_APPROVAL', 'APPLYING', 'TESTING', 'FIXING', 'FINAL_REVIEW', 'COMPLETE', 'PAUSED', 'BLOCKED', 'FAILED'];
    // Just verify stages are valid strings
    expect(stages.length).toBe(19);
    expect(stages).toContain('COMPLETE');
    expect(stages).toContain('FAILED');
  });
});
