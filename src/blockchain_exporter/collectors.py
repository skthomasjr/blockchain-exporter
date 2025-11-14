"""Metric collection helpers for blockchain entities."""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Set

from web3 import Web3
from web3.exceptions import Web3RPCError

from .config import ContractConfig
from .exceptions import RpcError, RpcProtocolError
from .logging import build_log_extra, get_logger, log_duration
from .metrics import (
    record_log_chunk_blocks,
    record_log_chunk_created,
    record_log_chunk_duration,
)
from .models import AccountLabels, ChainRuntimeContext, ContractLabels, TransferWindow
from .rpc import RPC_MAX_RETRIES, GetLogsParams

LOGGER = get_logger(__name__)

DEFAULT_TOKEN_DECIMALS = 0
DEFAULT_TRANSFER_LOOKBACK_BLOCKS = 5000
LOG_SPLIT_MIN_BLOCK_SPAN = 1
LOG_MAX_CHUNK_SIZE = 2000
# Minimum chunk size when adaptive chunking reduces size due to large responses
LOG_MIN_CHUNK_SIZE = 100
# Target response size (in logs) for adaptive chunking - if response exceeds this, reduce chunk size
LOG_TARGET_RESPONSE_SIZE = 5000
# Reduction factor when response is too large (reduce chunk size by this factor)
LOG_CHUNK_REDUCTION_FACTOR = 0.75
# Growth factor when response is small (increase chunk size by this factor, with max cap)
LOG_CHUNK_GROWTH_FACTOR = 1.25
TRANSFER_EVENT_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()

ERC20_ABI = (
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "account", "type": "address"},
        ],
        "outputs": [
            {"name": "", "type": "uint256"},
        ],
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "", "type": "uint8"},
        ],
    },
)


def record_contract_balances(
    runtime: ChainRuntimeContext,
    latest_block_number: int,
) -> None:
    blockchain = runtime.config
    chain_state = runtime.chain_state

    for contract in blockchain.contracts:
        # Skip disabled contracts (defensive check, though they should be filtered during parsing)
        if not contract.enabled:
            continue

        contract_labels = runtime.contract_labels(contract)
        chain_state.contract_balance_labels.add(contract_labels.as_tuple())

        window = _resolve_transfer_lookup_window(contract, latest_block_number)
        transfer_labels = contract_labels.with_window(window.span)
        chain_state.contract_transfer_labels.add(transfer_labels)

        with log_duration(
            LOGGER,
            "collect_contract_balances",
            extra=build_log_extra(
                blockchain=blockchain,
                chain_id_label=runtime.chain_id_label,
                contract=contract,
                additional={
                    "window_start": window.start_block,
                    "window_end": window.end_block,
                },
            ),
        ):
            try:
                checksum_address = Web3.to_checksum_address(contract.address)

                balance_wei = runtime.rpc.get_balance(
                    checksum_address,
                    extra=build_log_extra(
                        blockchain=blockchain,
                        chain_id_label=runtime.chain_id_label,
                        contract=contract,
                    ),
                )

                balance_eth = Web3.from_wei(balance_wei, "ether")

                total_supply = _collect_contract_total_supply(
                    runtime,
                    contract,
                    checksum_address,
                    contract_labels,
                )

                transfer_count = _collect_contract_transfer_count(
                    runtime,
                    contract,
                    checksum_address,
                    contract_labels,
                    window,
                )
            except RpcError as exc:
                LOGGER.warning(
                    "Failed to retrieve balance for contract %s on %s: %s",
                    contract.address,
                    blockchain.name,
                    exc,
                    exc_info=exc,
                    extra=build_log_extra(
                        blockchain=blockchain,
                        chain_id_label=runtime.chain_id_label,
                        contract=contract,
                        additional={
                            "window_start": window.start_block,
                            "window_end": window.end_block,
                            **exc.context,
                        },
                    ),
                )

                metrics = runtime.metrics
                labels_tuple = (*contract_labels.as_tuple(),)
                transfer_labels_tuple = (*transfer_labels,)

                metrics.contract.balance_eth.labels(*labels_tuple).set(0)
                metrics.contract.balance_wei.labels(*labels_tuple).set(0)
                metrics.contract.token_supply.labels(*labels_tuple).set(0)
                metrics.contract.transfer_count.labels(*transfer_labels_tuple).set(0)

                continue

            metrics = runtime.metrics
            labels_tuple = (*contract_labels.as_tuple(),)
            transfer_labels_tuple = (*transfer_labels,)

            metrics.contract.balance_eth.labels(*labels_tuple).set(float(balance_eth))
            metrics.contract.balance_wei.labels(*labels_tuple).set(float(balance_wei))

            metrics.contract.token_supply.labels(*labels_tuple).set(float(total_supply))

            if transfer_count is not None:
                metrics.contract.transfer_count.labels(*transfer_labels_tuple).set(float(transfer_count))
            else:
                metrics.contract.transfer_count.labels(*transfer_labels_tuple).set(0)


