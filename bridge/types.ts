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
  ModelInfo,
  ModelSettings,
  Settings,
  StudioNode,
  StudioState,
  TaskOptions,
  TestLog,
  TestState,
  ViewTile,
} from './types';

export interface MockState {
  bootSteps: BootStep[];
  connections: ConnectionInfo;
  agents: AgentInfo[];
  jobs: Job[];
  messages: ChatMessage[];
  context: ContextItem[];
  changes: ChangedFile[];
  views: ViewTile[];
  model: ModelInfo;
  assets: Asset[];
  studioTree: StudioNode[];
  studioState: StudioState;
  testState: TestState;
  testLogs: TestLog[];
  settings: Settings;
  diagnostics: Diagnostic[];
  modelSettings: ModelSettings;
}

export function createMockState(): MockState {
  const now = Date.now();

  return {
    bootSteps: [
      { stage: 'CORE', state: 'READY' },
      { stage: 'BROWSER', state: 'READY' },
      { stage: 'AI', state: 'CONNECTING' },
      { stage: 'STUDIO', state: 'OFF' },
    ],
    connections: {
      bridge: 'READY',
      browser: 'READY',
      chatgpt: 'READY',
      deepseek: 'READY',
      hunyuan: 'LOGIN',
      studio: 'OFF',
    },
    agents: [
      { id: 'chatgpt', name: 'ChatGPT', status: 'READY', model: 'gpt-4o', reasoning: true },
      { id: 'deepseek', name: 'DeepSeek', status: 'READY', model: 'deepseek-v3', reasoning: true },
      { id: 'hunyuan', name: 'Hunyuan', status: 'LOGIN', version: 'hunyuan-3d-1.0', quality: 'standard' },
      { id: 'studio', name: 'Studio', status: 'OFF' },
    ],
    jobs: [
      { id: 'job_001', title: 'Fix ragdoll', status: 'COMPLETE', stage: 'COMPLETE', createdAt: now - 720000, updatedAt: now - 600000 },
      { id: 'job_002', title: 'Bomb VFX', status: 'COMPLETE', stage: 'COMPLETE', createdAt: now - 1860000, updatedAt: now - 1680000 },
      { id: 'job_003', title: 'Dash mechanic', status: 'FAILED', stage: 'FAILED', createdAt: now - 3900000, updatedAt: now - 3600000 },
      { id: 'job_004', title: 'Impact system', status: 'RUNNING', stage: 'BUILDING', createdAt: now - 120000, updatedAt: now - 30000 },
    ],
    messages: [
      { id: 'msg_001', role: 'user', content: 'Fix the ragdoll attachment issue', timestamp: now - 600000 },
      { id: 'msg_002', role: 'zenless', content: 'Investigating RagdollService:184. Found invalid attachment reference.', timestamp: now - 550000 },
    ],
    context: [
      { id: 'ctx_1', name: 'BombService', type: 'Script', path: 'ServerScriptService/BombService', relevance: 0.92, state: 'included' },
      { id: 'ctx_2', name: 'RagdollService', type: 'Script', path: 'ServerScriptService/RagdollService', relevance: 0.88, state: 'included' },
      { id: 'ctx_3', name: 'CombatClient', type: 'Local', path: 'StarterPlayerScripts/CombatClient', relevance: 0.71, state: 'included' },
      { id: 'ctx_4', name: 'ImpactRemote', type: 'Remote', path: 'ReplicatedStorage/Remotes/ImpactRemote', relevance: 0.65, state: 'included' },
      { id: 'ctx_5', name: 'VFXHelper', type: 'Module', path: 'ReplicatedStorage/Modules/VFXHelper', relevance: 0.42, state: 'excluded' },
    ],
    changes: [
      {
        id: 'file_1', name: 'RagdollService', status: 'M', additions: 8, deletions: 3,
        diff: [
          { type: 'unchanged', content: 'local RagdollService = {}', oldLine: 1, newLine: 1 },
          { type: 'removed', content: '  local attachment = character:FindFirstChild("RagdollAttachment")', oldLine: 4 },
          { type: 'added', content: '  local attachment = Instance.new("Attachment")', newLine: 4 },
          { type: 'added', content: '  attachment.Parent = character.PrimaryPart', newLine: 5 },
          { type: 'unchanged', content: 'end', oldLine: 6, newLine: 8 },
        ],
      },
    ],
    views: [
      { name: 'FRONT', state: 'READY', version: 3 },
      { name: 'BACK', state: 'READY', version: 3 },
      { name: 'LEFT', state: 'READY', version: 2 },
      { name: 'RIGHT', state: 'GENERATING', version: 4 },
      { name: 'TOP', state: 'EMPTY' },
      { name: 'BOTTOM', state: 'EMPTY' },
    ],
    model: { state: 'READY', geometryStatus: 'READY', textureStatus: 'READY', modelUrl: '/mock/model.glb' },
    assets: [
      { id: 'a1', name: 'concept_v3', type: 'IMG', url: '/mock/img/concept_v3.png', size: 240000, createdAt: now - 300000 },
      { id: 'a2', name: 'bomb_model', type: 'GLB', url: '/mock/model.glb', size: 1200000, createdAt: now - 480000 },
    ],
    studioTree: [
      { id: 'sn_1', name: 'Workspace', className: 'Workspace', path: 'Workspace', children: [
        { id: 'sn_1_1', name: 'Arena', className: 'Model', path: 'Workspace/Arena' },
      ]},
      { id: 'sn_2', name: 'ReplicatedStorage', className: 'ReplicatedStorage', path: 'ReplicatedStorage', children: [
        { id: 'sn_2_1', name: 'Remotes', className: 'Folder', path: 'ReplicatedStorage/Remotes' },
      ]},
      { id: 'sn_3', name: 'ServerScriptService', className: 'ServerScriptService', path: 'ServerScriptService', children: [
        { id: 'sn_3_1', name: 'BombService', className: 'Script', path: 'ServerScriptService/BombService' },
        { id: 'sn_3_2', name: 'RagdollService', className: 'Script', path: 'ServerScriptService/RagdollService' },
      ]},
    ],
    studioState: 'ONLINE',
    testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 },
    testLogs: [],
    settings: {
      models: {
        chatgpt: { model: 'gpt-4o', reasoning: true },
        deepseek: { model: 'deepseek-v3', reasoning: true },
        hunyuan: { version: 'hunyuan-3d-1.0', quality: 'standard' },
        smartRouting: true,
      },
      autoApprove: false,
      maxRevisions: 3,
      bridgePort: 8787,
    },
    diagnostics: [
      { id: 'd1', severity: 'error', source: 'Studio', message: 'Invalid attachment', file: 'RagdollService', line: 184, timestamp: now - 18000 },
    ],
    modelSettings: {
      chatgpt: { model: 'gpt-4o', reasoning: true },
      deepseek: { model: 'deepseek-v3', reasoning: true },
      hunyuan: { version: 'hunyuan-3d-1.0', quality: 'standard' },
      smartRouting: true,
    },
  };
}
