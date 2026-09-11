export type ConnectionStatus = "READY" | "CONNECTING" | "LOGIN" | "OFF" | "ERR";
export type SocketStatus = "CONNECTING" | "CONNECTED" | "RECONNECTING" | "DISCONNECTED";

export type AgentId = "chatgpt" | "deepseek" | "hunyuan" | "studio";
export type ProviderId = Extract<AgentId, "chatgpt" | "deepseek" | "hunyuan">;

export type ProviderRole = "BUILDER" | "REVIEWER" | "VISUAL" | "RESEARCH" | "THREED";

export interface AgentInfo {
  id: AgentId;
  name: string;
  status: ConnectionStatus;
  model?: string;
  reasoning?: boolean;
  version?: string;
  quality?: string;
}

export const PROVIDER_NAMES: Record<ProviderId, string> = {
  chatgpt: "ChatGPT",
  deepseek: "DeepSeek",
  hunyuan: "Hunyuan",
};

export const AGENT_NAMES: Record<AgentId, string> = {
  chatgpt: "ChatGPT",
  deepseek: "DeepSeek",
  hunyuan: "Hunyuan",
  studio: "Roblox Studio",
};

export const AGENT_ROLES: Record<AgentId, string> = {
  chatgpt: "BUILDER",
  deepseek: "REVIEWER",
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
export type ChatMode = "PROJECT" | "TEMP";

export interface TaskOptions {
  visualFirst: boolean;
  create3D: boolean;
  review: boolean;
  autoTest: boolean;
  autoFix: boolean;
  approval: boolean;
  risk: "low" | "medium" | "high";
  revisions: number;
  fixAttempts: number;
  effort?: EffortLevel;
  research?: "AUTO" | "ON" | "OFF";
  chatMode?: ChatMode;
}

export const DEFAULT_TASK_OPTIONS: TaskOptions = {
  visualFirst: true,
  create3D: true,
  review: true,
  autoTest: true,
  autoFix: true,
  approval: true,
  risk: "medium",
  revisions: 3,
  fixAttempts: 3,
  effort: "AUTO",
  research: "AUTO",
  chatMode: "PROJECT",
};

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
  artifact?: ChatArtifact;
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

export type ChatArtifactType = "IMAGE" | "MODEL_3D" | "FILE" | "DIFF" | "REPORT";
export type ChatArtifactState = "GENERATING" | "READY" | "APPROVED" | "REJECTED" | "FAILED";

export interface ChatArtifact {
  id: string;
  jobId?: string;
  messageId?: string;
  type: ChatArtifactType;
  name: string;
  mime?: string;
  size?: number;
  state: ChatArtifactState;
  previewUrl?: string;
  contentUrl?: string;
  modelUrl?: string;
  metadata?: {
    version?: number;
    views?: string[];
    risk?: string;
    reviewer?: string;
    decision?: string;
    fileCount?: number;
    [key: string]: unknown;
  };
  actions?: string[];
  createdAt: number;
  updatedAt?: number;
  version?: number;
  revision?: number;
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
  cycle?: number;
  attempt?: number;
  startedAt?: number;
  updatedAt?: number;
  finishedAt?: number;
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

export interface JobProjection {
  jobId: string;
  messages: ChatMessage[];
  activities: ChatActivity[];
  artifacts: ChatArtifact[];
  contextItems: ContextItem[];
  changedFiles: ChangedFile[];
  review: Review | null;
  views: ViewTile[];
  concept: { version: number; status: string; prompt?: string };
  modelInfo: ModelInfo;
  testState: TestState;
  testCases: TestCaseResult[];
  testFailures: TestFailure[];
  testLogs: TestLog[];
}

export type ViewName = "FRONT" | "BACK" | "LEFT" | "RIGHT" | "TOP" | "BOTTOM";
export type ViewState = "EMPTY" | "GENERATING" | "READY" | "FAILED" | "APPROVED";

export interface ViewTile {
  name: ViewName;
  state: ViewState;
  assetId?: string;
  imageUrl?: string;
  version?: number;
  error?: string;
}

export interface ConceptInfo {
  version: number;
  status: "GENERATING" | "READY" | "APPROVED" | "FAILED";
  prompt?: string;
}

export type ModelGenState = "IDLE" | "GENERATING" | "READY" | "FAILED";

export interface ModelInfo {
  state: ModelGenState;
  approvalState?: "PENDING_APPROVAL" | "APPROVED";
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

export type StudioReadiness =
  | "MCP_RUNTIME_AVAILABLE"
  | "MCP_CONNECTED"
  | "STUDIO_NOT_RUNNING"
  | "STUDIO_INSTANCE_FOUND"
  | "MULTIPLE_STUDIOS"
  | "PROJECT_SELECTED"
  | "PROJECT_READY"
  | "MCP_SETUP_REQUIRED"
  | "MCP_RUNTIME_ERROR"
  | "NO_PROJECT";

export interface StudioStateSnapshot {
  state: StudioState;
  readiness?: StudioReadiness;
  selectedStudioId?: string | null;
  studioId?: string | null;
  projectName?: string | null;
  placeId?: string | number | null;
  universeId?: string | number | null;
}

export interface StudioInstance {
  id: string;
  label: string;
  placeId?: string | number | null;
  universeId?: string | number | null;
  project?: string | null;
  raw: Record<string, unknown>;
}

export interface StudioDiscoverySnapshot {
  state: StudioReadiness;
  selectedStudioId: string | null;
  detail: string;
  studios: StudioInstance[];
  capabilities?: {
    name: string;
    category: string;
    description: string;
    inputSchema: Record<string, unknown>;
  }[];
}

export interface ProjectIdentity {
  name: string;
  studioId: string | null;
  placeId: string | number | null;
  universeId: string | number | null;
}

export interface StudioNode {
  id: string;
  name: string;
  className: string;
  path: string;
  children?: StudioNode[];
  locked?: boolean;
  usedAsContext?: boolean;
}

export type TestStatus = "IDLE" | "STARTING" | "RUNNING" | "STOPPING" | "STOPPED" | "FAILED" | "STALE";
export type LogLevel = "ERR" | "WARN" | "ZEN" | "SRV" | "CLI";

export interface TestLog {
  id: string;
  runId?: string;
  jobId?: string;
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
  runId?: string;
  jobId?: string;
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
  runId?: string;
  jobId?: string;
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
  resultStatus?: "PASSED" | "FAILED" | "SKIPPED" | "NOT_RUN" | "CANCELLED";
  counts?: { total: number; passed: number; failed: number; skipped: number };
}

export interface ModelOption {
  id: string;
  label: string;
  available?: boolean;
}

export interface ModelSettings {
  chatgpt: { model: string; reasoning: boolean };
  deepseek: { model: string; reasoning: boolean };
  hunyuan: { version: string; quality: string };
  smartRouting: boolean;
}

export interface ModelCatalog {
  chatgpt: { models: ModelOption[]; reasoningOptions?: ModelOption[] };
  deepseek: { models: ModelOption[]; reasoningOptions?: ModelOption[] };
  hunyuan: { versions: ModelOption[]; qualities: ModelOption[] };
}

export interface Settings {
  models: ModelSettings;
  autoApprove: boolean;
  maxRevisions: number;
  bridgePort: number;
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
  hunyuan: ConnectionStatus;
  studio: ConnectionStatus;
}

export type BootStage = "CORE" | "STATE" | "BRIDGE" | "UI" | "BROWSER" | "AI" | "STUDIO";
export type BootState = "READY" | "CONNECTING" | "OFF";

export interface BootStep {
  stage: BootStage;
  state: BootState;
}

export type ReadinessStepState =
  | "CHECKING"
  | "READY"
  | "LOGIN_REQUIRED"
  | "NOT_FOUND"
  | "SETUP_REQUIRED"
  | "SELECT_REQUIRED"
  | "PROJECT_READY"
  | "CAPABILITY_MISSING"
  | "CLEANUP_REQUIRED"
  | "AUTHENTICATED"
  | "EXPIRED"
  | "CHALLENGE"
  | "OFF"
  | "CONNECTING"
  | "ERROR"
  | "OPTIONAL";

export interface ReadinessStep {
  id: string;
  label: string;
  providerId?: ProviderId;
  required: boolean;
  state: ReadinessStepState;
  detail?: string;
}

export type ReadinessState = "CHECKING" | "READY" | "ACTION_REQUIRED" | "DEGRADED";

export interface ReadinessStateInfo {
  state: ReadinessState;
  steps: ReadinessStep[];
  canRunProjectTasks?: boolean;
  checkedAt?: number;
  checks?: ReadinessStep[];
  providers?: ProviderReadiness[];
  studio?: Record<string, unknown>;
  storage?: {
    bytesUsed: number;
    budgetBytes: number;
    withinBudget: boolean;
  };
  system?: Record<string, unknown>;
}

export interface ProviderCapabilities {
  supportsText: boolean;
  supportsReasoning: boolean;
  reasoningLevels: string[];
  supportsSearch: boolean;
  supportsFiles: boolean;
  acceptedMimeTypes: string[];
  acceptedExtensions: string[];
  maxFiles: number;
  maxBytesPerFile: number;
  supportsImages: boolean;
  supportsVision: boolean;
  supportsAudio: boolean;
  supportsArchives: boolean;
  supportsCodeExecution: boolean;
  supportsTools: boolean;
  supportsImageGeneration: boolean;
  supports3DGeneration: boolean;
  supportsGeometry: boolean;
  supportsTexture: boolean;
  supportsDownload: boolean;
  supportsCancel: boolean;
  supportsStreaming: boolean;
  source?: string;
  detectedAt?: number;
}

export interface ProviderMode {
  id: string;
  label: string;
  capabilities: ProviderCapabilities;
  source?: string;
}

export interface ProviderModel {
  id: string;
  label: string;
  available?: boolean;
}

export interface ProviderDescriptor {
  providerId: string;
  displayName: string;
  webUrl: string;
  support: "VERIFIED" | "BETA" | "EXPERIMENTAL" | "UNSUPPORTED";
  adapter: string;
  roles: ProviderRole[];
  modes: ProviderMode[];
  enabled: boolean;
  authState: ProviderAuthState;
  route: string;
  detail?: string;
  selection?: Record<string, unknown>;
  session?: Record<string, unknown> | null;
  liveCapabilities?: ProviderCapabilities | null;
  status?: ConnectionStatus;
  loginState?: ProviderLoginState;
}

export type ProviderLoginState = "IDLE" | "OPENING" | "WAITING" | "VERIFYING" | "READY" | "FAILED";

export type ProviderAuthState =
  | "UNKNOWN"
  | "CHECKING"
  | "LOGIN_REQUIRED"
  | "LOGIN_WINDOW_OPEN"
  | "AUTHENTICATING"
  | "CHALLENGE"
  | "AUTHENTICATED"
  | "VERIFYING_PERSISTENCE"
  | "READY"
  | "EXPIRED"
  | "ERROR";

export interface ProviderReadiness {
  providerId: string;
  displayName: string;
  authState: ProviderAuthState;
  route: string;
  required: boolean;
  detail: string;
}

export interface ToolDescriptor {
  id: string;
  name: string;
  purpose: string;
  version: string;
  source: string;
  license: string;
  downloadSize: number;
  installedSize: number;
  checksum: string;
  trustLevel: string;
  updatePolicy: string;
  archive: boolean;
  status: "INSTALLED" | "AVAILABLE" | "ON_DEMAND";
  lastUsed?: number | null;
  installedAt?: number | null;
}

export interface StorageInfo {
  bytesUsed: number;
  budgetBytes: number;
  withinBudget: boolean;
  categories: { id: string; bytes: number; protected: boolean }[];
}

export interface ZenlessEventMap {
  BOOT_STAGE_CHANGED: { stage: BootStage; state: BootState };
  BOOT_COMPLETE: Record<string, never>;
  CONNECTION_CHANGED: Partial<ConnectionInfo>;
  AGENT_STATUS_CHANGED: { agent: AgentId; status: ConnectionStatus };
  PIPELINE_STATE_CHANGED: { jobId: string; stage: PipelineStage };
  JOB_CREATED: { jobId: string; job: Job };
  JOB_UPDATED: { jobId: string; job: Partial<Job> & { id: string } };
  JOB_COMPLETE: { jobId: string };
  JOB_FAILED: { jobId: string; reason: string };
  CHAT_STREAM_STARTED: { jobId: string; messageId: string; provider?: string };
  CHAT_STREAM_DELTA: { jobId: string; messageId: string; delta: string };
  CHAT_STREAM_FINISHED: { jobId: string; messageId: string };
  CHAT_MESSAGE: { jobId: string; message: ChatMessage };
  CHAT_ACTIVITY: { jobId: string; activity: ChatActivity };
  CHAT_ARTIFACT: { jobId: string; artifact: ChatArtifact };
  CHAT_SYSTEM_EVENT: {
    severity: "CRITICAL" | "ERROR" | "WARNING" | "INFO";
    title: string;
    message: string;
    recovery?: string;
    jobId?: string;
    diagnosticId?: string;
  };
  LOGIN_REQUIRED: { providerId: ProviderId };
  LOGIN_WINDOW_WILL_OPEN: { providerId: ProviderId };
  LOGIN_WINDOW_OPENED: { providerId: ProviderId; route: string };
  LOGIN_DETECTED: { providerId: ProviderId };
  LOGIN_PERSISTENCE_VERIFYING: { providerId: ProviderId };
  LOGIN_READY: { providerId: ProviderId; route: string; persistent: boolean };
  LOGIN_FAILED: { providerId: ProviderId; message: string; recovery: string };
  PROVIDER_CAPABILITIES_CHANGED: { provider: ProviderDescriptor };
  PROVIDER_MODEL_CHANGED: { providerId: string; selection: Record<string, string> };
  READINESS_CHANGED: { readiness: ReadinessStateInfo };
  CONTEXT_UPDATED: { jobId: string; items: ContextItem[] };
  CHANGES_UPDATED: { jobId: string; files: ChangedFile[] };
  REVIEW_READY: { jobId: string; review: Review };
  VISUAL_GENERATION_CHANGED: {
    jobId: string;
    view: ViewName;
    state: ViewState;
    assetId?: string | null;
    conceptVersion: number;
  };
  VISUAL_READY: {
    jobId: string;
    view: ViewName;
    imageUrl: string;
    assetId: string;
    conceptVersion: number;
  };
  VISUAL_APPROVED: { jobId: string; views: ViewName[]; conceptVersion?: number };
  MODEL_GENERATION_CHANGED: { jobId: string; target: "geometry" | "texture"; state: ModelGenState };
  MODEL_READY: {
    jobId: string;
    assetId: string;
    version: number;
    modelUrl: string;
    filename?: string;
    geometryStatus: "READY";
    textureStatus: "READY";
  };
  MODEL_APPROVED: { jobId: string };
  ASSETS_UPDATED: { assets: Asset[] };
  STUDIO_STATE_CHANGED: StudioStateSnapshot;
  STUDIO_DISCOVERY_CHANGED: StudioDiscoverySnapshot;
  STUDIO_SELECTION_REQUIRED: StudioDiscoverySnapshot;
  STUDIO_TREE_UPDATED: { tree: StudioNode[] };
  TEST_STARTED: { jobId: string; runId: string };
  TEST_CASE_STARTED: { jobId: string; testCase: TestCaseResult };
  TEST_CASE_FINISHED: { jobId: string; testCase: TestCaseResult };
  TEST_FAILURE: { jobId: string; failure: TestFailure };
  TEST_LOG: { jobId: string; log: TestLog };
  TEST_FINISHED: {
    jobId: string;
    runId: string;
    status: "PASSED" | "FAILED" | "SKIPPED" | "NOT_RUN" | "CANCELLED";
    counts: { total: number; passed: number; failed: number; skipped: number };
    passed?: boolean;
  };
  TOOL_STATUS_CHANGED: { tool: ToolDescriptor };
  STORAGE_CLEANUP_COMPLETED: {
    bytesBefore: number;
    bytesAfter: number;
    bytesRemoved: number;
    categories: string[];
    itemsRemoved: number;
    storage: StorageInfo;
  };
  SETTINGS_CHANGED: { settings: Partial<Settings> };
  DIAGNOSTIC_EVENT: { diagnostic: Diagnostic };
}

export type ZenlessEvent = {
  [K in keyof ZenlessEventMap]: { type: K; data: ZenlessEventMap[K] };
}[keyof ZenlessEventMap];

export type ZenlessEventHandler = (event: ZenlessEvent) => void;
