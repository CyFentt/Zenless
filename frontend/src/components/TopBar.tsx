import { useStore } from '@/store';
import { Minus, Square, X } from 'lucide-react';
import { StatusDot } from './StatusDot';

export function TopBar() {
  const projectRoot = useStore((s) => s.settings?.projectRoot);
  const studioProjectName = useStore((s) => s.studioProjectName);
  const projectName = studioProjectName || projectRoot?.split(/[\\/]/).filter(Boolean).pop() || "Open Roblox Studio";
  const jobs = useStore((s) => s.jobs);
  const currentJobId = useStore((s) => s.currentJobId);
  const connections = useStore((s) => s.connections);
  const agents = useStore((s) => s.agents);
  const socketStatus = useStore((s) => s.socketStatus);

  const currentJob = jobs.find((j) => j.id === currentJobId);
  const chatgpt = agents.find((a) => a.id === 'chatgpt');
  const studioStatus = connections.studio;

  const stageLabels: Record<string, string> = {
    COLLECTING_CONTEXT: 'CONTEXT',
    PLANNING: 'PLAN',
    BUILDING: 'BUILD',
    REVIEWING: 'REVIEW',
    TESTING: 'TEST',
    COMPLETE: 'DONE',
    FAILED: 'FAIL',
    PAUSED: 'PAUSE',
    BLOCKED: 'BLOCK',
  };

  return (
    <header className="h-12 shrink-0 bg-ink-900 border-b border-ink-600 flex items-center justify-between px-3 text-2xs uppercase tracking-wider">
      <div className="pywebview-drag-region flex-1 self-stretch flex items-center gap-3 min-w-0" onDoubleClick={() => void window.pywebview?.api?.toggle_maximize?.()}>
        <span className="text-ink-300">PROJECT</span>
        <span className="text-ink-50">/</span>
        <span className="text-ink-0 font-medium">{projectName}</span>
        {currentJob && (
          <>
            <span className="text-ink-600">·</span>
            <span className="text-ink-300">{currentJob.title.toUpperCase()}</span>
            <span className="text-ink-600">·</span>
            <span className="text-ink-100">{stageLabels[currentJob.stage] ?? currentJob.stage}</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-4">
        {chatgpt && (
          <span className="flex items-center gap-1.5">
            <span className="text-ink-300">Builder</span>
            <StatusDot status={chatgpt.status} />
          </span>
        )}
        <span className="flex items-center gap-1.5">
          <span className="text-ink-300">Studio</span>
          <StatusDot status={studioStatus} />
        </span>
        <span className="flex items-center gap-1.5">
          <span className="text-ink-300">WS</span>
          <StatusDot
            status={
              socketStatus === 'CONNECTED' ? 'READY' :
              socketStatus === 'CONNECTING' ? 'CONNECTING' :
              socketStatus === 'RECONNECTING' ? 'CONNECTING' : 'OFF'
            }
          />
        </span>
        <div className="flex items-center ml-2">
          <button aria-label="Minimize window" onClick={() => void window.pywebview?.api?.minimize_window?.()} className="w-10 h-10 flex items-center justify-center hover:bg-ink-800"><Minus size={14} /></button>
          <button aria-label="Maximize or restore window" onClick={() => void window.pywebview?.api?.toggle_maximize?.()} className="w-10 h-10 flex items-center justify-center hover:bg-ink-800"><Square size={12} /></button>
          <button aria-label="Close window" onClick={() => void window.pywebview?.api?.close_window?.()} className="w-10 h-10 flex items-center justify-center hover:bg-zen-red hover:text-white"><X size={16} /></button>
        </div>
      </div>
    </header>
  );
}
