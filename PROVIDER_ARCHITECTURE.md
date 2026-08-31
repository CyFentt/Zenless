# Provider architecture

## Registry and support boundary

`ProviderRegistry` is the single catalog for provider identity, web location, support status, adapter, default roles, modes, and compatibility capability hints. The registry currently exposes 18 manifests. Three browser adapters are enabled and marked `BETA`; the remaining catalog entries are `UNSUPPORTED` and cannot be logged in, selected, or assigned.

Support values are `VERIFIED`, `BETA`, `EXPERIMENTAL`, and `UNSUPPORTED`. Catalog presence never upgrades support. Only observed external E2E evidence can justify `VERIFIED`.

Default roles are:

| Provider identity | Default roles | Enabled |
| --- | --- | --- |
| ChatGPT | `BUILDER`, `VISUAL`, `RESEARCH` | Yes |
| DeepSeek | `REVIEWER` | Yes |
| Hunyuan 3D | `3D` | Yes |

Role bindings are durable and exclusive per role. Assigning `BUILDER`, `REVIEWER`, `VISUAL`, `RESEARCH`, or `3D` to an enabled provider removes that role from the prior binding while preserving provider identity.

## Authentication model

The canonical states are:

`UNKNOWN`, `CHECKING`, `LOGIN_REQUIRED`, `LOGIN_WINDOW_OPEN`, `AUTHENTICATING`, `CHALLENGE`, `AUTHENTICATED`, `VERIFYING_PERSISTENCE`, `READY`, `EXPIRED`, and `ERROR`.

Each enabled provider has selectors and URL patterns for authenticated application state, unauthenticated state, challenges, login pages, authenticated pages, composers, accounts, generation controls, models, and modes. Auth evaluation prioritizes challenge and unauthenticated evidence. Generic text inputs are not authenticated evidence. Providers with explicit login patterns require strong application or combined account and generation/composer evidence.

Managed and embedded login controllers require an authenticated state to remain stable for at least two seconds while not generating. They then persist the browser profile and re-probe the restored session before reporting success. Password, MFA, CAPTCHA, email verification, and consent are never automated around or bypassed.

## Route and session persistence

The gateway can route an enabled provider through embedded WebView2 or a managed Playwright context. It persists the last successful route, probes that route first after restart, probes alternatives when necessary, and selects an authenticated route over an idle route.

`provider-routes.json` stores route preference. `provider-sessions.json` stores non-secret operational metadata:

- provider ID and adapter;
- internal profile location;
- last successful route;
- last authenticated and verified times;
- selected model and mode;
- capability fingerprint;
- last health state.

Passwords and provider cookies are not serialized into these metadata files or sent through chat events. Browser profile directories contain session material and are protected from storage cleanup.

## Capabilities

The canonical mode capability model includes text, reasoning levels, search, file upload, MIME types, extensions, file count, per-file size, images, vision, audio, archives, code execution, tools, image generation, 3D generation, geometry, texture, download, cancel, and streaming.

Manifest modes are fallback compatibility hints. A live mode probe is authoritative and may disable a hinted feature. DeepSeek mode changes click only known visible Instant or Expert controls, verify the selected state, and then re-probe capabilities. Legacy capability names are normalized with the canonical camel-case fields, including consistent `select_model`, `get_models`, and `select_mode` values.

Current hints include:

- ChatGPT default: text, reasoning, cancel, and streaming.
- DeepSeek Instant: text, reasoning, search, one-file upload, vision, cancel, and streaming.
- DeepSeek Expert: text, reasoning, cancel, and streaming; file upload is not assumed.
- Hunyuan 3D: up to six compatible images plus geometry, texture, download, cancel, and streaming.

These are hints, not external verification. The frontend must render `liveCapabilities` when present and use mode hints only when a live snapshot is unavailable.

## Attachments and provider prompts

Before provider transport, attachments are inspected and routed against the selected live mode. Unsupported archives can be safely extracted only when the internal extractor supports the format. Accepted files are ranked and partitioned into batches no larger than `maxFiles`; no accepted file is silently discarded.

Provider prompts receive only the context required for their role. Current date, task effort, relevant Studio evidence, available tool names, and review block metadata are explicit. The system does not request private chain-of-thought. Research uses provider search only when the selected live mode advertises it.

## Failure behavior

Unavailable auth, changed controls, unsupported modes, missing file upload, route failure, and capability loss produce structured errors or events. The gateway does not click controls solely because they resemble a previous selector. External site changes can still require adapter updates.

Unit and fixture tests can verify auth logic, stable-close behavior, route persistence, capability normalization, and provider batching. They do not prove a real account, provider model, or live 3D workflow.
