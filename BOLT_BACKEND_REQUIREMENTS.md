# Backend contract handoff

This file defines the backend-vnext contract for frontend integration. The backend remains authoritative. Frontend state must rehydrate from REST at startup and after every WebSocket reconnect, then apply WebSocket events as deltas.

## Transport

`GET /api/session` returns `{ "token": string }`. Every other `/api/*` request requires `X-Zenless-Token: <token>`. WebSocket connects to `/ws?token=<token>`.

```ts
type BackendEvent<T extends object = Record<string, unknown>> = {
  type: string
  data: T
}

type BackendError = {
  code: string
  message: string
  details?: Record<string, unknown>
}
```

Successful endpoints return the documented object or array directly. They do not use a shared success envelope. Every response includes `X-Request-Id`.

## Shared types

```ts
type AuthState =
  | 'UNKNOWN'
  | 'CHECKING'
  | 'LOGIN_REQUIRED'
  | 'LOGIN_WINDOW_OPEN'
  | 'AUTHENTICATING'
  | 'CHALLENGE'
  | 'AUTHENTICATED'
  | 'VERIFYING_PERSISTENCE'
  | 'READY'
  | 'EXPIRED'
  | 'ERROR'

type ProviderSupport = 'VERIFIED' | 'BETA' | 'EXPERIMENTAL' | 'UNSUPPORTED'
type ProviderRole = 'BUILDER' | 'REVIEWER' | 'VISUAL' | 'RESEARCH' | '3D'
type FeatureMode = 'AUTO' | 'ON' | 'OFF'
type Effort = 'AUTO' | 'MINIMUM' | 'MEDIUM' | 'MAXIMUM'
type ChatMode = 'PROJECT' | 'TEMP'

type ModeCapabilities = {
  supportsText: boolean
  supportsReasoning: boolean
  reasoningLevels: string[]
  supportsSearch: boolean
  supportsFiles: boolean
  acceptedMimeTypes: string[]
  acceptedExtensions: string[]
  maxFiles: number
  maxBytesPerFile: number
  supportsImages: boolean
  supportsVision: boolean
  supportsAudio: boolean
  supportsArchives: boolean
  supportsCodeExecution: boolean
  supportsTools: boolean
  supportsImageGeneration: boolean
  supports3DGeneration: boolean
  supportsGeometry: boolean
  supportsTexture: boolean
  supportsDownload: boolean
  supportsCancel: boolean
  supportsStreaming: boolean
}

type ProviderMode = {
  id: string
  label: string
  source: string
  capabilities: ModeCapabilities
}

type ProviderSession = {
  providerId: string
  adapter: string
  lastSuccessfulRoute: string
  lastAuthenticatedAt: string
  lastVerifiedAt: string
  selectedModel: string
  selectedMode: string
  capabilityVersion: string
  healthState: string
}

type LiveCapabilities = ModeCapabilities & {
  send_text: boolean
  upload_files: boolean
  file_types: string[]
  max_image_inputs: number
  cancel: boolean
  select_model: boolean
  get_models: boolean
  select_mode: boolean
  geometry: boolean
  texture: boolean
  download_artifact: boolean
  source: string
  [key: string]: unknown
}

type Provider = {
  providerId: string
  displayName: string
  webUrl: string
  support: ProviderSupport
  adapter: string
  roles: ProviderRole[]
  modes: ProviderMode[]
  enabled: boolean
  selection: { route?: 'webview2' | 'playwright'; mode?: string; model?: string }
  authState: AuthState
  route: string
  detail?: string
  session?: ProviderSession | null
  liveCapabilities: LiveCapabilities | null
}
```

Provider profile paths and cookies are private backend state and are never returned to the frontend.

## Readiness

