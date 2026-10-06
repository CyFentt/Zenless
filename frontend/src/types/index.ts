export type ConnectionStatus = "READY" | "CONNECTING" | "LOGIN" | "OFF" | "ERR";
export type SocketStatus = "CONNECTING" | "CONNECTED" | "RECONNECTING" | "DISCONNECTED";

export type AgentId = "chatgpt" | "deepseek" | "gemini" | "hunyuan" | "studio";
export type ProviderId = Extract<AgentId, "chatgpt" | "deepseek" | "gemini" | "hunyuan">;

export type ProviderRole = "BUILDER" | "REVIEWER" | "RESEARCH" | "VISUAL" | "THREED";

export interface AgentInfo {
  id: AgentId;
  name: string;
  status: ConnectionStatus;
  model?: string;
  version?: string;
}

export const PROVIDER_NAMES: Record<ProviderId, string> = {
  chatgpt: "ChatGPT",
  deepseek: "DeepSeek",
  gemini: "Gemini",
  hunyuan: "Hunyuan",
};

export const AGENT_NAMES: Record<AgentId, string> = {
  chatgpt: "ChatGPT",
  deepseek: "DeepSeek",
  gemini: "Gemini",
  hunyuan: "Hunyuan",
  studio: "Roblox Studio",
};

export const AGENT_ROLES: Record<AgentId, string> = {
  chatgpt: "BUILDER",
  deepseek: "REVIEWER",
  gemini: "RESEARCH",
  hunyuan: "3D GENERATOR",
  studio: "EDITOR",
};

export type PipelineStage =
  | "NEW"
  | "COLLECTING_CONTEXT"
  | "PLANNING"
  | "GENERATING_CONCEPT"
  | "WAITING_IMAGE_APPROVAL"
  | "GENERATING_3D"
  | "WAITING_3D_APPROVAL"
  | "BUILDING"
  | "REVIEWING"
  | "REVISING"
  | "WAITING_CHANGE_APPROVAL"
  | "APPLYING"
  | "TESTING"
  | "FIXING"
  | "FINAL_REVIEW"
  | "COMPLETE"
  | "PAUSED"
  | "BLOCKED"
  | "FAILED";

export const STAGE_LABELS: Record<PipelineStage, string> = {
  NEW: "NEW",
  COLLECTING_CONTEXT: "CONTEXT",
  PLANNING: "PLAN",
  GENERATING_CONCEPT: "CONCEPT",
  WAITING_IMAGE_APPROVAL: "IMG OK",
  GENERATING_3D: "3D",
  WAITING_3D_APPROVAL: "3D OK",
  BUILDING: "BUILD",
  REVIEWING: "REVIEW",
  REVISING: "REVISE",
  WAITING_CHANGE_APPROVAL: "CHG OK",
  APPLYING: "APPLY",
  TESTING: "TEST",
  FIXING: "FIX",
  FINAL_REVIEW: "FINAL",
  COMPLETE: "DONE",
  PAUSED: "PAUSE",
  BLOCKED: "BLOCK",
  FAILED: "FAIL",
};

export const PIPELINE_STEPS = [
  "CONTEXT",
  "PLAN",
  "BUILD",
  "REVIEW",
  "APPLY",
  "TEST",
  "DONE",
] as const;
export type PipelineStep = (typeof PIPELINE_STEPS)[number];

export type JobStatus = "NEW" | "RUNNING" | "PAUSED" | "BLOCKED" | "FAILED" | "COMPLETE";

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

export type EffortLevel = "AUTO" | "MIN" | "MED" | "MAX";
export type ApprovalMode = "ASK" | "SAFE_AUTO" | "FULL_AUTO";

export interface TaskOptions {
  visualFirst: boolean;
  create3D: boolean;
  review: boolean;
  autoTest: boolean;
  autoFix: boolean;
  approval: boolean;
  approvalMode: ApprovalMode;
  risk: "low" | "medium" | "high";
  revisions: number;
  fixAttempts: number;
  smartRouting?: boolean;
  continuousVerification?: boolean;
  effort?: EffortLevel;
  research?: "AUTO" | "ON" | "OFF";
}

