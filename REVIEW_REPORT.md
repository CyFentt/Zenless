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
## Final 2.1.2 hardening continuation

The continuation review closed the remaining pre-release failure paths that were not covered by the earlier validation pass:

- Static Roblox quality subprocesses now stop the pipeline immediately when cancellation is signalled, kill on deadline expiry, and do not leak a second TimeoutExpired after forced cleanup.
- The WebView2 provider readiness deadline now imports and uses the monotonic clock correctly; forced helper shutdown remains covered when terminate is ignored.
- Chat job creation now registers attachments before worker startup. Any pre-start preparation failure removes the persisted task and its cascade-owned records instead of leaving an orphaned job. Identical files attached to different jobs receive job-scoped asset IDs so rollback cannot steal or delete another job's historical asset association.
- The Windows source-wheel path validates cached artifacts by SHA-256, uses SHA-256-pinned pip 26.2.1 and setuptools 84.0.0 in a dedicated offline build environment, pins CI to Python 3.14.7, and records the source-build toolchain in release.json.
- Legacy provider login-state symbols removed in the earlier pass have no remaining references in the current frontend/backend contract paths reviewed.

The current GitHub Actions validation still fails before a hosted runner is assigned: the validate job reports runner_id 0, an empty runner name and zero executed steps, while package/release are skipped. Re-running failed jobs after the October 5 Actions incident was marked resolved produced the same pre-runner failure. Therefore no new Python, frontend, Playwright or Windows packaging pass is claimed for this exact HEAD. The repository changes above are regression-covered in source, but release remains blocked on an executable CI/Windows run.

