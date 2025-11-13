# blockchain-exporter

FastAPI-based exporter exposing Prometheus metrics for blockchain monitoring.

## Runtime Overview

- Load environment configuration and `config.toml`, expanding environment variables.
- Set basic metrics (up, configured_blockchains) early for immediate availability.
- Launch background pollers that scrape RPC endpoints, update Prometheus gauges, and back off with exponential delays on repeated failures.
- Expose health endpoints (`/health`, `/health/details`, `/health/livez`, `/health/readyz`) on port 8080 for Kubernetes probes.
- Expose metrics endpoint (`/metrics`) on port 9100 for Prometheus scraping.

## Configuration

A `.env.example` file is provided in the repository with all available environment variables documented. Copy it to `.env` and fill in your values:

```bash
cp .env.example .env
```

Environment variables provide operational tuning without code changes:

| Variable | Description | Default |
| --- | --- | --- |
| `BLOCKCHAIN_EXPORTER_CONFIG_PATH` | Path to `config.toml` (file or directory). | `./config.toml` |
| `LOG_LEVEL` | Root log level (`INFO`, `DEBUG`, etc.). | `INFO` |
| `LOG_FORMAT` | `text` or `json` logging. | `text` |
| `LOG_COLOR_ENABLED` | Enable ANSI color output when using text logging. | `true` |
| `POLL_DEFAULT_INTERVAL` | Fallback poll interval when a chain omits `poll_interval`. | `5m` |
| `MAX_FAILURE_BACKOFF_SECONDS` | Ceiling for exponential poll backoff. | `900` |
| `RPC_REQUEST_TIMEOUT_SECONDS` | Web3 HTTP timeout in seconds. | `10.0` |
| `READINESS_STALE_THRESHOLD_SECONDS` | Staleness threshold for readiness gating. | `300` |
| `HEALTH_PORT` | Port for health check endpoints (`/health`, `/health/livez`, `/health/readyz`). | `8080` |
| `METRICS_PORT` | Port for Prometheus metrics endpoint (`/metrics`). | `9100` |

All environment configuration is surfaced through `blockchain_exporter.settings`; modules read from this singleton so overrides apply uniformly.

### Configuration Contract

- `config.toml` owns blockchain-facing data: chain names, `${ENV}`-expandable RPC URLs, optional per-chain `poll_interval`, watched accounts, contracts, and lookback windows.
- Environment variables (table above) remain the source of truth for operational tuning—logging, default poll cadence, backoff ceilings, RPC timeout, readiness thresholds, HTTP port, and alternate config locations.
- At startup we resolve both into a `RuntimeSettings` bundle: `blockchains` mirrors the validated TOML entries, while `settings` exposes environment-driven knobs. The bundle also records the resolved `config_path`.
- Use `make print-config` (optionally `CONFIG=path/to/config.toml`) to emit the merged view with RPC URLs masked. To inspect secrets locally, run `python -m blockchain_exporter.cli --print-resolved --show-secrets`.

### Logging

- `LOG_FORMAT=text` enables structured text logging; `json` switches to JSON.
- Text logging defaults to ANSI coloring (timestamp cyan, level color-coded). Set `LOG_COLOR_ENABLED=false` or run in JSON mode to disable colors (useful for non-TTY pipelines).
- Both formatters carry through structured context fields supplied via `build_log_extra`.

## Dependency Injection & Testing

The application is designed for dependency injection so tests and alternative deployments can supply their own metrics registries or RPC clients.

```python
from prometheus_client import CollectorRegistry

from pathlib import Path

from blockchain_exporter.app import create_app
from blockchain_exporter.config import resolve_config_path
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import create_metrics
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import get_settings

registry = CollectorRegistry()

metrics = create_metrics(registry)

settings = get_settings()

context = ApplicationContext(
    metrics=metrics,
    runtime=RuntimeSettings(
        app=settings,
        blockchains=[],  # or a custom list loaded elsewhere
        config_path=resolve_config_path(settings),
    ),
    rpc_factory=lambda chain: FakeRpcClient(chain),
)

app = create_app(metrics=metrics, context=context)
```

- Pass a custom `MetricsStoreProtocol` via `create_app(metrics=...)` to reuse an existing Prometheus registry in tests or sidecars.
- Supply an `ApplicationContext` with preloaded configs and an RPC factory to avoid reading `config.toml` or hitting real endpoints during smoke tests.
- Tests can call `reset_metrics_state()` and `reset_application_context()` to clear global caches before and after each run (see `tests/conftest.py`).

## Kubernetes Deployment (Helm)

The application includes a Helm chart for Kubernetes deployment. The chart manages ConfigMap, Secret, Deployment, Service, and ServiceAccount resources.

### Helm Chart Features