```ts
type ReadinessStep = {
  id: string
  label: string
  state: string
  required: boolean
  detail?: string
}

type ProviderReadiness = {
  providerId: string
  displayName: string
  authState: AuthState
  route: string
  required: boolean
  detail: string
}

type StudioInstance = {
  id: string
  label: string
  placeId: unknown
  universeId: unknown
  project: unknown
  raw: Record<string, unknown>
}

type StudioCapability = {
  name: string
  category: 'READ' | 'SEARCH' | 'VISUAL' | 'PLAYTEST' | 'INPUT' | 'RUNTIME' | 'ASSET' | 'MUTATION' | 'ADMIN_PROJECT'
  description: string
  inputSchema: Record<string, unknown>
}

type StudioDiscovery = {
  state:
    | 'MCP_RUNTIME_AVAILABLE'
    | 'MCP_CONNECTED'
    | 'STUDIO_NOT_RUNNING'
    | 'STUDIO_INSTANCE_FOUND'
    | 'MULTIPLE_STUDIOS'
    | 'PROJECT_SELECTED'
    | 'PROJECT_READY'
    | 'MCP_SETUP_REQUIRED'
    | 'MCP_RUNTIME_ERROR'
    | 'NO_PROJECT'
  selectedStudioId: string | null
  detail: string
  studios: StudioInstance[]
  capabilities?: StudioCapability[]
}

type SetupIssue = {
  code: string
  severity: string
  message: string
  recovery: string
}

type SystemSnapshot = {
  platform: string
  architecture: string
  disk: { free: number; total: number }
  memory: { total: number; available: number; loadPercent: number } | null
  webView2: string | null
  studioInstallations: string[]
  issues: SetupIssue[]
}

type ReadinessSnapshot = {
  state: 'READY' | 'ACTION_REQUIRED' | 'DEGRADED'
  canRunProjectTasks: boolean
  checkedAt: number
  checks: ReadinessStep[]
  steps: ReadinessStep[]
  providers: ProviderReadiness[]
  studio: StudioDiscovery
  storage: { bytesUsed: number; budgetBytes: number; withinBudget: boolean }
  system: SystemSnapshot
}
```

`GET /api/readiness` returns `ReadinessSnapshot`. `GET /api/readiness?refresh=1` bypasses the three-second cache, performs bounded provider probes, refreshes Studio discovery, and verifies the required Studio tool advertisements. Render `steps` in order. Do not enable project submission unless `canRunProjectTasks` is true.

`READINESS_CHANGED` data is the full `ReadinessSnapshot`.

## Providers

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/api/providers` | Query `refresh=1` optional | `Provider[]` |
| `GET` | `/api/providers/:id` | Query `refresh=1` optional | `Provider` |
| `POST` | `/api/providers/:id/login` | Empty object | `{ ok: boolean }` |
| `POST` | `/api/providers/:id/refresh` | Empty object | `Provider` |
| `POST` | `/api/providers/:id/select` | `{ route?: 'webview2' | 'playwright', mode?: string, model?: string }` | `Provider` |
| `POST` | `/api/providers/:id/assign-role` | `{ role: ProviderRole }` | `Provider` |

Login is asynchronous. `{ ok: true }` means the worker was scheduled or already running, not that authentication succeeded. Complete UI state from login events and a provider/readiness refresh. Do not offer Login, Select, or Assign for `enabled: false`.

Mode hints are not authority. Selecting `instant` or `expert` changes the visible provider control and succeeds only after the selected state is verified and capabilities are reprobed. When `liveCapabilities` exists, immediately disable controls that it reports unsupported. Expert-like modes can legitimately report `supportsFiles: false`.

## Studios

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/api/studios` | Query `refresh=1` optional | `StudioDiscovery` |
| `POST` | `/api/studios/select` | `{ studioId: string }` | `StudioDiscovery` |
| `POST` | `/api/studios/refresh` | Empty object | `StudioDiscovery` |

When state is `MULTIPLE_STUDIOS`, render a picker from `studios` and do not choose the first item automatically. Store only the returned `selectedStudioId`; the backend persists the durable selection.

## Storage

