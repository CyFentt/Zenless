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
  ModelCatalog,
  ModelSettings,
  Settings,
  StudioNode,
  TestLog,
  ViewTile,
} from '@/types';

const now = Date.now();

export const mockBootSteps: BootStep[] = [
  { stage: 'CORE', state: 'READY' },
  { stage: 'BROWSER', state: 'READY' },
  { stage: 'AI', state: 'CONNECTING' },
  { stage: 'STUDIO', state: 'OFF' },
];

export const mockConnections: ConnectionInfo = {
  bridge: 'READY',
  browser: 'READY',
  chatgpt: 'READY',
  deepseek: 'READY',
  hunyuan: 'LOGIN',
  studio: 'OFF',
};

export const mockAgents: AgentInfo[] = [
  { id: 'chatgpt', name: 'ChatGPT', status: 'READY', model: 'chatgpt-default', reasoning: true },
  { id: 'deepseek', name: 'DeepSeek', status: 'READY', model: 'deepseek-default', reasoning: true },
  { id: 'hunyuan', name: 'Hunyuan', status: 'LOGIN', version: 'hunyuan-current', quality: 'standard' },
  { id: 'studio', name: 'Studio', status: 'OFF' },
];

export const mockJobs: Job[] = [
  {
    id: 'job_001',
    title: 'Fix ragdoll',
    status: 'COMPLETE',
    stage: 'COMPLETE',
    createdAt: now - 1000 * 60 * 12,
    updatedAt: now - 1000 * 60 * 10,
    fixAttempts: 1,
    maxFixAttempts: 3,
  },
  {
    id: 'job_002',
    title: 'Bomb VFX',
    status: 'COMPLETE',
    stage: 'COMPLETE',
    createdAt: now - 1000 * 60 * 31,
    updatedAt: now - 1000 * 60 * 28,
  },
  {
    id: 'job_003',
    title: 'Dash mechanic',
    status: 'FAILED',
    stage: 'FAILED',
    createdAt: now - 1000 * 60 * 65,
    updatedAt: now - 1000 * 60 * 60,
  },
  {
    id: 'job_004',
    title: 'Impact system',
    status: 'RUNNING',
    stage: 'BUILDING',
    createdAt: now - 1000 * 60 * 2,
    updatedAt: now - 1000 * 30,
  },
];

export const mockChatMessages: ChatMessage[] = [
  {
    id: 'msg_001',
    role: 'user',
    content: 'Fix the ragdoll attachment issue in RagdollService',
    timestamp: now - 1000 * 60 * 12,
  },
  {
    id: 'msg_002',
    role: 'zenless',
    content: 'Investigating RagdollService:184. Found invalid attachment reference. Proposing fix:\n\n```lua\n-- RagdollService:184\nlocal attachment = Instance.new("Attachment")\nattachment.Parent = humanoidRootPart\n```\n\nAwaiting approval to apply.',
    timestamp: now - 1000 * 60 * 11,
  },
  {
    id: 'msg_003',
    role: 'user',
    content: 'Apply it',
    timestamp: now - 1000 * 60 * 10,
  },
  {
    id: 'msg_004',
    role: 'zenless',
    content: 'Applied. Running Play Test...',
    timestamp: now - 1000 * 60 * 10 + 5000,
  },
];

export const mockContext: ContextItem[] = [
  { id: 'ctx_1', name: 'BombService', type: 'Script', path: 'ServerScriptService/BombService', relevance: 0.92, state: 'included' },
  { id: 'ctx_2', name: 'RagdollService', type: 'Script', path: 'ServerScriptService/RagdollService', relevance: 0.88, state: 'included' },
  { id: 'ctx_3', name: 'CombatClient', type: 'Local', path: 'StarterPlayerScripts/CombatClient', relevance: 0.71, state: 'included' },
  { id: 'ctx_4', name: 'ImpactRemote', type: 'Remote', path: 'ReplicatedStorage/Remotes/ImpactRemote', relevance: 0.65, state: 'included' },
  { id: 'ctx_5', name: 'VFXHelper', type: 'Module', path: 'ReplicatedStorage/Modules/VFXHelper', relevance: 0.42, state: 'excluded' },
  { id: 'ctx_6', name: 'SoundManager', type: 'Module', path: 'ReplicatedStorage/Modules/SoundManager', relevance: 0.28, state: 'excluded' },
  { id: 'ctx_7', name: 'PlayerData', type: 'Module', path: 'ServerScriptService/PlayerData', relevance: 0.15, state: 'locked' },
];

