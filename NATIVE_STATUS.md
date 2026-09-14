# Native workspace integration

The Python Qt workspace is available through `RUN.bat` or `main.py --native-ui`.
The Core, provider adapters, authorized Studio transport, SQLite history and web detail workspaces remain shared.

Implemented: native titlebar, vector controls, conversation history, asynchronous requests, selected-job isolation, attachment submission, cancellation, interface audio and access to the existing detailed approval workspace.

The migration is in progress. Task/provider controls, workspace menus, animated history, streamed text and code/image approval actions now run in the native interface. Detailed visual previews, 3D inspection and logs still use the existing embedded React interface. Matching loading animations, native visual approval previews and full release validation remain pending. This is not a final design-equivalent release.

## Build

Run `BUILD.bat` with Python 3.14 and Node.js available. It creates an isolated build environment, installs dependencies, runs the canonical checks and builds `dist/Zenless.exe`. Run `RUN.bat` to select the native interface. The existing `build.ps1` installer path remains available separately.

Provider authentication is manual. Build authentication cleanup remains enabled. Provider quota is never bypassed, and unavailable external capabilities are not reported as passed.

## Verified in this integration

- Backend before native additions: 120 tests and 5 subtests passed.
- Native history isolation and escaped message rendering: 2 tests passed.
- Native history, stream isolation, message escaping and shell geometry/navigation: 4 tests passed.
- Full Python suite with native integration: 124 tests and 5 subtests passed.
- Frontend regression suite: 71 tests passed; lint, type checking and production build passed.
- Browser integration and native regression checks after shutdown ordering correction: 5 tests passed.
- Python type checking: zero errors.
- Earlier native shell startup and clean shutdown: passed from source.

Full updated GUI validation, frozen native package validation and live authenticated provider flows remain pending.
The repeated source startup and shutdown check passed without the earlier browser cancellation warning. The native window was inspected at 680 by 450 pixels; geometry and workspace navigation checks also passed at the default 900 by 590 size.
