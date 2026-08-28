import type { ConnectionStatus } from '@/types';
import { Tooltip } from './Tooltip';

interface StatusDotProps {
  status: ConnectionStatus;
  label?: string;
  size?: 'sm' | 'md';
}

const colorMap: Record<ConnectionStatus, string> = {
  READY: 'bg-zen-okBright',
  CONNECTING: 'bg-zen-warnBright animate-pulse-soft',
  LOGIN: 'bg-zen-warnBright',
  OFF: 'bg-ink-400',
  ERR: 'bg-zen-errBright',
};

export function StatusDot({ status, label, size = 'sm' }: StatusDotProps) {
  const dot = (
    <span
      className={`inline-block ${size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2'} ${colorMap[status]} ${status === 'CONNECTING' ? 'animate-pulse-soft' : ''}`}
    />
  );
  if (label) {
    return (
      <Tooltip content={label}>
        <span className="inline-flex">{dot}</span>
      </Tooltip>
    );
  }
  return dot;
}

interface StatusBadgeProps {
  status: ConnectionStatus;
  label?: string;
}

const badgeColor: Record<ConnectionStatus, string> = {
  READY: 'text-zen-okBright border-ink-600',
  CONNECTING: 'text-zen-warnBright border-ink-600',
  LOGIN: 'text-zen-warnBright border-ink-600',
  OFF: 'text-ink-300 border-ink-600',
  ERR: 'text-zen-errBright border-ink-600',
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-1.5 py-0.5 text-2xs font-medium uppercase tracking-wide border ${badgeColor[status]}`}>
      <StatusDot status={status} />
      <span>{label ?? status}</span>
    </span>
  );
}
