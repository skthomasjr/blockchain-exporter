# Blockchain Exporter – Reference Prompt & Architecture Snapshot

Use this file when you need to brief an AI assistant about the current state of the project. The sections below capture the architecture, conventions, and open work so you can copy/paste (or link) the right context quickly.

## 1. System Overview

- **Purpose**: FastAPI-based Prometheus exporter that polls Ethereum-compatible chains (mainnet & testnets) for account/contract metrics.
- **Entry Points**:
  - `blockchain_exporter.main:run()` (used by Docker/CLI) → launches Uvicorn with `create_app()`.
  - `blockchain_exporter.app:create_app(metrics=...)` builds the FastAPI instance, configures logging, loads config, and starts async pollers via lifespan.
- **Key Runtime Modules**:
  - `config.py`: loads `config.toml`, supports env interpolation, defines `BlockchainConfig`, `ContractConfig`, etc.
  - `settings.py`: centralizes environment vars (logging, poller intervals, health thresholds, metrics port, config path resolution).
  - `runtime_settings.py`: combines environment-driven `AppSettings`, resolved `config.toml` blockchains, and the concrete `config_path` into a cached `RuntimeSettings` bundle for dependency injection/testing.
  - `metrics.py`: defines `MetricsBundle` (exporter/account/contract/chain gauges), cache state (`CHAIN_*` dicts), helpers (`record_poll_success`, `reset_chain_metrics`, etc.), and `create_metrics()/get_metrics()/set_metrics()` for dependency injection.
  - `poller/`: orchestrates background polling.
    - `control.py`: async loop with backoff, calls `collect_blockchain_metrics()` (to-thread).
    - `collect.py`: synchronous core using `ChainRuntimeContext` (config, RPC client, metrics bundle, chain state) to update gauges.
    - `intervals.py`: polling cadence + Web3 HTTPProvider factory.
    - `connection_pool.py`: connection pool manager for reusing Web3 clients and HTTP connections across multiple chains.
    - `manager.py`: `PollerManager` class to encapsulate and manage global polling state, preventing race conditions and improving testability.
  - `collectors.py`: token & contract metric collection, log chunking, default fallbacks for ERC-721/20 quirks.
  - `rpc.py`: `RpcClient` wrapper with retry/backoff for Web3 calls (`get_balance`, `get_logs`, `get_code`, `get_chain_id`, `call_contract_function`). Includes error categorization and RPC call duration/error rate metrics.
  - `logging.py`: structured logging helpers (`build_log_extra`, `log_duration`).
  - `health.py`: readiness/liveness + metrics payload formatting.
  - `api.py`: `/health`, `/health/details`, `/health/livez`, `/health/readyz`, `/health/reload`, `/metrics` endpoints.
  - `reload.py`: configuration reload functionality supporting dynamic updates without service restart.
  - `context.py`: `ApplicationContext` for dependency injection, with helper functions for creating default contexts and RPC factories.

## 2. Data Flow (Polling Lifecycle)

1. Lifespan startup loads configs, marks exporter up, optionally performs synchronous warm poll (if `WARM_POLL_ENABLED=true`) to populate metrics before readiness flips healthy, and schedules `poll_blockchain` tasks.
1. Each poll cycle (`poll_blockchain`) runs `collect_chain_metrics_sync` in a thread:
   - Build/resolve `ChainRuntimeContext` (`BlockchainConfig`, chain ID, `RpcClient`, metrics bundle, label caches).
   - Record latest block, finalized block, and time-since metrics.
   - Update configured account balances, token balances, additional contract accounts.
   - Update contract metrics: ETH balance, raw/normalized token supply, transfer counts with chunked `eth_getLogs`.
   - Cache label sets to support metric cleanup.
   - Call `record_poll_success` or `record_poll_failure` to update health caches and gauges.
1. `/metrics` checks readiness; if any chain is fresh & healthy the Prometheus payload is returned (with scientific notation normalized).

## 3. Configuration & Environment

- **Config file**: `config.toml` with `[blockchains]` array; each chain lists `rpc_url`, `poll_interval`, `contracts`, `accounts`, `transfer_lookback_blocks`, etc. `${ENV}` interpolation is applied before parsing.
- **Environment**:
  - `.env` autoloaded via `dotenv` for RPC URLs and other secrets.
  - Key vars documented in README & `settings.py`: `LOG_LEVEL`, `LOG_FORMAT`, `POLL_DEFAULT_INTERVAL`, `RPC_REQUEST_TIMEOUT_SECONDS`, `READINESS_STALE_THRESHOLD_SECONDS`, `MAX_FAILURE_BACKOFF_SECONDS`, `HEALTH_PORT`, `METRICS_PORT`, `BLOCKCHAIN_EXPORTER_CONFIG_PATH`.
- **Runtime settings**: `get_runtime_settings()` produces a cached `RuntimeSettings` (environment settings + blockchain configs + resolved config path); `ApplicationContext` exposes `context.settings` and `context.blockchains` via this bundle.
- **Kubernetes Deployment (Helm)**:
  - Helm chart in `helm/charts/blockchain-exporter/` manages ConfigMap, Secret, Deployment, Service, and ServiceAccount resources.
  - Chart generates `config.toml` from declarative `blockchains` configuration in `values.yaml`, or uses a custom `config.toml` if provided.
  - Supports both direct secret values (stored in a Kubernetes Secret) and references to existing Secrets via `secretRef`.
  - Environment variables are injected for TOML variable interpolation (e.g., `${ETH_MAINNET_RPC_ENDPOINT}`) and additional non-secret variables (including `valueFrom` sources) can be defined via `.Values.env`.
  - Default probe settings optimized for fast startup (startup: 1s period, readiness/liveness: relaxed intervals).
  - Commands: `make helm-install [VALUES=path/to/values.yaml]`, `make helm-uninstall`, `make lint-helm`.
