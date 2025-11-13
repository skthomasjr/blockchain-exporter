from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from web3 import Web3
from web3.exceptions import Web3RPCError

from blockchain_exporter.collectors import (
    LOG_MAX_CHUNK_SIZE,
    _collect_contract_total_supply,
    _collect_contract_transfer_count,
    _contract_decimals_label,
    _is_response_too_big_error,
    _record_contract_account_token_balance,
    _resolve_transfer_lookup_window,
    clear_eth_metrics_for_account,
    clear_token_metrics_for_account,
    record_additional_contract_accounts,
    record_contract_balances,
)
from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.metrics import ChainMetricLabelState, create_metrics
from blockchain_exporter.models import ChainRuntimeContext, TransferWindow
from blockchain_exporter.rpc import RPC_MAX_RETRIES


class FakeRpc:
    def __init__(self) -> None:
        self.get_balance_calls: list[str] = []
        self.get_logs_calls: list[tuple[int, int]] = []
        self.success_calls: list[tuple[int, int]] = []
        self.logs_plan: dict[tuple[int, int], int] = {}
        self.error_ranges: set[tuple[int, int]] = set()

    web3 = SimpleNamespace()

    def get_balance(self, address: str, **_kwargs) -> int:
        self.get_balance_calls.append(address)
        return 5 * 10**18

    def get_code(self, address: str, **_kwargs) -> bytes:
        return b""

    def call_contract_function(self, call, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return call()

    def get_logs(self, params: dict[str, int], **_kwargs) -> list[dict[str, int]]:
        start = params["fromBlock"]
        end = params["toBlock"]
        key = (start, end)
        self.get_logs_calls.append(key)

        if key in self.error_ranges:
            self.error_ranges.remove(key)
            raise Web3RPCError({"message": "Response is too big"})

        count = self.logs_plan.get(key, 0)
        self.success_calls.append(key)
        return [{}] * count


class FakeFunc:
    def __init__(self, value: int) -> None:
        self._value = value

    def call(self) -> int:
        return self._value


class FakeContractFunctions:
    def __init__(self, balance: int, decimals: int) -> None:
        self._balance = balance
        self._decimals = decimals

    def balanceOf(self, _address: str) -> FakeFunc:
        return FakeFunc(self._balance)

    def decimals(self) -> FakeFunc:
        return FakeFunc(self._decimals)


class FakeContract:
    def __init__(self, balance: int, decimals: int) -> None:
        self.functions = FakeContractFunctions(balance, decimals)


class RpcWithContract(FakeRpc):
    def __init__(self, balance: int, decimals: int, *, fail_decimals: bool = False) -> None:
        super().__init__()
        self._balance = balance
        self._decimals = decimals
        self._fail_decimals = fail_decimals
        self.web3 = SimpleNamespace(
            eth=SimpleNamespace(contract=lambda *_args, **_kwargs: FakeContract(balance, decimals)),
        )

    def call_contract_function(self, func, description: str, **_kwargs):  # type: ignore[no-untyped-def]
        if self._fail_decimals and description.endswith("decimals()"):
            raise RuntimeError("decimals unavailable")
        return func()


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval="1m",
        contracts=[
            ContractConfig(
                name="Sample Token",
                address="0x0000000000000000000000000000000000000002",
                decimals=None,
                accounts=[],
                transfer_lookback_blocks=LOG_MAX_CHUNK_SIZE + 100,
            )
        ],
        accounts=[
            AccountConfig(
                name="Treasury",
                address="0x0000000000000000000000000000000000000001",
            )
        ],
    )


def build_runtime(blockchain_config: BlockchainConfig, rpc: FakeRpc):
    metrics = create_metrics()

    chain_state = ChainMetricLabelState(chain_id_label="1")

    return ChainRuntimeContext(
        config=blockchain_config,
        chain_id_label="1",
        rpc=rpc,
        metrics=metrics,
        chain_state=chain_state,
    )


