import type { ZenlessAPI } from "../api/types";
import type {
  AgentInfo,
  Asset,
  ChangedFile,
  ChatMessage,
  ConnectionInfo,
  ContextItem,
  Diagnostic,
  Job,
  ModelCatalog,
  ModelInfo,
  ProviderId,
  Review,
  Settings,
  StudioNode,
  StudioState,
  TaskOptions,
  TestLog,
  TestState,
  ViewTile,
} from "@/types";
import { DEFAULT_TASK_OPTIONS } from "@/types";
import {
  mockAgents,
  mockAssets,
  mockBootSteps,
  mockChanges,
  mockChatMessages,
  mockConnections,
  mockContext,
  mockDiagnostics,
  mockJobs,
  mockModelCatalog,
  mockModelInfo,
  mockSettings,
  mockStudioTree,
  mockTestLogs,
  mockViews,
} from "./mockData";

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const uid = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));

export class MockZenlessAPI implements ZenlessAPI {
  private jobs: Job[] = clone(mockJobs);
  private messages: ChatMessage[] = clone(mockChatMessages);
  private context: ContextItem[] = clone(mockContext);
  private changes: ChangedFile[] = clone(mockChanges);
  private views: ViewTile[] = clone(mockViews);
  private model: ModelInfo = clone(mockModelInfo);
  private assets: Asset[] = clone(mockAssets);
  private studioTree: StudioNode[] = clone(mockStudioTree);
  private logs: TestLog[] = clone(mockTestLogs);
  private diagnostics: Diagnostic[] = clone(mockDiagnostics);
  private settings: Settings = clone(mockSettings);
  private connections: ConnectionInfo = clone(mockConnections);
  private agents: AgentInfo[] = clone(mockAgents);
  private testState: TestState = { status: "IDLE", elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 };
  private studioState: StudioState = "ONLINE";
  private conceptPrompt = "Industrial bomb device, dark metal, sci-fi";

