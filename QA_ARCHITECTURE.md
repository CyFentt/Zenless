# QA architecture

## Evidence states

- `PASSED`: the case ran and the observed condition passed.
- `FAILED`: the case ran and produced an error or mismatch.
- `SKIPPED`: the required capability was unavailable or the case did not apply.
- `NOT RUN`: no execution was attempted for this verification.

Source inspection cannot turn a Play test, provider operation, visual asset, or clean-machine check into `PASSED`.

## Release gate

`build.ps1` stops at the first failure and reaches packaging only after:

1. Ruff lint and formatting checks.
2. Pyright type checking.
3. Backend pytest coverage.
4. Clean frontend dependency installation.
5. ESLint and TypeScript checks.
6. Frontend Vitest coverage.
7. A production Vite build with mocks disabled.

This gate verifies local code, contracts, persistence, transport, and packaging. It does not prove external services or gameplay.

## QA profiles

| Profile | Intended use | Scope |
| --- | --- | --- |
| `SMOKE` | Low-risk local or visual change | Short Play and focused checks |
| `STANDARD` | Common change | Evidence, Edit state, Play output, and safe input smoke |
| `DEEP` | Persistence, remotes, physics, multiplayer, or high risk | Standard coverage plus device and opt-in multiplayer harnesses |

Each run records an ID, deterministic seed, plan, cases, duration, pass/skip/fail counts, output, and reproducible failures. Cancellation and maximum duration are enforced. Cleanup always requests Stop when Play was started.

## Capability rules

| Area | Execution | Missing capability |
| --- | --- | --- |
| Edit, Play, Stop, Output | Connected Studio tools | Explicit failure or skip by criticality |
| Project test runner | Explicit project or Studio harness | `SKIPPED`, never inferred from filenames |
| Multiplayer | Opt-in project harness with bounded players and time | `SKIPPED` without the exact contract |
| Virtual input | Validated client input schema during Play | `SKIPPED`, never simulated through internal state |
| Device emulation | Validated apply, capture, read-back, and restore | `SKIPPED` without capability; failure on incomplete restore |
| Persistent data | Isolated test namespace and idempotent cleanup | Block when isolation is unsafe |

The multiplayer harness belongs to the game and must declare its protocol. Transport smoke does not replace gameplay assertions.

## Visual evidence

Each visual version must contain six distinct PNG files. Verification records format, non-empty content, minimum dimensions, SHA-256 per view, duplicate detection, direction, version metadata, and authorized asset rendering.

Semantic review compares identity, proportions, colors, details, and orientation against the master specification. Regeneration creates a new version and preserves prior evidence.

## 3D evidence

The adapter records observed capabilities and upload limits before sending assets. Evidence separately covers accepted references, structurally valid geometry, texture application, authorized download, local viewing, and independent regeneration targets.

Missing controls, incompatible limits, empty downloads, and invalid local models fail the stage. A URL or provider message is not a validated model.

## External verification

Final release verification should observe provider login persistence, streaming, independent reviews, the six-view workflow, geometry and texture generation, Studio approval and read-back, Play and Stop, recovery after safe interruption, and recovery after a potentially mutating interruption.

When no real Studio connection, authenticated provider session, or clean Windows machine is available, those checks remain `NOT RUN` and are reported as such.
