# Rubra

Rubra is a portable Windows workspace for autonomous Roblox Studio development. It coordinates existing Roblox tooling, Studio MCP capabilities, authenticated web AI sessions, local models, indexing, review, and evidence-based QA behind one compact desktop interface.

Install `Rubra-Setup.exe` to `%LOCALAPPDATA%\Programs\Rubra`, then use the Start menu shortcut. The installer preserves existing user data on updates. `Rubra-Windows.zip` remains available for a portable installation in a writable folder. Python is included. Native Windows execution and live integrations still require validation; see `RELEASE_NOTES.md`.

The project is derived from the existing Zenless codebase. Rubra does not replace established tools when an upstream project already provides the required capability; pinned tools and source mirrors are composed under the portable runtime instead.

## Workflow

```text
objective
  -> inspect Studio and indexed project context
  -> load task-specific Roblox skills
  -> task-specific skills, local analysis, and optional Gemini research
  -> local Qwen Coder or authenticated ChatGPT implementation plan
  -> separate Qwen3 or authenticated DeepSeek review
  -> approval policy
  -> Studio MCP mutation with read-back
  -> static + runtime + security + visual QA
  -> automatic repair and regression reruns
  -> independent final review
  -> complete or block
```

## Portable runtime

Mutable Rubra state stays next to the executable:

```text
Rubra/
  Rubra.exe
  data/
  runtime/
    node/
    tools/
    npm/
    sources/
    local-ai/
    models/
    index/
    model-cache/
```

For a portable installation, deleting the Rubra folder removes Rubra state, browser profiles, downloaded models, indexes, pinned source mirrors, and portable tooling. Roblox Studio and the Microsoft WebView2 runtime are platform dependencies and are not removed.

On first launch Rubra provisions its pinned runtime automatically. Downloads with a published digest are SHA-256 verified before extraction and archive traversal is rejected.

## AI roles

- ChatGPT: primary builder and implementation agent.
- DeepSeek: independent reviewer and final-review agent.
- Gemini: routed research and visual second-opinion agent.
- Hunyuan: 3D generation when the provider surface exposes the required capability.
- Local Scout: bundled Qwen3 4B through llama.cpp for inexpensive planning and QA scenario generation.

Authentication uses normal provider pages in Rubra's managed browser profile. Rubra does not bypass CAPTCHA, MFA, consent, or provider authentication.

## Roblox toolchain

The portable runtime composes established projects including Rojo, Rokit, Selene, StyLua, Luau Language Server, Lune, Tripwire, mcp-code-search, TestEZ, Fusion, Matter, Zap, ProfileStore, Promise, Blender MCP, ZeroScript references, Roblox development skills, Wally, run-in-roblox, Remodel, darklua, and Roblox Studio MCP implementations.

Source mirrors are pinned to exact commits in `assets/toolchain.json`. They remain subject to their upstream licenses.

## Project indexing

Set the project folder in Settings. Rubra uses the pinned mcp-code-search implementation for semantic and keyword retrieval (Luau uses text chunks). Index data, embedding caches, and Python/uv state remain inside `runtime/`.

The index is context, not authority. Studio read-back and live test evidence remain authoritative for the active place.

## Verification

Rubra separates evidence channels instead of treating a model response as a test result. Depending on task risk and effort, verification can include:

- StyLua formatting checks.
- Selene linting when project configuration exists.
- Rojo builds.
- Luau Language Server analysis.
- Lune project tests when a runner exists.
- Studio Play output.
- Roblox Studio MCP playtest subagent when exposed.
- Tripwire remote/client-trust security analysis.
- viewport screenshots with independent visual review.
- device-emulation and bounded input checks.
- opt-in multiplayer harnesses.
- post-mutation script read-back and final independent review.

Missing optional capabilities are reported as skipped or unavailable. They are not reported as passed.

Continuous verification repeats repair and regression checks while progress is possible, with a hard safety cap to prevent a non-progressing loop.

## Approval modes

`ASK` requires manual write approval. `SAFE AUTO` can skip a local code gate only after an approved high-confidence review and when policy classifies every action as low or medium risk. `FULL AUTO` skips local approval gates but does not bypass blocked actions, destructive-operation policy, authentication, or external service permissions.

## Generated source policy

Generated game source is English-only, uses professional names, and omits explanatory/TODO comments. Rubra avoids suffix noise such as `v2`, `v3`, and `final2`.

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

Build the Windows executable with:

```powershell
.\build.ps1
```

Install NSIS 3 before building. The package targets are `dist\Rubra-Setup.exe` and `dist\Rubra-Windows.zip`, containing the same portable folder. `packaging/windows-runtime.json` pins the official Windows Python runtime and application wheels by SHA-256. `scripts/build_portable.py` also supports packaging from Linux with NSIS after the production frontend is built. `Rubra.spec` remains available for native Windows PyInstaller builds.

See `RUBRA.md`, `ARCHITECTURE.md`, `QA_ARCHITECTURE.md`, `NOTICE.md`, and `LICENSE`.

Rubra is distributed under GPL-3.0.

## Desktop recovery

Studio discovery runs in the background and retries when Studio opens later. The editor uses structured MCP results and can read script sources. Play Test can create a session for the open place without an AI build task. MCP and provider operations run outside the HTTP event loop so state and WebSocket updates remain responsive.

Pinned tools, upstream Roblox skill sources, and local models are prepared after the desktop opens. Settings → Models shows preparation progress. The hardware rules select Qwen3 4B and Qwen2.5 Coder 7B for machines with at least 20 GB RAM and sufficient free disk space. Each model is unloaded before switching; Vulkan falls back to CPU when startup fails. Web research, image interpretation, and Hunyuan generation remain separate capabilities.

Provider authentication is confirmed from account and composer signals, rejects visible sign-in controls, and requires a stable state before hiding its window. Provider UI changes can require adapter updates. A guest composer alone never counts as login.

Run `python -m pytest`, `npm test` in `frontend`, and `npm run test:e2e` after installing Playwright Chromium. The E2E configuration starts a mock UI server and does not access real accounts or Studio.
