# Installation architecture

## Artifacts

`Zenless.spec` builds a console-free, single-file Windows executable at `dist\Zenless.exe`. It contains the Python runtime, backend dependencies, compiled frontend bundle, assets, vendor resources, license, and notice. No Python, Node, npm, Vite, Git, or test runner is required for normal launch.

`installer\Zenless.nsi` builds `dist\ZenlessSetup.exe`. The installer is per-user and declares `RequestExecutionLevel user`; normal installation and launch do not request Administrator.

## Installed layout

```text
%LOCALAPPDATA%\Programs\Zenless\
  Zenless.exe
  Uninstall Zenless.exe

%LOCALAPPDATA%\Zenless\
  zenless.db
  browser-profile\
  webview-profile\
  ui-profile\
  browser-runtime\
  runs\
  snapshots\
  visuals\
  models\
  tools\
  logs\
```

Setup creates current-user Desktop and Start Menu shortcuts, `HKCU\Software\Zenless`, and `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Zenless`. It creates no service or scheduled task.

## First launch

Startup displays the native splash, checks WebView2, opens durable state, binds the authenticated loopback bridge, starts Core services, and opens the WebView2 shell. System diagnostics report Windows version, architecture, free disk, available memory, WebView2, detected Studio installations, and structured setup issues.

If WebView2 is absent, Zenless uses the bundled or official bootstrapper, validates a valid Microsoft Authenticode signer, runs the installer silently, and verifies the runtime afterward. Managed Chromium is provisioned only when its route is needed. Optional development and 3D tools are not part of first-run installation.

Component repair supports `WEBVIEW2`, `MANAGED_CHROMIUM` or `BROWSER_RUNTIME`, and `FRONTEND_BUNDLE`. Repair is component-scoped and does not reinstall the application.

## Uninstall modes

Windows Apps and `POST /api/system/uninstall` invoke the installed uninstaller. Interactive uninstall presents a native Keep Settings and Sessions choice that is enabled by default. Quiet Windows uninstall also preserves data by default; Full Remove requires the explicit `/REMOVEDATA` mode selected by Zenless Settings.

- `KEEP_SETTINGS`: removes installed binaries, shortcuts, and Zenless registry entries while retaining `%LOCALAPPDATA%\Zenless`.
- `FULL_REMOVE`: performs the same installed-file cleanup and removes `%LOCALAPPDATA%\Zenless`.

Full Remove deletes Zenless-owned application data. It does not target Studio, user projects, unrelated browser profiles, other applications, general Windows temporary data, or unrelated registry keys. The backend accepts only the exact per-user install and data roots. The portable executable has no installed uninstaller, so its Settings uninstall endpoint returns a controlled error.

Settings-initiated uninstall passes the current Zenless process identifier directly to NSIS. The uninstaller waits for that exact process to exit before deleting files, uses a working directory outside the installation root, reports partial cleanup as a nonzero exit, and does not use a shell or encoded command.

## Build

Developer prerequisites are Python with `requirements-dev.txt`, a compiled `frontend\dist`, and NSIS 3.12 for setup output.

```powershell
.\build.ps1
```

The default sequence is Ruff, Pyright, pytest, compiled-frontend presence, PyInstaller, and NSIS. It does not install frontend dependencies or modify frontend source.

```powershell
.\build.ps1 -SkipInstaller
.\build.ps1 -FrontendIntegration
```

`-SkipInstaller` produces only the portable executable. `-FrontendIntegration` additionally runs `npm ci`, ESLint, TypeScript, Vitest, and the production frontend build; use it only after frontend changes are integrated.

## Release verification

A complete release records these independently:

1. Ruff, Pyright, and pytest results.
2. PyInstaller output and frozen smoke startup.
3. NSIS compilation, silent per-user installation, shortcut and registry checks, launch, Keep Settings uninstall, Full Remove uninstall, and reinstall.
4. First launch on a clean Windows 11 x64 profile without developer tooling.
5. WebView2 absent and present paths.
6. Live provider login and restart persistence.
7. Live Studio discovery, selection, mutation, Play, Output, and Stop.

Build success alone does not certify clean-machine, provider, or Studio behavior. Executables are not described as signed unless signing was performed and verified for that release.
