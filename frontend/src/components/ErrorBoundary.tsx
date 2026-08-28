import { Component, type ReactNode } from 'react';
import { frontendDiagnostics } from '@/services/diagnostics';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    frontendDiagnostics.report('error', 'react', `${error.message}\n${info.componentStack}`);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-screen bg-ink-950 text-ink-150 gap-3">
          <span className="text-xs uppercase tracking-widest text-zen-errBright">Fatal Error</span>
          <span className="text-xs text-ink-300 max-w-md text-center font-mono">{this.state.message}</span>
          <button
            onClick={() => window.location.reload()}
            className="mt-2 px-3 h-7 text-xs text-ink-0 border border-ink-500 hover:bg-ink-700 transition-colors"
          >
            RELOAD
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