def test_record_contract_balances_sets_metrics(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    rpc = FakeRpc()
    runtime = build_runtime(blockchain_config, rpc)

    monkeypatch.setattr(
        "blockchain_exporter.collectors._collect_contract_total_supply",
        lambda *_args, **_kwargs: Decimal(42),
    )
    monkeypatch.setattr(
        "blockchain_exporter.collectors._collect_contract_transfer_count",
        lambda *_args, **_kwargs: 7,
    )

    record_contract_balances(runtime, latest_block_number=10)

    labels = {
        "blockchain": "Test Chain",
        "chain_id": "1",
        "contract_name": "Sample Token",
        "contract_address": "0x0000000000000000000000000000000000000002",
    }

    transfer_labels = dict(labels, window_blocks=str(LOG_MAX_CHUNK_SIZE + 100))

    registry = runtime.metrics.registry

    assert registry.get_sample_value("blockchain_contract_balance_eth", labels) == 5.0
    assert registry.get_sample_value("blockchain_contract_token_total_supply", labels) == 42.0
    assert registry.get_sample_value("blockchain_contract_transfer_count_window", transfer_labels) == 7.0


def test_record_contract_balances_on_failure_sets_zero(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    rpc = FakeRpc()
    runtime = build_runtime(blockchain_config, rpc)

    monkeypatch.setattr(
        "blockchain_exporter.collectors._collect_contract_total_supply",
        lambda *_args, **_kwargs: Decimal(0),
    )
    monkeypatch.setattr(
        "blockchain_exporter.collectors._collect_contract_transfer_count",
        lambda *_args, **_kwargs: 0,
    )

    def failing_balance(_address: str, **_kwargs) -> int:
        raise RuntimeError("rpc failure")

    rpc.get_balance = failing_balance  # type: ignore[assignment]

    record_contract_balances(runtime, latest_block_number=10)

    labels = {
        "blockchain": "Test Chain",
        "chain_id": "1",
        "contract_name": "Sample Token",
        "contract_address": "0x0000000000000000000000000000000000000002",
    }

    registry = runtime.metrics.registry

    assert registry.get_sample_value("blockchain_contract_balance_eth", labels) == 0.0


def test_record_contract_balances_sets_transfer_count_to_zero_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    blockchain_config: BlockchainConfig,
) -> None:
    rpc = FakeRpc()

    runtime = build_runtime(blockchain_config, rpc)

    monkeypatch.setattr(
        "blockchain_exporter.collectors._collect_contract_total_supply",
        lambda *_args, **_kwargs: Decimal(11),
    )

    monkeypatch.setattr(
        "blockchain_exporter.collectors._collect_contract_transfer_count",
        lambda *_args, **_kwargs: None,
    )

    record_contract_balances(runtime, latest_block_number=15)

    labels = {
        "blockchain": "Test Chain",
        "chain_id": "1",
        "contract_name": "Sample Token",
        "contract_address": "0x0000000000000000000000000000000000000002",
    }

    transfer_labels = dict(labels, window_blocks=str(LOG_MAX_CHUNK_SIZE + 100))

    registry = runtime.metrics.registry

    assert registry.get_sample_value("blockchain_contract_transfer_count_window", transfer_labels) == 0.0


def test_collect_contract_transfer_count_chunks_and_retries(blockchain_config: BlockchainConfig) -> None:
    rpc = FakeRpc()
    rpc.logs_plan = {
        (0, LOG_MAX_CHUNK_SIZE): 1,
        (LOG_MAX_CHUNK_SIZE + 1, LOG_MAX_CHUNK_SIZE + 100): 2,
        (0, LOG_MAX_CHUNK_SIZE // 2): 3,
        (LOG_MAX_CHUNK_SIZE // 2 + 1, LOG_MAX_CHUNK_SIZE): 4,
    }
    rpc.error_ranges = {(0, LOG_MAX_CHUNK_SIZE)}

    runtime = SimpleNamespace(config=blockchain_config, chain_id_label="1", rpc=rpc)

    contract = blockchain_config.contracts[0]
    labels = SimpleNamespace()
    window = TransferWindow(0, contract.transfer_lookback_blocks + 0, contract.transfer_lookback_blocks)

    total = _collect_contract_transfer_count(runtime, contract, contract.address, labels, window)

    expected_total = sum(rpc.logs_plan.get(call, 0) for call in rpc.success_calls)
    assert total == expected_total
    assert (0, LOG_MAX_CHUNK_SIZE) in rpc.get_logs_calls


def test_helpers() -> None:
    contract = ContractConfig(
        name="Token",
        address="0x1",
        decimals=6,
        accounts=[],
        transfer_lookback_blocks=None,
    )

    window = _resolve_transfer_lookup_window(contract, latest_block_number=100)
    assert window.start_block == max(0, 100 - 5000)
    assert window.span == 5000

    assert _contract_decimals_label(contract) == "6"
    assert _contract_decimals_label(contract, decimals_override=8) == "8"

    error = Web3RPCError({"message": "Response is too big"})
    assert _is_response_too_big_error(error) is True
    assert _is_response_too_big_error(ValueError("nope")) is False


def test_clear_metric_helpers(blockchain_config: BlockchainConfig) -> None:
    rpc = FakeRpc()
    runtime = build_runtime(blockchain_config, rpc)

    account = runtime.config.accounts[0]
    account_labels = runtime.account_labels(account)

    metrics = runtime.metrics.account

    token_labels = (
        runtime.config.name,
        runtime.chain_id_label,
        runtime.config.contracts[0].name,
        runtime.config.contracts[0].address,
        _contract_decimals_label(runtime.config.contracts[0]),
        account_labels.account_name,
        account_labels.account_address,
        "0",
    )

    metrics.token_balance.labels(*token_labels).set(1)
    metrics.token_balance_raw.labels(*token_labels).set(2)
    runtime.chain_state.account_token_labels.add(token_labels)

    clear_token_metrics_for_account(runtime, account_labels, is_contract=False)

    assert metrics.token_balance._metrics == {}
    assert token_labels not in runtime.chain_state.account_token_labels

    metrics.balance_eth.labels(*(account_labels.as_tuple() + ("0",))).set(1)
    metrics.balance_wei.labels(*(account_labels.as_tuple() + ("0",))).set(1)

    clear_eth_metrics_for_account(runtime, account_labels)

    assert metrics.balance_eth._metrics == {}


def test_record_contract_account_token_balance_updates_metrics(blockchain_config: BlockchainConfig) -> None:
    rpc = RpcWithContract(balance=200, decimals=2)
    runtime = build_runtime(blockchain_config, rpc)

    contract = blockchain_config.contracts[0]
    account_labels = runtime.account_labels(blockchain_config.accounts[0])
    checksum_account = Web3.to_checksum_address(account_labels.account_address)

    _record_contract_account_token_balance(runtime, contract, checksum_account, account_labels, is_contract=True)

    labels = (
        runtime.config.name,
        runtime.chain_id_label,
        contract.name,
        contract.address,
        _contract_decimals_label(contract, 2),
        account_labels.account_name,
        account_labels.account_address,
        "1",
    )

    raw_metric = runtime.metrics.account.token_balance_raw.labels(*labels)
    balance_metric = runtime.metrics.account.token_balance.labels(*labels)

    assert raw_metric._value.get() == 200.0
    assert balance_metric._value.get() == 2.0


def test_record_contract_account_token_balance_handles_failures(blockchain_config: BlockchainConfig) -> None:
    rpc = RpcWithContract(balance=0, decimals=0, fail_decimals=True)
    runtime = build_runtime(blockchain_config, rpc)

    contract = blockchain_config.contracts[0]
    account_labels = runtime.account_labels(blockchain_config.accounts[0])
    checksum_account = Web3.to_checksum_address(account_labels.account_address)

    _record_contract_account_token_balance(runtime, contract, checksum_account, account_labels, is_contract=False)

    labels = (
        runtime.config.name,
        runtime.chain_id_label,
        contract.name,
        contract.address,
        _contract_decimals_label(contract, 0),
        account_labels.account_name,
        account_labels.account_address,
        "0",
    )

    raw_metric = runtime.metrics.account.token_balance_raw.labels(*labels)
    balance_metric = runtime.metrics.account.token_balance.labels(*labels)

    assert raw_metric._value.get() == 0.0
    assert balance_metric._value.get() == 0.0


def test_record_contract_account_token_balance_uses_rpc_retry_configuration(blockchain_config: BlockchainConfig) -> None:
    class RecordingRpc(FakeRpc):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, dict[str, object]]] = []
            self.web3 = SimpleNamespace(
                eth=SimpleNamespace(
                    contract=lambda *_args, **_kwargs: FakeContract(balance=500, decimals=3),
                ),
            )

        def call_contract_function(self, func, description: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append((description, kwargs))
            return func()

    rpc = RecordingRpc()
    runtime = build_runtime(blockchain_config, rpc)

    contract = blockchain_config.contracts[0]
    account_labels = runtime.account_labels(blockchain_config.accounts[0])
    checksum_account = Web3.to_checksum_address(account_labels.account_address)

    _record_contract_account_token_balance(runtime, contract, checksum_account, account_labels, is_contract=True)

    assert len(rpc.calls) == 2

    balance_description, balance_kwargs = rpc.calls[0]
    decimals_description, decimals_kwargs = rpc.calls[1]

    assert ".balanceOf(" in balance_description
    assert balance_kwargs["max_attempts"] == RPC_MAX_RETRIES

    assert decimals_description.endswith(".decimals()")
    assert decimals_kwargs["max_attempts"] == 1
    assert decimals_kwargs["log_level"] == logging.DEBUG
    assert decimals_kwargs["include_traceback"] is False


def test_record_contract_account_token_balance_falls_back_with_existing_decimals(
    blockchain_config: BlockchainConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class InvalidBalanceRpc(RpcWithContract):
        def call_contract_function(self, func, description: str, **kwargs):  # type: ignore[no-untyped-def]
            if "balanceOf" in description:
                return "not-a-number"
            return super().call_contract_function(func, description, **kwargs)

    contract_with_decimals = replace(blockchain_config.contracts[0], decimals=4)
    config_with_decimals = replace(blockchain_config, contracts=[contract_with_decimals])

    rpc = InvalidBalanceRpc(balance=0, decimals=4)
    runtime = build_runtime(config_with_decimals, rpc)

    account_labels = runtime.account_labels(config_with_decimals.accounts[0])
    checksum_account = Web3.to_checksum_address(account_labels.account_address)

    caplog.set_level(logging.DEBUG)

    _record_contract_account_token_balance(
        runtime,
        contract_with_decimals,
        checksum_account,
        account_labels,
        is_contract=False,
    )

    labels = (
        runtime.config.name,
        runtime.chain_id_label,
        contract_with_decimals.name,
        contract_with_decimals.address,
        _contract_decimals_label(contract_with_decimals, 4),
        account_labels.account_name,
        account_labels.account_address,
        "0",
    )

    raw_metric = runtime.metrics.account.token_balance_raw.labels(*labels)
    balance_metric = runtime.metrics.account.token_balance.labels(*labels)

    assert raw_metric._value.get() == 0.0
    assert balance_metric._value.get() == 0.0

    assert any("defaulting to zero (decimals=4)" in record.message for record in caplog.records)


def test_collect_contract_total_supply_handles_errors(blockchain_config: BlockchainConfig) -> None:
    rpc = RpcWithContract(balance=0, decimals=0)
    runtime = build_runtime(blockchain_config, rpc)

    def failing_call(call, description: str, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("no supply")

    runtime.rpc.call_contract_function = failing_call  # type: ignore[assignment]

    result = _collect_contract_total_supply(
        runtime,
        blockchain_config.contracts[0],
        "0x0000000000000000000000000000000000000001",
        SimpleNamespace(),
    )

    assert result == Decimal(0)


def test_record_additional_contract_accounts_processes_new_account(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    rpc = FakeRpc()
    rpc.get_code = lambda *_args, **_kwargs: b"\x01"
    rpc.call_contract_function = lambda func, *_args, **_kwargs: func()

    extra_account = AccountConfig(
        name="Vault",
        address="0x0000000000000000000000000000000000000003",
    )
    contract_with_account = replace(blockchain_config.contracts[0], accounts=[extra_account])
    config_with_account = replace(blockchain_config, contracts=[contract_with_account])

    runtime = build_runtime(config_with_account, rpc)

    cleared: list[str] = []
    recorded: list[str] = []

    def fake_clear(runtime_arg, account_labels):  # type: ignore[no-untyped-def]
        cleared.append(account_labels.account_address)

    def fake_record(runtime_arg, contract, checksum_address, account_labels, is_contract):  # type: ignore[no-untyped-def]
        recorded.append(account_labels.account_address)

    monkeypatch.setattr("blockchain_exporter.collectors.clear_eth_metrics_for_account", fake_clear)
    monkeypatch.setattr("blockchain_exporter.collectors._record_contract_account_token_balance", fake_record)

    processed_accounts: set[str] = set()
    record_additional_contract_accounts(runtime, processed_accounts)

    assert cleared == [extra_account.address]
    assert recorded == [extra_account.address]
    assert extra_account.address.lower() in processed_accounts


def test_record_additional_contract_accounts_handles_rpc_errors(monkeypatch, blockchain_config: BlockchainConfig) -> None:
    rpc = FakeRpc()

    def failing_get_code(*_args, **_kwargs) -> bytes:
        raise RuntimeError("rpc down")

    rpc.get_code = failing_get_code  # type: ignore[assignment]

    extra_account = AccountConfig(
        name="Vault",
        address="0x0000000000000000000000000000000000000003",
    )

    contract_with_account = replace(blockchain_config.contracts[0], accounts=[extra_account])

    config_with_account = replace(blockchain_config, contracts=[contract_with_account])

    runtime = build_runtime(config_with_account, rpc)

    zero_calls: list[tuple[str, bool]] = []

    cleared_accounts: list[str] = []

    def fake_clear(runtime_arg, account_labels):  # type: ignore[no-untyped-def]
        cleared_accounts.append(account_labels.account_address)

    def fake_zero(runtime_arg, contract, account_labels, is_contract, decimals_label):  # type: ignore[no-untyped-def]
        zero_calls.append((account_labels.account_address, is_contract))

    monkeypatch.setattr("blockchain_exporter.collectors.clear_eth_metrics_for_account", fake_clear)
    monkeypatch.setattr("blockchain_exporter.collectors._record_contract_account_token_balance_zero", fake_zero)

    processed_accounts: set[str] = set()

    record_additional_contract_accounts(runtime, processed_accounts)

    assert cleared_accounts == [extra_account.address, extra_account.address]
    assert zero_calls == [(extra_account.address, False)]
    assert extra_account.address.lower() in processed_accounts
