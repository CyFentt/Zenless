// ── Enumerations ──────────────────────────────────────────────
export type ConnectionStatus = 'READY' | 'CONNECTING' | 'LOGIN' | 'OFF' | 'ERR';
export type SocketStatus = 'CONNECTING' | 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED';

export type AgentId = 'chatgpt' | 'deepseek' | 'hunyuan' | 'studio';

export interface AgentInfo {
  id: AgentId;
  name: string;
  status: ConnectionStatus;
  model?: string;
  reasoning?: boolean;
  version?: string;
  quality?: string;
}

export type PipelineStage =
  | 'NEW'
  | 'COLLECTING_CONTEXT'
  | 'PLANNING'
  | 'GENERATING_CONCEPT'
  | 'WAITING_IMAGE_APPROVAL'
  | 'GENERATING_3D'
  | 'WAITING_3D_APPROVAL'
  | 'BUILDING'
  | 'REVIEWING'
  | 'REVISING'
  | 'WAITING_CHANGE_APPROVAL'
  | 'APPLYING'
  | 'TESTING'
  | 'FIXING'
  | 'FINAL_REVIEW'
  | 'COMPLETE'
  | 'PAUSED'
  | 'BLOCKED'
  | 'FAILED';

// Compact stage labels for display
export const STAGE_LABELS: Record<PipelineStage, string> = {
  NEW: 'NEW',
  COLLECTING_CONTEXT: 'CONTEXT',
  PLANNING: 'PLAN',
  GENERATING_CONCEPT: 'CONCEPT',
  WAITING_IMAGE_APPROVAL: 'IMG OK',
  GENERATING_3D: '3D',
  WAITING_3D_APPROVAL: '3D OK',
  BUILDING: 'BUILD',
  REVIEWING: 'REVIEW',
  REVISING: 'REVISE',
  WAITING_CHANGE_APPROVAL: 'CHG OK',
  APPLYING: 'APPLY',
  TESTING: 'TEST',
  FIXING: 'FIX',
  FINAL_REVIEW: 'FINAL',
  COMPLETE: 'DONE',
  PAUSED: 'PAUSE',
  BLOCKED: 'BLOCK',
  FAILED: 'FAIL',
};

// Compact pipeline steps for the visual stepper
export const PIPELINE_STEPS = [
  'CONTEXT',
  'PLAN',
  'BUILD',
  'REVIEW',
  'APPLY',
  'TEST',
  'DONE',
] as const;
export type PipelineStep = (typeof PIPELINE_STEPS)[number];

export type JobStatus = 'NEW' | 'RUNNING' | 'PAUSED' | 'BLOCKED' | 'FAILED' | 'COMPLETE';

export interface Job {
  id: string;
  title: string;
  status: JobStatus;
  stage: PipelineStage;
  createdAt: number;
  updatedAt: number;
  options?: TaskOptions;
  fixAttempts?: number;
  maxFixAttempts?: number;
}

export interface TaskOptions {
  visualFirst: boolean;
  create3D: boolean;
  review: boolean;
  autoTest: boolean;
  autoFix: boolean;
  approval: boolean;
  risk: 'low' | 'medium' | 'high';
  revisions: number;
  fixAttempts: number;
}

export const DEFAULT_TASK_OPTIONS: TaskOptions = {
  visualFirst: false,
  create3D: true,
  review: true,
  autoTest: true,
  autoFix: true,
  approval: true,
  risk: 'medium',
  revisions: 3,
  fixAttempts: 3,
};

// ── Chat ──────────────────────────────────────────────────────
export type ChatRole = 'user' | 'zenless' | 'system';

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  timestamp: number;
  streaming?: boolean;
  jobId?: string;
  attachments?: ChatAttachment[];
}

export interface ChatAttachment {
  id: string;
  name: string;
  type: 'image' | 'file' | 'context';
  size?: number;
}

// ── Context ───────────────────────────────────────────────────
export type ContextItemType = 'Script' | 'Module' | 'Remote' | 'Local' | 'Service';
export type ContextState = 'included' | 'excluded' | 'locked';

export interface ContextItem {
  id: string;
  name: string;
  type: ContextItemType;
  path: string;
  relevance: number;
  state: ContextState;
}

// ── Changes / Diff ────────────────────────────────────────────
export type FileStatus = 'M' | 'A' | 'D';

export interface ChangedFile {
  id: string;
  name: string;
  status: FileStatus;
  additions: number;
  deletions: number;
  diff: DiffLine[];
}

export type DiffLineType = 'added' | 'removed' | 'unchanged' | 'hunk';

export interface DiffLine {
  type: DiffLineType;
  content: string;
  oldLine?: number;
  newLine?: number;
}

// ── Visual ────────────────────────────────────────────────────
export type ViewName = 'FRONT' | 'BACK' | 'LEFT' | 'RIGHT' | 'TOP' | 'BOTTOM';
export type ViewState = 'EMPTY' | 'GENERATING' | 'READY' | 'FAILED' | 'APPROVED';

export interface ViewTile {
  name: ViewName;
  state: ViewState;
  imageUrl?: string;
  version?: number;
}

export interface ConceptInfo {
  version: number;
  status: 'GENERATING' | 'READY' | 'APPROVED' | 'FAILED';
  prompt?: string;
}

