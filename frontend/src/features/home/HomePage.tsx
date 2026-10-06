import { useStore } from "@/store";
import { StatusDot } from "@/components/StatusDot";
import { Pipeline } from "@/components/Pipeline";
import { Tooltip } from "@/components/Tooltip";
import type { AgentId } from "@/types";

const AGENT_LABELS: Record<AgentId, string> = {
  chatgpt: "Builder",
  deepseek: "Reviewer",
  gemini: "Research",
  hunyuan: "3D Generator",
  studio: "Editor",
};

function displaySource(source: string): string {
  return AGENT_LABELS[source.toLowerCase() as AgentId] ?? source;
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "now";
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  return `${hr}h`;
}

export function HomePage() {
  const jobs = useStore((s) => s.jobs);
  const agents = useStore((s) => s.agents);
  const diagnostics = useStore((s) => s.diagnostics);
  const setCurrentJobId = useStore((s) => s.setCurrentJobId);
  const setActivePage = useStore((s) => s.setActivePage);

  const currentJob = jobs.find(
    (j) => j.status === "NEW" || j.status === "RUNNING" || j.status === "PAUSED",
  );
  const alerts = diagnostics
    .filter((d) => d.severity === "critical" || d.severity === "error" || d.severity === "warning")
    .slice(-8)
    .reverse();
  const recentJobs = jobs.slice(0, 5);

  return (
    <div className="h-full overflow-y-auto scrollbar-zen p-6 animate-fade-in">
      <div className="max-w-3xl space-y-8">
        <section>
          <h2 className="text-2xs uppercase tracking-widest text-ink-300 mb-2">CURRENT</h2>
          {currentJob ? (
            <div className="flex items-baseline gap-4">
              <span className="text-lg font-medium text-ink-0">{currentJob.title}</span>
              <Pipeline stage={currentJob.stage} />
            </div>
          ) : (
            <div className="border border-ink-600 bg-ink-900 p-5 space-y-3">
              <p className="text-sm text-ink-50">Ready for your next Roblox project.</p>
              <p className="text-xs text-ink-300">Open a place in Studio to explore its scripts or run a Play Test. Describe what you want to build in the chat.</p>
              <div className="flex gap-3">
                <button onClick={() => setActivePage('chat')} className="px-3 py-2 bg-zen-red text-white text-xs">Start building</button>
                <button onClick={() => setActivePage('studio')} className="px-3 py-2 border border-ink-500 text-ink-50 text-xs">Open editor</button>
              </div>
            </div>
          )}
        </section>

        <section>
          <h2 className="text-2xs uppercase tracking-widest text-ink-300 mb-3">SYSTEM</h2>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2 max-w-md">
            {agents.map((agent) => (
              <div
                key={agent.id}
                className="flex items-center justify-between border-b border-ink-700 pb-1"
              >
                <span className="text-xs text-ink-100">{displaySource(agent.id)}</span>
                <div className="flex items-center gap-2">
                  <StatusDot status={agent.status} />
                  <span className="text-2xs uppercase tracking-wider text-ink-300">
                    {agent.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-2xs uppercase tracking-widest text-ink-300 mb-3">RECENT</h2>
          <div className="space-y-0">
            {recentJobs.map((job) => (
              <button
                key={job.id}
                onClick={() => {
                  setCurrentJobId(job.id);
                  setActivePage("build");
                }}
                className="flex items-center justify-between w-full px-3 h-8 border-b border-ink-700 hover:bg-ink-850 transition-colors group"
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xs text-ink-400 font-mono">{timeAgo(job.updatedAt)}</span>
                  <span className="text-xs text-ink-100 group-hover:text-ink-0">{job.title}</span>
                </div>
                <div className="flex items-center gap-2">
                  <StatusDot
                    status={
                      job.status === "COMPLETE"
                        ? "READY"
                        : job.status === "FAILED"
                          ? "ERR"
                          : job.status === "RUNNING"
                            ? "CONNECTING"
                            : job.status === "PAUSED"
                              ? "LOGIN"
                              : "OFF"
                    }
                  />
                  <span
                    className={`text-2xs uppercase tracking-wider ${
                      job.status === "COMPLETE"
                        ? "text-zen-okBright"
                        : job.status === "FAILED"
                          ? "text-zen-errBright"
                          : job.status === "RUNNING"
                            ? "text-ink-100"
                            : "text-ink-400"
                    }`}
                  >
                    {job.status}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </section>

        {alerts.length > 0 && (
          <section>
            <h2 className="text-2xs uppercase tracking-widest text-zen-errBright mb-3">DIAGNOSTICS</h2>
            <div className="space-y-0">
              {alerts.map((diagnostic) => {
                const severe = diagnostic.severity === "critical" || diagnostic.severity === "error";
                const detail = [
                  diagnostic.probableCause ? `Cause: ${diagnostic.probableCause}` : "",
                  diagnostic.impact ? `Impact: ${diagnostic.impact}` : "",
                  diagnostic.recovery ? `Recovery: ${diagnostic.recovery}` : "",
                  diagnostic.file ? `${diagnostic.file}:${diagnostic.line ?? "?"}` : "",
                ].filter(Boolean).join("\n");
                return (
                  <Tooltip key={diagnostic.id} content={detail || diagnostic.message}>
                    <div className="flex items-center gap-3 px-3 min-h-8 py-1 border-b border-ink-700 hover:bg-ink-850 transition-colors cursor-pointer">
                      <StatusDot status={severe ? "ERR" : "LOGIN"} />
                      <span className="text-2xs text-ink-300 font-mono">{displaySource(diagnostic.source)}</span>
                      <span className="text-xs text-ink-100 truncate flex-1">{diagnostic.message}</span>
                      {(diagnostic.occurrenceCount ?? 1) > 1 && <span className="text-2xs text-ink-400">×{diagnostic.occurrenceCount}</span>}
                    </div>
                  </Tooltip>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
