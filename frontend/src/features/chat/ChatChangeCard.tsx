import { useState } from 'react';
import { FileCode, Check, X, ShieldAlert, AlertTriangle, CheckCircle2, MessageSquare } from 'lucide-react';
import type { ChatArtifact } from '@/types';

interface Props {
  artifact: ChatArtifact;
  onApprove: (jobId: string) => Promise<void>;
  onReject: (jobId: string) => Promise<void>;
  onRequestRevision: (jobId: string, feedback: string) => Promise<void>;
  onOpenDiff: (jobId: string) => void;
}

export function ChatChangeCard({ artifact, onApprove, onReject, onRequestRevision, onOpenDiff }: Props) {
  const [acting, setActing] = useState(false);
  const [showRevisionInput, setShowRevisionInput] = useState(false);
  const [revisionFeedback, setRevisionFeedback] = useState('');

  const jobId = artifact.jobId ?? '';
  const metadata = artifact.metadata || {};
  const risk = metadata.risk ? String(metadata.risk).toUpperCase() : null;
  const fileCount = metadata.fileCount !== undefined ? Number(metadata.fileCount) : null;
  const reviewer = metadata.reviewer ? String(metadata.reviewer) : null;
  const decision = metadata.decision ? String(metadata.decision).toUpperCase() : null;

  const handleApprove = async () => {
    if (!jobId || acting) return;
    setActing(true);
    try {
      await onApprove(jobId);
    } finally {
      setActing(false);
    }
  };

  const handleReject = async () => {
    if (!jobId || acting) return;
    setActing(true);
    try {
      await onReject(jobId);
    } finally {
      setActing(false);
    }
  };

  const handleSubmitRevision = async () => {
    if (!jobId || !revisionFeedback.trim() || acting) return;
    setActing(true);
    try {
      await onRequestRevision(jobId, revisionFeedback.trim());
      setShowRevisionInput(false);
      setRevisionFeedback('');
    } finally {
      setActing(false);
    }
  };

  return (
    <div className="my-3 p-4 bg-ink-900/90 border border-ink-700 rounded font-mono text-2xs space-y-3 shadow-lg">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-ink-800 pb-2">
        <div className="flex items-center gap-2">
          <FileCode size={14} className="text-ink-200" />
          <span className="font-semibold text-xs text-ink-100">{artifact.name || 'CODE CHANGES READY'}</span>
        </div>
        <span
          className={`px-2 py-0.5 rounded font-bold uppercase tracking-wider ${
            artifact.state === 'APPROVED'
              ? 'bg-zen-ok/20 text-zen-okBright'
              : artifact.state === 'REJECTED' || artifact.state === 'FAILED'
                ? 'bg-zen-err/20 text-zen-errBright'
                : 'bg-zen-warn/20 text-zen-warnBright'
          }`}
        >
          {artifact.state}
        </span>
      </div>

      {/* Review & Stats Summary */}
      <div className="grid grid-cols-2 gap-3 bg-ink-950/80 p-3 rounded border border-ink-800">
        <div>
          <span className="text-ink-400 text-2xs uppercase block mb-1">INDEPENDENT REVIEW</span>
          <div className="flex items-center gap-2">
            {decision === 'APPROVE' ? (
              <CheckCircle2 size={13} className="text-zen-okBright" />
            ) : decision === 'BLOCK' ? (
              <ShieldAlert size={13} className="text-zen-errBright" />
            ) : decision === 'REVISE' ? (
              <AlertTriangle size={13} className="text-zen-warnBright" />
            ) : null}
            <span className="text-ink-100 font-bold">{decision || 'PENDING'}</span>
            {reviewer && <span className="text-ink-400 text-2xs">({reviewer})</span>}
          </div>
        </div>

        <div>
          <span className="text-ink-400 text-2xs uppercase block mb-1">RISK & IMPACT</span>
          <div className="flex items-center gap-2">
            {risk ? (
              <span
                className={`px-1.5 py-0.5 rounded font-bold uppercase ${
                  risk === 'LOW'
                    ? 'bg-zen-ok/20 text-zen-okBright'
                    : risk === 'CRITICAL' || risk === 'HIGH'
                      ? 'bg-zen-err/20 text-zen-errBright'
                      : 'bg-zen-warn/20 text-zen-warnBright'
                }`}
              >
                {risk} RISK
              </span>
            ) : (
              <span className="text-ink-400 text-2xs">UNASSESSED</span>
            )}
            {fileCount !== null && <span className="text-ink-300">{fileCount} files modified</span>}
          </div>
        </div>
      </div>

      {/* Revision Form */}
      {showRevisionInput && (
        <div className="space-y-2 p-2.5 bg-ink-950 border border-ink-700 rounded">
          <span className="text-ink-300 text-2xs uppercase font-semibold">REQUEST REVISION FEEDBACK</span>
          <textarea
            value={revisionFeedback}
            onChange={(e) => setRevisionFeedback(e.target.value)}
            placeholder="Describe requested code changes (e.g. adjust explosion blast radius logic)..."
            rows={3}
            className="w-full bg-ink-900 text-ink-100 border border-ink-700 p-2 text-2xs rounded focus:outline-none focus:border-ink-500 resize-none"
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setShowRevisionInput(false)}
              disabled={acting}
              className="px-2.5 py-1 bg-ink-800 text-ink-300 rounded uppercase hover:text-ink-100"
            >
              CANCEL
            </button>
            <button
              onClick={handleSubmitRevision}
              disabled={acting || !revisionFeedback.trim()}
              className="px-2.5 py-1 bg-ink-700 text-ink-0 border border-ink-500 rounded uppercase font-semibold hover:bg-ink-600 disabled:opacity-50"
            >
              SUBMIT REVISION
            </button>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div className="flex items-center gap-2">
          {artifact.state !== 'APPROVED' && (
            <button
              onClick={handleApprove}
              disabled={acting}
              className="flex items-center gap-1 px-3 py-1.5 bg-zen-ok text-black rounded font-bold uppercase hover:bg-zen-okBright transition-colors disabled:opacity-50"
            >
              <Check size={12} />
              APPROVE
            </button>
          )}

          <button
            onClick={() => setShowRevisionInput(!showRevisionInput)}
            disabled={acting}
            className="flex items-center gap-1 px-2.5 py-1.5 bg-ink-800 text-ink-100 border border-ink-700 rounded uppercase hover:bg-ink-700 transition-colors"
          >
            <MessageSquare size={12} />
            REQUEST CHANGES
          </button>

          {artifact.state !== 'REJECTED' && artifact.state !== 'APPROVED' && (
            <button
              onClick={handleReject}
              disabled={acting}
              className="flex items-center gap-1 px-2.5 py-1.5 bg-zen-err/20 text-zen-errBright border border-zen-err/40 rounded uppercase hover:bg-zen-err/30 transition-colors disabled:opacity-50"
            >
              <X size={12} />
              REJECT
            </button>
          )}
        </div>

        <button
          onClick={() => jobId && onOpenDiff(jobId)}
          className="px-3 py-1.5 bg-ink-850 text-ink-200 border border-ink-700 rounded uppercase font-semibold hover:text-ink-0 hover:bg-ink-800 transition-colors"
        >
          VIEW FULL DIFF
        </button>
      </div>
    </div>
  );
}
