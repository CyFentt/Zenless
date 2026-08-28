# ZENLESS — Codex Handoff

## What is complete in this repository

### Frontend

- React/TypeScript/Vite Zenless UI
- accepted black/white minimal/gothic design
- HOME / CHAT / BUILD / VISUAL / STUDIO / TEST / SETTINGS
- Mock Mode and Real API abstraction
- typed REST contract
- typed WebSocket event contract
- current-job state without production hardcoded IDs
- real chat attachment `File` pipeline to `FormData`
- Six View image URL rendering
- GLB/GLTF viewer with production `NO MODEL` behavior
- Build review model (APPROVE/REVISE/BLOCK + risk/details)
- Studio inspect/lock/use-as-context frontend actions
- dynamic provider model catalog/settings calls
- frontend diagnostics with dedup/correlation fields

### Bridge foundation

- local Node/TypeScript development Bridge
- `127.0.0.1` default bind
- session token and origin validation foundation
- `ws` WebSocket library
- REST routes matching the frontend contract
- mock adapter only

The Bridge is **not** the real Zenless backend.

## Codex must implement

1. **Zenless Core adapter** — connect Bridge commands to the existing Orchestrator/state machine/job manager.
2. **Persistence/recovery** — real SQLite state, safe resume and pending-operation handling.
3. **Managed Browser** — real lifecycle and provider session state.
4. **ChatGPT adapter** — truthful login/session/model discovery/send/stream/upload/download/cancel/recovery.
5. **DeepSeek adapter** — same provider contract, used for review/final review.
6. **Hunyuan adapter** — six-view input policy, geometry/texture generation states, approved model asset flow.
7. **StudioMCP adapter** — real tree/search/inspect/context/test integration.
8. **Mutation safety** — keep READ CURRENT → SNAPSHOT → VERSION/HASH VALIDATE → APPLY → READ BACK → VERIFY, with operation IDs and dedup/idempotency.
9. **Play Test events** — real test state/log stream/error correlation and bounded Auto Fix loop.
10. **Diagnostics bridge** — pipe real Core/Browser/Studio/storage errors into `Diagnostic`/`DIAGNOSTIC_EVENT`.
11. **Multipart attachments** — size/type validation, safe temporary storage/cleanup and backend/provider forwarding.
12. **Asset serving** — authorized ID-based image/GLB/texture delivery; reject traversal/arbitrary paths.
13. **Static UI serving/application shell** — launch the built frontend from the final local app without requiring npm/Vite from the user.
14. **Port/bootstrap** — choose an available local port and communicate it safely to the shell/UI.
15. **Windows packaging** — final Zenless installer/executable; no manual Python/Node/npm/Playwright installation for end users.

## Do not change unless objectively necessary

- visual identity/navigation
- frontend/backend separation
- `ZenlessAPI` as UI command boundary
- `ZenlessEvent` event-driven model
- no-browser-extension primary architecture
- provider model lists must stay dynamic
- production UI must never fabricate READY/model/job/Studio state

## Provider/browser rule

The final primary architecture is Managed Browser behind Zenless Core/Bridge. Do not introduce a required Chrome/Firefox extension. Manual normal login may show the provider page when necessary; do not implement cookie theft, credential capture, CAPTCHA bypass or stealth evasion.

## API methods the production Bridge/Core adapter must satisfy

See `src/services/api/types.ts`. It is the frontend source of truth and covers:

- bootstrap/status/connections/agents
- jobs
- chat + attachments/cancel
- context
- changes/review
- visual/six-view
- 3D model
- assets
- Studio
- tests
- settings/models/Smart Routing
- diagnostics

## WebSocket events the production Core must emit

See `ZenlessEventMap` in `src/types/index.ts` and the table in `BACKEND_CONTRACT.md`.

## Acceptance target

```text
Open Zenless
→ UI appears
→ Core/Bridge state truthful
→ provider login state truthful
→ StudioMCP state truthful
→ user sends task/attachments
→ Core investigates Studio
→ ChatGPT work streams to UI
→ DeepSeek review appears in BUILD
→ approval applies safely through StudioMCP
→ Play Test logs stream to TEST
→ errors reach Diagnostics
→ job completes/recoverable state persists
```

Only then package the final Windows release.
