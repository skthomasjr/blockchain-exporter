import time

from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.health import generate_health_report, generate_readiness_report
from blockchain_exporter.metrics import (
    CHAIN_HEALTH_STATUS,
    CHAIN_LAST_SUCCESS,
    set_configured_blockchains,
)


def _build_blockchain(name: str, rpc_url: str) -> BlockchainConfig:
    return BlockchainConfig(
        name=name,
        rpc_url=rpc_url,
        poll_interval=None,
        contracts=[],
        accounts=[],
    )


def test_generate_health_report_ok_when_no_blockchains() -> None:
    set_configured_blockchains([])

    status, status_code, chains = generate_health_report()

    assert status == "ok"
    assert status_code == 200
    assert chains == []


def test_generate_health_report_initializing_when_configured() -> None:
    set_configured_blockchains([_build_blockchain("Mainnet", "https://mainnet.local")])

    status, status_code, chains = generate_health_report()

    assert status == "initializing"
    assert status_code == 503
    assert chains == []


def test_generate_health_report_degraded() -> None:
    set_configured_blockchains(
        [
            _build_blockchain("Mainnet", "https://mainnet.local"),
            _build_blockchain("Sepolia", "https://sepolia.local"),
        ]
    )

    CHAIN_HEALTH_STATUS[("Mainnet", "1")] = True
    CHAIN_HEALTH_STATUS[("Sepolia", "11155111")] = False

    status, status_code, chains = generate_health_report()

    assert status == "degraded"
    assert status_code == 200
    assert len(chains) == 2


def test_generate_readiness_report_staleness() -> None:
    now = time.time()

    set_configured_blockchains(
        [
            _build_blockchain("Mainnet", "https://mainnet.local"),
            _build_blockchain("Sepolia", "https://sepolia.local"),
        ]
    )

    CHAIN_HEALTH_STATUS[("Mainnet", "1")] = True
    CHAIN_LAST_SUCCESS[("Mainnet", "1")] = now

    CHAIN_HEALTH_STATUS[("Sepolia", "11155111")] = True
    CHAIN_LAST_SUCCESS[("Sepolia", "11155111")] = now - 10_000

    ready, details = generate_readiness_report()

    assert ready is True
    assert any(item["status"] == "not_ready" for item in details)


def test_generate_readiness_report_ready_when_no_blockchains() -> None:
    set_configured_blockchains([])

    ready, details = generate_readiness_report()

    assert ready is True
    assert details == []


def test_generate_readiness_report_not_ready_when_configured_without_status() -> None:
    set_configured_blockchains([_build_blockchain("Mainnet", "https://mainnet.local")])

    ready, details = generate_readiness_report()

    assert ready is False
    assert details == []