- **Tooling**:
  - `make print-config [CONFIG=path]` → pretty JSON of resolved settings with RPC URLs masked (use CLI `--show-secrets` to reveal).
  - `make validate-config [CONFIG=path]` → run TOML validation.
  - `make run` / `make lint` / `make lint-md` / `make lint-docker` / `make lint-helm` / `make test` / `make docker-build` / `make docker-run` / `make helm-install` / `make helm-uninstall`.
  - Logging options: `LOG_FORMAT` (`text`/`json`) and `LOG_COLOR_ENABLED` (defaults to true) control formatter style; colors are suppressed automatically when the toggle is false.
  - Cleanup macro: `make lint && make test && make validate-config` mirrors the CI pipeline (Ruff + Markdown + Hadolint + Helm, pytest with coverage ≥85%, config validation).

## 4. Logging & Metrics Conventions

- Logging uses structured extras; `rpc_url` intentionally excluded. `log_duration` wraps expensive operations.
- Metrics are grouped (`ExporterMetrics`, `AccountMetrics`, `ContractMetrics`, `ChainMetrics`). All interactions go through an injected `MetricsBundle` for testability.
- Label caches (`ChainMetricLabelState`) avoid stale series; helper functions ensure cleanup on chain ID changes/failures.
- JSON logs keep `color_message` for completeness; structured text logs color levels/timestamps unless `LOG_COLOR_ENABLED=false`.
- Core modules use concise docstrings to describe contexts, factories, and pollers for quick orientation.

## 5. Outstanding Improvements (from `docs/TODO.md`)

- See `docs/TODO.md` for current task list. Recent focus has been on test coverage improvements (now at 92%).

## 6. Known Testing & Operational Considerations

- **Test Coverage**: 92% overall (2069 total lines, 169 uncovered). Comprehensive test suites cover:
  - Configuration reload functionality (`test_reload.py`, `test_api_reload.py`, `test_poller_manager_reload.py`, `test_main_signals.py`, `test_app_reload_monitor.py`)
  - Context helper functions (`test_context.py` - 100% coverage)
  - Warm poll edge cases (`test_app_warm_poll.py`)
  - App error handling (`test_app_error_handling.py`)
  - RPC client methods (`test_rpc_client_methods.py`)
  - RPC error categorization (`test_rpc_error_categorization.py`)
  - Poller collect error paths (`test_poller_collect.py`)
  - See `docs/TEST_COVERAGE_GAPS.md` for detailed coverage analysis and remaining gaps.
- `collect_chain_metrics_sync` accepts injected `rpc_client`/`metrics`, but will construct defaults when omitted.
- Background pollers run indefinitely; lifespan cancels and gathers tasks on shutdown and resets `ApplicationContext`.
- Log chunking thresholds (`LOG_MAX_CHUNK_SIZE`, `LOG_SPLIT_MIN_BLOCK_SPAN`) guard against "response too big" RPC errors; retry/backoff is handled by `RpcClient`.
- Connection pooling (`poller/connection_pool.py`) reuses Web3 clients and HTTP connections for improved performance when polling multiple chains.
- Warm poll feature (optional synchronous poll during startup) populates metrics before readiness flips healthy, improving initial metric availability.
- Configuration reload via SIGHUP or HTTP POST `/health/reload` endpoint allows updating blockchain configurations without restarting the service.

## 7. Reference Prompt Template

Use or adapt the prompt below when engaging an assistant in future sessions:

```
You are helping with the "blockchain-exporter" FastAPI project that exposes Prometheus metrics for Ethereum-family chains.
Key facts:
- Entry point `blockchain_exporter.app:create_app(metrics=...)` builds the app; `poller/control.py` manages async polling; `collectors.py` updates Prometheus gauges via an injected `MetricsBundle`.
- Config lives in `config.toml`, loaded through `config.py` with env interpolation; settings are centralized in `settings.py`.
- Metrics are grouped in `metrics.py` (`ExporterMetrics`, `AccountMetrics`, `ContractMetrics`, `ChainMetrics`). Health state is tracked via `CHAIN_HEALTH_STATUS` / `CHAIN_LAST_SUCCESS`.
- RPC access goes through `RpcClient` in `rpc.py` with retry/backoff and connection pooling; token transfers use adaptive chunked `eth_getLogs` to handle large response sizes. RPC call duration and error rate metrics are tracked per blockchain and operation type.
- Health endpoints and readiness gating are implemented in `api.py` / `health.py`. Configuration reload is supported via SIGHUP signal or HTTP POST `/health/reload` endpoint.
- Kubernetes deployment via Helm chart in `helm/charts/blockchain-exporter/` (ConfigMap, Secret, Deployment, Service, ServiceAccount). Chart generates `config.toml` from declarative `blockchains` configuration or uses custom `config.toml`. Supports direct secret values and references to existing Secrets via `secretRef`. Environment variables are injected for TOML variable interpolation, and additional non-secret variables (including `valueFrom` sources) can be defined via `.Values.env`. Health endpoints are on port 8080, metrics on port 9100. Probes target the health port (8080).
Current focus (see TODO.md): define next enhancements based on production feedback; existing tooling (validate-config, coverage at 92%, CI, Helm) is in place. Recent work focused on comprehensive test coverage improvements and error handling enhancements.
Please follow the existing logging and metrics patterns (no logging of secrets, keep Prometheus label ordering consistent) and respect the user's preference for blank lines between variable declarations. Avoid reformatting unrelated code.
```

Copy this block into your requests (feel free to trim) so the assistant jumps in with full context.
