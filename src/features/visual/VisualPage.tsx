import { useEffect, useState, lazy, Suspense } from 'react';
import { useStore } from '@/store';
import { getApi, isMockMode, getMockApi } from '@/services';
import { Tabs, Segmented } from '@/components/Tabs';
import { Tooltip } from '@/components/Tooltip';
import { Modal } from '@/components/Modal';
import { Pencil, RefreshCw, Check, CircleAlert as AlertCircle, ZoomIn, X } from 'lucide-react';
import { frontendDiagnostics } from '@/services/diagnostics';
import type { ViewName, ViewTile } from '@/types';

const ModelViewer = lazy(() => import('@/features/visual/ModelViewer').then((m) => ({ default: m.ModelViewer })));

type VisualTab = 'views' | '3d' | 'assets';

export function VisualPage() {
  const [tab, setTab] = useState<VisualTab>('views');

  return (
    <div className="flex flex-col h-full">
      <Tabs
        tabs={[
          { id: 'views', label: 'VIEWS' },
          { id: '3d', label: '3D' },
          { id: 'assets', label: 'ASSETS' },
        ]}
        active={tab}
        onChange={(t) => setTab(t as VisualTab)}
      />
      <div className="flex-1 overflow-hidden">
        {tab === 'views' && <ViewsTab />}
        {tab === '3d' && (
          <Suspense fallback={<div className="flex items-center justify-center h-full text-xs text-ink-300 animate-pulse">Loading 3D…</div>}>
            <ModelViewerTab />
          </Suspense>
        )}
        {tab === 'assets' && <AssetsTab />}
      </div>
    </div>
  );
}

const VIEW_NAMES: ViewName[] = ['FRONT', 'BACK', 'LEFT', 'RIGHT', 'TOP', 'BOTTOM'];

function useJobId(): string | null {
  const currentJobId = useStore((s) => s.currentJobId);
  return currentJobId;
}

