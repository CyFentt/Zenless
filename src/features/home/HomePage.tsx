import { useEffect } from 'react';
import { useStore } from '@/store';
import { getApi } from '@/services';
import { StatusDot } from '@/components/StatusDot';
import { Pipeline } from '@/components/Pipeline';
import { Tooltip } from '@/components/Tooltip';

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const min = Math.floor(diff / 60000);
  if (min < 1) return 'now';
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  return `${hr}h`;
}

export function HomePage() {
  const jobs = useStore((s) => s.jobs);
  const agents = useStore((s) => s.agents);
  const connections = useStore((s) => s.connections);
  const diagnostics = useStore((s) => s.diagnostics);
  const setCurrentJobId = useStore((s) => s.setCurrentJobId);
  const setActivePage = useStore((s) => s.setActivePage);
  const currentJobId = useStore((s) => s.currentJobId);

  const currentJob = jobs.find((j) => j.status === 'RUNNING');
  const errors = diagnostics.filter((d) => d.severity === 'error');
  const recentJobs = jobs.slice(0, 5);

  return (
    <div className="h-full overflow-y-auto scrollbar-zen p-6 animate-fade-in">
      <div className="max-w-3xl space-y-8">
        {/* Current */}
        <section>
          <h2 className="text-2xs uppercase tracking-widest text-ink-300 mb-2">CURRENT</h2>
          {currentJob ? (
            <div className="flex items-baseline gap-4">
              <span className="text-lg font-medium text-ink-0">{currentJob.title}</span>
              <Pipeline stage={currentJob.stage} />
            </div>
          ) : (
            <span className="text-sm text-ink-300">—</span>
          )}
        </section>

        {/* System */}
        <section>
          <h2 className="text-2xs uppercase tracking-widest text-ink-300 mb-3">SYSTEM</h2>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 max-w-md">
            {agents.map((agent) => (
              <div key={agent.id} className="flex items-center justify-between border-b border-ink-700 pb-1">
                <span className="text-xs text-ink-100">{agent.name}</span>
                <div className="flex items-center gap-2">
                  <StatusDot status={agent.status} />
                  <span className="text-2xs uppercase tracking-wider text-ink-300">{agent.status}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Recent */}
        <section>
          <h2 className="text-2xs uppercase tracking-widest text-ink-300 mb-3">RECENT</h2>
          <div className="space-y-0">
            {recentJobs.map((job) => (
              <button
                key={job.id}
                onClick={() => { setCurrentJobId(job.id); setActivePage('build'); }}
                className="flex items-center justify-between w-full px-3 h-8 border-b border-ink-700 hover:bg-ink-850 transition-colors group"
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xs text-ink-400 font-mono">{timeAgo(job.updatedAt)}</span>
                  <span className="text-xs text-ink-100 group-hover:text-ink-0">{job.title}</span>
                </div>
                <div className="flex items-center gap-2">
                  <StatusDot
                    status={
                      job.status === 'COMPLETE' ? 'READY' :
                      job.status === 'FAILED' ? 'ERR' :
                      job.status === 'RUNNING' ? 'CONNECTING' :
                      job.status === 'PAUSED' ? 'LOGIN' : 'OFF'
                    }
                  />
                  <span className={`text-2xs uppercase tracking-wider ${
                    job.status === 'COMPLETE' ? 'text-zen-okBright' :
                    job.status === 'FAILED' ? 'text-zen-errBright' :
                    job.status === 'RUNNING' ? 'text-ink-100' : 'text-ink-400'
                  }`}>{job.status}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* Errors */}
        {errors.length > 0 && (
          <section>
            <h2 className="text-2xs uppercase tracking-widest text-zen-errBright mb-3">ERRORS</h2>
            <div className="space-y-0">
              {errors.map((err) => (
                <Tooltip key={err.id} content={`${err.file ?? 'Unknown'}:${err.line ?? '?'}`}>
                  <div className="flex items-center gap-3 px-3 h-8 border-b border-ink-700 hover:bg-ink-850 transition-colors cursor-pointer">
                    <StatusDot status="ERR" />
                    <span className="text-2xs text-ink-300 font-mono">{err.source}</span>
                    <span className="text-xs text-ink-100 truncate">{err.message}</span>
                  </div>
                </Tooltip>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