def record_additional_contract_accounts(
    runtime: ChainRuntimeContext,
    processed_accounts: Set[str],
) -> None:
    blockchain = runtime.config

    for contract in blockchain.contracts:
        # Skip disabled contracts (defensive check, though they should be filtered during parsing)
        if not contract.enabled:
            continue

        for contract_account in contract.accounts:
            # Skip disabled contract accounts (defensive check, though they should be filtered during parsing)
            if not contract_account.enabled:
                continue

            account_labels = runtime.account_labels(contract_account)
            account_address_lower = account_labels.account_address.lower()

            if account_address_lower in processed_accounts:
                continue

            processed_accounts.add(account_address_lower)

            clear_eth_metrics_for_account(runtime, account_labels)

            try:
                checksum_address = Web3.to_checksum_address(contract_account.address)

                code = runtime.rpc.get_code(
                    checksum_address,
                    extra=build_log_extra(
                        blockchain=blockchain,
                        chain_id_label=runtime.chain_id_label,
                        contract=contract,
                        account_name=contract_account.name,
                        account_address=contract_account.address,
                    ),
                )

                is_contract = bool(code and len(code) > 0)
            except RpcError as exc:
                LOGGER.warning(
                    "Failed to retrieve balance for contract account %s on %s: %s",
                    contract_account.address,
                    blockchain.name,
                    exc,
                    exc_info=exc,
                    extra=build_log_extra(
                        blockchain=blockchain,
                        chain_id_label=runtime.chain_id_label,
                        contract=contract,
                        account_name=contract_account.name,
                        account_address=contract_account.address,
                        additional=exc.context,
                    ),
                )

                _record_contract_account_token_balance_zero(
                    runtime,
                    contract,
                    account_labels,
                    is_contract=False,
                    decimals_label=_contract_decimals_label(contract),
                )

                clear_eth_metrics_for_account(runtime, account_labels)

                continue

            _record_contract_account_token_balance(
                runtime,
                contract,
                checksum_address,
                account_labels,
                is_contract,
            )


def clear_token_metrics_for_account(
    runtime: ChainRuntimeContext,
    account_labels: AccountLabels,
    is_contract: bool,
) -> None:
    chain_state = runtime.chain_state
    contract_flag = "1" if is_contract else "0"

    for contract in runtime.config.contracts:
        token_labels = (
            runtime.config.name,
            runtime.chain_id_label,
            contract.name,
            contract.address,
            _contract_decimals_label(contract),
            account_labels.account_name,
            account_labels.account_address,
            contract_flag,
        )

        try:
            metrics = runtime.metrics
            metrics.account.token_balance.remove(*token_labels)
        except KeyError:
            pass

        try:
            metrics = runtime.metrics
            metrics.account.token_balance_raw.remove(*token_labels)
        except KeyError:
            pass

        chain_state.account_token_labels.discard(token_labels)


def clear_eth_metrics_for_account(
    runtime: ChainRuntimeContext,
    account_labels: AccountLabels,
) -> None:
    for is_contract_flag in ("0", "1"):
        label_tuple = (*account_labels.as_tuple(), is_contract_flag)

        try:
            runtime.metrics.account.balance_eth.remove(*label_tuple)
        except KeyError:
            pass

        try:
            runtime.metrics.account.balance_wei.remove(*label_tuple)
        except KeyError:
            pass


