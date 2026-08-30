import { CheckCircle2, AlertTriangle, Play } from 'lucide-react';
import type { TestCaseResult, TestFailure } from '@/types';

interface Props {
  jobId?: string;
  testCases?: TestCaseResult[];
  failures?: TestFailure[];
  onOpenTestPage: (jobId: string) => void;
}

export function ChatTestCard({ jobId, testCases = [], failures = [], onOpenTestPage }: Props) {
  const passed = testCases.filter((c) => c.status === 'PASSED').length;
  const failed = testCases.filter((c) => c.status === 'FAILED').length;
  const skipped = testCases.filter((c) => c.status === 'SKIPPED').length;
  const totalCases = testCases.length;

  const hasFailures = failed > 0 || failures.length > 0;
  const hasExecutedCases = totalCases > 0;

  // Truthful status determination
  let statusText = 'NOT RUN';
  let statusStyle = 'bg-ink-800 text-ink-300';

  if (hasFailures) {
    statusText = 'FAILED';
    statusStyle = 'bg-zen-err/20 text-zen-errBright';
  } else if (hasExecutedCases && passed > 0 && skipped === 0) {
    statusText = 'PASSED';
    statusStyle = 'bg-zen-ok/20 text-zen-okBright';
  } else if (hasExecutedCases && passed > 0 && skipped > 0) {
    statusText = `PASSED (${skipped} SKIPPED)`;
    statusStyle = 'bg-zen-ok/20 text-zen-okBright';
  } else if (hasExecutedCases && passed === 0 && skipped > 0) {
    statusText = 'SKIPPED';
    statusStyle = 'bg-zen-warn/20 text-zen-warnBright';
  }

  return (
    <div className="my-3 p-4 bg-ink-900/90 border border-ink-700 rounded font-mono text-2xs space-y-3 shadow-lg">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-ink-800 pb-2">
        <div className="flex items-center gap-2">
          <Play size={14} className="text-ink-200" />
          <span className="font-semibold text-xs text-ink-100">PLAY TEST RESULTS</span>
        </div>
        <span className={`px-2 py-0.5 rounded font-bold uppercase tracking-wider ${statusStyle}`}>
          {statusText}
        </span>
      </div>

      {/* Summary Counts */}
      <div className="grid grid-cols-3 gap-2 bg-ink-950 p-2.5 rounded border border-ink-800 text-center">
        <div>
          <span className="text-ink-400 text-2xs uppercase block">PASSED</span>
          <span className="text-sm font-bold text-zen-okBright">{passed}</span>
        </div>
        <div>
          <span className="text-ink-400 text-2xs uppercase block">FAILED</span>
          <span className={`text-sm font-bold ${failed > 0 || failures.length > 0 ? 'text-zen-errBright' : 'text-ink-300'}`}>
            {failed > 0 ? failed : failures.length}
          </span>
        </div>
        <div>
          <span className="text-ink-400 text-2xs uppercase block">SKIPPED</span>
          <span className="text-sm font-bold text-ink-300">{skipped}</span>
        </div>
      </div>

      {/* Failure Highlight */}
      {failures.length > 0 && (
        <div className="p-2.5 bg-zen-err/10 border border-zen-err/30 rounded text-zen-errBright space-y-1">
          <div className="flex items-center gap-1.5 font-bold">
            <AlertTriangle size={12} />
            <span>PRIMARY FAILURE:</span>
          </div>
          <p className="text-2xs leading-relaxed">{failures[0].message}</p>
          {failures[0].file && (
            <span className="text-2xs text-ink-400 block">
              Location: {failures[0].file}:{failures[0].line ?? '?'}
            </span>
          )}
        </div>
      )}

      {!hasFailures && hasExecutedCases && passed > 0 && (
        <div className="flex items-center gap-2 text-zen-okBright">
          <CheckCircle2 size={13} />
          <span>Executed QA test cases passed successfully.</span>
        </div>
      )}

      {/* Action */}
      <div className="flex justify-end pt-1">
        <button
          onClick={() => jobId && onOpenTestPage(jobId)}
          className="px-3 py-1.5 bg-ink-850 text-ink-200 border border-ink-700 rounded uppercase font-semibold hover:text-ink-0 hover:bg-ink-800 transition-colors"
        >
          VIEW TEST DETAILS
        </button>
      </div>
    </div>
  );
}
