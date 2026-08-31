import { useEffect } from 'react';
import { getApi, getSocket } from '@/services';
import type { ZenlessAPI } from '@/services/api/types';
import { frontendDiagnostics } from '@/services/diagnostics';
import type { ZenlessSocket } from '@/services/websocket/socket';
import { useStore } from '@/store';
import { handleEvent } from '@/store/eventHandler';
import type { Job, SocketStatus } from '@/types';

export class ApplicationRuntime {
  private active = false;
  private started = false;
  private connected = false;
  private hydration: Promise<void> | null = null;
  private hydrationQueued = false;
  private unsubscribeEvent = () => {};
  private unsubscribeStatus = () => {};
  private unsubscribeDiagnostics = () => {};

  constructor(private api: ZenlessAPI, private socket: ZenlessSocket) {}

  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    this.active = true;
    frontendDiagnostics.init();
    this.unsubscribeDiagnostics = frontendDiagnostics.on((diagnostic) => useStore.getState().addDiagnostic(diagnostic));
    try {
      const result = await this.api.bootstrap();
      if (!this.active) return;
      const store = useStore.getState();
      store.setBootSteps(result.steps);
      store.setBackendReady(result.steps.some((step) => step.stage === 'UI' && step.state === 'READY'));
      this.unsubscribeEvent = this.socket.on('event', handleEvent);
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
    this.unsubscribeEvent();
    this.unsubscribeStatus();
    this.unsubscribeDiagnostics();
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
    const [bootstrap, connections, agents, jobs, settings, diagnostics, assets, studioState, studioTree] = await Promise.all([
      this.api.bootstrap(),
      this.api.getConnections(),
      this.api.getAgents(),
      this.api.getJobs(),
      this.api.getSettings(),
      this.api.getDiagnostics(),
      this.api.getAssets(),
      this.api.getStudioState(),
      this.api.getStudioTree(),
    ]);
    if (!this.active) return;
    const store = useStore.getState();
    store.setBootSteps(bootstrap.steps);
    store.setBackendReady(bootstrap.steps.some((step) => step.stage === 'UI' && step.state === 'READY'));
    store.setConnections(connections);
    store.setAgents(agents);
    store.setJobs(jobs);
    store.setSettings(settings);
    const frontend = frontendDiagnostics.getAll();
    const backendIds = new Set(diagnostics.map((diagnostic) => diagnostic.id));
    store.setDiagnostics([...diagnostics, ...frontend.filter((diagnostic) => !backendIds.has(diagnostic.id))]);
    store.setAssets(assets);
    store.setStudioState(studioState.state);
    store.setStudioTree(studioTree);
    const current = this.selectCurrentJob(jobs, store.currentJobId);
    store.setCurrentJobId(current?.id ?? null);
    if (current) await this.loadJobSnapshot(current);
    if (!this.active) return;
    useStore.getState().setRuntimeHydrated(true);
    useStore.getState().setBootError('');
  }

  private async loadJobSnapshot(job: Job): Promise<void> {
    const [timeline, context, changes, visual, model] = await Promise.all([
      this.api.getTimeline(job.id),
      this.api.getContext(job.id),
      this.api.getChanges(job.id),
      this.api.getVisual(job.id),
      this.api.getModel(job.id),
    ]);
    if (!this.active || useStore.getState().currentJobId !== job.id) return;
    const store = useStore.getState();
    store.setMessages(timeline.messages);
    store.setActivities(timeline.activities);
    store.setArtifacts(timeline.artifacts);
    if (timeline.test) {
      store.setTestState(timeline.test.testState);
      store.setTestCases(timeline.test.cases);
      store.setTestFailures(timeline.test.failures);
      if (timeline.test.logs) store.setTestLogs(timeline.test.logs);
    }
    store.setContextItems(context);
    store.setChangedFiles(changes);
    store.setViews(visual.views);
    store.setConcept(visual.concept.version, visual.concept.status, visual.concept.prompt);
    store.setModelInfo(model);
  }

  private selectCurrentJob(jobs: Job[], currentJobId: string | null): Job | null {
    return jobs.find((job) => job.id === currentJobId)
      ?? jobs.find((job) => job.status === 'NEW' || job.status === 'RUNNING' || job.status === 'PAUSED')
      ?? jobs[0]
      ?? null;
  }
}

export function AppRuntime() {
  useEffect(() => {
    const runtime = new ApplicationRuntime(getApi(), getSocket());
    void runtime.start();
    return () => runtime.stop();
  }, []);
  return null;
}
