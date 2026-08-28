import type {
  AgentInfo,
  Asset,
  BootStep,
  ChangedFile,
  ChatMessage,
  ConnectionInfo,
  ContextItem,
  Diagnostic,
  Job,
  ModelCatalog,
  ModelInfo,
  Review,
  Settings,
  StudioNode,
  StudioState,
  TestLog,
  TestState,
  ViewTile,
} from '../src/types/index.ts';

export interface MockState {
  bootSteps: BootStep[];
  connections: ConnectionInfo;
  agents: AgentInfo[];
  jobs: Job[];
  messages: ChatMessage[];
  context: ContextItem[];
  changes: ChangedFile[];
  review: Review;
  views: ViewTile[];
  conceptPrompt: string;
  model: ModelInfo;
  assets: Asset[];
  studioTree: StudioNode[];
  studioState: StudioState;
  testState: TestState;
  testLogs: TestLog[];
  settings: Settings;
  diagnostics: Diagnostic[];
  modelCatalog: ModelCatalog;
}

const svg = (label: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="100%" height="100%" fill="#090909"/><circle cx="400" cy="280" r="120" fill="#181818" stroke="#aaa"/><text x="400" y="535" text-anchor="middle" fill="#eee" font-family="monospace" font-size="30">${label}</text></svg>`)}`;

export function createMockState(): MockState {
  const now = Date.now();
  const changes: ChangedFile[] = [{
    id: 'file_1', name: 'RagdollService', status: 'M', additions: 8, deletions: 3,
    diff: [
      { type: 'unchanged', content: 'local RagdollService = {}', oldLine: 1, newLine: 1 },
      { type: 'removed', content: 'local attachment = character:FindFirstChild("RagdollAttachment")', oldLine: 4 },
      { type: 'added', content: 'local attachment = Instance.new("Attachment")', newLine: 4 },
    ],
  }];

  return {
    bootSteps: [
      { stage: 'CORE', state: 'READY' },
      { stage: 'BROWSER', state: 'READY' },
      { stage: 'AI', state: 'CONNECTING' },
      { stage: 'STUDIO', state: 'OFF' },
    ],
    connections: { bridge: 'READY', browser: 'READY', chatgpt: 'READY', deepseek: 'READY', hunyuan: 'LOGIN', studio: 'OFF' },
    agents: [
      { id: 'chatgpt', name: 'ChatGPT', status: 'READY', model: 'chatgpt-default', reasoning: true },
      { id: 'deepseek', name: 'DeepSeek', status: 'READY', model: 'deepseek-default', reasoning: true },
      { id: 'hunyuan', name: 'Hunyuan', status: 'LOGIN', version: 'hunyuan-current', quality: 'standard' },
      { id: 'studio', name: 'Studio', status: 'OFF' },
    ],
    jobs: [
      { id: 'mock_job_active', title: 'Impact system', status: 'RUNNING', stage: 'BUILDING', createdAt: now - 120000, updatedAt: now - 30000 },
    ],
    messages: [],
    context: [
      { id: 'ctx_1', name: 'BombService', type: 'Script', path: 'ServerScriptService/BombService', relevance: 0.92, state: 'included' },
      { id: 'ctx_2', name: 'RagdollService', type: 'Script', path: 'ServerScriptService/RagdollService', relevance: 0.88, state: 'included' },
    ],
    changes,
    review: {
      decision: 'APPROVE', risk: 'LOW', criticalIssues: [], warnings: [], suggestions: [], reviewer: 'DeepSeek', timestamp: now, files: changes, ready: true,
    },
    views: [
      { name: 'FRONT', state: 'READY', imageUrl: svg('FRONT'), version: 1 },
      { name: 'BACK', state: 'READY', imageUrl: svg('BACK'), version: 1 },
      { name: 'LEFT', state: 'READY', imageUrl: svg('LEFT'), version: 1 },
      { name: 'RIGHT', state: 'READY', imageUrl: svg('RIGHT'), version: 1 },
      { name: 'TOP', state: 'READY', imageUrl: svg('TOP'), version: 1 },
      { name: 'BOTTOM', state: 'READY', imageUrl: svg('BOTTOM'), version: 1 },
    ],
    conceptPrompt: 'Industrial bomb device',
    model: { state: 'EMPTY', geometryStatus: 'IDLE', textureStatus: 'IDLE' },
    assets: [],
    studioTree: [
      { id: 'studio_1', name: 'Workspace', className: 'Workspace', path: 'Workspace', children: [{ id: 'studio_1_1', name: 'Arena', className: 'Model', path: 'Workspace/Arena' }] },
      { id: 'studio_2', name: 'ServerScriptService', className: 'ServerScriptService', path: 'ServerScriptService', children: [{ id: 'studio_2_1', name: 'RagdollService', className: 'Script', path: 'ServerScriptService/RagdollService' }] },
    ],
    studioState: 'ONLINE',
    testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 },
    testLogs: [],
    settings: {
      models: {
        chatgpt: { model: 'chatgpt-default', reasoning: true },
        deepseek: { model: 'deepseek-default', reasoning: true },
        hunyuan: { version: 'hunyuan-current', quality: 'standard' },
        smartRouting: true,
      },
      autoApprove: false,
      maxRevisions: 3,
      bridgePort: 8787,
    },
    diagnostics: [],
    modelCatalog: {
      chatgpt: { models: [{ id: 'chatgpt-default', label: 'Default', available: true }] },
      deepseek: { models: [{ id: 'deepseek-default', label: 'Default', available: true }] },
      hunyuan: { versions: [{ id: 'hunyuan-current', label: 'Current', available: true }], qualities: [{ id: 'standard', label: 'STANDARD', available: true }] },
    },
  };
}
