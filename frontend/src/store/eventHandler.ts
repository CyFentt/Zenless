import type { ZenlessEvent } from '@/types';
import { useStore } from '@/store';

export function handleEvent(event: ZenlessEvent) {
  const store = useStore.getState();
  const currentJobId = store.currentJobId;
  const isStrictlyCurrentJob = (jobId: string) => currentJobId !== null && jobId === currentJobId;

  switch (event.type) {
    case 'BOOT_STAGE_CHANGED':
      {
        const steps = useStore.getState().bootSteps;
        const known = steps.some((step) => step.stage === event.data.stage);
        store.setBootSteps(
          known
            ? steps.map((step) => (step.stage === event.data.stage ? { ...step, state: event.data.state } : step))
            : [...steps, { stage: event.data.stage, state: event.data.state }],
        );
        if (event.data.stage === 'UI' && event.data.state === 'READY') store.setBackendReady(true);
      }
      break;
    case 'BOOT_COMPLETE':
      store.setBackendReady(true);
      break;
    case 'CONNECTION_CHANGED':
      store.setConnections(event.data);
      break;
    case 'AGENT_STATUS_CHANGED':
      store.upsertAgent(event.data.agent, { status: event.data.status });
      break;
    case 'PIPELINE_STATE_CHANGED':
      store.updateJob(event.data.jobId, { stage: event.data.stage });
      break;
    case 'JOB_CREATED':
      store.upsertJob(event.data.job);
      if (!store.currentJobId) {
        store.setCurrentJobId(event.data.job.id);
      }
      break;
    case 'JOB_UPDATED':
      store.updateJob(event.data.job.id, event.data.job);
      if (!store.currentJobId) {
        store.setCurrentJobId(event.data.job.id);
      }
      break;
    case 'JOB_COMPLETE':
      store.updateJob(event.data.jobId, { status: 'COMPLETE', stage: 'COMPLETE' });
      break;
    case 'JOB_FAILED':
      store.updateJob(event.data.jobId, { status: 'FAILED', stage: 'FAILED' });
      break;
    case 'CHAT_STREAM_STARTED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setStreaming(event.data.messageId);
      }
      break;
    case 'CHAT_STREAM_DELTA':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.appendStreamDelta(event.data.delta);
      }
      break;
    case 'CHAT_STREAM_FINISHED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.finishStream();
      }
      break;
    case 'CHAT_MESSAGE':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.addMessage(event.data.message);
      }
      break;
    case 'CHAT_ACTIVITY':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.addActivity(event.data.activity);
      }
      break;
    case 'CHAT_ARTIFACT':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.addArtifact(event.data.artifact);
      }
      break;
    case 'PROVIDER_LOGIN_STATE':
      store.setLoginState(event.data.provider, event.data.state);
      if (event.data.state === 'READY') {
        store.upsertProvider(event.data.provider, { status: 'READY', loginState: 'READY' });
        store.setConnections({ [event.data.provider]: 'READY' } as Partial<Record<string, unknown>> as never);
      }
      break;
    case 'READINESS_CHANGED':
      store.setReadiness(event.data.readiness);
      break;
    case 'CONTEXT_UPDATED':
      if (isStrictlyCurrentJob(event.data.jobId)) store.setContextItems(event.data.items);
      break;
    case 'CHANGES_UPDATED':
      if (isStrictlyCurrentJob(event.data.jobId)) store.setChangedFiles(event.data.files);
      break;
    case 'REVIEW_READY':
      if (isStrictlyCurrentJob(event.data.jobId)) store.setChangedFiles(event.data.review.files);
      break;
    case 'VISUAL_GENERATION_CHANGED':
      if (isStrictlyCurrentJob(event.data.jobId) && event.data.view) {
        store.setViews(
          useStore.getState().views.map((v) =>
            v.name === event.data.view ? { ...v, state: event.data.state } : v,
          ),
        );
      }
      break;
    case 'VISUAL_READY':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setViews(
          useStore.getState().views.map((v) =>
            v.name === event.data.view ? { ...v, state: 'READY', imageUrl: event.data.imageUrl } : v,
          ),
        );
      }
      break;
    case 'VISUAL_APPROVED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        const viewsToApprove = new Set(event.data.views || []);
        store.setViews(
          useStore.getState().views.map((v) =>
            viewsToApprove.has(v.name) ? { ...v, state: 'APPROVED' } : v,
          ),
        );
      }
      break;
    case 'MODEL_GENERATION_CHANGED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        const mi = useStore.getState().modelInfo;
        if (event.data.target === 'geometry') {
          store.setModelInfo({ ...mi, geometryStatus: event.data.state as 'IDLE' | 'GENERATING' | 'READY' | 'FAILED', state: event.data.state as 'EMPTY' | 'GENERATING' | 'READY' | 'APPROVED' | 'FAILED' });
        } else {
          store.setModelInfo({ ...mi, textureStatus: event.data.state as 'IDLE' | 'GENERATING' | 'READY' | 'FAILED', state: event.data.state as 'EMPTY' | 'GENERATING' | 'READY' | 'APPROVED' | 'FAILED' });
        }
      }
      break;
    case 'MODEL_READY':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setModelInfo({ ...useStore.getState().modelInfo, state: 'READY', modelUrl: event.data.modelUrl, filename: event.data.filename });
      }
      break;
    case 'MODEL_APPROVED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setModelInfo({ ...useStore.getState().modelInfo, state: 'APPROVED' });
      }
      break;
    case 'ASSETS_UPDATED':
      store.setAssets(event.data.assets);
      break;
    case 'STUDIO_STATE_CHANGED':
      store.setStudioState(event.data.state);
      break;
    case 'STUDIO_TREE_UPDATED':
      store.setStudioTree(event.data.tree);
      break;
    case 'TEST_STARTED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setTestState({ ...useStore.getState().testState, status: 'RUNNING' });
      }
      break;
    case 'TEST_CASE_STARTED':
    case 'TEST_CASE_FINISHED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.upsertTestCase(event.data.testCase);
      }
      break;
    case 'TEST_FAILURE':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.addTestFailure(event.data.failure);
        store.addTestLog({
          id: `failure_${event.data.failure.id}`,
          timestamp: event.data.failure.timestamp,
          level: 'ERR',
          message: event.data.failure.message,
          file: event.data.failure.file,
          line: event.data.failure.line,
          stack: event.data.failure.stack,
          cause: event.data.failure.cause,
          recovery: event.data.failure.recovery,
          testCaseId: event.data.failure.testCaseId,
          suite: event.data.failure.suite,
          expected: event.data.failure.expected,
          actual: event.data.failure.actual,
        });
      }
      break;
    case 'TEST_LOG':
      if (!event.data.jobId || isStrictlyCurrentJob(event.data.jobId)) {
        store.addTestLog(event.data.log);
      }
      break;
    case 'TEST_FINISHED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setTestState({ ...useStore.getState().testState, status: event.data.passed ? 'IDLE' : 'FAILED' });
      }
      break;
    case 'SETTINGS_CHANGED':
      if (useStore.getState().settings) {
        store.setSettings({ ...useStore.getState().settings!, ...event.data.settings });
      }
      break;
    case 'DIAGNOSTIC_EVENT':
      store.addDiagnostic(event.data.diagnostic);
      break;
  }
}
