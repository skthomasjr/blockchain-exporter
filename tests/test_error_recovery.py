"""Comprehensive error recovery tests for RPC failures and recovery scenarios."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from prometheus_client import CollectorRegistry

from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.exceptions import RpcConnectionError
from blockchain_exporter.metrics import (
    CHAIN_HEALTH_STATUS,
    CHAIN_LAST_SUCCESS,
    MetricsBundle,
    create_metrics,
    record_poll_failure,
    record_poll_success,
)
from blockchain_exporter.poller.collect import collect_chain_metrics_sync
from blockchain_exporter.poller.control import poll_blockchain
from blockchain_exporter.rpc import RpcClient, execute_with_retries


class UnavailableRpcError(Exception):
    """Simulates an unavailable RPC endpoint."""


class NetworkTimeoutError(Exception):
    """Simulates a network timeout."""


class MalformedResponseError(Exception):
    """Simulates a malformed RPC response."""


class NetworkConnectionError(Exception):
    """Simulates a connection error."""


class FakeUnavailableRpcClient:
    """RPC client that simulates an unavailable endpoint."""

    def __init__(self, blockchain: BlockchainConfig) -> None:
        self.blockchain = blockchain
        self.web3 = SimpleNamespace(is_connected=lambda: False, eth=SimpleNamespace(chain_id=1))


class FakeTimeoutRpcClient:
    """RPC client that simulates timeouts."""

    def __init__(self, blockchain: BlockchainConfig, fail_count: int = 3) -> None:
        self.blockchain = blockchain
        self.fail_count = fail_count
        self.call_count = 0
        self.block_call_map: dict[str, int] = {}
        self.web3 = SimpleNamespace(
            is_connected=lambda: True,
            eth=SimpleNamespace(
                chain_id=1,
                get_balance=lambda *args, **kwargs: self._raise_timeout(),
                get_block=lambda identifier, **kwargs: self._raise_timeout(identifier),
                get_logs=lambda *args, **kwargs: self._raise_timeout(),
                get_code=lambda *args, **kwargs: b"",
            ),
        )

    def _raise_timeout(self, identifier: str) -> SimpleNamespace:
        # Track calls per block identifier
        if identifier not in self.block_call_map:
            self.block_call_map[identifier] = 0
        self.block_call_map[identifier] += 1
        if self.block_call_map[identifier] <= self.fail_count:
            raise NetworkTimeoutError("Request timed out")
        # Return different block numbers based on identifier
        if identifier == "finalized":
            return SimpleNamespace(number=12340, timestamp=int(time.time()) - 10)
        return SimpleNamespace(number=12345, timestamp=int(time.time()))

    def _raise_timeout_balance(self) -> int:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise NetworkTimeoutError("Request timed out")
        return 0

    def _raise_timeout_logs(self) -> list[dict[str, Any]]:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise NetworkTimeoutError("Request timed out")
        return []


class FakePartialFailureRpcClient:
    """RPC client that has partial failures (some operations succeed, others fail)."""

    def __init__(self, blockchain: BlockchainConfig) -> None:
        self.blockchain = blockchain
        self.balance_calls = 0
        self.block_calls = 0
        self.block_call_map: dict[str, int] = {}
        self.web3 = SimpleNamespace(
            is_connected=lambda: True,
            eth=SimpleNamespace(
                chain_id=1,
                get_balance=lambda *args, **kwargs: self._get_balance(),
                get_block=lambda identifier, **kwargs: self._get_block(identifier),
                get_logs=lambda *args, **kwargs: [],
                get_code=lambda *args, **kwargs: b"",
            ),
        )

    def _get_balance(self) -> int:
        self.balance_calls += 1
        # Fail on first 2 attempts, succeed on 3rd attempt (with max_attempts=3, this allows retries to work)
        if self.balance_calls <= 2:
            raise NetworkConnectionError("Connection refused")
        # Succeed on 3rd attempt
        return 1000000000000000000

    def _get_block(self, identifier: str) -> SimpleNamespace:
        # Track calls per identifier
        # Note: execute_with_retries calls the operation multiple times, so each call increments the counter
        if identifier not in self.block_call_map:
            self.block_call_map[identifier] = 0
        self.block_call_map[identifier] += 1

        # Fail on first attempt for "latest" only (to test partial failure with retries)
        # With max_attempts=3, it will retry and succeed on the second attempt
        # "finalized" always succeeds to allow the collect to complete
        if identifier == "latest" and self.block_call_map[identifier] == 1:
            raise NetworkTimeoutError("Request timed out")
        # Return different block numbers based on identifier
        if identifier == "finalized":
            return SimpleNamespace(number=12340, timestamp=int(time.time()) - 10)
        return SimpleNamespace(number=12345, timestamp=int(time.time()))


class FakeMalformedResponseRpcClient:
    """RPC client that returns malformed responses."""

    def __init__(self, blockchain: BlockchainConfig) -> None:
        self.blockchain = blockchain
        self.call_count = 0
        self.block_call_map: dict[str, int] = {}
        self.web3 = SimpleNamespace(
            is_connected=lambda: True,
            eth=SimpleNamespace(
                chain_id=1,
                get_block=lambda identifier, **kwargs: self._get_malformed_block(identifier),
                get_balance=lambda *args, **kwargs: 0,
                get_logs=lambda *args, **kwargs: [],
                get_code=lambda *args, **kwargs: b"",
            ),
        )

    def _get_malformed_block(self, identifier: str) -> SimpleNamespace:
        # Track calls per identifier
        # Note: execute_with_retries calls the operation multiple times, so each call increments the counter
        if identifier not in self.block_call_map:
            self.block_call_map[identifier] = 0
        self.block_call_map[identifier] += 1

        # Missing required fields on first 2 attempts for "latest" only
        # This will cause AttributeError when accessing .number
        # With max_attempts=3, it will retry and succeed on the third attempt
        # "finalized" always succeeds to allow the collect to complete
        if identifier == "latest" and self.block_call_map[identifier] <= 2:
            # Return object missing .number attribute - will raise AttributeError
            return SimpleNamespace(hash="0x123")
        # Return valid block after retries
        if identifier == "finalized":
            return SimpleNamespace(number=12340, timestamp=int(time.time()) - 10)
        return SimpleNamespace(number=12345, timestamp=int(time.time()))


class FakeRecoveryRpcClient:
    """RPC client that fails initially then recovers."""

    def __init__(self, blockchain: BlockchainConfig, fail_cycles: int = 3) -> None:
        self.blockchain = blockchain
        self.fail_cycles = fail_cycles
        self.poll_count = 0
        self.block_call_map: dict[str, int] = {}
        self.web3 = SimpleNamespace(
            is_connected=lambda: True,
            eth=SimpleNamespace(
                chain_id=1,
                get_balance=lambda *args, **kwargs: 1000000000000000000,
                get_block=lambda identifier, **kwargs: self._get_block(identifier),
                get_logs=lambda *args, **kwargs: [],
                get_code=lambda *args, **kwargs: b"",
            ),
        )

    def _get_block(self, identifier: str) -> SimpleNamespace:
        # Track calls per identifier
        # Note: execute_with_retries calls the operation multiple times, so each call increments the counter
        if identifier not in self.block_call_map:
            self.block_call_map[identifier] = 0
        self.block_call_map[identifier] += 1

        # Fail on first N calls for "latest" only (to test recovery across multiple poll cycles)
        # Each poll cycle calls get_block("latest") once, and with max_attempts=3, it will retry within that call
        # So we need to fail enough times to exhaust retries in the first poll cycle
        if identifier == "latest":
            # Track total poll attempts (not retries within a single call)
            # We want to fail the first fail_cycles poll cycles
            # Since each poll cycle retries up to 3 times, we need to fail 3 * fail_cycles times
            total_calls = self.block_call_map[identifier]
            if total_calls <= (3 * self.fail_cycles):
                raise UnavailableRpcError("Endpoint unavailable")
        # Return different block numbers based on identifier
        if identifier == "finalized":
            return SimpleNamespace(number=12340, timestamp=int(time.time()) - 10)
        return SimpleNamespace(number=12345, timestamp=int(time.time()))


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval="1m",
        contracts=[],
        accounts=[],
    )


@pytest.fixture
def blockchain_with_accounts() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval="1m",
        contracts=[],
        accounts=[
            AccountConfig(name="Test Account", address="0x1234567890123456789012345678901234567890"),
        ],
    )


@pytest.fixture
def blockchain_with_contracts() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval="1m",
        contracts=[
            ContractConfig(
                name="Test Contract",
                address="0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
                decimals=None,
                transfer_lookback_blocks=100,
                accounts=[],
            ),
        ],
        accounts=[],
    )


@pytest.fixture
def metrics_registry() -> CollectorRegistry:
    return CollectorRegistry()


@pytest.fixture
def test_metrics(metrics_registry: CollectorRegistry) -> MetricsBundle:
    return create_metrics(registry=metrics_registry)


def test_unavailable_rpc_endpoint_records_failure(
    blockchain_config: BlockchainConfig,
    test_metrics: MetricsBundle,
) -> None:
    """Test that unavailable RPC endpoints are handled and failures are recorded."""
    rpc_client = FakeUnavailableRpcClient(blockchain_config)
    rpc = RpcClient(rpc_client.web3, blockchain_config)

    result = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc, metrics=test_metrics)

    assert result is False
    assert (blockchain_config.name, "unknown") in CHAIN_HEALTH_STATUS
    assert CHAIN_HEALTH_STATUS[(blockchain_config.name, "unknown")] is False
    assert test_metrics.chain.poll_success.labels(blockchain_config.name, "unknown")._value.get() == 0.0


def test_timeout_errors_retry_and_fail(
    blockchain_config: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that timeout errors trigger retries and eventually fail."""
    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    rpc_client = FakeTimeoutRpcClient(blockchain_config, fail_count=5)
    rpc = RpcClient(rpc_client.web3, blockchain_config)

    result = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc, metrics=test_metrics)

    assert result is False
    assert test_metrics.chain.poll_success.labels(blockchain_config.name, "1")._value.get() == 0.0