def _record_contract_account_token_balance(
    runtime: ChainRuntimeContext,
    contract: ContractConfig,
    account_checksum: str,
    account_labels: AccountLabels,
    is_contract: bool,
) -> None:
    web3_client = runtime.web3

    try:
        checksum_contract = Web3.to_checksum_address(contract.address)

        contract_instance = web3_client.eth.contract(
            address=checksum_contract,
            abi=ERC20_ABI,
        )

        balance_raw = runtime.rpc.call_contract_function(
            lambda: contract_instance.functions.balanceOf(account_checksum).call(),
            f"{contract.address}.balanceOf({account_checksum})",
            max_attempts=RPC_MAX_RETRIES,
            extra=build_log_extra(
                blockchain=runtime.config,
                chain_id_label=runtime.chain_id_label,
                contract=contract,
                account_name=account_labels.account_name,
                account_address=account_labels.account_address,
            ),
        )

        decimals = contract.decimals

        if decimals is None:
            try:
                decimals = runtime.rpc.call_contract_function(
                    lambda: contract_instance.functions.decimals().call(),
                    f"{contract.address}.decimals()",
                    max_attempts=1,
                    log_level=logging.DEBUG,
                    include_traceback=False,
                    extra=build_log_extra(
                        blockchain=runtime.config,
                        chain_id_label=runtime.chain_id_label,
                        contract=contract,
                    ),
                )
            except RpcError as decimals_exc:
                # RPC errors from contract function calls are wrapped in RpcError
                LOGGER.debug(
                    "Unable to read decimals for token %s on %s; defaulting to %s: %s",
                    contract.name,
                    runtime.config.name,
                    DEFAULT_TOKEN_DECIMALS,
                    decimals_exc,
                    exc_info=decimals_exc,
                    extra=build_log_extra(
                        blockchain=runtime.config,
                        chain_id_label=runtime.chain_id_label,
                        contract=contract,
                        additional=decimals_exc.context,
                    ),
                )

                decimals = DEFAULT_TOKEN_DECIMALS

        decimals_label = _contract_decimals_label(contract, decimals)

        normalized_balance = Decimal(balance_raw) / (Decimal(10) ** decimals)
    except (RpcError, ValueError, TypeError, InvalidOperation) as exc:
        # RPC errors from contract function calls are wrapped in RpcError
        # ValueError/TypeError/InvalidOperation can occur when balance_raw is not a valid number
        decimals_value = locals().get("decimals")
        decimals_fallback = decimals_value if isinstance(decimals_value, int) else DEFAULT_TOKEN_DECIMALS

        # Extract context from RpcError if available, otherwise use empty dict
        exc_context = exc.context if isinstance(exc, RpcError) else {}

        LOGGER.debug(
            "Failed to retrieve token balance for account %s on contract %s (%s); defaulting to zero (decimals=%s): %s",
            account_labels.account_address,
            contract.name,
            runtime.config.name,
            decimals_fallback,
            exc,
            exc_info=exc,
            extra=build_log_extra(
                blockchain=runtime.config,
                chain_id_label=runtime.chain_id_label,
                contract=contract,
                account_name=account_labels.account_name,
                account_address=account_labels.account_address,
                additional=exc_context,
            ),
        )

        _record_contract_account_token_balance_zero(
            runtime,
            contract,
            account_labels,
            is_contract,
            _contract_decimals_label(contract, decimals_fallback),
        )

        return

    token_labels = (
        runtime.config.name,
        runtime.chain_id_label,
        contract.name,
        contract.address,
        decimals_label,
        account_labels.account_name,
        account_labels.account_address,
        "1" if is_contract else "0",
    )

    runtime.chain_state.account_token_labels.add(token_labels)

    metrics = runtime.metrics

    metrics.account.token_balance.labels(*token_labels).set(float(normalized_balance))
    metrics.account.token_balance_raw.labels(*token_labels).set(float(balance_raw))


def _record_contract_account_token_balance_zero(
    runtime: ChainRuntimeContext,
    contract: ContractConfig,
    account_labels: AccountLabels,
    is_contract: bool,
    decimals_label: str,
) -> None:
    token_labels = (
        runtime.config.name,
        runtime.chain_id_label,
        contract.name,
        contract.address,
        decimals_label,
        account_labels.account_name,
        account_labels.account_address,
        "1" if is_contract else "0",
    )

    runtime.chain_state.account_token_labels.add(token_labels)

    metrics = runtime.metrics

    metrics.account.token_balance.labels(*token_labels).set(0)
    metrics.account.token_balance_raw.labels(*token_labels).set(0)