export const DEFAULT_TASK_OPTIONS: TaskOptions = {
  visualFirst: false,
  create3D: false,
  review: true,
  autoTest: true,
  autoFix: true,
  approval: true,
  approvalMode: "ASK",
  risk: "medium",
  revisions: 3,
  fixAttempts: 3,
  smartRouting: true,
  continuousVerification: true,
  effort: "AUTO",
  research: "AUTO",
};

export type PromptQueueState = "QUEUED" | "PREPARING" | "INFLIGHT" | "BLOCKED" | "FAILED" | "COMPLETED" | "CANCELLED";

export interface PromptQueueItem {
  id: string;
  position: number;
  state: PromptQueueState;
  content: string;
  parentJobId?: string | null;
  jobId?: string | null;
  attempts: number;
  maxAttempts: number;
  lastError: string;
  nextAttemptAt: string;
  createdAt: number;
  updatedAt: number;
  options: Partial<TaskOptions>;
}

export interface PromptQueueConfig {
  paused: boolean;
  continueOnFailure: boolean;
  chainConversation: boolean;
  delaySeconds: number;
  maxAttempts: number;
}

export interface PromptQueueSnapshot {
  items: PromptQueueItem[];
  config: PromptQueueConfig;
}

export type ChatRole = "user" | "zenless" | "system";

export interface ChatAction {
  type: "LOGIN";
  provider: ProviderId;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  timestamp: number;
  streaming?: boolean;
  jobId?: string;
  attachments?: ChatAttachment[];
  action?: ChatAction;
  activity?: ChatActivity;
  error?: ChatError;
}

export interface ChatAttachment {
  id: string;
  name: string;
  type: "image" | "file" | "context";
  size?: number;
  mime?: string;
  previewUrl?: string;
  state?: "READY" | "EXTRACTING" | "ROUTING" | "UNSUPPORTED" | "FAILED" | "PREPARING";
}

export interface TestCapture {
  id: string;
  imageUrl: string;
  width: number;
  height: number;
  timestamp: number;
}

export type ChatActivityStatus = "QUEUED" | "RUNNING" | "DONE" | "WARNING" | "FAILED";
export type ChatActivityPhase = "CONTEXT" | "PLAN" | "BUILD" | "REVIEW" | "APPLY" | "TEST" | "FINAL" | "RESEARCH" | "CONCEPT" | "THREED";

export interface ChatActivity {
  id: string;
  jobId?: string;
  providerId?: AgentId;
  role?: string;
  phase: ChatActivityPhase;
  status: ChatActivityStatus;
  title: string;
  target?: string;
  step?: number;
  totalSteps?: number;
  detail?: string;
  timestamp: number;
}

export interface ChatError {
  source: string;
  message: string;
  detail?: string;
  retryable?: boolean;
}

export type ContextItemType = "Script" | "Module" | "Remote" | "Local" | "Service";
export type ContextState = "included" | "excluded" | "locked";

export interface ContextItem {
  id: string;
  name: string;
  type: ContextItemType;
  path: string;
  relevance: number;
  state: ContextState;
}

export type FileStatus = "M" | "A" | "D";

export interface ChangedFile {
  id: string;
  name: string;
  status: FileStatus;
  additions: number;
  deletions: number;
  diff: DiffLine[];
}

export type DiffLineType = "added" | "removed" | "unchanged" | "hunk";

export interface DiffLine {
  type: DiffLineType;
  content: string;
  oldLine?: number;
  newLine?: number;
}

export type ReviewDecision = "APPROVE" | "REVISE" | "BLOCK";
export type ReviewRisk = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Review {
  decision: ReviewDecision;
  risk: ReviewRisk;
  criticalIssues: string[];
  warnings: string[];
  suggestions: string[];
  summary?: string;
  reviewer: string;
  timestamp: number;
  files: ChangedFile[];
  ready: boolean;
}

export type ViewName = "FRONT" | "BACK" | "LEFT" | "RIGHT" | "TOP" | "BOTTOM";
export type ViewState = "EMPTY" | "GENERATING" | "READY" | "FAILED" | "APPROVED";

export interface ViewTile {
  name: ViewName;
  state: ViewState;
  imageUrl?: string;
  version?: number;
  error?: string;
}

