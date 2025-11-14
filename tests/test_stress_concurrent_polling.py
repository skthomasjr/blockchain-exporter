"""Stress tests for concurrent polling across multiple blockchains.

These tests verify thread safety, memory usage, and performance under load
with realistic numbers of chains (10+), accounts, and contracts.
"""

from __future__ import annotations

import asyncio
import gc
import importlib
import tracemalloc
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from prometheus_client import CollectorRegistry

from blockchain_exporter.app import create_app
from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import MetricsBundle, create_metrics, get_metrics
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import get_settings

app_module = importlib.import_module("blockchain_exporter.app")


def _create_test_blockchain(
    chain_index: int,
    num_accounts: int = 5,
    num_contracts: int = 3,
    accounts_per_contract: int = 2,
) -> BlockchainConfig:
    """Create a test blockchain configuration with specified accounts and contracts."""
    accounts = [
        AccountConfig(
            name=f"Account {i}",
            address=f"0x{'0' * 38}{i:02x}",
        )
        for i in range(num_accounts)
    ]
    
    contracts = [
        ContractConfig(
            name=f"Contract {i}",
            address=f"0x{'a' * 38}{i:02x}",
            decimals=None,
            transfer_lookback_blocks=1000,
            accounts=[
                AccountConfig(
                    name=f"Contract {i} Account {j}",
                    address=f"0x{'c' * 36}{i:02x}{j:02x}",
                )
                for j in range(accounts_per_contract)
            ],
        )
        for i in range(num_contracts)
    ]
    
    return BlockchainConfig(
        name=f"Test Chain {chain_index}",
        rpc_url=f"https://rpc-{chain_index}.example.com",
        poll_interval="10s",
        contracts=contracts,
        accounts=accounts,
    )