  async bootstrap() {
    await delay(400);
    return { steps: clone(mockBootSteps) };
  }
  async getStatus() {
    await delay(100);
    return { ready: true };
  }
  async getConnections() {
    await delay(80);
    return clone(this.connections);
  }
  async getAgents() {
    await delay(80);
    return clone(this.agents);
  }
  async loginProvider(provider: ProviderId) {
    await delay(50);
    this.connections[provider] = "READY";
    this.setMockAgentStatus(provider, "READY");
    return { ok: true };
  }
  async getJobs() {
    await delay(80);
    return clone(this.jobs);
  }
  async getJob(id: string) {
    await delay(60);
    const job = this.jobs.find((j) => j.id === id);
    if (!job) throw new Error("Job not found");
    return clone(job);
  }
  async createJob(title: string, options?: Partial<TaskOptions>) {
    await delay(150);
    const job: Job = {
      id: uid("job"),
      title,
      status: "RUNNING",
      stage: "COLLECTING_CONTEXT",
      createdAt: Date.now(),
      updatedAt: Date.now(),
      options: { ...DEFAULT_TASK_OPTIONS, ...options },
    };
    this.jobs.unshift(job);
    return clone(job);
  }
  async pauseJob(id: string) {
    await delay(100);
    return this.updateJob(id, { status: "PAUSED", stage: "PAUSED" });
  }
  async resumeJob(id: string) {
    await delay(100);
    return this.updateJob(id, { status: "RUNNING", stage: "BUILDING" });
  }
  async cancelJob(id: string) {
    await delay(100);
    this.jobs = this.jobs.filter((j) => j.id !== id);
    return { ok: true };
  }
  async getMessages(jobId: string) {
    await delay(60);
    return clone(this.messages.filter((message) => message.jobId === jobId));
  }
  async sendMessage(
    content: string,
    jobId?: string,
    attachments: File[] = [],
    _options?: TaskOptions,
  ) {
    await delay(120);
    const msg: ChatMessage = {
      id: uid("msg"),
      role: "user",
      content,
      timestamp: Date.now(),
      jobId,
      attachments: attachments.map((file, index) => ({
        id: `mock_att_${Date.now()}_${index}`,
        name: file.name,
        type: file.type.startsWith("image/") ? "image" : "file",
        size: file.size,
        mime: file.type,
      })),
    };
    this.messages.push(msg);
    return { messageId: msg.id, jobId };
  }
  async cancelGeneration(_jobId: string) {
    await delay(80);
    return { ok: true };
  }
  async getContext(_jobId: string) {
    await delay(80);
    return clone(this.context);
  }
  async refreshContext(_jobId: string) {
    await delay(200);
    return clone(this.context);
  }
  async includeContext(itemId: string) {
    await delay(50);
    this.context = this.context.map((c) =>
      c.id === itemId ? { ...c, state: "included" as const } : c,
    );
    return { ok: true };
  }
  async excludeContext(itemId: string) {
    await delay(50);
    this.context = this.context.map((c) =>
      c.id === itemId ? { ...c, state: "excluded" as const } : c,
    );
    return { ok: true };
  }
  async lockContext(itemId: string) {
    await delay(50);
    this.context = this.context.map((c) =>
      c.id === itemId ? { ...c, state: "locked" as const } : c,
    );
    return { ok: true };
  }
  async unlockContext(itemId: string) {
    await delay(50);
    this.context = this.context.map((c) =>
      c.id === itemId ? { ...c, state: "included" as const } : c,
    );
    return { ok: true };
  }
  async inspectContext(itemId: string) {
    await delay(50);
    const item = this.context.find((c) => c.id === itemId);
    if (!item) throw new Error("Context item not found");
    return clone(item);
  }
  async getChanges(_jobId: string) {
    await delay(80);
    return clone(this.changes);
  }
  async getReview(_jobId: string): Promise<Review> {
    await delay(80);
    return {
      decision: "APPROVE",
      risk: "LOW",
      criticalIssues: [],
      warnings: ["Verify ragdoll recovery after repeated impacts."],
      suggestions: ["Keep attachment creation server-authoritative."],
      summary: "Changes are consistent with the current context.",
      reviewer: "Reviewer",
      timestamp: Date.now(),
      files: clone(this.changes),
      ready: true,
    };
  }
  async approveChanges(_jobId: string) {
    await delay(100);
    return { ok: true };
  }
  async rejectChanges(_jobId: string) {
    await delay(100);
    return { ok: true };
  }
  async editChanges(_jobId: string, _fileId: string, _content: string) {
    await delay(100);
    return { ok: true };
  }
  async getVisual(_jobId: string) {
    await delay(80);
    return {
      views: clone(this.views),
      concept: { version: 3, status: "READY", prompt: this.conceptPrompt },
    };
  }
  async approveVisual(_jobId: string) {
    await delay(80);
    this.views = this.views.map((v) => ({ ...v, state: "APPROVED" as const }));
    return { ok: true };
  }
  async editConcept(_jobId: string, prompt: string) {
    await delay(80);
    this.conceptPrompt = prompt;
    return { ok: true };
  }
  async regenerateVisual(_jobId: string) {
    await delay(200);
    this.views = this.views.map((v) => ({ ...v, state: "GENERATING" as const }));
    return { ok: true };
  }
  async regenerateView(_jobId: string, view: string) {
    await delay(150);
    this.views = this.views.map((v) =>
      v.name === view ? { ...v, state: "GENERATING" as const } : v,
    );
    return { ok: true };
  }
  async getModel(_jobId: string) {
    await delay(80);
    return clone(this.model);
  }
  async approveModel(_jobId: string) {
    await delay(80);
    this.model = { ...this.model, state: "APPROVED" as const };
    return { ok: true };
  }
  async regenerateGeometry(_jobId: string) {
    await delay(150);
    this.model = { ...this.model, geometryStatus: "GENERATING" as const };
    return { ok: true };
  }
  async regenerateTexture(_jobId: string) {
    await delay(150);
    this.model = { ...this.model, textureStatus: "GENERATING" as const };
    return { ok: true };
  }
  async getAssets() {
    await delay(80);
    return clone(this.assets);
  }
  async getStudioState() {
    await delay(50);
    return { state: this.studioState };
  }
  async getStudioTree() {
    await delay(80);
    return clone(this.studioTree);
  }
  async searchStudio(query: string) {
    await delay(100);
    const results: StudioNode[] = [];
    const walk = (nodes: StudioNode[]) => {
      for (const n of nodes) {
        if (n.name.toLowerCase().includes(query.toLowerCase())) results.push(n);
        if (n.children) walk(n.children);
      }
    };
    walk(this.studioTree);
    return results;
  }
  async refreshStudio() {
    await delay(200);
    return { ok: true };
  }
  async lockStudioReference(nodeId: string) {
    await delay(50);
    this.studioTree = mapStudioNode(this.studioTree, nodeId, (node) => ({ ...node, locked: true }));
    return { ok: true };
  }
  async unlockStudioReference(nodeId: string) {
    await delay(50);
    this.studioTree = mapStudioNode(this.studioTree, nodeId, (node) => ({
      ...node,
      locked: false,
    }));
    return { ok: true };
  }
  async useStudioAsContext(nodeId: string) {
    await delay(50);
    this.studioTree = mapStudioNode(this.studioTree, nodeId, (node) => ({
      ...node,
      usedAsContext: true,
    }));
    return { ok: true };
  }
  async inspectStudio(nodeId: string) {
    await delay(50);
    const find = (nodes: StudioNode[]): StudioNode | undefined => {
      for (const n of nodes) {
        if (n.id === nodeId) return n;
        if (n.children) {
          const f = find(n.children);
          if (f) return f;
        }
      }
    };
    const node = find(this.studioTree);
    if (!node) throw new Error("Node not found");
    return clone(node);
  }
  async startTest(_jobId: string) {
    await delay(100);
    this.testState = { status: "RUNNING", elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 };
    return { ok: true };
  }
  async stopTest(_jobId: string) {
    await delay(80);
    this.testState = { ...this.testState, status: "STOPPED" };
    return { ok: true };
  }
  async getTestState(_jobId: string) {
    await delay(50);
    return clone(this.testState);
  }
  async getSettings() {
    await delay(50);
    return clone(this.settings);
  }
  async updateSettings(partial: Partial<Settings>) {
    await delay(80);
    this.settings = {
      ...this.settings,
      ...partial,
      models: { ...this.settings.models, ...(partial.models ?? {}) },
    };
    return clone(this.settings);
  }
  async getModels(): Promise<ModelCatalog> {
    await delay(50);
    return clone(mockModelCatalog);
  }
  async setModel(agent: "chatgpt" | "deepseek" | "hunyuan", model: string) {
    await delay(50);
    if (agent === "hunyuan") this.settings.models.hunyuan.version = model;
    else this.settings.models[agent].model = model;
    return { ok: true };
  }
  async setSmartRouting(enabled: boolean) {
    await delay(50);
    this.settings.models.smartRouting = enabled;
    return { ok: true };
  }
  async getDiagnostics() {
    await delay(50);
    return clone(this.diagnostics);
  }

