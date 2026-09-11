import { useStore } from '@/store';
import { StatusDot } from './StatusDot';

export function TopBar() {
  const jobs = useStore((s) => s.jobs);
  const currentJobId = useStore((s) => s.currentJobId);
  const connections = useStore((s) => s.connections);
  const agents = useStore((s) => s.agents);
  const socketStatus = useStore((s) => s.socketStatus);
  const studioState = useStore((s) => s.studioState);
  const projectIdentity = useStore((s) => s.projectIdentity);

  const currentJob = jobs.find((j) => j.id === currentJobId);
  const chatgpt = agents.find((a) => a.id === 'chatgpt');

  const projectName = projectIdentity?.name.trim();
  const displayProject = projectName
    ? projectName.toUpperCase()
    : studioState === 'SELECT_REQUIRED'
      ? 'SELECT PROJECT'
      : studioState === 'CONNECTING' || studioState === 'SEARCHING' || studioState === 'ONLINE'
        ? 'DETECTING PROJECT'
        : 'NO PROJECT';

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
    <header className="h-8 shrink-0 bg-ink-900 border-b border-ink-600 flex items-center justify-between px-3 text-2xs uppercase tracking-wider">
      <div className="flex items-center gap-3">
        <span className="text-ink-300">PROJECT</span>
        <span className="text-ink-50">/</span>
        <span className="text-ink-0 font-medium">{displayProject}</span>
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
            <span className="text-ink-300">ChatGPT · Builder</span>
            <StatusDot status={chatgpt.status} />
          </span>
        )}
        <span className="flex items-center gap-1.5">
          <span className="text-ink-300">Roblox Studio</span>
          <StatusDot status={connections.studio} />
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
      </div>
    </header>
  );
}
