# QA architecture

## Evidence boundary

- `PASSED`: the case executed and the observed assertion passed.
- `FAILED`: the case executed and produced an error or mismatch.
- `SKIPPED`: an advertised requirement was unavailable or the case did not apply.
- `STALE`: the evidence predates the latest relevant mutation.
- `NOT RUN`: no execution was attempted for this release check.

Source inspection cannot turn a Play test, provider operation, visual workflow, installer test, or clean-machine check into `PASSED`.

## Canonical flow

Automatic QA is part of the project pipeline after the final approved mutation reaches Studio:

```text
APPLY -> READ-BACK -> INVALIDATE OLD EVIDENCE -> TEST
  -> bounded FIX -> APPLY -> READ-BACK -> RETEST
  -> FINAL VERIFICATION
```

The manual test API remains available for diagnostics and reruns, but it is not the normal completion path. A later mutation changes earlier `PASSED` or `FAILED` runs to `STALE` before final verification.

## Profiles

| Profile | Maximum duration | Maximum scenarios | Maximum clients | Chaos iterations |
| --- | ---: | ---: | ---: | ---: |
| `SMOKE` | 45 seconds | 4 | 1 | 0 |
| `STANDARD` | 120 seconds | 10 | 2 | 2 |
| `DEEP` | 240 seconds | 18 | 4 | 5 |

`MINIMUM` effort selects `SMOKE`. `MAXIMUM` effort or high risk selects `DEEP`. Other tasks select `STANDARD`. Each run records its profile, seed, plan, cases, duration, counts, output, failures, and mutation relationship.

## Scenario compiler and executor

AI-generated scenario descriptions are inputs to a bounded compiler, not executable code. The internal step vocabulary is:

`START_PLAY`, `WAIT`, `MOVE_CHARACTER`, `KEY_PRESS`, `MOUSE_CLICK`, `CALL_SAFE_TEST_HARNESS`, `ASSERT_PROPERTY`, `ASSERT_OUTPUT_NOT_CONTAINS_ERROR`, `CAPTURE_SCREEN`, and `STOP_PLAY`.

The current compiler emits Start, a bounded wait, optional bounded movement intent, Output assertion, optional screen capture, and Stop. The executor maps only compatible advertised Studio tools. Unsupported input schemas and other unmapped steps are `SKIPPED`. It never executes LLM-generated Luau.

Cancellation and deadlines are checked between steps. If Play starts, cleanup requests Stop in `finally`, including failure and cancellation paths.

## Capability rules

| Area | Execution | Missing capability |
| --- | --- | --- |
| Edit, Play, Stop, Output | Selected Studio target and advertised tools | Fail or skip according to criticality |
| Project test runner | Explicit project or Studio harness | `SKIPPED`, never inferred from filenames |
| Feature scenarios | Compiled bounded DSL | Unsupported step is `SKIPPED` |
| Multiplayer | Opt-in bounded project harness | `SKIPPED` without the exact protocol |
| Virtual input | Validated Studio-side schema during Play | `SKIPPED` when unavailable |
| Device emulation | Apply, capture, read-back, and restore | `SKIPPED` when unavailable; fail on unsafe restore |
| Persistent data | Isolated namespace and idempotent cleanup | Block when isolation is unsafe |

Multiplayer and device tests are capability-dependent. Transport availability does not prove gameplay behavior.

## Visual and 3D evidence

Each visual version contains separate `FRONT`, `BACK`, `LEFT`, `RIGHT`, `TOP`, and `BOTTOM` PNG assets. Deterministic checks record dimensions, MIME, hash, direction, duplicates, version, and authorization. Generation publishes per-view lifecycle and ready events; approval updates the stored artifact and publishes one aggregate approval event.

3D evidence is separated into upload acceptance, geometry, texture, authorized download, local structural validation, and approval. A provider message or URL alone cannot establish model readiness.

## Final review policy

Independent review runs only when task policy enables it. When disabled, final verification still checks current mutation evidence, current QA status, and console findings. It is not labeled independent review.

## Development gates

The backend gate is:

```powershell
python -m ruff check .
python -m pyright
python -m pytest -o addopts= -q
```

Frontend lint, types, tests, and production build run only with `build.ps1 -FrontendIntegration` after frontend integration. Frozen startup, installer install/uninstall, live Studio, live providers, and clean Windows are separate release gates.

Jest Roblox is currently an on-demand catalog entry, not a globally installed or automatically injected runner. Existing project test conventions remain authoritative. No release should report Jest integration unless a real compatible project test was executed.

## Manual external checklist

When resources are available, record these independently:

1. Live Studio discovery, target selection, tree read, controlled mutation, read-back, Play, Output, capture, input when advertised, and Stop.
2. Login, restart persistence, streaming, mode switching, capability refresh, file limits, cancellation, and recovery for each enabled provider.
3. Six-view upload, geometry, texture, download, and local model validation for the 3D provider.
4. Per-user setup, first launch without developer tooling, repair, Keep Settings uninstall, Full Remove uninstall, and reinstall in a clean Windows 11 x64 profile.

Unavailable resources remain `NOT RUN` or `LOGIN_REQUIRED`; they are never inferred from unit tests.
