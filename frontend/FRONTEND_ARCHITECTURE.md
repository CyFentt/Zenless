# ZENLESS — Frontend Architecture

## Purpose

Zenless Web is the official UI layer. It is intentionally separate from Zenless Core. The frontend displays state and sends commands; it does not implement AI reasoning, Roblox mutation policy, provider automation or persistence authority.

```text
React UI ↔ ZenlessAPI / ZenlessSocket ↔ Python LocalWebBridge ↔ Zenless Core
```

## Stack

- React 18 + TypeScript strict
- Vite 5
- Tailwind CSS
- Zustand
- Three.js / React Three Fiber / Drei (lazy 3D)
- Lucide icons
- Vitest + Testing Library
- ESLint + Prettier

## Navigation

Primary navigation is deliberately short:

- `HOME`
- `CHAT`
- `BUILD`
- `VISUAL`
- `STUDIO`
- `TEST`
- `SETTINGS`

`BUILD` contains Context / Changes / History. `VISUAL` contains Views / 3D / Assets. `SETTINGS` contains General / Models / Links / Logs.

## Visual direction

The accepted visual system is black/white/gray, compact, technical, slightly gothic/underground and minimal. It avoids blue SaaS styling, large rounded cards and verbose labels. Secondary explanation belongs in tooltips/details rather than permanent screen text.

## Directory layout

```text
src/
  App.tsx
  main.tsx
  index.css
  components/
  features/
    boot/
    home/
    chat/
    build/
    visual/
    studio/
    test/
    settings/
  services/
    api/
    websocket/
    mock/
    diagnostics.ts
  store/
  types/
bridge/
  server.ts
  mockAdapter.ts
  types.ts
```

## Runtime modes

### Mock mode

`VITE_ZENLESS_MOCK=true`

Uses `MockZenlessAPI` and `MockZenlessSocket` entirely in-browser. It does not require the Bridge, Studio or provider sessions. Mock operational values live under `src/services/mock/`, not inside production components.

### Real/production frontend mode

`VITE_ZENLESS_MOCK=false`

Uses `RealZenlessAPI` and `RealZenlessSocket`. No provider/model/job/model asset success may be invented. Missing services must render truthful `OFF`, `LOGIN`, `ERR`, `NO JOB`, `NO MODEL`, etc.

## API layer

`src/services/api/types.ts` defines `ZenlessAPI`. Components do not call `fetch()` directly.

`RealZenlessAPI` provides:

- centralized base URL
- session token bootstrap
- `X-Zenless-Token`
- request IDs
- JSON serialization
- structured `ApiError`
- timeout/AbortController handling
- `FormData` for chat attachments

The Bridge/backend remains authoritative.

## Chat attachments

The composer retains actual `File` objects until send. UI displays compact attachment chips/previews and allows removal. In real mode, `RealZenlessAPI.sendMessage()` uses multipart form data when files exist. The frontend never uploads directly to ChatGPT/DeepSeek/Hunyuan.

## WebSocket

`RealZenlessSocket` maintains one logical connection and implements:

- `CONNECTING`, `CONNECTED`, `RECONNECTING`, `DISCONNECTED`
- bounded exponential reconnect
- jitter
- one reconnect timer
- manual disconnect cancellation
- typed `ZenlessEvent` dispatch
- malformed payload diagnostics

Event-to-store mapping lives in `src/store/eventHandler.ts`.

## State

Zustand stores UI-relevant current state only: boot, navigation, socket, connections, agents, jobs/current job, chat/stream, context, changes, visual/model/assets, Studio, tests, settings and diagnostics.

No production `job_004` fallback exists in feature components. Mock IDs belong only to mock/test data.

## Six View

Exactly six canonical orthographic views are represented: FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM.

View states:

- EMPTY
- GENERATING
- READY
- FAILED
- APPROVED

READY/APPROVED render the supplied `imageUrl`. Mock mode supplies demo image URLs. Production never invents image data.

## 3D

`ModelViewer` is lazy-loaded. It loads real GLB/GLTF URLs using React Three Fiber/Drei and provides orbit/zoom/lighting. A demo geometry is permitted only in Mock Mode. Production with no URL renders `NO MODEL` rather than fake geometry.

## Build / Review

Review uses a typed `Review` object:

- APPROVE / REVISE / BLOCK
- LOW / MEDIUM / HIGH / CRITICAL risk
- critical issues
- warnings
- suggestions
- reviewer/timestamp

Diff rendering is IDE-style and action buttons call the API/mock layer.

## Studio

Studio page consumes `StudioState` and `StudioNode[]` from the API. Search, refresh, inspect, lock/unlock and use-as-context are API operations. There are no production hardcoded Studio trees.

## Models / Settings

Provider model catalogs come from `getModels()`. Model names are not permanently hardcoded in Settings components. Selection, reasoning/quality settings and Smart Routing persist through API methods; failures are diagnosed rather than silently accepted.

## Diagnostics

`FrontendDiagnostics` captures/deduplicates frontend failures including global window errors, rejected promises, API failures, WebSocket parse/transport failures and feature-level errors.

Diagnostic fields support severity, source/component, message, file/line/function, cause, impact, recovery, stack, occurrence count and correlation IDs.

## Performance

- Feature pages use `React.lazy`.
- 3D and diff viewers are lazy-loaded.
- Heavy content is not loaded on HOME.
- WebSocket is event-driven rather than high-frequency polling.
- Logs use compact rendering; virtualization should remain for large live streams.
- Avoid unnecessary global-store subscriptions and unbounded caches.

## Development Bridge

`bridge/` is an optional fixture/mock server, not the production backend. It:

- binds to `127.0.0.1`
- uses ESM imports
- uses the established `ws` package instead of handwritten WebSocket framing
- generates/validates a startup token
- validates configured origins
- provides REST/WebSocket routes against a mock adapter

Multipart attachments are intentionally not parsed by this fixture. The production Python Bridge already applies attachment count/size/name checks and task-scoped storage.

## Environment

```env
VITE_ZENLESS_MOCK=true
VITE_ZENLESS_API_BASE=http://127.0.0.1:8787
VITE_ZENLESS_WS_BASE=ws://127.0.0.1:8787
```

Never put secrets in `VITE_*` values.

## Commands

```bash
npm ci
npm run dev
npm run typecheck
npm run build
npm run lint
npm test
```

Bridge development:

```bash
cd bridge
npm ci
npm run dev
```

See `BACKEND_CONTRACT.md` for the real wire protocol and `CODEX_HANDOFF.md` for invariants and release verification.
