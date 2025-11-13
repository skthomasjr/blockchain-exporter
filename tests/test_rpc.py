from __future__ import annotations

from types import SimpleNamespace

import pytest

from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.rpc import RpcClient, execute_with_retries


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval=None,
        contracts=[],
        accounts=[],
    )


def test_execute_with_retries_eventual_success(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    attempts: list[str] = []

    def flaky_operation() -> str:
        attempts.append("call")

        if len(attempts) < 3:
            raise ValueError("temporary failure")

        return "ok"

    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    result = execute_with_retries(
        flaky_operation,
        "flaky",
        blockchain_config,
        max_attempts=5,
        include_traceback=False,
    )

    assert result == "ok"
    assert len(attempts) == 3


def test_execute_with_retries_raises_last_exception(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    def always_fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        execute_with_retries(
            always_fail,
            "always_fail",
            blockchain_config,
            max_attempts=2,
        )


def test_rpc_client_get_balance(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        captured["blockchain"] = blockchain.name
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    class FakeEth:
        def __init__(self) -> None:
            self.balance_calls: list[str] = []

        def get_balance(self, address: str) -> int:
            self.balance_calls.append(address)
            return 123

    fake_eth = FakeEth()

    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    value = client.get_balance("0xabc")

    assert value == 123
    assert fake_eth.balance_calls == ["0xabc"]
    assert captured == {"description": "eth_getBalance(0xabc)", "blockchain": "Test Chain"}


def test_rpc_client_get_block(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    class FakeEth:
        def get_block(self, identifier: str, *, full_transactions: bool) -> dict[str, object]:
            return {"identifier": identifier, "full": full_transactions}

    fake_web3 = SimpleNamespace(eth=FakeEth())

    client = RpcClient(fake_web3, blockchain_config)

    result = client.get_block("finalized", full_transactions=True)

    assert result == {"identifier": "finalized", "full": True}
    assert captured["description"] == "eth_getBlock('finalized')"