  getMockMessages() {
    return this.messages;
  }
  getMockLogs() {
    return this.logs;
  }
  getMockTestState() {
    return this.testState;
  }
  setMockTestState(s: TestState) {
    this.testState = s;
  }
  addMockLog(log: TestLog) {
    this.logs.push(log);
  }
  setMockStudioState(s: StudioState) {
    this.studioState = s;
  }
  setMockConnection(key: keyof ConnectionInfo, status: ConnectionInfo[keyof ConnectionInfo]) {
    this.connections[key] = status;
  }
  setMockAgentStatus(id: string, status: ConnectionInfo["bridge"]) {
    this.agents = this.agents.map((a) => (a.id === id ? { ...a, status } : a));
  }

  private updateJob(id: string, patch: Partial<Job>): Job {
    const idx = this.jobs.findIndex((j) => j.id === id);
    if (idx < 0) throw new Error("Job not found");
    this.jobs[idx] = { ...this.jobs[idx], ...patch, updatedAt: Date.now() };
    return clone(this.jobs[idx]);
  }
}

function mapStudioNode(
  nodes: StudioNode[],
  id: string,
  update: (node: StudioNode) => StudioNode,
): StudioNode[] {
  return nodes.map((node) => ({
    ...(node.id === id ? update(node) : node),
    children: node.children ? mapStudioNode(node.children, id, update) : node.children,
  }));
}
