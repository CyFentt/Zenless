import { useEffect, useState } from 'react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Tooltip } from '@/components/Tooltip';
import { StatusDot } from '@/components/StatusDot';
import { Search, RefreshCw, Play, Folder, FileCode2, ChevronRight, Lock, Unlock, Eye, ExternalLink } from 'lucide-react';
import type { StudioNode } from '@/types';

export function StudioPage() {
  const studioState = useStore((s) => s.studioState);
  const studioTree = useStore((s) => s.studioTree);
  const setStudioTree = useStore((s) => s.setStudioTree);
  const setStudioState = useStore((s) => s.setStudioState);
  const selectedNode = useStore((s) => s.selectedStudioNode);
  const setSelectedNode = useStore((s) => s.setSelectedStudioNode);
  const studioQuery = useStore((s) => s.studioQuery);
  const setStudioQuery = useStore((s) => s.setStudioQuery);
  const currentJobId = useStore((s) => s.currentJobId);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [searchResult, setSearchResult] = useState<{ query: string; nodes: StudioNode[] } | null>(null);
  const normalizedQuery = studioQuery.trim();

  useEffect(() => {
    Promise.all([getApi().getStudioState(), getApi().getStudioTree()])
      .then(([state, tree]) => { setStudioState(state.state); setStudioTree(tree); })
      .catch((error) => frontendDiagnostics.capture(error, 'studio', 'Failed to load Studio state'));
  }, [setStudioTree, setStudioState]);

  useEffect(() => {
    if (!normalizedQuery) return;
    const query = normalizedQuery;
    const timer = window.setTimeout(() => {
      getApi().searchStudio(query)
        .then((nodes) => setSearchResult({ query, nodes }))
        .catch((error) => frontendDiagnostics.capture(error, 'studio', 'Studio search failed'));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [normalizedQuery]);

  const searchResults = searchResult?.query === normalizedQuery ? searchResult.nodes : null;

  const toggleNode = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleRefresh = async () => {
    try {
      await getApi().refreshStudio();
      const tree = await getApi().getStudioTree();
      setStudioTree(tree);
    } catch (error) { frontendDiagnostics.capture(error, 'studio', 'Studio refresh failed'); }
  };

  const handleInspect = async (node: StudioNode) => {
    try { setSelectedNode(await getApi().inspectStudio(node.id)); }
    catch (error) { frontendDiagnostics.capture(error, 'studio', 'Studio inspect failed'); }
  };

  const handleLock = async () => {
    if (!selectedNode) return;
    try {
      if (selectedNode.locked) await getApi().unlockStudioReference(selectedNode.id);
      else await getApi().lockStudioReference(selectedNode.id);
      setSelectedNode({ ...selectedNode, locked: !selectedNode.locked });
    } catch (error) { frontendDiagnostics.capture(error, 'studio', 'Studio lock update failed'); }
  };

  const handleUse = async () => {
    if (!selectedNode) return;
    try {
      await getApi().useStudioAsContext(selectedNode.id);
      setSelectedNode({ ...selectedNode, usedAsContext: true });
    } catch (error) { frontendDiagnostics.capture(error, 'studio', 'Failed to add Studio object to context'); }
  };

  const handlePlay = async () => {
    if (!currentJobId) {
      frontendDiagnostics.report('warning', 'studio', 'No active job for Play Test');
      return;
    }
    try { await getApi().startTest(currentJobId); }
    catch (error) { frontendDiagnostics.capture(error, 'studio', 'Failed to start Play Test'); }
  };

  const renderTree = (nodes: StudioNode[], depth = 0): React.ReactNode => nodes.map((node) => {
    const hasChildren = !!node.children?.length;
    const isExpanded = expanded.has(node.id);
    const isFolder = node.className.includes('Folder') || node.className.includes('Workspace') || node.className.includes('Service') || node.className.includes('StarterPlayer');
    return (
      <div key={node.id}>
        <div
          className={`flex items-center h-7 px-2 hover:bg-ink-850 cursor-pointer transition-colors group ${selectedNode?.id === node.id ? 'bg-ink-800' : ''}`}
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
          onClick={() => { setSelectedNode(node); if (hasChildren) toggleNode(node.id); }}
        >
          {hasChildren ? <ChevronRight size={10} className={`text-ink-400 transition-transform shrink-0 ${isExpanded ? 'rotate-90' : ''}`} /> : <span className="w-2.5 shrink-0" />}
          {isFolder ? <Folder size={12} className="text-ink-300 shrink-0 ml-1" /> : <FileCode2 size={12} className="text-ink-100 shrink-0 ml-1" />}
          <span className="text-xs text-ink-100 ml-1.5 truncate">{node.name}</span>
          {node.locked && <Lock size={9} className="ml-auto text-ink-400" />}
        </div>
        {hasChildren && isExpanded && renderTree(node.children ?? [], depth + 1)}
      </div>
    );
  });

  return (
    <div className="flex h-full">
      <div className="w-64 shrink-0 border-r border-ink-600 flex flex-col">
        <div className="flex items-center justify-between px-2 h-8 border-b border-ink-600 shrink-0">
          <div className="flex items-center gap-1.5">
            <span className="text-2xs uppercase tracking-wider text-ink-300">Studio</span>
            <StatusDot status={studioState === 'ONLINE' ? 'READY' : studioState === 'CONNECTING' ? 'CONNECTING' : 'OFF'} />
          </div>
          <div className="flex gap-1">
            <Tooltip content="Refresh"><button onClick={() => void handleRefresh()} className="w-5 h-5 flex items-center justify-center text-ink-300 hover:text-ink-0" aria-label="Refresh Studio"><RefreshCw size={11} /></button></Tooltip>
            <Tooltip content="Play"><button onClick={() => void handlePlay()} className="w-5 h-5 flex items-center justify-center text-ink-300 hover:text-ink-0" aria-label="Start Play Test"><Play size={11} /></button></Tooltip>
          </div>
        </div>
        <div className="px-2 py-1.5 border-b border-ink-700 shrink-0">
          <div className="relative">
            <Search size={10} className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-400" />
            <input value={studioQuery} onChange={(e) => setStudioQuery(e.target.value)} placeholder="Search" className="w-full h-6 pl-6 pr-2 text-2xs text-ink-50 bg-ink-850 border border-ink-600 focus:border-ink-500 placeholder:text-ink-400" />
          </div>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-zen">
          {normalizedQuery ? (
            searchResults ? (
            searchResults.length === 0 ? <div className="px-3 py-4 text-center text-2xs text-ink-400 uppercase">No results</div> : searchResults.map((node) => (
              <button key={node.id} onClick={() => void handleInspect(node)} className="flex items-center w-full h-7 px-2 hover:bg-ink-850 transition-colors text-left">
                <FileCode2 size={12} className="text-ink-100 shrink-0" />
                <span className="text-xs text-ink-100 ml-1.5 truncate">{node.name}</span>
                <span className="text-2xs text-ink-400 ml-auto font-mono truncate">{node.path}</span>
              </button>
            ))
            ) : <div className="px-3 py-4 text-center text-2xs text-ink-400 uppercase">Searching</div>
          ) : renderTree(studioTree)}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-zen">
        {selectedNode ? (
          <div className="p-4 space-y-4 animate-fade-in">
            <div className="flex items-center justify-between border-b border-ink-700 pb-3">
              <span className="text-sm font-medium text-ink-0">{selectedNode.name}</span>
              <div className="flex gap-1">
                <Tooltip content="Inspect"><button onClick={() => void handleInspect(selectedNode)} className="flex items-center gap-1 px-2 h-6 text-2xs uppercase tracking-wider text-ink-150 border border-ink-600 hover:bg-ink-800"><ExternalLink size={10} />OPEN</button></Tooltip>
                <Tooltip content={selectedNode.locked ? 'Unlock' : 'Lock'}><button onClick={() => void handleLock()} className="flex items-center gap-1 px-2 h-6 text-2xs uppercase tracking-wider text-ink-150 border border-ink-600 hover:bg-ink-800">{selectedNode.locked ? <Unlock size={10} /> : <Lock size={10} />}{selectedNode.locked ? 'UNLOCK' : 'LOCK'}</button></Tooltip>
                <Tooltip content="Use as context"><button onClick={() => void handleUse()} className="flex items-center gap-1 px-2 h-6 text-2xs uppercase tracking-wider text-ink-150 border border-ink-600 hover:bg-ink-800"><Eye size={10} />USE</button></Tooltip>
              </div>
            </div>
            <div className="space-y-2">
              <DetailRow label="NAME" value={selectedNode.name} />
              <DetailRow label="CLASS" value={selectedNode.className} mono />
              <DetailRow label="PATH" value={selectedNode.path} mono />
              {selectedNode.usedAsContext && <DetailRow label="CONTEXT" value="USED" />}
            </div>
            {!!selectedNode.children?.length && (
              <div>
                <div className="text-2xs uppercase tracking-wider text-ink-300 mb-2">CHILDREN</div>
                {selectedNode.children.map((child) => (
                  <button key={child.id} onClick={() => void handleInspect(child)} className="flex items-center w-full h-7 px-2 hover:bg-ink-850 transition-colors text-left">
                    <span className="text-xs text-ink-100">{child.name}</span>
                    <span className="text-2xs text-ink-400 ml-auto font-mono">{child.className}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider">Select an item</div>}
      </div>
    </div>
  );
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-ink-700">
      <span className="text-2xs uppercase tracking-wider text-ink-300">{label}</span>
      <span className={`text-xs text-ink-50 ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  );
}
