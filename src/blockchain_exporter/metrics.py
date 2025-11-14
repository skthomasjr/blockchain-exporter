"""Prometheus metric registry and helpers for blockchain exporter state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, Protocol, runtime_checkable

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from .config import BlockchainConfig


@dataclass(slots=True)
class ExporterMetrics:
    up: Gauge
    configured_blockchains: Gauge
    poller_thread_count: Gauge


@dataclass(slots=True)
class AccountMetrics:
    balance_eth: Gauge
    balance_wei: Gauge
    token_balance: Gauge
    token_balance_raw: Gauge


@dataclass(slots=True)
class ContractMetrics:
    balance_eth: Gauge
    balance_wei: Gauge
    token_supply: Gauge
    transfer_count: Gauge


@dataclass(slots=True)
class ChainMetrics:
    head_block_number: Gauge
    finalized_block_number: Gauge
    head_block_timestamp: Gauge
    time_since_last_block: Gauge
    poll_success: Gauge
    poll_timestamp: Gauge
    configured_accounts_count: Gauge
    configured_contracts_count: Gauge
    rpc_call_duration_seconds: Histogram
    rpc_error_total: Counter
    poll_duration_seconds: Histogram
    consecutive_failures: Gauge
    backoff_duration_seconds: Histogram
    log_chunks_created_total: Counter
    log_blocks_queried_per_chunk: Histogram
    log_chunk_duration_seconds: Histogram


@runtime_checkable
class MetricsStoreProtocol(Protocol):
    registry: CollectorRegistry
    exporter: ExporterMetrics
    account: AccountMetrics
    contract: ContractMetrics
    chain: ChainMetrics


@dataclass(slots=True)
class MetricsBundle(MetricsStoreProtocol):
    registry: CollectorRegistry
    exporter: ExporterMetrics
    account: AccountMetrics
    contract: ContractMetrics
    chain: ChainMetrics


def create_metrics(registry: CollectorRegistry | None = None) -> MetricsBundle:
    registry = registry or CollectorRegistry()

    exporter = ExporterMetrics(
        up=Gauge(
            "blockchain_exporter_up",
            "Indicates whether the exporter is available (1 for up, 0 for down).",
            registry=registry,
        ),
        configured_blockchains=Gauge(
            "blockchain_exporter_configured_blockchains",
            "Number of blockchains currently configured in the exporter.",
            registry=registry,
        ),
        poller_thread_count=Gauge(
            "blockchain_exporter_poller_thread_count",
            "Number of active polling threads (tasks) currently running.",
            registry=registry,
        ),
    )

    account = AccountMetrics(
        balance_eth=Gauge(
            "blockchain_account_balance_eth",
            "Current account balance expressed in Ether for configured blockchain accounts.",
            labelnames=("blockchain", "chain_id", "account_name", "account_address", "is_contract"),
            registry=registry,
        ),
        balance_wei=Gauge(
            "blockchain_account_balance_wei",
            "Current account balance expressed in Wei for configured blockchain accounts.",
            labelnames=("blockchain", "chain_id", "account_name", "account_address", "is_contract"),
            registry=registry,
        ),
        token_balance=Gauge(
            "blockchain_account_token_balance",
            "Current ERC-20 token balance expressed using token decimals for configured blockchain accounts.",
            labelnames=(
                "blockchain",
                "chain_id",
                "token_name",
                "token_address",
                "token_decimals",
                "account_name",
                "account_address",
                "is_contract",
            ),
            registry=registry,
        ),
        token_balance_raw=Gauge(
            "blockchain_account_token_balance_raw",
            "Current ERC-20 token balance in raw units for configured blockchain accounts.",
            labelnames=(
                "blockchain",
                "chain_id",
                "token_name",
                "token_address",
                "token_decimals",
                "account_name",
                "account_address",
                "is_contract",
            ),
            registry=registry,
        ),
    )

    contract = ContractMetrics(
        balance_eth=Gauge(
            "blockchain_contract_balance_eth",
            "Current contract balance expressed in Ether for configured blockchain contracts.",
            labelnames=("blockchain", "chain_id", "contract_name", "contract_address"),
            registry=registry,
        ),
        balance_wei=Gauge(
            "blockchain_contract_balance_wei",
            "Current contract balance expressed in Wei for configured blockchain contracts.",
            labelnames=("blockchain", "chain_id", "contract_name", "contract_address"),
            registry=registry,
        ),
        token_supply=Gauge(
            "blockchain_contract_token_total_supply",
            "Total token supply for ERC-compliant contracts.",
            labelnames=("blockchain", "chain_id", "contract_name", "contract_address"),
            registry=registry,
        ),
        transfer_count=Gauge(
            "blockchain_contract_transfer_count_window",
            "Number of token Transfer events observed within the configured block window.",
            labelnames=("blockchain", "chain_id", "contract_name", "contract_address", "window_blocks"),
            registry=registry,
        ),
    )

    chain = ChainMetrics(
        head_block_number=Gauge(
            "blockchain_chain_head_block_number",
            "Latest block number reported by the blockchain RPC endpoint.",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        finalized_block_number=Gauge(
            "blockchain_chain_finalized_block_number",
            "Finalized block number reported by the blockchain RPC endpoint.",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        head_block_timestamp=Gauge(
            "blockchain_chain_head_block_timestamp_seconds",
            "Unix timestamp of the latest block reported by the blockchain RPC endpoint.",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        time_since_last_block=Gauge(
            "blockchain_chain_time_since_last_block_seconds",
            "Time elapsed in seconds since the latest block was produced.",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        poll_success=Gauge(
            "blockchain_poll_success",
            "Indicates whether the most recent polling cycle succeeded (1) or failed (0).",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        poll_timestamp=Gauge(
            "blockchain_poll_timestamp_seconds",
            "Unix timestamp of the most recent successful polling cycle.",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        configured_accounts_count=Gauge(
            "blockchain_chain_configured_accounts_count",
            "Total number of configured accounts (including contract accounts) per blockchain.",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        configured_contracts_count=Gauge(
            "blockchain_chain_configured_contracts_count",
            "Total number of configured contracts per blockchain.",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        rpc_call_duration_seconds=Histogram(
            "blockchain_rpc_call_duration_seconds",
            "Duration of RPC calls in seconds, measured per blockchain, chain_id, and operation type.",
            labelnames=("blockchain", "chain_id", "operation"),
            buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            registry=registry,
        ),
        rpc_error_total=Counter(
            "blockchain_rpc_error_total",
            "Total number of RPC errors, categorized by error type, blockchain, chain_id, and operation.",
            labelnames=("blockchain", "chain_id", "operation", "error_type"),
            registry=registry,
        ),
        poll_duration_seconds=Histogram(
            "blockchain_poll_duration_seconds",
            "Duration of polling cycles in seconds, measured per blockchain and chain_id.",
            labelnames=("blockchain", "chain_id"),
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
            registry=registry,
        ),
        consecutive_failures=Gauge(
            "blockchain_poll_consecutive_failures",
            "Number of consecutive polling failures for a blockchain, per chain_id.",
            labelnames=("blockchain", "chain_id"),
            registry=registry,
        ),
        backoff_duration_seconds=Histogram(
            "blockchain_poll_backoff_duration_seconds",
            "Duration of backoff delays in seconds after polling failures, per blockchain and chain_id.",
            labelnames=("blockchain", "chain_id"),
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0),
            registry=registry,
        ),
        log_chunks_created_total=Counter(
            "blockchain_log_chunks_created_total",
            "Total number of log chunks created for large log queries, per blockchain, chain_id, and contract address.",
            labelnames=("blockchain", "chain_id", "contract_address"),
            registry=registry,
        ),
        log_blocks_queried_per_chunk=Histogram(
            "blockchain_log_blocks_queried_per_chunk",
            "Number of blocks queried per log chunk, per blockchain, chain_id, and contract address.",
            labelnames=("blockchain", "chain_id", "contract_address"),
            buckets=(10, 50, 100, 250, 500, 1000, 2000, 5000, 10000),
            registry=registry,
        ),
        log_chunk_duration_seconds=Histogram(
            "blockchain_log_chunk_duration_seconds",
            "Duration of individual log chunk queries in seconds, per blockchain, chain_id, and contract address.",
            labelnames=("blockchain", "chain_id", "contract_address"),
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            registry=registry,
        ),
    )

    return MetricsBundle(
        registry=registry,
        exporter=exporter,
        account=account,
        contract=contract,
        chain=chain,
    )


_METRICS: MetricsStoreProtocol = create_metrics()


def get_metrics() -> MetricsStoreProtocol:
    return _METRICS


def set_metrics(bundle: MetricsStoreProtocol) -> None:
    global _METRICS
    _METRICS = bundle


def reset_metrics_state(registry: CollectorRegistry | None = None) -> MetricsStoreProtocol:
    """Rebuild the metrics bundle and clear all cached label state."""

    bundle = create_metrics(registry)
    set_metrics(bundle)

    CHAIN_LABEL_CACHE.clear()
    CHAIN_RESOLVED_IDS.clear()
    CONFIGURED_BLOCKCHAINS.clear()
    CHAIN_HEALTH_STATUS.clear()
    CHAIN_LAST_SUCCESS.clear()

    return bundle


@dataclass(slots=True)
class ChainMetricLabelState:
    chain_id_label: str

    account_balance_labels: set[tuple[str, str, str, str, str]] = field(default_factory=set)

    contract_balance_labels: set[tuple[str, str, str, str]] = field(default_factory=set)

    contract_transfer_labels: set[tuple[str, str, str, str, str]] = field(default_factory=set)

    account_token_labels: set[tuple[str, str, str, str, str, str, str, str]] = field(default_factory=set)


CHAIN_LABEL_CACHE: dict[tuple[str, str], ChainMetricLabelState] = {}

CHAIN_RESOLVED_IDS: dict[tuple[str, str], str] = {}

CONFIGURED_BLOCKCHAINS: set[tuple[str, str]] = set()

CHAIN_HEALTH_STATUS: dict[tuple[str, str], bool] = {}

CHAIN_LAST_SUCCESS: Dict[tuple[str, str], float] = {}


def set_configured_blockchains(blockchains: Iterable[BlockchainConfig]) -> None:
    CONFIGURED_BLOCKCHAINS.clear()

    for blockchain in blockchains:
        CONFIGURED_BLOCKCHAINS.add(blockchain_identity(blockchain))

    metrics = get_metrics()

    blockchain_count = len(CONFIGURED_BLOCKCHAINS)

    metrics.exporter.configured_blockchains.set(blockchain_count)


def blockchain_identity(blockchain: BlockchainConfig) -> tuple[str, str]:
    """Return a stable identity for a blockchain configuration."""

    return (blockchain.name, blockchain.rpc_url)


def update_chain_label_cache(
    blockchain: BlockchainConfig,
    state: ChainMetricLabelState,
) -> None:
    """Cache the most recently recorded labels for the chain."""

    CHAIN_LABEL_CACHE[blockchain_identity(blockchain)] = state


def get_cached_chain_id_label(blockchain: BlockchainConfig) -> str | None:
    return CHAIN_RESOLVED_IDS.get(blockchain_identity(blockchain))


def clear_cached_metrics(blockchain: BlockchainConfig) -> bool:
    state = CHAIN_LABEL_CACHE.pop(blockchain_identity(blockchain), None)

    if state is None:
        return False

    metrics = get_metrics()

    remove_chain_metrics_for_label(blockchain, state.chain_id_label)
    CHAIN_HEALTH_STATUS.pop((blockchain.name, state.chain_id_label), None)
    CHAIN_LAST_SUCCESS.pop((blockchain.name, state.chain_id_label), None)

    for labels in state.account_balance_labels:
        _safe_remove_metric(metrics.account.balance_eth, labels)
        _safe_remove_metric(metrics.account.balance_wei, labels)

    for labels in state.contract_balance_labels:
        _safe_remove_metric(metrics.contract.balance_eth, labels)
        _safe_remove_metric(metrics.contract.balance_wei, labels)
        _safe_remove_metric(metrics.contract.token_supply, labels)

    for labels in state.contract_transfer_labels:
        _safe_remove_metric(metrics.contract.transfer_count, labels)

    for labels in state.account_token_labels:
        _safe_remove_metric(metrics.account.token_balance, labels)
        _safe_remove_metric(metrics.account.token_balance_raw, labels)

    return True


def _safe_remove_metric(gauge: Gauge, labels: tuple[str, ...]) -> None:
    try:
        gauge.remove(*labels)
    except KeyError:
        pass


def remove_chain_metrics_for_label(
    blockchain: BlockchainConfig,
    chain_id_label: str,
) -> None:
    """Remove all metrics associated with the specified chain label."""

    metrics = get_metrics()
    label_tuple = (blockchain.name, chain_id_label)

    _safe_remove_metric(metrics.chain.poll_success, label_tuple)
    _safe_remove_metric(metrics.chain.poll_timestamp, label_tuple)
    _safe_remove_metric(metrics.chain.head_block_number, label_tuple)
    _safe_remove_metric(metrics.chain.finalized_block_number, label_tuple)
    _safe_remove_metric(metrics.chain.head_block_timestamp, label_tuple)
    _safe_remove_metric(metrics.chain.time_since_last_block, label_tuple)
    _safe_remove_metric(metrics.chain.configured_accounts_count, label_tuple)
    _safe_remove_metric(metrics.chain.configured_contracts_count, label_tuple)
    # Note: We don't remove rpc_call_duration_seconds metrics as they are histograms
    # that accumulate over time and don't need explicit cleanup.
    CHAIN_HEALTH_STATUS.pop(label_tuple, None)
    CHAIN_LAST_SUCCESS.pop(label_tuple, None)


def reset_chain_metrics(
    blockchain: BlockchainConfig,
    chain_id_label: str | None = None,
    *,
    metrics: MetricsStoreProtocol | None = None,
) -> None:
    """Reset chain-level gauges for the provided label.

    Args:
        blockchain: The blockchain configuration.
        chain_id_label: Optional chain ID label (defaults to cached or 'unknown').
        metrics: Optional metrics store (defaults to global metrics).
    """
    metrics_store = metrics or get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label)

    metrics_store.chain.head_block_number.labels(*labels).set(0)
    metrics_store.chain.finalized_block_number.labels(*labels).set(0)
    metrics_store.chain.head_block_timestamp.labels(*labels).set(0)
    metrics_store.chain.time_since_last_block.labels(*labels).set(0)
    metrics_store.chain.configured_accounts_count.labels(*labels).set(0)
    metrics_store.chain.configured_contracts_count.labels(*labels).set(0)


def record_poll_success(
    blockchain: BlockchainConfig,
    chain_id_label: str,
    *,
    timestamp: float | None = None,
    metrics: MetricsStoreProtocol | None = None,
) -> None:
    """Record a successful polling cycle for the given chain.

    Args:
        blockchain: The blockchain configuration.
        chain_id_label: The chain ID label.
        timestamp: Optional timestamp (defaults to current time).
        metrics: Optional metrics store (defaults to global metrics).
    """
    metrics_store = metrics or get_metrics()
    labels = (blockchain.name, chain_id_label)

    now = time.time() if timestamp is None else timestamp

    metrics_store.chain.poll_success.labels(*labels).set(1)
    metrics_store.chain.poll_timestamp.labels(*labels).set(now)
    CHAIN_HEALTH_STATUS[(blockchain.name, chain_id_label)] = True
    CHAIN_LAST_SUCCESS[(blockchain.name, chain_id_label)] = now


def record_poll_failure(
    blockchain: BlockchainConfig,
    chain_id_label: str | None = None,
    *,
    metrics: MetricsStoreProtocol | None = None,
) -> None:
    """Record a failed polling cycle for the given chain.

    Args:
        blockchain: The blockchain configuration.
        chain_id_label: Optional chain ID label (defaults to cached or 'unknown').
        metrics: Optional metrics store (defaults to global metrics).
    """
    metrics_store = metrics or get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label)

    metrics_store.chain.poll_success.labels(*labels).set(0)
    metrics_store.chain.poll_timestamp.labels(*labels).set(0)

    reset_chain_metrics(blockchain, resolved_label, metrics=metrics_store)
    clear_cached_metrics(blockchain)
    CHAIN_HEALTH_STATUS[(blockchain.name, resolved_label)] = False


def handle_chain_id_update(
    blockchain: BlockchainConfig,
    new_label: str,
) -> None:
    identity = blockchain_identity(blockchain)

    previous = CHAIN_RESOLVED_IDS.get(identity)

    if previous == new_label:
        return

    if previous:
        cleared = clear_cached_metrics(blockchain)

        if not cleared:
            remove_chain_metrics_for_label(blockchain, previous)
            CHAIN_HEALTH_STATUS.pop((blockchain.name, previous), None)

    CHAIN_RESOLVED_IDS[identity] = new_label


def record_rpc_call_duration(
    blockchain: BlockchainConfig,
    operation: str,
    duration_seconds: float,
    chain_id_label: str | None = None,
) -> None:
    """Record the duration of an RPC call.

    Args:
        blockchain: The blockchain configuration.
        operation: The operation type (e.g., "get_balance", "get_block", "get_logs").
        duration_seconds: The duration of the RPC call in seconds.
        chain_id_label: The chain ID label. If None, will attempt to resolve from cache.
    """
    metrics = get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label, operation)

    metrics.chain.rpc_call_duration_seconds.labels(*labels).observe(duration_seconds)


def record_rpc_error(
    blockchain: BlockchainConfig,
    operation: str,
    error_type: str,
    chain_id_label: str | None = None,
) -> None:
    """Record an RPC error.

    Args:
        blockchain: The blockchain configuration.
        operation: The operation type (e.g., "get_balance", "get_block", "get_logs").
        error_type: The error category (e.g., "timeout", "connection_error", "rpc_error", "value_error", "unknown").
        chain_id_label: The chain ID label. If None, will attempt to resolve from cache.
    """
    metrics = get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label, operation, error_type)

    metrics.chain.rpc_error_total.labels(*labels).inc()


def record_poll_duration(
    blockchain: BlockchainConfig,
    duration_seconds: float,
    chain_id_label: str | None = None,
) -> None:
    """Record the duration of a polling cycle.

    Args:
        blockchain: The blockchain configuration.
        duration_seconds: The duration of the polling cycle in seconds.
        chain_id_label: The chain ID label. If None, will attempt to resolve from cache.
    """
    metrics = get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label)

    metrics.chain.poll_duration_seconds.labels(*labels).observe(duration_seconds)


def record_consecutive_failures(
    blockchain: BlockchainConfig,
    consecutive_failures: int,
    chain_id_label: str | None = None,
) -> None:
    """Record the number of consecutive polling failures.

    Args:
        blockchain: The blockchain configuration.
        consecutive_failures: The number of consecutive failures.
        chain_id_label: The chain ID label. If None, will attempt to resolve from cache.
    """
    metrics = get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label)

    metrics.chain.consecutive_failures.labels(*labels).set(float(consecutive_failures))


def record_backoff_duration(
    blockchain: BlockchainConfig,
    backoff_seconds: float,
    chain_id_label: str | None = None,
) -> None:
    """Record the duration of a backoff delay.

    Args:
        blockchain: The blockchain configuration.
        backoff_seconds: The duration of the backoff delay in seconds.
        chain_id_label: The chain ID label. If None, will attempt to resolve from cache.
    """
    metrics = get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label)

    metrics.chain.backoff_duration_seconds.labels(*labels).observe(backoff_seconds)


def update_poller_thread_count(active_count: int) -> None:
    """Update the number of active polling threads (tasks).

    Args:
        active_count: The number of active polling tasks.
    """
    metrics = get_metrics()
    metrics.exporter.poller_thread_count.set(float(active_count))


def record_log_chunk_created(
    blockchain: BlockchainConfig,
    contract_address: str,
    chain_id_label: str | None = None,
) -> None:
    """Record that a log chunk was created for a large log query.

    Args:
        blockchain: The blockchain configuration.
        contract_address: The contract address being queried.
        chain_id_label: The chain ID label. If None, will attempt to resolve from cache.
    """
    metrics = get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label, contract_address.lower())

    metrics.chain.log_chunks_created_total.labels(*labels).inc()


def record_log_chunk_blocks(
    blockchain: BlockchainConfig,
    contract_address: str,
    blocks_queried: int,
    chain_id_label: str | None = None,
) -> None:
    """Record the number of blocks queried in a log chunk.

    Args:
        blockchain: The blockchain configuration.
        contract_address: The contract address being queried.
        blocks_queried: The number of blocks queried in this chunk.
        chain_id_label: The chain ID label. If None, will attempt to resolve from cache.
    """
    metrics = get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label, contract_address.lower())

    metrics.chain.log_blocks_queried_per_chunk.labels(*labels).observe(float(blocks_queried))


def record_log_chunk_duration(
    blockchain: BlockchainConfig,
    contract_address: str,
    duration_seconds: float,
    chain_id_label: str | None = None,
) -> None:
    """Record the duration of a log chunk query.

    Args:
        blockchain: The blockchain configuration.
        contract_address: The contract address being queried.
        duration_seconds: The duration of the chunk query in seconds.
        chain_id_label: The chain ID label. If None, will attempt to resolve from cache.
    """
    metrics = get_metrics()
    resolved_label = chain_id_label or get_cached_chain_id_label(blockchain) or "unknown"

    labels = (blockchain.name, resolved_label, contract_address.lower())

    metrics.chain.log_chunk_duration_seconds.labels(*labels).observe(duration_seconds)


__all__ = [
    "AccountMetrics",
    "ChainMetricLabelState",
    "ChainMetrics",
    "ContractMetrics",
    "ExporterMetrics",
    "MetricsBundle",
    "MetricsStoreProtocol",
    "blockchain_identity",
    "clear_cached_metrics",
    "create_metrics",
    "get_cached_chain_id_label",
    "get_metrics",
    "handle_chain_id_update",
    "record_backoff_duration",
    "record_consecutive_failures",
    "record_log_chunk_blocks",
    "record_log_chunk_created",
    "record_log_chunk_duration",
    "record_poll_duration",
    "record_poll_failure",
    "record_poll_success",
    "record_rpc_call_duration",
    "record_rpc_error",
    "remove_chain_metrics_for_label",
    "reset_chain_metrics",
    "reset_metrics_state",
    "set_configured_blockchains",
    "set_metrics",
    "update_chain_label_cache",
    "update_poller_thread_count",
]
