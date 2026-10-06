import { useState } from "react";
import {
  Home,
  PanelLeftClose,
  PanelLeftOpen,
  MessageSquare,
  FileCode,
  Box,
  Gamepad2,
  Play,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { useStore } from "@/store";
import { Tooltip } from "./Tooltip";
import { StatusDot } from "./StatusDot";

interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { id: "home", label: "HOME", icon: Home },
  { id: "chat", label: "CHAT", icon: MessageSquare },
  { id: "build", label: "BUILD", icon: FileCode },
  { id: "visual", label: "VISUAL", icon: Box },
  { id: "studio", label: "EDITOR", icon: Gamepad2 },
  { id: "test", label: "TEST", icon: Play },
  { id: "settings", label: "SETTINGS", icon: Settings },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const jobs = useStore((s) => s.jobs);
  const setCurrentJobId = useStore((s) => s.setCurrentJobId);
  const activePage = useStore((s) => s.activePage);
  const setActivePage = useStore((s) => s.setActivePage);
  const connections = useStore((s) => s.connections);

  const allReady = connections.bridge === "READY";
  const anyError = Object.values(connections).some((v) => v === "ERR");

  return (
    <nav aria-label="Main navigation" className={`${collapsed ? "w-[72px]" : "w-52"} shrink-0 bg-ink-900 border-r border-ink-600 flex flex-col items-center py-3 gap-1`}>
      <div className="mb-4 flex items-center justify-center min-h-9">
        {!collapsed ? (
          <span className="rubra-wordmark text-sm tracking-[0.28em] font-semibold">RUBRA</span>
        ) : (
          <span className="rubra-mark" aria-label="Rubra">R</span>
        )}
      </div>
      <button aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={() => setCollapsed(!collapsed)} className="mb-3 p-2 text-ink-100 hover:text-zen-redBright">
        {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
      </button>
      <div className="flex flex-col gap-0.5 w-full px-3">
        {NAV.map((item) => {
          const Icon = item.icon;
          const isActive = activePage === item.id;
          return (
            <Tooltip key={item.id} content={item.label}>
              <button
                onClick={() => setActivePage(item.id)}
                className={`relative flex items-center gap-3 px-3 w-full h-10 transition-colors duration-150 ${
                  isActive
                    ? "text-zen-redBright bg-zen-red/10"
                    : "text-ink-300 hover:text-ink-50 hover:bg-ink-800"
                }`}
                aria-label={item.label}
                aria-current={isActive ? "page" : undefined}
              >
                {isActive && <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-zen-redBright" />}
                <Icon size={16} strokeWidth={1.5} className="shrink-0" />
                {!collapsed && <span className="text-xs tracking-wider">{item.label}</span>}
              </button>
            </Tooltip>
          );
        })}
      </div>

      <div className="flex-1 w-full min-h-0 overflow-y-auto scrollbar-zen px-3 mt-6">
        {!collapsed && <>
          <p className="text-2xs uppercase tracking-widest text-ink-100 mb-3">Recent tasks</p>
          {jobs.slice(0, 8).map((job) => <button key={job.id} onClick={() => { setCurrentJobId(job.id); setActivePage("build"); }} className="block w-full text-left truncate py-2 text-xs text-ink-100 hover:text-ink-0" title={job.title}>{job.title}</button>)}
          {jobs.length === 0 && <p className="text-xs text-ink-150">No tasks yet</p>}
        </>}
      </div>
      <div className="pt-2 border-t border-ink-700 w-full px-3">
        <Tooltip content={allReady ? "Core bridge ready" : anyError ? "One or more connections need attention" : "Connections are still initializing"}>
          <span className={`flex items-center ${collapsed ? 'justify-center' : 'justify-between'} py-2`}>
            {!collapsed && <span className="text-2xs uppercase tracking-widest text-ink-400">System</span>}
            <span className="flex items-center gap-2">
              <StatusDot status={allReady ? "READY" : anyError ? "ERR" : "CONNECTING"} size="md" />
              {!collapsed && <span className="text-2xs uppercase tracking-wider text-ink-300">{allReady ? "READY" : anyError ? "ATTENTION" : "CONNECTING"}</span>}
            </span>
          </span>
        </Tooltip>
      </div>
    </nav>
  );
}