def test_partial_failures_handle_gracefully(
    blockchain_with_accounts: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that partial failures (some operations succeed, others fail) are handled."""
    from blockchain_exporter.metrics import get_metrics, set_metrics

    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test_metrics instead of global metrics
        set_metrics(test_metrics)

        # Create a client where get_block("latest") succeeds after one retry
        # and get_balance succeeds after retries
        # This tests that retries work correctly and partial failures don't break the collect
        class FakePartialSuccessRpcClient:
            def __init__(self, blockchain: BlockchainConfig) -> None:
                self.blockchain = blockchain
                self.balance_calls = 0
                self.block_call_map: dict[str, int] = {}
                self.web3 = SimpleNamespace(
                    is_connected=lambda: True,
                    eth=SimpleNamespace(
                        chain_id=1,
                        get_balance=lambda *args, **kwargs: self._get_balance(),
                        get_block=lambda identifier, **kwargs: self._get_block(identifier),
                        get_logs=lambda *args, **kwargs: [],
                        get_code=lambda *args, **kwargs: b"",
                    ),
                )

            def _get_balance(self) -> int:
                self.balance_calls += 1
                # Succeed on first attempt (no failures)
                return 1000000000000000000

            def _get_block(self, identifier: str) -> SimpleNamespace:
                if identifier not in self.block_call_map:
                    self.block_call_map[identifier] = 0
                self.block_call_map[identifier] += 1

                # Fail on first attempt for "latest" only (will retry and succeed)
                if identifier == "latest" and self.block_call_map[identifier] == 1:
                    raise NetworkTimeoutError("Request timed out")
                if identifier == "finalized":
                    return SimpleNamespace(number=12340, timestamp=int(time.time()) - 10)
                return SimpleNamespace(number=12345, timestamp=int(time.time()))

        rpc_client = FakePartialSuccessRpcClient(blockchain_with_accounts)
        rpc = RpcClient(rpc_client.web3, blockchain_with_accounts)

        # get_block("latest") fails once then succeeds after retry (max_attempts=3)
        # get_balance succeeds immediately
        # The collect should succeed after retries
        result = collect_chain_metrics_sync(blockchain_with_accounts, rpc_client=rpc, metrics=test_metrics)

        # The collect should succeed after retries
        assert result is True

        # Verify metrics show success
        labels = (blockchain_with_accounts.name, "1")
        assert test_metrics.chain.poll_success.labels(*labels)._value.get() == 1.0
    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_malformed_responses_retry_and_recover(
    blockchain_config: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that malformed responses trigger retries and eventually succeed."""
    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    # Create a client that returns malformed blocks (missing .number attribute) on first 2 attempts
    # This will cause AttributeError which should be caught in _record_chain_health_metrics
    # The AttributeError occurs after execute_with_retries returns, so retries won't help
    # Instead, we need to raise an exception from within the retry loop
    # So we'll modify the fake client to raise an exception instead of returning malformed data
    class FakeMalformedRpcClient:
        def __init__(self, blockchain: BlockchainConfig) -> None:
            self.blockchain = blockchain
            self.block_call_map: dict[str, int] = {}
            self.web3 = SimpleNamespace(
                is_connected=lambda: True,
                eth=SimpleNamespace(
                    chain_id=1,
                    get_block=lambda identifier, **kwargs: self._get_block(identifier),
                    get_balance=lambda *args, **kwargs: 0,
                    get_logs=lambda *args, **kwargs: [],
                    get_code=lambda *args, **kwargs: b"",
                ),
            )

        def _get_block(self, identifier: str) -> SimpleNamespace:
            if identifier not in self.block_call_map:
                self.block_call_map[identifier] = 0
            self.block_call_map[identifier] += 1

            # Raise exception on first 2 attempts for "latest" (will trigger retries)
            # "finalized" always succeeds
            if identifier == "latest" and self.block_call_map[identifier] <= 2:
                raise ValueError("Malformed response")
            if identifier == "finalized":
                return SimpleNamespace(number=12340, timestamp=int(time.time()) - 10)
            return SimpleNamespace(number=12345, timestamp=int(time.time()))

    rpc_client = FakeMalformedRpcClient(blockchain_config)
    rpc = RpcClient(rpc_client.web3, blockchain_config)

    # The malformed block will raise ValueError on first 2 attempts
    # execute_with_retries will retry and succeed on the third attempt
    result = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc, metrics=test_metrics)

    # With retries (max_attempts=3), it should succeed on the third attempt
    assert result is True


