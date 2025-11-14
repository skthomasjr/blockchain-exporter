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

- [ ] Add RPC call duration metrics (histogram) for monitoring latency and identifying slow endpoints. Track metrics per blockchain and operation type (get_balance, get_logs, get_block, etc.) to enable alerting on slow RPC calls.
- [ ] Add RPC error rate metrics (counter) per blockchain and error type to track RPC endpoint health and identify problematic operations or chains. Include labels for error categories (timeout, connection_error, rpc_error, etc.).
- [ ] Implement comprehensive error handling with specific exception types instead of broad `Exception` catches. Create custom exception hierarchy (RpcError, ConfigError, ValidationError) with structured error messages and context.
- [ ] Add connection pooling for RPC clients to reduce connection overhead and improve performance when polling multiple chains or making frequent requests. Consider using a connection pool manager per blockchain.
- [ ] Add observability metrics for poller internals: poll_duration_seconds (histogram), consecutive_failures (gauge per chain), backoff_duration_seconds (histogram), and poller_thread_count (gauge) to monitor polling health and performance.

### Medium Priority (Architecture & Maintainability)

- [ ] Refactor module-level global state in `app.py` (`_polling_tasks_created`, `_global_polling_tasks`, `_primary_app`) into a dedicated `PollerManager` class to improve testability, prevent race conditions in concurrent scenarios, and enable proper dependency injection.
- [X] Improve type safety by replacing `Any` types in `rpc.py` (especially in Protocol definitions and return types) with proper generic types or TypedDict. Use `BlockIdentifier` type for block identifiers and structured types for RPC responses where possible.
- [ ] Add ability to set env values in the helm chart to expose all application settings (LOG_LEVEL, POLL_DEFAULT_INTERVAL, RPC_REQUEST_TIMEOUT_SECONDS, etc.) as Helm values for better deployment flexibility. Document all available options in values.yaml.
- [ ] Implement config file validation with detailed error messages including line numbers and field names. Add validation for address format, poll interval format, numeric ranges, and required field presence.
- [ ] Add optional `enabled` boolean field (default `true`) to `BlockchainConfig` in `config.toml` to allow disabling entire blockchains without removing them from configuration. Update `load_blockchain_configs()` to filter disabled blockchains and modify `_lifespan` to skip creating polling tasks for disabled blockchains.

### Medium Priority (Testing & Reliability)

- [X] Add an integration test that boots both `create_health_app()` and `create_metrics_app()` simultaneously and asserts that background polling tasks are only created once (no duplicate logs/metrics). Verify shared state behavior and graceful shutdown coordination.
- [X] Add comprehensive error recovery tests: test behavior with unavailable RPC endpoints, malformed responses, network timeouts, partial failures, and recovery scenarios. Verify backoff behavior and metric updates during failures.
- [X] Add stress tests for concurrent polling across multiple blockchains to verify thread safety, memory usage, and performance under load. Test with realistic numbers of chains (10+), accounts, and contracts.
- [ ] Add end-to-end tests with real RPC endpoints (using testnets) to verify integration with actual blockchain nodes and catch protocol-level issues before production deployment.

### Lower Priority (Features & Enhancements)

- [ ] Evaluate restoring an optional synchronous "warm poll" during startup (configurable timeout) so key gauges are populated before readiness flips to healthy. This improves initial metric availability for monitoring systems.
- [ ] Add optional `enabled` boolean field (default `true`) to `AccountConfig`, `ContractConfig`, and `ContractAccountConfig` in `config.toml` to allow disabling individual accounts, contracts, and contract accounts. Update config parsing to filter disabled items and modify collectors to skip disabled entities during metric collection.
- [ ] Add config reload capability (via SIGHUP or HTTP endpoint) to allow updating blockchain configurations without restarting the service. This requires careful handling of running pollers and metric cleanup.
- [ ] Add support for WebSocket RPC connections as an alternative to HTTP for lower latency and real-time updates. Consider connection management and fallback to HTTP.
- [X] Add metric for total number of configured accounts and contracts per blockchain to track configuration complexity and help with capacity planning.
- [ ] Improve chunking algorithm for large log queries: add adaptive chunk sizing based on response size, implement smarter block range selection, and add metrics for chunking efficiency (chunks_created, blocks_queried_per_chunk).

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
