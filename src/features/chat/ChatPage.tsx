import { useState, useRef, useEffect, lazy, Suspense } from 'react';
import { Paperclip, ArrowUp, Settings2, X } from 'lucide-react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { Tooltip } from '@/components/Tooltip';
import { DEFAULT_TASK_OPTIONS, type TaskOptions } from '@/types';
const TaskOptionsPanel = lazy(() => import('./TaskOptionsPanel').then((m) => ({ default: m.TaskOptionsPanel })));

export function ChatPage() {
  const messages = useStore((s) => s.messages);
  const streamingMessageId = useStore((s) => s.streamingMessageId);
  const streamingContent = useStore((s) => s.streamingContent);
  const addMessage = useStore((s) => s.addMessage);
  const currentJobId = useStore((s) => s.currentJobId);

  const [input, setInput] = useState('');
  const [showOptions, setShowOptions] = useState(false);
  const [options, setOptions] = useState<TaskOptions>(DEFAULT_TASK_OPTIONS);
  const [attachments, setAttachments] = useState<{ id: string; name: string }[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent]);

  const handleSend = async () => {
    if (!input.trim()) return;
    const content = input.trim();
    setInput('');
    const api = getApi();
    addMessage({ id: `msg_${Date.now()}`, role: 'user', content, timestamp: Date.now(), jobId: currentJobId ?? undefined });
    setAttachments([]);
    await api.sendMessage(content, currentJobId ?? undefined);
  };

  const handleAttach = () => fileInputRef.current?.click();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const newAttachments = Array.from(files).slice(0, 3).map((f) => ({ id: `att_${Date.now()}_${f.name}`, name: f.name }));
    setAttachments((prev) => [...prev, ...newAttachments].slice(0, 5));
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="flex h-full">
      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-zen">
          <div className="max-w-3xl mx-auto px-6 py-4 space-y-1">
            {messages.length === 0 && !streamingMessageId && (
              <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider pt-20">
                Start a conversation
              </div>
            )}
            {messages.map((msg) => (
              <ChatMessageRow key={msg.id} role={msg.role} content={msg.content} timestamp={msg.timestamp} />
            ))}
            {streamingMessageId && (
              <ChatMessageRow role="zenless" content={streamingContent + '▊'} timestamp={Date.now()} streaming />
            )}
          </div>
        </div>

        {/* Input area */}
        <div className="shrink-0 border-t border-ink-600 px-6 py-3">
          <div className="max-w-3xl mx-auto">
            {/* Attachments */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {attachments.map((att) => (
                  <span key={att.id} className="inline-flex items-center gap-1.5 px-2 h-6 text-2xs text-ink-100 bg-ink-800 border border-ink-600">
                    <Paperclip size={10} />
                    {att.name}
                    <button onClick={() => setAttachments((prev) => prev.filter((a) => a.id !== att.id))} className="text-ink-300 hover:text-ink-0">
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
              <button onClick={handleSend} disabled={!input.trim()} className="w-8 h-8 flex items-center justify-center text-ink-0 bg-ink-700 border border-ink-500 disabled:opacity-30 hover:bg-ink-600 transition-colors" aria-label="Send">
                <ArrowUp size={14} strokeWidth={1.5} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Options panel */}
      {showOptions && (
        <Suspense fallback={null}>
          <TaskOptionsPanel options={options} onChange={setOptions} onClose={() => setShowOptions(false)} />
        </Suspense>
      )}
    </div>
  );
}

function ChatMessageRow({ role, content, timestamp, streaming }: { role: 'user' | 'zenless' | 'system'; content: string; timestamp: number; streaming?: boolean }) {
  const isUser = role === 'user';
  const time = new Date(timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });

  const parts = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className={`py-2 ${isUser ? '' : ''} ${streaming ? 'opacity-80' : ''}`}>
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
    </div>
  );
}
