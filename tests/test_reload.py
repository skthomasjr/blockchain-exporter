"""Tests for configuration reload functionality."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from blockchain_exporter.config import AccountConfig, BlockchainConfig
from blockchain_exporter.context import ApplicationContext, get_application_context, set_application_context
from blockchain_exporter.exceptions import ConfigError, ValidationError
from blockchain_exporter.metrics import (
    CHAIN_HEALTH_STATUS,
    CHAIN_LABEL_CACHE,
    CHAIN_LAST_SUCCESS,
    blockchain_identity,
    create_metrics,
    get_metrics,
)
from blockchain_exporter.poller.manager import get_poller_manager
from blockchain_exporter.reload import reload_configuration
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
def application_context(blockchain_config: BlockchainConfig, fake_rpc_factory) -> ApplicationContext:
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
    set_application_context(context)
    return context


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_configuration_adds_new_blockchain(
    blockchain_config: BlockchainConfig,
    blockchain_config_2: BlockchainConfig,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_configuration adds new blockchains."""
    # Create initial config file
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"""
[[blockchains]]
name = "{blockchain_config.name}"
rpc_url = "{blockchain_config.rpc_url}"
poll_interval = "{blockchain_config.poll_interval}"

[[blockchains.accounts]]
name = "{blockchain_config.accounts[0].name}"
address = "{blockchain_config.accounts[0].address}"
""",
        encoding="utf-8",
    )

    # Mock config loading to return updated config
    def mock_load_configs(path: Path | None = None) -> list[BlockchainConfig]:
        return [blockchain_config, blockchain_config_2]

    monkeypatch.setattr("blockchain_exporter.reload.load_blockchain_configs", mock_load_configs)
    monkeypatch.setattr("blockchain_exporter.reload.resolve_config_path", lambda _: config_file)

    # Mock PollerManager.reload_tasks
    manager = get_poller_manager()
    reload_tasks_called = False

    async def mock_reload_tasks(
        old_blockchains: Any,
        new_blockchains: Any,
        context: Any,
    ) -> None:
        nonlocal reload_tasks_called
        reload_tasks_called = True
        assert len(old_blockchains) == 1
        assert len(new_blockchains) == 2

    monkeypatch.setattr(manager, "reload_tasks", mock_reload_tasks)

    success, message = await reload_configuration()

    assert success is True
    assert "Added: 1" in message
    assert "Removed: 0" in message
    assert reload_tasks_called

    # Verify context was updated
    new_context = get_application_context()
    assert len(new_context.blockchains) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_configuration_removes_blockchain(
    blockchain_config: BlockchainConfig,
    blockchain_config_2: BlockchainConfig,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_configuration removes blockchains and cleans up metrics."""
    # Set up initial context with two blockchains
    initial_runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[blockchain_config, blockchain_config_2],
        config_path=Path("config.toml"),
    )
    initial_context = ApplicationContext(
        metrics=application_context.metrics,
        runtime=initial_runtime,
        rpc_factory=application_context.rpc_factory,
    )
    set_application_context(initial_context)

    # Add some cached metrics for the blockchain that will be removed
    from blockchain_exporter.metrics import ChainMetricLabelState, update_chain_label_cache

    state = ChainMetricLabelState(chain_id_label="1")
    update_chain_label_cache(blockchain_config_2, state)
    CHAIN_HEALTH_STATUS[(blockchain_config_2.name, "1")] = True
    CHAIN_LAST_SUCCESS[(blockchain_config_2.name, "1")] = 1000.0

    # Mock config loading to return only one blockchain
    def mock_load_configs(path: Path | None = None) -> list[BlockchainConfig]:
        return [blockchain_config]

    monkeypatch.setattr("blockchain_exporter.reload.load_blockchain_configs", mock_load_configs)
    monkeypatch.setattr("blockchain_exporter.reload.resolve_config_path", lambda _: tmp_path / "config.toml")

    # Mock PollerManager.reload_tasks
    manager = get_poller_manager()
    reload_tasks_called = False

    async def mock_reload_tasks(
        old_blockchains: Any,
        new_blockchains: Any,
        context: Any,
    ) -> None:
        nonlocal reload_tasks_called
        reload_tasks_called = True
        assert len(old_blockchains) == 2
        assert len(new_blockchains) == 1

    monkeypatch.setattr(manager, "reload_tasks", mock_reload_tasks)

    success, message = await reload_configuration()

    assert success is True
    assert "Added: 0" in message
    assert "Removed: 1" in message
    assert reload_tasks_called

    # Verify metrics were cleaned up
    assert blockchain_identity(blockchain_config_2) not in CHAIN_LABEL_CACHE
    assert (blockchain_config_2.name, "1") not in CHAIN_HEALTH_STATUS
    assert (blockchain_config_2.name, "1") not in CHAIN_LAST_SUCCESS


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_configuration_no_changes(
    blockchain_config: BlockchainConfig,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_configuration handles no changes gracefully."""
    # Mock config loading to return same blockchain
    def mock_load_configs(path: Path | None = None) -> list[BlockchainConfig]:
        return [blockchain_config]

    monkeypatch.setattr("blockchain_exporter.reload.load_blockchain_configs", mock_load_configs)
    monkeypatch.setattr("blockchain_exporter.reload.resolve_config_path", lambda _: tmp_path / "config.toml")

    # Mock PollerManager.reload_tasks
    manager = get_poller_manager()
    reload_tasks_called = False

    async def mock_reload_tasks(
        old_blockchains: Any,
        new_blockchains: Any,
        context: Any,
    ) -> None:
        nonlocal reload_tasks_called
        reload_tasks_called = True
        assert len(old_blockchains) == 1
        assert len(new_blockchains) == 1

    monkeypatch.setattr(manager, "reload_tasks", mock_reload_tasks)

    success, message = await reload_configuration()

    assert success is True
    assert "Added: 0" in message
    assert "Removed: 0" in message
    assert reload_tasks_called


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_configuration_file_not_found(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_configuration handles FileNotFoundError gracefully."""
    missing_file = tmp_path / "missing.toml"

    def mock_resolve_config_path(settings: Any) -> Path:
        return missing_file

    monkeypatch.setattr("blockchain_exporter.reload.resolve_config_path", mock_resolve_config_path)

    success, message = await reload_configuration()

    assert success is False
    assert "not found" in message.lower()

    # Verify existing context is preserved
    context = get_application_context()
    assert context is not None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_configuration_config_error(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_configuration handles ConfigError gracefully."""
    def mock_load_configs(path: Path | None = None) -> list[BlockchainConfig]:
        raise ConfigError("Invalid config structure", config_section="blockchains")

    monkeypatch.setattr("blockchain_exporter.reload.load_blockchain_configs", mock_load_configs)
    monkeypatch.setattr("blockchain_exporter.reload.resolve_config_path", lambda _: tmp_path / "config.toml")

    success, message = await reload_configuration()

    assert success is False
    assert "Configuration error" in message

    # Verify existing context is preserved
    context = get_application_context()
    assert context is not None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_configuration_validation_error(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_configuration handles ValidationError gracefully."""
    def mock_load_configs(path: Path | None = None) -> list[BlockchainConfig]:
        raise ValidationError(
            "Invalid address format",
            config_section="blockchains[0].accounts[0].address",
            config_key="address",
            value="invalid",
        )

    monkeypatch.setattr("blockchain_exporter.reload.load_blockchain_configs", mock_load_configs)
    monkeypatch.setattr("blockchain_exporter.reload.resolve_config_path", lambda _: tmp_path / "config.toml")

    success, message = await reload_configuration()

    assert success is False
    assert "Configuration error" in message

    # Verify existing context is preserved
    context = get_application_context()
    assert context is not None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_configuration_unexpected_error(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_configuration handles unexpected errors gracefully."""
    def mock_load_configs(path: Path | None = None) -> list[BlockchainConfig]:
        raise RuntimeError("Unexpected error")

    monkeypatch.setattr("blockchain_exporter.reload.load_blockchain_configs", mock_load_configs)
    monkeypatch.setattr("blockchain_exporter.reload.resolve_config_path", lambda _: tmp_path / "config.toml")

    success, message = await reload_configuration()

    assert success is False
    assert "Unexpected error" in message

    # Verify existing context is preserved
    context = get_application_context()
    assert context is not None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_reload_configuration_updates_configured_blockchains_metric(
    blockchain_config: BlockchainConfig,
    blockchain_config_2: BlockchainConfig,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that reload_configuration updates the configured_blockchains metric."""
    def mock_load_configs(path: Path | None = None) -> list[BlockchainConfig]:
        return [blockchain_config, blockchain_config_2]

    monkeypatch.setattr("blockchain_exporter.reload.load_blockchain_configs", mock_load_configs)
    monkeypatch.setattr("blockchain_exporter.reload.resolve_config_path", lambda _: tmp_path / "config.toml")

    manager = get_poller_manager()
    monkeypatch.setattr(manager, "reload_tasks", AsyncMock())

    metrics_before = get_metrics()
    initial_count = metrics_before.exporter.configured_blockchains._value.get()

    success, _message = await reload_configuration()

    assert success is True

    metrics_after = get_metrics()
    final_count = metrics_after.exporter.configured_blockchains._value.get()

    assert final_count == 2.0
    assert final_count != initial_count

