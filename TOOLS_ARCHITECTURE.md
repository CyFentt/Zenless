# Tools architecture

## Policy

Optional tools are task-scoped and on demand. Normal Zenless startup installs none of them. The official Studio MCP remains the primary Studio connection, and existing project conventions remain authoritative. Zenless does not migrate a Studio-first project to filesystem synchronization or install a package manager merely because it is cataloged.

## Manifest

Each `ToolManifest` records:

- `id`, `name`, and `purpose`;
- pinned `version` and HTTPS package `source`;
- `license`;
- expected download and installed sizes;
- SHA-256 `checksum`;
- `trust_level` and `update_policy`;
- whether the package is an archive.

Automatic installation is allowed only when the source is HTTPS, the version is non-empty, and the checksum is exactly 64 hexadecimal characters. Downloaded bytes are streamed to a Zenless-owned staging file, bounded against the manifest size, hashed before use, and moved or safely extracted only after verification.

Removal resolves the exact `%LOCALAPPDATA%\Zenless\tools\<tool-id>` target and refuses any path outside the ToolManager root. The tool state file records installed time, last use, and version.

## Current catalog status

The default catalog describes repository, Luau formatting and analysis, project synchronization, package management, pure module testing, archive, dependency scanning, and 3D tools. Every current default entry lacks a pinned executable package version and checksum, so its status is `ON_DEMAND` and `POST /api/tools/:id/install` returns a controlled conflict. No default tool is silently downloaded.

This is intentional until each package has a current release, license, size, checksum, and security review. Catalog links identify upstream projects but are not install packages.

Jest Roblox is cataloged but is not globally installed or injected into a user project. RAR and 7Z are detected by attachment inspection, but only ZIP has a built-in safe extraction path. External archive or 3D tooling remains unavailable until a pinned manifest is configured.

## API lifecycle

`GET /api/tools` returns the catalog and current state. Install and remove endpoints return the updated tool object and publish one `TOOL_STATUS_CHANGED` event. Repeated catalog reads do not install, update, execute, or remove anything.

The current orchestrator does not automatically invoke catalog tools. Job-aware tool selection, explicit user consent for large or powerful packages, execution sandboxing, and post-job cleanup remain requirements before an optional tool can participate in production tasks.

## Storage and diagnostics

Installed packages are counted as `OPTIONAL_TOOLS`; transient package data is counted as `TOOL_CACHE`. Tool cache is eligible for LRU cleanup, while installed tool directories are not. Download, checksum, extraction, ownership, and removal failures return structured API errors and one status event when state changes.

## Adding an installable tool

1. Confirm a maintained release and license from an authoritative upstream source.
2. Pin a concrete version, direct HTTPS artifact, SHA-256, and realistic size bounds.
3. Verify archive contents and runtime dependencies.
4. Add install, removal, ownership, and corrupted-download tests.
5. Integrate the tool only behind a capability need and task policy.
6. Record real execution evidence before changing its support claim.
