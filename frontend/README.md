# Zenless frontend

This directory is the canonical React, TypeScript, and Vite source. Production serves `dist/` through the authenticated local bridge. `bridge/` and Mock Mode are development fixtures only.

## Development

```powershell
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

The complete release gate is `../build.ps1`. It disables Mock Mode for production and packages the executable only after every Python and frontend gate passes.

## Constraints

- The UI requests actions and renders authoritative state and events.
- Do not create a second frontend source tree at the repository root.
- Do not edit `dist/` manually.
- Never expose credentials, cookies, or arbitrary local paths to the frontend.
