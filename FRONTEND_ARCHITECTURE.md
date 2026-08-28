# ZENLESS — Frontend Architecture

## Overview

Zenless is a Roblox development workstation controlled by AI. The frontend is a React + TypeScript + Vite SPA that communicates with the Zenless Bridge via REST and WebSocket. The frontend never talks directly to ChatGPT, DeepSeek, Hunyuan, or Roblox Studio — everything goes through the Bridge.

## Tech Stack

- **React 18** — UI library
- **TypeScript** — strict mode, full type safety
- **Vite 5** — build tool, dev server, code splitting
- **Tailwind CSS 3** — utility-first styling, custom dark theme
- **Zustand 5** — lightweight global state
- **Three.js + React Three Fiber + Drei** — 3D model viewer (lazy-loaded)
- **Lucide React** — icons
- **Vitest + Testing Library** — tests

## Directory Structure

```
src/
  App.tsx                  Entry point, lazy page router, boot gate
  main.tsx                 React root
  index.css                Tailwind + custom utilities, fonts

  components/              Reusable UI components
    AppShell.tsx           Layout shell (sidebar + topbar + content)
    Sidebar.tsx            Vertical nav with icons + tooltips
    TopBar.tsx             Compact status bar (project, stage, connections)
    StatusDot.tsx          StatusDot + StatusBadge
    Tabs.tsx               Tabs, Segmented, Toggle, Select
    Tooltip.tsx            Minimal tooltip
    Modal.tsx              Modal + Drawer
    Pipeline.tsx           Compact pipeline stepper
    ErrorBoundary.tsx      React error boundary

  features/                Feature pages (lazy-loaded)
    boot/
      SplashScreen.tsx     Boot sequence + data initialization
    home/
      HomePage.tsx         Current task, pipeline, system, recent, errors
    chat/
      ChatPage.tsx         Chat interface (messages + composer + options)
      TaskOptionsPanel.tsx Side panel for task configuration
    build/
      BuildPage.tsx        Tabs: Context, Changes, History
      DiffViewer.tsx       IDE-style diff with edit mode
    visual/
      VisualPage.tsx       Tabs: Views (6-view grid), 3D, Assets
      ModelViewer.tsx      React Three Fiber GLB/GLTF viewer
    studio/
      StudioPage.tsx       Studio hierarchy tree + details panel
    test/
      TestPage.tsx         Play/stop, log console, error detail modal
    settings/
      SettingsPage.tsx     Tabs: General, Models, Links, Logs

  services/                API + WebSocket layer
    index.ts               Service factory (mock vs real)
    diagnostics.ts         FrontendDiagnostics (error capture)
    api/
      types.ts             ZenlessAPI interface (full contract)
      realApi.ts           RealZenlessAPI — HTTP transport only
    websocket/
      socket.ts            RealZenlessSocket — WebSocket with reconnect
      mockSocket.ts        MockZenlessSocket — simulated events
    mock/
      mockApi.ts           MockZenlessAPI — in-memory mock backend
      mockData.ts          All mock data (single source)

  store/                   Zustand state
    index.ts               Single store with all slices
    eventHandler.ts        Maps WebSocket events → store updates

  types/
    index.ts               All TypeScript types + discriminated union events
```

## State Management

Zustand single store with flat state. Selectors used in components to prevent unnecessary re-renders. The store holds only UI-relevant state — the Bridge is the source of truth.

### Store Slices

- **boot**: `booted`, `bootSteps`
- **navigation**: `activePage`
- **socket**: `socketStatus`
- **connections**: `connections`, `agents`
- **jobs**: `jobs`, `currentJobId`
- **chat**: `messages`, `streamingMessageId`, `streamingContent`
- **context**: `contextItems`
- **changes**: `changedFiles`, `selectedFileId`
- **visual**: `views`, `conceptVersion`, `conceptStatus`, `conceptPrompt`
- **model**: `modelInfo`
- **assets**: `assets`
- **studio**: `studioState`, `studioTree`, `selectedStudioNode`, `studioQuery`
- **test**: `testState`, `testLogs`, `logFilter`
- **settings**: `settings`
- **diagnostics**: `diagnostics`

