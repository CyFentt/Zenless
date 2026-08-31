import { useState, useRef, useEffect, lazy, Suspense } from 'react';
import { Paperclip, ArrowUp, Settings2, X } from 'lucide-react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { ApiError } from '@/services/api/realApi';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Tooltip } from '@/components/Tooltip';
import { DEFAULT_TASK_OPTIONS, type ChatMessage, type ProviderId, type TaskOptions, type ChatArtifact } from '@/types';

import { ChatActivityGroup } from './ChatActivityGroup';
import { ChatChangeCard } from './ChatChangeCard';
import { ChatImageGallery } from './ChatImageGallery';
import { ChatModelCard } from './ChatModelCard';
import { ChatTestCard } from './ChatTestCard';
import { ChatErrorCard } from './ChatErrorCard';

const TaskOptionsPanel = lazy(() => import('./TaskOptionsPanel').then((m) => ({ default: m.TaskOptionsPanel })));

export function ChatPage() {
  const messages = useStore((s) => s.messages);
  const activities = useStore((s) => s.activities);
  const artifacts = useStore((s) => s.artifacts);
  const views = useStore((s) => s.views);
  const conceptVersion = useStore((s) => s.conceptVersion);
  const modelInfo = useStore((s) => s.modelInfo);
  const testCases = useStore((s) => s.testCases);
  const testFailures = useStore((s) => s.testFailures);
  const diagnostics = useStore((s) => s.diagnostics);

  const streamingMessageId = useStore((s) => s.streamingMessageId);
  const streamingContent = useStore((s) => s.streamingContent);
  const addMessage = useStore((s) => s.addMessage);
  const setMessages = useStore((s) => s.setMessages);
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
        const [job, snapshot] = await Promise.all([getApi().getJob(result.jobId), getApi().getMessages(result.jobId)]);
        upsertJob(job);
        setMessages(snapshot);
      }
    } catch (error) {
      frontendDiagnostics.capture(error, 'chat', 'Failed to send message', { jobId: currentJobId ?? undefined });
      addMessage({
        id: `error_${crypto.randomUUID?.() ?? Date.now()}`,
        role: 'system',
        content: chatErrorMessage(error),
        timestamp: Date.now(),
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
      addMessage({ id: `login_error_${Date.now()}`, role: 'system', content: 'The login window could not be opened.', timestamp: Date.now() });
    } finally {
      setLoggingProvider(null);
    }
  };

  const handleAttach = () => fileInputRef.current?.click();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const newAttachments = Array.from(files).slice(0, 3).map((file) => ({
      id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      file,
      previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
    }));
    setAttachments((prev) => {
      const combined = [...prev, ...newAttachments];
      combined.slice(5).forEach((attachment) => attachment.previewUrl && URL.revokeObjectURL(attachment.previewUrl));
      return combined.slice(0, 5);
    });
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // Filter activities, artifacts, and diagnostics strictly relevant to active job
  const jobActivities = currentJobId ? activities.filter((a) => a.jobId === currentJobId) : [];
  const imageArtifacts = currentJobId ? artifacts.filter((a) => a.type === 'IMAGE' && a.jobId === currentJobId) : [];
  const modelArtifacts = currentJobId ? artifacts.filter((a) => a.type === 'MODEL_3D' && a.jobId === currentJobId) : [];
  const diffArtifacts = currentJobId ? artifacts.filter((a) => a.type === 'DIFF' && a.jobId === currentJobId) : [];
  const criticalErrors = currentJobId
    ? diagnostics.filter((d) => (d.severity === 'critical' || d.severity === 'error') && d.jobId === currentJobId)
    : [];

  // Chronological timeline item composition
  type TimelineItem =
    | { type: 'MESSAGE'; id: string; timestamp: number; message: ChatMessage }
    | { type: 'ACTIVITY_GROUP'; id: string; timestamp: number }
    | { type: 'DIFF_ARTIFACT'; id: string; timestamp: number; artifact: (typeof artifacts)[0] }
    | { type: 'IMAGE_GALLERY'; id: string; timestamp: number }
    | { type: 'MODEL_CARD'; id: string; timestamp: number; artifact?: (typeof artifacts)[0] }
    | { type: 'TEST_CARD'; id: string; timestamp: number }
    | { type: 'ERROR_CARD'; id: string; timestamp: number; diag: (typeof diagnostics)[0] };

  const timelineItems: TimelineItem[] = [];

  messages.forEach((msg) => {
    timelineItems.push({ type: 'MESSAGE', id: msg.id, timestamp: msg.timestamp, message: msg });
  });

  if (jobActivities.length > 0) {
    const latestActivityTs = Math.max(...jobActivities.map((a) => a.timestamp || 0));
    timelineItems.push({ type: 'ACTIVITY_GROUP', id: 'activity_group', timestamp: latestActivityTs });
  }

  diffArtifacts.forEach((art) => {
    timelineItems.push({ type: 'DIFF_ARTIFACT', id: art.id, timestamp: art.createdAt, artifact: art });
  });

  if (views.length > 0 || imageArtifacts.length > 0) {
    const latestImageTs = Math.max(
      ...imageArtifacts.map((a) => a.createdAt),
      0
    );
    timelineItems.push({ type: 'IMAGE_GALLERY', id: 'image_gallery', timestamp: latestImageTs || Date.now() });
  }

  if (modelInfo.modelUrl || modelArtifacts.length > 0) {
    const latestModelTs = modelArtifacts[0]?.createdAt || Date.now();
    const modelStateMap: Record<string, ChatArtifact['state']> = {
      EMPTY: 'GENERATING',
      GENERATING_GEOMETRY: 'GENERATING',
      GEOMETRY_READY: 'READY',
      GENERATING_TEXTURE: 'GENERATING',
      TEXTURE_READY: 'READY',
      READY: 'READY',
      FAILED: 'FAILED',
    };
    const defaultModelArtifact: ChatArtifact = {
      id: 'model_art',
      type: 'MODEL_3D',
      name: modelInfo.filename || '3D Model',
      state: modelStateMap[modelInfo.state] || 'READY',
      jobId: currentJobId ?? undefined,
      createdAt: latestModelTs,
    };
    timelineItems.push({ type: 'MODEL_CARD', id: modelArtifacts[0]?.id || 'model_card', timestamp: latestModelTs, artifact: modelArtifacts[0] || defaultModelArtifact });
  }

  if (testCases.length > 0 || testFailures.length > 0) {
    timelineItems.push({ type: 'TEST_CARD', id: 'test_card', timestamp: Date.now() });
  }

  criticalErrors.forEach((diag) => {
    timelineItems.push({ type: 'ERROR_CARD', id: diag.id, timestamp: diag.timestamp, diag });
  });

  // Sort timeline chronologically
  timelineItems.sort((a, b) => a.timestamp - b.timestamp);

  // Domain Action Handlers
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

  // Deep Link Handlers with Navigation Targets
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
  const openSettingsPage = (tab: string = 'logs') => {
    setNavigationTarget({ page: 'settings', tab });
    setActivePage('settings');
  };

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col min-w-0">
        <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-zen">
          <div className="max-w-3xl mx-auto px-6 py-4 space-y-3">
            {messages.length === 0 && !streamingMessageId && jobActivities.length === 0 && (
              <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider pt-20">
                Start a conversation
              </div>
            )}

            {/* Unified Chronological Timeline */}
            {timelineItems.map((item) => {
              if (item.type === 'MESSAGE') {
                return (
                  <ChatMessageRow
                    key={item.id}
                    message={item.message}
                    logging={loggingProvider === item.message.action?.provider}
                    onLogin={handleProviderLogin}
                  />
                );
              }
              if (item.type === 'ACTIVITY_GROUP') {
                return (
                  <ChatActivityGroup
                    key={item.id}
                    activities={jobActivities}
                onOpenContext={() => currentJobId && openBuildPage(currentJobId, 'context')}
                  />
                );
              }
              if (item.type === 'DIFF_ARTIFACT') {
                return (
                  <ChatChangeCard
                    key={item.id}
                    artifact={item.artifact}
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
                    views={views}
                    conceptVersion={conceptVersion}
                    jobId={currentJobId ?? undefined}
                    onApproveVisual={handleApproveVisual}
                    onRegenerateVisual={handleRegenerateVisual}
                    onOpenVisualPage={(j) => openVisualPage(j, 'views')}
                  />
                );
              }
              if (item.type === 'MODEL_CARD') {
                const modelStateMap: Record<string, ChatArtifact['state']> = {
                  EMPTY: 'GENERATING',
                  GENERATING_GEOMETRY: 'GENERATING',
                  GEOMETRY_READY: 'READY',
                  GENERATING_TEXTURE: 'GENERATING',
                  TEXTURE_READY: 'READY',
                  READY: 'READY',
                  FAILED: 'FAILED',
                };
                const fallbackModelArt: ChatArtifact = {
                  id: 'model_art',
                  type: 'MODEL_3D',
                  name: modelInfo.filename || '3D Model',
                  state: modelStateMap[modelInfo.state] || 'READY',
                  jobId: currentJobId ?? undefined,
                  createdAt: Date.now(),
                };
                return (
                  <ChatModelCard
                    key={item.id}
                    artifact={item.artifact || fallbackModelArt}
                    modelInfo={modelInfo}
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
                    onOpenSettings={() => openSettingsPage('logs')}
                  />
                );
              }
              return null;
            })}

            {streamingMessageId && (
              <ChatMessageRow
                message={{ id: streamingMessageId, role: 'zenless', content: streamingContent + '▊', timestamp: Date.now() }}
                streaming
                onLogin={handleProviderLogin}
              />
            )}
          </div>
        </div>

        {/* Composer Controls & Input */}
        <div className="shrink-0 border-t border-ink-600 px-6 py-3">
          <div className="max-w-3xl mx-auto space-y-2">
            {/* Control Center Toolbar */}
            <div className="flex items-center justify-between font-mono text-2xs">
              <div className="flex flex-wrap items-center gap-2">
                <Tooltip content="Research mode for official docs">
                  <button
                    type="button"
                    onClick={() => {
                      const next = options.research === 'AUTO' ? 'ON' : options.research === 'ON' ? 'OFF' : 'AUTO';
                      setOptions({ ...options, research: next });
                    }}
                    className="px-2 py-0.5 bg-ink-900 text-ink-200 border border-ink-700 rounded hover:text-ink-0 hover:bg-ink-800 transition-colors uppercase"
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
                    className="px-2 py-0.5 bg-ink-900 text-ink-200 border border-ink-700 rounded hover:text-ink-0 hover:bg-ink-800 transition-colors uppercase"
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
                    className="px-2 py-0.5 bg-ink-900 text-ink-200 border border-ink-700 rounded hover:text-ink-0 hover:bg-ink-800 transition-colors uppercase"
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
                    className="px-2 py-0.5 bg-ink-900 text-ink-200 border border-ink-700 rounded hover:text-ink-0 hover:bg-ink-800 transition-colors uppercase"
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
                <button onClick={handleAttach} className="w-8 h-8 flex items-center justify-center text-ink-300 hover:text-ink-0 border border-ink-600 hover:border-ink-500 transition-colors" aria-label="Attach file">
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
                <button onClick={() => setShowOptions(!showOptions)} className={`w-8 h-8 flex items-center justify-center border transition-colors ${showOptions ? 'text-ink-0 bg-ink-700 border-ink-500' : 'text-ink-300 border-ink-600 hover:border-ink-500 hover:text-ink-0'}`} aria-label="Task options">
                  <Settings2 size={14} strokeWidth={1.5} />
                </button>
              </Tooltip>
              <button onClick={handleSend} disabled={sending || (!input.trim() && attachments.length === 0)} className="w-8 h-8 flex items-center justify-center text-ink-0 bg-ink-700 border border-ink-500 disabled:opacity-30 hover:bg-ink-600 transition-colors" aria-label="Send">
                <ArrowUp size={14} strokeWidth={1.5} />
              </button>
            </div>
          </div>
        </div>
      </div>
      {showOptions && (
        <Suspense fallback={null}>
          <TaskOptionsPanel options={options} onChange={setOptions} onClose={() => setShowOptions(false)} />
        </Suspense>
      )}
    </div>
  );
}

function ChatMessageRow({ message, streaming, logging, onLogin }: { message: ChatMessage; streaming?: boolean; logging?: boolean; onLogin: (provider: ProviderId) => Promise<void> }) {
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
    </div>
  );
}

function chatErrorAction(error: unknown): ChatMessage['action'] {
  if (!(error instanceof ApiError) || error.code !== 'PROVIDER_LOGIN_REQUIRED' || !error.details || typeof error.details !== 'object') return undefined;
  const provider = (error.details as { provider?: unknown }).provider;
  return provider === 'chatgpt' || provider === 'deepseek' || provider === 'hunyuan' ? { type: 'LOGIN', provider } : undefined;
}

function chatErrorMessage(error: unknown): string {
  const action = chatErrorAction(error);
  if (action) {
    const labels: Record<ProviderId, string> = { chatgpt: 'Builder', deepseek: 'Reviewer', hunyuan: '3D Generator' };
    return `${labels[action.provider]} requires login.`;
  }
  return error instanceof Error && error.message.trim() ? error.message : 'The message could not be sent.';
}
