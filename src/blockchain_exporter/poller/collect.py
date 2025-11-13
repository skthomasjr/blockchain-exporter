"""Synchronous metric collection routines invoked by the poller."""

from __future__ import annotations

import time

from web3 import Web3

from ..collectors import (
    clear_token_metrics_for_account,
    record_additional_contract_accounts,
    record_contract_balances,
)
from ..config import BlockchainConfig
from ..logging import build_log_extra, get_logger, log_duration
from ..metrics import (
    ChainMetricLabelState,
    MetricsStoreProtocol,
    get_cached_chain_id_label,
    get_metrics,
    handle_chain_id_update,
    record_poll_failure,
    record_poll_success,
    update_chain_label_cache,
)
from ..models import ChainRuntimeContext
from ..rpc import RpcClient, RpcClientProtocol
from .intervals import create_web3_client

LOGGER = get_logger(__name__)


def collect_chain_metrics_sync(
    blockchain: BlockchainConfig,
    rpc_client: RpcClientProtocol | None = None,
    metrics: MetricsStoreProtocol | None = None,
) -> bool:
    """Collect and record metrics for a blockchain within the polling thread."""

    try:
        web3_client = rpc_client.web3 if rpc_client is not None else create_web3_client(blockchain)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception(
            "Failed to create Web3 client for %s.",
            blockchain.name,
            exc_info=exc,
            extra=build_log_extra(blockchain=blockchain),
        )

        record_poll_failure(blockchain)

        return False

    if not web3_client.is_connected():
        LOGGER.warning(
            "Unable to connect to RPC endpoint for blockchain %s (%s).",
            blockchain.name,
            blockchain.rpc_url,
            extra=build_log_extra(blockchain=blockchain),
        )

        record_poll_failure(blockchain)

        return False

    chain_id_label = _resolve_chain_id_label(blockchain, web3_client)

    metrics_bundle = metrics or get_metrics()

    runtime = ChainRuntimeContext(
        config=blockchain,
        chain_id_label=chain_id_label,
        rpc=rpc_client or RpcClient(web3_client, blockchain),
        metrics=metrics_bundle,
        chain_state=ChainMetricLabelState(chain_id_label=chain_id_label),
    )

    rpc_client = runtime.rpc

    latest_block_number = _record_chain_health_metrics(runtime)

    if latest_block_number is None:
        record_poll_failure(blockchain, chain_id_label)

        return False

    with log_duration(
        LOGGER,
        "record_contract_balances_completed",
        extra=build_log_extra(blockchain=blockchain, chain_id_label=chain_id_label),
    ):
        record_contract_balances(runtime, latest_block_number)

    processed_accounts: set[str] = set()

    for account in blockchain.accounts:
        account_labels = runtime.account_labels(account)

        processed_accounts.add(account_labels.account_address.lower())

        try:
            checksum_address = Web3.to_checksum_address(account.address)

            balance_wei = rpc_client.get_balance(
                checksum_address,
                extra=build_log_extra(
                    blockchain=blockchain,
                    chain_id_label=chain_id_label,
                    account_name=account.name,
                    account_address=account.address,
                ),
            )

            balance_eth = Web3.from_wei(balance_wei, "ether")

            code = rpc_client.get_code(
                checksum_address,
                extra=build_log_extra(
                    blockchain=blockchain,
                    chain_id_label=chain_id_label,
                    account_name=account.name,
                    account_address=account.address,
                ),
            )

            is_contract = bool(code and len(code) > 0)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Failed to retrieve balance for account %s on %s.",
                account.address,
                blockchain.name,
                exc_info=exc,
                extra=build_log_extra(
                    blockchain=blockchain,
                    chain_id_label=chain_id_label,
                    account_name=account.name,
                    account_address=account.address,
                ),
            )

            failure_labels = account_labels.with_contract_flag(False)

            runtime.chain_state.account_balance_labels.add(failure_labels)

            metrics = runtime.metrics

            metrics.account.balance_eth.labels(*failure_labels).set(0)
            metrics.account.balance_wei.labels(*failure_labels).set(0)

            clear_token_metrics_for_account(runtime, account_labels, is_contract=False)

            continue

        metric_labels = account_labels.with_contract_flag(is_contract)

        runtime.chain_state.account_balance_labels.add(metric_labels)

        metrics = runtime.metrics

        metrics.account.balance_eth.labels(*metric_labels).set(float(balance_eth))
        metrics.account.balance_wei.labels(*metric_labels).set(float(balance_wei))

        clear_token_metrics_for_account(runtime, account_labels, is_contract)

    record_additional_contract_accounts(runtime, processed_accounts)

    update_chain_label_cache(blockchain, runtime.chain_state)
    record_poll_success(blockchain, runtime.chain_state.chain_id_label)
    return True