export const mockChanges: ChangedFile[] = [
  {
    id: 'file_1',
    name: 'RagdollService',
    status: 'M',
    additions: 8,
    deletions: 3,
    diff: [
      { type: 'unchanged', content: 'local RagdollService = {}', oldLine: 1, newLine: 1 },
      { type: 'unchanged', content: '', oldLine: 2, newLine: 2 },
      { type: 'unchanged', content: 'function RagdollService:apply(character)', oldLine: 3, newLine: 3 },
      { type: 'removed', content: '  local attachment = character:FindFirstChild("RagdollAttachment")', oldLine: 4 },
      { type: 'removed', content: '  if not attachment then return end', oldLine: 5 },
      { type: 'added', content: '  local attachment = Instance.new("Attachment")', newLine: 4 },
      { type: 'added', content: '  attachment.Name = "RagdollAttachment"', newLine: 5 },
      { type: 'added', content: '  attachment.Parent = character.PrimaryPart', newLine: 6 },
      { type: 'added', content: '  if not attachment then return end', newLine: 7 },
      { type: 'added', content: '  self:_configureConstraints(character, attachment)', newLine: 8 },
      { type: 'unchanged', content: 'end', oldLine: 6, newLine: 9 },
      { type: 'unchanged', content: '', oldLine: 7, newLine: 10 },
      { type: 'unchanged', content: 'return RagdollService', oldLine: 8, newLine: 11 },
    ],
  },
  {
    id: 'file_2',
    name: 'BombService',
    status: 'M',
    additions: 4,
    deletions: 1,
    diff: [
      { type: 'unchanged', content: 'function BombService:detonate(pos)', oldLine: 42, newLine: 42 },
      { type: 'removed', content: '  self:createExplosion(pos, 50)', oldLine: 43 },
      { type: 'added', content: '  local radius = self:getConfig("blastRadius", 50)', newLine: 43 },
      { type: 'added', content: '  self:createExplosion(pos, radius)', newLine: 44 },
      { type: 'added', content: '  self:spawnDebris(pos, radius * 0.5)', newLine: 45 },
      { type: 'added', content: '  SoundManager:play("explosion", pos)', newLine: 46 },
      { type: 'unchanged', content: 'end', oldLine: 44, newLine: 47 },
    ],
  },
  {
    id: 'file_3',
    name: 'ImpactHelper',
    status: 'A',
    additions: 22,
    deletions: 0,
    diff: [
      { type: 'added', content: 'local ImpactHelper = {}', newLine: 1 },
      { type: 'added', content: '', newLine: 2 },
      { type: 'added', content: 'function ImpactHelper:create(point, normal, intensity)', newLine: 3 },
      { type: 'added', content: '  local effect = Instance.new("ParticleEmitter")', newLine: 4 },
      { type: 'added', content: '  effect.Parent = workspace.Terrain', newLine: 5 },
      { type: 'added', content: '  effect.Position = point', newLine: 6 },
      { type: 'added', content: '  effect.Rate = 0', newLine: 7 },
      { type: 'added', content: '  effect.Lifetime = NumberRange.new(0.3, 0.6)', newLine: 8 },
      { type: 'added', content: '  task.delay(1, function() effect:Destroy() end)', newLine: 9 },
      { type: 'added', content: 'end', newLine: 10 },
      { type: 'added', content: '', newLine: 11 },
      { type: 'added', content: 'return ImpactHelper', newLine: 12 },
    ],
  },
];

