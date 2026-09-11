import type { ZenlessAPI } from '@/services/api/types';
import { frontendDiagnostics } from '@/services/diagnostics';
import type { ZenlessSocket } from '@/services/websocket/socket';
import { useStore } from '@/store';
import { handleEvent } from '@/store/eventHandler';
import type { Job, ProjectIdentity, SocketStatus, StudioStateSnapshot, ZenlessEvent } from '@/types';

const JOB_PROJECTION_EVENTS = new Set<ZenlessEvent['type']>([
  'CHAT_STREAM_STARTED',
  'CHAT_STREAM_DELTA',
  'CHAT_STREAM_FINISHED',
  'CHAT_MESSAGE',
  'CHAT_ACTIVITY',
  'CHAT_ARTIFACT',
  'CONTEXT_UPDATED',
  'CHANGES_UPDATED',
  'REVIEW_READY',
  'VISUAL_GENERATION_CHANGED',
  'VISUAL_READY',
  'VISUAL_APPROVED',
  'MODEL_GENERATION_CHANGED',
  'MODEL_READY',
  'MODEL_APPROVED',
  'TEST_STARTED',
  'TEST_CASE_STARTED',
  'TEST_CASE_FINISHED',
  'TEST_FAILURE',
  'TEST_LOG',
  'TEST_FINISHED',
]);

export class ApplicationRuntime {
  private active = false;
  private started = false;
  private connected = false;
  private hydration: Promise<void> | null = null;
  private hydrationQueued = false;
  private jobHydrationGeneration = 0;
  private jobHydration: Promise<void> = Promise.resolve();
  private jobHydrationController: AbortController | null = null;
  private jobHydrationBuffer: { jobId: string; generation: number; events: ZenlessEvent[] } | null = null;
  private unsubscribeEvent = () => {};
  private unsubscribeStatus = () => {};
  private unsubscribeDiagnostics = () => {};
  private unsubscribeJob = () => {};