- **Dual-Port Architecture**: Health endpoints on port 8080, metrics endpoint on port 9100 for better network isolation and security.
- **ConfigMap Generation**: Automatically generates `config.toml` from declarative `blockchains` configuration in `values.yaml`, or uses a custom `config.toml` if provided.
- **Secret Management**: Supports both direct values (stored in a Kubernetes Secret) and references to existing Secrets via `secretRef`.
- **Environment Variable Injection**: Injects secrets as environment variables for TOML variable interpolation (e.g., `${ETH_MAINNET_RPC_ENDPOINT}`) and supports additional non-secret environment variables (with optional `valueFrom` sources) via `.Values.env`.
- **Optimized Probes**: Default probe settings optimized for fast-starting services (startup probe: 1s period, readiness/liveness: relaxed intervals). Probes target the health port (8080).
- **Image Pull Policy**: Configurable image pull policy (default: `IfNotPresent`).

### Helm Commands

- `make helm-install [VALUES=path/to/values.yaml]`: Install or upgrade the chart in the `blockchain-exporter` namespace.
- `make helm-uninstall`: Uninstall the chart from the `blockchain-exporter` namespace.
- `make lint-helm`: Lint the Helm chart templates.
- `make helm-package VERSION=<version>`: Package the Helm chart locally (e.g., `make helm-package VERSION=0.1.0`).

### Installing from OCI Registry

After a release, the Helm chart is available at `ghcr.io/skthomasjr/helm-charts/blockchain-exporter`:

```bash
# Add the OCI registry as a Helm repository (one-time setup)
helm registry login ghcr.io -u skthomasjr

# Install from OCI registry
helm install blockchain-exporter oci://ghcr.io/skthomasjr/helm-charts/blockchain-exporter --version 0.1.0

# Or upgrade an existing installation
helm upgrade blockchain-exporter oci://ghcr.io/skthomasjr/helm-charts/blockchain-exporter --version 0.1.0
```

### Configuration

The chart supports two configuration approaches:

1. **Declarative Configuration** (recommended): Define blockchains, accounts, and contracts in `values.yaml`:

   ```yaml
   blockchains:
     - name: Ethereum Mainnet
       rpc_url: ${ETH_MAINNET_RPC_ENDPOINT}
       poll_interval: 5m
       accounts:
         - name: Example Account
           address: 0x123...
   ```

1. **Custom ConfigMap**: Provide a complete `config.toml` in `values.yaml`:

   ```yaml
   config:
     toml: |
       [[blockchains]]
       name = "Ethereum Mainnet"
       rpc_url = "${ETH_MAINNET_RPC_ENDPOINT}"
   ```

### Secrets

Secrets can be configured in two ways:

1. **Direct Values** (development/testing): Values are stored in a Kubernetes Secret named `<release-name>-secrets`:

   ```yaml
   secrets:
     - name: ETH_MAINNET_RPC_ENDPOINT
       value: https://eth-mainnet.example.com
   ```

1. **Secret References** (production): Reference existing Kubernetes Secrets:

   ```yaml
   secrets:
     - name: ETH_MAINNET_RPC_ENDPOINT
       secretRef:
         name: rpc-secrets
         key: eth-mainnet-url
   ```

The chart only creates a Secret resource when direct values are provided. When using `secretRef`, no Secret resource is created.

### Probe Configuration

Default probe settings are optimized for fast startup:

- **Startup Probe**: `periodSeconds: 1`, `failureThreshold: 10` (aggressive for quick startup detection).
- **Readiness Probe**: `periodSeconds: 10`, `initialDelaySeconds: 0` (relaxed for normal operation).
- **Liveness Probe**: `periodSeconds: 30`, `initialDelaySeconds: 15` (relaxed to avoid false positives).

These settings can be overridden in `values.yaml`:

```yaml
startupProbe:
  httpGet:
    path: /health/readyz
    port: 8080
  periodSeconds: 1
  failureThreshold: 10
```

## Development Workflow

- `make run`: start both servers (health on `http://localhost:8080`, metrics on `http://localhost:9100`).
- `make lint`: run Ruff, Markdown formatting (`mdformat --check README.md docs`), Hadolint for Dockerfiles, and Helm chart linting.
- `make lint-md`: run only the Markdown lint step.
- `make lint-docker`: run Hadolint against `Dockerfile` (uses local `hadolint` if present, otherwise falls back to Docker).
- `make lint-helm`: lint the Helm chart templates.
- `make test`: execute pytest with coverage (HTML and XML reports generated via pytest-cov).
- `make validate-config CONFIG=path/to/config.toml`: run the TOML validator without starting the app.
- `make print-config CONFIG=path/to/config.toml`: emit the resolved runtime settings with RPC URLs masked by default (use `CONFIG=` to inspect alternate files).
- `make helm-install [VALUES=path/to/values.yaml]`: install or upgrade the Helm chart.
- `make helm-uninstall`: uninstall the Helm chart.

Coverage artifacts are written to `coverage.xml` (for CI) and `htmlcov/` when run locally.

### CLI Examples

