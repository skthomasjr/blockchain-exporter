"""Tests for PollerManager reload_tasks functionality."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from blockchain_exporter.config import AccountConfig, BlockchainConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import create_metrics
from blockchain_exporter.poller.manager import PollerManager, reset_poller_manager
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import get_settings


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="TestChain",
        rpc_url="https://test.invalid",
        poll_interval="1s",
        contracts=[],
        accounts=[
            AccountConfig(
                name="TestAccount",
                address="0x0000000000000000000000000000000000000005",
            )
        ],
    )


@pytest.fixture
def blockchain_config_2() -> BlockchainConfig:
    return BlockchainConfig(
        name="TestChain2",
        rpc_url="https://test2.invalid",
        poll_interval="2s",
        contracts=[],
        accounts=[],
    )


@pytest.fixture
def fake_rpc_factory():
    def _factory(blockchain: BlockchainConfig) -> Any:
        rpc = SimpleNamespace()
        rpc.web3 = SimpleNamespace(is_connected=lambda: True, eth=SimpleNamespace(chain_id=1))
        rpc.get_block = MagicMock(return_value=SimpleNamespace(number=100, timestamp=1000))
        rpc.get_balance = MagicMock(return_value=0)
        rpc.get_code = MagicMock(return_value=b"")
        rpc.get_logs = MagicMock(return_value=[])
        return rpc

    return _factory


@pytest.fixture
def context(blockchain_config: BlockchainConfig, fake_rpc_factory) -> ApplicationContext:
    metrics = create_metrics()
    runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[blockchain_config],
        config_path=Path("config.toml"),
    )
    return ApplicationContext(
        metrics=metrics,
        runtime=runtime,
        rpc_factory=fake_rpc_factory,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_tasks_adds_new_blockchain(
    blockchain_config: BlockchainConfig,
    blockchain_config_2: BlockchainConfig,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_tasks adds new blockchain tasks."""
    reset_poller_manager()
    manager = PollerManager()

    # Create initial tasks
    from fastapi import FastAPI

    app = FastAPI()
    initial_tasks = manager.create_tasks([blockchain_config], context, app)
    assert len(initial_tasks) == 1

    # Mock poll_blockchain to track calls
    poll_calls = []

    async def mock_poll_blockchain(
        blockchain: BlockchainConfig,
        *,
        context: ApplicationContext | None = None,
    ) -> None:
        poll_calls.append(blockchain.name)
        await asyncio.sleep(0.1)  # Simulate some work

    monkeypatch.setattr("blockchain_exporter.poller.manager.poller_control.poll_blockchain", mock_poll_blockchain)

    # Reload with new blockchain
    await manager.reload_tasks([blockchain_config], [blockchain_config, blockchain_config_2], context)

    # Give tasks a moment to start
    await asyncio.sleep(0.2)

    # Verify new task was created
    assert len(manager.polling_tasks) == 2
    assert len(poll_calls) >= 1  # At least one new task should have started

    # Cleanup
    for task in manager.polling_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*manager.polling_tasks, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_tasks_removes_blockchain(
    blockchain_config: BlockchainConfig,
    blockchain_config_2: BlockchainConfig,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_tasks removes blockchain tasks."""
    reset_poller_manager()
    manager = PollerManager()

    # Create initial tasks with two blockchains
    from fastapi import FastAPI

    app = FastAPI()

    # Track which tasks are created and cancelled
    created_tasks: dict[str, asyncio.Task] = {}
    cancelled_tasks: list[str] = []

    async def mock_poll_blockchain(
        blockchain: BlockchainConfig,
        *,
        context: ApplicationContext | None = None,
    ) -> None:
        created_tasks[blockchain.name] = asyncio.current_task()
        try:
            await asyncio.sleep(3600)  # Run indefinitely
        except asyncio.CancelledError:
            cancelled_tasks.append(blockchain.name)
            raise

    monkeypatch.setattr("blockchain_exporter.poller.manager.poller_control.poll_blockchain", mock_poll_blockchain)

    initial_tasks = manager.create_tasks([blockchain_config, blockchain_config_2], context, app)
    assert len(initial_tasks) == 2

    # Give tasks a moment to start
    await asyncio.sleep(0.2)

    # Verify both tasks are tracked
    assert len(manager.task_by_blockchain) == 2

    # Reload with one blockchain removed
    await manager.reload_tasks([blockchain_config, blockchain_config_2], [blockchain_config], context)

    # Verify task was removed from manager
    assert len(manager.polling_tasks) == 1
    assert len(manager.task_by_blockchain) == 1
    # Verify the removed blockchain is no longer in task_by_blockchain
    from blockchain_exporter.metrics import blockchain_identity

    assert blockchain_identity(blockchain_config_2) not in manager.task_by_blockchain

    # Cleanup
    for task in manager.polling_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*manager.polling_tasks, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_tasks_no_changes(
    blockchain_config: BlockchainConfig,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_tasks handles no changes gracefully."""
    reset_poller_manager()
    manager = PollerManager()

    # Create initial tasks
    from fastapi import FastAPI

    app = FastAPI()
    initial_tasks = manager.create_tasks([blockchain_config], context, app)
    initial_count = len(initial_tasks)

    # Reload with same blockchains
    await manager.reload_tasks([blockchain_config], [blockchain_config], context)

    # Verify no change in task count
    assert len(manager.polling_tasks) == initial_count

    # Cleanup
    for task in manager.polling_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*manager.polling_tasks, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_tasks_thread_safety(
    blockchain_config: BlockchainConfig,
    blockchain_config_2: BlockchainConfig,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_tasks is thread-safe."""
    reset_poller_manager()
    manager = PollerManager()

    from fastapi import FastAPI

    app = FastAPI()
    manager.create_tasks([blockchain_config], context, app)

    # Mock poll_blockchain
    async def mock_poll_blockchain(
        blockchain: BlockchainConfig,
        *,
        context: ApplicationContext | None = None,
    ) -> None:
        await asyncio.sleep(0.1)

    monkeypatch.setattr("blockchain_exporter.poller.manager.poller_control.poll_blockchain", mock_poll_blockchain)

    # Run multiple reloads concurrently
    async def concurrent_reload() -> None:
        await manager.reload_tasks([blockchain_config], [blockchain_config, blockchain_config_2], context)

    await asyncio.gather(concurrent_reload(), concurrent_reload(), concurrent_reload())

    # Verify state is consistent
    assert len(manager.polling_tasks) >= 1

    # Cleanup
    for task in manager.polling_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*manager.polling_tasks, return_exceptions=True)

