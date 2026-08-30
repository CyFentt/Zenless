import { useState, lazy, Suspense } from 'react';
import { Box, Check, RefreshCw, Eye } from 'lucide-react';
import type { ChatArtifact, ModelInfo } from '@/types';

const ModelViewer = lazy(() =>
  import('@/features/visual/ModelViewer').then((m) => ({ default: m.ModelViewer }))
);

interface Props {
  artifact: ChatArtifact;
  modelInfo?: ModelInfo;
  onApproveModel: (jobId: string) => Promise<void>;
  onRegenerateGeometry: (jobId: string) => Promise<void>;
  onRegenerateTexture: (jobId: string) => Promise<void>;
  onOpenModelViewer: (jobId: string) => void;
}

export function ChatModelCard({ artifact, modelInfo, onApproveModel, onRegenerateGeometry, onRegenerateTexture, onOpenModelViewer }: Props) {
  const [acting, setActing] = useState(false);
  const [interactive3D, setInteractive3D] = useState(false);

  const jobId = artifact.jobId ?? '';
  const modelUrl = artifact.modelUrl || modelInfo?.modelUrl;

  const handleApprove = async () => {
    if (!jobId || acting) return;
    setActing(true);
    try {
      await onApproveModel(jobId);
    } finally {
      setActing(false);
    }
  };

  const handleRegenGeo = async () => {
    if (!jobId || acting) return;
    setActing(true);
    try {
      await onRegenerateGeometry(jobId);
    } finally {
      setActing(false);
    }
  };

  const handleRegenTex = async () => {
    if (!jobId || acting) return;
    setActing(true);
    try {
      await onRegenerateTexture(jobId);
    } finally {
      setActing(false);
    }
  };

  return (
    <div className="my-3 p-4 bg-ink-900/90 border border-ink-700 rounded font-mono text-2xs space-y-3 shadow-lg">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-ink-800 pb-2">
        <div className="flex items-center gap-2">
          <Box size={14} className="text-ink-200" />
          <span className="font-semibold text-xs text-ink-100">{artifact.name || '3D MODEL GENERATED'}</span>
        </div>
        <span
          className={`px-2 py-0.5 rounded font-bold uppercase tracking-wider ${
            artifact.state === 'APPROVED'
              ? 'bg-zen-ok/20 text-zen-okBright'
              : artifact.state === 'FAILED'
                ? 'bg-zen-err/20 text-zen-errBright'
                : 'bg-zen-warn/20 text-zen-warnBright'
          }`}
        >
          {artifact.state}
        </span>
      </div>

      {/* Geometry & Texture Status */}
      <div className="flex items-center justify-between px-3 py-2 bg-ink-950 rounded border border-ink-800">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="text-ink-400">SHAPE</span>
            <span
              className={`w-2 h-2 rounded-full ${
                modelInfo?.geometryStatus === 'READY' ? 'bg-zen-okBright' : 'bg-zen-warnBright animate-pulse'
              }`}
            />
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-ink-400">TEXTURE</span>
            <span
              className={`w-2 h-2 rounded-full ${
                modelInfo?.textureStatus === 'READY' ? 'bg-zen-okBright' : 'bg-zen-warnBright animate-pulse'
              }`}
            />
          </div>
        </div>

        <button
          onClick={() => setInteractive3D(!interactive3D)}
          className="flex items-center gap-1 text-ink-300 hover:text-ink-0 transition-colors uppercase text-2xs"
        >
          <Eye size={12} />
          {interactive3D ? 'HIDE PREVIEW' : 'PREVIEW 3D'}
        </button>
      </div>

      {/* Lazy Interactive 3D Preview */}
      {interactive3D && (
        <div className="h-56 bg-ink-950 rounded border border-ink-800 relative overflow-hidden">
          <Suspense fallback={<div className="flex items-center justify-center h-full text-ink-400">Loading 3D...</div>}>
            <ModelViewer modelUrl={modelUrl} allowDemo={!modelUrl} />
          </Suspense>
        </div>
      )}

      {/* Action Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div className="flex items-center gap-2">
          {artifact.state !== 'APPROVED' && (
            <button
              onClick={handleApprove}
              disabled={acting || !jobId}
              className="flex items-center gap-1 px-3 py-1.5 bg-zen-ok text-black rounded font-bold uppercase hover:bg-zen-okBright transition-colors disabled:opacity-50"
            >
              <Check size={12} />
              APPROVE MODEL
            </button>
          )}

          <button
            onClick={handleRegenGeo}
            disabled={acting || !jobId}
            className="flex items-center gap-1 px-2.5 py-1.5 bg-ink-800 text-ink-100 border border-ink-700 rounded uppercase hover:bg-ink-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={11} />
            SHAPE
          </button>

          <button
            onClick={handleRegenTex}
            disabled={acting || !jobId}
            className="flex items-center gap-1 px-2.5 py-1.5 bg-ink-800 text-ink-100 border border-ink-700 rounded uppercase hover:bg-ink-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={11} />
            TEXTURE
          </button>
        </div>

        <button
          onClick={() => jobId && onOpenModelViewer(jobId)}
          className="px-3 py-1.5 bg-ink-850 text-ink-200 border border-ink-700 rounded uppercase font-semibold hover:text-ink-0 hover:bg-ink-800 transition-colors"
        >
          OPEN FULL 3D WORKSPACE
        </button>
      </div>
    </div>
  );
}
