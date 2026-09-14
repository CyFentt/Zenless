import { useState, useRef, useEffect, lazy, Suspense } from 'react';
import { Paperclip, ArrowUp, Settings2, X, History, Plus } from 'lucide-react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { ApiError } from '@/services/api/realApi';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Tooltip } from '@/components/Tooltip';
import {
  DEFAULT_TASK_OPTIONS,
  PROVIDER_NAMES,
  type ChatActivity,
  type ChatArtifact,
  type ChatMessage,
  type ModelInfo,
  type ProviderId,
  type TaskOptions,
  type ViewName,
  type ViewState,
  type ViewTile,
} from '@/types';

import { ChatActivityGroup } from './ChatActivityGroup';
import { ChatChangeCard } from './ChatChangeCard';
import { ChatImageGallery } from './ChatImageGallery';
import { ChatModelCard } from './ChatModelCard';
import { ChatTestCard } from './ChatTestCard';
import { ChatErrorCard } from './ChatErrorCard';

const TaskOptionsPanel = lazy(() => import('./TaskOptionsPanel').then((m) => ({ default: m.TaskOptionsPanel })));

const VIEW_NAMES = new Set<ViewName>(['FRONT', 'BACK', 'LEFT', 'RIGHT', 'TOP', 'BOTTOM']);
const VIEW_STATES = new Set<ViewState>(['EMPTY', 'GENERATING', 'READY', 'FAILED', 'APPROVED']);
const MAX_ATTACHMENTS = 50;

function artifactViews(artifact: ChatArtifact): ViewTile[] {
  const raw = artifact.metadata?.views;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const value = item as Record<string, unknown>;
    const name = String(value.name ?? '') as ViewName;
    const state = String(value.state ?? 'EMPTY') as ViewState;
    if (!VIEW_NAMES.has(name) || !VIEW_STATES.has(state)) return [];
    return [{
      name,
      state,
      assetId: typeof value.assetId === 'string' ? value.assetId : undefined,
      imageUrl: typeof value.imageUrl === 'string' ? value.imageUrl : undefined,
      version: typeof value.version === 'number' ? value.version : artifact.version,
    }];
  });
}

function artifactModel(artifact: ChatArtifact): ModelInfo {
  const metadata = artifact.metadata ?? {};
  const status = (value: unknown): ModelInfo['geometryStatus'] => {
    const normalized = String(value ?? 'IDLE');
    return normalized === 'GENERATING' || normalized === 'READY' || normalized === 'FAILED' ? normalized : 'IDLE';
  };
  return {
    state: artifact.state === 'FAILED' || artifact.state === 'REJECTED'
        ? 'FAILED'
        : artifact.state === 'GENERATING'
          ? 'GENERATING'
          : 'READY',
    approvalState: artifact.state === 'APPROVED' ? 'APPROVED' : 'PENDING_APPROVAL',
    geometryStatus: status(metadata.geometryStatus),
    textureStatus: status(metadata.textureStatus),
    modelUrl: artifact.modelUrl || artifact.contentUrl,
    filename: artifact.name,
  };
}

