# Rubra

Rubra is a portable Windows workspace for autonomous Roblox Studio game development. It is derived from the existing Zenless codebase and composes established Roblox tooling instead of replacing it.

The application keeps mutable state under its own folder, provisions pinned tools on first launch, uses authenticated web sessions for ChatGPT, DeepSeek, Gemini and Hunyuan, connects to Roblox Studio through MCP, and drives planning, implementation, visual inspection, adversarial QA, repair and final verification.

## Product direction

Rubra uses a compact dark interface with a restrained red accent. The UI is intentionally thin. The backend owns state, provider routing, Studio writes, snapshots, skill selection, verification and recovery.

## Portable layout

    Rubra/
      Rubra.exe
      app/
        main.py
        zenless/
        assets/
        frontend/dist/
      data/
      runtime/
        python/
        node/
        tools/
        local-ai/
        models/
        npm/
        plugins/
        sources/

Deleting the Rubra folder removes Rubra state, downloaded models, browser profiles, source mirrors and portable tools. Roblox Studio and Microsoft WebView2 remain platform dependencies.

## First launch

Rubra verifies and installs pinned binaries inside the application folder. The default toolchain includes Node.js, Rokit, Rojo, Selene, StyLua, Luau Language Server, Lune, ripgrep, jq, Tripwire, llama.cpp CPU/Vulkan builds and a hardware-gated Qwen3 4B GGUF model.

Source mirrors include ZeroScript, Roblox Studio MCP implementations, Roblox development skill repositories, TestEZ, Fusion, Matter, Zap, ProfileStore, Promise, Blender MCP, mcp-code-search and Roblox AI Studio. Source mirrors are pinned to exact commits.

The local Qwen model is installed automatically only when the machine has at least 20 GB of RAM and 8 GB of free disk space. It is an auxiliary local worker, not a substitute for the stronger web builders and reviewers.

## Studio authority

Rubra prefers the newest StudioMCP.exe paired with an installed Roblox Studio version and uses %LOCALAPPDATA%\\Roblox\\mcp.bat only when no versioned StudioMCP binary is available. Every Studio operation remains scoped to a concrete studio_id.

## Verification policy

Rubra treats test evidence as authoritative. Static checks, Studio read-back, playtest output, screenshots, security scans and independent model review are separate evidence channels. A missing capability is never reported as passed.

Continuous verification can iterate until the verification matrix is green, progress has converged, a capability is genuinely unavailable, or the user cancels. Repeated identical failure fingerprints must become a diagnostic block rather than an endless non-progressing loop.

## Source style

Generated Luau and project code is English-only, uses professional naming and is emitted without comments unless an upstream file format requires a directive or license notice. Rubra never creates v2, v3, final2 or similar naming noise.

## Providers

ChatGPT is the default builder. DeepSeek is the independent reviewer. Gemini is available for research, visual reasoning and second-opinion review. Hunyuan is available for 3D generation when its rendered product surface exposes the required capability. Provider state is discovered from the rendered site and failures are fail-closed.

## Security

The local bridge binds only to loopback. Downloads with published digests are SHA-256 verified before extraction. Archive traversal is blocked. Browser profiles remain local. Rubra does not export provider cookies into private API tokens. Destructive live Open Cloud actions remain capability-gated.

## Project indexing

The existing mcp-code-search integration now starts through a bundled Rubra adapter using the pinned upstream lockfile. Each configured project receives its own storage namespace and MCP process. Switching or clearing the project closes the previous process, and project changes wait for in-flight searches to finish.

Every search refreshes the incremental index before returning evidence. Indexing failures and missing completion confirmations block search rather than reusing stale results. Common credential files, external symlinks, junctions, binary assets and Rubra runtime/browser data are excluded. Project-level `.code-search.toml` cannot redirect storage or select a remote embedding provider. Embedded credentials inside otherwise allowed source files still require project hygiene.

Luau files are explicitly identified as Luau and use the upstream text chunking fallback. This does not claim Luau AST analysis. Initial semantic indexing still requires the upstream dependencies and embedding model; Windows startup and full embedding inference require platform verification.

## Local worker lifecycle

Local scout requests and backend startup are serialized. Vulkan startup failures stop the failed process before trying CPU, and CPU fallback explicitly disables GPU layers. Server output goes to `data/logs/local-ai.log` instead of an undrained pipe. Startup diagnostics read a bounded log tail.

## Build recovery

The missing Changes/Context/History workspace and diff viewer were restored from Zenless commit `fae0baec35763c9a36bda20a48b11e5d21ae0adf`, then adapted to the current API. Build outputs are ignored only at their intended paths so the source workspace remains tracked. Gemini login handling and project-index demo contracts now match the backend. Demo mode reports indexing as unavailable and cannot fabricate index evidence.

The packaging specification tolerates the absent optional vendor directory and icon while still requiring the production frontend and core assets. Static type checking targets the Windows application platform. WebView2 integration tests remain Windows-only.
