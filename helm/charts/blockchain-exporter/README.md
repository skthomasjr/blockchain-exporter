# blockchain-exporter

A Helm chart for deploying the blockchain-exporter, a FastAPI-based exporter that exposes Prometheus metrics for blockchain monitoring.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.0+

## Installing the Chart

### From OCI Registry (Recommended)

The chart is published to GitHub Container Registry after each release and is publicly accessible:

```bash
helm install blockchain-exporter oci://ghcr.io/skthomasjr/helm-charts/blockchain-exporter --namespace blockchain-exporter --create-namespace

helm upgrade blockchain-exporter oci://ghcr.io/skthomasjr/helm-charts/blockchain-exporter --namespace blockchain-exporter
```

The standard namespace is `blockchain-exporter` (it will be created automatically if it doesn't exist).

> **Note**: The chart is public, so no authentication is required to install it. If you need to publish your own charts to a private registry, use `helm registry login ghcr.io -u <your-github-username>`.

## Uninstalling the Chart

```bash
helm uninstall blockchain-exporter --namespace blockchain-exporter
```

## Configuration

The following table lists the key configurable parameters and their default values:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `1` |
| `image.repository` | Container image repository | `ghcr.io/skthomasjr/images/blockchain-exporter` |
| `image.tag` | Container image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `service.type` | Kubernetes service type | `ClusterIP` |
| `service.healthPort` | Health check port | `8080` |
| `service.metricsPort` | Metrics port | `9100` |
| `blockchains` | Declarative blockchain configuration | `[]` |
| `secrets` | Environment variables for TOML variable interpolation | `[]` |
| `env` | Additional non-secret environment variables | `[]` |
| `resources` | Resource requests and limits | `{}` |
| `livenessProbe` | Liveness probe configuration | See `values.yaml` |
| `readinessProbe` | Readiness probe configuration | See `values.yaml` |
| `startupProbe` | Startup probe configuration | See `values.yaml` |

### Configuration Methods

The chart supports declarative configuration via `blockchains`. Define blockchains, accounts, and contracts declaratively in `values.yaml`, and the chart generates the `config.toml` automatically.

#### Example: Declarative Configuration

```yaml
blockchains:
  - name: Ethereum Mainnet
    rpc_url: ${ETH_MAINNET_RPC_ENDPOINT}
    poll_interval: 1m
    accounts:
      - name: My Wallet
        address: 0x1234567890123456789012345678901234567890
    contracts:
      - name: USDC Token
        address: 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
        transfer_lookback_blocks: 5000
        accounts:
          - name: Token Holder
            address: 0xabcdefabcdefabcdefabcdefabcdefabcdefabcd

secrets:
  - name: ETH_MAINNET_RPC_ENDPOINT
    secretRef:
      name: rpc-secrets
      key: eth-mainnet-url
```

### Secrets Management

Secrets can be provided in two ways:

1. **Direct Values**: Values are stored in a Kubernetes Secret named `<release-name>-secrets`.

   ```yaml
   secrets:
     - name: ETH_MAINNET_RPC_ENDPOINT
       value: https://eth-mainnet.example.com
   ```

1. **Secret References**: Reference existing Kubernetes Secrets.

   ```yaml
   secrets:
     - name: ETH_MAINNET_RPC_ENDPOINT
       secretRef:
         name: rpc-secrets
         key: eth-mainnet-url
   ```

### Resource Limits

Example resource configuration:

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi
```

## Chart Features

- **Dual-Port Architecture**: Health endpoints on port 8080, metrics endpoint on port 9100 for better network isolation.
- **ConfigMap Generation**: Automatically generates `config.toml` from declarative configuration.
- **Secret Management**: Supports both direct values and references to existing Secrets.
- **Health Probes**: Optimized startup, readiness, and liveness probes.
- **Service Account**: Automatically creates a service account with configurable options.

## Upgrading

To upgrade to a newer version:

```bash
helm upgrade blockchain-exporter oci://ghcr.io/skthomasjr/helm-charts/blockchain-exporter --namespace blockchain-exporter
```

## Additional Resources

- [Chart Values Reference](values.yaml)
- [Main README](../../../README.md)
- [Application Documentation](https://github.com/skthomasjr/blockchain-exporter)