export function ChatPage() {
  const messages = useStore((s) => s.messages);
  const activities = useStore((s) => s.activities);
  const artifacts = useStore((s) => s.artifacts);
  const views = useStore((s) => s.views);
  const conceptVersion = useStore((s) => s.conceptVersion);
  const modelInfo = useStore((s) => s.modelInfo);
  const testCases = useStore((s) => s.testCases);
  const testFailures = useStore((s) => s.testFailures);
  const testState = useStore((s) => s.testState);
  const diagnostics = useStore((s) => s.diagnostics);

  const streamingMessageId = useStore((s) => s.streamingMessageId);
  const streamingContent = useStore((s) => s.streamingContent);
  const addMessage = useStore((s) => s.addMessage);
  const reconcileMessage = useStore((s) => s.reconcileMessage);
  const upsertJob = useStore((s) => s.upsertJob);
  const currentJobId = useStore((s) => s.currentJobId);
  const setCurrentJobId = useStore((s) => s.setCurrentJobId);
  const setConnections = useStore((s) => s.setConnections);
  const setAgents = useStore((s) => s.setAgents);
  const setActivePage = useStore((s) => s.setActivePage);

  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loggingProvider, setLoggingProvider] = useState<ProviderId | null>(null);
  const [showOptions, setShowOptions] = useState(false);
  const [panelView, setPanelView] = useState<'task' | 'providers' | 'defaults'>('task');
  const [showHistory, setShowHistory] = useState(false);
  const [options, setOptions] = useState<TaskOptions>(DEFAULT_TASK_OPTIONS);
  const [attachments, setAttachments] = useState<{ id: string; file: File; previewUrl?: string }[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent, activities, artifacts]);

  const handleSend = async () => {
    const content = input.trim();
    if ((!content && attachments.length === 0) || sending) return;
    const files = attachments.map((attachment) => attachment.file);
    const displayContent = content || files.map((file) => file.name).join(', ');
    const localId = `pending_${crypto.randomUUID?.() ?? `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`}`;
    setInput('');
    setSending(true);
    addMessage({ id: localId, role: 'user', content: displayContent, timestamp: Date.now(), jobId: currentJobId ?? undefined });
    setAttachments((prev) => { prev.forEach((attachment) => attachment.previewUrl && URL.revokeObjectURL(attachment.previewUrl)); return []; });
    try {
      const result = await getApi().sendMessage(content, currentJobId ?? undefined, files, options);
      reconcileMessage(localId, result.messageId, result.jobId);
      if (result.jobId) {
        setCurrentJobId(result.jobId);
        const job = await getApi().getJob(result.jobId);
        upsertJob(job);
      }
    } catch (error) {
      frontendDiagnostics.capture(error, 'chat', 'Failed to send message', { jobId: currentJobId ?? undefined });
      addMessage({
        id: `error_${crypto.randomUUID?.() ?? Date.now()}`,
        role: 'system',
        content: chatErrorMessage(error),
        timestamp: Date.now(),
        jobId: currentJobId ?? undefined,
        action: chatErrorAction(error),
      });
    } finally {
      setSending(false);
    }
  };

  const handleProviderLogin = async (provider: ProviderId) => {
    if (loggingProvider) return;
    setLoggingProvider(provider);
    setConnections({ [provider]: 'CONNECTING' });
    try {
      await getApi().loginProvider(provider);
      const [connections, agents] = await Promise.all([getApi().getConnections(), getApi().getAgents()]);
      setConnections(connections);
      setAgents(agents);
    } catch (error) {
      frontendDiagnostics.capture(error, 'chat', 'Failed to open provider login');
      addMessage({
        id: `login_error_${Date.now()}`,
        role: 'system',
        content: 'The login window could not be opened.',
        timestamp: Date.now(),
        jobId: currentJobId ?? undefined,
      });
    } finally {
      setLoggingProvider(null);
    }
  };

  const handleAttach = () => fileInputRef.current?.click();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const newAttachments = Array.from(files).slice(0, MAX_ATTACHMENTS).map((file) => ({
      id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      file,
      previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
    }));
    setAttachments((prev) => {
      const combined = [...prev, ...newAttachments];
      combined.slice(MAX_ATTACHMENTS).forEach((attachment) => attachment.previewUrl && URL.revokeObjectURL(attachment.previewUrl));
      return combined.slice(0, MAX_ATTACHMENTS);
    });
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const jobs = useStore((s) => s.jobs);
  const currentJob = useStore((s) => s.jobs.find((job) => job.id === s.currentJobId));
  const jobMessages = currentJobId
    ? messages.filter((message) => message.jobId === currentJobId)
    : messages.filter((message) => !message.jobId);
  const jobActivities = currentJobId ? activities.filter((a) => a.jobId === currentJobId) : [];
  const imageArtifacts = currentJobId ? artifacts.filter((a) => a.type === 'IMAGE' && a.jobId === currentJobId) : [];
  const modelArtifacts = currentJobId ? artifacts.filter((a) => a.type === 'MODEL_3D' && a.jobId === currentJobId) : [];
  const diffArtifacts = currentJobId ? artifacts.filter((a) => a.type === 'DIFF' && a.jobId === currentJobId) : [];
  const criticalErrors = currentJobId
    ? diagnostics.filter((d) => (d.severity === 'critical' || d.severity === 'error') && d.jobId === currentJobId)
    : [];

  type TimelineItem =
    | { type: 'MESSAGE'; id: string; timestamp: number; message: ChatMessage }
    | { type: 'ACTIVITY_GROUP'; id: string; timestamp: number; activities: ChatActivity[] }
    | { type: 'DIFF_ARTIFACT'; id: string; timestamp: number; artifact: (typeof artifacts)[0] }
    | { type: 'IMAGE_GALLERY'; id: string; timestamp: number; artifact: (typeof artifacts)[0]; views: ViewTile[] }
    | { type: 'MODEL_CARD'; id: string; timestamp: number; artifact: (typeof artifacts)[0] }
    | { type: 'TEST_CARD'; id: string; timestamp: number }
    | { type: 'ERROR_CARD'; id: string; timestamp: number; diag: (typeof diagnostics)[0] };

  const timelineItems: TimelineItem[] = [];

  jobMessages.forEach((msg) => {
    timelineItems.push({ type: 'MESSAGE', id: msg.id, timestamp: msg.timestamp, message: msg });
  });

  const groupedActivities = new Map<string, ChatActivity[]>();
  [...jobActivities]
    .sort((left, right) => (left.startedAt ?? left.timestamp) - (right.startedAt ?? right.timestamp))
    .forEach((activity) => {
      const key = `${activity.phase}:${activity.cycle ?? 1}:${activity.attempt ?? 1}`;
      const group = groupedActivities.get(key) ?? [];
      group.push(activity);
      groupedActivities.set(key, group);
    });
  groupedActivities.forEach((group, key) => {
    const timestamp = Math.min(...group.map((activity) => activity.startedAt ?? activity.timestamp));
    timelineItems.push({ type: 'ACTIVITY_GROUP', id: `activity:${key}`, timestamp, activities: group });
  });

  diffArtifacts.forEach((art) => {
    timelineItems.push({ type: 'DIFF_ARTIFACT', id: art.id, timestamp: art.createdAt, artifact: art });
  });

  imageArtifacts.forEach((artifact) => {
    const historicalViews = artifactViews(artifact);
    const galleryViews = historicalViews.length > 0
      ? historicalViews
      : artifact.id === imageArtifacts[imageArtifacts.length - 1]?.id
        ? views
        : [];
    timelineItems.push({
      type: 'IMAGE_GALLERY',
      id: artifact.id,
      timestamp: artifact.createdAt,
      artifact,
      views: galleryViews,
    });
  });

  modelArtifacts
    .filter((artifact) => Boolean(artifact.modelUrl || artifact.contentUrl))
    .forEach((artifact) => {
      timelineItems.push({ type: 'MODEL_CARD', id: artifact.id, timestamp: artifact.createdAt, artifact });
    });

  const testTimestamp = Math.max(
    0,
    ...testCases.map((testCase) => testCase.finishedAt || testCase.startedAt || 0),
    ...testFailures.map((failure) => failure.timestamp || 0),
  );
  if (testTimestamp > 0) {
    timelineItems.push({ type: 'TEST_CARD', id: 'test-card', timestamp: testTimestamp });
  }

  criticalErrors.forEach((diag) => {
    timelineItems.push({ type: 'ERROR_CARD', id: diag.id, timestamp: diag.timestamp, diag });
  });

  timelineItems.sort((left, right) => left.timestamp - right.timestamp || left.id.localeCompare(right.id));

  const handleApproveChanges = async (jobId: string) => {
    await getApi().approveChanges(jobId);
  };
  const handleRejectChanges = async (jobId: string) => {
    await getApi().rejectChanges(jobId);
  };
  const handleRequestRevision = async (jobId: string, feedback: string) => {
    await getApi().editChanges(jobId, 'feedback', feedback);
  };

  const handleApproveVisual = async (jobId: string) => {
    await getApi().approveVisual(jobId);
  };
  const handleRegenerateVisual = async (jobId: string) => {
    await getApi().regenerateVisual(jobId);
  };

  const handleApproveModel = async (jobId: string) => {
    await getApi().approveModel(jobId);
  };
  const handleRegenerateGeometry = async (jobId: string) => {
    await getApi().regenerateGeometry(jobId);
  };
  const handleRegenerateTexture = async (jobId: string) => {
    await getApi().regenerateTexture(jobId);
  };

  const setNavigationTarget = useStore((s) => s.setNavigationTarget);
  const latestDiffId = diffArtifacts[diffArtifacts.length - 1]?.id;
  const latestImageId = imageArtifacts[imageArtifacts.length - 1]?.id;
  const latestModelId = modelArtifacts[modelArtifacts.length - 1]?.id;

  const openBuildPage = (jobId: string, tab: string = 'changes') => {
    setCurrentJobId(jobId);
    setNavigationTarget({ page: 'build', tab });
    setActivePage('build');
  };
  const openVisualPage = (jobId: string, tab: string = 'views') => {
    setCurrentJobId(jobId);
    setNavigationTarget({ page: 'visual', tab });
    setActivePage('visual');
  };
  const openTestPage = (jobId: string) => {
    setCurrentJobId(jobId);
    setNavigationTarget({ page: 'test' });
    setActivePage('test');
  };
  const openLogsPage = () => {
    setNavigationTarget({ page: 'logs' });
    setActivePage('logs');
  };

  return (
    <div className="flex h-full animate-page-in">
      <div className="flex-1 flex flex-col min-w-0">
        <div className="relative flex h-10 shrink-0 items-center justify-between border-b border-ink-700 px-4">
          <div className="min-w-0">
            <span className="block truncate text-2xs uppercase tracking-[0.18em] text-ink-100">{currentJob?.title ?? 'New conversation'}</span>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={() => { setCurrentJobId(null); setShowHistory(false); }} className="zen-icon-button" aria-label="New conversation"><Plus size={13} /></button>
            <button onClick={() => setShowHistory((value) => !value)} className={`zen-icon-button ${showHistory ? 'border-ink-500 bg-ink-800 text-ink-0' : ''}`} aria-label="Conversation history"><History size={13} /></button>
          </div>
          {showHistory && (
            <>
              <button className="fixed inset-0 z-30 cursor-default" onClick={() => setShowHistory(false)} aria-label="Close history" />
              <div className="absolute right-4 top-9 z-40 w-80 border border-ink-600 bg-ink-900 p-1 shadow-panel animate-reveal">
                <div className="max-h-72 overflow-y-auto scrollbar-zen">
                  {jobs.length === 0 ? <div className="px-3 py-8 text-center text-2xs uppercase tracking-wider text-ink-400">No conversations</div> : jobs.map((job) => (
                    <button
                      key={job.id}
                      onClick={() => { setCurrentJobId(job.id); setShowHistory(false); }}
                      className={`zen-row block w-full border-b border-ink-700 px-3 py-2 text-left ${job.id === currentJobId ? 'bg-ink-800' : ''}`}
                    >
                      <span className="block truncate text-xs text-ink-50">{job.title}</span>
                      <span className="mt-0.5 block text-[9px] uppercase tracking-wider text-ink-400">{job.stage.replace(/_/g, ' ')}</span>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
        <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-zen">
          <div className="max-w-3xl mx-auto px-6 py-4 space-y-3">
            {jobMessages.length === 0 && !streamingMessageId && jobActivities.length === 0 && (
              <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider pt-20">
                Start a conversation
              </div>
            )}

            {timelineItems.map((item) => {
              if (item.type === 'MESSAGE') {
                return (
                  <ChatMessageRow
                    key={item.id}
                    message={item.message}
                    logging={loggingProvider === item.message.action?.provider}
                    onLogin={handleProviderLogin}
                    onOpenControls={() => { setPanelView('providers'); setShowOptions(true); }}
                  />
                );
              }
              if (item.type === 'ACTIVITY_GROUP') {
                return (
                  <ChatActivityGroup
                    key={item.id}
                    activities={item.activities}
                    onOpenContext={() => currentJobId && openBuildPage(currentJobId, 'context')}
                  />
                );
              }
              if (item.type === 'DIFF_ARTIFACT') {
                return (
                  <ChatChangeCard
                    key={item.id}
                    artifact={item.artifact}
                    actionable={item.artifact.id === latestDiffId && currentJob?.stage === 'WAITING_CHANGE_APPROVAL'}
                    onApprove={handleApproveChanges}
                    onReject={handleRejectChanges}
                    onRequestRevision={handleRequestRevision}
                    onOpenDiff={(j) => openBuildPage(j, 'changes')}
                  />
                );
              }
              if (item.type === 'IMAGE_GALLERY') {
                return (
                  <ChatImageGallery
                    key={item.id}
                    views={item.views}
                    conceptVersion={item.artifact.version ?? conceptVersion}
                    state={item.artifact.state}
                    actionable={item.artifact.id === latestImageId && currentJob?.stage === 'WAITING_IMAGE_APPROVAL'}
                    jobId={currentJobId ?? undefined}
                    onApproveVisual={handleApproveVisual}
                    onRegenerateVisual={handleRegenerateVisual}
                    onOpenVisualPage={(j) => openVisualPage(j, 'views')}
                  />
                );
              }
              if (item.type === 'MODEL_CARD') {
                const historicalModel = artifactModel(item.artifact);
                const visibleModel = item.artifact.id === latestModelId
                  ? { ...historicalModel, ...modelInfo, state: historicalModel.state, modelUrl: historicalModel.modelUrl }
                  : historicalModel;
                return (
                  <ChatModelCard
                    key={item.id}
                    artifact={item.artifact}
                    modelInfo={visibleModel}
                    actionable={item.artifact.id === latestModelId && currentJob?.stage === 'WAITING_3D_APPROVAL'}
                    onApproveModel={handleApproveModel}
                    onRegenerateGeometry={handleRegenerateGeometry}
                    onRegenerateTexture={handleRegenerateTexture}
                    onOpenModelViewer={(j) => openVisualPage(j, '3d')}
                  />
                );
              }
              if (item.type === 'TEST_CARD') {
                return (
                  <ChatTestCard
                    key={item.id}
                    jobId={currentJobId ?? undefined}
                    testCases={testCases}
                    failures={testFailures}
                    testState={testState}
                    onOpenTestPage={openTestPage}
                  />
                );
              }
              if (item.type === 'ERROR_CARD') {
                return (
                  <ChatErrorCard
                    key={item.id}
                    source={item.diag.source}
                    message={item.diag.message}
                    detail={item.diag.probableCause}
                    onOpenSettings={openLogsPage}
                  />
                );
              }
              return null;
            })}

            {streamingMessageId && (
              <ChatMessageRow
                message={{
                  id: streamingMessageId,
                  role: 'zenless',
                  content: streamingContent + '▊',
                  timestamp: currentJob?.updatedAt ?? 0,
                  jobId: currentJobId ?? undefined,
                }}
                streaming
                onLogin={handleProviderLogin}
                onOpenControls={() => { setPanelView('providers'); setShowOptions(true); }}
              />
            )}
          </div>
        </div>

        <div className="shrink-0 border-t border-ink-600 px-6 py-3">
          <div className="max-w-3xl mx-auto space-y-2">
            <div className="flex items-center justify-between font-mono text-2xs">
              <div className="flex flex-wrap items-center gap-2">
                <Tooltip content="Research mode for official docs">
                  <button
                    type="button"
                    onClick={() => {
                      const next = options.research === 'AUTO' ? 'ON' : options.research === 'ON' ? 'OFF' : 'AUTO';
                      setOptions({ ...options, research: next });
                    }}
                    className="px-2 py-0.5 bg-ink-900 text-ink-200 border border-ink-700 hover:text-ink-0 hover:bg-ink-800 transition-colors uppercase"
                  >
                    Research: <span className="font-bold text-ink-50">{options.research ?? 'AUTO'}</span>
                  </button>
                </Tooltip>

                <Tooltip content="AI Orchestration Effort Depth">
                  <button
                    type="button"
                    onClick={() => {
                      const nexts: Record<string, TaskOptions['effort']> = { AUTO: 'MIN', MIN: 'MED', MED: 'MAX', MAX: 'AUTO' };
                      setOptions({ ...options, effort: nexts[options.effort ?? 'AUTO'] });
                    }}
                    className="px-2 py-0.5 bg-ink-900 text-ink-200 border border-ink-700 hover:text-ink-0 hover:bg-ink-800 transition-colors uppercase"
                  >
                    Effort: <span className="font-bold text-ink-50">{options.effort ?? 'AUTO'}</span>
                  </button>
                </Tooltip>

                <Tooltip content="Context Scope (Project History vs Isolated Temp)">
                  <button
                    type="button"
                    onClick={() => {
                      setOptions({ ...options, chatMode: options.chatMode === 'TEMP' ? 'PROJECT' : 'TEMP' });
                    }}
                    className="px-2 py-0.5 bg-ink-900 text-ink-200 border border-ink-700 hover:text-ink-0 hover:bg-ink-800 transition-colors uppercase"
                  >
                    Mode: <span className="font-bold text-ink-50">{options.chatMode ?? 'PROJECT'}</span>
                  </button>
                </Tooltip>

                <Tooltip content="Approval policy for code & asset changes">
                  <button
                    type="button"
                    onClick={() => {
                      setOptions({ ...options, approval: !options.approval });
                    }}
                    className="px-2 py-0.5 bg-ink-900 text-ink-200 border border-ink-700 hover:text-ink-0 hover:bg-ink-800 transition-colors uppercase"
                  >
                    Approval: <span className="font-bold text-ink-50">{options.approval ? 'MANUAL' : 'AUTO'}</span>
                  </button>
                </Tooltip>
              </div>
            </div>

            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {attachments.map((att) => (
                  <span key={att.id} className="inline-flex items-center gap-1.5 px-2 h-6 text-2xs text-ink-100 bg-ink-800 border border-ink-600">
                    <Paperclip size={10} />
                    {att.previewUrl && <img src={att.previewUrl} alt="" className="w-4 h-4 object-cover border border-ink-600" />}
                    {att.file.name}
                    <button onClick={() => setAttachments((prev) => {
                      const target = prev.find((a) => a.id === att.id);
                      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
                      return prev.filter((a) => a.id !== att.id);
                    })} className="text-ink-300 hover:text-ink-0">
                      <X size={10} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-end gap-2">
              <Tooltip content="Attach">
                <button onClick={handleAttach} className="zen-icon-button w-8 h-8 border-ink-600" aria-label="Attach file">
                  <Paperclip size={14} strokeWidth={1.5} />
                </button>
              </Tooltip>
              <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileChange} />
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                placeholder="Message Zenless"
                rows={1}
                className="flex-1 bg-ink-800 border border-ink-600 text-sm text-ink-0 px-3 py-2 resize-none placeholder:text-ink-400 focus:border-ink-500 transition-colors scrollbar-zen"
                style={{ minHeight: '36px', maxHeight: '120px' }}
              />
              <Tooltip content="Options">
                <button onClick={() => { setPanelView('task'); setShowOptions(!showOptions); }} className={`zen-icon-button w-8 h-8 ${showOptions ? 'text-ink-0 bg-ink-700 border-ink-400' : 'border-ink-600'}`} aria-label="Task and provider controls">
                  <Settings2 size={14} strokeWidth={1.5} />
                </button>
              </Tooltip>
              <button onClick={handleSend} disabled={sending || (!input.trim() && attachments.length === 0)} className="w-8 h-8 flex items-center justify-center text-ink-950 bg-ink-0 border border-ink-0 disabled:opacity-30 hover:bg-ink-25 transition-all" aria-label="Send">
                <ArrowUp size={14} strokeWidth={1.5} />
              </button>
            </div>
          </div>
        </div>
      </div>
      {showOptions && (
        <Suspense fallback={null}>
          <TaskOptionsPanel options={options} initialView={panelView} onChange={setOptions} onClose={() => setShowOptions(false)} />
        </Suspense>
      )}
    </div>
  );
}

function ChatMessageRow({ message, streaming, logging, onLogin, onOpenControls }: { message: ChatMessage; streaming?: boolean; logging?: boolean; onLogin: (provider: ProviderId) => Promise<void>; onOpenControls: () => void }) {
  const isUser = message.role === 'user';
  const time = new Date(message.timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
  const parts = message.content.split(/(```[\s\S]*?```)/g);

  return (
    <div className={`py-2 ${streaming ? 'opacity-80' : ''}`}>
      <div className="flex items-baseline gap-2 mb-1">
        <span className={`text-2xs uppercase tracking-widest font-medium ${isUser ? 'text-ink-100' : 'text-ink-0'}`}>{isUser ? 'YOU' : 'ZENLESS'}</span>
        <span className="text-2xs text-ink-400 font-mono">{time}</span>
      </div>
      <div className={`text-sm leading-relaxed ${isUser ? 'text-ink-50' : 'text-ink-100'} pl-0`}>
        {parts.map((part, idx) => {
          if (part.startsWith('```')) {
            const code = part.replace(/```\w*\n?/, '').replace(/```$/, '');
            return (
              <pre key={idx} className="my-2 p-3 bg-ink-950 border border-ink-700 text-2xs font-mono text-ink-50 overflow-x-auto scrollbar-zen">
                <code>{code}</code>
              </pre>
            );
          }
          return <span key={idx}>{part}</span>;
        })}
      </div>
      {message.action?.type === 'LOGIN' && (
        <button disabled={logging} onClick={() => void onLogin(message.action!.provider)} className="mt-2 px-3 h-7 text-2xs uppercase tracking-wider text-ink-0 border border-ink-500 hover:bg-ink-800 disabled:opacity-50">
          {logging ? 'OPENING' : 'LOGIN'}
        </button>
      )}
      {requiresProviderControl(message.content) && (
        <button onClick={onOpenControls} className="zen-button mt-2">Open controls</button>
      )}
    </div>
  );
}

function requiresProviderControl(content: string) {
  return /^(QUOTA_EXHAUSTED|RATE_LIMITED|MODEL_UNAVAILABLE|TEMP_UNAVAILABLE|PROVIDER_MODE_UNAVAILABLE|ATTACHMENT_TEXT_)/.test(content)
    || /select a file-capable mode/i.test(content);
}

function chatErrorAction(error: unknown): ChatMessage['action'] {
  if (!(error instanceof ApiError) || error.code !== 'PROVIDER_LOGIN_REQUIRED' || !error.details || typeof error.details !== 'object') return undefined;
  const provider = (error.details as { provider?: unknown }).provider;
  return provider === 'chatgpt' || provider === 'deepseek' || provider === 'hunyuan' ? { type: 'LOGIN', provider } : undefined;
}

function chatErrorMessage(error: unknown): string {
  const action = chatErrorAction(error);
  if (action) {
    return `${PROVIDER_NAMES[action.provider]} requires login.`;
  }
  return error instanceof Error && error.message.trim() ? error.message : 'The message could not be sent.';
}