function ViewsTab() {
  const views = useStore((s) => s.views);
  const setViews = useStore((s) => s.setViews);
  const conceptVersion = useStore((s) => s.conceptVersion);
  const conceptStatus = useStore((s) => s.conceptStatus);
  const conceptPrompt = useStore((s) => s.conceptPrompt);
  const jobId = useJobId();
  const [editOpen, setEditOpen] = useState(false);
  const [editText, setEditText] = useState('');
  const [previewView, setPreviewView] = useState<ViewTile | null>(null);

  useEffect(() => {
    if (!jobId) return;
    getApi().getVisual(jobId).then((data) => {
      setViews(data.views);
      useStore.getState().setConcept(data.concept.version, data.concept.status, data.concept.prompt);
    }).catch((e) => frontendDiagnostics.report('error', 'visual', `Failed to load visual: ${e}`));
  }, [jobId, setViews]);

  const handleRegen = async () => {
    if (!jobId) return;
    setViews(views.map((v) => ({ ...v, state: 'GENERATING' as const })));
    await getApi().regenerateVisual(jobId).catch((e) => frontendDiagnostics.report('error', 'visual', `Regen failed: ${e}`));
  };
  const handleApprove = async () => {
    if (!jobId) return;
    await getApi().approveVisual(jobId).catch((e) => frontendDiagnostics.report('error', 'visual', `Approve failed: ${e}`));
    setViews(views.map((v) => ({ ...v, state: 'APPROVED' as const })));
  };
  const handleEditOpen = () => {
    setEditText(conceptPrompt || '');
    setEditOpen(true);
  };
  const handleEditSave = async () => {
    if (!jobId) return;
    await getApi().editConcept(jobId, editText).catch((e) => frontendDiagnostics.report('error', 'visual', `Concept edit failed: ${e}`));
    useStore.getState().setConcept(conceptVersion, conceptStatus, editText);
    setEditOpen(false);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 grid grid-cols-3 grid-rows-2 gap-px bg-ink-600 p-px">
        {VIEW_NAMES.map((name) => {
          const view = views.find((v) => v.name === name) ?? { name, state: 'EMPTY' as const };
          return <ViewTile key={name} view={view} jobId={jobId} onPreview={setPreviewView} />;
        })}
      </div>
      <div className="flex items-center justify-between px-3 h-10 border-t border-ink-600 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-2xs uppercase tracking-wider text-ink-300">V{conceptVersion}</span>
          <span className={`text-2xs uppercase tracking-wider ${conceptStatus === 'READY' ? 'text-zen-okBright' : conceptStatus === 'GENERATING' ? 'text-zen-warnBright' : 'text-ink-400'}`}>{conceptStatus}</span>
        </div>
        <div className="flex gap-1">
          <Tooltip content="Edit concept prompt"><button onClick={handleEditOpen} className="flex items-center gap-1 px-2 h-7 text-2xs uppercase tracking-wider text-ink-150 border border-ink-600 hover:bg-ink-800 transition-colors"><Pencil size={10} />EDIT</button></Tooltip>
          <Tooltip content="Regenerate all views"><button onClick={handleRegen} className="flex items-center gap-1 px-2 h-7 text-2xs uppercase tracking-wider text-ink-150 border border-ink-600 hover:bg-ink-800 transition-colors"><RefreshCw size={10} />REGEN</button></Tooltip>
          <button onClick={handleApprove} className="flex items-center gap-1 px-2 h-7 text-2xs uppercase tracking-wider text-zen-okBright border border-ink-600 hover:bg-ink-800 transition-colors"><Check size={10} />APPROVE</button>
        </div>
      </div>

      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="CONCEPT" width="w-96">
        <div className="space-y-3">
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            rows={4}
            className="w-full bg-ink-800 border border-ink-600 text-xs text-ink-50 p-3 resize-none focus:border-ink-500 scrollbar-zen"
            placeholder="Describe the concept..."
            autoFocus
          />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setEditOpen(false)} className="px-3 h-7 text-2xs uppercase tracking-wider text-ink-300 border border-ink-600 hover:bg-ink-800">CANCEL</button>
            <button onClick={handleEditSave} disabled={!editText.trim()} className="px-3 h-7 text-2xs uppercase tracking-wider text-zen-okBright border border-ink-600 hover:bg-ink-800 disabled:opacity-30">SAVE</button>
          </div>
        </div>
      </Modal>

      <Modal open={!!previewView} onClose={() => setPreviewView(null)} title={previewView?.name} width="w-[480px]">
        {previewView?.imageUrl && (
          <div className="flex items-center justify-center">
            <img src={previewView.imageUrl} alt={previewView.name} className="max-w-full max-h-[400px] object-contain" />
          </div>
        )}
      </Modal>
    </div>
  );
}

