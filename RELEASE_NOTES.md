# Rubra 2.1.1 prerelease

This release addresses live Studio inventory failures and improves development against the already open game.

- Decode structured results, text blocks, encoded JSON, fenced JSON and embedded text resources. Prefer the current paired StudioMCP binary over a stale launcher. Tree indexing failure remains visible without disconnecting Studio or blocking Play.
- Select the open/active Studio game automatically. Keep running jobs pinned to their original game; detect late startup, project changes and idle inventory updates without requiring a local project folder.
- Enumerate up to 50,000 objects and read up to 2,000 scripts with paginated Edit-mode reads. Preserve duplicate objects in the tree and export complete readable sources for static/security checks. Show protected-source and coverage gaps; prompt snippets remain explicitly bounded.
- Review/debug/test requests can run QA against existing games without first changing source. Refresh source snapshots after changes so static checks inspect current code.
- Scene, UI, geometry and property edits support bounded native execution with expected-property snapshots, concurrent-change rejection and post-write read-back. Persistent writes retain the operation ledger preventing automatic replay.
- Capture successive gameplay frames before Stop without resizing the original evidence. The Test page displays dimensions and opens the original image. Web image-capable accounts can independently review the captured frames; unavailable vision review is recorded as skipped.
- Keep workers running while the window is hidden in the Windows notification area. Double-click or Open Rubra restores the window; Quit Rubra stops it. A per-installation Windows mutex prevents duplicate desktop workers. Set Windows taskbar identity and icons for the desktop and provider windows.
- Choose a writable installation location, create a desktop shortcut, and preserve existing application data during updates. Default: `%LOCALAPPDATA%\Programs\Rubra`. Protected folders still require Windows write permission.
- Modernize chat spacing, message bubbles, expanding composer, task stop control and review/repair prompts. Display instance inspection details. Ignore stale test hydration and completion events from another session.

Validation covers Python regressions, frontend unit tests, Chromium UI flows, type/lint checks, Windows package structure and real Luau reader execution under upstream Lune with Roblox Instance fixtures. Lune fixtures validate code and serialization; they do not replace a live Studio session. Native Windows tray/mutex, installer execution, real Studio Play/viewport and provider-account flows cannot be verified in this Linux environment. The package remains a prerelease pending those checks on the target PC.

Close the old Rubra process before installing. Initial local-model/tool preparation requires Internet access, several GB of downloads and sufficient free disk space. Local models handle text/code; image and 3D generation still need their respective providers.
