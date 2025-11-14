"""Async control loop for blockchain polling."""

from __future__ import annotations

import asyncio
import logging
import time

from ..config import BlockchainConfig
from ..context import ApplicationContext, get_application_context
from ..exceptions import RpcError
from ..logging import build_log_extra, get_logger, log_duration
from ..metrics import (
    MetricsStoreProtocol,
    get_cached_chain_id_label,
    record_backoff_duration,
    record_consecutive_failures,
    record_poll_duration,
    record_poll_failure,
)
from ..rpc import RpcClientProtocol
from .collect import collect_chain_metrics_sync
from .intervals import (
    MAX_FAILURE_BACKOFF_SECONDS,
    determine_poll_interval_seconds,
)

LOGGER = get_logger(__name__)


async def poll_blockchain(
    blockchain: BlockchainConfig,
    *,
    context: ApplicationContext | None = None,
) -> None:
    """Continuously collect metrics for a blockchain with exponential backoff on failures.

    This function runs indefinitely until cancelled. It performs metric collection cycles
    at the configured poll interval, with exponential backoff when failures occur.

    Args:
        blockchain: Blockchain configuration to poll.
        context: Optional application context (defaults to global context).
    """

    context_obj = context or get_application_context()

    interval_seconds = determine_poll_interval_seconds(blockchain)
    LOGGER.info(
        "Polling %s every %s seconds.",
        blockchain.name,
        interval_seconds,
        extra=build_log_extra(blockchain=blockchain),
    )

    consecutive_failures = 0

    while True:
        start_time = time.monotonic()
        success = False

        try:
            with log_duration(
                LOGGER,
                "poller_iteration",
                level=logging.INFO,
                extra=build_log_extra(blockchain=blockchain),
            ):
                rpc_client = context_obj.create_rpc_client(blockchain)
                try:
                    success = await collect_blockchain_metrics(
                        blockchain,
                        rpc_client=rpc_client,
                        metrics=context_obj.metrics,
                    )
                finally:
                    # Return Web3 client to connection pool for reuse
                    # Only return if rpc_client was successfully created
                    if rpc_client is not None:
                        try:
                            from .connection_pool import get_connection_pool_manager

                            pool_manager = get_connection_pool_manager()
                            pool_manager.return_client(blockchain, rpc_client.web3)
                        except Exception:  # noqa: BLE001
                            # Ignore errors when returning to pool (e.g., if web3 is None)
                            # This prevents cascading failures during shutdown or test cleanup
                            pass
        except asyncio.CancelledError:
            LOGGER.debug(
                "Polling task for %s cancelled.",
                blockchain.name,
                extra=build_log_extra(blockchain=blockchain),
            )
            raise
        except RpcError as exc:
            # RPC errors are expected and handled gracefully
            LOGGER.warning(
                "RPC error while polling blockchain %s: %s",
                blockchain.name,
                exc,
                exc_info=exc,
                extra=build_log_extra(
                    blockchain=blockchain,
                    additional=exc.context,
                ),
            )
            record_poll_failure(blockchain)
            consecutive_failures += 1
        except Exception as exc:  # noqa: BLE001
            # Keep broad Exception catch for truly unexpected errors (programming errors, etc.)
            LOGGER.exception(
                "Unexpected error while polling blockchain %s.",
                blockchain.name,
                exc_info=exc,
                extra=build_log_extra(blockchain=blockchain),
            )
            record_poll_failure(blockchain)
            consecutive_failures += 1
        else:
            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1

        new_interval = determine_poll_interval_seconds(blockchain)

        if new_interval != interval_seconds:
            LOGGER.info(
                "Updated poll interval for %s to %s seconds.",
                blockchain.name,
                new_interval,
                extra=build_log_extra(blockchain=blockchain),
            )

            interval_seconds = new_interval

        elapsed = time.monotonic() - start_time

        # Record poll duration
        chain_id_label = get_cached_chain_id_label(blockchain)
        record_poll_duration(blockchain, elapsed, chain_id_label=chain_id_label)

        # Record consecutive failures
        record_consecutive_failures(blockchain, consecutive_failures, chain_id_label=chain_id_label)

        if consecutive_failures > 0:
            failure_backoff = min(
                interval_seconds * (2 ** (consecutive_failures - 1)),
                MAX_FAILURE_BACKOFF_SECONDS,
            )
            sleep_duration = max(failure_backoff - elapsed, 0)

            # Record backoff duration (only if we're actually backing off)
            if sleep_duration > 0:
                record_backoff_duration(blockchain, sleep_duration, chain_id_label=chain_id_label)

            LOGGER.debug(
                "Backing off %.2f seconds before next poll for %s after %s consecutive failure(s).",
                sleep_duration if sleep_duration > 0 else 0,
                blockchain.name,
                consecutive_failures,
                extra=build_log_extra(
                    blockchain=blockchain,
                    elapsed=sleep_duration if sleep_duration > 0 else 0,
                    additional={"consecutive_failures": consecutive_failures},
                ),
            )
        else:
            sleep_duration = max(interval_seconds - elapsed, 0)

        if sleep_duration > 0:
            await asyncio.sleep(sleep_duration)


async def collect_blockchain_metrics(
    blockchain: BlockchainConfig,
    *,
    rpc_client: RpcClientProtocol | None = None,
    metrics: MetricsStoreProtocol | None = None,
) -> bool:
    """Execute one metrics collection cycle inside a worker thread.

    Args:
        blockchain: Blockchain configuration to collect metrics for.
        rpc_client: Optional RPC client (defaults to creating one from context).
        metrics: Optional metrics store (defaults to global metrics).

    Returns:
        True if collection succeeded, False otherwise.
    """

    return await asyncio.to_thread(
        collect_chain_metrics_sync,
        blockchain,
        rpc_client,
        metrics,
    )


__all__ = ["collect_blockchain_metrics", "poll_blockchain"]
