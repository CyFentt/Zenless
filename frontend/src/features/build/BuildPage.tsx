import { useEffect, useState } from 'react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Tabs } from '@/components/Tabs';
import { Modal } from '@/components/Modal';
import { Tooltip } from '@/components/Tooltip';
import { DiffViewer } from './DiffViewer';
import { Check, X, RefreshCw, Lock, Unlock, Eye, FileCode, CheckCircle, AlertTriangle, ShieldAlert } from 'lucide-react';
import type { ContextItem, Job } from '@/types';

type BuildTab = 'context' | 'changes' | 'history';

export function BuildPage() {
  const navigationTarget = useStore((s) => s.navigationTarget);
  const setNavigationTarget = useStore((s) => s.setNavigationTarget);
  const [activeTab, setActiveTab] = useState<BuildTab>(() => (
    navigationTarget?.page === 'build'
    && (navigationTarget.tab === 'context' || navigationTarget.tab === 'changes' || navigationTarget.tab === 'history')
      ? navigationTarget.tab
      : 'changes'
  ));

  useEffect(() => {
    if (navigationTarget?.page === 'build') setNavigationTarget(null);
  }, [navigationTarget, setNavigationTarget]);

  return (
    <div className="flex flex-col h-full bg-ink-950">
      <Tabs
        tabs={[
          { id: 'changes', label: 'CHANGES' },
          { id: 'context', label: 'CONTEXT' },
          { id: 'history', label: 'HISTORY' },
        ]}
        active={activeTab}
        onChange={(t) => setActiveTab(t as BuildTab)}
      />
      <div className="flex-1 overflow-hidden">
        {activeTab === 'changes' && <ChangesTab />}
        {activeTab === 'context' && <ContextTab />}
        {activeTab === 'history' && <HistoryTab />}
      </div>
    </div>
  );
}

