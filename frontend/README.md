# Zenless Web

Zenless web frontend + development Bridge foundation.

## Frontend

```bash
npm install
npm run dev
```

Quality gates:

```bash
npm run typecheck
npm run build
npm run lint
npm test
```

Default `.env.development` runs the full UI in browser-only Mock Mode.

## Development Bridge

```bash
cd bridge
npm install
npm run dev
```

Set `VITE_ZENLESS_MOCK=false` to exercise the HTTP/WebSocket transport against the development Bridge.

The Bridge is a mock/foundation only. Real Zenless Core, providers, StudioMCP, persistence and Windows packaging are the next Codex integration stage.

See:

- `FRONTEND_ARCHITECTURE.md`
- `BACKEND_CONTRACT.md`
- `CODEX_HANDOFF.md`
