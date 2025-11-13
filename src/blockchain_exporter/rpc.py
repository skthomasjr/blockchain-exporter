"""RPC retry helpers and constants."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Protocol, runtime_checkable

from .config import BlockchainConfig
from .logging import get_logger

LOGGER = get_logger(__name__)

RPC_MAX_RETRIES = 3
RPC_INITIAL_BACKOFF_SECONDS = 0.5
RPC_MAX_BACKOFF_SECONDS = 5.0


@runtime_checkable
class Web3ProviderProtocol(Protocol):
    def is_connected(self) -> bool: ...

    @property
    def eth(self) -> Any: ...


@runtime_checkable
class RpcClientProtocol(Protocol):
    @property
    def web3(self) -> Web3ProviderProtocol: ...

    @property
    def blockchain(self) -> BlockchainConfig: ...

    def get_chain_id(
        self,
        *,
        description: str | None = None,
        max_attempts: int | None = 1,
        extra: dict[str, Any] | None = None,
    ) -> int: ...

    def get_balance(
        self,
        address: str,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> int: ...

    def get_code(
        self,
        address: str,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> bytes: ...

    def get_block(
        self,
        block_identifier: Any,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
        full_transactions: bool = False,
    ) -> Any: ...

    def get_logs(
        self,
        params: dict[str, Any],
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def call_contract_function(
        self,
        call: Callable[[], Any],
        description: str,
        *,
        max_attempts: int | None = 1,
        log_level: int = logging.WARNING,
        include_traceback: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> Any: ...


def execute_with_retries(
    operation: Callable[[], Any],
    description: str,
    blockchain: BlockchainConfig,
    max_attempts: int | None = None,
    *,
    log_level: int = logging.WARNING,
    include_traceback: bool = True,
    context_extra: dict[str, Any] | None = None,
) -> Any:
    """Execute an RPC operation with retries and exponential backoff."""
    last_exception: Exception | None = None

    attempt_limit = max_attempts if max_attempts is not None else RPC_MAX_RETRIES

    for attempt in range(1, attempt_limit + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_exception = exc

            log_kwargs: dict[str, Any] = {}

            if include_traceback:
                log_kwargs["exc_info"] = exc

            if context_extra:
                log_kwargs["extra"] = context_extra

            LOGGER.log(
                log_level,
                "RPC operation '%s' failed for %s (attempt %s/%s).",
                description,
                blockchain.name,
                attempt,
                attempt_limit,
                **log_kwargs,
            )

            if attempt < attempt_limit:
                backoff_seconds = min(
                    RPC_INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                    RPC_MAX_BACKOFF_SECONDS,
                )

                time.sleep(backoff_seconds)

    if last_exception is not None:
        raise last_exception

    raise RuntimeError(f"RPC operation '{description}' failed without raising an exception.")


class RpcClient:
    """Wrapper around Web3 that centralizes retry handling."""

    def __init__(self, web3: Web3ProviderProtocol, blockchain: BlockchainConfig) -> None:
        self._web3 = web3
        self._blockchain = blockchain

    @property
    def web3(self) -> Web3ProviderProtocol:
        return self._web3

    @property
    def blockchain(self) -> BlockchainConfig:
        return self._blockchain

    def get_chain_id(
        self,
        *,
        description: str | None = None,
        max_attempts: int | None = 1,
        extra: dict[str, Any] | None = None,
    ) -> int:
        desc = description or "eth_chainId"
        return execute_with_retries(
            lambda: self._web3.eth.chain_id,
            desc,
            self._blockchain,
            max_attempts=max_attempts,
            log_level=logging.DEBUG,
            include_traceback=False,
            context_extra=extra,
        )

    def get_balance(
        self,
        address: str,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> int:
        desc = description or f"eth_getBalance({address})"
        return execute_with_retries(
            lambda: self._web3.eth.get_balance(address),
            desc,
            self._blockchain,
            max_attempts=max_attempts,
            context_extra=extra,
        )

    def get_code(
        self,
        address: str,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> bytes:
        desc = description or f"eth_getCode({address})"
        return execute_with_retries(
            lambda: self._web3.eth.get_code(address),
            desc,
            self._blockchain,
            max_attempts=max_attempts,
            context_extra=extra,
        )

    def get_block(
        self,
        block_identifier: Any,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
        full_transactions: bool = False,
    ) -> Any:
        desc = description or f"eth_getBlock({block_identifier!r})"
        return execute_with_retries(
            lambda: self._web3.eth.get_block(block_identifier, full_transactions=full_transactions),
            desc,
            self._blockchain,
            max_attempts=max_attempts,
            context_extra=extra,
        )

    def get_logs(
        self,
        params: dict[str, Any],
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        desc = description or "eth_getLogs"
        return execute_with_retries(
            lambda: self._web3.eth.get_logs(params),
            desc,
            self._blockchain,
            max_attempts=max_attempts,
            context_extra=extra,
        )

    def call_contract_function(
        self,
        call: Callable[[], Any],
        description: str,
        *,
        max_attempts: int | None = 1,
        log_level: int = logging.WARNING,
        include_traceback: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> Any:
        return execute_with_retries(
            call,
            description,
            self._blockchain,
            max_attempts=max_attempts,
            log_level=log_level,
            include_traceback=include_traceback,
            context_extra=extra,
        )


__all__ = [
    "RpcClient",
    "RpcClientProtocol",
    "Web3ProviderProtocol",
    "execute_with_retries",
    "RPC_INITIAL_BACKOFF_SECONDS",
    "RPC_MAX_BACKOFF_SECONDS",
    "RPC_MAX_RETRIES",
]