## API Layer

### ZenlessAPI Interface (`src/services/api/types.ts`)

Defines all methods the frontend needs. Both `RealZenlessAPI` and `MockZenlessAPI` implement it.

### RealZenlessAPI (`src/services/api/realApi.ts`)

- Pure HTTP transport — no business logic
- Centralized `fetch` with JSON, headers, timeouts
- `AbortController` per request for timeout cancellation
- `X-Zenless-Token` header from localStorage (startup session token)
- `ApiError` class with status, message, request ID
- Base URL from `VITE_ZENLESS_API_BASE`

### MockZenlessAPI (`src/services/mock/mockApi.ts`)

- In-memory state with mutable arrays
- Simulated delays (50-300ms)
- Returns cloned data to prevent mutation
- Exposes mock-specific helpers for the mock socket

## WebSocket

### RealZenlessSocket (`src/services/websocket/socket.ts`)

- Single connection to `VITE_ZENLESS_WS_BASE/ws`
- States: CONNECTING → CONNECTED → RECONNECTING → DISCONNECTED
- Exponential backoff (max 5 attempts, capped at 8s)
- Manual disconnect cancels reconnect
- Typed events via discriminated union

### MockZenlessSocket (`src/services/websocket/mockSocket.ts`)

- Simulates connection delay
- Emits events: Hunyuan login→ready, Studio offline→online
- Simulates chat streaming (word-by-word)
- Simulates test log streaming when test is running

## Events

All WebSocket events are typed via `ZenlessEvent` discriminated union in `src/types/index.ts`. The `handleEvent` function in `src/store/eventHandler.ts` maps each event type to store mutations.

## Code Splitting

All feature pages are lazy-loaded via `React.lazy`. The 3D viewer (`ModelViewer.tsx`) is lazy-loaded within the Visual page. The DiffViewer is lazy-loaded within the Build page. This keeps Three.js and other heavy code off the initial bundle.

## 3D Viewer

`ModelViewer.tsx` uses React Three Fiber with:
- `OrbitControls` for rotate/zoom
- `Environment` for studio lighting
- `useGLTF` for GLB/GLTF loading
- Grid helper for spatial reference
- Dark background matching the app theme

In mock mode, a geometric placeholder is shown instead of a real GLB.

## Diagnostics

`FrontendDiagnostics` (`src/services/diagnostics.ts`) captures:
- `window.onerror`
- `unhandledrejection`
- React `ErrorBoundary` errors
- API errors (reported by callers)

No silent `catch {}` blocks. All errors are surfaced to the diagnostics store and visible in Settings → Logs.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `VITE_ZENLESS_MOCK` | `true` = mock mode, `false` = production | `true` |
| `VITE_ZENLESS_API_BASE` | REST API base URL | `http://127.0.0.1:8787` |
| `VITE_ZENLESS_WS_BASE` | WebSocket base URL | `ws://127.0.0.1:8787` |

## Design System

### Colors
- Background: `#050505` (ink-950)
- Surfaces: `#090909`–`#121212` (ink-900 to ink-700)
- Borders: `#1a1a1a`–`#242424` (ink-600 to ink-500)
- Text: `#f2f2f2` (ink-0), secondary `#858585` (ink-150)
- Accent: white
- States: very dim green (ok), dim amber (warn), deep red (err)

### Typography
- UI: Inter (300/400/500/600)
- Code/Logs: JetBrains Mono (400/500)
- No large text sizes — hierarchy via weight, spacing, contrast

### Borders & Radius
- 1px borders, low contrast
- 0-6px radius — no rounded mobile-style cards

### Animations
- 150-250ms transitions
- opacity, transform, subtle blur
- No bouncing, spinning, or neon flashing

## Build

```bash
npm install
npm run build      # production build
npm run lint       # ESLint
npm run typecheck  # TypeScript check
npm test           # Vitest
```
