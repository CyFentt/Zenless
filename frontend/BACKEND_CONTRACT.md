# ZENLESS — Backend Contract

This is the versioned transport contract between the React frontend and the real local Zenless backend. Production is served by `zenless/web_bridge.py` and `zenless/core.py`; `frontend/bridge/` and Mock Mode remain development fixtures and are never selected by the production build.

## Architecture

```text
React UI
  ↕ REST + WebSocket
Python Zenless Bridge (127.0.0.1, ephemeral port)
  ↕ adapters
Zenless Core / Orchestrator / Providers / StudioMCP / Persistence
```

The Bridge transports commands, state, authorized files and events. It contains no AI reasoning or Roblox mutation policy; the Core and Orchestrator remain authoritative.

## Configuration

Frontend environment variables:

| Variable | Purpose | Development default |
|---|---|---|
| `VITE_ZENLESS_MOCK` | `true` uses in-browser Mock API/Socket | `true` in `.env.development`; forced `false` by the release build |
| `VITE_ZENLESS_API_BASE` | Optional REST base override | same origin |
| `VITE_ZENLESS_WS_BASE` | Optional WebSocket base override | same origin (`ws:`/`wss:`) |

The production Bridge is not configured through public host/token environment variables. It rejects any bind other than `127.0.0.1`, asks the OS for an available port and creates a fresh 48-byte URL-safe token for each process. A remote mode is intentionally out of scope.

## Session, origin and request IDs

1. Frontend obtains a startup session token with `GET /api/session` from an allowed origin.
2. Authenticated REST requests send `X-Zenless-Token: <token>`.
3. WebSocket connects to `/ws?token=<token>`.
4. Bridge validates exact `Origin` values; production must not default to `*`.
5. REST responses include `X-Request-Id`. Frontend may also send its own request ID.
6. Never expose provider cookies, passwords, browser credentials or filesystem paths to the frontend.

## Error schema

Non-2xx responses should use:

```json
{
  "code": "STABLE_MACHINE_CODE",
  "message": "Short human-readable message",
  "details": {}
}
```

`details` is optional and must be sanitized. The HTTP response should include `X-Request-Id`.

## REST API

### Boot / health

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/session` | — | `{ token: string }` |
| GET | `/api/bootstrap` | — | `{ steps: BootStep[] }` |
| GET | `/api/status` | — | `{ ready: boolean }` |
| GET | `/api/connections` | — | `ConnectionInfo` |
| GET | `/api/agents` | — | `AgentInfo[]` |
| POST | `/api/providers/:provider/login` | — | `{ ok: boolean }` |

`provider` is one of `chatgpt`, `deepseek` or `hunyuan`. This command asks the backend to open the provider's normal managed login flow; credentials and session data never pass through the React frontend.

### Jobs

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/jobs` | — | `Job[]` |
| GET | `/api/jobs/:id` | — | `Job` |
| POST | `/api/jobs` | `{ title, options? }` | `Job` |
| POST | `/api/jobs/:id/pause` | — | `Job` |
| POST | `/api/jobs/:id/resume` | — | `Job` |
| DELETE | `/api/jobs/:id` | — | `{ ok: boolean }` |

The backend is authoritative for the current job. The frontend must never depend on a production hardcoded job ID.

### Chat

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/chat` | JSON `{ content, jobId? }` **or** multipart form with `content`, optional `jobId`, repeated `attachments` | `{ messageId, jobId? }` |
| POST | `/api/chat/:jobId/cancel` | — | `{ ok: boolean }` |

The production Bridge accepts JSON or multipart. Multipart is bounded to five attachments, 32 MiB per file and 96 MiB total; filenames are sanitized and files are moved into task-scoped storage before provider forwarding. Browser-only Mock Mode may use fixture behavior and must never be enabled in release.

### Context

| Method | Path | Response / action |
|---|---|---|
| GET | `/api/jobs/:jobId/context` | `ContextItem[]` |
| POST | `/api/jobs/:jobId/context/refresh` | refreshed `ContextItem[]` |
| POST | `/api/context/:id/include` | `{ ok }` |
| POST | `/api/context/:id/exclude` | `{ ok }` |
| POST | `/api/context/:id/lock` | `{ ok }` |
| POST | `/api/context/:id/unlock` | `{ ok }` |
| GET | `/api/context/:id` | `ContextItem` |

### Changes / review

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/jobs/:jobId/changes` | — | `ChangedFile[]` |
| GET | `/api/jobs/:jobId/review` | — | `Review` |
| POST | `/api/jobs/:jobId/changes/approve` | — | `{ ok }` |
| POST | `/api/jobs/:jobId/changes/reject` | — | `{ ok }` |
| PUT | `/api/jobs/:jobId/changes/:fileId` | `{ content }` | `{ ok }` |

