import type { ConnectionStatus } from '@/types';
import { Tooltip } from './Tooltip';

interface StatusDotProps {
  status: ConnectionStatus;
  label?: string;
  size?: 'sm' | 'md';
}

const colorMap: Record<ConnectionStatus, string> = {
  READY: 'bg-ink-0',
  CONNECTING: 'bg-ink-100 animate-pulse-soft',
  LOGIN: 'bg-ink-200',
  OFF: 'bg-ink-400',
  ERR: 'bg-ink-50 ring-1 ring-ink-200',
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
  READY: 'text-ink-0 border-ink-600',
  CONNECTING: 'text-ink-100 border-ink-600',
  LOGIN: 'text-ink-200 border-ink-600',
  OFF: 'text-ink-300 border-ink-600',
  ERR: 'text-ink-25 border-ink-400',
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-1.5 py-0.5 text-2xs font-medium uppercase tracking-wide border ${badgeColor[status]}`}>
      <StatusDot status={status} />
      <span>{label ?? status}</span>
    </span>
  );
}
