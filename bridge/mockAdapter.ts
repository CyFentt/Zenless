import { createMockState, type MockState } from './types';

export function createMockAdapter() {
  const state: MockState = createMockState();
  const subscribers = new Set<(event: { type: string; data: unknown }) => void>();

  function emit(type: string, data: unknown) {
    subscribers.forEach((fn) => fn({ type, data }));
  }

  function uid(prefix: string): string {
    return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
  }

  const adapter = {
    state,
    subscribe(fn: (event: { type: string; data: unknown }) => void): () => void {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },

    // Boot
    bootstrap() {
      return { steps: state.bootSteps };
    },
    getStatus() {
      return { ready: true };
    },

    // Connections
    getConnections() { return state.connections; },
    getAgents() { return state.agents; },

    // Jobs
    getJobs() { return state.jobs; },
    getJob(id: string) { return state.jobs.find((j) => j.id === id); },
    createJob(title: string, options?: Partial<{ visualFirst: boolean; create3D: boolean; review: boolean; autoTest: boolean; autoFix: boolean; approval: boolean; risk: string; revisions: number; fixAttempts: number }>) {
      const job = {
        id: uid('job'),
        title,
        status: 'RUNNING' as const,
        stage: 'COLLECTING_CONTEXT' as const,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        options,
      };
      state.jobs.unshift(job);
      emit('JOB_CREATED', { job });
      return job;
    },
    pauseJob(id: string) {
      const job = state.jobs.find((j) => j.id === id);
      if (job) { job.status = 'PAUSED'; job.stage = 'PAUSED'; job.updatedAt = Date.now(); emit('JOB_UPDATED', { job: { id } }); }
      return job;
    },
    resumeJob(id: string) {
      const job = state.jobs.find((j) => j.id === id);
      if (job) { job.status = 'RUNNING'; job.stage = 'BUILDING'; job.updatedAt = Date.now(); emit('JOB_UPDATED', { job: { id } }); }
      return job;
    },
    cancelJob(id: string) {
      state.jobs = state.jobs.filter((j) => j.id !== id);
      return { ok: true };
    },

    // Chat
    sendMessage(content: string, jobId?: string) {
      const msg = { id: uid('msg'), role: 'user' as const, content, timestamp: Date.now(), jobId };
      state.messages.push(msg);
      // Simulate response
      setTimeout(() => {
        const responseId = uid('msg');
        emit('CHAT_STREAM_STARTED', { messageId: responseId, jobId });
        const text = 'Analyzing request. Proposing changes for your approval.';
        const words = text.split(' ');
        let idx = 0;
        const timer = setInterval(() => {
          if (idx >= words.length) {
            clearInterval(timer);
            emit('CHAT_STREAM_FINISHED', { messageId: responseId });
            return;
          }
          emit('CHAT_STREAM_DELTA', { messageId: responseId, delta: (idx === 0 ? '' : ' ') + words[idx] });
          idx++;
        }, 100);
      }, 500);
      return { messageId: msg.id, jobId };
    },
    cancelGeneration() { return { ok: true }; },

    // Context
    getContext() { return state.context; },
    refreshContext() { return state.context; },
    includeContext(id: string) {
      const item = state.context.find((c) => c.id === id);
      if (item) item.state = 'included';
      return { ok: true };
    },
    excludeContext(id: string) {
      const item = state.context.find((c) => c.id === id);
      if (item) item.state = 'excluded';
      return { ok: true };
    },
    lockContext(id: string) {
      const item = state.context.find((c) => c.id === id);
      if (item) item.state = 'locked';
      return { ok: true };
    },
    unlockContext(id: string) {
      const item = state.context.find((c) => c.id === id);
      if (item) item.state = 'included';
      return { ok: true };
    },
    inspectContext(id: string) { return state.context.find((c) => c.id === id); },

    // Changes
    getChanges() { return state.changes; },
    getReview() { return { files: state.changes, ready: true }; },
    approveChanges() { return { ok: true }; },
    rejectChanges() { return { ok: true }; },
    editChanges() { return { ok: true }; },

    // Visual
    getVisual() {
      return { views: state.views, concept: { version: 3, status: 'READY', prompt: 'Industrial bomb device' } };
    },
    approveVisual() { return { ok: true }; },
    editConcept() { return { ok: true }; },
    regenerateVisual() { return { ok: true }; },
    regenerateView() { return { ok: true }; },

    // Model
    getModel() { return state.model; },
    approveModel() { return { ok: true }; },
    regenerateGeometry() { return { ok: true }; },
    regenerateTexture() { return { ok: true }; },

    // Assets
    getAssets() { return state.assets; },

    // Studio
    getStudioState() { return { state: state.studioState }; },
    getStudioTree() { return state.studioTree; },
    searchStudio(query: string) {
      const results: typeof state.studioTree = [];
      const walk = (nodes: typeof state.studioTree) => {
        for (const n of nodes) {
          if (n.name.toLowerCase().includes(query.toLowerCase())) results.push(n);
          if (n.children) walk(n.children);
        }
      };
      walk(state.studioTree);
      return results;
    },
    refreshStudio() { return { ok: true }; },
    inspectStudio(id: string) {
      const find = (nodes: typeof state.studioTree): typeof state.studioTree[0] | undefined => {
        for (const n of nodes) {
          if (n.id === id) return n;
          if (n.children) { const f = find(n.children); if (f) return f; }
        }
      };
      return find(state.studioTree);
    },

    // Test
    startTest() {
      state.testState.status = 'RUNNING';
      emit('TEST_STARTED', {});
      return { ok: true };
    },
    stopTest() {
      state.testState.status = 'STOPPED';
      return { ok: true };
    },
    getTestState() { return state.testState; },

    // Settings
    getSettings() { return state.settings; },
    updateSettings(partial: Record<string, unknown>) {
      state.settings = { ...state.settings, ...partial };
      return state.settings;
    },
    getModels() { return state.settings.models; },
    setModel(agent: string, model: string) {
      if (agent === 'chatgpt') state.settings.models.chatgpt.model = model;
      if (agent === 'deepseek') state.settings.models.deepseek.model = model;
      return { ok: true };
    },
    setSmartRouting(enabled: boolean) {
      state.settings.models.smartRouting = enabled;
      return { ok: true };
    },

    // Diagnostics
    getDiagnostics() { return state.diagnostics; },
  };

  return adapter;
}

export type MockAdapter = ReturnType<typeof createMockAdapter>;
