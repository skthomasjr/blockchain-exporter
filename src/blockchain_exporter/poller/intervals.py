"""Utilities for polling intervals and Web3 client creation."""

from __future__ import annotations

import re

from web3 import HTTPProvider, Web3

from ..config import BlockchainConfig
from ..logging import get_logger
from ..settings import get_settings

LOGGER = get_logger(__name__)
SETTINGS = get_settings()

DEFAULT_POLL_INTERVAL = SETTINGS.poller.default_interval
DEFAULT_RPC_TIMEOUT_SECONDS = SETTINGS.poller.rpc_request_timeout_seconds
POLL_INTERVAL_PATTERN = re.compile(r"^\s*(\d+)\s*([smhSMH]?)\s*$")
MAX_FAILURE_BACKOFF_SECONDS = SETTINGS.poller.max_failure_backoff_seconds


def determine_rpc_timeout_seconds() -> float:
    """Return the configured RPC request timeout in seconds."""
    return DEFAULT_RPC_TIMEOUT_SECONDS


def create_web3_client(blockchain: BlockchainConfig) -> Web3:
    """Create a Web3 client configured for the specified blockchain.

    Args:
        blockchain: Blockchain configuration containing the RPC URL.

    Returns:
        Configured Web3 client instance.
    """
    timeout_seconds = determine_rpc_timeout_seconds()

    provider = HTTPProvider(
        blockchain.rpc_url,
        request_kwargs={"timeout": timeout_seconds},
    )

    return Web3(provider)


def determine_poll_interval_seconds(blockchain: BlockchainConfig) -> int:
    """Determine the poll interval in seconds for a blockchain.

    Uses the blockchain's configured poll_interval, falling back to the default
    if not specified or invalid.

    Args:
        blockchain: Blockchain configuration to determine interval for.

    Returns:
        Poll interval in seconds (always positive).
    """
    raw_value = blockchain.poll_interval or DEFAULT_POLL_INTERVAL

    resolved_seconds = parse_duration_to_seconds(raw_value)

    if resolved_seconds is None or resolved_seconds <= 0:
        LOGGER.warning(
            "Invalid poll_interval '%s' for %s. Falling back to %s.",
            raw_value,
            blockchain.name,
            DEFAULT_POLL_INTERVAL,
        )

        return DEFAULT_POLL_INTERVAL_SECONDS

    return resolved_seconds


def parse_duration_to_seconds(value: str) -> int | None:
    """Parse a duration string (e.g., '5m', '10s', '1h') to seconds.

    Supports formats: 'N', 'Ns', 'Nm', 'Nh' where N is a positive integer.
    Case-insensitive for unit letters.

    Args:
        value: Duration string to parse.

    Returns:
        Duration in seconds, or None if parsing fails.
    """
    match = POLL_INTERVAL_PATTERN.match(value)

    if not match:
        return None

    amount = int(match.group(1))

    unit = match.group(2).lower() or "s"

    unit_multipliers = {"s": 1, "m": 60, "h": 3600}

    multiplier = unit_multipliers.get(unit)

    if multiplier is None:
        return None

    return amount * multiplier


# Parse the default poll interval to seconds, with a fallback of 300 seconds (5 minutes).
DEFAULT_POLL_INTERVAL_SECONDS = (
    parse_duration_to_seconds(DEFAULT_POLL_INTERVAL) if DEFAULT_POLL_INTERVAL else None
) or 300


__all__ = [
    "DEFAULT_POLL_INTERVAL",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_RPC_TIMEOUT_SECONDS",
    "MAX_FAILURE_BACKOFF_SECONDS",
    "create_web3_client",
    "determine_poll_interval_seconds",
    "determine_rpc_timeout_seconds",
    "parse_duration_to_seconds",
]
