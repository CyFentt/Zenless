# Zenless

Zenless is a local Windows desktop orchestrator for Roblox Studio development. It connects an authenticated local interface, browser-based AI providers, Studio MCP, durable project state, controlled mutations, and bounded QA. Provider login, MFA, CAPTCHA, consent, and account permissions remain manual.

```text
request
  -> active readiness and task-intent checks
  -> Studio discovery and relevant context collection
  -> bounded research, planning, and review
  -> explicit approval for protected changes
  -> snapshot, hash precondition, mutation, and read-back
  -> automatic QA, bounded repair, and final verification
  -> complete, block, or fail with evidence
```

## Run

Windows 11 x64 is the primary target. Windows 10 x64 is best effort.

1. Install with `ZenlessSetup.exe` or run the portable `Zenless.exe`.
2. Open the intended Roblox Studio project in Edit mode with a compatible Studio MCP server enabled.
3. Complete provider login only when readiness or the selected task requires it.
4. Submit the objective in Chat and approve protected changes when prompted.

Readiness distinguishes core, bridge, browser, provider, storage, and Studio states. Multiple detected Studio instances require an explicit selection. Ordinary code tasks do not require the 3D provider unless task intent or an explicit option enables 3D.

## Task controls

- `visualFirst` and `create3D`: `AUTO`, `ON`, or `OFF`; legacy booleans remain accepted.
- `effort`: `AUTO`, `MINIMUM`, `MEDIUM`, or `MAXIMUM`.
- `chatMode`: `PROJECT` or `TEMP`; temporary chat starts without conversation handoff while retaining the same requested project workflow and safety gates.
- Independent review is optional. Deterministic final verification remains required when it is disabled.

## Safety and privacy

- The HTTP and WebSocket bridge binds only to loopback, uses an ephemeral port and per-process token, and validates host and origin.
- The Core is authoritative. The interface cannot declare provider readiness, apply a Studio change, or fabricate QA success.
- Persistent changes use a current read, durable snapshot, SHA-256 precondition, idempotent operation, allowlisted Studio call, read-back, and evidence.
- Provider profiles stay under Zenless-owned local storage. Passwords are never stored and cookies are never sent to the frontend.
- ZIP extraction rejects traversal, absolute paths, links, special files, reserved Windows names, excessive counts, excessive sizes, and suspicious compression ratios.
- Optional tools are never installed by default. Automatic installation requires an HTTPS package with a pinned version and SHA-256 checksum.
- Storage cleanup evicts only disposable data. The database, browser session profiles, required runtime, active evidence, and explicitly protected paths are preserved.

Application data is stored under `%LOCALAPPDATA%\Zenless`. The per-user installer uses `%LOCALAPPDATA%\Programs\Zenless` and does not require elevation for normal installation or launch.

## Development

Install backend dependencies and run the backend gate:

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pyright
python -m pytest -o addopts= -q
```

Build the portable executable and installer from an existing compiled frontend:

```powershell
.\build.ps1
```

The default build does not edit or rebuild frontend source. After the frontend integration branch is merged, its gate can be requested explicitly:

```powershell
.\build.ps1 -FrontendIntegration
```

`build.ps1` requires a compiled `frontend\dist`, PyInstaller, and NSIS 3.12 unless `-SkipInstaller` is used. Outputs are `dist\Zenless.exe` and, unless skipped, `dist\ZenlessSetup.exe`.

## Verification boundary

Ruff, Pyright, pytest, frozen startup, installer execution, live providers, live Studio, and a clean Windows profile are separate gates. A static or unit-test result does not certify an external provider, gameplay, installation, or clean-machine workflow. Current release evidence is recorded in [RELEASE_NOTES.md](RELEASE_NOTES.md).

## Source map

- `zenless/core.py`: authoritative application state, REST adapters, and user-visible events.
- `zenless/orchestrator.py`: task pipeline, approvals, mutation safety, QA, repair, and final verification.
- `zenless/provider_registry.py`: provider manifests, auth states, modes, and normalized capabilities.
- `zenless/agent_gateway.py`: persistent route selection across embedded and managed browser controllers.
- `zenless/studio_discovery.py`: bounded discovery, selection, readiness, and capability classification.
- `zenless/attachments.py`: inspection, safe ZIP extraction, provider routing, ranking, and batching.
- `zenless/qa_breaker.py` and `zenless/scenario_qa.py`: QA profiles, evidence, bounded scenarios, and cleanup.
- `zenless/storage.py`, `zenless/tool_manager.py`, and `zenless/uninstall.py`: local lifecycle controls.
- `zenless/web_bridge.py`: authenticated REST, upload, asset, and WebSocket transport.

See [ARCHITECTURE.md](ARCHITECTURE.md), [PROVIDER_ARCHITECTURE.md](PROVIDER_ARCHITECTURE.md), [QA_ARCHITECTURE.md](QA_ARCHITECTURE.md), [TOOLS_ARCHITECTURE.md](TOOLS_ARCHITECTURE.md), [INSTALLATION_ARCHITECTURE.md](INSTALLATION_ARCHITECTURE.md), and [BACKEND_REQUIREMENTS.md](BACKEND_REQUIREMENTS.md).

Licensed under GPL-3.0.
