# Rubra 2.0.3 validation

## Results

| Check | Result |
| --- | --- |
| Python suite | 129 passed, 1 Windows-only test skipped; 4 subtests passed |
| Frontend suite | 69 passed |
| Ruff / Pyright | Passed |
| ESLint / TypeScript | Passed |
| Production frontend | Built successfully |
| Backend statement coverage | 50% (3,871 of 7,696 statements) |

Three new property-based schema tests are configured for 250 generated examples each. Transport tests use actual Python child processes, including 32 concurrent requests answered in reverse order. HTTP tests run the authenticated loopback server and send streamed request bodies, malformed input and repeated operation keys. These are local integration tests, not live Studio/provider tests.

## Fixed defects

- Session bootstrap could wait indefinitely; its fetch and body now have a timeout.
- REST timeouts ended at response headers, allowing response bodies to stall startup.
- A failed saved-task restoration could block the entire application shell.
- Broken MCP pipes and reader errors could leave callers waiting for the full tool timeout.
- Closing a stuck MCP reader could block on a pipe; shutdown now joins before closing reader-owned streams and terminates an unresponsive owned child.
- Python treated boolean response IDs as integer request IDs; those responses are ignored.
- Schema composition treated oneOf as anyOf and skipped sibling constraints; array limits were skipped without an item schema.
- Chunked JSON requests bypassed the JSON size cap; streaming reads now enforce it independently of Content-Length.
- Optional chunked JSON bodies were ignored, losing the selected test profile.
- An idempotency key from one task could replay its result for another task; resource identity is now checked.

## Remaining validation

Windows desktop execution, real WebView2 rendering, installer upgrade/uninstall behavior, provider authentication and live Roblox Studio editing/playtests require Windows validation. The Windows package is built and checked structurally; this is not evidence of a successful Windows execution. Backend coverage is 50%, so this review does not establish full-project coverage or absence of defects. Native GUI and external-provider code account for substantial untested paths.
