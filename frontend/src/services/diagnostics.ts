import type { Diagnostic, DiagnosticSeverity } from '@/types';

type DiagHandler = (diag: Diagnostic) => void;

interface DiagnosticExtra {
  component?: string;
  function?: string;
  probableCause?: string;
  impact?: string;
  recovery?: string;
  stack?: string;
  jobId?: string;
  requestId?: string;
  operationId?: string;
}

class FrontendDiagnostics {
  private handlers = new Set<DiagHandler>();
  private diags: Diagnostic[] = [];
  private fingerprints = new Map<string, string>();
  private initialized = false;

  init() {
    if (this.initialized || typeof window === 'undefined') return;
    this.initialized = true;

    window.addEventListener('error', (e: ErrorEvent) => {
      this.report('error', 'window', e.message || 'Unknown error', e.filename, e.lineno, {
        stack: e.error instanceof Error ? e.error.stack : undefined,
      });
    });

    window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
      const reason = e.reason;
      const message = reason instanceof Error ? reason.message : safeDescribe(reason);
      this.report('error', 'promise', `Unhandled rejection: ${message}`, undefined, undefined, {
        stack: reason instanceof Error ? reason.stack : undefined,
      });
    });
  }

  report(
    severity: DiagnosticSeverity,
    source: string,
    message: string,
    file?: string,
    line?: number,
    extra: DiagnosticExtra = {},
  ) {
    const fingerprint = [severity, source, message, file ?? '', line ?? '', extra.function ?? ''].join('|');
    const existingId = this.fingerprints.get(fingerprint);

    if (existingId) {
      const index = this.diags.findIndex((d) => d.id === existingId);
      if (index >= 0) {
        const current = this.diags[index];
        const updated: Diagnostic = {
          ...current,
          occurrenceCount: (current.occurrenceCount ?? 1) + 1,
          timestamp: Date.now(),
          stack: extra.stack ?? current.stack,
          requestId: extra.requestId ?? current.requestId,
          operationId: extra.operationId ?? current.operationId,
        };
        this.diags[index] = updated;
        this.handlers.forEach((handler) => handler(updated));
        return updated;
      }
    }

    const diag: Diagnostic = {
      id: `diag_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      severity,
      source,
      component: extra.component,
      message,
      file,
      line,
      function: extra.function,
      probableCause: extra.probableCause,
      impact: extra.impact,
      recovery: extra.recovery,
      stack: extra.stack,
      occurrenceCount: 1,
      jobId: extra.jobId,
      requestId: extra.requestId,
      operationId: extra.operationId,
      timestamp: Date.now(),
    };

    this.diags.push(diag);
    this.fingerprints.set(fingerprint, diag.id);
    this.handlers.forEach((handler) => handler(diag));

    const log = severity === 'critical' || severity === 'error' ? console.error : severity === 'warning' ? console.warn : console.info;
    log(`[${source}] ${message}`, extra.stack ?? '');
    return diag;
  }

  capture(error: unknown, source: string, message = 'Unexpected frontend error', extra: DiagnosticExtra = {}) {
    const err = error instanceof Error ? error : new Error(safeDescribe(error));
    return this.report('error', source, `${message}: ${err.message}`, undefined, undefined, {
      ...extra,
      stack: err.stack ?? extra.stack,
    });
  }

  on(handler: DiagHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  getAll(): Diagnostic[] {
    return [...this.diags];
  }
}

function safeDescribe(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

export const frontendDiagnostics = new FrontendDiagnostics();