function ContextTab() {
  const currentJobId = useStore((s) => s.currentJobId);
  const contextItems = useStore((s) => s.contextItems);
  const setContextItems = useStore((s) => s.setContextItems);

  const [inspectingItem, setInspectingItem] = useState<ContextItem | null>(null);
  const [loading, setLoading] = useState(false);

  const handleRefresh = async () => {
    if (!currentJobId) return;
    setLoading(true);
    try {
      const items = await getApi().refreshContext(currentJobId);
      setContextItems(items);
    } catch (err) {
      frontendDiagnostics.capture(err, 'build', 'Failed to refresh context items');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleInclude = async (item: ContextItem) => {
    if (item.state === 'locked') return;
    try {
      if (item.state === 'included') {
        await getApi().excludeContext(item.id);
        setContextItems(contextItems.map((c) => (c.id === item.id ? { ...c, state: 'excluded' } : c)));
      } else {
        await getApi().includeContext(item.id);
        setContextItems(contextItems.map((c) => (c.id === item.id ? { ...c, state: 'included' } : c)));
      }
    } catch (err) {
      frontendDiagnostics.capture(err, 'build', 'Failed to toggle context inclusion');
    }
  };

  const handleToggleLock = async (item: ContextItem) => {
    try {
      if (item.state === 'locked') {
        await getApi().unlockContext(item.id);
        setContextItems(contextItems.map((c) => (c.id === item.id ? { ...c, state: 'included' } : c)));
      } else {
        await getApi().lockContext(item.id);
        setContextItems(contextItems.map((c) => (c.id === item.id ? { ...c, state: 'locked' } : c)));
      }
    } catch (err) {
      frontendDiagnostics.capture(err, 'build', 'Failed to toggle context lock');
    }
  };

  const handleInspect = async (item: ContextItem) => {
    try {
      const detailed = await getApi().inspectContext(item.id);
      setInspectingItem(detailed);
    } catch {
      setInspectingItem(item);
    }
  };

  return (
    <div className="flex flex-col h-full p-4 overflow-hidden">
      <div className="flex items-center justify-between pb-3 border-b border-ink-700">
        <div className="flex items-center gap-3">
          <span className="text-2xs uppercase tracking-widest text-ink-300">
            RELEVANT PROJECT OBJECTS ({contextItems.length})
          </span>
          {loading && <RefreshCw size={12} className="animate-spin text-ink-400" />}
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading || !currentJobId}
          className="flex items-center gap-1.5 px-3 py-1 text-2xs font-mono uppercase tracking-wider bg-ink-850 text-ink-100 border border-ink-700 rounded hover:bg-ink-800 transition-colors disabled:opacity-50"
        >
          <RefreshCw size={11} />
          REFRESH INDEX
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-zen py-3 space-y-2">
        {contextItems.length === 0 ? (
          <div className="p-8 text-center text-xs text-ink-400 font-mono">
            {currentJobId ? 'No context items derived yet.' : 'No active job selected.'}
          </div>
        ) : (
          contextItems.map((item) => {
            const relPercent = Math.round((item.relevance ?? 0) * 100);
            return (
              <div
                key={item.id}
                className={`flex items-center justify-between p-3 border rounded transition-colors ${
                  item.state === 'included'
                    ? 'bg-ink-900 border-ink-700'
                    : item.state === 'locked'
                      ? 'bg-ink-900/60 border-zen-ok/40'
                      : 'bg-ink-950 border-ink-800 opacity-60'
                }`}
              >
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  <FileCode size={16} className="text-ink-300 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-ink-100 truncate">{item.name}</span>
                      <span className="px-1.5 py-0.2 text-2xs font-mono bg-ink-800 text-ink-300 rounded shrink-0">
                        {item.type}
                      </span>
                    </div>
                    <div className="text-2xs font-mono text-ink-400 truncate">{item.path}</div>
                  </div>
                </div>

                <div className="flex items-center gap-4 shrink-0">
                  <div className="flex items-center gap-2 w-28">
                    <span className="text-2xs font-mono text-ink-400 w-8 text-right">{relPercent}%</span>
                    <div className="flex-1 h-1.5 bg-ink-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-ink-300 transition-all duration-300"
                        style={{ width: `${Math.min(100, Math.max(0, relPercent))}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-1 border-l border-ink-700 pl-3">
                    <Tooltip content="Inspect context details">
                      <button
                        onClick={() => handleInspect(item)}
                        className="p-1.5 text-ink-300 hover:text-ink-0 hover:bg-ink-800 rounded transition-colors"
                      >
                        <Eye size={13} />
                      </button>
                    </Tooltip>

                    <Tooltip content={item.state === 'locked' ? 'Unlock context' : 'Lock context'}>
                      <button
                        onClick={() => handleToggleLock(item)}
                        className={`p-1.5 rounded transition-colors ${
                          item.state === 'locked'
                            ? 'text-zen-okBright bg-zen-ok/10 hover:bg-zen-ok/20'
                            : 'text-ink-300 hover:text-ink-0 hover:bg-ink-800'
                        }`}
                      >
                        {item.state === 'locked' ? <Lock size={13} /> : <Unlock size={13} />}
                      </button>
                    </Tooltip>

                    <Tooltip
                      content={
                        item.state === 'locked'
                          ? 'Locked'
                          : item.state === 'included'
                            ? 'Exclude from AI prompt'
                            : 'Include in AI prompt'
                      }
                    >
                      <button
                        onClick={() => handleToggleInclude(item)}
                        disabled={item.state === 'locked'}
                        className={`px-2 py-1 text-2xs font-mono font-semibold rounded uppercase transition-colors ${
                          item.state === 'included'
                            ? 'bg-ink-700 text-ink-100 hover:bg-ink-600'
                            : item.state === 'locked'
                              ? 'bg-ink-800 text-ink-400 opacity-50 cursor-not-allowed'
                              : 'bg-ink-850 text-ink-400 hover:text-ink-200'
                        }`}
                      >
                        {item.state}
                      </button>
                    </Tooltip>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {inspectingItem && (
        <Modal
          open={!!inspectingItem}
          onClose={() => setInspectingItem(null)}
          title={`INSPECT: ${inspectingItem.name}`}
          width="w-[34rem]"
        >
          <div className="space-y-4 font-mono text-xs text-ink-200">
            <div>
              <span className="text-ink-400 text-2xs uppercase block">Path</span>
              <span className="text-ink-100">{inspectingItem.path}</span>
            </div>
            <div className="grid grid-cols-3 gap-4 border-y border-ink-700 py-3">
              <div>
                <span className="text-ink-400 text-2xs uppercase block">Type</span>
                <span className="text-ink-100">{inspectingItem.type}</span>
              </div>
              <div>
                <span className="text-ink-400 text-2xs uppercase block">Relevance</span>
                <span className="text-ink-100">{Math.round((inspectingItem.relevance ?? 0) * 100)}%</span>
              </div>
              <div>
                <span className="text-ink-400 text-2xs uppercase block">State</span>
                <span className="text-ink-100 uppercase">{inspectingItem.state}</span>
              </div>
            </div>
            <div className="flex justify-end pt-2">
              <button
                onClick={() => setInspectingItem(null)}
                className="px-3 py-1 bg-ink-800 text-ink-100 border border-ink-700 rounded text-2xs uppercase hover:bg-ink-700 transition-colors"
              >
                CLOSE
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ChangesTab() {
  const currentJobId = useStore((s) => s.currentJobId);
  const currentJob = useStore((s) => s.jobs.find((job) => job.id === s.currentJobId));
  const changedFiles = useStore((s) => s.changedFiles);
  const setChangedFiles = useStore((s) => s.setChangedFiles);
  const review = useStore((s) => s.review);
  const selectedFileId = useStore((s) => s.selectedFileId);
  const setSelectedFileId = useStore((s) => s.setSelectedFileId);

  const [acting, setActing] = useState(false);

  useEffect(() => {
    if (changedFiles.length > 0 && !selectedFileId) setSelectedFileId(changedFiles[0].id);
  }, [changedFiles, selectedFileId, setSelectedFileId]);

  const selectedFile = changedFiles.find((f) => f.id === selectedFileId) ?? changedFiles[0];

  const handleApprove = async () => {
    if (!currentJobId) return;
    setActing(true);
    try {
      await getApi().approveChanges(currentJobId);
    } catch (err) {
      frontendDiagnostics.capture(err, 'build', 'Failed to approve changes');
    } finally {
      setActing(false);
    }
  };

  const handleReject = async () => {
    if (!currentJobId) return;
    setActing(true);
    try {
      await getApi().rejectChanges(currentJobId);
    } catch (err) {
      frontendDiagnostics.capture(err, 'build', 'Failed to reject changes');
    } finally {
      setActing(false);
    }
  };

  const handleSaveContent = async (fileId: string, content: string) => {
    if (!currentJobId) return;
    await getApi().editChanges(currentJobId, fileId, content);
    const updated = await getApi().getChanges(currentJobId);
    setChangedFiles(updated);
  };

  return (
    <div className="flex h-full overflow-hidden">
      <div className="w-80 shrink-0 border-r border-ink-700 flex flex-col bg-ink-900 overflow-hidden">
        {review && (
          <div className="p-3 border-b border-ink-700 bg-ink-950 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-2xs font-mono uppercase tracking-widest text-ink-300">
                INDEPENDENT REVIEW
              </span>
              <span className="text-2xs font-mono text-ink-400">{review.reviewer}</span>
            </div>

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {review.decision === 'APPROVE' ? (
                  <CheckCircle size={16} className="text-zen-okBright" />
                ) : review.decision === 'BLOCK' ? (
                  <ShieldAlert size={16} className="text-zen-errBright" />
                ) : (
                  <AlertTriangle size={16} className="text-zen-warnBright" />
                )}
                <span
                  className={`text-xs font-bold font-mono tracking-wider ${
                    review.decision === 'APPROVE'
                      ? 'text-zen-okBright'
                      : review.decision === 'BLOCK'
                        ? 'text-zen-errBright'
                        : 'text-zen-warnBright'
                  }`}
                >
                  {review.decision}
                </span>
              </div>
              <span
                className={`px-1.5 py-0.5 text-2xs font-mono font-semibold rounded uppercase ${
                  review.risk === 'LOW'
                    ? 'bg-zen-ok/20 text-zen-okBright'
                    : review.risk === 'CRITICAL' || review.risk === 'HIGH'
                      ? 'bg-zen-err/20 text-zen-errBright'
                      : 'bg-zen-warn/20 text-zen-warnBright'
                }`}
              >
                {review.risk} RISK
              </span>
            </div>

            {review.summary && (
              <p className="text-2xs font-mono text-ink-200 line-clamp-3">{review.summary}</p>
            )}

            {review.criticalIssues.length > 0 && (
              <div className="space-y-1 pt-1">
                <span className="text-2xs font-mono text-zen-errBright font-semibold uppercase">
                  Critical Issues ({review.criticalIssues.length}):
                </span>
                {review.criticalIssues.map((issue, idx) => (
                  <div key={idx} className="text-2xs font-mono text-zen-errBright/80 truncate">
                    • {issue}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="p-3 border-b border-ink-700 flex gap-2 bg-ink-950">
          <button
            onClick={handleApprove}
            disabled={acting || changedFiles.length === 0 || currentJob?.stage !== 'WAITING_CHANGE_APPROVAL'}
            className="flex-1 flex items-center justify-center gap-1.5 h-8 text-2xs font-mono uppercase font-semibold bg-zen-ok text-black rounded hover:bg-zen-okBright transition-colors disabled:opacity-50"
          >
            <Check size={12} />
            APPROVE
          </button>
          <button
            onClick={handleReject}
            disabled={acting || changedFiles.length === 0 || currentJob?.stage !== 'WAITING_CHANGE_APPROVAL'}
            className="flex-1 flex items-center justify-center gap-1.5 h-8 text-2xs font-mono uppercase font-semibold bg-zen-err text-white rounded hover:bg-zen-errBright transition-colors disabled:opacity-50"
          >
            <X size={12} />
            REJECT
          </button>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-zen">
          <div className="px-3 py-2 text-2xs font-mono uppercase tracking-widest text-ink-400 border-b border-ink-800">
            CHANGED FILES ({changedFiles.length})
          </div>
          {changedFiles.length === 0 ? (
            <div className="p-4 text-xs font-mono text-ink-400 text-center italic">
              No changes in current job.
            </div>
          ) : (
            changedFiles.map((file) => {
              const isSelected = selectedFile?.id === file.id;
              return (
                <button
                  key={file.id}
                  onClick={() => setSelectedFileId(file.id)}
                  className={`flex items-center justify-between w-full px-3 py-2.5 border-b border-ink-800 text-left transition-colors ${
                    isSelected ? 'bg-ink-800' : 'hover:bg-ink-850'
                  }`}
                >
                  <div className="min-w-0 flex-1 pr-2">
                    <div className="text-xs font-mono font-medium text-ink-100 truncate">
                      {file.name}
                    </div>
                    <div className="flex items-center gap-2 text-2xs font-mono mt-0.5">
                      <span className="text-zen-okBright">+{file.additions}</span>
                      <span className="text-zen-errBright">-{file.deletions}</span>
                    </div>
                  </div>
                  <span
                    className={`px-1.5 py-0.5 text-2xs font-mono font-bold rounded shrink-0 ${
                      file.status === 'A'
                        ? 'bg-zen-ok/20 text-zen-okBright'
                        : file.status === 'D'
                          ? 'bg-zen-err/20 text-zen-errBright'
                          : 'bg-ink-700 text-ink-200'
                    }`}
                  >
                    {file.status}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </div>

      <div className="flex-1 p-3 overflow-hidden">
        {selectedFile ? (
          <DiffViewer file={selectedFile} onSaveContent={handleSaveContent} />
        ) : (
          <div className="flex items-center justify-center h-full text-xs font-mono text-ink-400 uppercase">
            NO FILE SELECTED
          </div>
        )}
      </div>
    </div>
  );
}

function HistoryTab() {
  const jobs = useStore((s) => s.jobs);
  const currentJobId = useStore((s) => s.currentJobId);
  const setCurrentJobId = useStore((s) => s.setCurrentJobId);

  const formatTime = (ts: number) => {
    if (!ts) return '—';
    const date = new Date(ts);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  return (
    <div className="flex flex-col h-full p-4 overflow-hidden">
      <div className="pb-3 border-b border-ink-700 flex items-center justify-between">
        <span className="text-2xs uppercase tracking-widest text-ink-300">
          JOB HISTORY ({jobs.length})
        </span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-zen py-3 space-y-2">
        {jobs.length === 0 ? (
          <div className="p-8 text-center text-xs font-mono text-ink-400">No jobs recorded yet.</div>
        ) : (
          jobs.map((job: Job) => {
            const isSelected = job.id === currentJobId;
            return (
              <div
                key={job.id}
                onClick={() => setCurrentJobId(job.id)}
                className={`flex items-center justify-between p-3 border rounded cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-ink-850 border-ink-500'
                    : 'bg-ink-900/70 border-ink-800 hover:bg-ink-850/60'
                }`}
              >
                <div className="min-w-0 flex-1 pr-4">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold text-ink-100 truncate">{job.title}</span>
                    {isSelected && (
                      <span className="px-1.5 py-0.2 text-2xs font-mono bg-zen-ok/20 text-zen-okBright rounded uppercase">
                        ACTIVE
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-2xs font-mono text-ink-400 mt-1">
                    <span>ID: {job.id.slice(0, 12)}</span>
                    <span>UPDATED: {formatTime(job.updatedAt)}</span>
                  </div>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <span className="px-2 py-0.5 text-2xs font-mono bg-ink-800 text-ink-200 border border-ink-700 rounded uppercase">
                    {job.stage}
                  </span>
                  <span
                    className={`px-2 py-0.5 text-2xs font-mono font-bold rounded uppercase ${
                      job.status === 'COMPLETE'
                        ? 'bg-zen-ok/20 text-zen-okBright'
                        : job.status === 'FAILED'
                          ? 'bg-zen-err/20 text-zen-errBright'
                          : job.status === 'RUNNING'
                            ? 'bg-ink-700 text-ink-100'
                            : 'bg-ink-800 text-ink-400'
                    }`}
                  >
                    {job.status}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
