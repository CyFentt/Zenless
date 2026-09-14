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
    <nav className="w-14 shrink-0 bg-ink-900 border-r border-ink-600 flex flex-col items-center py-3 gap-1">
      <div className="mb-4 flex h-8 w-8 items-center justify-center border border-ink-500 bg-ink-950">
        <span className="text-xs font-semibold tracking-[0.18em] text-ink-0 translate-x-[0.08em]">Z</span>
      </div>
      <div className="flex flex-col gap-0.5 flex-1">
        {NAV.map((item) => {
          const Icon = item.icon;
          const isActive = activePage === item.id;
          return (
            <Tooltip key={item.id} content={item.label}>
              <button
                onClick={() => setActivePage(item.id)}
                className={`zen-nav relative flex items-center justify-center w-10 h-10 ${
                  isActive
                    ? "text-ink-0 bg-ink-700"
                    : "text-ink-300 hover:text-ink-50 hover:bg-ink-800"
                }`}
                aria-label={item.label}
                aria-current={isActive ? "page" : undefined}
              >
                {isActive && <span className="absolute left-0 top-1 bottom-1 w-px bg-ink-0 animate-nav-line" />}
                <Icon size={16} strokeWidth={1.5} />
              </button>
            </Tooltip>
          );
        })}
      </div>

      <div className="pt-2 border-t border-ink-700 w-full flex justify-center">
        <Tooltip content={allReady ? "READY" : anyError ? "ERROR" : "CONNECTING"}>
          <span className="flex items-center justify-center py-2">
            <StatusDot status={allReady ? "READY" : anyError ? "ERR" : "CONNECTING"} size="md" />
          </span>
        </Tooltip>
      </div>
    </nav>
  );
}