`Review` includes `decision: APPROVE|REVISE|BLOCK`, `risk: LOW|MEDIUM|HIGH|CRITICAL`, `criticalIssues[]`, `warnings[]`, `suggestions[]`, optional `summary`, `reviewer`, `timestamp`, `files[]`, and `ready`.

### Visual / six-view

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/jobs/:jobId/visual` | — | `{ views: ViewTile[], concept: { version, status, prompt? } }` |
| POST | `/api/jobs/:jobId/visual/approve` | — | `{ ok }` |
| PUT | `/api/jobs/:jobId/visual/concept` | `{ prompt }` | `{ ok }` |
| POST | `/api/jobs/:jobId/visual/regenerate` | — | `{ ok }` |
| POST | `/api/jobs/:jobId/visual/views/:view/regenerate` | — | `{ ok }` |

Exactly six canonical directions are used: `FRONT`, `BACK`, `LEFT`, `RIGHT`, `TOP`, `BOTTOM`. `imageUrl` must be a browser-safe Bridge URL, not a Windows path.

### 3D model

| Method | Path | Response / action |
|---|---|---|
| GET | `/api/jobs/:jobId/model` | `ModelInfo` |
| POST | `/api/jobs/:jobId/model/approve` | `{ ok }` |
| POST | `/api/jobs/:jobId/model/geometry/regenerate` | `{ ok }` |
| POST | `/api/jobs/:jobId/model/texture/regenerate` | `{ ok }` |

`ModelInfo` may expose `modelUrl` and `filename`; production must not fabricate a model when none exists.

### Assets

| Method | Path | Response |
|---|---|---|
| GET | `/api/assets` | `Asset[]` |
| GET | `/api/assets/:id/content` (preferred production shape) | authorized binary stream |

Production uses `/api/assets/:id/content`, resolves the stored asset ID inside the authorized data root and rejects traversal. Mock fixtures may use in-memory URLs. Never send `C:\...` paths to the web UI.

### Studio

| Method | Path | Response / action |
|---|---|---|
| GET | `/api/studio/state` | `{ state: StudioState }` |
| GET | `/api/studio/tree` | `StudioNode[]` |
| GET | `/api/studio/search?q=...` | `StudioNode[]` |
| POST | `/api/studio/refresh` | `{ ok }` |
| GET | `/api/studio/:nodeId` | `StudioNode` |
| POST | `/api/studio/:nodeId/lock` | `{ ok }` |
| POST | `/api/studio/:nodeId/unlock` | `{ ok }` |
| POST | `/api/studio/:nodeId/context` | `{ ok }` |

The production adapter queries StudioMCP. UI requests never bypass Zenless mutation safety.

### Tests

| Method | Path | Response |
|---|---|---|
| POST | `/api/jobs/:jobId/test` | `{ ok }` |
| POST | `/api/jobs/:jobId/test/stop` | `{ ok }` |
| GET | `/api/jobs/:jobId/test/state` | `TestState` |

### Settings / models

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/settings` | — | `Settings` |
| PATCH | `/api/settings` | `Partial<Settings>` | `Settings` |
| GET | `/api/settings/models` | — | `ModelCatalog` |
| PUT | `/api/settings/models` | `{ agent: chatgpt|deepseek|hunyuan, model }` | `{ ok }` |
| PUT | `/api/settings/smart-routing` | `{ enabled }` | `{ ok }` |

Model lists are discovered by the real backend/provider sessions. Production UI must not rely on fixed model names.

### Diagnostics

| Method | Path | Response |
|---|---|---|
| GET | `/api/diagnostics` | `Diagnostic[]` |

`Diagnostic` supports `critical|error|warning|info`, source/component/message, optional file/line/function, probable cause, impact, recovery, stack, occurrence count, and job/request/operation IDs.

## WebSocket contract

One logical connection at `WS_BASE/ws?token=<session-token>`. Each frame is:

```json
{ "type": "EVENT_NAME", "data": {} }
```

Canonical event names and payloads are defined by `ZenlessEventMap` in `src/types/index.ts`. Provider stream deltas are forwarded as they are observed by WebView2/Playwright; only the completed response is persisted:

