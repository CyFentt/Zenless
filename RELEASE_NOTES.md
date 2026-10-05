# Rubra 2.1.0 prerelease

This release addresses the desktop failures reported during 2.0.3 testing.

- Studio reconnects when opened after Rubra; late MCP installation is rediscovered. Structured tree results, hierarchy, project identity, and script content are exposed in the editor.
- Play Test works for the open place without an AI build task. Its session is persisted, can be stopped across pages, and closes owned Play execution on cancellation.
- Guest text fields no longer count as authentication. Login waits for stable account evidence; closing a window releases it for retry. Different provider requests run independently, and busy health probes respond without waiting behind a login.
- Slow MCP, chat preflight, indexing, and model operations run outside the HTTP event loop. Tool preparation starts after the desktop is available.
- Local models can build and review text/code, with separate inference contexts, bounded completion continuation, sequential model loading, and Vulkan-to-CPU fallback. Qwen2.5 Coder 7B is pinned to an upstream revision and SHA-256.
- Settings rows are aligned, tooltips use Radix collision handling, model controls report supported options, and labels have improved contrast. The frameless shell has its own window controls, one brand icon, notifications, motion respecting reduced-motion, and concise chat process updates.
- Existing Roblox skill sources use the correct portable runtime root. Ordinary code tasks no longer require the optional web 3D generator.

Install `Rubra-Setup.exe`; the default is `%LOCALAPPDATA%\Programs\Rubra`. Existing data and downloaded runtimes are preserved during updates. Initial model preparation requires several GB of downloads and free disk space; progress is visible in Settings → Models.

Validation: Python, frontend unit, HTTP/child-process integration, and Chromium UI tests pass. This package has not been executed on native Windows or against real Roblox Studio and provider accounts in this environment. Authentication selectors, Windows window controls, Vulkan allocation, live model output quality, and real Studio lifecycle must still be confirmed on the target PC. The local model path handles text/code; it does not replace web image or 3D generation.