- Inspect resolved settings (RPC URLs masked): `make print-config CONFIG=path/to/config.toml` or `python -m blockchain_exporter.cli --config path/to/config.toml --print-resolved`.
- Reveal secrets locally when required: `python -m blockchain_exporter.cli --config path/to/config.toml --print-resolved --show-secrets`.
- Validate configuration without printing: `python -m blockchain_exporter.cli --config path/to/config.toml` (also available via `make validate-config`).
- Cleanup macro (lint + tests + config validation): `make lint && make test && make validate-config` to mirror CI gate behaviour.

## Operational Guidance & Alerting

- **Readiness Lag**: Alert when `/health/readyz` reports `not_ready` for a chain longer than `READINESS_STALE_THRESHOLD_SECONDS`.
- **Polling Failures**: Monitor `blockchain_poll_success{blockchain="…"}` for sustained 0 values; consider paging after multiple poll intervals.
- **Metric Freshness**: Track `blockchain_poll_timestamp_seconds` to ensure values keep increasing; stale timestamps indicate RPC or poller issues.
- **Transfer Activity**: For high-value contracts, alert on sudden drops to zero in `blockchain_contract_transfer_count_window`.
- Include these checks in runbooks with remediation steps (verify RPC health, credentials, redeploy exporter).

## Release Checklist

- Confirm the feature branch is synced with `main` and `git status` is clean aside from intentional release changes.
- Run `make validate-config` (with and without `CONFIG=...`) to ensure all deployment configs pass aggressive validation.
- Execute `make test` and verify the pytest coverage summary keeps the TOTAL line at or above the enforced threshold (currently 85%).
- Inspect `coverage.xml` or open `htmlcov/index.html` to spot untested deltas; add tests for any new gaps before proceeding.
- Push the branch and confirm the GitHub Actions workflow succeeds (lint, tests with coverage, config validation) before tagging or deploying.
- Perform a final smoke test against the release candidate (fast `/health` and `/metrics` probes) to confirm runtime wiring remains sound.
- **Create a release**: After all checks pass, create a release in one of two ways:
  1. **Via GitHub UI** (recommended): Go to Releases → "Draft a new release" → Create tag `v0.0.1` → Publish release
  1. **Via Git**: Create and push a version tag (e.g., `v0.0.1`) to trigger the Docker image build and push:
     ```bash
     git tag v0.0.1
     git push origin v0.0.1
     ```
- **Verify Docker image**: After pushing the tag, the GitHub Actions workflow will automatically build and push the Docker image to `ghcr.io/skthomasjr/blockchain-exporter`. Check the Actions tab to confirm the image was published successfully.
- **Verify Helm chart**: The workflow will also package and push the Helm chart to `ghcr.io/skthomasjr/helm-charts/blockchain-exporter` with the same version as your tag.
- **Make packages public**: After the first release, make both packages public:
  1. Go to your repository on GitHub
  1. Click on "Packages" in the right sidebar (or navigate to `https://github.com/skthomasjr?tab=packages`)
  1. For each package (`blockchain-exporter` Docker image and `helm-charts` Helm chart):
     - Click on the package name
     - Click "Package settings"
     - Scroll to "Danger Zone" and click "Change visibility"
     - Select "Public" and confirm

The Docker image will be available at `ghcr.io/skthomasjr/blockchain-exporter` with tags matching your release versions (e.g., `v0.0.1`, `0.0.1`, `0.0`, `0`).

The Helm chart will be available at `oci://ghcr.io/skthomasjr/helm-charts/blockchain-exporter` with versions matching your release tags (e.g., `0.0.1`).

### CI Expectations

- GitHub Actions workflow runs `make lint` (Ruff, Markdown formatting, Hadolint), `make test` (pytest with coverage), and `make validate-config` on pushes to `main` and pull requests.
- **Docker image build**: When you publish a GitHub release or push a version tag (e.g., `v0.0.1`), the workflow automatically builds and pushes the Docker image to GitHub Container Registry (`ghcr.io/skthomasjr/blockchain-exporter`).
- **Helm chart build**: The same release trigger also packages and pushes the Helm chart to the OCI registry (`oci://ghcr.io/skthomasjr/helm-charts/blockchain-exporter`).
- Coverage gate: ensure the pytest TOTAL line stays at or above **85%** locally before pushing.
- Treat `make lint && make test && make validate-config` as the local pre-push macro to replicate CI.

### Runbook Steps

1. **Regenerate Coverage Reports**: Run `make test` and review `coverage.xml` (for CI) or open `htmlcov/index.html` locally to inspect uncovered paths.
1. **Validate Configuration**: Execute `make validate-config CONFIG=path/to/config.toml` (or omit `CONFIG` to use defaults) before deployment and as part of any pipeline gate.
   - When auditing differences across environments, run `make print-config CONFIG=path/to/config.toml` to review the resolved settings (RPC URLs masked unless `--show-secrets` is used).
1. **Respond to Poller Health Alerts**:
   - Check `/health/details` for the affected chain and note `last_success_timestamp`.
   - Inspect logs filtered by `blockchain=<name>` to identify RPC failures or chunking backoffs.
   - If retry exhaustion continues, redeploy the exporter or switch RPC endpoints, then confirm `blockchain_poll_success` returns to 1.
