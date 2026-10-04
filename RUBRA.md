# Rubra

Rubra is a portable Windows workspace for autonomous Roblox Studio game development. It is derived from the existing Zenless codebase and composes established Roblox tooling instead of replacing it.

The application keeps mutable state under its own folder, provisions pinned tools on first launch, uses authenticated web sessions for ChatGPT, DeepSeek, Gemini and Hunyuan, connects to Roblox Studio through MCP, and drives planning, implementation, visual inspection, adversarial QA, repair and final verification.

## Product direction

Rubra uses a compact dark interface with a restrained red accent. The UI is intentionally thin. The backend owns state, provider routing, Studio writes, snapshots, skill selection, verification and recovery.

## Portable layout

    Rubra/
      Rubra.exe
      data/
      runtime/
        node/
        tools/
        local-ai/
        models/
        npm/
        plugins/
        sources/
      frontend/

Deleting the Rubra folder removes Rubra state, downloaded models, browser profiles, source mirrors and portable tools. Roblox Studio and Microsoft WebView2 remain platform dependencies.

## First launch

Rubra verifies and installs pinned binaries inside the application folder. The default toolchain includes Node.js, Rokit, Rojo, Selene, StyLua, Luau Language Server, Lune, ripgrep, jq, Tripwire, llama.cpp CPU/Vulkan builds and a hardware-gated Qwen3 4B GGUF model.

Source mirrors include ZeroScript, Roblox Studio MCP implementations, Roblox development skill repositories, TestEZ, Fusion, Matter, Zap, ProfileStore, Promise, Blender MCP, mcp-code-search and Roblox AI Studio. Source mirrors are pinned to exact commits.

The local Qwen model is installed automatically only when the machine has at least 20 GB of RAM and 8 GB of free disk space. It is an auxiliary local worker, not a substitute for the stronger web builders and reviewers.

## Studio authority

Rubra prefers Roblox's current Studio MCP launcher at %LOCALAPPDATA%\\Roblox\\mcp.bat and falls back to versioned StudioMCP.exe discovery. Every Studio operation remains scoped to a concrete studio_id.

## Verification policy

Rubra treats test evidence as authoritative. Static checks, Studio read-back, playtest output, screenshots, security scans and independent model review are separate evidence channels. A missing capability is never reported as passed.

Continuous verification can iterate until the verification matrix is green, progress has converged, a capability is genuinely unavailable, or the user cancels. Repeated identical failure fingerprints must become a diagnostic block rather than an endless non-progressing loop.

## Source style

Generated Luau and project code is English-only, uses professional naming and is emitted without comments unless an upstream file format requires a directive or license notice. Rubra never creates v2, v3, final2 or similar naming noise.

## Providers

ChatGPT is the default builder. DeepSeek is the independent reviewer. Gemini is available for research, visual reasoning and second-opinion review. Hunyuan is available for 3D generation when its rendered product surface exposes the required capability. Provider state is discovered from the rendered site and failures are fail-closed.

## Security

The local bridge binds only to loopback. Downloads with published digests are SHA-256 verified before extraction. Archive traversal is blocked. Browser profiles remain local. Rubra does not export provider cookies into private API tokens. Destructive live Open Cloud actions remain capability-gated.
