# Merge notes

Base: Bolt `project.rar`.

The Lovable archive was **not** overlaid wholesale because it is mostly a generic TanStack/shadcn scaffold and would replace working Zenless-specific features. Only safe/useful ideas/configuration were incorporated:

- Prettier configuration (`.prettierrc`, `.prettierignore`)
- stronger centralized frontend error-description/diagnostic behavior, adapted to the existing Zenless architecture

The Zenless-specific fixes were then completed directly on the Bolt base: attachments, dynamic models/settings persistence, richer diagnostics/dedup, Six View image rendering, production-safe 3D empty state, current-job handling, Review model, Studio actions, typed API/WebSocket contracts, `ws`-based development Bridge, token/origin foundation and Codex handoff docs.