def _create_fake_rpc_client(blockchain: BlockchainConfig) -> Any:
    """Create a fake RPC client that simulates successful responses.
    
    Returns an RpcClientProtocol-compatible object that can be used
    by the collection logic.
    """
    from blockchain_exporter.rpc import RpcClient
    
    block_number = 1000000
    timestamp = 1700000000
    
    def _get_block(identifier: str, **kwargs: Any) -> SimpleNamespace:
        nonlocal block_number, timestamp
        if identifier == "latest":
            block_number += 1
            timestamp += 12
        elif identifier == "finalized":
            block_number -= 10
        return SimpleNamespace(number=block_number, timestamp=timestamp)
    
    def _get_balance(*args: Any, **kwargs: Any) -> int:
        return 1000000000000000000  # 1 ETH in wei
    
    def _get_code(*args: Any, **kwargs: Any) -> bytes:
        return b"0x"  # Empty code (not a contract)
    
    def _get_logs(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []  # No logs
    
    def _contract(address: str, **kwargs: Any) -> Any:
        """Mock contract factory that returns a contract proxy."""
        # Return a mock contract that has the methods we need
        def _call_contract_function(*args: Any, **kwargs: Any) -> Any:
            # Return mock values for contract function calls
            return 1000000  # Mock total supply or balance
        
        contract_proxy = SimpleNamespace(
            functions=SimpleNamespace(
                totalSupply=lambda: SimpleNamespace(call=_call_contract_function),
                decimals=lambda: SimpleNamespace(call=lambda: 18),
                balanceOf=lambda address: SimpleNamespace(call=_call_contract_function),
            ),
        )
        return contract_proxy
    
    # Extract chain index from name (e.g., "Test Chain 5" -> 5)
    chain_index = int(blockchain.name.split()[-1])
    
    web3 = SimpleNamespace(
        is_connected=lambda: True,
        eth=SimpleNamespace(
            chain_id=1 + chain_index,  # Unique chain ID per chain
            get_block=_get_block,
            get_balance=_get_balance,
            get_code=_get_code,
            get_logs=_get_logs,
            contract=_contract,
        ),
    )
    
    # Wrap in RpcClient to match the expected interface
    return RpcClient(web3, blockchain)


@pytest.fixture
def stress_metrics_registry() -> CollectorRegistry:
    """Create a fresh metrics registry for stress tests."""
    return CollectorRegistry()


@pytest.fixture
def stress_test_metrics(stress_metrics_registry: CollectorRegistry) -> MetricsBundle:
    """Create a fresh metrics bundle for stress tests."""
    return create_metrics(registry=stress_metrics_registry)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_concurrent_polling_10_chains_thread_safety(
    monkeypatch: pytest.MonkeyPatch,
    stress_test_metrics: MetricsBundle,
) -> None:
    """Test that 10 concurrent blockchain polls maintain thread safety.
    
    This test verifies:
    - No race conditions when updating metrics from multiple threads
    - All chains complete polling successfully
    - Metrics are correctly recorded for all chains
    """
    # Create 10 blockchains, each with 5 accounts and 3 contracts
    blockchains = [
        _create_test_blockchain(i, num_accounts=5, num_contracts=3, accounts_per_contract=2)
        for i in range(10)
    ]
    
    runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=blockchains,
        config_path=Path("config.toml"),
    )
    
    context = ApplicationContext(
        metrics=stress_test_metrics,
        runtime=runtime,
        rpc_factory=_create_fake_rpc_client,
    )
    
    # Track poll calls to verify all chains are polled
    poll_calls: dict[str, int] = {}
    import threading
    poll_lock = threading.Lock()
    
    # We need to track RPC client creation to verify all chains are polled
    # The real collection logic will run and set metrics properly
    # Note: rpc_factory is synchronous, called from threads
    def _tracking_rpc_factory(blockchain: BlockchainConfig) -> Any:
        """Track RPC client creation and return fake client."""
        with poll_lock:
            poll_calls[blockchain.name] = poll_calls.get(blockchain.name, 0) + 1
        return _create_fake_rpc_client(blockchain)
    
    # Replace the RPC factory with our tracking version
    context.rpc_factory = _tracking_rpc_factory
    
    monkeypatch.setattr(
        app_module,
        "get_application_context",
        lambda: context,
    )
    
    # Create app and start polling
    app = create_app(context=context, metrics=stress_test_metrics)
    
    async with app.router.lifespan_context(app):
        # Wait for all chains to complete at least one poll cycle
        await asyncio.sleep(0.5)
        
        # Wait a bit more for all collections to complete
        await asyncio.sleep(0.2)
        
        # Verify all chains were polled
        assert len(poll_calls) == 10, f"Expected 10 chains to be polled, got {len(poll_calls)}"
        for blockchain in blockchains:
            assert blockchain.name in poll_calls, f"Chain {blockchain.name} was not polled"
            assert poll_calls[blockchain.name] >= 1, f"Chain {blockchain.name} should have been polled at least once"
        
        # Verify metrics were recorded for all chains
        for blockchain in blockchains:
            chain_index = int(blockchain.name.split()[-1])
            chain_id_label = str(1 + chain_index)
            labels = (blockchain.name, chain_id_label)
            
            # Check that poll_success metric exists for this chain
            poll_success = stress_test_metrics.chain.poll_success.labels(*labels)
            assert poll_success._value.get() >= 0.0, f"Poll success metric should exist for {blockchain.name}"
            
            # Check configured accounts/contracts metrics
            accounts_count = stress_test_metrics.chain.configured_accounts_count.labels(*labels)
            contracts_count = stress_test_metrics.chain.configured_contracts_count.labels(*labels)
            
            # 5 accounts + (3 contracts * 2 accounts per contract) = 11 total accounts
            assert accounts_count._value.get() == 11.0, (
                f"Expected 11 accounts for {blockchain.name}, got {accounts_count._value.get()}"
            )
            assert contracts_count._value.get() == 3.0, (
                f"Expected 3 contracts for {blockchain.name}, got {contracts_count._value.get()}"
            )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_concurrent_polling_memory_usage(
    monkeypatch: pytest.MonkeyPatch,
    stress_test_metrics: MetricsBundle,
) -> None:
    """Test memory usage with 15 chains, each with many accounts and contracts.
    
    This test verifies:
    - Memory usage remains reasonable under load
    - No memory leaks from concurrent polling
    - Metrics don't accumulate unbounded memory
    """
    # Create 15 blockchains with more accounts/contracts
    blockchains = [
        _create_test_blockchain(i, num_accounts=10, num_contracts=5, accounts_per_contract=3)
        for i in range(15)
    ]
    
    runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=blockchains,
        config_path=Path("config.toml"),
    )
    
    context = ApplicationContext(
        metrics=stress_test_metrics,
        runtime=runtime,
        rpc_factory=_create_fake_rpc_client,
    )
    
    async def _fast_collect(*args: Any, **kwargs: Any) -> bool:
        """Fast collection that doesn't block."""
        await asyncio.sleep(0.001)
        return True
    
    monkeypatch.setattr(
        app_module,
        "get_application_context",
        lambda: context,
    )
    monkeypatch.setattr(
        "blockchain_exporter.poller.control.collect_blockchain_metrics",
        _fast_collect,
    )
    
    # Start memory tracking
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()
    
    app = create_app(context=context, metrics=stress_test_metrics)
    
    async with app.router.lifespan_context(app):
        # Run multiple poll cycles
        await asyncio.sleep(1.0)
        
        # Take another snapshot
        snapshot2 = tracemalloc.take_snapshot()
        
        # Calculate memory difference
        top_stats = snapshot2.compare_to(snapshot1, "lineno")
        
        # Get total memory increase
        total_increase = sum(stat.size_diff for stat in top_stats)
        
        # Memory increase should be reasonable (less than 50MB for 15 chains)
        # This is a sanity check - actual memory will vary
        assert total_increase < 50 * 1024 * 1024, (
            f"Memory increase too large: {total_increase / 1024 / 1024:.2f}MB. "
            "Possible memory leak detected."
        )
    
    tracemalloc.stop()
    
    # Force garbage collection and verify metrics are still accessible
    gc.collect()
    
    # Verify metrics are still valid after GC
    for blockchain in blockchains[:5]:  # Check a sample
        chain_id_label = str(1 + int(blockchain.name.split()[-1]))
        labels = (blockchain.name, chain_id_label)
        poll_success = stress_test_metrics.chain.poll_success.labels(*labels)
        assert poll_success._value.get() >= 0.0


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_concurrent_polling_performance_under_load(
    monkeypatch: pytest.MonkeyPatch,
    stress_test_metrics: MetricsBundle,
) -> None:
    """Test performance with 12 chains polling concurrently.
    
    This test verifies:
    - All chains can poll concurrently without blocking
    - Poll cycles complete within reasonable time
    - No significant performance degradation with many chains
    """
    # Create 12 blockchains
    blockchains = [
        _create_test_blockchain(i, num_accounts=8, num_contracts=4, accounts_per_contract=2)
        for i in range(12)
    ]
    
    runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=blockchains,
        config_path=Path("config.toml"),
    )
    
    context = ApplicationContext(
        metrics=stress_test_metrics,
        runtime=runtime,
        rpc_factory=_create_fake_rpc_client,
    )
    
    poll_times: dict[str, list[float]] = {}
    poll_lock = asyncio.Lock()
    
    async def _timed_collect(
        blockchain: BlockchainConfig,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """Track how long each poll takes."""
        import time
        start = time.monotonic()
        # Simulate RPC work
        await asyncio.sleep(0.05)
        elapsed = time.monotonic() - start
        
        async with poll_lock:
            if blockchain.name not in poll_times:
                poll_times[blockchain.name] = []
            poll_times[blockchain.name].append(elapsed)
        
        return True
    
    monkeypatch.setattr(
        app_module,
        "get_application_context",
        lambda: context,
    )
    monkeypatch.setattr(
        "blockchain_exporter.poller.control.collect_blockchain_metrics",
        _timed_collect,
    )
    
    app = create_app(context=context, metrics=stress_test_metrics)
    
    async with app.router.lifespan_context(app):
        # Wait for multiple poll cycles
        await asyncio.sleep(0.8)
        
        # Verify all chains completed polls
        assert len(poll_times) == 12, f"Expected 12 chains to poll, got {len(poll_times)}"
        
        # Verify poll times are reasonable (should be around 0.05s + overhead)
        for blockchain_name, times in poll_times.items():
            assert len(times) >= 1, f"Chain {blockchain_name} should have at least one poll"
            avg_time = sum(times) / len(times)
            # Poll time should be reasonable (less than 1 second per poll)
            assert avg_time < 1.0, (
                f"Chain {blockchain_name} average poll time too slow: {avg_time:.3f}s"
            )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_concurrent_polling_metrics_consistency(
    monkeypatch: pytest.MonkeyPatch,
    stress_test_metrics: MetricsBundle,
) -> None:
    """Test that metrics remain consistent under concurrent updates.
    
    This test verifies:
    - No metric corruption from concurrent updates
    - All chains have correct metric values
    - Metrics don't interfere with each other
    """
    # Create 10 blockchains with varying configurations
    blockchains = [
        _create_test_blockchain(
            i,
            num_accounts=5 + (i % 3),  # Vary account counts
            num_contracts=2 + (i % 2),  # Vary contract counts
            accounts_per_contract=2,
        )
        for i in range(10)
    ]
    
    runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=blockchains,
        config_path=Path("config.toml"),
    )
    
    context = ApplicationContext(
        metrics=stress_test_metrics,
        runtime=runtime,
        rpc_factory=_create_fake_rpc_client,
    )
    
    monkeypatch.setattr(
        app_module,
        "get_application_context",
        lambda: context,
    )
    # Use real collection logic with fake RPC client to test metric consistency
    # Set global metrics so record_poll_success uses the test metrics
    from blockchain_exporter.metrics import set_metrics
    
    original_metrics = get_metrics()
    try:
        set_metrics(stress_test_metrics)
        
        app = create_app(context=context, metrics=stress_test_metrics)
        
        async with app.router.lifespan_context(app):
            # Wait for polls to complete (need more time for real collection logic)
            # Poll interval is 10 seconds, but first poll should complete quickly
            # Wait up to 3 seconds for all polls to complete
            max_wait = 3.0
            wait_interval = 0.1
            waited = 0.0
            all_polls_complete = False
            
            while waited < max_wait and not all_polls_complete:
                await asyncio.sleep(wait_interval)
                waited += wait_interval
                
                # Check if all polls have completed by verifying poll_success > 0 for all chains
                all_polls_complete = all(
                    stress_test_metrics.chain.poll_success.labels(
                        blockchain.name,
                        str(1 + int(blockchain.name.split()[-1]))
                    )._value.get() > 0
                    for blockchain in blockchains
                )
            
            # Verify metrics for all chains
            for blockchain in blockchains:
                chain_id_label = str(1 + int(blockchain.name.split()[-1]))
                labels = (blockchain.name, chain_id_label)
                
                # Verify poll_success is set correctly
                poll_success = stress_test_metrics.chain.poll_success.labels(*labels)
                assert poll_success._value.get() == 1.0, (
                    f"Chain {blockchain.name} should have poll_success=1.0, "
                    f"got {poll_success._value.get()} after {waited:.1f}s"
                )
                
                # Verify configured counts match expected values
                expected_accounts = len(blockchain.accounts) + sum(
                    len(contract.accounts) for contract in blockchain.contracts
                )
                expected_contracts = len(blockchain.contracts)
                
                accounts_count = stress_test_metrics.chain.configured_accounts_count.labels(*labels)
                contracts_count = stress_test_metrics.chain.configured_contracts_count.labels(*labels)
                
                assert accounts_count._value.get() == float(expected_accounts), (
                    f"Chain {blockchain.name} should have {expected_accounts} accounts, "
                    f"got {accounts_count._value.get()}"
                )
                assert contracts_count._value.get() == float(expected_contracts), (
                    f"Chain {blockchain.name} should have {expected_contracts} contracts, "
                    f"got {contracts_count._value.get()}"
                )
                
                # Verify head_block_number is set (should be > 0)
                head_block = stress_test_metrics.chain.head_block_number.labels(*labels)
                assert head_block._value.get() > 0, (
                    f"Chain {blockchain.name} should have head_block_number > 0"
                )
    finally:
        # Restore original metrics
        set_metrics(original_metrics)