```ts
type StorageCategoryId =
  | 'DATABASE'
  | 'LOGS'
  | 'RUNS'
  | 'JOB_SNAPSHOTS'
  | 'GENERATED_IMAGES'
  | 'GENERATED_3D'
  | 'DOWNLOADS'
  | 'TEMP'
  | 'BROWSER_CACHE'
  | 'BROWSER_SESSION_PROFILE'
  | 'BROWSER_RUNTIME'
  | 'OPTIONAL_TOOLS'
  | 'TOOL_CACHE'
  | 'TEST_ARTIFACTS'
  | 'OTHER'

type StorageSnapshot = {
  bytesUsed: number
  budgetBytes: number
  withinBudget: boolean
  categories: { id: StorageCategoryId; bytes: number; protected: boolean }[]
}

type StorageCleanup = {
  bytesBefore: number
  bytesAfter: number
  bytesRemoved: number
  categories: string[]
  itemsRemoved: number
  storage: StorageSnapshot
}
```

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/api/storage` | None | `StorageSnapshot` |
| `POST` | `/api/storage/cleanup` | Empty object | `StorageCleanup` |
| `PATCH` | `/api/storage/settings` | `{ budgetBytes: number }` | `StorageSnapshot` |

The backend clamps `budgetBytes` to 1-100 GB. Cleanup runs to the active budget and never accepts arbitrary paths from the frontend.

## Optional tools

```ts
type ToolStatus = 'INSTALLED' | 'AVAILABLE' | 'ON_DEMAND'

type Tool = {
  id: string
  name: string
  purpose: string
  version: string
  source: string
  license: string
  download_size: number
  installed_size: number
  checksum: string
  trust_level: string
  update_policy: string
  archive: boolean
  downloadSize: number
  installedSize: number
  trustLevel: string
  updatePolicy: string
  status: ToolStatus
  lastUsed: string | null
  installedAt: string | null
}
```

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/api/tools` | None | `Tool[]` |
| `POST` | `/api/tools/:id/install` | Empty object | `Tool` |
| `POST` | `/api/tools/:id/remove` | Empty object | `Tool` |

Current default tools are `ON_DEMAND` and not installable until a verified pinned package is configured. Render the controlled backend error instead of converting it to success.

## System lifecycle

```ts
type UninstallMode = 'KEEP_SETTINGS' | 'FULL_REMOVE'

type UninstallResult = {
  scheduled: true
  mode: UninstallMode
  available: boolean
  scope: string
}

type RepairComponent = 'WEBVIEW2' | 'MANAGED_CHROMIUM' | 'BROWSER_RUNTIME' | 'FRONTEND_BUNDLE'

type RepairResult = {
  component: RepairComponent
  state: 'READY'
  path: string
}
```

`POST /api/system/uninstall` accepts `{ mode: UninstallMode }` and returns `UninstallResult`. If the app is portable or its installed uninstaller is unavailable, it returns `409 UNINSTALL_UNAVAILABLE`.

`POST /api/system/repair` accepts `{ component: RepairComponent }` and returns `RepairResult` or a structured error.

## Task options

New chat and job requests accept:

```ts
type TaskOptionsRequest = {
  visualFirst?: FeatureMode | boolean | 0 | 1
  create3D?: FeatureMode | boolean | 0 | 1
  effort?: Effort
  chatMode?: ChatMode
  deadlineMinutes?: number
  review?: boolean
  autoTest?: boolean
  autoFix?: boolean
  approval?: boolean
  risk?: 'low' | 'medium' | 'high'
  revisions?: number
  fixAttempts?: number
}
```

Missing `visualFirst` and `create3D` mean `AUTO`. Job responses expose resolved booleans as `visualFirst` and `create3D`, original modes as `visualMode` and `create3DMode`, and the remaining normalized settings. `TEMP` mode must be presented as non-project chat; it cannot perform Studio writes or visual/3D generation.

## Activity and artifacts

```ts
type ChatActivity = {
  id: string
  jobId: string
  providerId: string
  role: string
  phase: string
  status: 'RUNNING' | 'FINISHED'
  title: string
  target: string
  step: number
  totalSteps: number
  timestamp: number
  detail?: string
}

type ChatArtifact = {
  id: string
  jobId: string
  messageId: string | null
  type: 'IMAGE' | 'MODEL_3D' | 'FILE'
  name: string
  mime: string
  size: number
  state: string
  previewUrl: string | null
  contentUrl: string | null
  modelUrl: string | null
  metadata: Record<string, unknown>
  actions: string[]
  createdAt: number
}
```

