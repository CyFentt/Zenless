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
} from '@/types';

export interface ZenlessAPI {
  // Boot
  bootstrap(): Promise<{ steps: BootStep[] }>;
  getStatus(): Promise<{ ready: boolean }>;

  // Connections / Agents
  getConnections(): Promise<ConnectionInfo>;
  getAgents(): Promise<AgentInfo[]>;

  // Jobs
  getJobs(): Promise<Job[]>;
  getJob(id: string): Promise<Job>;
  createJob(title: string, options?: Partial<TaskOptions>): Promise<Job>;
  pauseJob(id: string): Promise<Job>;
  resumeJob(id: string): Promise<Job>;
  cancelJob(id: string): Promise<{ ok: boolean }>;

  // Chat
  sendMessage(content: string, jobId?: string): Promise<{ messageId: string; jobId?: string }>;
  cancelGeneration(jobId: string): Promise<{ ok: boolean }>;

  // Context
  getContext(jobId: string): Promise<ContextItem[]>;
  refreshContext(jobId: string): Promise<ContextItem[]>;
  includeContext(itemId: string): Promise<{ ok: boolean }>;
  excludeContext(itemId: string): Promise<{ ok: boolean }>;
  lockContext(itemId: string): Promise<{ ok: boolean }>;
  unlockContext(itemId: string): Promise<{ ok: boolean }>;
  inspectContext(itemId: string): Promise<ContextItem>;

  // Changes
  getChanges(jobId: string): Promise<ChangedFile[]>;
  getReview(jobId: string): Promise<{ files: ChangedFile[]; ready: boolean }>;
  approveChanges(jobId: string): Promise<{ ok: boolean }>;
  rejectChanges(jobId: string): Promise<{ ok: boolean }>;
  editChanges(jobId: string, fileId: string, content: string): Promise<{ ok: boolean }>;

  // Visual
  getVisual(jobId: string): Promise<{ views: ViewTile[]; concept: { version: number; status: string; prompt?: string } }>;
  approveVisual(jobId: string): Promise<{ ok: boolean }>;
  editConcept(jobId: string, prompt: string): Promise<{ ok: boolean }>;
  regenerateVisual(jobId: string): Promise<{ ok: boolean }>;
  regenerateView(jobId: string, view: string): Promise<{ ok: boolean }>;

  // 3D Model
  getModel(jobId: string): Promise<ModelInfo>;
  approveModel(jobId: string): Promise<{ ok: boolean }>;
  regenerateGeometry(jobId: string): Promise<{ ok: boolean }>;
  regenerateTexture(jobId: string): Promise<{ ok: boolean }>;

  // Assets
  getAssets(): Promise<Asset[]>;

  // Studio
  getStudioState(): Promise<{ state: StudioState }>;
  getStudioTree(): Promise<StudioNode[]>;
  searchStudio(query: string): Promise<StudioNode[]>;
  refreshStudio(): Promise<{ ok: boolean }>;
  inspectStudio(nodeId: string): Promise<StudioNode>;

  // Test
  startTest(jobId: string): Promise<{ ok: boolean }>;
  stopTest(jobId: string): Promise<{ ok: boolean }>;
  getTestState(jobId: string): Promise<TestState>;

  // Settings
  getSettings(): Promise<Settings>;
  updateSettings(partial: Partial<Settings>): Promise<Settings>;
  getModels(): Promise<ModelSettings>;
  setModel(agent: 'chatgpt' | 'deepseek', model: string): Promise<{ ok: boolean }>;
  setSmartRouting(enabled: boolean): Promise<{ ok: boolean }>;

  // Diagnostics
  getDiagnostics(): Promise<Diagnostic[]>;
}
