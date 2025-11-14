# TODO

## Instructions

**Task Management:**

- Review the Task section before adding or editing items.
- Prioritize production readiness: maintainability, testability, performance, clarity.
- Items marked with `[?]` are requested for next work.
- Mark completed items with `[X]` after linting, testing, and verifying health/metrics endpoints.
- Refresh the Task list with the next highest-impact item once it becomes empty.

## Tasks

### High Priority (Production Readiness)

### Medium Priority (Architecture & Maintainability)

### Lower Priority (Testing & Reliability)

- [ ] Add end-to-end tests with real RPC endpoints (using testnets) to verify integration with actual blockchain nodes and catch protocol-level issues before production deployment. Consider using a separate test suite that can be run manually or in a separate CI job to avoid rate limits.

### Lower Priority (Features & Enhancements)

- [ ] Evaluate restoring an optional synchronous "warm poll" during startup (configurable timeout) so key gauges are populated before readiness flips to healthy. This improves initial metric availability for monitoring systems that query metrics immediately after deployment.
- [?] Improve chunking algorithm for large log queries: add adaptive chunk sizing based on response size, implement smarter block range selection, and add metrics for chunking efficiency (chunks_created, blocks_queried_per_chunk, chunk_duration_seconds). This can significantly improve performance for contracts with high transfer volumes.
- [ ] Add config reload capability (via SIGHUP or HTTP endpoint) to allow updating blockchain configurations without restarting the service. This requires careful handling of running pollers and metric cleanup. Useful for dynamic environments but adds complexity.
- [ ] Add support for WebSocket RPC connections as an alternative to HTTP for lower latency and real-time updates. Consider connection management, reconnection logic, and fallback to HTTP. This is a larger architectural change that may provide marginal benefits for most use cases.

## Cleanup

- Normalized import grouping/whitespace across Python modules to maintain stdlib / third-party / local separation without broader reformatting.
- Refresh documentation (`README.md`, `docs/AI_REFERENCE.md`, `docs/AI_TODO.md`) to reflect recent changes when directed.
- Polish code layout/formatting across the entire project (respect existing spacing/import conventions; avoid mass reformatting).
- Analyze test coverage to identify new or lingering gaps and propose targeted test additions.
- Review code comments/docstrings for consistency, clarity, and presence where needed; align style with existing conventions.
- Alphabetize non-functional enumerations (e.g., constant lists, `__all__`, documentation bullets, variable names, functions) where ordering has no semantic meaning to keep diffs tidy.
- Update the Task list according to the Instructions section (verify priorities, move completed items, surface the next high-impact work).
- Fix any outstanding Python linting issues reported by Ruff.
- Fix any Markdown linting issues reported by `mdformat --wrap=keep`.
- Fix any Dockerfile linting issues reported by Hadolint.