def _record_chain_health_metrics(runtime: ChainRuntimeContext) -> int | None:
    metric_labels = (runtime.config.name, runtime.chain_id_label)

    try:
        latest_block = runtime.rpc.get_block(
            "latest",
            extra=build_log_extra(
                blockchain=runtime.config,
                chain_id_label=runtime.chain_id_label,
            ),
        )

        latest_block_number = latest_block.number

        latest_block_timestamp = latest_block.timestamp

        runtime.metrics.chain.head_block_number.labels(*metric_labels).set(
            float(latest_block_number)
        )

        runtime.metrics.chain.head_block_timestamp.labels(*metric_labels).set(
            float(latest_block_timestamp)
        )

        time_since_last_block = max(time.time() - latest_block_timestamp, 0)

        runtime.metrics.chain.time_since_last_block.labels(*metric_labels).set(
            float(time_since_last_block)
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Failed to collect latest block metrics for %s.",
            runtime.config.name,
            exc_info=exc,
            extra=build_log_extra(
                blockchain=runtime.config,
                chain_id_label=runtime.chain_id_label,
            ),
        )

        runtime.metrics.chain.head_block_number.labels(*metric_labels).set(0)

        runtime.metrics.chain.head_block_timestamp.labels(*metric_labels).set(0)

        runtime.metrics.chain.time_since_last_block.labels(*metric_labels).set(0)

        return None

    try:
        finalized_block = runtime.rpc.get_block(
            "finalized",
            extra=build_log_extra(
                blockchain=runtime.config,
                chain_id_label=runtime.chain_id_label,
            ),
        )

        finalized_block_number = finalized_block.number

        runtime.metrics.chain.finalized_block_number.labels(*metric_labels).set(
            float(finalized_block_number)
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug(
            "RPC endpoint did not return finalized block for %s.",
            runtime.config.name,
            exc_info=exc,
            extra=build_log_extra(
                blockchain=runtime.config,
                chain_id_label=runtime.chain_id_label,
            ),
        )

        runtime.metrics.chain.finalized_block_number.labels(*metric_labels).set(0)

    return int(latest_block_number)


def _resolve_chain_id_label(blockchain: BlockchainConfig, web3_client: Web3) -> str:
    cached = get_cached_chain_id_label(blockchain)

    if cached:
        return cached

    try:
        resolved_id = web3_client.eth.chain_id

        resolved = str(resolved_id)

        handle_chain_id_update(blockchain, resolved)

        return resolved
    except Exception as exc:  # noqa: BLE001
        cached = get_cached_chain_id_label(blockchain)

        if cached:
            LOGGER.debug(
                "Using cached chain_id '%s' for %s after failed lookup.",
                cached,
                blockchain.name,
                exc_info=exc,
                extra=build_log_extra(
                    blockchain=blockchain,
                    additional={"cached_chain_id": cached},
                ),
            )

            return cached

        LOGGER.warning(
            "Unable to resolve chain_id for %s; using 'unknown'.",
            blockchain.name,
            exc_info=exc,
            extra=build_log_extra(blockchain=blockchain),
        )

        handle_chain_id_update(blockchain, "unknown")

        return "unknown"


__all__ = ["collect_chain_metrics_sync"]
