# Rubra 2.1.0 validation

| Check | Result |
| --- | --- |
| Python suite | 153 passed, 1 Windows-only test skipped; 4 subtests passed |
| Frontend unit suite | 70 passed |
| Chromium E2E suite | 14 passed |
| Ruff / Pyright | Passed |
| ESLint / TypeScript | Passed |
| Production frontend | Built successfully |

## Regression coverage

The new backend regressions cover late Studio discovery and consumer rebinding, project changes, structured tree parsing and script reads, invalid responses, multiple-place rejection, refresh contention, standalone Play task persistence, active-build exclusion, actual QA Start/Stop calls through a test adapter, cancellation, local routing and task-scoped attachments, login guest rejection and closure, independent provider dispatch, strict authentication confirmation, completion continuation, model unloading, and live HTTP responsiveness during a blocked MCP call.

Chromium tests exercise settings at 1000 × 650 and 1420 × 880, tooltip viewport bounds, Play without a build task, editor identity and tree, actionable Home state, native control dispatch, single-icon branding, account/composer evidence for all four provider adapters, model discovery, chat process updates, error notifications, and reduced-motion behavior. A unit regression checks that a delayed startup snapshot cannot overwrite a newer Studio connection and tree. These tests use local fixtures, not signed-in web sessions.

Existing property-based schema tests run 250 examples each. Existing transport tests use real Python child processes and concurrent requests. Existing HTTP tests use authenticated loopback requests, WebSocket events, streamed bodies, operation identity, and malformed input.

## Remaining validation

The environment is Linux. Native Windows/WebView2 execution, real provider authentication, Roblox Studio integration, and inference with the downloaded production weights are not verified here. One native WebView2 test is skipped for that reason. Packaging verification checks dependency versions, x64 PE binaries, clean source identity, and absence of user data; it does not prove native execution.
