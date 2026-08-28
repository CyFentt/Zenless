import { useEffect, useState, lazy, Suspense } from 'react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { Tabs } from '@/components/Tabs';
import { Tooltip } from '@/components/Tooltip';
import { Plus, Minus, Lock, Unlock, Eye, Check, X, Clock } from 'lucide-react';
import type { ContextItem } from '@/types';

const DiffViewer = lazy(() => import('@/features/build/DiffViewer').then((m) => ({ default: m.DiffViewer })));

type BuildTab = 'context' | 'changes' | 'history';

export function BuildPage() {
  const [tab, setTab] = useState<BuildTab>('context');

  return (
    <div className="flex flex-col h-full">
      <Tabs
        tabs={[
          { id: 'context', label: 'CONTEXT' },
          { id: 'changes', label: 'CHANGES' },
          { id: 'history', label: 'HISTORY' },
        ]}
        active={tab}
        onChange={(t) => setTab(t as BuildTab)}
      />
      <div className="flex-1 overflow-hidden">
        {tab === 'context' && <ContextTab />}
        {tab === 'changes' && <ChangesTab />}
        {tab === 'history' && <HistoryTab />}
      </div>
    </div>
  );
}

// ── Context Tab ───────────────────────────────────────────
function ContextTab() {
  const contextItems = useStore((s) => s.contextItems);
  const setContextItems = useStore((s) => s.setContextItems);
  const currentJobId = useStore((s) => s.currentJobId);

  useEffect(() => {
    if (!currentJobId) {
      getApi().getContext('job_004').then(setContextItems).catch(() => {});
    } else {
      getApi().getContext(currentJobId).then(setContextItems).catch(() => {});
    }
  }, [currentJobId, setContextItems]);

  const handleAction = async (item: ContextItem, action: 'include' | 'exclude' | 'lock' | 'unlock' | 'inspect') => {
    const api = getApi();
    if (action === 'include') { await api.includeContext(item.id); setContextItems(contextItems.map((c) => c.id === item.id ? { ...c, state: 'included' } : c)); }
    if (action === 'exclude') { await api.excludeContext(item.id); setContextItems(contextItems.map((c) => c.id === item.id ? { ...c, state: 'excluded' } : c)); }
    if (action === 'lock') { await api.lockContext(item.id); setContextItems(contextItems.map((c) => c.id === item.id ? { ...c, state: 'locked' } : c)); }
    if (action === 'unlock') { await api.unlockContext(item.id); setContextItems(contextItems.map((c) => c.id === item.id ? { ...c, state: 'included' } : c)); }
  };

  return (
    <div className="h-full overflow-y-auto scrollbar-zen">
      <table className="w-full">
        <thead>
          <tr className="border-b border-ink-600 sticky top-0 bg-ink-950">
            <th className="text-left text-2xs uppercase tracking-wider text-ink-300 font-medium px-3 py-2">Name</th>
            <th className="text-left text-2xs uppercase tracking-wider text-ink-300 font-medium px-2 py-2 w-24">Type</th>
            <th className="text-left text-2xs uppercase tracking-wider text-ink-300 font-medium px-2 py-2 w-48">Path</th>
            <th className="text-right text-2xs uppercase tracking-wider text-ink-300 font-medium px-2 py-2 w-20">Rel</th>
            <th className="text-right text-2xs uppercase tracking-wider text-ink-300 font-medium px-3 py-2 w-24">Actions</th>
          </tr>
        </thead>
        <tbody>
          {contextItems.map((item) => (
            <tr key={item.id} className="border-b border-ink-700 hover:bg-ink-850 transition-colors">
              <td className="px-3 py-2 text-xs text-ink-50 font-medium">{item.name}</td>
              <td className="px-2 py-2 text-2xs text-ink-300 font-mono">{item.type}</td>
              <td className="px-2 py-2 text-2xs text-ink-400 font-mono truncate max-w-48">{item.path}</td>
              <td className="px-2 py-2 text-right">
                <span className={`text-2xs font-mono ${item.relevance > 0.7 ? 'text-ink-50' : item.relevance > 0.4 ? 'text-ink-150' : 'text-ink-400'}`}>
                  {(item.relevance * 100).toFixed(0)}
                </span>
              </td>
              <td className="px-3 py-2">
                <div className="flex items-center justify-end gap-1">
                  {item.state === 'locked' ? (
                    <Tooltip content="Unlock"><button onClick={() => handleAction(item, 'unlock')} className="w-6 h-6 flex items-center justify-center text-ink-300 hover:text-ink-0"><Unlock size={12} /></button></Tooltip>
                  ) : item.state === 'included' ? (
                    <>
                      <Tooltip content="Exclude"><button onClick={() => handleAction(item, 'exclude')} className="w-6 h-6 flex items-center justify-center text-ink-300 hover:text-ink-0"><Minus size={12} /></button></Tooltip>
                      <Tooltip content="Lock"><button onClick={() => handleAction(item, 'lock')} className="w-6 h-6 flex items-center justify-center text-ink-300 hover:text-ink-0"><Lock size={12} /></button></Tooltip>
                    </>
                  ) : (
                    <Tooltip content="Include"><button onClick={() => handleAction(item, 'include')} className="w-6 h-6 flex items-center justify-center text-ink-300 hover:text-ink-0"><Plus size={12} /></button></Tooltip>
                  )}
                  <Tooltip content="Inspect"><button onClick={() => handleAction(item, 'inspect')} className="w-6 h-6 flex items-center justify-center text-ink-300 hover:text-ink-0"><Eye size={12} /></button></Tooltip>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Changes Tab ───────────────────────────────────────────
function ChangesTab() {
  const changedFiles = useStore((s) => s.changedFiles);
  const setChangedFiles = useStore((s) => s.setChangedFiles);
  const selectedFileId = useStore((s) => s.selectedFileId);
  const setSelectedFileId = useStore((s) => s.setSelectedFileId);
  const currentJobId = useStore((s) => s.currentJobId);

  useEffect(() => {
    const jobId = currentJobId ?? 'job_004';
    getApi().getChanges(jobId).then(setChangedFiles).catch(() => {});
  }, [currentJobId, setChangedFiles]);

  const selectedFile = changedFiles.find((f) => f.id === selectedFileId);
  const jobId = currentJobId ?? 'job_004';

  const handleApprove = async () => { await getApi().approveChanges(jobId); };
  const handleReject = async () => { await getApi().rejectChanges(jobId); };

  return (
    <div className="flex h-full">
      {/* File list */}
      <div className="w-56 shrink-0 border-r border-ink-600 overflow-y-auto scrollbar-zen">
        <div className="flex items-center justify-between px-3 h-8 border-b border-ink-600">
          <span className="text-2xs uppercase tracking-wider text-ink-300">REVIEW</span>
          <span className="text-2xs text-ink-400">DeepSeek</span>
        </div>
        {changedFiles.map((file) => (
          <button
            key={file.id}
            onClick={() => setSelectedFileId(file.id)}
            className={`flex items-center w-full px-3 h-8 border-b border-ink-700 transition-colors text-left ${selectedFileId === file.id ? 'bg-ink-700' : 'hover:bg-ink-850'}`}
          >
            <span className={`text-2xs font-mono w-4 ${file.status === 'A' ? 'text-zen-okBright' : file.status === 'D' ? 'text-zen-errBright' : 'text-zen-warnBright'}`}>
              {file.status}
            </span>
            <span className="text-xs text-ink-50 flex-1 truncate ml-1">{file.name}</span>
            <span className="text-2xs text-zen-okBright font-mono">+{file.additions}</span>
            <span className="text-2xs text-zen-errBright font-mono ml-1">-{file.deletions}</span>
          </button>
        ))}
        <div className="flex gap-1 p-2 mt-1">
          <button onClick={handleApprove} className="flex-1 h-7 text-2xs uppercase tracking-wider text-zen-okBright border border-ink-600 hover:bg-ink-800 transition-colors">APPROVE</button>
          <button onClick={handleReject} className="flex-1 h-7 text-2xs uppercase tracking-wider text-zen-errBright border border-ink-600 hover:bg-ink-800 transition-colors">REJECT</button>
        </div>
      </div>

      {/* Diff viewer */}
      <div className="flex-1 overflow-hidden">
        {selectedFile ? (
          <Suspense fallback={<div className="flex items-center justify-center h-full text-xs text-ink-300 animate-pulse">Loading diff…</div>}>
            <DiffViewer file={selectedFile} />
          </Suspense>
        ) : (
          <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider">Select a file</div>
        )}
      </div>
    </div>
  );
}

// ── History Tab ───────────────────────────────────────────
function HistoryTab() {
  const jobs = useStore((s) => s.jobs);
  const setCurrentJobId = useStore((s) => s.setCurrentJobId);

  const formatTime = (ts: number) => new Date(ts).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });

  return (
    <div className="h-full overflow-y-auto scrollbar-zen">
      {jobs.map((job) => (
        <button
          key={job.id}
          onClick={() => setCurrentJobId(job.id)}
          className="flex items-center w-full px-3 h-9 border-b border-ink-700 hover:bg-ink-850 transition-colors group"
        >
          <span className="text-2xs text-ink-400 font-mono w-12">{formatTime(job.updatedAt)}</span>
          <span className="text-xs text-ink-100 group-hover:text-ink-0 flex-1 text-left">{job.title}</span>
          {job.status === 'COMPLETE' ? <Check size={12} className="text-zen-okBright" /> : job.status === 'FAILED' ? <X size={12} className="text-zen-errBright" /> : <Clock size={12} className="text-ink-300" />}
        </button>
      ))}
    </div>
  );
}
