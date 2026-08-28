import type { ZenlessEvent } from '@/types';
import { useStore } from '@/store';

export function handleEvent(event: ZenlessEvent) {
  const store = useStore.getState();

  switch (event.type) {
    case 'BOOT_STAGE_CHANGED':
      store.setBootSteps(
        useStore.getState().bootSteps.map((s) =>
          s.stage === event.data.stage ? { ...s, state: event.data.state } : s,
        ),
      );
      break;
    case 'BOOT_COMPLETE':
      store.setBooted(true);
      break;
    case 'CONNECTION_CHANGED':
      store.setConnections(event.data);
      break;
    case 'AGENT_STATUS_CHANGED':
      store.setAgents(
        useStore.getState().agents.map((a) =>
          a.id === event.data.agent ? { ...a, status: event.data.status } : a,
        ),
      );
      break;
    case 'PIPELINE_STATE_CHANGED':
      store.updateJob(event.data.jobId, { stage: event.data.stage });
      break;
    case 'JOB_CREATED':
      store.addJob(event.data.job);
      break;
    case 'JOB_UPDATED':
      store.updateJob(event.data.job.id, event.data.job);
      break;
    case 'JOB_COMPLETE':
      store.updateJob(event.data.jobId, { status: 'COMPLETE', stage: 'COMPLETE' });
      break;
    case 'JOB_FAILED':
      store.updateJob(event.data.jobId, { status: 'FAILED', stage: 'FAILED' });
      break;
    case 'CHAT_STREAM_STARTED':
      store.setStreaming(event.data.messageId);
      break;
    case 'CHAT_STREAM_DELTA':
      store.appendStreamDelta(event.data.delta);
      break;
    case 'CHAT_STREAM_FINISHED':
      store.finishStream();
      break;
    case 'CHAT_MESSAGE':
      store.addMessage(event.data.message);
      break;
    case 'CONTEXT_UPDATED':
      store.setContextItems(event.data.items);
      break;
    case 'CHANGES_UPDATED':
      store.setChangedFiles(event.data.files);
      break;
    case 'REVIEW_READY':
      store.setChangedFiles(event.data.review.files);
      break;
    case 'VISUAL_GENERATION_CHANGED':
      if (event.data.view) {
        store.setViews(
          useStore.getState().views.map((v) =>
            v.name === event.data.view ? { ...v, state: event.data.state } : v,
          ),
        );
      }
      break;
    case 'VISUAL_READY':
      store.setViews(
        useStore.getState().views.map((v) =>
          v.name === event.data.view ? { ...v, state: 'READY', imageUrl: event.data.imageUrl } : v,
        ),
      );
      break;
    case 'VISUAL_APPROVED':
      store.setViews(
        useStore.getState().views.map((v) =>
          v.name === event.data.view ? { ...v, state: 'APPROVED' } : v,
        ),
      );
      break;
    case 'MODEL_GENERATION_CHANGED':
      {
        const mi = useStore.getState().modelInfo;
        if (event.data.target === 'geometry') {
          store.setModelInfo({ ...mi, geometryStatus: event.data.state as 'IDLE' | 'GENERATING' | 'READY' | 'FAILED', state: event.data.state as 'EMPTY' | 'GENERATING' | 'READY' | 'APPROVED' | 'FAILED' });
        } else {
          store.setModelInfo({ ...mi, textureStatus: event.data.state as 'IDLE' | 'GENERATING' | 'READY' | 'FAILED', state: event.data.state as 'EMPTY' | 'GENERATING' | 'READY' | 'APPROVED' | 'FAILED' });
        }
      }
      break;
    case 'MODEL_READY':
      store.setModelInfo({ ...useStore.getState().modelInfo, state: 'READY', modelUrl: event.data.modelUrl, filename: event.data.filename });
      break;
    case 'MODEL_APPROVED':
      store.setModelInfo({ ...useStore.getState().modelInfo, state: 'APPROVED' });
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
      store.setTestState({ ...useStore.getState().testState, status: 'RUNNING' });
      break;
    case 'TEST_CASE_STARTED':
      store.upsertTestCase(event.data.testCase);
      break;
    case 'TEST_CASE_FINISHED':
      store.upsertTestCase(event.data.testCase);
      break;
    case 'TEST_FAILURE':
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
      break;
    case 'TEST_LOG':
      store.addTestLog(event.data.log);
      break;
    case 'TEST_FINISHED':
      store.setTestState({ ...useStore.getState().testState, status: event.data.passed ? 'IDLE' : 'FAILED' });
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