def _collect_contract_total_supply(
    runtime: ChainRuntimeContext,
    contract: ContractConfig,
    contract_address: str,
    contract_labels: ContractLabels,
) -> Decimal:
    contract_proxy = runtime.web3.eth.contract(
        address=contract_address,
        abi=[
            {
                "name": "totalSupply",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"name": "", "type": "uint256"}],
            }
        ],
    )

    try:
        supply_raw = runtime.rpc.call_contract_function(
            lambda: contract_proxy.functions.totalSupply().call(),
            f"{contract_address}.totalSupply()",
            max_attempts=1,
            log_level=logging.DEBUG,
            include_traceback=False,
            extra=build_log_extra(
                blockchain=runtime.config,
                chain_id_label=runtime.chain_id_label,
                contract=contract,
            ),
        )
    except RpcError as exc:
        # RPC errors from contract function calls are wrapped in RpcError
        LOGGER.debug(
            "Unable to retrieve totalSupply for contract %s on %s; defaulting to zero: %s",
            contract_address,
            runtime.config.name,
            exc,
            exc_info=exc,
            extra=build_log_extra(
                blockchain=runtime.config,
                chain_id_label=runtime.chain_id_label,
                contract=contract,
                additional=exc.context,
            ),
        )

        return Decimal(0)

    return Decimal(supply_raw)


def _collect_contract_transfer_count(
    runtime: ChainRuntimeContext,
    contract: ContractConfig,
    contract_address: str,
    contract_labels: ContractLabels,
    window: TransferWindow,
) -> int | None:
    """Collect transfer event count for a contract with adaptive chunking.

    Uses adaptive chunk sizing based on response size:
    - If response exceeds target size, reduces chunk size for subsequent chunks
    - If response is small, may increase chunk size (with max cap) for efficiency
    - Records metrics for chunk creation, blocks queried, and duration
    """
    blockchain = runtime.config

    total_logs = 0
    # Track current chunk size per contract for adaptive sizing
    current_chunk_size = LOG_MAX_CHUNK_SIZE
    ranges: list[tuple[int, int]] = [(window.start_block, window.end_block)]

    while ranges:
        range_start, range_end = ranges.pop()

        if range_start > range_end:
            continue

        block_span = range_end - range_start + 1

        # If range exceeds current chunk size, split it
        if block_span > current_chunk_size:
            chunk_end = range_start + current_chunk_size - 1

            ranges.append((chunk_end + 1, range_end))
            ranges.append((range_start, chunk_end))

            continue

        # Record chunk creation for this query
        record_log_chunk_created(blockchain, contract_address, runtime.chain_id_label)

        chunk_start_time = time.monotonic()

        try:
            log_params: GetLogsParams = {
                "address": contract_address,
                "fromBlock": range_start,
                "toBlock": range_end,
                "topics": [TRANSFER_EVENT_TOPIC],
            }
            logs = runtime.rpc.get_logs(
                log_params,
                description=f"eth_getLogs({contract_address})",
                max_attempts=1,
                extra=build_log_extra(
                    blockchain=blockchain,
                    chain_id_label=runtime.chain_id_label,
                    contract=contract,
                    additional={
                        "from_block": range_start,
                        "to_block": range_end,
                    },
                ),
            )

            chunk_duration = time.monotonic() - chunk_start_time

            # Record chunk metrics
            record_log_chunk_blocks(blockchain, contract_address, block_span, runtime.chain_id_label)
            record_log_chunk_duration(blockchain, contract_address, chunk_duration, runtime.chain_id_label)

            total_logs += len(logs)

            # Adaptive chunk sizing based on response size
            if len(logs) > LOG_TARGET_RESPONSE_SIZE:
                # Response too large - reduce chunk size for future chunks
                new_chunk_size = max(
                    int(current_chunk_size * LOG_CHUNK_REDUCTION_FACTOR),
                    LOG_MIN_CHUNK_SIZE,
                )
                if new_chunk_size < current_chunk_size:
                    current_chunk_size = new_chunk_size
                    LOGGER.debug(
                        "Reducing chunk size to %d blocks for contract %s due to large response (%d logs)",
                        new_chunk_size,
                        contract_address,
                        len(logs),
                        extra=build_log_extra(
                            blockchain=blockchain,
                            chain_id_label=runtime.chain_id_label,
                            contract=contract,
                            additional={
                                "chunk_size": new_chunk_size,
                                "logs_count": len(logs),
                            },
                        ),
                    )
            elif len(logs) < LOG_TARGET_RESPONSE_SIZE // 4 and current_chunk_size < LOG_MAX_CHUNK_SIZE:
                # Response small and we're below max - increase chunk size for future chunks
                new_chunk_size = min(
                    int(current_chunk_size * LOG_CHUNK_GROWTH_FACTOR),
                    LOG_MAX_CHUNK_SIZE,
                )
                if new_chunk_size > current_chunk_size:
                    current_chunk_size = new_chunk_size
                    LOGGER.debug(
                        "Increasing chunk size to %d blocks for contract %s due to small response (%d logs)",
                        new_chunk_size,
                        contract_address,
                        len(logs),
                        extra=build_log_extra(
                            blockchain=blockchain,
                            chain_id_label=runtime.chain_id_label,
                            contract=contract,
                            additional={
                                "chunk_size": new_chunk_size,
                                "logs_count": len(logs),
                            },
                        ),
                    )

        except RpcError as exc:
            chunk_duration = time.monotonic() - chunk_start_time

            # Record chunk metrics even on error
            record_log_chunk_blocks(blockchain, contract_address, block_span, runtime.chain_id_label)
            record_log_chunk_duration(blockchain, contract_address, chunk_duration, runtime.chain_id_label)

            # Check if it's a "response too big" error that can be handled by chunking
            if _is_response_too_big_error(exc) and block_span > LOG_SPLIT_MIN_BLOCK_SPAN:
                # Reduce chunk size and split using new chunk size
                new_chunk_size = max(
                    int(current_chunk_size * LOG_CHUNK_REDUCTION_FACTOR),
                    LOG_MIN_CHUNK_SIZE,
                )
                current_chunk_size = new_chunk_size

                # Split at the new chunk size boundary
                if block_span > new_chunk_size:
                    chunk_end = range_start + new_chunk_size - 1
                    ranges.append((chunk_end + 1, range_end))
                    ranges.append((range_start, chunk_end))
                else:
                    # Range is small enough for new chunk size, split in half as fallback
                    midpoint = range_start + (range_end - range_start) // 2
                    ranges.append((midpoint + 1, range_end))
                    ranges.append((range_start, midpoint))

                LOGGER.debug(
                    "Splitting chunk for contract %s due to 'response too big' error. Reducing chunk size to %d blocks.",
                    contract_address,
                    new_chunk_size,
                    extra=build_log_extra(
                        blockchain=blockchain,
                        chain_id_label=runtime.chain_id_label,
                        contract=contract,
                        additional={
                            "chunk_size": new_chunk_size,
                            "from_block": range_start,
                            "to_block": range_end,
                        },
                    ),
                )

                continue

            LOGGER.debug(
                "Failed to retrieve transfer logs for contract %s between blocks %s and %s: %s",
                contract_address,
                range_start,
                range_end,
                exc,
                exc_info=exc,
                extra=build_log_extra(
                    blockchain=blockchain,
                    chain_id_label=runtime.chain_id_label,
                    contract=contract,
                    additional={
                        "from_block": range_start,
                        "to_block": range_end,
                        **exc.context,
                    },
                ),
            )

            return None

    return total_logs


