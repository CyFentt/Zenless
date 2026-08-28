import type { Diagnostic } from '@/types';

type DiagHandler = (diag: Diagnostic) => void;

class FrontendDiagnostics {
  private handlers = new Set<DiagHandler>();
  private diags: Diagnostic[] = [];

  init() {
    window.addEventListener('error', (e: ErrorEvent) => {
      this.report('error', 'window', e.message || 'Unknown error', e.filename, e.lineno);
    });
    window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
      const msg = e.reason instanceof Error ? e.reason.message : String(e.reason);
      this.report('error', 'promise', `Unhandled rejection: ${msg}`);
    });
  }

  report(severity: Diagnostic['severity'], source: string, message: string, file?: string, line?: number) {
    const diag: Diagnostic = {
      id: `diag_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      severity,
      source,
      message,
      file,
      line,
      timestamp: Date.now(),
    };
    this.diags.push(diag);
    this.handlers.forEach((h) => h(diag));
    // eslint-disable-next-line no-console
    console.error(`[${source}] ${message}`);
  }

  on(handler: DiagHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  getAll(): Diagnostic[] {
    return [...this.diags];
  }
}

export const frontendDiagnostics = new FrontendDiagnostics();
