# Zenless — Engineering Handoff

## Source of truth

`frontend/` is the only React/TypeScript/Vite source tree. The former root-level `src/`, `bridge/`, `package*.json` and build configs were stale duplicates and were removed. Production serves `frontend/dist` through the authenticated Python Bridge; `frontend/bridge/` and Mock Mode exist only for development and tests.

Do not restore a second frontend tree and do not edit generated `frontend/dist` by hand.

## Implemented boundaries

- `ZenlessAPI` is the UI command boundary; `ZenlessEventMap` is the event boundary.
- `zenless/web_bridge.py` owns local REST/WebSocket transport, token/origin/host checks, request correlation, multipart limits and authorized asset delivery.
- `zenless/core.py` owns state exposed to the UI and maps Event Bus updates into the frontend contract.
- `zenless/orchestrator.py` owns provider sequencing, approval gates, Studio mutation safety, QA/repair and the final review performed by the provider bound to the Reviewer role.
- `zenless/store.py` owns SQLite tasks/events/messages/approvals/assets/tests and idempotent operations.
- `zenless/agent_gateway.py` selects embedded WebView2 first and internal Playwright when the required capability is unavailable.
- `zenless/studio_mcp.py` is the only Studio command transport.
- `zenless/qa_breaker.py` records bounded, seeded QA evidence; it does not call an absent Studio capability a pass.

## Critical invariants

1. Never enable `VITE_ZENLESS_MOCK` in a production build.
2. Never move AI policy or Studio writes into the frontend/Bridge.
3. Preserve `READ CURRENT → SNAPSHOT → EXPECTED SHA-256 → CLAIM OPERATION → APPLY → READ BACK → VERIFY`.
4. A crash with a pending/unsafe write blocks recovery; it must not replay the mutation automatically.
5. Builder and Reviewer are independent role bindings. When independent review is enabled, the bound Reviewer checks the proposal and the final mutation/QA evidence. A final `BLOCK` cannot become `COMPLETE`.
6. Stream events are provisional display data. Persist only the completed provider response.
7. Six View means six separate versioned PNGs: `FRONT`, `BACK`, `LEFT`, `RIGHT`, `TOP`, `BOTTOM`. Regeneration creates a new version and never overwrites approved evidence in place.
8. Hunyuan image count, upload, geometry, texture and download support come from live capability discovery. Never fabricate a stage, percentage, model or texture.
9. Never expose provider cookies, credentials, browser profile paths or arbitrary Windows paths to React.
10. Keep login, MFA, CAPTCHA, consent, publishing and purchases manual.

## Verification before release

Run `build.ps1 -FrontendIntegration`; it gates PyInstaller behind Ruff, Pyright, pytest, `npm ci`, ESLint, TypeScript, Vitest and the production Vite build. A default `build.ps1` run reuses the existing compiled frontend. Report the exact counts from the release run.

Static/unit tests do not prove these external integrations:

- a fresh Windows machine with no development toolchain;
- real WebView2 provisioning and first-run login;
- real ChatGPT/DeepSeek/Hunyuan UI flows and generated assets;
- connected Roblox Studio mutation, Play/Stop and Output capture;
- multiplayer, VirtualInput or device-emulator QA;
- the complete visual and 3D E2E.

If any item was not observed, mark it `NOT RUN` or `CAPABILITY UNAVAILABLE`. Do not convert it to `PASS` from code inspection.

## Useful references

- `BACKEND_CONTRACT.md`: REST/WebSocket contract and runtime limits.
- `../ARCHITECTURE.md`: component and trust-boundary map.
- `../QA_ARCHITECTURE.md`: automated and manual verification matrix.
- `../RELEASE_NOTES.md`: current change set and release evidence.
