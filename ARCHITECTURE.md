# Architecture

## Runtime

```text
Windows executable
  -> authenticated loopback bridge
     -> authoritative Core
        -> Orchestrator
           -> browser gateway
           -> Studio protocol client
           -> QA runner
        -> local database and storage
     -> persistent frontend runtime
        -> WebSocket deltas
        -> REST snapshot recovery
        -> Splash or application shell
```

The frontend is a state projection. It cannot declare a provider ready, fabricate QA success, or write to Studio. The persistent runtime owns the local session, WebSocket, event subscriptions, initial hydration, and reconnect hydration. The Splash only renders boot state.

## Startup and shutdown

Immutable resources resolve from the checkout in development or the packaged resource root. Mutable data resolves to `%LOCALAPPDATA%\Zenless` unless a controlled test overrides it.

Public boot stages represent observed startup state. The application shell opens only after both backend UI readiness and a complete frontend snapshot. Shutdown cancels active work, stops QA, closes browser routes and Studio connections, maintains the database, and stops the bridge.

## Local transport

The bridge accepts only loopback traffic on an operating-system-assigned port. It validates exact hosts and origins, creates a random token per process, authenticates REST and WebSocket requests, and assigns request IDs.

JSON, multipart uploads, and files have explicit limits. Attachments use sanitized names and controlled storage. Assets are resolved by ID and must remain inside the authorized data root.

WebSocket events are deltas. A fresh REST snapshot is authoritative after startup and every reconnect. Provider stream fragments are transient; completed responses alone become durable state.

## Pipeline

```text
NEW
  -> CONTEXT
  -> PLAN
  -> VISUAL APPROVAL when enabled
  -> 3D APPROVAL when enabled
  -> INDEPENDENT REVIEW when enabled
  -> CHANGE APPROVAL
  -> APPLY
  -> TEST and bounded repair
  -> FINAL REVIEW
  -> COMPLETE, BLOCKED, or FAILED
```

Required providers are checked before project investigation. The Builder is always required, the Reviewer only when independent review is enabled, and the 3D Generator only for a 3D workflow. Missing authentication returns a structured login requirement and never leaves Chat silent.

## Mutation safety

Each approved mutation has correlated job, request, operation, and mutation identifiers. Script edits follow this sequence:

1. Read current source and compute its hash.
2. Create a durable snapshot.
3. Bind the expected hash to the approved action.
4. Claim an idempotency key in the local database.
5. Read again and verify the precondition.
6. Apply the action through the allowlisted Studio tool.
7. Read back and verify the expected content and hash.
8. Complete the operation with evidence or record failure.

A changed precondition blocks the write. A completed operation may return stored evidence, while an uncertain pending operation is never replayed automatically.

## Persistence and recovery

The local database uses foreign keys, a busy timeout, and WAL. Jobs, messages, events, approvals, operations, context, assets, test runs, and cases are durable. Large files remain in controlled storage with metadata in the database.

Interrupted pre-mutation work may recover as paused. Potentially mutating stages recover as blocked and require inspection before new work.

## Browser and visual workflows

The gateway selects an authenticated embedded or managed browser route by observed capability. Browser selectors and capabilities are runtime dependencies, so discovery failures become diagnostics rather than false readiness.

Visual First produces six separate versioned orthographic PNG files. Deterministic checks validate format, dimensions, hashes, direction, and duplicates before semantic review. Only approved views enter 3D generation. Geometry and texture are separate capability-gated stages that must produce validated local artifacts.

## Packaging

`Zenless.spec` creates one console-free Windows executable containing the production frontend and required resources. Mock Mode is disabled in release builds and unused GUI toolkits are excluded.