// ── 3D Model ──────────────────────────────────────────────────
export type ModelGenState = 'EMPTY' | 'GENERATING' | 'READY' | 'APPROVED' | 'FAILED';

export interface ModelInfo {
  state: ModelGenState;
  geometryStatus: 'IDLE' | 'GENERATING' | 'READY' | 'FAILED';
  textureStatus: 'IDLE' | 'GENERATING' | 'READY' | 'FAILED';
  modelUrl?: string;
}

// ── Assets ────────────────────────────────────────────────────
export type AssetType = 'IMG' | 'VIEW' | 'GLB' | 'TEX' | 'RBX';

export interface Asset {
  id: string;
  name: string;
  type: AssetType;
  url: string;
  thumbnailUrl?: string;
  size: number;
  createdAt: number;
}

// ── Studio ────────────────────────────────────────────────────
export type StudioState = 'ONLINE' | 'OFFLINE' | 'CONNECTING';

export interface StudioNode {
  id: string;
  name: string;
  className: string;
  path: string;
  children?: StudioNode[];
}

// ── Test ──────────────────────────────────────────────────────
export type TestStatus = 'IDLE' | 'RUNNING' | 'STOPPED' | 'FAILED';
export type LogLevel = 'ERR' | 'WARN' | 'ZEN' | 'SRV' | 'CLI';

export interface TestLog {
  id: string;
  timestamp: number;
  level: LogLevel;
  message: string;
  file?: string;
  line?: number;
  stack?: string;
  cause?: string;
  recovery?: string;
}

export interface TestState {
  status: TestStatus;
  elapsedMs: number;
  fixAttempt: number;
  maxFixAttempts: number;
}

// ── Settings ──────────────────────────────────────────────────
export interface ModelOption {
  id: string;
  label: string;
}

export interface ModelSettings {
  chatgpt: { model: string; reasoning: boolean };
  deepseek: { model: string; reasoning: boolean };
  hunyuan: { version: string; quality: string };
  smartRouting: boolean;
}

export interface Settings {
  models: ModelSettings;
  autoApprove: boolean;
  maxRevisions: number;
  bridgePort: number;
}

// ── Diagnostics ───────────────────────────────────────────────
export interface Diagnostic {
  id: string;
  severity: 'error' | 'warning' | 'info';
  source: string;
  message: string;
  file?: string;
  line?: number;
  timestamp: number;
}

// ── Connections ───────────────────────────────────────────────
export interface ConnectionInfo {
  bridge: ConnectionStatus;
  browser: ConnectionStatus;
  chatgpt: ConnectionStatus;
  deepseek: ConnectionStatus;
  hunyuan: ConnectionStatus;
  studio: ConnectionStatus;
}

// ── Boot ──────────────────────────────────────────────────────
export type BootStage = 'CORE' | 'BROWSER' | 'AI' | 'STUDIO';
export type BootState = 'READY' | 'CONNECTING' | 'OFF';

export interface BootStep {
  stage: BootStage;
  state: BootState;
}

// ── WebSocket Events (discriminated union) ────────────────────
export interface ZenlessEventMap {
  BOOT_STAGE_CHANGED: { stage: BootStage; state: BootState };
  BOOT_COMPLETE: Record<string, never>;
  CONNECTION_CHANGED: Partial<ConnectionInfo>;
  AGENT_STATUS_CHANGED: { agent: AgentId; status: ConnectionStatus };
  PIPELINE_STATE_CHANGED: { jobId: string; stage: PipelineStage };
  JOB_CREATED: { job: Job };
  JOB_UPDATED: { job: Partial<Job> & { id: string } };
  JOB_COMPLETE: { jobId: string };
  JOB_FAILED: { jobId: string; reason: string };
  CHAT_STREAM_STARTED: { messageId: string; jobId?: string };
  CHAT_STREAM_DELTA: { messageId: string; delta: string };
  CHAT_STREAM_FINISHED: { messageId: string };
  CHAT_MESSAGE: { message: ChatMessage };
  CONTEXT_UPDATED: { items: ContextItem[] };
  CHANGES_UPDATED: { files: ChangedFile[] };
  REVIEW_READY: { files: ChangedFile[] };
  VISUAL_GENERATION_CHANGED: { view?: ViewName; state: ViewState };
  VISUAL_READY: { view: ViewName; imageUrl: string };
  VISUAL_APPROVED: { view: ViewName };
  MODEL_GENERATION_CHANGED: { target: 'geometry' | 'texture'; state: ModelGenState };
  MODEL_READY: { modelUrl: string };
  MODEL_APPROVED: Record<string, never>;
  ASSETS_UPDATED: { assets: Asset[] };
  STUDIO_STATE_CHANGED: { state: StudioState };
  STUDIO_TREE_UPDATED: { tree: StudioNode[] };
  TEST_STARTED: Record<string, never>;
  TEST_LOG: { log: TestLog };
  TEST_FINISHED: { passed: boolean };
  SETTINGS_CHANGED: { settings: Partial<Settings> };
  DIAGNOSTIC_EVENT: { diagnostic: Diagnostic };
}

export type ZenlessEvent = {
  [K in keyof ZenlessEventMap]: { type: K; data: ZenlessEventMap[K] };
}[keyof ZenlessEventMap];

export type ZenlessEventHandler = (event: ZenlessEvent) => void;
