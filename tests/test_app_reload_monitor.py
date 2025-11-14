"""Tests for reload monitor background task in app.py."""

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
from blockchain_exporter.config import AccountConfig, BlockchainConfig
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
        accounts=[
            AccountConfig(
                name="TestAccount",
                address="0x0000000000000000000000000000000000000005",
            )
        ],
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
async def test_reload_monitor_detects_sighup(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload monitor detects SIGHUP and triggers reload."""
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

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    # Mock reload_configuration
    reload_called = False

    async def mock_reload_configuration() -> tuple[bool, str]:
        nonlocal reload_called
        reload_called = True
        return True, "Configuration reloaded successfully"

    monkeypatch.setattr("blockchain_exporter.reload.reload_configuration", mock_reload_configuration)

    # Import and patch _reload_event
    from blockchain_exporter.main import _reload_event

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        # Set the reload event to simulate SIGHUP
        _reload_event.set()

        # Wait for monitor to detect and process
        await asyncio.sleep(1.5)  # Wait longer than the 1s check interval

        # Verify reload was called
        assert reload_called


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_monitor_handles_reload_error(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that reload monitor handles reload errors gracefully."""
    caplog.set_level("ERROR")

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

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    # Mock reload_configuration to fail
    async def mock_reload_configuration() -> tuple[bool, str]:
        return False, "Configuration error: Invalid config"

    monkeypatch.setattr("blockchain_exporter.reload.reload_configuration", mock_reload_configuration)

    # Import and patch _reload_event
    from blockchain_exporter.main import _reload_event

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        # Set the reload event to simulate SIGHUP
        _reload_event.set()

        # Wait for monitor to detect and process
        await asyncio.sleep(1.5)

        # Verify error was logged
        error_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
        assert any("reload failed" in msg.lower() for msg in error_messages)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_monitor_cancels_on_shutdown(
    blockchain_config: BlockchainConfig,
    fake_rpc_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload monitor task is cancelled on shutdown."""
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

    # Mock poll_blockchain
    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        # Give monitor task a moment to start
        await asyncio.sleep(0.1)

    # After shutdown, verify monitor was cancelled (no exception means it handled cancellation gracefully)
    # If we get here without hanging, cancellation worked