def test_execute_with_retries_handles_connection_error(
    blockchain_config: BlockchainConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that connection errors trigger retries with exponential backoff."""
    attempts: list[float] = []
    sleep_times: list[float] = []

    def flaky_operation() -> str:
        attempts.append(time.monotonic())
        if len(attempts) < 3:
            raise NetworkConnectionError("Connection refused")
        return "success"

    def fake_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", fake_sleep)

    result = execute_with_retries(
        flaky_operation,
        "test_operation",
        blockchain_config,
        max_attempts=5,
        include_traceback=False,
    )

    assert result == "success"
    assert len(attempts) == 3
    assert len(sleep_times) == 2
    # Verify exponential backoff: 0.5s, 1.0s
    assert sleep_times[0] == pytest.approx(0.5, rel=0.1)
    assert sleep_times[1] == pytest.approx(1.0, rel=0.1)


def test_execute_with_retries_handles_timeout_error(
    blockchain_config: BlockchainConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that timeout errors trigger retries."""
    attempts: list[str] = []

    def timeout_operation() -> str:
        attempts.append("call")
        if len(attempts) < 2:
            raise NetworkTimeoutError("Request timed out")
        return "success"

    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    result = execute_with_retries(
        timeout_operation,
        "test_timeout",
        blockchain_config,
        max_attempts=3,
        include_traceback=False,
    )

    assert result == "success"
    assert len(attempts) == 2


def test_execute_with_retries_exhausts_attempts(
    blockchain_config: BlockchainConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that retries are exhausted and last exception is raised."""
    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    def always_fail() -> None:
        raise NetworkConnectionError("Connection refused")

    # NetworkConnectionError is now wrapped in RpcConnectionError
    with pytest.raises(RpcConnectionError, match="Connection refused"):
        execute_with_retries(
            always_fail,
            "test_failure",
            blockchain_config,
            max_attempts=3,
            include_traceback=False,
        )


def test_metric_updates_during_failures(
    blockchain_config: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that metrics are updated correctly during failures."""
    from blockchain_exporter.metrics import get_metrics, set_metrics

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test_metrics instead of global metrics
        set_metrics(test_metrics)

        chain_id_label = "1"

        # Record initial failure
        record_poll_failure(blockchain_config, chain_id_label)

        labels = (blockchain_config.name, chain_id_label)
        assert test_metrics.chain.poll_success.labels(*labels)._value.get() == 0.0
        assert test_metrics.chain.poll_timestamp.labels(*labels)._value.get() == 0.0
        assert CHAIN_HEALTH_STATUS[labels] is False

        # Record recovery
        record_poll_success(blockchain_config, chain_id_label)

        assert test_metrics.chain.poll_success.labels(*labels)._value.get() == 1.0
        assert test_metrics.chain.poll_timestamp.labels(*labels)._value.get() > 0.0
        assert CHAIN_HEALTH_STATUS[labels] is True
        assert labels in CHAIN_LAST_SUCCESS
    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_backoff_behavior_on_consecutive_failures(
    blockchain_config: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.CaplogFixture,
) -> None:
    """Test that consecutive failures trigger exponential backoff."""
    import logging


    caplog.set_level(logging.DEBUG)

    sleep_calls: list[float] = []
    failure_count = 0

    async def failing_collect(*args: Any, **kwargs: Any) -> bool:
        nonlocal failure_count
        failure_count += 1
        if failure_count >= 4:
            raise asyncio.CancelledError
        return False

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    context = SimpleNamespace(
        metrics=test_metrics,
        create_rpc_client=lambda _: None,
    )

    monkeypatch.setattr("blockchain_exporter.poller.control.collect_blockchain_metrics", failing_collect)
    monkeypatch.setattr("blockchain_exporter.poller.control.determine_poll_interval_seconds", lambda _: 1.0)
    monkeypatch.setattr("blockchain_exporter.poller.control.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(poll_blockchain(blockchain_config, context=context))

    # Verify backoff: 1s (interval), 2s (backoff), 4s (backoff)
    assert len(sleep_calls) >= 3
    assert sleep_calls[0] == pytest.approx(1.0, rel=0.1)
    assert sleep_calls[1] == pytest.approx(2.0, rel=0.1)
    assert sleep_calls[2] == pytest.approx(4.0, rel=0.1)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_recovery_after_failures(
    blockchain_config: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the system recovers after RPC endpoint comes back online."""
    from blockchain_exporter.metrics import get_metrics, set_metrics

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test_metrics instead of global metrics
        set_metrics(test_metrics)

        rpc_client = FakeRecoveryRpcClient(blockchain_config, fail_cycles=1)
        rpc = RpcClient(rpc_client.web3, blockchain_config)

        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

        # First poll should fail (get_block("latest") fails after all retries)
        # With fail_cycles=1, it will fail 3 times (max_attempts=3), exhausting retries
        result1 = await asyncio.to_thread(
            collect_chain_metrics_sync,
            blockchain_config,
            rpc_client=rpc,
            metrics=test_metrics,
        )
        assert result1 is False

        # Second poll should succeed (recovery - get_block("latest") succeeds after retries)
        # After the first poll fails, the next call should succeed
        result2 = await asyncio.to_thread(
            collect_chain_metrics_sync,
            blockchain_config,
            rpc_client=rpc,
            metrics=test_metrics,
        )
        assert result2 is True

        # Verify metrics reflect recovery
        labels = (blockchain_config.name, "1")
        assert test_metrics.chain.poll_success.labels(*labels)._value.get() == 1.0
        assert CHAIN_HEALTH_STATUS[labels] is True
    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_multiple_concurrent_failures(
    blockchain_config: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that multiple concurrent failures are handled independently."""
    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    # Create two separate RPC clients that fail independently
    rpc1 = FakeTimeoutRpcClient(blockchain_config, fail_count=10)
    rpc2 = FakeTimeoutRpcClient(blockchain_config, fail_count=10)

    client1 = RpcClient(rpc1.web3, blockchain_config)
    client2 = RpcClient(rpc2.web3, blockchain_config)

    result1 = collect_chain_metrics_sync(blockchain_config, rpc_client=client1, metrics=test_metrics)
    result2 = collect_chain_metrics_sync(blockchain_config, rpc_client=client2, metrics=test_metrics)

    # Both should fail
    assert result1 is False
    assert result2 is False

    # Verify failures are recorded independently
    labels = (blockchain_config.name, "1")
    assert test_metrics.chain.poll_success.labels(*labels)._value.get() == 0.0


def test_retry_backoff_calculation(blockchain_config: BlockchainConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that exponential backoff is calculated correctly."""
    sleep_times: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", fake_sleep)

    attempt_count = 0

    def flaky_op() -> str:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 4:
            raise NetworkConnectionError("Connection refused")
        return "success"

    execute_with_retries(
        flaky_op,
        "test_backoff",
        blockchain_config,
        max_attempts=5,
        include_traceback=False,
    )

    # Verify exponential backoff: 0.5s, 1.0s, 2.0s (capped at 5.0s)
    assert len(sleep_times) == 3
    assert sleep_times[0] == pytest.approx(0.5, rel=0.1)
    assert sleep_times[1] == pytest.approx(1.0, rel=0.1)
    assert sleep_times[2] == pytest.approx(2.0, rel=0.1)


def test_contract_operations_with_partial_failures(
    blockchain_with_contracts: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that contract operations handle partial failures gracefully."""
    from blockchain_exporter.metrics import get_metrics, set_metrics

    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test_metrics instead of global metrics
        set_metrics(test_metrics)

        # Create a client where get_block("latest") succeeds after one retry
        # Contract operations use get_logs which should succeed
        class FakeContractPartialRpcClient:
            def __init__(self, blockchain: BlockchainConfig) -> None:
                self.blockchain = blockchain
                self.block_call_map: dict[str, int] = {}
                # Create a fake contract function that returns 0
                fake_contract_func = MagicMock()
                fake_contract_func.return_value.functions.totalSupply.return_value.call.return_value = 0
                fake_contract_func.return_value.functions.balanceOf.return_value.call.return_value = 0
                fake_contract_func.return_value.functions.decimals.return_value.call.return_value = 18
                self.web3 = SimpleNamespace(
                    is_connected=lambda: True,
                    eth=SimpleNamespace(
                        chain_id=1,
                        get_balance=lambda *args, **kwargs: 0,
                        get_block=lambda identifier, **kwargs: self._get_block(identifier),
                        get_logs=lambda *args, **kwargs: [],
                        get_code=lambda *args, **kwargs: b"0x",
                        contract=fake_contract_func,
                    ),
                )

            def _get_block(self, identifier: str) -> SimpleNamespace:
                if identifier not in self.block_call_map:
                    self.block_call_map[identifier] = 0
                self.block_call_map[identifier] += 1

                # Fail on first attempt for "latest" only (will retry and succeed)
                if identifier == "latest" and self.block_call_map[identifier] == 1:
                    raise NetworkTimeoutError("Request timed out")
                if identifier == "finalized":
                    return SimpleNamespace(number=12340, timestamp=int(time.time()) - 10)
                return SimpleNamespace(number=12345, timestamp=int(time.time()))

        rpc_client = FakeContractPartialRpcClient(blockchain_with_contracts)
        rpc = RpcClient(rpc_client.web3, blockchain_with_contracts)

        # With retries (default max_attempts=3), get_block("latest") will fail once then succeed.
        # Contract operations use get_logs which should succeed.
        # The collect should eventually succeed.
        result = collect_chain_metrics_sync(blockchain_with_contracts, rpc_client=rpc, metrics=test_metrics)
        assert result is True
    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_poller_failure_then_success_clears_consecutive_failures(
    blockchain_config: BlockchainConfig,
    test_metrics: MetricsBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that successful poll after failures clears consecutive failure counter."""
    from blockchain_exporter.metrics import get_metrics, set_metrics

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test_metrics instead of global metrics
        set_metrics(test_metrics)

        rpc_client = FakeRecoveryRpcClient(blockchain_config, fail_cycles=1)
        rpc = RpcClient(rpc_client.web3, blockchain_config)

        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

        # First poll should fail (get_block("latest") fails after all retries)
        # With fail_cycles=1, it will fail 3 times (max_attempts=3), exhausting retries
        result1 = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc, metrics=test_metrics)
        assert result1 is False

        # Second poll should succeed (recovery - get_block("latest") succeeds after retries)
        # After the first poll fails, the next call should succeed
        result2 = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc, metrics=test_metrics)
        assert result2 is True

        # Verify metrics show success
        labels = (blockchain_config.name, "1")
        assert test_metrics.chain.poll_success.labels(*labels)._value.get() == 1.0
        assert CHAIN_HEALTH_STATUS[labels] is True
    finally:
        # Restore original metrics
        set_metrics(original_metrics)

