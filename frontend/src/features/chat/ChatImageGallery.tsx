import { useState } from 'react';
import { Image, Check, RefreshCw, Maximize2, X, AlertTriangle } from 'lucide-react';
import type { ChatArtifactState, ViewTile } from '@/types';

interface Props {
  views: ViewTile[];
  conceptVersion?: number;
  state?: ChatArtifactState;
  actionable?: boolean;
  jobId?: string;
  onApproveVisual: (jobId: string) => Promise<void>;
  onRegenerateVisual: (jobId: string) => Promise<void>;
  onOpenVisualPage: (jobId: string) => void;
}

const VIEW_NAMES: ViewTile['name'][] = ['FRONT', 'BACK', 'LEFT', 'RIGHT', 'TOP', 'BOTTOM'];

export function ChatImageGallery({ views, conceptVersion = 1, state = 'GENERATING', actionable = true, jobId, onApproveVisual, onRegenerateVisual, onOpenVisualPage }: Props) {
  const [expandedImage, setExpandedImage] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [actionError, setActionError] = useState('');

  const handleApprove = async () => {
    if (!jobId || acting || !actionable) return;
    setActing(true);
    setActionError('');
    try {
      await onApproveVisual(jobId);
    } catch (error) {
      setActionError(error instanceof Error && error.message ? error.message : 'The visual could not be approved.');
    } finally {
      setActing(false);
    }
  };

  const handleRegen = async () => {
    if (!jobId || acting || !actionable) return;
    setActing(true);
    setActionError('');
    try {
      await onRegenerateVisual(jobId);
    } catch (error) {
      setActionError(error instanceof Error && error.message ? error.message : 'The visual could not be regenerated.');
    } finally {
      setActing(false);
    }
  };

  return (
    <div className="my-3 p-4 bg-ink-900/90 border border-ink-700 rounded font-mono text-2xs space-y-3 shadow-lg">
      <div className="flex items-center justify-between border-b border-ink-800 pb-2">
        <div className="flex items-center gap-2">
          <Image size={14} className="text-ink-200" />
          <span className="font-semibold text-xs text-ink-100">CONCEPT VISUAL (V{conceptVersion})</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-ink-400 text-2xs uppercase">6 ORTHOGRAPHIC VIEWS</span>
          <span className={`px-2 py-0.5 rounded font-bold uppercase ${state === 'APPROVED' ? 'bg-zen-ok/20 text-zen-okBright' : state === 'FAILED' || state === 'REJECTED' ? 'bg-zen-err/20 text-zen-errBright' : 'bg-zen-warn/20 text-zen-warnBright'}`}>{state}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 grid-rows-2 gap-1.5 bg-ink-950 p-1.5 rounded border border-ink-800">
        {VIEW_NAMES.map((name) => {
          const tile = views.find((v) => v.name === name) || { name, state: 'EMPTY' as const };
          return (
            <div
              key={name}
              onClick={() => tile.imageUrl && setExpandedImage(tile.imageUrl)}
              className="relative aspect-square bg-ink-900 border border-ink-800 rounded flex flex-col items-center justify-center overflow-hidden group cursor-pointer hover:border-ink-600 transition-colors"
            >
              <span className="absolute top-1 left-1.5 text-2xs uppercase font-bold text-ink-300 z-10">
                {name}
              </span>

              {tile.imageUrl ? (
                <img src={tile.imageUrl} alt={`${name} view`} className="w-full h-full object-contain p-1" />
              ) : (
                <span className="text-2xs text-ink-500 uppercase">{tile.state}</span>
              )}

              {tile.imageUrl && (
                <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                  <Maximize2 size={14} className="text-ink-0" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {actionError && (
        <div role="alert" className="flex items-center gap-2 px-2.5 py-2 bg-zen-err/10 border border-zen-err/30 rounded text-zen-errBright">
          <AlertTriangle size={12} />
          <span>{actionError}</span>
        </div>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="flex items-center gap-2">
          {actionable && state !== 'APPROVED' && (
            <button
              onClick={handleApprove}
              disabled={acting || !jobId}
              className="flex items-center gap-1 px-3 py-1.5 bg-zen-ok text-black rounded font-bold uppercase hover:bg-zen-okBright transition-colors disabled:opacity-50"
            >
              <Check size={12} />
              APPROVE CONCEPT
            </button>
          )}
          {actionable && (
            <button
              onClick={handleRegen}
              disabled={acting || !jobId}
              className="flex items-center gap-1 px-2.5 py-1.5 bg-ink-800 text-ink-100 border border-ink-700 rounded uppercase hover:bg-ink-700 transition-colors disabled:opacity-50"
            >
              <RefreshCw size={12} />
              REGENERATE
            </button>
          )}
        </div>

        <button
          onClick={() => jobId && onOpenVisualPage(jobId)}
          className="px-3 py-1.5 bg-ink-850 text-ink-200 border border-ink-700 rounded uppercase font-semibold hover:text-ink-0 hover:bg-ink-800 transition-colors"
        >
          OPEN VISUAL WORKSPACE
        </button>
      </div>

      {expandedImage && (
        <div
          onClick={() => setExpandedImage(null)}
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4 animate-fade-in"
        >
          <div className="relative max-w-2xl max-h-[80vh] bg-ink-950 p-2 border border-ink-700 rounded">
            <button
              onClick={() => setExpandedImage(null)}
              className="absolute top-3 right-3 text-ink-300 hover:text-ink-0"
            >
              <X size={16} />
            </button>
            <img src={expandedImage} alt="Expanded preview" className="max-w-full max-h-[75vh] object-contain" />
          </div>
        </div>
      )}
    </div>
  );
}
