from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from blockchain_exporter.app import create_app
from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import get_metrics, record_poll_success
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import get_settings

app_module = importlib.import_module("blockchain_exporter.app")


async def _fake_collect_blockchain_metrics(
    blockchain: BlockchainConfig,
    *,
    rpc_client: Any | None = None,
    metrics: Any | None = None,
) -> bool:
    record_poll_success(blockchain, "test-chain")

    return True


async def _fake_poll_blockchain(
    blockchain: BlockchainConfig,
    *,
    context: ApplicationContext | None = None,
) -> None:
    await _fake_collect_blockchain_metrics(
        blockchain,
        metrics=context.metrics if context else None,
    )


@pytest.fixture
def mocked_client(monkeypatch) -> tuple[TestClient, BlockchainConfig]:
    metrics = get_metrics()

    settings = get_settings()

    blockchain = BlockchainConfig(
        name="Test Chain",
        rpc_url="https://example.local",
        poll_interval="1m",
        contracts=[
            ContractConfig(
                name="Test Token",
                address="0x0000000000000000000000000000000000000002",
                decimals=None,
                accounts=[],
                transfer_lookback_blocks=None,
            )
        ],
        accounts=[
            AccountConfig(
                name="Treasury",
                address="0x0000000000000000000000000000000000000001",
            )
        ],
    )

    context = ApplicationContext(
        metrics=metrics,
        runtime=RuntimeSettings(
            app=settings,
            blockchains=[blockchain],
            config_path=Path("config.toml"),
        ),
        rpc_factory=lambda _: None,
    )

    monkeypatch.setattr(
        "blockchain_exporter.poller.control.collect_blockchain_metrics",
        _fake_collect_blockchain_metrics,
    )
    monkeypatch.setattr(
        "blockchain_exporter.poller.control.poll_blockchain",
        _fake_poll_blockchain,
    )
    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _fake_poll_blockchain)

    app = create_app(context=context)

    with TestClient(app) as client:
        yield client, blockchain


def test_health_and_metrics_smoke(mocked_client) -> None:
    client, blockchain = mocked_client

    health_response = client.get("/health")
    assert health_response.status_code == 200

    payload = health_response.json()
    assert payload["status"] == "ok"
    assert payload["chains"][0]["blockchain"] == blockchain.name

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert "blockchain_exporter_up 1.0" in metrics_response.text


def test_health_details_includes_last_success(mocked_client) -> None:
    client, blockchain = mocked_client

    response = client.get("/health/details")
    assert response.status_code == 200

    details = response.json()
    assert details["status"] == "ok"

    chain_entry = details["chains"][0]
    assert chain_entry["blockchain"] == blockchain.name
    assert chain_entry["status"] == "ok"
    assert "last_success_timestamp" in chain_entry


def test_metrics_contains_poll_success_labels(mocked_client) -> None:
    client, blockchain = mocked_client

    response = client.get("/metrics")
    assert response.status_code == 200

    expected_fragment = (
        f'blockchain_poll_success{{blockchain="{blockchain.name}",chain_id="test-chain"}} 1.0'
    )

    assert expected_fragment in response.text


def test_metrics_endpoint_always_returns_metrics(mocked_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that /metrics endpoint always returns metrics, even when not ready."""
    client, _blockchain = mocked_client

    # Mock readiness to be False
    monkeypatch.setattr(
        "blockchain_exporter.api.generate_readiness_report",
        lambda: (False, []),
    )

    # /metrics should still return 200 with metrics (including 'up' metric)
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "blockchain_exporter_up 1.0" in response.text
    assert "blockchain_exporter_configured_blockchains" in response.text

    # Readiness should be checked via /health/readyz, not /metrics
    readiness_response = client.get("/health/readyz")
    assert readiness_response.status_code == 503
    assert readiness_response.json()["status"] == "not_ready"


def test_health_livez_endpoint(mocked_client) -> None:
    client, _blockchain = mocked_client

    response = client.get("/health/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_readyz_endpoint_reports_details(mocked_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, blockchain = mocked_client

    readiness_payload = [
        {
            "blockchain": blockchain.name,
            "chain_id": "test-chain",
            "status": "not_ready",
        }
    ]

    monkeypatch.setattr(
        "blockchain_exporter.api.generate_readiness_report",
        lambda: (False, readiness_payload),
    )

    response = client.get("/health/readyz")

    assert response.status_code == 503

    body = response.json()
    assert body["status"] == "not_ready"
    assert body["chains"] == readiness_payload


def test_metrics_endpoint_ready_when_no_blockchains() -> None:
    metrics = get_metrics()
    settings = get_settings()

    context = ApplicationContext(
        metrics=metrics,
        runtime=RuntimeSettings(
            app=settings,
            blockchains=[],
            config_path=Path("config.toml"),
        ),
        rpc_factory=lambda _: None,
    )

    app = create_app(context=context)

    with TestClient(app) as client:
        metrics_response = client.get("/metrics")
        assert metrics_response.status_code == 200
        assert "blockchain_exporter_up 1.0" in metrics_response.text

        readiness_response = client.get("/health/readyz")
        assert readiness_response.status_code == 200
        assert readiness_response.json() == {"status": "ready", "chains": []}
