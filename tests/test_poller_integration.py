from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from blockchain_exporter.collectors import LOG_MAX_CHUNK_SIZE, _collect_contract_transfer_count
from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import create_metrics
from blockchain_exporter.models import TransferWindow
from blockchain_exporter.poller.collect import collect_chain_metrics_sync
from blockchain_exporter.poller.control import poll_blockchain
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import get_settings


class ChunkingRpc:
    def __init__(self) -> None:
        self.web3 = SimpleNamespace(is_connected=lambda: True, eth=SimpleNamespace(chain_id=1))
        self.calls: list[tuple[int, int]] = []
        self.success_calls: list[tuple[int, int]] = []
        self.errors: set[tuple[int, int]] = set()

    def get_block(self, identifier: str, **_kwargs):
        if identifier == "latest":
            return SimpleNamespace(number=5000, timestamp=1000)
        return SimpleNamespace(number=4000, timestamp=900)

    def get_balance(self, *_args, **_kwargs) -> int:
        return 0

    def get_code(self, *_args, **_kwargs) -> bytes:
        return b""

    def get_logs(self, params: dict[str, int], **_kwargs) -> list[dict[str, int]]:
        key = (params["fromBlock"], params["toBlock"])
        self.calls.append(key)

        if key in self.errors:
            self.errors.remove(key)
            # Raise RpcProtocolError to match what RpcClient would wrap Web3RPCError as
            from blockchain_exporter.exceptions import RpcProtocolError

            raise RpcProtocolError(
                "RPC operation 'eth_getLogs' failed: response too big",
                blockchain="Test Chain",
                rpc_url="https://rpc.example",
                rpc_error_code=None,
                rpc_error_message="response too big",
            )

        self.success_calls.append(key)
        return [{}]

    def call_contract_function(self, call, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return call()


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="Integration Chain",
        rpc_url="https://rpc.example",
        poll_interval="1m",
        contracts=[
            ContractConfig(
                name="Token",
                address="0x0000000000000000000000000000000000000001",
                decimals=None,
                accounts=[],
                transfer_lookback_blocks=LOG_MAX_CHUNK_SIZE + 100,
            )
        ],
        accounts=[AccountConfig(name="Treasury", address="0x0000000000000000000000000000000000000002")],
    )


def test_collect_chain_metrics_sync_exercises_transfer_chunking(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    rpc = ChunkingRpc()
    # After fix: chunking creates (0, 1999) instead of (0, 2000), so update error range
    rpc.errors = {(0, LOG_MAX_CHUNK_SIZE - 1)}

    metrics = create_metrics()

    def fake_record_contract_balances(runtime_arg, latest_block_number):  # type: ignore[no-untyped-def]
        _collect_contract_transfer_count(
            runtime_arg,
            blockchain_config.contracts[0],
            blockchain_config.contracts[0].address,
            SimpleNamespace(),
            TransferWindow(0, latest_block_number, latest_block_number),
        )

    monkeypatch.setattr(
        "blockchain_exporter.poller.collect.record_contract_balances",
        fake_record_contract_balances,
    )

    monkeypatch.setattr(
        "blockchain_exporter.poller.collect.record_additional_contract_accounts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("blockchain_exporter.poller.collect.clear_token_metrics_for_account", lambda *_args, **_kwargs: None)

    result = collect_chain_metrics_sync(blockchain_config, rpc_client=rpc, metrics=metrics)

    assert result is True
    # After fix: chunks are created with exactly LOG_MAX_CHUNK_SIZE blocks
    # Window is (0, 5000), so it gets split into:
    # - (0, 1999) - will error and split further
    # - (2000, 3999) - 2000 blocks, succeeds
    # - (4000, 5000) - 1001 blocks, succeeds
    # The error range (0, 1999) gets split into smaller chunks after the error
    expected_success_ranges = {
        (2000, 3999),  # Second chunk of 2000 blocks
        (4000, 5000),  # Remaining chunk
    }
    # Verify that the expected ranges are in the success calls
    success_set = set(rpc.success_calls)
    assert expected_success_ranges.issubset(success_set), f"Expected {expected_success_ranges} to be subset of {success_set}"
    # Verify that chunking occurred (should have multiple calls)
    assert len(rpc.success_calls) >= 2, "Expected multiple chunk calls due to chunking"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_blockchain_failure_backoff(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    metrics = create_metrics()

    settings = get_settings()

    context = ApplicationContext(
        metrics=metrics,
        runtime=RuntimeSettings(
            app=settings,
            blockchains=[blockchain_config],
            config_path=Path("config.toml"),
        ),
        rpc_factory=lambda _chain: SimpleNamespace(web3=None),
    )

    sleep_calls: list[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        raise asyncio.CancelledError

    async def fake_collect(blockchain, *, rpc_client=None, metrics=None):  # type: ignore[no-untyped-def]
        return False

    monkeypatch.setattr("blockchain_exporter.poller.control.collect_blockchain_metrics", fake_collect)
    monkeypatch.setattr("blockchain_exporter.poller.control.determine_poll_interval_seconds", lambda _chain: 5)
    monkeypatch.setattr("blockchain_exporter.poller.control.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await poll_blockchain(blockchain_config, context=context)

    assert pytest.approx(sleep_calls[0], rel=1e-3) == 5
