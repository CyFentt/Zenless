import { useState, useRef, useEffect, lazy, Suspense } from 'react';
import { Paperclip, ArrowUp, Settings2, X } from 'lucide-react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { ApiError } from '@/services/api/realApi';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Tooltip } from '@/components/Tooltip';
import { DEFAULT_TASK_OPTIONS, type ChatMessage, type ProviderId, type TaskOptions } from '@/types';
const TaskOptionsPanel = lazy(() => import('./TaskOptionsPanel').then((m) => ({ default: m.TaskOptionsPanel })));

export function ChatPage() {
  const messages = useStore((s) => s.messages);
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
  }, [messages, streamingContent]);

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

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col min-w-0">
        <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-zen">
          <div className="max-w-3xl mx-auto px-6 py-4 space-y-1">
            {messages.length === 0 && !streamingMessageId && (
              <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider pt-20">
                Start a conversation
              </div>
            )}
            {messages.map((msg) => (
              <ChatMessageRow key={msg.id} message={msg} logging={loggingProvider === msg.action?.provider} onLogin={handleProviderLogin} />
            ))}
            {streamingMessageId && (
              <ChatMessageRow message={{ id: streamingMessageId, role: 'zenless', content: streamingContent + '▊', timestamp: Date.now() }} streaming onLogin={handleProviderLogin} />
            )}
          </div>
        </div>
        <div className="shrink-0 border-t border-ink-600 px-6 py-3">
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
