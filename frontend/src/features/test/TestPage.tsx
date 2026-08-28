import { useEffect, useState, useRef } from 'react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { frontendDiagnostics } from '@/services/diagnostics';
import { Segmented } from '@/components/Tabs';
import { Modal } from '@/components/Modal';
import { Play, Square } from 'lucide-react';
import type { TestLog, LogLevel } from '@/types';

const FILTERS = ['ALL', 'ERR', 'WARN', 'ZEN', 'SRV', 'CLI'] as const;

export function TestPage() {
  const testState = useStore((s) => s.testState);
  const testLogs = useStore((s) => s.testLogs);
  const testCases = useStore((s) => s.testCases);
  const logFilter = useStore((s) => s.logFilter);
  const setLogFilter = useStore((s) => s.setLogFilter);
  const setTestState = useStore((s) => s.setTestState);
  const setTestLogs = useStore((s) => s.setTestLogs);
  const resetTestDetails = useStore((s) => s.resetTestDetails);
  const currentJobId = useStore((s) => s.currentJobId);
  const [elapsed, setElapsed] = useState(0);
  const [selectedLog, setSelectedLog] = useState<TestLog | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!currentJobId) { setTestState({ status: 'IDLE', elapsedMs: 0, fixAttempt: 0, maxFixAttempts: 3 }); return; }
    getApi().getTestState(currentJobId).then(setTestState).catch((error) => frontendDiagnostics.capture(error, 'test', 'Failed to load test state'));
  }, [currentJobId, setTestState]);

  useEffect(() => {
    if (testState.status === 'RUNNING') {
      const startTime = Date.now() - elapsed;
      timerRef.current = setInterval(() => {
        setElapsed(Date.now() - startTime);
      }, 100);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testState.status]);

  const handlePlay = async () => {
    if (!currentJobId) { frontendDiagnostics.report('warning', 'test', 'No active job'); return; }
    try {
      setTestLogs([]); resetTestDetails(); setElapsed(0); setTestState({ ...testState, status: 'STARTING' });
      await getApi().startTest(currentJobId);
      setTestState({ ...testState, status: 'RUNNING' });
    } catch (error) { frontendDiagnostics.capture(error, 'test', 'Failed to start Play Test'); setTestState({ ...testState, status: 'FAILED' }); }
  };

  const handleStop = async () => {
    if (!currentJobId) return;
    try { setTestState({ ...testState, status: 'STOPPING' }); await getApi().stopTest(currentJobId); setTestState({ ...testState, status: 'STOPPED' }); }
    catch (error) { frontendDiagnostics.capture(error, 'test', 'Failed to stop Play Test'); setTestState({ ...testState, status: 'FAILED' }); }
  };

  const filteredLogs = logFilter === 'ALL' ? testLogs : testLogs.filter((l) => l.level === logFilter);
  const passedCases = testCases.filter((testCase) => testCase.status === 'PASSED').length;

  const formatTime = (ms: number) => {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
  };

  const formatLogTime = (ts: number) => new Date(ts).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

  const levelColor: Record<LogLevel, string> = {
    ERR: 'text-zen-errBright',
    WARN: 'text-zen-warnBright',
    ZEN: 'text-ink-50',
    SRV: 'text-ink-100',
    CLI: 'text-ink-150',
  };

  return (
    <div className="flex flex-col h-full">
      {/* Controls */}
      <div className="flex items-center justify-between px-3 h-9 border-b border-ink-600 shrink-0">
        <div className="flex items-center gap-3">
          {testState.status === 'RUNNING' ? (
            <button onClick={handleStop} className="flex items-center gap-1.5 px-2.5 h-7 text-2xs uppercase tracking-wider text-zen-errBright border border-ink-600 hover:bg-ink-800 transition-colors">
              <Square size={10} /> STOP
            </button>
          ) : (
            <button onClick={handlePlay} className="flex items-center gap-1.5 px-2.5 h-7 text-2xs uppercase tracking-wider text-zen-okBright border border-ink-600 hover:bg-ink-800 transition-colors">
              <Play size={10} /> PLAY
            </button>
          )}
          <span className={`text-2xs uppercase tracking-wider ${testState.status === 'RUNNING' ? 'text-zen-okBright' : testState.status === 'FAILED' ? 'text-zen-errBright' : 'text-ink-400'}`}>
            {testState.status}
          </span>
          {testState.status === 'RUNNING' && (
            <span className="text-2xs font-mono text-ink-100">{formatTime(elapsed)}</span>
          )}
          {testState.fixAttempt > 0 && (
            <span className="text-2xs text-zen-warnBright font-mono">FIX {testState.fixAttempt}/{testState.maxFixAttempts}</span>
          )}
          {testCases.length > 0 && (
            <span className="text-2xs text-ink-300 font-mono">CASES {passedCases}/{testCases.length}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Segmented
            options={FILTERS.map((f) => ({ id: f, label: f }))}
            active={logFilter}
            onChange={(f) => setLogFilter(f)}
          />
        </div>
      </div>

      {/* Logs */}
      <div className="flex-1 overflow-y-auto scrollbar-zen bg-ink-950 font-mono">
        {filteredLogs.length === 0 ? (
          <div className="flex items-center justify-center h-full text-2xs text-ink-400 uppercase tracking-wider">No logs</div>
        ) : (
          <div className="py-1">
            {filteredLogs.map((log) => (
              <button
                key={log.id}
                onClick={() => log.level === 'ERR' && setSelectedLog(log)}
                className={`flex items-start w-full px-3 py-0.5 text-2xs leading-relaxed hover:bg-ink-900 transition-colors text-left ${log.level === 'ERR' ? 'cursor-pointer' : 'cursor-default'}`}
              >
                <span className="text-ink-500 shrink-0 w-20">{formatLogTime(log.timestamp)}</span>
                <span className={`shrink-0 w-12 ${levelColor[log.level]}`}>{log.level}</span>
                <span className="text-ink-100 truncate">
                  {log.file && <span className="text-ink-300">{log.file}{log.line ? `:${log.line}` : ''} </span>}
                  {log.message}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Error detail modal */}
      <Modal open={!!selectedLog} onClose={() => setSelectedLog(null)} title="ERROR DETAIL" width="w-lg">
        {selectedLog && (
          <div className="space-y-3">
            <div>
              <span className="text-2xs uppercase tracking-wider text-ink-300">MESSAGE</span>
              <p className="text-xs text-ink-50 mt-1">{selectedLog.message}</p>
            </div>
            {selectedLog.file && (
              <DetailRow label="FILE" value={`${selectedLog.file}:${selectedLog.line ?? ''}`} />
            )}
            {selectedLog.testCaseId && <DetailRow label="TEST CASE" value={selectedLog.testCaseId} />}
            {selectedLog.suite && <DetailRow label="SUITE" value={selectedLog.suite} />}
            {selectedLog.expected !== undefined && <DetailRow label="EXPECTED" value={formatDetail(selectedLog.expected)} />}
            {selectedLog.actual !== undefined && <DetailRow label="ACTUAL" value={formatDetail(selectedLog.actual)} />}
            {selectedLog.stack && (
              <div>
                <span className="text-2xs uppercase tracking-wider text-ink-300">STACK</span>
                <pre className="mt-1 p-2 bg-ink-950 border border-ink-700 text-2xs text-ink-100 overflow-x-auto scrollbar-zen">{selectedLog.stack}</pre>
              </div>
            )}
            {selectedLog.cause && <DetailRow label="CAUSE" value={selectedLog.cause} />}
            {selectedLog.recovery && <DetailRow label="RECOVERY" value={selectedLog.recovery} />}
          </div>
        )}
      </Modal>
    </div>
  );
}

function formatDetail(value: unknown): string {
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); }
  catch { return String(value); }
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-2xs uppercase tracking-wider text-ink-300">{label}</span>
      <p className="text-xs text-ink-50 mt-1 font-mono">{value}</p>
    </div>
  );
}
