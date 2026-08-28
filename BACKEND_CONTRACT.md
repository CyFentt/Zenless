# ZENLESS — Backend Contract

This document defines the contract the Codex must implement to connect the Zenless frontend to real AI providers, Roblox Studio, and the Zenless Core.

## Architecture

```
Zenless UI (React)
    │
    REST + WebSocket
    │
Zenless Bridge (127.0.0.1:PORT)
    │
    ├── Zenless Core (orchestrator)
    ├── AI Providers (ChatGPT, DeepSeek, Hunyuan via Managed Browser)
    └── StudioMCP (Roblox Studio connection)
```

The Bridge is transport only. It does NOT make decisions. It forwards requests to Zenless Core and streams events back to the frontend.

## Bridge Foundation (Already Implemented)

The bridge foundation exists in `bridge/` and provides:

- HTTP server on `127.0.0.1` (never `0.0.0.0`)
- REST routes matching all endpoints below
- WebSocket upgrade handling
- Mock adapter with simulated state and events
- CORS headers on all responses
- Request ID header (`X-Request-Id`)

### Running the Bridge

```bash
cd bridge
npm install
npm run dev    # hot reload
npm start      # production
```

Environment: `ZENLESS_PORT` (default 8787), `ZENLESS_ALLOWED_ORIGIN` (default `*`).

## Security Contract

The Bridge expects (but does not yet enforce):

1. **Startup Session Token** — Bridge generates a token on start. Frontend stores it and sends as `X-Zenless-Token` header.
2. **Origin Validation** — Only accept requests from the known frontend origin.
3. **Request ID** — Every response includes `X-Request-Id` for tracing.
4. **Local Only** — Bridge binds to `127.0.0.1` only. No external access.

## REST API

All endpoints return JSON. Errors: `{ "error": "message" }` with appropriate HTTP status.

### Boot

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/bootstrap` | — | `{ steps: BootStep[] }` |
| GET | `/api/status` | — | `{ ready: boolean }` |

### Connections

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/connections` | — | `ConnectionInfo` |
| GET | `/api/agents` | — | `AgentInfo[]` |

### Jobs

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/jobs` | — | `Job[]` |
| GET | `/api/jobs/:id` | — | `Job` |
| POST | `/api/jobs` | `{ title: string, options?: Partial<TaskOptions> }` | `Job` |
| POST | `/api/jobs/:id/pause` | — | `Job` |
| POST | `/api/jobs/:id/resume` | — | `Job` |
| DELETE | `/api/jobs/:id` | — | `{ ok: boolean }` |

### Chat

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/chat` | `{ content: string, jobId?: string }` | `{ messageId: string, jobId?: string }` |
| POST | `/api/chat/:jobId/cancel` | — | `{ ok: boolean }` |

### Context

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/jobs/:jobId/context` | — | `ContextItem[]` |
| POST | `/api/jobs/:jobId/context/refresh` | — | `ContextItem[]` |
| POST | `/api/context/:id/include` | — | `{ ok: boolean }` |
| POST | `/api/context/:id/exclude` | — | `{ ok: boolean }` |
| POST | `/api/context/:id/lock` | — | `{ ok: boolean }` |
| POST | `/api/context/:id/unlock` | — | `{ ok: boolean }` |
| GET | `/api/context/:id` | — | `ContextItem` |

### Changes / Review

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/jobs/:jobId/changes` | — | `ChangedFile[]` |
| GET | `/api/jobs/:jobId/review` | — | `{ files: ChangedFile[], ready: boolean }` |
| POST | `/api/jobs/:jobId/changes/approve` | — | `{ ok: boolean }` |
| POST | `/api/jobs/:jobId/changes/reject` | — | `{ ok: boolean }` |
| PUT | `/api/jobs/:jobId/changes/:fileId` | `{ content: string }` | `{ ok: boolean }` |

