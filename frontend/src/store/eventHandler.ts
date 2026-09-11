import type {
  ConnectionInfo,
  ConnectionStatus,
  ProviderAuthState,
  ProviderId,
  ProviderLoginState,
  StudioDiscoverySnapshot,
  StudioState,
  ZenlessEvent,
} from '@/types';
import { useStore } from '@/store';

type StoreState = ReturnType<typeof useStore.getState>;
const VIEW_NAMES = ['FRONT', 'BACK', 'LEFT', 'RIGHT', 'TOP', 'BOTTOM'] as const;

function upsertView(
  views: StoreState['views'],
  name: StoreState['views'][number]['name'],
  patch: Partial<StoreState['views'][number]>,
): StoreState['views'] {
  return views.some((view) => view.name === name)
    ? views.map((view) => (view.name === name ? { ...view, ...patch, name } : view))
    : [...views, { name, state: 'EMPTY', ...patch }];
}

function visualReady(views: StoreState['views']) {
  return VIEW_NAMES.every((name) => {
    const view = views.find((item) => item.name === name);
    return view?.state === 'READY' || view?.state === 'APPROVED';
  });
}

function setProviderLogin(
  store: StoreState,
  providerId: ProviderId,
  loginState: ProviderLoginState,
  authState: ProviderAuthState,
  status: ConnectionStatus,
  patch: Record<string, unknown> = {},
) {
  store.setLoginState(providerId, loginState);
  store.upsertProvider(providerId, { loginState, authState, status, ...patch });
  store.setConnections({ [providerId]: status } as Partial<ConnectionInfo>);
}

function discoveryState(snapshot: StudioDiscoverySnapshot): StudioState {
  switch (snapshot.state) {
    case 'PROJECT_READY': return 'ONLINE';
    case 'MULTIPLE_STUDIOS': return 'SELECT_REQUIRED';
    case 'MCP_SETUP_REQUIRED': return 'SETUP_REQUIRED';
    case 'MCP_RUNTIME_ERROR': return 'ERROR';
    case 'STUDIO_NOT_RUNNING':
    case 'NO_PROJECT': return 'OFFLINE';
    default: return 'SEARCHING';
  }
}

