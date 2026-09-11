# Architecture

## Runtime ownership

```text
Zenless.exe
  -> native splash and WebView2 shell
  -> authenticated loopback bridge
     -> authoritative Core
        -> provider registry and browser gateway
        -> Studio discovery and Studio MCP client
        -> orchestrator, project index, and research broker
        -> attachment router and controlled asset service
        -> QA breaker and bounded scenario executor
        -> SQLite, storage budget, optional tools, diagnostics, and uninstall
     -> persistent frontend runtime
        -> REST hydration plus WebSocket deltas
```

The frontend is a state projection. The Core owns readiness, provider and Studio state, task policy, approvals, mutations, test evidence, storage, and errors. WebSocket messages are deltas; REST snapshots are authoritative after startup and reconnect.

## Startup and readiness

Mutable state resolves to `%LOCALAPPDATA%\Zenless`. Packaged resources resolve from the PyInstaller resource root. Startup stages are observed states for `CORE`, `STATE`, `BRIDGE`, `UI`, `BROWSER`, `AI`, and `STUDIO`; no percentage is synthesized.

`GET /api/readiness` collects a bounded snapshot of core, durable state, bridge, WebSocket configuration, compiled UI, browser status, provider auth, Studio selection, storage, and system diagnostics. Results are cached for three seconds unless `refresh=1` is requested. Readiness uses health and capability probes, not provider prompts.

## Local transport

The bridge listens only on `127.0.0.1` using an operating-system-assigned port. `/api/session` returns the random process token. Every other `/api/*` request requires `X-Zenless-Token`; WebSocket uses the token query parameter. Host, origin, request ID, body size, file count, per-file size, and aggregate upload size are validated.

REST errors use `{ "code": string, "message": string, "details"?: object }`. WebSocket events use `{ "type": string, "data": object }`. Assets are served only by database ID after their resolved path is confirmed inside the Zenless data root.

## Provider system

`ProviderRegistry` owns the catalog, role hints, support status, mode hints, and canonical capability shape. Only enabled manifests can be selected or assigned. A catalog entry is not proof of a working adapter; current enabled adapters are marked `BETA` until real external verification is completed.

Authentication uses provider-specific URL and DOM signals. Login fields, generic text inputs, and a composer alone are insufficient for providers with explicit auth markers. Challenge states keep the login surface available. Readiness requires authenticated state to remain stable before the session is treated as persistent.

`AgentGateway` probes the last successful route first, prefers an authenticated route over an idle route, and persists route and non-secret session metadata. Browser profiles contain the actual session material and are not copied into application messages. Live capability probes are authoritative; manifest mode capabilities are compatibility hints.

Role bindings are independent of provider identity: `BUILDER`, `REVIEWER`, `VISUAL`, `RESEARCH`, and `3D`. Default bindings remain Builder, Reviewer, and 3D/Visual, but supported enabled providers can be reassigned without changing the orchestrator contract.

## Task policy and orchestration

`TaskOptions` resolves `AUTO` visual and 3D modes from explicit intent. A code fix does not require 3D. A 3D request enables both the visual and 3D paths. `TEMP` starts without conversation handoff but still reads the selected Studio project and executes the same explicitly requested visual, 3D, QA, approval, and mutation flow.

The project pipeline is:

```text
NEW -> CONTEXT -> PLAN
  -> optional VISUAL and 3D approvals
  -> optional INDEPENDENT REVIEW
  -> CHANGE APPROVAL
  -> APPLY and READ-BACK
  -> automatic TEST and bounded FIX/RETEST
  -> FINAL VERIFICATION
  -> COMPLETE, BLOCKED, or FAILED
```

Required providers are derived from the resolved task. Builder is required for project implementation, Reviewer only when independent review is enabled, and 3D only when 3D is resolved on. Deterministic final verification runs even without an external reviewer.

`ProjectIndex` persists hashes, keywords, services, references, dependencies, remotes, and module links, then limits deep reads to relevant context. `ResearchBroker` supports allowlisted official HTTPS retrieval, provider search only when the live mode advertises it, and Studio documentation lookup only when an advertised tool maps to it. It does not bypass bot protection or invent unavailable search tools.

## Mutation safety and operational authority

Studio plus persisted Zenless state is operational authority. Provider conversation history is soft memory and never proves current Studio source.

Each persistent script mutation follows:

1. Read current source and compute SHA-256.
2. Save a durable snapshot.
3. Bind the expected hash to the approved operation.
4. Claim an idempotency key.
5. Read again and enforce the precondition.
6. Call an allowlisted mutation tool against the selected Studio instance.
7. Read back and verify content and hash.
8. Persist correlated evidence or a controlled failure.

A changed precondition blocks the write. An uncertain pending mutation is not replayed automatically. Every mutation invalidates earlier final-test evidence for that job.

## Studio system

`find_studio_mcp` attempts to pair MCP with the running Studio installation before using a bounded fallback. `StudioDiscoveryManager` starts MCP, retries registration with bounded delays, matches persisted Studio, place, and universe identities, and requires selection when multiple targets remain ambiguous. It never assumes the first target is correct.

Discovery reports `MCP_SETUP_REQUIRED`, `MCP_RUNTIME_ERROR`, `STUDIO_NOT_RUNNING`, `MULTIPLE_STUDIOS`, or `PROJECT_READY`. The capability registry enumerates and classifies advertised tools as read, search, visual, playtest, input, runtime, asset, mutation, or project administration. Tool availability is checked at execution time.

## Attachments and artifacts

Uploads are inspected by content signature, size, extension, MIME type, and SHA-256. Safe ZIP extraction is internal and bounded; RAR and 7Z are detected but not extracted without a separately verified tool path. Provider routing applies the live mode's accepted types, size, archive, and count limits, ranks relevant text and source files first, and creates multiple batches without silent drops.

Visual concept assets use `VIEW` and `image/png`; general images use `IMG`. Model states are `IDLE`, `GENERATING`, `READY`, or `FAILED`; approval is a separate field. Chat activity exposes observable stages and real step counts, not hidden reasoning or fake percentages. Chat artifacts contain controlled content URLs instead of arbitrary filesystem paths.

## QA and final verification

Automatic QA follows the final applied mutation. Profiles select bounded duration and depth. AI scenario text is compiled into a fixed internal DSL and cannot directly execute generated Luau. Missing Studio capabilities produce explicit skipped or failed evidence. Stop is requested in cleanup whenever Play started.

See [QA_ARCHITECTURE.md](QA_ARCHITECTURE.md) for execution and evidence boundaries.

## Local lifecycle

SQLite uses WAL and stores tasks, messages, context, approvals, operations, assets, test runs, and compact evidence. Large artifacts stay in controlled directories with database metadata. The storage manager tracks a configurable 1-100 GB budget with a 10 GB default and evicts disposable data by least-recent access. Provider profiles, database files, browser runtime, active evidence, and protected assets are not budget eviction candidates.

Optional tools are cataloged but installed only from verified, versioned, checksum-pinned HTTPS packages. The per-user NSIS installer and backend uninstall endpoint operate only on exact Zenless-owned roots.

## Packaging boundary

`Zenless.spec` produces a console-free single-file `Zenless.exe` containing Python runtime dependencies, compiled frontend assets, and bundled resources. `installer/Zenless.nsi` produces `ZenlessSetup.exe`. Normal launch does not request elevation. WebView2 is detected and, when absent, installed through the official bootstrapper after signature validation.
