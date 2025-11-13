from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.metrics import (
    CHAIN_HEALTH_STATUS,
    CHAIN_LABEL_CACHE,
    CHAIN_LAST_SUCCESS,
    CHAIN_RESOLVED_IDS,
    ChainMetricLabelState,
    clear_cached_metrics,
    get_cached_chain_id_label,
    get_metrics,
    handle_chain_id_update,
    record_poll_failure,
    record_poll_success,
    remove_chain_metrics_for_label,
    reset_chain_metrics,
    reset_metrics_state,
    set_configured_blockchains,
)


@pytest.fixture(autouse=True)
def reset_state() -> None:
    reset_metrics_state()
    CHAIN_LABEL_CACHE.clear()
    CHAIN_RESOLVED_IDS.clear()
    CHAIN_HEALTH_STATUS.clear()
    CHAIN_LAST_SUCCESS.clear()

    yield

    reset_metrics_state()
    CHAIN_LABEL_CACHE.clear()
    CHAIN_RESOLVED_IDS.clear()
    CHAIN_HEALTH_STATUS.clear()
    CHAIN_LAST_SUCCESS.clear()


@pytest.fixture
def blockchain() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval="1m",
        contracts=[],
        accounts=[],
    )


def test_reset_metrics_state_replaces_bundle() -> None:
    previous_bundle = get_metrics()

    new_registry = CollectorRegistry()

    new_bundle = reset_metrics_state(new_registry)

    assert new_bundle is get_metrics()
    assert new_bundle is not previous_bundle
    assert new_bundle.registry is new_registry
    assert CHAIN_LABEL_CACHE == {}


def test_record_poll_success_updates_health(blockchain: BlockchainConfig) -> None:
    record_poll_success(blockchain, "1", timestamp=1000.0)

    assert CHAIN_HEALTH_STATUS[(blockchain.name, "1")] is True
    assert CHAIN_LAST_SUCCESS[(blockchain.name, "1")] == 1000.0

    metrics = get_metrics()
    sample = metrics.chain.poll_success._metrics[(blockchain.name, "1")]
    assert sample._value.get() == 1.0


def test_record_poll_failure_clears_health(blockchain: BlockchainConfig) -> None:
    record_poll_success(blockchain, "1", timestamp=1000.0)

    record_poll_failure(blockchain, "1")

    assert CHAIN_HEALTH_STATUS[(blockchain.name, "1")] is False
    assert CHAIN_LAST_SUCCESS[(blockchain.name, "1")] == 1000.0

    metrics = get_metrics()
    assert metrics.chain.poll_success._metrics[(blockchain.name, "1")]._value.get() == 0.0


def test_reset_chain_metrics_zeros_gauges(blockchain: BlockchainConfig) -> None:
    metrics = get_metrics()
    labels = (blockchain.name, "1")

    metrics.chain.head_block_number.labels(*labels).set(123)

    metrics.chain.time_since_last_block.labels(*labels).set(5)

    reset_chain_metrics(blockchain, "1")

    assert metrics.chain.head_block_number._metrics[labels]._value.get() == 0.0
    assert metrics.chain.time_since_last_block._metrics[labels]._value.get() == 0.0


def test_clear_cached_metrics_removes_labels(blockchain: BlockchainConfig) -> None:
    state = ChainMetricLabelState(chain_id_label="1")

    state.account_balance_labels.add(("chain", "1", "acc", "addr", "0"))

    CHAIN_LABEL_CACHE[(blockchain.name, blockchain.rpc_url)] = state

    removed = clear_cached_metrics(blockchain)

    assert removed is True
    assert (blockchain.name, blockchain.rpc_url) not in CHAIN_LABEL_CACHE


def test_remove_chain_metrics_for_label_clears_gauges(blockchain: BlockchainConfig) -> None:
    metrics = get_metrics()
    labels = (blockchain.name, "1")

    metrics.chain.poll_success.labels(*labels).set(1)

    metrics.chain.head_block_number.labels(*labels).set(100)

    CHAIN_HEALTH_STATUS[labels] = True
    CHAIN_LAST_SUCCESS[labels] = 200.0

    remove_chain_metrics_for_label(blockchain, "1")

    assert labels not in metrics.chain.poll_success._metrics
    assert labels not in metrics.chain.head_block_number._metrics
    assert labels not in CHAIN_HEALTH_STATUS
    assert labels not in CHAIN_LAST_SUCCESS


def test_handle_chain_id_update_resets_previous(blockchain: BlockchainConfig) -> None:
    CHAIN_RESOLVED_IDS[(blockchain.name, blockchain.rpc_url)] = "1"
    CHAIN_HEALTH_STATUS[(blockchain.name, "1")] = True

    handle_chain_id_update(blockchain, "2")

    assert get_cached_chain_id_label(blockchain) == "2"
    assert (blockchain.name, "1") not in CHAIN_HEALTH_STATUS


def test_set_configured_blockchains_updates_exporter_metric(
    blockchain: BlockchainConfig,
) -> None:
    metrics = get_metrics()

    set_configured_blockchains([blockchain])

    value = metrics.exporter.configured_blockchains._value.get()

    assert value == 1.0