export interface ConceptInfo {
  version: number;
  status: "GENERATING" | "READY" | "APPROVED" | "FAILED";
  prompt?: string;
}

export type ModelGenState = "EMPTY" | "GENERATING" | "READY" | "APPROVED" | "FAILED";

export interface ModelInfo {
  state: ModelGenState;
  geometryStatus: "IDLE" | "GENERATING" | "READY" | "FAILED";
  textureStatus: "IDLE" | "GENERATING" | "READY" | "FAILED";
  modelUrl?: string;
  filename?: string;
  error?: string;
}

export type AssetType = "IMG" | "VIEW" | "GLB" | "GLTF" | "TEX" | "RBX";

export interface Asset {
  id: string;
  name: string;
  type: AssetType;
  url: string;
  thumbnailUrl?: string;
  size: number;
  createdAt: number;
  jobId?: string;
  conceptVersion?: number;
}

export type StudioState = "ONLINE" | "OFFLINE" | "CONNECTING" | "SEARCHING" | "SETUP_REQUIRED" | "SELECT_REQUIRED" | "ERROR";

export interface StudioNode {
  details?: unknown;
  detailsError?: string;
  id: string;
  name: string;
  className: string;
  path: string;
  children?: StudioNode[];
  locked?: boolean;
  usedAsContext?: boolean;
  source?: string;
}

export type TestStatus = "IDLE" | "STARTING" | "RUNNING" | "STOPPING" | "STOPPED" | "FAILED";
export type LogLevel = "ERR" | "WARN" | "RUBRA" | "SRV" | "CLI";

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
  testCaseId?: string;
  suite?: string;
  expected?: unknown;
  actual?: unknown;
}

export type TestCaseStatus = "RUNNING" | "PASSED" | "FAILED" | "SKIPPED";

export interface TestCaseResult {
  id: string;
  name: string;
  suite?: string;
  status: TestCaseStatus;
  startedAt?: number;
  finishedAt?: number;
  durationMs?: number;
  file?: string;
  line?: number;
}

export interface TestFailure {
  id: string;
  testCaseId?: string;
  name?: string;
  suite?: string;
  message: string;
  timestamp: number;
  file?: string;
  line?: number;
  stack?: string;
  expected?: unknown;
  actual?: unknown;
  cause?: string;
  recovery?: string;
}

export interface TestState {
  status: TestStatus;
  elapsedMs: number;
  fixAttempt: number;
  maxFixAttempts: number;
}

export interface ModelOption {
  id: string;
  label: string;
  available?: boolean;
}

export interface ModelSettings {
  chatgpt: { model: string };
  deepseek: { model: string };
  gemini: { model: string };
  hunyuan: { version: string };
  smartRouting: boolean;
}

export interface ModelCatalog {
  chatgpt: { models: ModelOption[] };
  deepseek: { models: ModelOption[] };
  gemini: { models: ModelOption[] };
  hunyuan: { versions: ModelOption[] };
}

export interface Settings {
  models: ModelSettings;
  autoApprove: boolean;
  approvalMode: ApprovalMode;
  maxRevisions: number;
  projectRoot: string;
  semanticIndex: boolean;
  localAI: boolean;
  bridgePort: number;
}

export interface ProjectIndexStatus {
  indexed?: boolean;
  configured: boolean;
  projectRoot: string;
  running: boolean;
  result: string;
  error?: string;
}

export interface ProjectSearchResult {
  projectRoot: string;
  query: string;
  result: string;
  available: boolean;
}

export type DiagnosticSeverity = "critical" | "error" | "warning" | "info";

export interface Diagnostic {
  id: string;
  severity: DiagnosticSeverity;
  source: string;
  component?: string;
  message: string;
  file?: string;
  line?: number;
  function?: string;
  probableCause?: string;
  impact?: string;
  recovery?: string;
  stack?: string;
  occurrenceCount?: number;
  jobId?: string;
  requestId?: string;
  operationId?: string;
  timestamp: number;
}

export interface ConnectionInfo {
  bridge: ConnectionStatus;
  browser: ConnectionStatus;
  chatgpt: ConnectionStatus;
  deepseek: ConnectionStatus;
  gemini: ConnectionStatus;
  hunyuan: ConnectionStatus;
  studio: ConnectionStatus;
}

