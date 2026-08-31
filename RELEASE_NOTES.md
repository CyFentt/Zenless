# Release Notes

## Unreleased backend-vnext - 2026-08-30

### Provider and readiness core

- Added an authoritative readiness snapshot for core, bridge, WebSocket, UI, browser, providers, Studio, storage, and system diagnostics.
- Replaced generic composer authentication with provider-specific URL, account, application, composer, generation, login, and challenge signals.
- Added stable authentication confirmation, persistence verification, durable route selection, and non-secret provider session metadata.
- Added a provider registry with support status, role bindings, mode-level capability hints, live capability normalization, selection, refresh, and reassignment APIs.
- Kept unsupported catalog entries visible but disabled; enabled browser adapters remain `BETA` until real external verification.
- Added `AUTO`, `ON`, and `OFF` visual and 3D intent, provider-independent effort, bounded deadlines, and temporary chat mode.

### Studio, orchestration, and QA

- Added bounded Studio discovery retry, persisted target matching, multiple-instance selection, running-version MCP preference, and dynamic capability classification.
- Added incremental project indexing, current-date prompts, bounded official research routes, block-aware review metadata, and adaptive review rounds.
- Made automatic QA follow the final applied mutation and invalidate stale test evidence after later mutations.
- Added a bounded scenario compiler and executor that maps feature descriptions only to validated internal steps.
- Preserved deterministic final verification when independent external review is disabled.

### Files, artifacts, storage, and tools

- Added content-aware attachment inspection, safe bounded ZIP extraction, provider type and size validation, relevance ranking, and complete batching.
- Normalized six-view assets to `VIEW`, model runtime states to `IDLE`, `GENERATING`, `READY`, or `FAILED`, and approval to a separate field.
- Added observable chat activity, unified image/model/file artifacts, aggregate visual approval, and user-visible diagnostic events.
- Expanded storage accounting to database, logs, runs, snapshots, generated assets, downloads, temporary data, browser cache and profiles, runtime, tools, tool cache, and test artifacts.
- Added configurable 1-100 GB budgets with a 10 GB default and LRU cleanup limited to disposable data.
- Added a checksum-pinned optional ToolManager. Current default entries are catalog-only and `ON_DEMAND`; no unpinned package is automatically installed.

### Windows lifecycle

- Changed native startup and WebView2 shell colors to monochrome.
- Added Windows x64, disk, memory, WebView2, and Studio diagnostics plus component-scoped repair endpoints.
- Added a per-user NSIS installer, Windows uninstall entry, current-user shortcuts, Keep Settings uninstall, Full Remove uninstall, and exact owned-root validation.
- `build.ps1` keeps backend and frontend work isolated by default and produces the portable executable plus installer when NSIS is available.

### Verification status

The entries above describe the implementation, not external E2E certification. Final gate results must be recorded from the release run.

| Gate | Current release evidence |
| --- | --- |
| Ruff | Pending final branch run |
| Pyright | Pending final branch run |
| pytest | Pending final branch run |
| Frozen executable startup | Pending final package run |
| Installer build and per-user install/uninstall | Pending final package run |
| Live Studio, Play, Output, and mutation | `NOT RUN` unless separately recorded |
| ChatGPT browser workflow | `LOGIN_REQUIRED` or `NOT RUN` unless separately recorded |
| DeepSeek browser workflow | `LOGIN_REQUIRED` or `NOT RUN` unless separately recorded |
| Hunyuan 3D workflow | `LOGIN_REQUIRED` or `NOT RUN` unless separately recorded |
| Clean Windows 11 x64 profile | `NOT RUN` unless separately recorded |

### Known limits

- Provider interfaces and account permissions can change independently of Zenless; live capability probes remain authoritative.
- Current provider catalog entries beyond the three enabled adapters have no active transport and cannot be selected.
- Optional tool manifests are not installable until a verified versioned package and checksum are configured.
- RAR and 7Z are detected but not extracted by the built-in safe extractor.
- The scenario executor skips input and harness steps without a compatible advertised Studio schema.
- Jest Roblox is not injected into user projects and is not a release PASS without a real project execution.
- The Settings uninstall endpoint requires an installed per-user uninstaller; the portable executable cannot uninstall itself through that endpoint.