def _resolve_transfer_lookup_window(
    contract: ContractConfig,
    latest_block_number: int,
) -> TransferWindow:
    window_span = contract.transfer_lookback_blocks or DEFAULT_TRANSFER_LOOKBACK_BLOCKS
    start_block = max(0, latest_block_number - window_span)

    return TransferWindow(start_block=start_block, end_block=latest_block_number, span=window_span)


def _contract_decimals_label(
    contract: ContractConfig,
    decimals_override: int | None = None,
) -> str:
    if decimals_override is not None:
        return str(decimals_override)

    if contract.decimals is not None:
        return str(contract.decimals)

    return str(DEFAULT_TOKEN_DECIMALS)


def _is_response_too_big_error(exception: Exception) -> bool:
    """Check if an exception represents a 'response too big' error.

    Handles both Web3RPCError (original) and RpcProtocolError (wrapped) exceptions.
    """
    # Check if it's a wrapped RpcProtocolError with Web3RPCError context
    if isinstance(exception, RpcProtocolError):
        # Check the error message for "too big" keywords
        error_message = str(exception).lower()
        if "too big" in error_message or "exceeded max limit" in error_message:
            return True
        # Check rpc_error_message if available
        if exception.rpc_error_message:
            message_lower = exception.rpc_error_message.lower()
            if "too big" in message_lower or "exceeded max limit" in message_lower:
                return True

    # Check if it's a Web3RPCError (original, not wrapped)
    if isinstance(exception, Web3RPCError):
        payload = exception.args[0] if exception.args else {}

        if isinstance(payload, dict):
            message = str(payload.get("message", "")).lower()

            if "too big" in message or "exceeded max limit" in message:
                return True

    return False


__all__ = [
    "clear_eth_metrics_for_account",
    "clear_token_metrics_for_account",
    "record_additional_contract_accounts",
    "record_contract_balances",
    "DEFAULT_TRANSFER_LOOKBACK_BLOCKS",
]
