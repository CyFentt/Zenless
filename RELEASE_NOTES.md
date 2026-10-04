# Rubra 2.0.2 prerelease

The installer defaults to `%LOCALAPPDATA%\Programs\Rubra`, creates a Start menu shortcut and registers an uninstaller. Updates preserve application data and downloaded tools. Uninstall removes program files while keeping data. The ZIP remains portable.

The supplied ruby icon is included in the launcher, installer and desktop window. The interface follows the OpenCode Studio navigation structure with a collapsible sidebar, recent tasks and a spacious workspace, using angular controls and black, red and white. Green and amber indicate success and pending/warning states.

A startup defect exposed the native window through the JavaScript API, causing pywebview to recursively inspect native objects. The window reference is now private and only the folder picker is exposed; a regression test runs the real pywebview API discovery. UI readiness no longer waits for Studio discovery. Failed hydration offers a retry instead of directing users to inaccessible settings. Legacy partial provider settings are merged with current defaults.

Additional fixes cover MCP pagination and structured content, ambiguous Studio selection, complete script readback verification, sequential edits, creation preconditions, playtest cleanup and evidence, skipped static checks, optional tool installation failures, provider status routing and WebSocket reconnection.

## Requirements

Windows 10 or later, x64; Internet access for first-launch tool downloads and provider login; Microsoft WebView2; Roblox Studio with MCP enabled and the intended place open. Close Rubra before updating. An older portable folder can be retained separately; this installer does not silently migrate it.

## Validation

Ruff and Pyright pass. Backend: 98 passed, one Windows-only test skipped. Frontend: ESLint, TypeScript and 56 tests pass; production build succeeds. Windows package structure is checked separately by `scripts/verify_portable.py`.

Windows execution, real provider authentication and live Roblox round trips remain unverified in this Linux environment. The screenshot symptoms informed the fixes but are not proof of a successful Windows retest. GitHub Actions was blocked by the repository account billing lock during the previous validation attempt. This build remains a prerelease.
