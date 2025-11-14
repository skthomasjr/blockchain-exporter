"""Tests for reload HTTP endpoint."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from blockchain_exporter.app import create_health_app
from blockchain_exporter.config import AccountConfig, BlockchainConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import create_metrics
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
def app_with_context(blockchain_config: BlockchainConfig, fake_rpc_factory):
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

    app = create_health_app(context=context)
    return app


def test_reload_endpoint_success(app_with_context, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test successful reload via HTTP endpoint."""
    with patch("blockchain_exporter.api.reload_configuration") as mock_reload:
        mock_reload.return_value = (True, "Configuration reloaded successfully. Added: 1, Removed: 0, Total: 2")

        client = TestClient(app_with_context)
        response = client.post("/health/reload")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "Added: 1" in data["message"]
        mock_reload.assert_called_once()


def test_reload_endpoint_error(app_with_context, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error response from reload endpoint."""
    with patch("blockchain_exporter.api.reload_configuration") as mock_reload:
        mock_reload.return_value = (False, "Configuration error: Invalid config")

        client = TestClient(app_with_context)
        response = client.post("/health/reload")

        assert response.status_code == 500
        data = response.json()
        assert data["status"] == "error"
        assert "Configuration error" in data["message"]
        mock_reload.assert_called_once()


def test_reload_endpoint_file_not_found(app_with_context, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reload endpoint with FileNotFoundError."""
    with patch("blockchain_exporter.api.reload_configuration") as mock_reload:
        mock_reload.return_value = (False, "Configuration file not found: /path/to/missing.toml")

        client = TestClient(app_with_context)
        response = client.post("/health/reload")

        assert response.status_code == 500
        data = response.json()
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()

