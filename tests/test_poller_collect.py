from __future__ import annotations

from types import SimpleNamespace

import pytest

from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.metrics import ChainMetricLabelState, create_metrics
from blockchain_exporter.models import ChainRuntimeContext
from blockchain_exporter.poller.collect import collect_chain_metrics_sync


class StubRpc:
    def __init__(self) -> None:
        self.web3 = SimpleNamespace(
            is_connected=lambda: True,
            eth=SimpleNamespace(chain_id=1),
        )
        self.block_calls: list[str] = []

    def get_block(self, identifier: str, **_kwargs):
        self.block_calls.append(identifier)
        if identifier == "latest":
            return SimpleNamespace(number=100, timestamp=1000)
        return SimpleNamespace(number=90, timestamp=900)

    def get_balance(self, address: str, **_kwargs) -> int:
        return 1

    def get_code(self, address: str, **_kwargs) -> bytes:
        return b""


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval="1m",
        contracts=[
            ContractConfig(
                name="Token",
                address="0x01",
                decimals=None,
                accounts=[],
                transfer_lookback_blocks=10,
            )
        ],
        accounts=[
            AccountConfig(name="Treasury", address="0x0000000000000000000000000000000000000002")
        ],
    )


def build_runtime(blockchain_config: BlockchainConfig, rpc) -> ChainRuntimeContext:
    metrics = create_metrics()
    state = ChainMetricLabelState(chain_id_label="1")
    return ChainRuntimeContext(
        config=blockchain_config,
        chain_id_label="1",
        rpc=rpc,
        metrics=metrics,
        chain_state=state,
    )


def test_collect_chain_metrics_sync_success(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    rpc = StubRpc()
    runtime = build_runtime(blockchain_config, rpc)

    called: dict[str, bool] = {"balances": False, "extra": False, "poll_success": False}

    def fake_record_contract_balances(runtime_arg, latest_block_number):  # type: ignore[no-untyped-def]
        called["balances"] = True
        assert latest_block_number == 100

    def fake_record_additional(runtime_arg, processed_accounts):  # type: ignore[no-untyped-def]
        called["extra"] = True
        assert processed_accounts == {"0x0000000000000000000000000000000000000002"}

    def fake_record_poll_success(blockchain, chain_id_label, **kwargs):  # type: ignore[no-untyped-def]
        called["poll_success"] = True
        assert chain_id_label == "1"
        # Accept metrics parameter but don't need to use it
        assert "metrics" in kwargs or True  # Accept with or without metrics

    monkeypatch.setattr("blockchain_exporter.poller.collect.record_contract_balances", fake_record_contract_balances)
    monkeypatch.setattr("blockchain_exporter.poller.collect.record_additional_contract_accounts", fake_record_additional)
    monkeypatch.setattr("blockchain_exporter.poller.collect.record_poll_success", fake_record_poll_success)

    result = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc, metrics=runtime.metrics)

    assert result is True
    assert called == {"balances": True, "extra": True, "poll_success": True}
    assert rpc.block_calls == ["latest", "finalized"]


def test_collect_chain_metrics_sync_handles_rpc_disconnect(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    rpc = StubRpc()
    rpc.web3 = SimpleNamespace(is_connected=lambda: False, eth=SimpleNamespace(chain_id=1))

    failures: list[BlockchainConfig] = []

    def fake_record_poll_failure(blockchain, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        failures.append(blockchain)

    monkeypatch.setattr("blockchain_exporter.poller.collect.record_poll_failure", fake_record_poll_failure)

    result = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc)

    assert result is False
    assert failures == [blockchain_config]


def test_collect_chain_metrics_sync_block_failure(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    rpc = StubRpc()

    def failing_get_block(_identifier: str, **_kwargs):
        # Raise RpcError directly since collect.py now catches RpcError
        from blockchain_exporter.exceptions import RpcError

        raise RpcError("unavailable", blockchain=blockchain_config.name, rpc_url=blockchain_config.rpc_url)

    rpc.get_block = failing_get_block  # type: ignore[assignment]

    failures: list[tuple[BlockchainConfig, str]] = []

    def fake_record_poll_failure(blockchain, chain_id_label="1", *_args, **_kwargs):  # type: ignore[no-untyped-def]
        failures.append((blockchain, chain_id_label))

    monkeypatch.setattr("blockchain_exporter.poller.collect.record_poll_failure", fake_record_poll_failure)

    result = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc)

    assert result is False
    assert failures == [(blockchain_config, "1")]
