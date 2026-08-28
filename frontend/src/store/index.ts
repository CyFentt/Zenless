import { create } from 'zustand';
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
  Settings,
  StudioNode,
  StudioState,
  TestLog,
  TestCaseResult,
  TestFailure,
  TestState,
  ViewTile,
  SocketStatus,
} from '@/types';

interface AppState {
  // Boot
  booted: boolean;
  bootSteps: BootStep[];

  // Navigation
  activePage: string;
  setActivePage: (page: string) => void;

  // Socket
  socketStatus: SocketStatus;

  // Connections / Agents
  connections: ConnectionInfo;
  agents: AgentInfo[];

  // Jobs
  jobs: Job[];
  currentJobId: string | null;
  setCurrentJobId: (id: string | null) => void;

  // Chat
  messages: ChatMessage[];
  streamingMessageId: string | null;
  streamingContent: string;

  // Context
  contextItems: ContextItem[];

  // Changes
  changedFiles: ChangedFile[];
  selectedFileId: string | null;
  setSelectedFileId: (id: string | null) => void;

  // Visual
  views: ViewTile[];
  conceptVersion: number;
  conceptStatus: string;
  conceptPrompt: string;

  // 3D Model
  modelInfo: ModelInfo;

  // Assets
  assets: Asset[];

  // Studio
  studioState: StudioState;
  studioTree: StudioNode[];
  selectedStudioNode: StudioNode | null;
  setSelectedStudioNode: (node: StudioNode | null) => void;
  studioQuery: string;
  setStudioQuery: (q: string) => void;

  // Test
  testState: TestState;
  testLogs: TestLog[];
  testCases: TestCaseResult[];
  testFailures: TestFailure[];
  logFilter: string;
  setLogFilter: (f: string) => void;

  // Settings
  settings: Settings | null;

  // Diagnostics
  diagnostics: Diagnostic[];

  // Setters (batch updates from events)
  setBooted: (b: boolean) => void;
  setBootSteps: (steps: BootStep[]) => void;
  setSocketStatus: (s: SocketStatus) => void;
  setConnections: (c: Partial<ConnectionInfo>) => void;
  setAgents: (a: AgentInfo[]) => void;
  setJobs: (j: Job[]) => void;
  addJob: (j: Job) => void;
  updateJob: (id: string, patch: Partial<Job>) => void;
  setMessages: (m: ChatMessage[]) => void;
  addMessage: (m: ChatMessage) => void;
  setStreaming: (id: string | null) => void;
  appendStreamDelta: (delta: string) => void;
  finishStream: () => void;
  setContextItems: (c: ContextItem[]) => void;
  setChangedFiles: (f: ChangedFile[]) => void;
  setViews: (v: ViewTile[]) => void;
  setConcept: (version: number, status: string, prompt?: string) => void;
  setModelInfo: (m: ModelInfo) => void;
  setAssets: (a: Asset[]) => void;
  setStudioState: (s: StudioState) => void;
  setStudioTree: (t: StudioNode[]) => void;
  setTestState: (t: TestState) => void;
  addTestLog: (log: TestLog) => void;
  setTestLogs: (logs: TestLog[]) => void;
  upsertTestCase: (testCase: TestCaseResult) => void;
  addTestFailure: (failure: TestFailure) => void;
  resetTestDetails: () => void;
  setSettings: (s: Settings) => void;
  addDiagnostic: (d: Diagnostic) => void;
  setDiagnostics: (d: Diagnostic[]) => void;
}