function applyStudioDiscovery(store: StoreState, snapshot: StudioDiscoverySnapshot) {
  store.setStudioDiscovery(snapshot);
  const state = discoveryState(snapshot);
  store.setStudioState(state);
  const selected = snapshot.studios.find((studio) => studio.id === snapshot.selectedStudioId);
  const projectName = selected?.project?.trim();
  if (selected && projectName) {
    store.setProjectIdentity({
      name: projectName,
      studioId: selected.id,
      placeId: selected.placeId ?? null,
      universeId: selected.universeId ?? null,
    });
  } else if (state === 'OFFLINE' || state === 'SELECT_REQUIRED' || state === 'ERROR') {
    store.setProjectIdentity(null);
  }
}

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
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setStreaming(event.data.messageId, event.data.jobId);
      }
      break;
    case 'CHAT_STREAM_DELTA':
      if (
        isStrictlyCurrentJob(event.data.jobId)
        && useStore.getState().streamingMessageId === event.data.messageId
      ) {
        store.appendStreamDelta(event.data.delta);
      }
      break;
    case 'CHAT_STREAM_FINISHED':
      if (
        isStrictlyCurrentJob(event.data.jobId)
        && useStore.getState().streamingMessageId === event.data.messageId
      ) {
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
    case 'LOGIN_REQUIRED':
      setProviderLogin(store, event.data.providerId, 'WAITING', 'LOGIN_REQUIRED', 'LOGIN');
      break;
    case 'LOGIN_WINDOW_WILL_OPEN':
      setProviderLogin(store, event.data.providerId, 'OPENING', 'LOGIN_REQUIRED', 'LOGIN');
      break;
    case 'LOGIN_WINDOW_OPENED':
      setProviderLogin(store, event.data.providerId, 'WAITING', 'LOGIN_WINDOW_OPEN', 'LOGIN', { route: event.data.route });
      break;
    case 'LOGIN_DETECTED':
      setProviderLogin(store, event.data.providerId, 'VERIFYING', 'AUTHENTICATING', 'CONNECTING');
      break;
    case 'LOGIN_PERSISTENCE_VERIFYING':
      setProviderLogin(store, event.data.providerId, 'VERIFYING', 'VERIFYING_PERSISTENCE', 'CONNECTING');
      break;
    case 'LOGIN_READY':
      setProviderLogin(store, event.data.providerId, 'READY', 'READY', 'READY', {
        route: event.data.route,
        session: { persistent: event.data.persistent },
      });
      break;
    case 'LOGIN_FAILED':
      setProviderLogin(store, event.data.providerId, 'FAILED', 'ERROR', 'ERR', { detail: event.data.message });
      break;
    case 'PROVIDER_CAPABILITIES_CHANGED':
      store.setProviders(
        useStore.getState().providers.some((provider) => provider.providerId === event.data.provider.providerId)
          ? useStore.getState().providers.map((provider) => (
              provider.providerId === event.data.provider.providerId ? event.data.provider : provider
            ))
          : [...useStore.getState().providers, event.data.provider],
      );
      break;
    case 'PROVIDER_MODEL_CHANGED':
      store.setProviders(
        useStore.getState().providers.map((provider) => (
          provider.providerId === event.data.providerId
            ? { ...provider, selection: event.data.selection }
            : provider
        )),
      );
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
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setReview(event.data.review);
        store.setChangedFiles(event.data.review.files);
      }
      break;
    case 'VISUAL_GENERATION_CHANGED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        const nextViews = upsertView(useStore.getState().views, event.data.view, {
          state: event.data.state,
          assetId: event.data.assetId ?? undefined,
          version: event.data.conceptVersion,
        });
        store.setViews(nextViews);
        const current = useStore.getState();
        const status = event.data.state === 'FAILED'
          ? 'FAILED'
          : event.data.state === 'GENERATING'
            ? 'GENERATING'
            : visualReady(nextViews)
              ? 'READY'
              : current.conceptStatus;
        store.setConcept(event.data.conceptVersion, status, current.conceptPrompt);
      }
      break;
    case 'VISUAL_READY':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        const nextViews = upsertView(useStore.getState().views, event.data.view, {
          state: 'READY',
          imageUrl: event.data.imageUrl,
          assetId: event.data.assetId,
          version: event.data.conceptVersion,
        });
        store.setViews(nextViews);
        const current = useStore.getState();
        store.setConcept(
          event.data.conceptVersion,
          visualReady(nextViews) ? 'READY' : current.conceptStatus,
          current.conceptPrompt,
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
        const current = useStore.getState();
        store.setConcept(event.data.conceptVersion ?? current.conceptVersion, 'APPROVED', current.conceptPrompt);
      }
      break;
    case 'MODEL_GENERATION_CHANGED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        const mi = useStore.getState().modelInfo;
        const approvalState = event.data.state === 'GENERATING' ? 'PENDING_APPROVAL' : mi.approvalState;
        if (event.data.target === 'geometry') {
          store.setModelInfo({ ...mi, approvalState, geometryStatus: event.data.state, state: event.data.state });
        } else {
          store.setModelInfo({ ...mi, approvalState, textureStatus: event.data.state, state: event.data.state });
        }
      }
      break;
    case 'MODEL_READY':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setModelInfo({
          ...useStore.getState().modelInfo,
          state: 'READY',
          approvalState: 'PENDING_APPROVAL',
          geometryStatus: event.data.geometryStatus,
          textureStatus: event.data.textureStatus,
          modelUrl: event.data.modelUrl,
          filename: event.data.filename,
        });
      }
      break;
    case 'MODEL_APPROVED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setModelInfo({ ...useStore.getState().modelInfo, approvalState: 'APPROVED' });
      }
      break;
    case 'ASSETS_UPDATED':
      store.setAssets(event.data.assets);
      break;
    case 'STUDIO_STATE_CHANGED':
      store.setStudioState(event.data.state);
      if (
        event.data.projectName
        || event.data.studioId
        || event.data.selectedStudioId
        || event.data.placeId !== undefined
        || event.data.universeId !== undefined
      ) {
        store.setProjectIdentity({
          name: event.data.projectName?.trim() ?? '',
          studioId: event.data.studioId ?? event.data.selectedStudioId ?? null,
          placeId: event.data.placeId ?? null,
          universeId: event.data.universeId ?? null,
        });
      } else if (event.data.state === 'OFFLINE') {
        store.setProjectIdentity(null);
      }
      break;
    case 'STUDIO_DISCOVERY_CHANGED':
    case 'STUDIO_SELECTION_REQUIRED':
      applyStudioDiscovery(store, event.data);
      break;
    case 'STUDIO_TREE_UPDATED':
      store.setStudioTree(event.data.tree);
      break;
    case 'TEST_STARTED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.resetTestDetails();
        store.setTestLogs([]);
        store.setTestState({
          ...useStore.getState().testState,
          status: 'RUNNING',
          resultStatus: undefined,
          counts: undefined,
        });
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
          runId: event.data.failure.runId,
          jobId: event.data.failure.jobId,
          suite: event.data.failure.suite,
          expected: event.data.failure.expected,
          actual: event.data.failure.actual,
        });
      }
      break;
    case 'TEST_LOG':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.addTestLog(event.data.log);
      }
      break;
    case 'TEST_FINISHED':
      if (isStrictlyCurrentJob(event.data.jobId)) {
        store.setTestState({
          ...useStore.getState().testState,
          status: event.data.status === 'FAILED' ? 'FAILED' : 'STOPPED',
          resultStatus: event.data.status,
          counts: event.data.counts,
        });
      }
      break;
    case 'TOOL_STATUS_CHANGED':
      store.setTools(
        useStore.getState().tools.some((tool) => tool.id === event.data.tool.id)
          ? useStore.getState().tools.map((tool) => (tool.id === event.data.tool.id ? event.data.tool : tool))
          : [...useStore.getState().tools, event.data.tool],
      );
      break;
    case 'STORAGE_CLEANUP_COMPLETED':
      store.setStorage(event.data.storage);
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
