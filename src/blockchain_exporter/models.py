"""Core data models used across the exporter."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from web3 import Web3

from .config import AccountConfig, BlockchainConfig, ContractAccountConfig, ContractConfig
from .metrics import ChainMetricLabelState, MetricsStoreProtocol
from .rpc import RpcClientProtocol


@dataclass(slots=True)
class AccountLabels:
    """Identifier for an account within a blockchain and chain ID context."""

    blockchain: str
    chain_id: str
    account_name: str
    account_address: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.blockchain, self.chain_id, self.account_name, self.account_address)

    def with_contract_flag(self, is_contract: bool) -> tuple[str, str, str, str, str]:
        return (*self.as_tuple(), "1" if is_contract else "0")


@dataclass(slots=True)
class ContractLabels:
    """Identifier for a contract metric series."""

    blockchain: str
    chain_id: str
    contract_name: str
    contract_address: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.blockchain, self.chain_id, self.contract_name, self.contract_address)

    def with_window(self, window_span: int) -> tuple[str, str, str, str, str]:
        return (*self.as_tuple(), str(window_span))


@dataclass(slots=True)
class TransferWindow:
    start_block: int
    end_block: int
    span: int

    def __iter__(self) -> Iterable[int]:
        yield self.start_block
        yield self.end_block
        yield self.span


@dataclass(slots=True)
class AccountSnapshot:
    labels: AccountLabels
    balance_wei: int
    balance_eth: Decimal
    is_contract: bool


@dataclass(slots=True)
class ChainRuntimeContext:
    """Represents runtime state required while polling a blockchain."""

    config: BlockchainConfig
    chain_id_label: str
    rpc: RpcClientProtocol
    metrics: MetricsStoreProtocol
    chain_state: ChainMetricLabelState

    @property
    def web3(self) -> Web3:
        return self.rpc.web3

    def account_labels(self, account: AccountConfig | ContractAccountConfig) -> AccountLabels:
        return AccountLabels(
            blockchain=self.config.name,
            chain_id=self.chain_id_label,
            account_name=account.name,
            account_address=account.address,
        )

    def contract_labels(self, contract: ContractConfig) -> ContractLabels:
        return ContractLabels(
            blockchain=self.config.name,
            chain_id=self.chain_id_label,
            contract_name=contract.name,
            contract_address=contract.address,
        )


__all__ = [
    "AccountLabels",
    "ContractLabels",
    "TransferWindow",
    "AccountSnapshot",
    "ChainRuntimeContext",
]