export type BootStage = "CORE" | "STATE" | "BRIDGE" | "UI" | "BROWSER" | "AI" | "STUDIO";
export type BootState = "READY" | "CONNECTING" | "OFF";

export interface BootStep {
  stage: BootStage;
  state: BootState;
}

export interface ProviderCapabilities {
  reasoning?: { supported: boolean; levels?: string[] };
  search?: { supported: boolean };
  files?: { supported: boolean; accepted?: string[]; maxCount?: number };
}

export interface ProviderMode {
  id: string;
  label: string;
  capabilities: ProviderCapabilities;
}

export interface ProviderModel {
  id: string;
  label: string;
  available?: boolean;
}

export interface ProviderDescriptor {
  id: ProviderId;
  name: string;
  role: ProviderRole;
  status: ConnectionStatus;
  model?: string;
  mode?: string;
  modes?: ProviderMode[];
  models?: ProviderModel[];
  capabilities?: ProviderCapabilities;
  verified?: "VERIFIED" | "BETA" | "EXPERIMENTAL" | "UNVERIFIED";
}

export interface ToolDescriptor {
  id: string;
  name: string;
  description?: string;
  status: "INSTALLED" | "NOT_INSTALLED" | "OPTIONAL" | "FAILED";
  category: "BUILT_IN" | "MCP" | "EXTERNAL";
  downloadSize?: string;
  installedSize?: string;
  reason?: string;
}

export interface StorageInfo {
  used: number;
  budget: number;
  categories: { name: string; size: number }[];
}

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
  CHAT_STREAM_DELTA: { messageId: string; jobId?: string; delta: string };
  CHAT_STREAM_FINISHED: { messageId: string; jobId?: string };
  CHAT_MESSAGE: { message: ChatMessage };
  CHAT_ACTIVITY: { activity: ChatActivity };
  CONTEXT_UPDATED: { jobId: string; items: ContextItem[] };
  CHANGES_UPDATED: { jobId: string; files: ChangedFile[] };
  REVIEW_READY: { jobId: string; review: Review };
  VISUAL_GENERATION_CHANGED: { jobId: string; view?: ViewName; state: ViewState; version?: number; prompt?: string };
  VISUAL_READY: { jobId: string; view: ViewName; imageUrl: string };
  VISUAL_APPROVED: { jobId: string; view?: ViewName };
  MODEL_GENERATION_CHANGED: { jobId: string; target: "geometry" | "texture"; state: ModelGenState };
  MODEL_READY: { jobId: string; modelUrl: string; filename?: string };
  MODEL_APPROVED: { jobId: string };
  ASSETS_UPDATED: { assets: Asset[] };
  STUDIO_STATE_CHANGED: { state: StudioState; projectName?: string; treeError?: string };
  STUDIO_TREE_UPDATED: { tree: StudioNode[] };
  TEST_STARTED: { jobId?: string };
  TEST_CASE_STARTED: { jobId?: string; testCase: TestCaseResult };
  TEST_CASE_FINISHED: { jobId?: string; testCase: TestCaseResult };
  TEST_FAILURE: { jobId?: string; failure: TestFailure };
  TEST_LOG: { jobId?: string; log: TestLog };
  TEST_CAPTURE: { jobId: string; capture: TestCapture };
  TEST_FINISHED: { passed: boolean; cancelled?: boolean; jobId?: string };
  SETTINGS_CHANGED: { settings: Partial<Settings> };
  DIAGNOSTIC_EVENT: { diagnostic: Diagnostic };
  PROMPT_QUEUE_CHANGED: PromptQueueSnapshot;
}

export type ZenlessEvent = {
  [K in keyof ZenlessEventMap]: { type: K; data: ZenlessEventMap[K] };
}[keyof ZenlessEventMap];

export type ZenlessEventHandler = (event: ZenlessEvent) => void;

export interface LocalAIState {
  enabled: boolean;
  available: boolean;
  running: boolean;
  model: string;
  models?: { id?: string; name: string; installed: boolean; state?: string; detail?: string }[];
  setup: { state: string; detail: string };
}