const viewSvg = (label: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600"><rect width="800" height="600" fill="#090909"/><rect x="170" y="110" width="460" height="380" rx="8" fill="#121212" stroke="#444"/><circle cx="400" cy="300" r="110" fill="#1b1b1b" stroke="#aaa" stroke-width="2"/><path d="M330 300h140M400 230v140" stroke="#777"/><text x="400" y="545" fill="#f2f2f2" font-family="monospace" font-size="28" text-anchor="middle">${label}</text></svg>`)}`;

export const mockViews: ViewTile[] = [
  { name: 'FRONT', state: 'READY', version: 3, imageUrl: viewSvg('FRONT') },
  { name: 'BACK', state: 'READY', version: 3, imageUrl: viewSvg('BACK') },
  { name: 'LEFT', state: 'APPROVED', version: 3, imageUrl: viewSvg('LEFT') },
  { name: 'RIGHT', state: 'GENERATING', version: 4 },
  { name: 'TOP', state: 'READY', version: 3, imageUrl: viewSvg('TOP') },
  { name: 'BOTTOM', state: 'EMPTY' },
];

export const mockModelInfo: ModelInfo = {
  state: 'READY',
  geometryStatus: 'READY',
  textureStatus: 'READY',
  modelUrl: '/mock/model.glb',
  filename: 'demo_model.glb',
};

export const mockAssets: Asset[] = [
  { id: 'a1', name: 'concept_v3', type: 'IMG', url: '/mock/img/concept_v3.png', size: 240000, createdAt: now - 1000 * 60 * 5 },
  { id: 'a2', name: 'front_view', type: 'VIEW', url: '/mock/img/front_view.png', size: 180000, createdAt: now - 1000 * 60 * 5 },
  { id: 'a3', name: 'bomb_model', type: 'GLB', url: '/mock/model.glb', size: 1200000, createdAt: now - 1000 * 60 * 8 },
  { id: 'a4', name: 'metal_tex', type: 'TEX', url: '/mock/tex/metal.png', size: 512000, createdAt: now - 1000 * 60 * 8 },
  { id: 'a5', name: 'impact_remote', type: 'RBX', url: '/mock/rbx/impact.rbxl', size: 8900000, createdAt: now - 1000 * 60 * 20 },
  { id: 'a6', name: 'back_view', type: 'VIEW', url: '/mock/img/back_view.png', size: 175000, createdAt: now - 1000 * 60 * 5 },
  { id: 'a7', name: 'left_view', type: 'VIEW', url: '/mock/img/left_view.png', size: 170000, createdAt: now - 1000 * 60 * 4 },
  { id: 'a8', name: 'concept_v2', type: 'IMG', url: '/mock/img/concept_v2.png', size: 230000, createdAt: now - 1000 * 60 * 15 },
];

export const mockStudioTree: StudioNode[] = [
  {
    id: 'sn_1',
    name: 'Workspace',
    className: 'Workspace',
    path: 'Workspace',
    children: [
      { id: 'sn_1_1', name: 'Arena', className: 'Model', path: 'Workspace/Arena' },
      { id: 'sn_1_2', name: 'Map', className: 'Folder', path: 'Workspace/Map' },
      { id: 'sn_1_3', name: 'SpawnPoints', className: 'Folder', path: 'Workspace/SpawnPoints' },
    ],
  },
  {
    id: 'sn_2',
    name: 'ReplicatedStorage',
    className: 'ReplicatedStorage',
    path: 'ReplicatedStorage',
    children: [
      { id: 'sn_2_1', name: 'Remotes', className: 'Folder', path: 'ReplicatedStorage/Remotes' },
      { id: 'sn_2_2', name: 'Modules', className: 'Folder', path: 'ReplicatedStorage/Modules' },
      { id: 'sn_2_3', name: 'Assets', className: 'Folder', path: 'ReplicatedStorage/Assets' },
    ],
  },
  {
    id: 'sn_3',
    name: 'ServerScriptService',
    className: 'ServerScriptService',
    path: 'ServerScriptService',
    children: [
      { id: 'sn_3_1', name: 'BombService', className: 'Script', path: 'ServerScriptService/BombService' },
      { id: 'sn_3_2', name: 'RagdollService', className: 'Script', path: 'ServerScriptService/RagdollService' },
      { id: 'sn_3_3', name: 'PlayerData', className: 'ModuleScript', path: 'ServerScriptService/PlayerData' },
    ],
  },
  {
    id: 'sn_4',
    name: 'StarterPlayer',
    className: 'StarterPlayer',
    path: 'StarterPlayer',
    children: [
      { id: 'sn_4_1', name: 'StarterPlayerScripts', className: 'Folder', path: 'StarterPlayer/StarterPlayerScripts' },
      { id: 'sn_4_2', name: 'StarterCharacterScripts', className: 'Folder', path: 'StarterPlayer/StarterCharacterScripts' },
    ],
  },
];

export const mockTestLogs: TestLog[] = [
  { id: 'log_1', timestamp: now - 30000, level: 'ZEN', message: 'Play Test started' },
  { id: 'log_2', timestamp: now - 28000, level: 'SRV', message: 'BombService initialized' },
  { id: 'log_3', timestamp: now - 25000, level: 'CLI', message: 'CombatClient loaded' },
  { id: 'log_4', timestamp: now - 20000, level: 'WARN', message: 'RagdollService:180 Attachment not found, creating fallback' },
  { id: 'log_5', timestamp: now - 18000, level: 'ERR', message: 'RagdollService:184 Invalid attachment', file: 'RagdollService', line: 184, stack: 'RagdollService:apply:184\nRagdollService:init:12\nServerScriptService:main:5', cause: 'Attachment parent is nil', recovery: 'Creating new Attachment instance' },
  { id: 'log_6', timestamp: now - 15000, level: 'ZEN', message: 'Auto-fix attempt 1/3: inject attachment creation' },
  { id: 'log_7', timestamp: now - 10000, level: 'ZEN', message: 'Fix applied, re-running test' },
  { id: 'log_8', timestamp: now - 5000, level: 'SRV', message: 'RagdollService initialized successfully' },
];

export const mockDiagnostics: Diagnostic[] = [
  { id: 'd1', severity: 'error', source: 'Studio', component: 'StudioMCP', message: 'Invalid attachment', file: 'RagdollService', line: 184, function: 'applyRagdoll', probableCause: 'Attachment parent is missing', impact: 'Ragdoll test failed', recovery: 'Recreate and validate attachment before apply', occurrenceCount: 1, timestamp: now - 18000 },
  { id: 'd2', severity: 'warning', source: 'Studio', message: 'WaitForChild timeout', file: 'BombService', line: 42, occurrenceCount: 2, timestamp: now - 25000 },
];

export const mockSettings: Settings = {
  models: {
    chatgpt: { model: 'chatgpt-default', reasoning: true },
    deepseek: { model: 'deepseek-default', reasoning: true },
    hunyuan: { version: 'hunyuan-current', quality: 'standard' },
    smartRouting: true,
  },
  autoApprove: false,
  maxRevisions: 3,
  bridgePort: 8787,
};

export const mockModelSettings: ModelSettings = mockSettings.models;

export const mockModelCatalog: ModelCatalog = {
  chatgpt: { models: [
    { id: 'chatgpt-default', label: 'Default', available: true },
    { id: 'chatgpt-reasoning', label: 'Reasoning', available: true },
  ] },
  deepseek: { models: [
    { id: 'deepseek-default', label: 'Default', available: true },
    { id: 'deepseek-reasoning', label: 'Reasoning', available: true },
  ] },
  hunyuan: {
    versions: [{ id: 'hunyuan-current', label: 'Current', available: true }],
    qualities: [
      { id: 'draft', label: 'DRAFT', available: true },
      { id: 'standard', label: 'STANDARD', available: true },
      { id: 'high', label: 'HIGH', available: true },
    ],
  },
};
