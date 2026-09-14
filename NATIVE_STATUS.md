# Native workspace integration

The Python Qt workspace is available through `RUN.bat` or `main.py --native-ui`.
The Core, provider adapters, authorized Studio transport, SQLite history and web detail workspaces remain shared.

Implemented: native titlebar, vector controls, conversation history, asynchronous requests, selected-job isolation, attachment submission, cancellation, interface audio and access to the existing detailed approval workspace.

The migration is in progress. The detailed workspaces still use the existing embedded React interface. Full native settings, matching workspace menus, loading animations, geometry validation, streaming text rendering and complete native approval cards remain pending. This is not a final design-equivalent release.

## Build

Run `BUILD.bat` with Python 3.14 and Node.js available. It creates an isolated build environment, installs dependencies, runs the canonical checks and builds `dist/Zenless.exe`. Run `RUN.bat` to select the native interface. The existing `build.ps1` installer path remains available separately.

Provider authentication is manual. Build authentication cleanup remains enabled. Provider quota is never bypassed, and unavailable external capabilities are not reported as passed.

## Verified in this integration

- Backend before native additions: 120 tests and 5 subtests passed.
- Native history isolation and escaped message rendering: 2 tests passed.
- Frontend regression suite: 71 tests passed; lint, type checking and production build passed.
- Browser integration and native regression checks after shutdown ordering correction: 5 tests passed.
- Python type checking: zero errors.
- Earlier native shell startup and clean shutdown: passed from source.

Full updated GUI validation, frozen native package validation and live authenticated provider flows remain pending.
The latest source startup returned successfully but emitted a browser cancellation warning. Shutdown ordering was corrected afterward; a full repeated GUI shutdown check remains pending.
