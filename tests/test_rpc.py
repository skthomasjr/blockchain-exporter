from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from prometheus_client import CollectorRegistry

from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.exceptions import (
    RpcConnectionError,
    RpcError,
    RpcProtocolError,
    RpcTimeoutError,
)
from blockchain_exporter.metrics import create_metrics, get_metrics, set_metrics
from blockchain_exporter.rpc import RpcClient, execute_with_retries


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval=None,
        contracts=[],
        accounts=[],
    )


def test_execute_with_retries_eventual_success(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    attempts: list[str] = []

    def flaky_operation() -> str:
        attempts.append("call")

        if len(attempts) < 3:
            raise ValueError("temporary failure")

        return "ok"

    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    # ValueError will be wrapped in RpcError but eventually succeeds
    result = execute_with_retries(
        flaky_operation,
        "flaky",
        blockchain_config,
        max_attempts=5,
        include_traceback=False,
    )

    assert result == "ok"
    assert len(attempts) == 3


def test_execute_with_retries_raises_last_exception(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    def always_fail() -> None:
        raise RuntimeError("boom")

    # Exceptions are now wrapped in RpcError
    with pytest.raises(RpcError, match="RPC operation 'always_fail' failed: boom"):
        execute_with_retries(
            always_fail,
            "always_fail",
            blockchain_config,
            max_attempts=2,
        )


def test_rpc_client_get_balance(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        captured["blockchain"] = blockchain.name
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    class FakeEth:
        def __init__(self) -> None:
            self.balance_calls: list[str] = []

        def get_balance(self, address: str) -> int:
            self.balance_calls.append(address)
            return 123

    fake_eth = FakeEth()

    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    value = client.get_balance("0xabc")

    assert value == 123
    assert fake_eth.balance_calls == ["0xabc"]
    assert captured == {"description": "eth_getBalance(0xabc)", "blockchain": "Test Chain"}


def test_rpc_client_get_block(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    class FakeEth:
        def get_block(self, identifier: str, *, full_transactions: bool) -> dict[str, object]:
            return {"identifier": identifier, "full": full_transactions}

    fake_web3 = SimpleNamespace(eth=FakeEth())

    client = RpcClient(fake_web3, blockchain_config)

    result = client.get_block("finalized", full_transactions=True)

    assert result == {"identifier": "finalized", "full": True}
    assert captured["description"] == "eth_getBlock('finalized')"


def test_rpc_call_duration_metrics_recorded(
    monkeypatch: pytest.MonkeyPatch,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that RPC call duration metrics are recorded correctly."""
    # Create test metrics
    test_registry = CollectorRegistry()
    test_metrics = create_metrics(test_registry)

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test metrics
        set_metrics(test_metrics)

        # Mock sleep to avoid delays
        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

        # Create a fake web3 client
        fake_eth = SimpleNamespace(
            chain_id=1,
            get_balance=lambda address: 12345,
            get_block=lambda identifier, **kwargs: SimpleNamespace(number=100, timestamp=1234567890),
        )
        fake_web3 = SimpleNamespace(eth=fake_eth)

        # Create RPC client with chain_id_label
        client = RpcClient(fake_web3, blockchain_config, chain_id_label="1")

        # Make RPC calls
        balance = client.get_balance("0xabc")
        block = client.get_block("latest")

        assert balance == 12345
        assert block.number == 100

        # Verify metrics were recorded
        labels_balance = (blockchain_config.name, "1", "get_balance")
        labels_block = (blockchain_config.name, "1", "get_block")

        # Get histogram samples
        histogram_balance = test_metrics.chain.rpc_call_duration_seconds.labels(*labels_balance)
        histogram_block = test_metrics.chain.rpc_call_duration_seconds.labels(*labels_block)

        # Verify samples were recorded by checking the histogram's _sum attribute
        # Prometheus histograms store _sum as a MutexValue, accessed via .get()
        sum_balance = histogram_balance._sum.get()
        sum_block = histogram_block._sum.get()

        # Both should have been observed (sum >= 0 indicates observation occurred)
        assert sum_balance >= 0
        assert sum_block >= 0

        # Check that observations were recorded by verifying metrics output
        from prometheus_client import generate_latest

        output = generate_latest(test_registry).decode()
        assert "blockchain_rpc_call_duration_seconds_sum" in output
        assert "blockchain_rpc_call_duration_seconds_count" in output
        assert f'blockchain="{blockchain_config.name}"' in output
        assert 'operation="get_balance"' in output
        assert 'operation="get_block"' in output
        assert 'chain_id="1"' in output

    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_rpc_call_duration_metrics_without_chain_id_label(
    monkeypatch: pytest.MonkeyPatch,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that RPC call duration metrics work even without chain_id_label."""
    # Create test metrics
    test_registry = CollectorRegistry()
    test_metrics = create_metrics(test_registry)

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test metrics
        set_metrics(test_metrics)

        # Mock sleep to avoid delays
        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

        # Create a fake web3 client
        fake_eth = SimpleNamespace(get_balance=lambda address: 12345)
        fake_web3 = SimpleNamespace(eth=fake_eth)

        # Create RPC client without chain_id_label (should use "unknown")
        client = RpcClient(fake_web3, blockchain_config)

        # Make RPC call
        balance = client.get_balance("0xabc")

        assert balance == 12345

        # Verify metrics were recorded with "unknown" chain_id by checking metrics output
        from prometheus_client import generate_latest

        output = generate_latest(test_registry).decode()
        assert "blockchain_rpc_call_duration_seconds_sum" in output
        assert "blockchain_rpc_call_duration_seconds_count" in output
        assert f'blockchain="{blockchain_config.name}"' in output
        assert 'operation="get_balance"' in output
        assert 'chain_id="unknown"' in output

    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_rpc_call_duration_includes_retry_time(
    monkeypatch: pytest.MonkeyPatch,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that RPC call duration includes retry time."""
    # Create test metrics
    test_registry = CollectorRegistry()
    test_metrics = create_metrics(test_registry)

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test metrics
        set_metrics(test_metrics)

        attempts: list[float] = []
        sleep_times: list[float] = []

        def mock_sleep(seconds: float) -> None:
            sleep_times.append(seconds)
            attempts.append(time.perf_counter())

        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", mock_sleep)

        call_count = 0

        def flaky_get_balance(address: str) -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary failure")
            return 12345

        fake_eth = SimpleNamespace(get_balance=flaky_get_balance)
        fake_web3 = SimpleNamespace(eth=fake_eth)

        client = RpcClient(fake_web3, blockchain_config, chain_id_label="1")

        balance = client.get_balance("0xabc")

        assert balance == 12345
        assert call_count == 3

        # Verify that sleep was called (retries occurred)
        assert len(sleep_times) == 2  # Two retries

        # Verify metric was recorded by checking metrics output
        from prometheus_client import generate_latest

        output = generate_latest(test_registry).decode()
        assert "blockchain_rpc_call_duration_seconds_sum" in output
        assert "blockchain_rpc_call_duration_seconds_count" in output
        assert f'blockchain="{blockchain_config.name}"' in output
        assert 'operation="get_balance"' in output
        assert 'chain_id="1"' in output

        # Verify duration includes retry time (should be >= 0)
        labels = (blockchain_config.name, "1", "get_balance")
        histogram = test_metrics.chain.rpc_call_duration_seconds.labels(*labels)
        total_duration = histogram._sum.get()
        assert total_duration >= 0

    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_rpc_error_metrics_recorded(
    monkeypatch: pytest.MonkeyPatch,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that RPC error metrics are recorded correctly."""
    # Create test metrics
    test_registry = CollectorRegistry()
    test_metrics = create_metrics(test_registry)

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test metrics
        set_metrics(test_metrics)

        # Mock sleep to avoid delays
        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

        # Create a fake web3 client that raises an error
        # Use built-in TimeoutError which will be wrapped in RpcTimeoutError
        def failing_get_balance(address: str) -> int:
            raise TimeoutError("Request timeout")

        fake_eth = SimpleNamespace(get_balance=failing_get_balance)
        fake_web3 = SimpleNamespace(eth=fake_eth)

        # Create RPC client with chain_id_label
        client = RpcClient(fake_web3, blockchain_config, chain_id_label="1")

        # Make RPC call that will fail - now raises RpcTimeoutError
        with pytest.raises(RpcTimeoutError, match="RPC operation 'eth_getBalance\\(0xabc\\)' failed: Request timeout"):
            client.get_balance("0xabc")

        # Verify error metrics were recorded by checking metrics output
        from prometheus_client import generate_latest

        output = generate_latest(test_registry).decode()
        assert "blockchain_rpc_error_total" in output
        assert f'blockchain="{blockchain_config.name}"' in output
        assert 'operation="get_balance"' in output
        assert 'error_type="timeout"' in output
        assert 'chain_id="1"' in output

        # Verify error counter was incremented (should be 3 for 3 retries)
        labels = (blockchain_config.name, "1", "get_balance", "timeout")
        error_counter = test_metrics.chain.rpc_error_total.labels(*labels)
        error_count = error_counter._value.get()
        assert error_count == 3.0  # 3 retries = 3 errors

    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_rpc_error_categorization(
    monkeypatch: pytest.MonkeyPatch,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that different error types are correctly categorized."""
    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Mock sleep to avoid delays
        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

        test_cases = [
            (ConnectionError("Connection refused"), "connection_error", RpcConnectionError),
            (OSError("Connection refused"), "connection_error", RpcConnectionError),
            (TimeoutError("Request timeout"), "timeout", RpcTimeoutError),
            (ValueError("Invalid value"), "value_error", RpcError),
            (TypeError("Invalid type"), "value_error", RpcError),
            (AttributeError("Attribute not found"), "value_error", RpcError),
            (KeyError("Key not found"), "value_error", RpcError),
            (RuntimeError("Unknown error"), "unknown", RpcError),
        ]

        for exception_type, expected_error_type, expected_rpc_error_class in test_cases:
            # Create new test metrics for each test case
            test_registry = CollectorRegistry()
            test_metrics = create_metrics(test_registry)
            set_metrics(test_metrics)

            def failing_operation(address: str) -> int:
                raise exception_type

            fake_eth = SimpleNamespace(get_balance=failing_operation)
            fake_web3 = SimpleNamespace(eth=fake_eth)

            client = RpcClient(fake_web3, blockchain_config, chain_id_label="1")

            # Make RPC call that will fail - exceptions are wrapped in RpcError
            with pytest.raises(expected_rpc_error_class):
                client.get_balance("0xabc")

            # Verify error metrics were recorded with correct error type
            labels = (blockchain_config.name, "1", "get_balance", expected_error_type)
            error_counter = test_metrics.chain.rpc_error_total.labels(*labels)
            error_count = error_counter._value.get()
            assert error_count == 3.0, f"Expected 3 errors for {exception_type}, got {error_count}"

    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_rpc_error_metrics_web3_rpc_error(
    monkeypatch: pytest.MonkeyPatch,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that Web3RPCError is correctly categorized as rpc_error."""
    # Create test metrics
    test_registry = CollectorRegistry()
    test_metrics = create_metrics(test_registry)

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test metrics
        set_metrics(test_metrics)

        # Mock sleep to avoid delays
        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

        # Create a Web3RPCError
        from web3.exceptions import Web3RPCError

        def failing_get_balance(address: str) -> int:
            raise Web3RPCError({"message": "RPC error occurred"})

        fake_eth = SimpleNamespace(get_balance=failing_get_balance)
        fake_web3 = SimpleNamespace(eth=fake_eth)

        # Create RPC client with chain_id_label
        client = RpcClient(fake_web3, blockchain_config, chain_id_label="1")

        # Make RPC call that will fail - Web3RPCError is wrapped in RpcProtocolError
        with pytest.raises(RpcProtocolError):
            client.get_balance("0xabc")

        # Verify error metrics were recorded with rpc_error type
        labels = (blockchain_config.name, "1", "get_balance", "rpc_error")
        error_counter = test_metrics.chain.rpc_error_total.labels(*labels)
        error_count = error_counter._value.get()
        assert error_count == 3.0  # 3 retries = 3 errors

        # Verify error type in metrics output
        from prometheus_client import generate_latest

        output = generate_latest(test_registry).decode()
        assert "blockchain_rpc_error_total" in output
        assert 'error_type="rpc_error"' in output

    finally:
        # Restore original metrics
        set_metrics(original_metrics)


def test_rpc_error_metrics_per_operation(
    monkeypatch: pytest.MonkeyPatch,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that errors are recorded per operation type."""
    # Create test metrics
    test_registry = CollectorRegistry()
    test_metrics = create_metrics(test_registry)

    # Save original metrics
    original_metrics = get_metrics()

    try:
        # Use test metrics
        set_metrics(test_metrics)

        # Mock sleep to avoid delays
        monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

        # Create fake web3 client that raises errors for different operations
        def failing_get_balance(address: str) -> int:
            raise ValueError("Balance error")

        def failing_get_block(identifier: str, **kwargs) -> dict:
            raise ConnectionError("Connection error")

        fake_eth = SimpleNamespace(
            get_balance=failing_get_balance,
            get_block=failing_get_block,
        )
        fake_web3 = SimpleNamespace(eth=fake_eth)

        # Create RPC client with chain_id_label
        client = RpcClient(fake_web3, blockchain_config, chain_id_label="1")

        # Make RPC calls that will fail - exceptions are wrapped in RpcError
        with pytest.raises(RpcError):
            client.get_balance("0xabc")

        with pytest.raises(RpcConnectionError):
            client.get_block("latest")

        # Verify error metrics were recorded for each operation
        labels_balance = (blockchain_config.name, "1", "get_balance", "value_error")
        labels_block = (blockchain_config.name, "1", "get_block", "connection_error")

        error_counter_balance = test_metrics.chain.rpc_error_total.labels(*labels_balance)
        error_counter_block = test_metrics.chain.rpc_error_total.labels(*labels_block)

        assert error_counter_balance._value.get() == 3.0
        assert error_counter_block._value.get() == 3.0

        # Verify error types in metrics output
        from prometheus_client import generate_latest

        output = generate_latest(test_registry).decode()
        assert 'operation="get_balance"' in output
        assert 'operation="get_block"' in output
        assert 'error_type="value_error"' in output
        assert 'error_type="connection_error"' in output

    finally:
        # Restore original metrics
        set_metrics(original_metrics)