function ViewTile({ view, jobId, onPreview }: { view: ViewTile; jobId: string | null; onPreview: (v: ViewTile) => void }) {
  const setViews = useStore((s) => s.setViews);
  const [imgError, setImgError] = useState(false);

  const handleRegen = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!jobId) return;
    setViews(useStore.getState().views.map((v) => v.name === view.name ? { ...v, state: 'GENERATING' as const } : v));
    await getApi().regenerateView(jobId, view.name).catch((e2) => frontendDiagnostics.report('error', 'visual', `View regen failed: ${e2}`));
  };

  const statusIcon = () => {
    switch (view.state) {
      case 'READY': return <span className="w-1.5 h-1.5 bg-zen-okBright" />;
      case 'APPROVED': return <Check size={10} className="text-zen-okBright" />;
      case 'GENERATING': return <RefreshCw size={10} className="text-zen-warnBright animate-spin-slow" />;
      case 'FAILED': return <AlertCircle size={10} className="text-zen-errBright" />;
      default: return <span className="w-1.5 h-1.5 bg-ink-500" />;
    }
  };

  const showImage = (view.state === 'READY' || view.state === 'APPROVED') && view.imageUrl && !imgError;

  return (
    <div className="bg-ink-950 relative group flex items-center justify-center overflow-hidden">
      <span className="absolute top-2 left-2 text-2xs uppercase tracking-wider text-ink-300 font-medium z-10">{view.name}</span>
      <span className="absolute top-2 right-2 z-10 flex items-center gap-1">
        {statusIcon()}
        <Tooltip content={view.state}>
          <span className={`text-2xs uppercase tracking-wider ${view.state === 'READY' || view.state === 'APPROVED' ? 'text-zen-okBright' : view.state === 'GENERATING' ? 'text-zen-warnBright' : view.state === 'FAILED' ? 'text-zen-errBright' : 'text-ink-400'}`}>{view.state}</span>
        </Tooltip>
      </span>

      {showImage ? (
        <img
          src={view.imageUrl}
          alt={view.name}
          className="w-full h-full object-contain"
          onError={() => { setImgError(true); frontendDiagnostics.report('warning', 'visual', `Image load failed: ${view.name}`); }}
          loading="lazy"
        />
      ) : view.state === 'EMPTY' || view.state === 'GENERATING' ? (
        <div className="w-full h-full flex items-center justify-center grid-bg">
          {view.state === 'GENERATING' && <RefreshCw size={20} className="text-ink-600 animate-spin-slow" />}
        </div>
      ) : view.state === 'FAILED' ? (
        <div className="w-full h-full flex flex-col items-center justify-center gap-2">
          <AlertCircle size={20} className="text-zen-err" />
          <button onClick={handleRegen} className="text-2xs text-ink-300 hover:text-ink-0 uppercase tracking-wider border border-ink-600 px-2 h-6">RETRY</button>
        </div>
      ) : (
        <div className="w-full h-full flex items-center justify-center grid-bg" />
      )}

      {showImage && (
        <button onClick={() => onPreview(view)} className="absolute top-2 right-14 w-6 h-6 flex items-center justify-center text-ink-400 hover:text-ink-0 opacity-0 group-hover:opacity-100 transition-opacity" aria-label="Zoom view">
          <ZoomIn size={11} />
        </button>
      )}
      {view.state !== 'GENERATING' && (
        <button onClick={handleRegen} className="absolute bottom-2 right-2 w-6 h-6 flex items-center justify-center text-ink-400 hover:text-ink-0 opacity-0 group-hover:opacity-100 transition-opacity" aria-label="Regenerate view">
          <RefreshCw size={10} />
        </button>
      )}
    </div>
  );
}

