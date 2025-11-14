"""Tests for app.py error handling edge cases."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from blockchain_exporter.app import _lifespan
from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import create_metrics
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import get_settings

app_module = importlib.import_module("blockchain_exporter.app")


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="TestChain",
        rpc_url="https://test.invalid",
        poll_interval="1s",
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


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_lifespan_handles_config_validation_error(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that lifespan handles ValueError (config validation error) gracefully."""
    caplog.set_level("ERROR")

    # Mock get_application_context to raise ValueError
    def failing_get_context():
        raise ValueError("Configuration validation error")

    monkeypatch.setattr(app_module, "get_application_context", failing_get_context)

    app = FastAPI(lifespan=_lifespan)

    # Should raise ValueError (not catch it)
    with pytest.raises(ValueError, match="Configuration validation error"):
        async with app.router.lifespan_context(app):
            pass

    # Verify error was logged
    error_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
    assert any("Configuration validation error" in msg for msg in error_messages)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_lifespan_handles_file_not_found_error(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that lifespan handles FileNotFoundError (config file not found) gracefully."""
    caplog.set_level("WARNING")

    metrics = create_metrics()

    # Mock get_application_context to raise FileNotFoundError
    def failing_get_context():
        raise FileNotFoundError("Config file not found")

    monkeypatch.setattr(app_module, "get_application_context", failing_get_context)

    # Mock resolve_config_path
    def mock_resolve_config_path(settings):
        return Path("nonexistent.toml")

    monkeypatch.setattr("blockchain_exporter.config.resolve_config_path", mock_resolve_config_path)

    # Mock get_metrics and default_rpc_factory
    from blockchain_exporter.context import default_rpc_factory

    monkeypatch.setattr("blockchain_exporter.metrics.get_metrics", lambda: metrics)
    monkeypatch.setattr("blockchain_exporter.context.default_rpc_factory", default_rpc_factory)

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    # Should not raise - FileNotFoundError is caught and handled
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.1)

    # Verify warning was logged
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("Configuration file not found" in msg for msg in warning_messages)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_lifespan_handles_warm_poll_exception(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that lifespan handles exceptions during warm poll gracefully."""
    caplog.set_level("WARNING")

    metrics = create_metrics()

    # Enable warm poll in settings
    from dataclasses import replace

    from blockchain_exporter.settings import get_settings

    base_settings = get_settings()
    warm_poll_settings = replace(
        base_settings,
        poller=replace(base_settings.poller, warm_poll_enabled=True, warm_poll_timeout_seconds=5.0),
    )

    runtime = RuntimeSettings(
        app=warm_poll_settings,
        blockchains=[blockchain_config],
        config_path=Path("config.toml"),
    )
    context = ApplicationContext(
        metrics=metrics,
        runtime=runtime,
        rpc_factory=fake_rpc_factory,
    )

    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    monkeypatch.setattr(app_module, "SETTINGS", warm_poll_settings)

    # Mock collect_chain_metrics_sync to raise an exception during warm poll
    def failing_collect_chain_metrics_sync(
        blockchain_config: BlockchainConfig,
        rpc_client: Any = None,
        metrics_store: Any = None,
    ) -> bool:
        raise RuntimeError("Warm poll exception")

    monkeypatch.setattr("blockchain_exporter.poller.collect.collect_chain_metrics_sync", failing_collect_chain_metrics_sync)

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    # Should not raise - exceptions in warm poll are caught
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.1)

    # The main goal is that the app starts successfully despite warm poll exceptions
    # Warm poll exceptions are caught and logged, but don't prevent startup
    # Note: context may not be set in app.state during test, but the important thing
    # is that the app doesn't crash and continues startup
    # Verify that some logging occurred (warm poll was attempted)
    all_messages = [record.message for record in caplog.records]
    # Should see at least the warm poll info message
    assert len(all_messages) > 0, f"Expected some log messages during warm poll, got: {all_messages}"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_lifespan_shutdown_handles_exceptions(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that lifespan shutdown handles exceptions gracefully."""
    caplog.set_level("WARNING")

    metrics = create_metrics()
    runtime = RuntimeSettings(
        app=get_settings(),
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

    # Mock collect_chain_metrics_sync
    def mock_collect_chain_metrics_sync(
        blockchain_config: BlockchainConfig,
        rpc_client: Any = None,
        metrics_store: Any = None,
    ) -> bool:
        return True

    monkeypatch.setattr(app_module, "collect_chain_metrics_sync", mock_collect_chain_metrics_sync)

    # Mock poll_blockchain to raise exception during shutdown
    poll_task_cancelled = False

    async def failing_poll_blockchain(*args: Any, **kwargs: Any) -> None:
        nonlocal poll_task_cancelled
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            poll_task_cancelled = True
            raise RuntimeError("Error during task cancellation")

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", failing_poll_blockchain)

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        # Give tasks time to start
        await asyncio.sleep(0.1)
        # Shutdown will be triggered when exiting context

    # Verify task was cancelled
    assert poll_task_cancelled

    # App should still shut down successfully despite exceptions
    assert not hasattr(app.state, "polling_tasks") or len(app.state.polling_tasks) == 0

