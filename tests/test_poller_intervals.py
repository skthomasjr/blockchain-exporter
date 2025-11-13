from __future__ import annotations

import pytest

from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.poller.intervals import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_RPC_TIMEOUT_SECONDS,
    create_web3_client,
    determine_poll_interval_seconds,
    parse_duration_to_seconds,
)


def make_blockchain_config(poll_interval: str | None) -> BlockchainConfig:
    return BlockchainConfig(
        name="Chain",
        rpc_url="https://rpc.test",
        poll_interval=poll_interval,
        contracts=[],
        accounts=[],
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("15s", 15),
        ("2m", 120),
        ("1h", 3600),
        ("30", 30),
        (" 5 m ", 300),
    ],
)
def test_parse_duration_to_seconds_parses_units(value: str, expected: int) -> None:
    result = parse_duration_to_seconds(value)

    assert result == expected


@pytest.mark.parametrize(
    "value",
    ["", "abc", "5x", "10 d"],
)
def test_parse_duration_to_seconds_returns_none_on_invalid(value: str) -> None:
    result = parse_duration_to_seconds(value)

    assert result is None


def test_determine_poll_interval_seconds_uses_chain_override() -> None:
    blockchain = make_blockchain_config("2m")

    seconds = determine_poll_interval_seconds(blockchain)

    assert seconds == 120


def test_determine_poll_interval_seconds_falls_back_on_invalid() -> None:
    blockchain = make_blockchain_config("not-a-duration")

    seconds = determine_poll_interval_seconds(blockchain)

    assert seconds == DEFAULT_POLL_INTERVAL_SECONDS


def test_determine_poll_interval_seconds_uses_default_when_missing() -> None:
    blockchain = make_blockchain_config(None)

    seconds = determine_poll_interval_seconds(blockchain)

    assert seconds == DEFAULT_POLL_INTERVAL_SECONDS


def test_create_web3_client_sets_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_provider: dict[str, object] = {}

    class DummyProvider:
        def __init__(self, endpoint_uri: str, request_kwargs: dict[str, object]) -> None:
            captured_provider["url"] = endpoint_uri
            captured_provider["request_kwargs"] = request_kwargs

    class DummyWeb3:
        def __init__(self, provider: DummyProvider) -> None:
            self.provider = provider

    monkeypatch.setattr("blockchain_exporter.poller.intervals.HTTPProvider", DummyProvider)
    monkeypatch.setattr("blockchain_exporter.poller.intervals.Web3", DummyWeb3)

    blockchain = make_blockchain_config("30s")

    client = create_web3_client(blockchain)

    assert isinstance(client, DummyWeb3)
    assert captured_provider["url"] == blockchain.rpc_url
    assert captured_provider["request_kwargs"] == {"timeout": DEFAULT_RPC_TIMEOUT_SECONDS}