function ModelViewerTab() {
  const modelInfo = useStore((s) => s.modelInfo);
  const setModelInfo = useStore((s) => s.setModelInfo);
  const jobId = useJobId();

  useEffect(() => {
    if (!jobId) return;
    getApi().getModel(jobId).then(setModelInfo).catch((e) => frontendDiagnostics.report('error', 'model', `Failed to load model: ${e}`));
  }, [jobId, setModelInfo]);

  const handleRegenGeo = async () => {
    if (!jobId) return;
    setModelInfo({ ...modelInfo, geometryStatus: 'GENERATING' });
    await getApi().regenerateGeometry(jobId).catch((e) => frontendDiagnostics.report('error', 'model', `Geo regen failed: ${e}`));
  };
  const handleRegenTex = async () => {
    if (!jobId) return;
    setModelInfo({ ...modelInfo, textureStatus: 'GENERATING' });
    await getApi().regenerateTexture(jobId).catch((e) => frontendDiagnostics.report('error', 'model', `Tex regen failed: ${e}`));
  };
  const handleApprove = async () => {
    if (!jobId) return;
    await getApi().approveModel(jobId).catch((e) => frontendDiagnostics.report('error', 'model', `Approve failed: ${e}`));
    setModelInfo({ ...modelInfo, state: 'APPROVED' });
  };

  const hasModel = modelInfo.modelUrl && modelInfo.state !== 'EMPTY';

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 relative bg-ink-950 overflow-hidden">
        {hasModel ? (
          <Suspense fallback={<div className="flex items-center justify-center h-full text-xs text-ink-300 animate-pulse">Loading viewer…</div>}>
            <ModelViewer modelUrl={modelInfo.modelUrl} />
          </Suspense>
        ) : (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <span className="text-xs text-ink-400 uppercase tracking-wider">NO MODEL</span>
            {modelInfo.filename && <span className="text-2xs text-ink-500 font-mono">{modelInfo.filename}</span>}
          </div>
        )}
      </div>
      <div className="flex items-center justify-between px-3 h-10 border-t border-ink-600 shrink-0">
        <div className="flex items-center gap-4">
          {modelInfo.filename && <span className="text-2xs text-ink-400 font-mono truncate max-w-48">{modelInfo.filename}</span>}
          <div className="flex items-center gap-1.5">
            <span className="text-2xs uppercase tracking-wider text-ink-300">GEOMETRY</span>
            <span className={`w-1.5 h-1.5 ${modelInfo.geometryStatus === 'READY' ? 'bg-zen-okBright' : modelInfo.geometryStatus === 'GENERATING' ? 'bg-zen-warnBright animate-pulse-soft' : modelInfo.geometryStatus === 'FAILED' ? 'bg-zen-errBright' : 'bg-ink-500'}`} />
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-2xs uppercase tracking-wider text-ink-300">TEXTURE</span>
            <span className={`w-1.5 h-1.5 ${modelInfo.textureStatus === 'READY' ? 'bg-zen-okBright' : modelInfo.textureStatus === 'GENERATING' ? 'bg-zen-warnBright animate-pulse-soft' : modelInfo.textureStatus === 'FAILED' ? 'bg-zen-errBright' : 'bg-ink-500'}`} />
          </div>
        </div>
        <div className="flex gap-1">
          <Tooltip content="Regenerate geometry"><button onClick={handleRegenGeo} className="px-2 h-7 text-2xs uppercase tracking-wider text-ink-150 border border-ink-600 hover:bg-ink-800"><RefreshCw size={10} className="inline mr-1" />SHAPE</button></Tooltip>
          <Tooltip content="Regenerate texture"><button onClick={handleRegenTex} className="px-2 h-7 text-2xs uppercase tracking-wider text-ink-150 border border-ink-600 hover:bg-ink-800"><RefreshCw size={10} className="inline mr-1" />TEXTURE</button></Tooltip>
          <button onClick={handleApprove} className="px-2 h-7 text-2xs uppercase tracking-wider text-zen-okBright border border-ink-600 hover:bg-ink-800"><Check size={10} className="inline mr-1" />APPROVE</button>
        </div>
      </div>
    </div>
  );
}