Activity step counts are real stage positions; do not derive percentages beyond `step / totalSteps`. Artifact URLs are backend-controlled paths. Never render a local path as a download URL.

Model REST state is exactly `IDLE`, `GENERATING`, `READY`, or `FAILED`. A ready model can separately expose `approvalState: 'PENDING_APPROVAL' | 'APPROVED'`. Six-view assets are `VIEW` with `image/png`.

## Events

All payloads below are the `data` field of `BackendEvent`.

| Event | Data |
| --- | --- |
| `READINESS_CHANGED` | `ReadinessSnapshot` |
| `LOGIN_REQUIRED` | `{ providerId: string }` |
| `LOGIN_WINDOW_WILL_OPEN` | `{ providerId: string }` |
| `LOGIN_WINDOW_OPENED` | `{ providerId: string, route: 'webview2' | 'playwright' }` |
| `LOGIN_DETECTED` | `{ providerId: string }` |
| `LOGIN_PERSISTENCE_VERIFYING` | `{ providerId: string }` |
| `LOGIN_READY` | `{ providerId: string, route: string, persistent: true }` |
| `LOGIN_FAILED` | `{ providerId: string, message: string, recovery: string }` |
| `PROVIDER_CAPABILITIES_CHANGED` | `{ provider: Provider }` |
| `PROVIDER_MODEL_CHANGED` | `{ providerId: string, selection: { route?: string, mode?: string, model?: string } }` |
| `STUDIO_DISCOVERY_CHANGED` | `StudioDiscovery` without guaranteed `capabilities` |
| `STUDIO_SELECTION_REQUIRED` | `StudioDiscovery` |
| `CHAT_ACTIVITY_STARTED` | `ChatActivity` |
| `CHAT_ACTIVITY_UPDATED` | `ChatActivity` |
| `CHAT_ACTIVITY_FINISHED` | `ChatActivity` |
| `CHAT_ARTIFACT_CREATED` | `{ artifact: ChatArtifact }` |
| `CHAT_ARTIFACT_UPDATED` | `{ artifact: ChatArtifact }` |
| `STORAGE_CLEANUP_COMPLETED` | `{ bytesBefore: number, bytesAfter: number, bytesRemoved: number, categories: string[], itemsRemoved: number }` |
| `TOOL_STATUS_CHANGED` | `{ tool: Tool }` |
| `CHAT_SYSTEM_EVENT` | `{ severity: string, title: string, message: string, recovery: string, jobId?: string | null, diagnosticId?: string }` |

The login pre-notification events are emitted before the blocking login workflow. Keep the modal or card active through challenges and uncertainty, and close it only on `LOGIN_READY`. `LOGIN_WINDOW_OPENED` is a lifecycle notification, not authentication evidence.

Existing events remain supported. New event handling must be additive and idempotent.

## Required frontend behavior

1. Hydrate readiness, providers, studios, storage, and tools on application startup and reconnect.
2. Treat REST hydration as authority and WebSocket messages as deltas.
3. Keep login UI open through `CHALLENGE`, `AUTHENTICATING`, and `VERIFYING_PERSISTENCE`; only `LOGIN_READY` completes it.
4. Use provider identity as the primary label and role as secondary metadata.
5. Disable unsupported mode controls from live capabilities without hiding the provider identity.
6. Require an explicit Studio choice for `MULTIPLE_STUDIOS`.
7. Render activity and artifacts in Chat while retaining drill-down pages.
8. Surface structured errors and `CHAT_SYSTEM_EVENT`; never leave a permanent loading state after failure.
9. Never hardcode Ready, test success, provider support, file acceptance, model readiness, or installation success.
10. Preserve current socket ownership in the application-lifetime runtime; no page or splash may own the authoritative connection.
