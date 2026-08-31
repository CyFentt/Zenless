import { AlertOctagon, RefreshCw, KeyRound, Settings } from 'lucide-react';
import type { ProviderId } from '@/types';

interface Props {
  source?: string;
  message: string;
  detail?: string;
  providerLogin?: ProviderId;
  onLogin?: (provider: ProviderId) => Promise<void>;
  onRetry?: () => void;
  onOpenSettings?: () => void;
}

export function ChatErrorCard({ source, message, detail, providerLogin, onLogin, onRetry, onOpenSettings }: Props) {
  return (
    <div className="my-3 p-4 bg-zen-err/10 border border-zen-err/40 rounded font-mono text-2xs space-y-3 shadow-lg">
      <div className="flex items-center justify-between border-b border-zen-err/30 pb-2">
        <div className="flex items-center gap-2 text-zen-errBright font-bold">
          <AlertOctagon size={14} />
          <span className="uppercase">{source || 'ACTION REQUIRED'}</span>
        </div>
        <span className="text-2xs text-zen-errBright/80 uppercase">ERROR</span>
      </div>

      <div className="space-y-1 text-ink-100">
        <p className="font-semibold text-xs text-zen-errBright">{message}</p>
        {detail && <p className="text-2xs text-ink-300">{detail}</p>}
      </div>

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="flex items-center gap-2">
          {providerLogin && onLogin && (
            <button
              onClick={() => onLogin(providerLogin)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-zen-err text-white rounded font-bold uppercase hover:bg-zen-errBright transition-colors"
            >
              <KeyRound size={12} />
              LOGIN TO {providerLogin.toUpperCase()}
            </button>
          )}

          {onRetry && (
            <button
              onClick={onRetry}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-ink-800 text-ink-100 border border-ink-700 rounded font-semibold uppercase hover:bg-ink-700 transition-colors"
            >
              <RefreshCw size={11} />
              RETRY
            </button>
          )}
        </div>

        {onOpenSettings && (
          <button
            onClick={onOpenSettings}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-ink-850 text-ink-200 border border-ink-700 rounded uppercase hover:text-ink-0 hover:bg-ink-800 transition-colors"
          >
            <Settings size={12} />
            SETTINGS & LOGS
          </button>
        )}
      </div>
    </div>
  );
}
