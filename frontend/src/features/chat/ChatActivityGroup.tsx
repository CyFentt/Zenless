import { useState } from 'react';
import { Activity, ChevronDown, ChevronRight, CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react';
import type { ChatActivity } from '@/types';

interface Props {
  activities: ChatActivity[];
  onOpenContext?: () => void;
}

export function ChatActivityGroup({ activities, onOpenContext }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (activities.length === 0) return null;

  const running = activities.filter((a) => a.status === 'RUNNING');
  const failed = activities.filter((a) => a.status === 'FAILED');
  const warning = activities.filter((a) => a.status === 'WARNING');
  const doneCount = activities.filter((a) => a.status === 'DONE').length;

  const activePhase = running.length > 0 ? running[0].phase : activities[activities.length - 1].phase;
  const activeTitle = running.length > 0 ? running[0].title : activities[activities.length - 1].title;

  return (
    <div className="my-2 bg-ink-900/90 border border-ink-700/80 rounded font-mono text-2xs overflow-hidden transition-all duration-200 hover:border-ink-600">
      {/* Summary Header */}
      <div
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between px-3 py-2 cursor-pointer bg-ink-900 hover:bg-ink-850 select-none transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <Activity size={12} className="text-ink-300 shrink-0" />
          <span className="px-1.5 py-0.5 bg-ink-800 text-ink-200 rounded font-bold tracking-wider shrink-0 uppercase">
            {activePhase}
          </span>
          <span className="text-ink-100 font-medium truncate">{activeTitle}</span>
        </div>

        <div className="flex items-center gap-2 shrink-0 ml-3">
          {running.length > 0 ? (
            <span className="flex items-center gap-1.5 text-zen-warnBright">
              <RefreshCw size={11} className="animate-spin" />
              <span>RUNNING ({doneCount}/{activities.length})</span>
            </span>
          ) : failed.length > 0 ? (
            <span className="flex items-center gap-1.5 text-zen-errBright">
              <AlertTriangle size={11} />
              <span>FAILED</span>
            </span>
          ) : warning.length > 0 ? (
            <span className="flex items-center gap-1.5 text-zen-warnBright">
              <AlertTriangle size={11} />
              <span>WARNING</span>
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-zen-okBright">
              <CheckCircle2 size={11} />
              <span>DONE ({doneCount}/{activities.length})</span>
            </span>
          )}

          {expanded ? <ChevronDown size={12} className="text-ink-400" /> : <ChevronRight size={12} className="text-ink-400" />}
        </div>
      </div>

      {/* Expanded Timeline Details */}
      {expanded && (
        <div className="border-t border-ink-800/80 p-2 space-y-1.5 bg-ink-950/60">
          {activities.map((act) => (
            <div key={act.id} className="flex items-center justify-between px-2 py-1 bg-ink-900/80 rounded border border-ink-800">
              <div className="flex items-center gap-2 min-w-0">
                {act.status === 'RUNNING' ? (
                  <RefreshCw size={10} className="text-zen-warnBright animate-spin shrink-0" />
                ) : act.status === 'DONE' ? (
                  <CheckCircle2 size={10} className="text-zen-okBright shrink-0" />
                ) : act.status === 'FAILED' ? (
                  <AlertTriangle size={10} className="text-zen-errBright shrink-0" />
                ) : (
                  <span className="w-1.5 h-1.5 bg-ink-500 rounded-full shrink-0" />
                )}
                <span className="text-ink-400 text-2xs uppercase w-16 shrink-0">{act.phase}</span>
                <span className="text-ink-100 truncate">{act.title}</span>
              </div>
              {act.detail && <span className="text-ink-400 text-2xs truncate pl-2">{act.detail}</span>}
            </div>
          ))}

          {onOpenContext && (
            <div className="pt-1 flex justify-end">
              <button
                onClick={onOpenContext}
                className="px-2 py-1 bg-ink-800 text-ink-200 border border-ink-700 rounded hover:text-ink-0 hover:bg-ink-700 transition-colors uppercase text-2xs font-semibold"
              >
                VIEW CONTEXT DETAILS
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
