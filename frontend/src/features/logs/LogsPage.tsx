import { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { StatusDot } from '@/components/StatusDot';
import { useStore } from '@/store';
import type { Diagnostic } from '@/types';

export function LogsPage() {
  const diagnostics = useStore((state) => state.diagnostics);
  const navigationTarget = useStore((state) => state.navigationTarget);
  const setNavigationTarget = useStore((state) => state.setNavigationTarget);
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (navigationTarget?.page === 'logs' || navigationTarget?.page === 'settings') setNavigationTarget(null);
  }, [navigationTarget, setNavigationTarget]);

  const visible = useMemo(() => {
    const value = query.trim().toLocaleLowerCase();
    if (!value) return diagnostics;
    return diagnostics.filter((diagnostic) => [
      diagnostic.source,
      diagnostic.component,
      diagnostic.message,
      diagnostic.file,
      diagnostic.probableCause,
    ].some((field) => field?.toLocaleLowerCase().includes(value)));
  }, [diagnostics, query]);

  return (
    <div className="flex h-full flex-col animate-page-in">
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-ink-600 px-4">
        <span className="text-2xs uppercase tracking-[0.24em] text-ink-0">Logs</span>
        <label className="flex h-7 w-56 items-center gap-2 border border-ink-650 bg-ink-850 px-2 transition-colors focus-within:border-ink-300">
          <Search size={11} className="text-ink-300" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter" className="min-w-0 flex-1 bg-transparent text-2xs text-ink-25 placeholder:text-ink-400" />
        </label>
      </header>
      <div className="flex-1 overflow-y-auto scrollbar-zen">
        <div className="mx-auto max-w-4xl p-4">
          {visible.length === 0 ? (
            <div className="py-20 text-center text-2xs uppercase tracking-wider text-ink-400">No diagnostics</div>
          ) : visible.map((diagnostic) => <DiagnosticRow key={diagnostic.id} diagnostic={diagnostic} />)}
        </div>
      </div>
    </div>
  );
}

function DiagnosticRow({ diagnostic }: { diagnostic: Diagnostic }) {
  const [open, setOpen] = useState(false);
  const status = diagnostic.severity === 'critical' || diagnostic.severity === 'error' ? 'ERR' : diagnostic.severity === 'warning' ? 'LOGIN' : 'READY';
  return (
    <button onClick={() => setOpen((value) => !value)} className="zen-row block w-full border-b border-ink-700 px-2 py-2.5 text-left">
      <div className="flex items-start gap-3">
        <StatusDot status={status} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-2xs uppercase tracking-wider text-ink-300">{diagnostic.source}</span>
            {diagnostic.file && <span className="truncate text-2xs font-mono text-ink-400">{diagnostic.file}:{diagnostic.line ?? ''}</span>}
            {(diagnostic.occurrenceCount ?? 1) > 1 && <span className="text-2xs text-ink-400">×{diagnostic.occurrenceCount}</span>}
          </div>
          <p className="mt-0.5 truncate text-xs text-ink-100">{diagnostic.message}</p>
          {open && (
            <div className="mt-2 space-y-1 whitespace-pre-wrap text-2xs font-mono text-ink-300 animate-reveal">
              {diagnostic.function && <div>fn: {diagnostic.function}</div>}
              {diagnostic.probableCause && <div>cause: {diagnostic.probableCause}</div>}
              {diagnostic.impact && <div>impact: {diagnostic.impact}</div>}
              {diagnostic.recovery && <div>recovery: {diagnostic.recovery}</div>}
              {diagnostic.stack && <div className="text-ink-400">{diagnostic.stack}</div>}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}