### Visual

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/jobs/:jobId/visual` | — | `{ views: ViewTile[], concept: { version, status, prompt? } }` |
| POST | `/api/jobs/:jobId/visual/approve` | — | `{ ok: boolean }` |
| PUT | `/api/jobs/:jobId/visual/concept` | `{ prompt: string }` | `{ ok: boolean }` |
| POST | `/api/jobs/:jobId/visual/regenerate` | — | `{ ok: boolean }` |
| POST | `/api/jobs/:jobId/visual/views/:view/regenerate` | — | `{ ok: boolean }` |

### 3D Model

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/jobs/:jobId/model` | — | `ModelInfo` |
| POST | `/api/jobs/:jobId/model/approve` | — | `{ ok: boolean }` |
| POST | `/api/jobs/:jobId/model/geometry/regenerate` | — | `{ ok: boolean }` |
| POST | `/api/jobs/:jobId/model/texture/regenerate` | — | `{ ok: boolean }` |

### Assets

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/assets` | — | `Asset[]` |
| GET | `/api/assets/:id` | — | Binary stream (image/GLB/texture) |

Assets must be served as URLs (`/api/assets/:id`), never as filesystem paths (`C:\Users\...`).

### Studio

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/studio/state` | — | `{ state: StudioState }` |
| GET | `/api/studio/tree` | — | `StudioNode[]` |
| GET | `/api/studio/search?q=...` | — | `StudioNode[]` |
| POST | `/api/studio/refresh` | — | `{ ok: boolean }` |
| GET | `/api/studio/:nodeId` | — | `StudioNode` |

### Test

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/jobs/:jobId/test` | — | `{ ok: boolean }` |
| POST | `/api/jobs/:jobId/test/stop` | — | `{ ok: boolean }` |
| GET | `/api/jobs/:jobId/test/state` | — | `TestState` |

### Settings

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/settings` | — | `Settings` |
| PATCH | `/api/settings` | `Partial<Settings>` | `Settings` |
| GET | `/api/settings/models` | — | `ModelSettings` |
| PUT | `/api/settings/models` | `{ agent: string, model: string }` | `{ ok: boolean }` |
| PUT | `/api/settings/smart-routing` | `{ enabled: boolean }` | `{ ok: boolean }` |

### Diagnostics

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/diagnostics` | — | `Diagnostic[]` |

## WebSocket Events

Single connection at `ws://127.0.0.1:PORT/ws`. Events are JSON: `{ "type": "...", "data": {...} }`.

### Boot Events

| Event | Payload | When |
|---|---|---|
| `BOOT_STAGE_CHANGED` | `{ stage: BootStage, state: BootState }` | A boot stage changes state |
| `BOOT_COMPLETE` | `{}` | All boot stages ready |

### Connection Events

| Event | Payload | When |
|---|---|---|
| `CONNECTION_CHANGED` | `Partial<ConnectionInfo>` | Any connection status changes |
| `AGENT_STATUS_CHANGED` | `{ agent: AgentId, status: ConnectionStatus }` | An agent's status changes |

### Pipeline Events

| Event | Payload | When |
|---|---|---|
| `PIPELINE_STATE_CHANGED` | `{ jobId: string, stage: PipelineStage }` | Job moves to a new pipeline stage |

### Job Events

| Event | Payload | When |
|---|---|---|
| `JOB_CREATED` | `{ job: Job }` | New job created |
| `JOB_UPDATED` | `{ job: Partial<Job> & { id: string } }` | Job metadata updated |
| `JOB_COMPLETE` | `{ jobId: string }` | Job finished successfully |
| `JOB_FAILED` | `{ jobId: string, reason: string }` | Job failed |

### Chat Events

| Event | Payload | When |
|---|---|---|
| `CHAT_STREAM_STARTED` | `{ messageId: string, jobId?: string }` | Zenless begins responding |
| `CHAT_STREAM_DELTA` | `{ messageId: string, delta: string }` | Incremental response text |
| `CHAT_STREAM_FINISHED` | `{ messageId: string }` | Response complete |
| `CHAT_MESSAGE` | `{ message: ChatMessage }` | Full message (non-streaming) |