  constructor(private api: ZenlessAPI, private socket: ZenlessSocket) {}

  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    this.active = true;
    frontendDiagnostics.init();
    this.unsubscribeDiagnostics = frontendDiagnostics.on((diagnostic) => useStore.getState().addDiagnostic(diagnostic));
    this.unsubscribeJob = useStore.subscribe((state, previous) => {
      if (state.currentJobId !== previous.currentJobId) this.requestJobHydration(state.currentJobId);
    });
    try {
      const result = await this.api.bootstrap();
      if (!this.active) return;
      const store = useStore.getState();
      store.setBootSteps(result.steps);
      store.setBackendReady(result.steps.some((step) => step.stage === 'UI' && step.state === 'READY'));
      this.unsubscribeEvent = this.socket.on('event', (event) => this.receiveEvent(event));
      this.unsubscribeStatus = this.socket.on('status', (status) => this.handleSocketStatus(status));
      this.socket.connect();
      await this.rehydrate();
    } catch (error) {
      if (!this.active) return;
      frontendDiagnostics.capture(error, 'runtime', 'Application startup failed');
      useStore.getState().setBootError('The local application state could not be loaded. Details are available in Settings > Logs.');
    }
  }

  stop(): void {
    if (!this.started) return;
    this.active = false;
    this.started = false;
    this.jobHydrationGeneration += 1;
    this.jobHydrationController?.abort();
    this.jobHydrationController = null;
    this.jobHydrationBuffer = null;
    this.unsubscribeEvent();
    this.unsubscribeStatus();
    this.unsubscribeDiagnostics();
    this.unsubscribeJob();
    this.socket.disconnect();
  }

  async rehydrate(): Promise<void> {
    if (!this.active) return;
    if (this.hydration) {
      this.hydrationQueued = true;
      return this.hydration;
    }
    this.hydration = this.loadSnapshot();
    try {
      await this.hydration;
    } catch (error) {
      if (this.active) {
        frontendDiagnostics.capture(error, 'runtime', 'State hydration failed');
        useStore.getState().setBootError('The local application state could not be loaded. Details are available in Settings > Logs.');
      }
    } finally {
      this.hydration = null;
      if (this.hydrationQueued && this.active) {
        this.hydrationQueued = false;
        void this.rehydrate();
      }
    }
  }

  async selectAndHydrateJob(jobId: string | null): Promise<void> {
    if (!this.active) return;
    if (useStore.getState().currentJobId === jobId) {
      await this.jobHydration;
      return;
    }
    useStore.getState().setCurrentJobId(jobId);
    await this.jobHydration;
  }

  private handleSocketStatus(status: SocketStatus): void {
    if (!this.active) return;
    useStore.getState().setSocketStatus(status);
    if (status === 'CONNECTED') {
      const reconnect = this.connected;
      this.connected = true;
      if (reconnect) void this.rehydrate();
    }
  }

  private async loadSnapshot(): Promise<void> {
    const previousJobs = new Map(useStore.getState().jobs.map((job) => [job.id, job]));
    const [
      bootstrap,
      connections,
      agents,
      providers,
      readiness,
      jobs,
      settings,
      diagnostics,
      assets,
      studioState,
      studioTree,
      tools,
      storage,
    ] = await Promise.all([
      this.api.bootstrap(),
      this.api.getConnections(),
      this.api.getAgents(),
      this.api.getProviders(),
      this.api.getReadiness(),
      this.api.getJobs(),
      this.api.getSettings(),
      this.api.getDiagnostics(),
      this.api.getAssets(),
      this.api.getStudioState(),
      this.api.getStudioTree(),
      this.api.getTools(),
      this.api.getStorage(),
    ]);
    if (!this.active) return;
    const store = useStore.getState();
    store.setBootSteps(bootstrap.steps);
    store.setBackendReady(bootstrap.steps.some((step) => step.stage === 'UI' && step.state === 'READY'));
    store.setConnections(connections);
    store.setAgents(agents);
    store.setProviders(providers);
    store.setReadiness(readiness);
    const concurrentJobs = store.jobs.filter((job) => previousJobs.get(job.id) !== job);
    const mergedJobs = [...new Map([...jobs, ...concurrentJobs].map((job) => [job.id, job])).values()];
    store.setJobs(mergedJobs);
    store.setSettings(settings);
    const frontend = frontendDiagnostics.getAll();
    const backendIds = new Set(diagnostics.map((diagnostic) => diagnostic.id));
    store.setDiagnostics([...diagnostics, ...frontend.filter((diagnostic) => !backendIds.has(diagnostic.id))]);
    store.setAssets(assets);
    store.setStudioState(studioState.state);
    store.setProjectIdentity(this.projectIdentity(studioState));
    store.setStudioTree(studioTree);
    store.setTools(tools);
    store.setStorage(storage);
    const selectedJob = this.selectCurrentJob(mergedJobs, store.currentJobId);
    let selectedHydration: Promise<void>;
    if (store.currentJobId !== selectedJob?.id) {
      store.setCurrentJobId(selectedJob?.id ?? null);
      selectedHydration = this.jobHydration;
    } else {
      selectedHydration = this.requestJobHydration(selectedJob?.id ?? null);
    }
    await selectedHydration;
    if (!this.active) return;
    useStore.getState().setRuntimeHydrated(true);
    useStore.getState().setBootError('');
  }

  private requestJobHydration(jobId: string | null): Promise<void> {
    this.jobHydrationController?.abort();
    const controller = new AbortController();
    this.jobHydrationController = controller;
    const generation = ++this.jobHydrationGeneration;
    this.jobHydrationBuffer = jobId ? { jobId, generation, events: [] } : null;
    this.jobHydration = jobId
      ? this.loadJobSnapshot(jobId, generation, controller.signal)
      : Promise.resolve();
    return this.jobHydration;
  }

  private async loadJobSnapshot(jobId: string, generation: number, signal: AbortSignal): Promise<void> {
    const previous = useStore.getState();
    const stream = previous.streamingJobId === jobId ? {
      streamingJobId: jobId,
      streamingMessageId: previous.streamingMessageId,
      streamingContent: previous.streamingContent,
    } : null;
    try {
      const [timeline, contextItems, changedFiles, review, visual, modelInfo] = await Promise.all([
        this.api.getTimeline(jobId, signal),
        this.api.getContext(jobId, signal),
        this.api.getChanges(jobId, signal),
        this.api.getReview(jobId, signal),
        this.api.getVisual(jobId, signal),
        this.api.getModel(jobId, signal),
      ]);
      if (timeline.jobId !== jobId) throw new Error('The timeline snapshot does not match the selected job.');
      if (!this.active || signal.aborted || generation !== this.jobHydrationGeneration) return;
      useStore.getState().projectJobSnapshot({
        jobId,
        messages: timeline.messages,
        activities: timeline.activities,
        artifacts: timeline.artifacts,
        contextItems,
        changedFiles,
        review: review.ready ? review : null,
        views: visual.views,
        concept: visual.concept,
        modelInfo,
        testState: timeline.test.testState,
        testCases: timeline.test.cases,
        testFailures: timeline.test.failures,
        testLogs: timeline.test.logs ?? [],
      });
      const messageIds = new Set(timeline.messages.map((message) => message.id));
      if (stream?.streamingMessageId && !messageIds.has(stream.streamingMessageId)) useStore.setState(stream);
      const buffer = this.jobHydrationBuffer;
      if (buffer?.jobId === jobId && buffer.generation === generation) {
        this.jobHydrationBuffer = null;
        buffer.events.forEach((event) => {
          if ('messageId' in event.data && messageIds.has(event.data.messageId as string)) return;
          handleEvent(event);
        });
      }
    } catch (error) {
      if (!this.active || signal.aborted || generation !== this.jobHydrationGeneration) return;
      frontendDiagnostics.capture(error, 'runtime', 'Failed to hydrate active job snapshot', { jobId });
    } finally {
      if (this.jobHydrationBuffer?.generation === generation) this.jobHydrationBuffer = null;
    }
  }

  private receiveEvent(event: ZenlessEvent): void {
    handleEvent(event);
    const buffer = this.jobHydrationBuffer;
    if (!buffer || !JOB_PROJECTION_EVENTS.has(event.type)) return;
    const data = event.data as { jobId?: unknown };
    if (data.jobId === buffer.jobId && useStore.getState().currentJobId === buffer.jobId) {
      buffer.events.push(event);
    }
  }

  private selectCurrentJob(jobs: Job[], currentJobId: string | null): Job | null {
    return jobs.find((job) => job.id === currentJobId)
      ?? jobs.find((job) => job.status === 'NEW' || job.status === 'RUNNING' || job.status === 'PAUSED')
      ?? jobs[0]
      ?? null;
  }

  private projectIdentity(snapshot: StudioStateSnapshot): ProjectIdentity | null {
    const studioId = snapshot.studioId ?? snapshot.selectedStudioId ?? null;
    const name = snapshot.projectName?.trim() ?? '';
    const placeId = snapshot.placeId ?? null;
    const universeId = snapshot.universeId ?? null;
    if (!studioId && !name && placeId === null && universeId === null) return null;
    return { name, studioId, placeId, universeId };
  }
}
