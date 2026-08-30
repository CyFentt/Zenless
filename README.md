# Zenless

Zenless is a local Windows application that coordinates Studio development through authenticated browser sessions without API keys. Login, MFA, CAPTCHA, and consent remain manual.

```text
request
  -> read Studio state
  -> create a proposal
  -> run an independent review
  -> request user approval
  -> apply verified Studio changes
  -> run bounded QA and repair
  -> perform a final review
  -> complete or block
```

## Usage

1. Open the current Studio project in Edit mode and connect a compatible MCP server.
2. Run `Zenless.exe`.
3. Use Settings > Links to authenticate the Builder, Reviewer, and 3D Generator when required.
4. Submit a complete objective in Chat and approve each relevant write gate.

Persistent data is stored under `%LOCALAPPDATA%\Zenless`, including the local database, rotating logs, private browser profiles, validated attachments, snapshots, evidence, and generated assets.

## Guarantees

- The HTTP and WebSocket bridge binds only to loopback with an ephemeral port, a per-process token, strict host and origin validation, and request IDs.
- The Core is authoritative. The UI requests actions but cannot apply changes or declare success.
- Mutations require a current read, snapshot, SHA-256 precondition, idempotent operation, application, read-back, and verification.
- Recovery never repeats an uncertain write automatically.
- Browser deltas are forwarded through WebSocket while completed responses alone become durable state.
- Visual First uses six versioned orthographic views with explicit approval and controlled regeneration.
- 3D generation discovers available capabilities and keeps geometry and texture stages separate.
- QA records its profile, seed, cases, evidence, output, and result. Missing capabilities are skipped or blocked, never reported as successful.
- Shutdown is cooperative across the bridge, browser controllers, Studio connection, queues, and database.

## Limits

- Browser automation depends on current provider interfaces and may require selector updates.
- The managed browser fallback is provisioned only when needed.
- Local 3D import depends on capabilities exposed by the connected Studio server.
- Multiplayer, virtual input, and device emulation run only when the connected Studio server exposes them.
- The release is a single-file executable and does not include a separate installer.

## Development

```powershell
python -m pip install -r requirements-dev.txt
npm --prefix frontend ci
python -m ruff check .
python -m pyright
python -m pytest -o addopts= -q
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

`tests/live_studio_smoke.py` starts Play only after Studio confirms Edit mode and always requests Stop in `finally`. It requires a real connected instance.

Build the release with:

```powershell
.\build.ps1
```

The build runs Ruff, Pyright, pytest, dependency installation, ESLint, TypeScript, Vitest, a production Vite build with mocks disabled, and PyInstaller. The only release artifact is `dist\Zenless.exe`.

## Source layout

- `frontend/`: canonical React and TypeScript source plus the transport contract.
- `zenless/core.py`: authoritative application state and UI adapters.
- `zenless/web_bridge.py`: authenticated local REST and WebSocket transport.
- `zenless/orchestrator.py`: pipeline, approval gates, mutation, and final review.
- `zenless/agent_gateway.py`: browser route selection by capability.
- `zenless/studio_mcp.py`: Studio protocol client.
- `zenless/store.py`: local database, idempotent operations, and recovery.
- `zenless/qa_breaker.py`: QA planning, execution, and evidence.
- `Zenless.spec`: console-free single-file Windows package.

See [ARCHITECTURE.md](ARCHITECTURE.md), [QA_ARCHITECTURE.md](QA_ARCHITECTURE.md), [frontend/BACKEND_CONTRACT.md](frontend/BACKEND_CONTRACT.md), and [RELEASE_NOTES.md](RELEASE_NOTES.md).

Licensed under GPL-3.0. See `NOTICE.md` for required legal notices.
