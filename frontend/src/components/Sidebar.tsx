import {
  MessageSquare,
  FileCode,
  Box,
  Gamepad2,
  Play,
  ScrollText,
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
  { id: "chat", label: "CHAT", icon: MessageSquare },
  { id: "build", label: "BUILD", icon: FileCode },
  { id: "visual", label: "VISUAL", icon: Box },
  { id: "studio", label: "EDITOR", icon: Gamepad2 },
  { id: "test", label: "TEST", icon: Play },
  { id: "logs", label: "LOGS", icon: ScrollText },
];

export function Sidebar() {
  const activePage = useStore((s) => s.activePage);
  const setActivePage = useStore((s) => s.setActivePage);
  const connections = useStore((s) => s.connections);

  const allReady = connections.bridge === "READY";
  const anyError = Object.values(connections).some((v) => v === "ERR");

  return (
    <nav className="h-[30px] shrink-0 bg-[#060606] border-b border-[#1b1b1b] flex items-end px-[5px] gap-1" aria-label="Workspaces">
      <div className="flex min-w-0 gap-0.5 flex-1 overflow-x-auto scrollbar-zen">
        {NAV.map((item) => {
          const Icon = item.icon;
          const isActive = activePage === item.id;
          return (
            <Tooltip key={item.id} content={item.label}>
              <button
                onClick={() => setActivePage(item.id)}
                className={`zen-nav relative flex items-center justify-center gap-1.5 min-w-[74px] h-[24px] px-2 border border-b-0 font-mono text-[9px] font-bold tracking-wider ${
                  isActive
                    ? "text-[#f0f0f0] bg-[#0b0b0b] border-[#505050] border-t-[#d8d8d8]"
                    : "text-[#737373] bg-[#070707] border-[#202020] hover:text-[#d8d8d8] hover:border-[#383838]"
                }`}
                aria-label={item.label}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon size={11} strokeWidth={1.5} />
                <span>{item.label}</span>
              </button>
            </Tooltip>
          );
        })}
      </div>

      <div className="px-2 self-center flex justify-center">
        <Tooltip content={allReady ? "READY" : anyError ? "ERROR" : "CONNECTING"}>
          <span className="flex items-center justify-center py-2">
            <StatusDot status={allReady ? "READY" : anyError ? "ERR" : "CONNECTING"} size="md" />
          </span>
        </Tooltip>
      </div>
    </nav>
  );
}
