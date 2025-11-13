"""Async control loop for blockchain polling."""

from __future__ import annotations

import asyncio
import logging
import time

from ..config import BlockchainConfig
from ..context import ApplicationContext, get_application_context
from ..logging import build_log_extra, get_logger, log_duration
from ..metrics import MetricsStoreProtocol, record_poll_failure
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
                success = await collect_blockchain_metrics(
                    blockchain,
                    rpc_client=rpc_client,
                    metrics=context_obj.metrics,
                )
        except asyncio.CancelledError:
            LOGGER.debug(
                "Polling task for %s cancelled.",
                blockchain.name,
                extra=build_log_extra(blockchain=blockchain),
            )
            raise
        except Exception as exc:  # noqa: BLE001
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

        if consecutive_failures > 0:
            failure_backoff = min(
                interval_seconds * (2 ** (consecutive_failures - 1)),
                MAX_FAILURE_BACKOFF_SECONDS,
            )
            sleep_duration = max(failure_backoff - elapsed, 0)

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
