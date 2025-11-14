"""RPC retry helpers and constants."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Literal, Protocol, TypedDict, runtime_checkable

from .config import BlockchainConfig
from .exceptions import RpcConnectionError, RpcError, RpcProtocolError, RpcTimeoutError
from .logging import get_logger
from .metrics import record_rpc_call_duration, record_rpc_error

LOGGER = get_logger(__name__)

RPC_MAX_RETRIES = 3
RPC_INITIAL_BACKOFF_SECONDS = 0.5
RPC_MAX_BACKOFF_SECONDS = 5.0

# Type aliases for block identifiers
BlockIdentifier = int | Literal["latest", "pending", "earliest", "finalized", "safe"]


def _extract_operation_type(description: str) -> str:
    """Extract operation type from RPC call description.

    Converts descriptions like "eth_getBalance(...)" to "get_balance",
    "eth_chainId" to "get_chain_id", etc.

    Args:
        description: The RPC call description.

    Returns:
        The normalized operation type.
    """
    desc_lower = description.lower()

    if "chainid" in desc_lower or "chain_id" in desc_lower:
        return "get_chain_id"
    if "getbalance" in desc_lower or "get_balance" in desc_lower:
        return "get_balance"
    if "getcode" in desc_lower or "get_code" in desc_lower:
        return "get_code"
    if "getblock" in desc_lower or "get_block" in desc_lower:
        return "get_block"
    if "getlogs" in desc_lower or "get_logs" in desc_lower:
        return "get_logs"
    if "call" in desc_lower or "function" in desc_lower:
        return "call_contract_function"

    # Fallback: use description as-is, but normalize it
    # Extract operation name from description (e.g., "eth_getBalance(...)" -> "getBalance")
    operation = description.split("(")[0].replace("eth_", "").strip()
    # Convert to snake_case if needed (e.g., "getBalance" -> "get_balance")
    if operation and operation[0].islower() and any(c.isupper() for c in operation):
        # Simple camelCase to snake_case conversion
        operation = re.sub(r"(?<!^)(?=[A-Z])", "_", operation).lower()
    return operation or "unknown"


def _categorize_error(exception: Exception) -> str:
    """Categorize an exception into an error type for metrics.

    Args:
        exception: The exception to categorize.

    Returns:
        The error category: "timeout", "connection_error", "rpc_error", "value_error", or "unknown".
    """
    # Check if it's already one of our custom RPC exceptions
    if isinstance(exception, RpcTimeoutError):
        return "timeout"
    if isinstance(exception, RpcConnectionError):
        return "connection_error"
    if isinstance(exception, RpcProtocolError):
        return "rpc_error"
    if isinstance(exception, RpcError):
        # Generic RPC error - check context for more specific type
        if "timeout" in str(exception).lower():
            return "timeout"
        if "connection" in str(exception).lower():
            return "connection_error"
        return "rpc_error"

    exception_type = type(exception).__name__
    exception_str = str(exception).lower()

    # Check for timeout errors
    if "timeout" in exception_type.lower() or "timeout" in exception_str:
        return "timeout"

    # Check for connection errors
    if "connection" in exception_type.lower() or "connection" in exception_str:
        return "connection_error"

    # Check for OSError/IOError related to network (connection refused, network unreachable, etc.)
    if isinstance(exception, (OSError, ConnectionError)):
        if any(
            keyword in exception_str
            for keyword in [
                "connection refused",
                "network unreachable",
                "name resolution",
                "name or service not known",
                "connection aborted",
                "connection reset",
            ]
        ):
            return "connection_error"

    # Check for RPC errors (Web3RPCError, JSON-RPC errors)
    if "rpc" in exception_type.lower() or "rpc" in exception_str:
        return "rpc_error"

    # Check for web3-specific errors
    try:
        from web3.exceptions import Web3RPCError

        if isinstance(exception, Web3RPCError):
            return "rpc_error"
    except ImportError:
        pass

    # Check for value/format errors
    if isinstance(exception, (ValueError, TypeError, AttributeError, KeyError)):
        return "value_error"

    # Default to unknown
    return "unknown"


def _wrap_rpc_exception(
    exception: Exception,
    blockchain: BlockchainConfig,
    operation: str,
    description: str,
    attempt: int,
    max_attempts: int,
) -> RpcError:
    """Wrap an exception in an appropriate RpcError subclass.

    Args:
        exception: The exception to wrap.
        blockchain: The blockchain configuration.
        operation: The operation type (e.g., "get_balance").
        description: The operation description.
        attempt: The attempt number.
        max_attempts: The maximum number of attempts.

    Returns:
        An RpcError or appropriate subclass wrapping the original exception.
    """
    error_type = _categorize_error(exception)
    error_message = f"RPC operation '{description}' failed: {exception}"

    # Check if it's already an RpcError
    if isinstance(exception, RpcError):
        return exception

    # Create appropriate RPC error subclass based on error type
    if error_type == "timeout":
        return RpcTimeoutError(
            error_message,
            blockchain=blockchain.name,
            rpc_url=blockchain.rpc_url,
            operation=operation,
            attempt=attempt,
            max_attempts=max_attempts,
            context={"original_exception": type(exception).__name__},
        )
    if error_type == "connection_error":
        return RpcConnectionError(
            error_message,
            blockchain=blockchain.name,
            rpc_url=blockchain.rpc_url,
            operation=operation,
            attempt=attempt,
            max_attempts=max_attempts,
            context={"original_exception": type(exception).__name__},
        )
    if error_type == "rpc_error":
        # Try to extract RPC error code and message from Web3RPCError
        rpc_error_code = None
        rpc_error_message = None
        try:
            from web3.exceptions import Web3RPCError

            if isinstance(exception, Web3RPCError) and exception.args:
                error_data = exception.args[0] if exception.args else {}
                if isinstance(error_data, dict):
                    rpc_error_code = error_data.get("code")
                    rpc_error_message = error_data.get("message")
        except ImportError:
            pass

        return RpcProtocolError(
            error_message,
            blockchain=blockchain.name,
            rpc_url=blockchain.rpc_url,
            operation=operation,
            attempt=attempt,
            max_attempts=max_attempts,
            rpc_error_code=rpc_error_code,
            rpc_error_message=rpc_error_message,
            context={"original_exception": type(exception).__name__},
        )

    # Default to generic RpcError
    return RpcError(
        error_message,
        blockchain=blockchain.name,
        rpc_url=blockchain.rpc_url,
        operation=operation,
        attempt=attempt,
        max_attempts=max_attempts,
        context={"original_exception": type(exception).__name__, "error_type": error_type},
    )


class BlockData(Protocol):
    """Block data structure returned by eth_getBlock.

    This Protocol defines the interface for block data used by the exporter.
    web3.py returns objects with attributes matching this protocol.
    """

    number: int
    timestamp: int
    # Additional fields may exist but are not required for the exporter


class LogEntryDict(TypedDict, total=False):
    """Log entry dictionary structure returned by eth_getLogs."""

    address: str
    topics: list[str]
    data: str
    blockNumber: int
    blockHash: str
    transactionHash: str
    transactionIndex: int
    logIndex: int
    removed: bool


class GetLogsParams(TypedDict, total=False):
    """Parameters for eth_getLogs request."""

    fromBlock: int | Literal["latest", "pending", "earliest", "finalized", "safe"]
    toBlock: int | Literal["latest", "pending", "earliest", "finalized", "safe"]
    address: str | list[str]
    topics: list[str | list[str] | None] | None


@runtime_checkable
class Web3EthProtocol(Protocol):
    """Protocol for Web3 eth module."""

    @property
    def chain_id(self) -> int: ...

    def get_balance(self, address: str, block_identifier: BlockIdentifier | None = None) -> int: ...

    def get_code(self, address: str, block_identifier: BlockIdentifier | None = None) -> bytes: ...

    def get_block(
        self,
        block_identifier: BlockIdentifier,
        full_transactions: bool = False,
    ) -> BlockData: ...

    def get_logs(self, filter_params: GetLogsParams) -> list[LogEntryDict]: ...


@runtime_checkable
class Web3ProviderProtocol(Protocol):
    """Protocol for Web3 provider interface."""

    def is_connected(self) -> bool: ...

    @property
    def eth(self) -> Web3EthProtocol: ...


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
        block_identifier: BlockIdentifier,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
        full_transactions: bool = False,
    ) -> BlockData: ...

    def get_logs(
        self,
        params: GetLogsParams,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> list[LogEntryDict]: ...

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
    operation_type: str | None = None,
    chain_id_label: str | None = None,
) -> Any:
    """Execute an RPC operation with retries and exponential backoff.

    Records the duration of successful RPC calls as a Prometheus histogram metric.

    Args:
        operation: The RPC operation to execute.
        description: Human-readable description of the operation.
        blockchain: The blockchain configuration.
        max_attempts: Maximum number of retry attempts. Defaults to RPC_MAX_RETRIES.
        log_level: Log level for retry messages.
        include_traceback: Whether to include traceback in error logs.
        context_extra: Additional context for logging.
        operation_type: The operation type for metrics (e.g., "get_balance", "get_block").
            If None, will be extracted from description.
        chain_id_label: The chain ID label for metrics. If None, will be resolved from cache.

    Returns:
        The result of the operation.

    Raises:
        Exception: The last exception raised if all retry attempts fail.
    """
    last_exception: Exception | None = None

    attempt_limit = max_attempts if max_attempts is not None else RPC_MAX_RETRIES
    op_type = operation_type or _extract_operation_type(description)

    # Measure total duration including retries
    start_time = time.perf_counter()

    for attempt in range(1, attempt_limit + 1):
        try:
            result = operation()
            # Record total duration on successful call (including retries and backoff)
            duration = time.perf_counter() - start_time
            record_rpc_call_duration(
                blockchain=blockchain,
                operation=op_type,
                duration_seconds=duration,
                chain_id_label=chain_id_label,
            )
            return result
        except RpcError as exc:
            # Already an RpcError, use it directly
            last_exception = exc

            # Record error metric
            error_type = _categorize_error(exc)
            record_rpc_error(
                blockchain=blockchain,
                operation=op_type,
                error_type=error_type,
                chain_id_label=chain_id_label,
            )

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
        except Exception as exc:  # noqa: BLE001
            # Wrap external exceptions in RpcError
            wrapped_exception = _wrap_rpc_exception(
                exc,
                blockchain,
                op_type,
                description,
                attempt,
                attempt_limit,
            )
            last_exception = wrapped_exception

            # Record error metric
            error_type = _categorize_error(exc)
            record_rpc_error(
                blockchain=blockchain,
                operation=op_type,
                error_type=error_type,
                chain_id_label=chain_id_label,
            )

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

    def __init__(
        self,
        web3: Web3ProviderProtocol,
        blockchain: BlockchainConfig,
        chain_id_label: str | None = None,
    ) -> None:
        self._web3 = web3
        self._blockchain = blockchain
        self._chain_id_label = chain_id_label

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
            operation_type="get_chain_id",
            chain_id_label=self._chain_id_label,
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
            operation_type="get_balance",
            chain_id_label=self._chain_id_label,
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
            operation_type="get_code",
            chain_id_label=self._chain_id_label,
        )

    def get_block(
        self,
        block_identifier: BlockIdentifier,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
        full_transactions: bool = False,
    ) -> BlockData:
        desc = description or f"eth_getBlock({block_identifier!r})"
        result = execute_with_retries(
            lambda: self._web3.eth.get_block(block_identifier, full_transactions=full_transactions),
            desc,
            self._blockchain,
            max_attempts=max_attempts,
            context_extra=extra,
            operation_type="get_block",
            chain_id_label=self._chain_id_label,
        )
        # web3.py returns objects with attributes matching BlockData protocol
        return result  # type: ignore[return-value]

    def get_logs(
        self,
        params: GetLogsParams,
        *,
        description: str | None = None,
        max_attempts: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> list[LogEntryDict]:
        desc = description or "eth_getLogs"
        result = execute_with_retries(
            lambda: self._web3.eth.get_logs(params),
            desc,
            self._blockchain,
            max_attempts=max_attempts,
            context_extra=extra,
            operation_type="get_logs",
            chain_id_label=self._chain_id_label,
        )
        # web3.py returns a list of dict-like objects matching LogEntryDict structure
        return result  # type: ignore[return-value]

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
            operation_type="call_contract_function",
            chain_id_label=self._chain_id_label,
        )


__all__ = [
    "BlockData",
    "BlockIdentifier",
    "GetLogsParams",
    "LogEntryDict",
    "RpcClient",
    "RpcClientProtocol",
    "Web3EthProtocol",
    "Web3ProviderProtocol",
    "_categorize_error",
    "_wrap_rpc_exception",
    "execute_with_retries",
    "RPC_INITIAL_BACKOFF_SECONDS",
    "RPC_MAX_BACKOFF_SECONDS",
    "RPC_MAX_RETRIES",
]