| Event | Payload |
|---|---|
| `BOOT_STAGE_CHANGED` | `{ stage, state }` |
| `BOOT_COMPLETE` | `{}` |
| `CONNECTION_CHANGED` | `Partial<ConnectionInfo>` |
| `AGENT_STATUS_CHANGED` | `{ agent, status }` |
| `PIPELINE_STATE_CHANGED` | `{ jobId, stage }` |
| `JOB_CREATED` | `{ job }` |
| `JOB_UPDATED` | `{ job: Partial<Job> & { id } }` |
| `JOB_COMPLETE` | `{ jobId }` |
| `JOB_FAILED` | `{ jobId, reason }` |
| `CHAT_STREAM_STARTED` | `{ messageId, jobId? }` |
| `CHAT_STREAM_DELTA` | `{ messageId, delta }` |
| `CHAT_STREAM_FINISHED` | `{ messageId }` |
| `CHAT_MESSAGE` | `{ message }` |
| `CONTEXT_UPDATED` | `{ items }` |
| `CHANGES_UPDATED` | `{ files }` |
| `REVIEW_READY` | `{ review }` |
| `VISUAL_GENERATION_CHANGED` | `{ view?, state }` |
| `VISUAL_READY` | `{ view, imageUrl }` |
| `VISUAL_APPROVED` | `{ view }` |
| `MODEL_GENERATION_CHANGED` | `{ target: geometry|texture, state }` |
| `MODEL_READY` | `{ modelUrl, filename? }` |
| `MODEL_APPROVED` | `{}` |
| `ASSETS_UPDATED` | `{ assets }` |
| `STUDIO_STATE_CHANGED` | `{ state }` |
| `STUDIO_TREE_UPDATED` | `{ tree }` |
| `TEST_STARTED` | `{ jobId? }` |
| `TEST_CASE_STARTED` | `{ jobId?, testCase: TestCaseResult }` |
| `TEST_CASE_FINISHED` | `{ jobId?, testCase: TestCaseResult }` |
| `TEST_FAILURE` | `{ jobId?, failure: TestFailure }` |
| `TEST_LOG` | `{ log }` |
| `TEST_FINISHED` | `{ passed, jobId? }` |
| `SETTINGS_CHANGED` | `{ settings }` |
| `DIAGNOSTIC_EVENT` | `{ diagnostic }` |

Client requirements: one connection, bounded exponential reconnect with jitter, no duplicate listeners/timers, manual disconnect cancels reconnect, malformed payloads are diagnosed rather than crashing the app.

## Source-of-truth types

Frontend source-of-truth types live in:

- `src/types/index.ts`
- `src/services/api/types.ts`

The development fixtures import compatible types. A generated/shared protocol package may be introduced later, but wire compatibility must be preserved.

## Production invariants

1. Mock Mode is compile-time disabled for the release and cannot report production readiness.
2. A mutation is `READ CURRENT → SNAPSHOT → EXPECTED SHA-256 → CLAIM OPERATION → APPLY → READ BACK → VERIFY`; an existing pending operation is never replayed after a crash.
3. ChatGPT builds; DeepSeek performs the independent proposal review and a second real final review after mutation and QA. `REVISE` has a bounded repair loop; `BLOCK` prevents completion.
4. Visual First stores six separate, versioned PNG assets and visual-QA evidence. Approval/regeneration commands act on a gate; no placeholder image is treated as generated output.
5. Hunyuan capabilities are discovered from the live provider UI. Approved views are uploaded only up to the discovered limit; geometry and texture are separate operations and unavailable capabilities return a stable error.
6. Provider deltas, QA cases, diagnostics and pipeline stages travel through the Core Event Bus to one authenticated WebSocket connection.
7. Asset responses are ID-based and authorized; provider cookies, browser profile paths and arbitrary filesystem paths are never exposed.
8. Recovery is conservative: pre-mutation work may be paused, while interrupted mutation/QA/final-review stages are blocked for explicit inspection.

## Runtime-dependent limits

- Provider websites, account entitlements and model catalogs can change independently of Zenless. Absence of an upload/generation/download control is reported as capability unavailable.
- Studio Play/Output is executed only against a connected StudioMCP instance in Edit mode.
- Multiplayer, `StudioTestService`, VirtualInput and device emulation are not inferred from ordinary Play Test. They are executed only when the connected Studio tooling exposes a bounded capability; otherwise QA records a skip/gap.
- Clean-machine Windows, live provider and live Roblox E2E evidence belongs in release verification, not in this transport contract.
