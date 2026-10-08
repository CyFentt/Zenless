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
## User-reproduced 2.1.2 hardening closure

A second Windows-oriented review was driven by live failures reproduced in the packaged application and closed the following cross-layer paths:

- Provider authentication no longer treats the DeepSeek Reviewer as globally mandatory. Independent Review can be disabled, Smart Routing can use a local reviewer or Gemini, anti-bot challenges are detected and bounded without challenge bypass, and active login workers cannot be downgraded by background health refresh or Play Test shutdown.
- Hunyuan authentication can be confirmed from a stable usable 3D session/capability surface and the embedded login window hides after confirmed authentication instead of remaining open indefinitely.
- Manual Play Stop waits for the QA worker shutdown before provider reconciliation so a Studio test lifecycle cannot corrupt unrelated provider UI state.
- Qwen/llama.cpp preparation records individual component results, resumes interrupted downloads, verifies pinned SHA-256 values, exposes RAM/disk eligibility reasons, supports targeted retries, and never labels a failed-but-existing file as installed.
- The prompt queue is durable and sequential. Pending and inflight work are separated, retry/backoff is bounded, restart reconciliation follows the persisted job identity, ambiguous delivery becomes SENT_UNCONFIRMED, queue continuation is blocked until ambiguity is explicitly resolved, and partial/unknown sends are never replayed automatically.
- Smart Routing now treats recoverable provider quota/capacity/input-limit failures as routing events. Builder/Reviewer roles can move to verified local/Gemini routes before output begins; partial streamed output disables automatic resend. Research can fall back to the local scout instead of requiring Gemini when Smart Routing is enabled.
- Diagnostics now persist frontend, browser, provider, queue, local-AI and QA failures with bounded details. Previously silent local QA planner and task rollback failures are surfaced while preserving safe fallback behavior.
- UI contracts were aligned with backend state: Independent Review is named explicitly, local provider fallbacks are labelled LOCAL, local model/runtime failures remain retryable, prompt-queue ambiguity has explicit Mark Sent / Retry controls, and the sidebar status indicator is labelled as system health.

Official Qwen Hugging Face metadata was checked for the pinned local weights: Qwen3-4B Q4_K_M SHA-256 is 7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5 and Qwen2.5-Coder-7B-Instruct Q4_K_M SHA-256 is 509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c. The pinned llama.cpp b11379 Windows CPU/Vulkan release asset digests were also matched against GitHub release metadata.

GitHub Actions remains an external validation blocker for this repository: current validate jobs still complete with runner_id 0, an empty runner name and zero executed steps, so no current-HEAD CI pass is claimed. Source regressions were added for the newly fixed state machines and validation paths, but a native Windows/package run is still required before calling the prerelease fully validated.

### Final lifecycle/local-runtime pass

The final continuation after the reproduced-bug closure found and corrected additional cross-layer race and recovery conditions:

- Login cancellation is out-of-band and no longer creates a hidden provider window or starts an inactive Playwright transport merely to cancel it. DeepSeek generic WebView login failure remains human-driven instead of escalating into automated browser login.
- A managed-browser failure while switching an authenticated visible login into a headless context is contained to that provider and reported; it no longer tears down the browser worker shared by other provider state.
- Play Test Stop now confirms that the QA/orchestrator worker has actually exited before provider reconciliation. A slow shutdown reports a bounded diagnostic and deliberately leaves provider sessions untouched.
- Generation cancellation tracks provider participation per task and sends cancel only to routes used by that task, avoiding unrelated provider startup and state mutation.
- Local model availability now honors persisted component verification state. Failed, skipped or optional Qwen/llama.cpp artifacts are non-routable; corrupt raw models are deleted before retry; model/runtime maintenance is serialized against active jobs.
- When a compatible Ollama model is already available, default preparation skips redundant portable local-AI downloads while retaining any already verified portable fallback. Cancelled setup merges partial results instead of erasing untouched component history.
- Prompt-queue UI always keeps non-terminal work visible, and empty JSON chat requests can no longer create placeholder jobs without attachments.

The latest checked workflow for this continuation still failed before execution: validate had runner_id 0, an empty runner name and no steps. Therefore this report intentionally does not claim a clean current-HEAD pytest, frontend, Playwright or Windows-package run.

