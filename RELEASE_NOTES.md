# Rubra 2.0.1

Rubra now ships as a Windows x64 package with its own Python runtime and the production React interface. `Rubra-Setup.exe` extracts the application into a new folder. `Rubra-Windows.zip` contains the same application for manual extraction. Open `Rubra.exe` from the extracted folder; a global Python installation is unnecessary.

The distribution composes the official Python embeddable package, the existing application, pinned Windows wheels and NSIS. Published dependency digests are checked before extraction. The package includes upstream Python and dependency licenses, source commit metadata and SHA-256 checksums.

Startup failures during toolchain setup now produce the same startup log and error dialog as interface failures. An absent optional icon no longer reaches WebView2. The portable WebView2 helper uses the bundled console interpreter with hidden execution and pipes for its protocol. Remaining startup and provider window titles use Rubra branding.

This package includes the previous Rubra work: isolated project indexes with incremental refresh and credential-file exclusions, a pinned mcp-code-search adapter, serialized local AI startup with Vulkan-to-CPU fallback, the restored Changes/Context/History workspace and diff viewer, provider login error handling and the authenticated local application bridge.

## Requirements and use

- Windows 10 or later, x64, and a writable application folder.
- Internet access for the first launch, provider authentication and tool/model downloads.
- Roblox Studio with the current Studio MCP capability and an open place.
- Microsoft WebView2. Startup can provision the Microsoft runtime when it is missing.

Select a new folder during setup. Existing folders are refused to protect saved state. After extracting, open `Rubra.exe`, complete provider authentication and select the project folder in Settings. Keep the entire application folder together. Deleting it removes Rubra state and portable tools; Roblox Studio and Microsoft WebView2 remain installed.

## Validation status

The Linux-side checks pass: Ruff, Pyright, 82 backend tests, ESLint, TypeScript, 53 frontend tests and the production Vite build. One WebView2 integration test is skipped because it requires Windows. Package checks cover all 21 installed Python dependencies and 63 Windows binaries, including x64 Python extensions. The package uses the production frontend with demo mode disabled.

Windows application execution, WebView2 rendering, real provider logins and live Roblox Studio round trips have not been verified in this environment. GitHub Actions cannot start because the repository account has a billing lock. Wine cannot run because the execution environment denies its required Unix socket. This release is a prerelease until Windows validation is completed; it does not claim that the full live workflow has passed.
