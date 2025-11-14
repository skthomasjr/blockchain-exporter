"""Tests for context helper functions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from blockchain_exporter.config import AccountConfig, BlockchainConfig
from blockchain_exporter.context import (
    ApplicationContext,
    create_default_context,
    default_rpc_factory,
    get_application_context,
    reset_application_context,
    set_application_context,
)
from blockchain_exporter.metrics import create_metrics, reset_metrics_state, set_metrics
from blockchain_exporter.rpc import RpcClient
from blockchain_exporter.runtime_settings import RuntimeSettings, reset_runtime_settings_cache
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


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """Reset context and metrics state before each test."""
    reset_application_context()
    reset_metrics_state()
    reset_runtime_settings_cache()
    yield
    reset_application_context()
    reset_metrics_state()
    reset_runtime_settings_cache()


def test_default_rpc_factory_creates_rpc_client(blockchain_config: BlockchainConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that default_rpc_factory creates an RpcClient using connection pool."""
    # Mock the connection pool manager
    mock_web3 = SimpleNamespace(
        is_connected=lambda: True,
        eth=SimpleNamespace(chain_id=1),
    )

    mock_pool_manager = MagicMock()
    mock_pool_manager.get_client.return_value = mock_web3

    def mock_get_pool_manager():
        return mock_pool_manager

    monkeypatch.setattr("blockchain_exporter.poller.connection_pool.get_connection_pool_manager", mock_get_pool_manager)

    rpc_client = default_rpc_factory(blockchain_config)

    assert isinstance(rpc_client, RpcClient)
    assert rpc_client.web3 is mock_web3
    mock_pool_manager.get_client.assert_called_once_with(blockchain_config)


def test_default_rpc_factory_uses_connection_pool(blockchain_config: BlockchainConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that default_rpc_factory uses connection pool for multiple calls."""
    mock_web3 = SimpleNamespace(
        is_connected=lambda: True,
        eth=SimpleNamespace(chain_id=1),
    )

    mock_pool_manager = MagicMock()
    mock_pool_manager.get_client.return_value = mock_web3

    def mock_get_pool_manager():
        return mock_pool_manager

    monkeypatch.setattr("blockchain_exporter.poller.connection_pool.get_connection_pool_manager", mock_get_pool_manager)

    # Create multiple RPC clients for the same blockchain
    rpc_client1 = default_rpc_factory(blockchain_config)
    rpc_client2 = default_rpc_factory(blockchain_config)

    # Both should use the same pool manager
    assert mock_pool_manager.get_client.call_count == 2
    assert isinstance(rpc_client1, RpcClient)
    assert isinstance(rpc_client2, RpcClient)


def test_create_default_context_loads_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that create_default_context loads runtime settings and creates context."""
    # Mock get_runtime_settings to return a test runtime
    test_runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[],
        config_path=Path("config.toml"),
    )

    def mock_get_runtime_settings():
        return test_runtime

    monkeypatch.setattr("blockchain_exporter.context.get_runtime_settings", mock_get_runtime_settings)

    context = create_default_context()

    assert isinstance(context, ApplicationContext)
    assert context.runtime is test_runtime
    assert context.metrics is not None
    assert context.rpc_factory is default_rpc_factory


def test_create_default_context_uses_global_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that create_default_context uses global metrics."""
    test_metrics = create_metrics()
    set_metrics(test_metrics)

    test_runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[],
        config_path=Path("config.toml"),
    )

    def mock_get_runtime_settings():
        return test_runtime

    monkeypatch.setattr("blockchain_exporter.context.get_runtime_settings", mock_get_runtime_settings)

    context = create_default_context()

    assert context.metrics is test_metrics


def test_get_application_context_creates_default_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that get_application_context creates default context when none exists."""
    test_runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[],
        config_path=Path("config.toml"),
    )

    def mock_get_runtime_settings():
        return test_runtime

    monkeypatch.setattr("blockchain_exporter.context.get_runtime_settings", mock_get_runtime_settings)

    # Ensure no context exists
    reset_application_context()

    context = get_application_context()

    assert isinstance(context, ApplicationContext)
    assert context.runtime is test_runtime


def test_get_application_context_returns_existing_context() -> None:
    """Test that get_application_context returns existing context without recreating."""
    test_metrics = create_metrics()
    test_runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[],
        config_path=Path("config.toml"),
    )
    test_context = ApplicationContext(
        metrics=test_metrics,
        runtime=test_runtime,
        rpc_factory=default_rpc_factory,
    )

    set_application_context(test_context)

    context = get_application_context()

    assert context is test_context


def test_set_application_context_replaces_existing() -> None:
    """Test that set_application_context replaces existing context."""
    test_metrics1 = create_metrics()
    test_metrics2 = create_metrics()
    test_runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[],
        config_path=Path("config.toml"),
    )

    context1 = ApplicationContext(
        metrics=test_metrics1,
        runtime=test_runtime,
        rpc_factory=default_rpc_factory,
    )
    context2 = ApplicationContext(
        metrics=test_metrics2,
        runtime=test_runtime,
        rpc_factory=default_rpc_factory,
    )

    set_application_context(context1)
    assert get_application_context() is context1

    set_application_context(context2)
    assert get_application_context() is context2


def test_reset_application_context_clears_context() -> None:
    """Test that reset_application_context clears the cached context."""
    test_metrics = create_metrics()
    test_runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[],
        config_path=Path("config.toml"),
    )
    test_context = ApplicationContext(
        metrics=test_metrics,
        runtime=test_runtime,
        rpc_factory=default_rpc_factory,
    )

    set_application_context(test_context)
    assert get_application_context() is test_context

    reset_application_context()

    # Next call should create a new context
    with patch("blockchain_exporter.context.get_runtime_settings") as mock_get_runtime:
        mock_get_runtime.return_value = test_runtime
        new_context = get_application_context()
        assert new_context is not test_context


def test_application_context_create_rpc_client(blockchain_config: BlockchainConfig) -> None:
    """Test that ApplicationContext.create_rpc_client uses the factory."""
    mock_rpc = MagicMock()

    def mock_factory(blockchain: BlockchainConfig):
        assert blockchain is blockchain_config
        return mock_rpc

    test_metrics = create_metrics()
    test_runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[blockchain_config],
        config_path=Path("config.toml"),
    )
    context = ApplicationContext(
        metrics=test_metrics,
        runtime=test_runtime,
        rpc_factory=mock_factory,
    )

    rpc_client = context.create_rpc_client(blockchain_config)

    assert rpc_client is mock_rpc


def test_application_context_properties() -> None:
    """Test that ApplicationContext properties return correct values."""
    test_metrics = create_metrics()
    test_settings = get_settings()
    test_runtime = RuntimeSettings(
        app=test_settings,
        blockchains=[],
        config_path=Path("config.toml"),
    )
    context = ApplicationContext(
        metrics=test_metrics,
        runtime=test_runtime,
        rpc_factory=default_rpc_factory,
    )

    assert context.settings is test_settings
    assert context.blockchains == []