function AssetsTab() {
  const assets = useStore((s) => s.assets);
  const setAssets = useStore((s) => s.setAssets);
  const [layout, setLayout] = useState<'grid' | 'list'>('grid');
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    getApi().getAssets().then(setAssets).catch((e) => frontendDiagnostics.report('error', 'assets', `Failed to load assets: ${e}`));
  }, [setAssets]);

  const selectedAsset = assets.find((a) => a.id === selected);

  if (selectedAsset) {
    return (
      <div className="flex h-full">
        <div className="w-48 shrink-0 border-r border-ink-600 overflow-y-auto scrollbar-zen">
          {assets.map((a) => (
            <button key={a.id} onClick={() => setSelected(a.id)} className={`flex items-center w-full px-3 h-8 border-b border-ink-700 text-left ${selected === a.id ? 'bg-ink-700' : 'hover:bg-ink-850'}`}>
              <span className="text-2xs font-mono text-ink-400 w-10">{a.type}</span>
              <span className="text-xs text-ink-50 truncate">{a.name}</span>
            </button>
          ))}
        </div>
        <div className="flex-1 flex flex-col">
          <div className="flex items-center justify-between px-3 h-8 border-b border-ink-600">
            <span className="text-2xs uppercase tracking-wider text-ink-100">{selectedAsset.name}</span>
            <button onClick={() => setSelected(null)} className="text-2xs text-ink-300 hover:text-ink-0 uppercase">CLOSE</button>
          </div>
          <div className="flex-1 flex items-center justify-center bg-ink-950 grid-bg p-6">
            {selectedAsset.type === 'GLB' || selectedAsset.type === 'VIEW' || selectedAsset.type === 'IMG' ? (
              selectedAsset.url && !selectedAsset.url.includes('/mock/') ? (
                <img src={selectedAsset.url} alt={selectedAsset.name} className="max-w-full max-h-full object-contain" />
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <span className="text-xs text-ink-400 uppercase tracking-wider">{selectedAsset.type === 'GLB' ? '3D MODEL' : 'PREVIEW'}</span>
                  <span className="text-2xs text-ink-500 font-mono">{selectedAsset.name}</span>
                </div>
              )
            ) : (
              <div className="w-32 h-32 border border-ink-600 flex items-center justify-center text-xs text-ink-500 font-mono">{selectedAsset.type}</div>
            )}
          </div>
          <div className="px-3 py-2 border-t border-ink-600 flex gap-4">
            <span className="text-2xs text-ink-300 uppercase">TYPE: <span className="text-ink-50">{selectedAsset.type}</span></span>
            <span className="text-2xs text-ink-300 uppercase">SIZE: <span className="text-ink-50">{(selectedAsset.size / 1000).toFixed(0)}KB</span></span>
            {selectedAsset.conceptVersion && <span className="text-2xs text-ink-300 uppercase">V: <span className="text-ink-50">{selectedAsset.conceptVersion}</span></span>}
          </div>
        </div>
      </div>
    );
  }

  if (assets.length === 0) {
    return <div className="flex items-center justify-center h-full text-xs text-ink-400 uppercase tracking-wider">NO ASSETS</div>;
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-zen">
      <div className="flex items-center justify-end px-3 py-2 border-b border-ink-600">
        <Segmented options={[{ id: 'grid', label: 'GRID' }, { id: 'list', label: 'LIST' }]} active={layout} onChange={(v) => setLayout(v as 'grid' | 'list')} />
      </div>
      {layout === 'grid' ? (
        <div className="grid grid-cols-4 lg:grid-cols-6 gap-px bg-ink-600 p-px">
          {assets.map((a) => (
            <button key={a.id} onClick={() => setSelected(a.id)} className="bg-ink-950 hover:bg-ink-850 p-3 flex flex-col items-center gap-2 transition-colors group">
              <div className="w-14 h-14 border border-ink-600 flex items-center justify-center text-2xs font-mono text-ink-400 group-hover:border-ink-500 group-hover:text-ink-200 overflow-hidden">
                {a.thumbnailUrl ? <img src={a.thumbnailUrl} alt={a.name} className="w-full h-full object-cover" /> : a.type}
              </div>
              <span className="text-2xs text-ink-100 truncate w-full text-center">{a.name}</span>
            </button>
          ))}
        </div>
      ) : (
        <div>
          {assets.map((a) => (
            <button key={a.id} onClick={() => setSelected(a.id)} className="flex items-center w-full px-3 h-8 border-b border-ink-700 hover:bg-ink-850 transition-colors">
              <span className="text-2xs font-mono text-ink-400 w-12">{a.type}</span>
              <span className="text-xs text-ink-50 flex-1 text-left">{a.name}</span>
              <span className="text-2xs text-ink-400 font-mono">{(a.size / 1000).toFixed(0)}KB</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
