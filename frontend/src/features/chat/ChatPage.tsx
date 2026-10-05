import { useState, useRef, useEffect, lazy, Suspense } from 'react';
import { Paperclip, ArrowUp, Settings2, X, Square, ScanSearch, Wrench, Code2 } from 'lucide-react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { ApiError } from '@/services/api/realApi';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Tooltip } from '@/components/Tooltip';
import { DEFAULT_TASK_OPTIONS, type ChatMessage, type ProviderId, type TaskOptions } from '@/types';
const TaskOptionsPanel = lazy(() => import('./TaskOptionsPanel').then((m) => ({ default: m.TaskOptionsPanel })));

export function ChatPage() {
  const projectName = useStore((s) => s.studioProjectName);
  const job = useStore((s) => s.jobs.find((item) => item.id === s.currentJobId));
  const working = job?.status === 'RUNNING' || job?.status === 'NEW';
  const activities = useStore((s) => s.activities);
  const messages = useStore((s) => s.messages);
  const streamingMessageId = useStore((s) => s.streamingMessageId);
  const streamingContent = useStore((s) => s.streamingContent);
  const addMessage = useStore((s) => s.addMessage);
  const setMessages = useStore((s) => s.setMessages);
  const reconcileMessage = useStore((s) => s.reconcileMessage);
  const upsertJob = useStore((s) => s.upsertJob);
  const currentJobId = useStore((s) => s.currentJobId);
  const setCurrentJobId = useStore((s) => s.setCurrentJobId);
  const connections = useStore((s) => s.connections);
  const setConnections = useStore((s) => s.setConnections);
  const setAgents = useStore((s) => s.setAgents);

  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loggingProvider, setLoggingProvider] = useState<ProviderId | null>(null);
  const [showOptions, setShowOptions] = useState(false);
  const settings = useStore((s) => s.settings);
  const [optionOverrides, setOptionOverrides] = useState<Partial<TaskOptions>>({});
  const options: TaskOptions = { ...DEFAULT_TASK_OPTIONS,
    ...(settings ? { approvalMode: settings.approvalMode, approval: settings.approvalMode !== 'FULL_AUTO', revisions: settings.maxRevisions, smartRouting: settings.models.smartRouting } : {}),
    ...optionOverrides };
  const setOptions = (next: TaskOptions) => setOptionOverrides((previous) => {
    const changed = Object.fromEntries(Object.entries(next).filter(([key, value]) => value !== options[key as keyof TaskOptions]));
    return { ...previous, ...changed };
  });
  const [attachments, setAttachments] = useState<{ id: string; file: File; previewUrl?: string }[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (composerRef.current) {
      composerRef.current.style.height = 'auto';
      composerRef.current.style.height = `${Math.min(180, Math.max(48, composerRef.current.scrollHeight))}px`;
    }
  }, [input]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent]);

  useEffect(() => {
    if (!loggingProvider) return;
    const state = connections[loggingProvider];
    if (state === 'READY' || state === 'ERR' || state === 'OFF') setLoggingProvider(null);
  }, [connections, loggingProvider]);

  const handleSend = async () => {
    const content = input.trim();
    if ((!content && attachments.length === 0) || sending || working) return;
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
        if (useStore.getState().currentJobId === result.jobId) setMessages(snapshot);
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
      const [nextConnections, agents] = await Promise.all([getApi().getConnections(), getApi().getAgents()]);
      setConnections(nextConnections);
      setAgents(agents);
      if (nextConnections[provider] === 'READY' || nextConnections[provider] === 'ERR' || nextConnections[provider] === 'OFF') {
        setLoggingProvider(null);
      }
    } catch (error) {
      setLoggingProvider(null);
      frontendDiagnostics.capture(error, 'chat', 'Failed to open provider login');
      addMessage({ id: `login_error_${Date.now()}`, role: 'system', content: 'The login window could not be opened.', timestamp: Date.now() });
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

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col min-w-0">
        <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-zen">
          <div className="max-w-3xl mx-auto px-6 py-8 space-y-6 min-h-full flex flex-col">
            {messages.length === 0 && !streamingMessageId && (
              <div className="my-auto py-10 space-y-7 text-center">
                <div className="space-y-3">
                  <h1 className="text-2xl font-medium text-ink-0 tracking-tight">What should we work on?</h1>
                  <p className="text-sm text-ink-300">{projectName ? `Working with ${projectName}` : 'Open your game in Studio. Rubra connects automatically.'}</p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {[{ icon: ScanSearch, label: 'Review this game', prompt: 'Review this existing game, inspect its scripts and structure, and report concrete issues.' }, { icon: Wrench, label: 'Find and fix errors', prompt: 'Inspect this game, reproduce its errors, fix the causes, and test the changes.' }, { icon: Code2, label: 'Build a feature', prompt: 'Help me add a feature to this existing game: ' }].map(({ icon: Icon, label, prompt }) => (
                    <button key={label} onClick={() => { setInput(prompt); composerRef.current?.focus(); }} className="inline-flex items-center gap-2 px-3 py-2.5 rounded-lg border border-ink-700 hover:border-zen-red text-xs text-ink-100 hover:text-ink-0 transition-colors"><Icon size={14} />{label}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((msg) => (
              <ChatMessageRow key={msg.id} message={msg} logging={loggingProvider === msg.action?.provider} onLogin={handleProviderLogin} />
            ))}
            {activities.filter((activity) => activity.jobId === currentJobId).slice(-6).length > 0 && (
              <div className="mt-5 border-l border-zen-red pl-4 space-y-2" aria-live="polite">
                {activities.filter((activity) => activity.jobId === currentJobId).slice(-6).map((activity) => (
                  <div key={activity.id} className="text-xs animate-fade-in">
                    <span className="text-zen-redBright mr-2">{activity.phase}</span>
                    <span className="text-ink-50">{activity.title}</span>
                    {activity.detail && <p className="text-ink-300 mt-1">{activity.detail}</p>}
                  </div>
                ))}
              </div>
            )}
            {streamingMessageId && (
              <ChatMessageRow message={{ id: streamingMessageId, role: 'zenless', content: streamingContent + '▊', timestamp: Date.now() }} streaming onLogin={handleProviderLogin} />
            )}
          </div>
        </div>
        <div className="shrink-0 px-6 pb-5 pt-3">
          <div className="max-w-3xl mx-auto">
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
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
            <div className="rubra-composer flex items-center gap-2 rounded-xl border border-ink-600 bg-ink-900 p-2 focus-within:border-zen-red transition-colors">
              <Tooltip content="Attach">
                <button onClick={handleAttach} className="w-8 h-8 shrink-0 flex items-center justify-center text-ink-300 hover:text-ink-0 border border-ink-600 hover:border-ink-500 transition-colors" aria-label="Attach file">
                  <Paperclip size={14} strokeWidth={1.5} />
                </button>
              </Tooltip>
              <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileChange} />
              <textarea
                ref={composerRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); handleSend(); } }}
                placeholder="Message Rubra"
                rows={1}
                className="flex-1 min-w-0 bg-transparent text-sm text-ink-0 px-2 py-3 resize-none placeholder:text-ink-300 outline-none scrollbar-zen"
                style={{ minHeight: '48px', maxHeight: '180px' }}
              />
              <Tooltip content="Options">
                <button onClick={() => setShowOptions(!showOptions)} className={`w-8 h-8 shrink-0 flex items-center justify-center border transition-colors ${showOptions ? 'text-ink-0 bg-ink-700 border-ink-500' : 'text-ink-300 border-ink-600 hover:border-ink-500 hover:text-ink-0'}`} aria-label="Task options">
                  <Settings2 size={14} strokeWidth={1.5} />
                </button>
              </Tooltip>
              {working && currentJobId && <Tooltip content="Stop the active task"><button aria-label="Stop task" onClick={() => void getApi().cancelGeneration(currentJobId).catch((error) => frontendDiagnostics.capture(error, 'chat', 'Failed to stop task'))} className="w-8 h-8 rounded-lg flex items-center justify-center text-zen-redBright border border-zen-red"><Square size={13} /></button></Tooltip>}
              <button onClick={handleSend} disabled={sending || working || (!input.trim() && attachments.length === 0)} className="w-8 h-8 shrink-0 flex items-center justify-center text-white bg-zen-red rounded-lg disabled:opacity-30 hover:bg-zen-redBright transition-colors" aria-label="Send">
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
    <div className={`${isUser ? 'self-end max-w-[88%] rounded-xl bg-ink-850 border border-ink-700 px-4 py-3' : 'w-full py-2'} ${streaming ? 'opacity-80' : ''}`}>
      <div className="flex items-baseline gap-2 mb-1">
        <span className={`text-2xs uppercase tracking-widest font-medium ${isUser ? 'text-ink-100' : 'text-ink-0'}`}>{isUser ? 'You' : message.role === 'system' ? 'Notice' : 'Rubra'}</span>
        <span className="text-2xs text-ink-400 font-mono">{time}</span>
      </div>
      <div className={`text-sm leading-7 whitespace-pre-wrap break-words ${isUser ? 'text-ink-50' : 'text-ink-100'} pl-0`}>
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
  return provider === 'chatgpt' || provider === 'deepseek' || provider === 'gemini' || provider === 'hunyuan' ? { type: 'LOGIN', provider } : undefined;
}

function chatErrorMessage(error: unknown): string {
  const action = chatErrorAction(error);
  if (action) {
    const labels: Record<ProviderId, string> = { chatgpt: 'Builder', deepseek: 'Reviewer', gemini: 'Research', hunyuan: '3D Generator' };
    return `${labels[action.provider]} requires login.`;
  }
  return error instanceof Error && error.message.trim() ? error.message : 'The message could not be sent.';
}
