"""Tests for warm poll edge cases in app.py."""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from blockchain_exporter.app import _lifespan
from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import create_metrics
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import AppSettings, get_settings

app_module = importlib.import_module("blockchain_exporter.app")


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="TestChain",
        rpc_url="https://test.invalid",
        poll_interval="1s",
        contracts=[
            ContractConfig(
                name="Token",
                address="0x0000000000000000000000000000000000000010",
                decimals=None,
                accounts=[],
                transfer_lookback_blocks=None,
            )
        ],
        accounts=[
            AccountConfig(
                name="Treasury",
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


def _build_settings_with_warm_poll(enabled: bool, timeout: float = 30.0) -> AppSettings:
    base_settings = get_settings()

    return replace(
        base_settings,
        poller=replace(
            base_settings.poller,
            warm_poll_enabled=enabled,
            warm_poll_timeout_seconds=timeout,
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_warm_poll_timeout_scenario(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that warm poll handles timeout scenarios gracefully."""
    caplog.set_level("WARNING")

    metrics = create_metrics()
    runtime = RuntimeSettings(
        app=_build_settings_with_warm_poll(enabled=True, timeout=0.1),  # Very short timeout
        blockchains=[blockchain_config],
        config_path=Path("config.toml"),
    )
    context = ApplicationContext(
        metrics=metrics,
        runtime=runtime,
        rpc_factory=fake_rpc_factory,
    )

    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    monkeypatch.setattr(app_module, "SETTINGS", runtime.app)

    # Mock collect_chain_metrics_sync to take longer than timeout
    def slow_collect_chain_metrics_sync(
        blockchain_config: BlockchainConfig,
        rpc_client: Any = None,
        metrics_store: Any = None,
    ) -> bool:
        import time

        time.sleep(1.0)  # Sleep longer than timeout
        return True

    monkeypatch.setattr(
        app_module,
        "collect_chain_metrics_sync",
        slow_collect_chain_metrics_sync,
    )

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        # Give warm poll a moment to timeout
        await asyncio.sleep(0.2)

    # Verify timeout was logged
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("Warm poll timed out" in msg for msg in warning_messages)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_warm_poll_error_handling(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that warm poll handles errors gracefully without failing startup."""
    caplog.set_level("WARNING")

    metrics = create_metrics()
    runtime = RuntimeSettings(
        app=_build_settings_with_warm_poll(enabled=True, timeout=5.0),
        blockchains=[blockchain_config],
        config_path=Path("config.toml"),
    )
    context = ApplicationContext(
        metrics=metrics,
        runtime=runtime,
        rpc_factory=fake_rpc_factory,
    )

    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    monkeypatch.setattr(app_module, "SETTINGS", runtime.app)

    # Mock collect_chain_metrics_sync to raise an exception
    def failing_collect_chain_metrics_sync(
        blockchain_config: BlockchainConfig,
        rpc_client: Any = None,
        metrics_store: Any = None,
    ) -> bool:
        raise RuntimeError("Warm poll error")

    monkeypatch.setattr(
        app_module,
        "collect_chain_metrics_sync",
        failing_collect_chain_metrics_sync,
    )

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    # Should not raise - errors are caught and logged
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.1)

    # Verify error was logged
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("Warm poll raised exception" in msg or "Warm poll encountered error" in msg for msg in warning_messages)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_warm_poll_multiple_blockchains(
    blockchain_config: BlockchainConfig,
    blockchain_config_2: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that warm poll works with multiple blockchains."""
    metrics = create_metrics()
    runtime = RuntimeSettings(
        app=_build_settings_with_warm_poll(enabled=True, timeout=5.0),
        blockchains=[blockchain_config, blockchain_config_2],
        config_path=Path("config.toml"),
    )
    context = ApplicationContext(
        metrics=metrics,
        runtime=runtime,
        rpc_factory=fake_rpc_factory,
    )

    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    monkeypatch.setattr(app_module, "SETTINGS", runtime.app)

    # Track which blockchains were polled
    polled_blockchains: list[str] = []

    def tracking_collect_chain_metrics_sync(
        blockchain_config: BlockchainConfig,
        rpc_client: Any = None,
        metrics_store: Any = None,
    ) -> bool:
        polled_blockchains.append(blockchain_config.name)
        return True

    monkeypatch.setattr(
        app_module,
        "collect_chain_metrics_sync",
        tracking_collect_chain_metrics_sync,
    )

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        # Give warm poll time to complete
        await asyncio.sleep(0.2)

    # Verify both blockchains were polled
    assert len(polled_blockchains) == 2
    assert blockchain_config.name in polled_blockchains
    assert blockchain_config_2.name in polled_blockchains


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_warm_poll_partial_success_failure(
    blockchain_config: BlockchainConfig,
    blockchain_config_2: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that warm poll handles partial success/failure scenarios."""
    caplog.set_level("WARNING")

    metrics = create_metrics()
    runtime = RuntimeSettings(
        app=_build_settings_with_warm_poll(enabled=True, timeout=5.0),
        blockchains=[blockchain_config, blockchain_config_2],
        config_path=Path("config.toml"),
    )
    context = ApplicationContext(
        metrics=metrics,
        runtime=runtime,
        rpc_factory=fake_rpc_factory,
    )

    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    monkeypatch.setattr(app_module, "SETTINGS", runtime.app)

    # Mock collect_chain_metrics_sync to succeed for one, fail for another
    def partial_collect_chain_metrics_sync(
        blockchain_config: BlockchainConfig,
        rpc_client: Any = None,
        metrics_store: Any = None,
    ) -> bool:
        if blockchain_config.name == "TestChain":
            return True
        return False  # Fail for TestChain2

    monkeypatch.setattr(
        app_module,
        "collect_chain_metrics_sync",
        partial_collect_chain_metrics_sync,
    )

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        # Give warm poll time to complete
        await asyncio.sleep(0.2)

    # Verify partial failure was logged
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("Warm poll failed" in msg for msg in warning_messages)

    # App should still start successfully despite partial failure
    # Context is set during lifespan, verify it exists
    assert hasattr(app.state, "context")
    # Note: context may be None if lifespan hasn't fully initialized, but app should still be functional


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_warm_poll_skipped_when_disabled(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that warm poll is skipped when disabled."""
    metrics = create_metrics()
    runtime = RuntimeSettings(
        app=_build_settings_with_warm_poll(enabled=False),
        blockchains=[blockchain_config],
        config_path=Path("config.toml"),
    )
    context = ApplicationContext(
        metrics=metrics,
        runtime=runtime,
        rpc_factory=fake_rpc_factory,
    )

    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    monkeypatch.setattr(app_module, "SETTINGS", runtime.app)

    warm_poll_called = False

    def tracking_collect_chain_metrics_sync(
        blockchain_config: BlockchainConfig,
        rpc_client: Any = None,
        metrics_store: Any = None,
    ) -> bool:
        nonlocal warm_poll_called
        warm_poll_called = True
        return True

    monkeypatch.setattr(
        app_module,
        "collect_chain_metrics_sync",
        tracking_collect_chain_metrics_sync,
    )

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.1)

    # Warm poll should not have been called
    assert warm_poll_called is False