export const useStore = create<AppState>((set) => ({
  booted: false,
  bootSteps: [],

  activePage: 'home',
  setActivePage: (page) => set({ activePage: page }),

  socketStatus: 'DISCONNECTED',

  connections: {
    bridge: 'OFF',
    browser: 'OFF',
    chatgpt: 'OFF',
    deepseek: 'OFF',
    hunyuan: 'OFF',
    studio: 'OFF',
  },
  agents: [],

  jobs: [],
  currentJobId: null,
  setCurrentJobId: (id) => set({ currentJobId: id }),

  messages: [],
  streamingMessageId: null,
  streamingContent: '',

  contextItems: [],

  changedFiles: [],
  selectedFileId: null,
  setSelectedFileId: (id) => set({ selectedFileId: id }),

  views: [],
  conceptVersion: 0,
  conceptStatus: 'EMPTY',
  conceptPrompt: '',

  modelInfo: { state: 'EMPTY', geometryStatus: 'IDLE', textureStatus: 'IDLE' },

  assets: [],

  studioState: 'OFFLINE',
  studioTree: [],
  selectedStudioNode: null,
  setSelectedStudioNode: (node) => set({ selectedStudioNode: node }),
  studioQuery: '',
  setStudioQuery: (q) => set({ studioQuery: q }),

  testState: { status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 },
  testLogs: [],
  testCases: [],
  testFailures: [],
  logFilter: 'ALL',
  setLogFilter: (f) => set({ logFilter: f }),

  settings: null,

  diagnostics: [],

  setBooted: (b) => set({ booted: b }),
  setBootSteps: (steps) => set({ bootSteps: steps }),
  setSocketStatus: (s) => set({ socketStatus: s }),
  setConnections: (c) => set((state) => ({ connections: { ...state.connections, ...c } })),
  setAgents: (a) => set({ agents: a }),
  setJobs: (j) => set({ jobs: j }),
  addJob: (j) => set((state) => ({ jobs: [j, ...state.jobs] })),
  updateJob: (id, patch) =>
    set((state) => ({ jobs: state.jobs.map((j) => (j.id === id ? { ...j, ...patch, updatedAt: Date.now() } : j)) })),
  setMessages: (m) => set({ messages: m }),
  addMessage: (m) => set((state) => ({ messages: [...state.messages, m] })),
  setStreaming: (id) => set({ streamingMessageId: id, streamingContent: '' }),
  appendStreamDelta: (delta) => set((state) => ({ streamingContent: state.streamingContent + delta })),
  finishStream: () =>
    set((state) => {
      if (!state.streamingMessageId) return {};
      const msg: ChatMessage = {
        id: state.streamingMessageId,
        role: 'zenless',
        content: state.streamingContent,
        timestamp: Date.now(),
      };
      return { messages: [...state.messages, msg], streamingMessageId: null, streamingContent: '' };
    }),
  setContextItems: (c) => set({ contextItems: c }),
  setChangedFiles: (f) => set({ changedFiles: f }),
  setViews: (v) => set({ views: v }),
  setConcept: (version, status, prompt) =>
    set({ conceptVersion: version, conceptStatus: status, conceptPrompt: prompt ?? '' }),
  setModelInfo: (m) => set({ modelInfo: m }),
  setAssets: (a) => set({ assets: a }),
  setStudioState: (s) => set({ studioState: s }),
  setStudioTree: (t) => set({ studioTree: t }),
  setTestState: (t) => set({ testState: t }),
  addTestLog: (log) => set((state) => ({ testLogs: [...state.testLogs, log] })),
  setTestLogs: (logs) => set({ testLogs: logs }),
  upsertTestCase: (testCase) =>
    set((state) => {
      const exists = state.testCases.some((item) => item.id === testCase.id);
      return {
        testCases: exists
          ? state.testCases.map((item) => (item.id === testCase.id ? { ...item, ...testCase } : item))
          : [...state.testCases, testCase],
      };
    }),
  addTestFailure: (failure) => set((state) => ({ testFailures: [...state.testFailures, failure] })),
  resetTestDetails: () => set({ testCases: [], testFailures: [] }),
  setSettings: (s) => set({ settings: s }),
  addDiagnostic: (d) => set((state) => ({ diagnostics: [...state.diagnostics, d] })),
  setDiagnostics: (d) => set({ diagnostics: d }),
}));
