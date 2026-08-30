# Release Notes

## Unreleased - 2026-08-30

### Runtime and recovery

- Application-lifetime ownership keeps the WebSocket, subscriptions, and hydration active after the splash closes.
- Startup waits for both backend readiness and an authoritative REST snapshot.
- Every reconnect refreshes connections, agents, jobs, settings, diagnostics, assets, Studio state, messages, context, changes, visual state, model state, and test state.
- Agent, job, and message updates use idempotent upserts to prevent missing rows and duplicate chat history.
- Interrupted jobs are recovered conservatively according to their last persisted stage.

### Chat and providers

- Provider authentication is checked before a job is created or Studio work begins.
- Login-required responses are structured, visible in chat, and expose a legitimate Login action.
- Blocked and failed pipeline states persist and publish their real error messages.
- Chat submission reconciles the temporary user message with its persisted server ID and hydrates the new job immediately.
- Visible agent names are Builder, Reviewer, 3D Generator, and Studio.

### Core and safety

- The local bridge uses an ephemeral port, random session token, strict host and origin checks, authenticated WebSocket access, bounded multipart input, and ID-based assets.
- Mutations require snapshots, SHA-256 preconditions, operation claims, read-back, and correlated evidence.
- Pending mutation operations are never replayed automatically after a crash.
- Diagnostics collect startup, bridge, browser, Studio, and pipeline failures in bounded rotating logs.

### QA and release

- QA records profile, seed, plan, cases, output, failures, and independent review, and always requests Play cleanup.
- Conditional checks remain `SKIPPED` when the required tool, schema, project harness, or live Studio session is unavailable.
- `build.ps1` blocks packaging until Ruff, Pyright, pytest, ESLint, TypeScript, Vitest, and the production Vite build pass.
- `Zenless.spec` produces one Windows executable without a console or unused GUI toolkits.

### Verification

| Gate | Current result |
|---|---|
| Ruff | `PASS` |
| Pyright | `PASS` - 0 errors, 0 warnings |
| pytest | `PASS` - 51 tests |
| ESLint | `PASS` |
| TypeScript | `PASS` |
| Vitest | `PASS` - 5 files, 50 tests |
| Production dependency audit | `PASS` - 0 vulnerabilities |
| Production Vite build | `PASS` |
| One-file executable | `PASS` - 63,738,647 bytes, SHA-256 `757FF4E68460D61AA32DDFB2352990CC448C40EC1AB1DD522071D48F10AD9854` |
| Frozen executable startup | `PASS` |
| Frozen embedded browser round trip | `PASS` |
| Live Studio, Play, and Output | `NOT RUN` - no connected Studio session |
| Live provider and visual workflow | `NOT RUN` |
| Clean Windows machine | `NOT RUN` |

### Known limits

- Provider sites and account permissions can change independently and may require adapter maintenance.
- The release produces `Zenless.exe` without a separate installer.
- Local GLB support still depends on the import capabilities exposed by Studio and its bridge.
