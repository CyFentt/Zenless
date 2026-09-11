import type {
  AgentInfo,
  Asset,
  BootStep,
  ChatMessage,
  ChatActivity,
  ChatArtifact,
  ChangedFile,
  ConnectionInfo,
  ContextItem,
  Diagnostic,
  Job,
  ModelCatalog,
  ModelInfo,
  ProviderDescriptor,
  ProviderId,
  ReadinessStateInfo,
  Review,
  Settings,
  StudioNode,
  StudioStateSnapshot,
  StorageInfo,
  TaskOptions,
  TestCaseResult,
  TestFailure,
  TestLog,
  TestState,
  ToolDescriptor,
  ViewTile,
} from '@/types';

export interface JobTimelineSnapshot {
  jobId: string;
  messages: ChatMessage[];
  activities: ChatActivity[];
  artifacts: ChatArtifact[];
  test: {
    testState: TestState;
    cases: TestCaseResult[];
    failures: TestFailure[];
    logs?: TestLog[];
  };
}

export interface ZenlessAPI {
  bootstrap(): Promise<{ steps: BootStep[] }>;
  getStatus(): Promise<{ ready: boolean }>;

  getConnections(): Promise<ConnectionInfo>;
  getAgents(): Promise<AgentInfo[]>;
  getProviders(): Promise<ProviderDescriptor[]>;
  getReadiness(): Promise<ReadinessStateInfo>;
  loginProvider(provider: ProviderId): Promise<{ ok: boolean }>;

  getJobs(): Promise<Job[]>;
  getJob(id: string): Promise<Job>;
  createJob(title: string, options?: Partial<TaskOptions>): Promise<Job>;
  pauseJob(id: string): Promise<Job>;
  resumeJob(id: string): Promise<Job>;
  cancelJob(id: string): Promise<{ ok: boolean }>;
  getMessages(jobId: string): Promise<ChatMessage[]>;
  getTimeline(jobId: string, signal?: AbortSignal): Promise<JobTimelineSnapshot>;

  sendMessage(content: string, jobId?: string, attachments?: File[], options?: TaskOptions): Promise<{ messageId: string; jobId?: string }>;
  cancelGeneration(jobId: string): Promise<{ ok: boolean }>;

  getContext(jobId: string, signal?: AbortSignal): Promise<ContextItem[]>;
  refreshContext(jobId: string): Promise<ContextItem[]>;
  includeContext(itemId: string): Promise<{ ok: boolean }>;
  excludeContext(itemId: string): Promise<{ ok: boolean }>;
  lockContext(itemId: string): Promise<{ ok: boolean }>;
  unlockContext(itemId: string): Promise<{ ok: boolean }>;
  inspectContext(itemId: string): Promise<ContextItem>;

  getChanges(jobId: string, signal?: AbortSignal): Promise<ChangedFile[]>;
  getReview(jobId: string, signal?: AbortSignal): Promise<Review>;
  approveChanges(jobId: string): Promise<{ ok: boolean }>;
  rejectChanges(jobId: string): Promise<{ ok: boolean }>;
  editChanges(jobId: string, fileId: string, content: string): Promise<{ ok: boolean }>;

  getVisual(jobId: string, signal?: AbortSignal): Promise<{ views: ViewTile[]; concept: { version: number; status: string; prompt?: string } }>;
  approveVisual(jobId: string): Promise<{ ok: boolean }>;
  editConcept(jobId: string, prompt: string): Promise<{ ok: boolean }>;
  regenerateVisual(jobId: string): Promise<{ ok: boolean }>;
  regenerateView(jobId: string, view: string): Promise<{ ok: boolean }>;

  getModel(jobId: string, signal?: AbortSignal): Promise<ModelInfo>;
  approveModel(jobId: string): Promise<{ ok: boolean }>;
  regenerateGeometry(jobId: string): Promise<{ ok: boolean }>;
  regenerateTexture(jobId: string): Promise<{ ok: boolean }>;

  getAssets(): Promise<Asset[]>;

  getStudioState(): Promise<StudioStateSnapshot>;
  getStudioTree(): Promise<StudioNode[]>;
  searchStudio(query: string): Promise<StudioNode[]>;
  refreshStudio(): Promise<{ ok: boolean }>;
  inspectStudio(nodeId: string): Promise<StudioNode>;
  lockStudioReference(nodeId: string): Promise<{ ok: boolean }>;
  unlockStudioReference(nodeId: string): Promise<{ ok: boolean }>;
  useStudioAsContext(nodeId: string): Promise<{ ok: boolean }>;

  startTest(jobId: string): Promise<{ ok: boolean }>;
  stopTest(jobId: string): Promise<{ ok: boolean }>;
  getTestState(jobId: string): Promise<TestState>;

  getSettings(): Promise<Settings>;
  updateSettings(partial: Partial<Settings>): Promise<Settings>;
  getModels(): Promise<ModelCatalog>;
  setModel(agent: 'chatgpt' | 'deepseek' | 'hunyuan', model: string): Promise<{ ok: boolean }>;
  setSmartRouting(enabled: boolean): Promise<{ ok: boolean }>;

  getDiagnostics(): Promise<Diagnostic[]>;
  getTools(): Promise<ToolDescriptor[]>;
  getStorage(): Promise<StorageInfo>;
}