### Context Events

| Event | Payload | When |
|---|---|---|
| `CONTEXT_UPDATED` | `{ items: ContextItem[] }` | Context list changes |

### Changes Events

| Event | Payload | When |
|---|---|---|
| `CHANGES_UPDATED` | `{ files: ChangedFile[] }` | File changes detected |
| `REVIEW_READY` | `{ files: ChangedFile[] }` | Review is ready for approval |

### Visual Events

| Event | Payload | When |
|---|---|---|
| `VISUAL_GENERATION_CHANGED` | `{ view?: ViewName, state: ViewState }` | View generation state changed |
| `VISUAL_READY` | `{ view: ViewName, imageUrl: string }` | A view image is ready |
| `VISUAL_APPROVED` | `{ view: ViewName }` | A view was approved |

### 3D Model Events

| Event | Payload | When |
|---|---|---|
| `MODEL_GENERATION_CHANGED` | `{ target: "geometry" \| "texture", state: ModelGenState }` | Geometry or texture generation state |
| `MODEL_READY` | `{ modelUrl: string }` | 3D model is ready |
| `MODEL_APPROVED` | `{}` | Model was approved |

### Asset Events

| Event | Payload | When |
|---|---|---|
| `ASSETS_UPDATED` | `{ assets: Asset[] }` | Asset list changed |

### Studio Events

| Event | Payload | When |
|---|---|---|
| `STUDIO_STATE_CHANGED` | `{ state: StudioState }` | Studio connection state changed |
| `STUDIO_TREE_UPDATED` | `{ tree: StudioNode[] }` | Studio hierarchy updated |

### Test Events

| Event | Payload | When |
|---|---|---|
| `TEST_STARTED` | `{}` | Play test started |
| `TEST_LOG` | `{ log: TestLog }` | A log line was emitted |
| `TEST_FINISHED` | `{ passed: boolean }` | Play test finished |

### Settings Events

| Event | Payload | When |
|---|---|---|
| `SETTINGS_CHANGED` | `{ settings: Partial<Settings> }` | Settings were updated |

### Diagnostics Events

| Event | Payload | When |
|---|---|---|
| `DIAGNOSTIC_EVENT` | `{ diagnostic: Diagnostic }` | A diagnostic event occurred |

## TypeScript Types

All shared types are in `src/types/index.ts`. The Bridge should import from there or define compatible types.

## Bridge Handoff — TODO CODEX

The following must be implemented by the Codex:

### Adapters

1. **Zenless Core Adapter** — Connect Bridge to the orchestrator that understands user requests, plans, and coordinates AI providers.
2. **StudioMCP Adapter** — Connect Bridge to Roblox Studio via StudioMCP for hierarchy inspection, script reading, and applying changes.
3. **Managed Browser Adapter** — Control a browser instance to interact with ChatGPT, DeepSeek, and Hunyuan web interfaces.
4. **ChatGPT Adapter** — Send prompts, receive responses, handle login state.
5. **DeepSeek Adapter** — Send prompts, receive responses, handle login state.
6. **Hunyuan Adapter** — Send 3D generation requests, receive GLB models, handle login state.

### Infrastructure

7. **SQLite/Recovery** — Persist job state, context, and session data for crash recovery.
8. **Windows Packaging** — Package Bridge as `Zenless Bridge.exe` with auto-start and port management.
9. **Session Token** — Generate and validate startup session tokens.
10. **Asset Serving** — Implement `/api/assets/:id` to serve images, GLB files, and textures from a managed directory.

### Important Rules

- The Bridge NEVER makes decisions. It forwards requests and events.
- The Bridge NEVER opens `0.0.0.0`. Local only.
- The Bridge NEVER exposes filesystem paths to the frontend.
- Provider statuses must be truthful: `READY`, `LOGIN`, `OFF`, `ERR` — never fake.
