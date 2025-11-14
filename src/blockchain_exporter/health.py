"""Health reporting and metrics formatting helpers."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Tuple

from fastapi import status

from .metrics import CHAIN_HEALTH_STATUS, CHAIN_LAST_SUCCESS, CONFIGURED_BLOCKCHAINS
from .settings import get_settings

SETTINGS = get_settings()
READINESS_STALE_THRESHOLD_SECONDS = SETTINGS.health.readiness_stale_threshold_seconds


def generate_health_report(
    include_details: bool = False,
) -> Tuple[str, int, List[Dict[str, str]]]:
    if not CONFIGURED_BLOCKCHAINS:
        return (
            "ok",
            status.HTTP_200_OK,
            [],
        )

    if not CHAIN_HEALTH_STATUS:
        return (
            "initializing",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            [],
        )

    any_success = any(CHAIN_HEALTH_STATUS.values())
    all_success = all(CHAIN_HEALTH_STATUS.values())

    if all_success:
        overall_status = "ok"
        status_code = status.HTTP_200_OK
    elif any_success:
        overall_status = "degraded"
        status_code = status.HTTP_200_OK
    else:
        overall_status = "unhealthy"
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    chain_details: List[Dict[str, str]] = []

    for (blockchain_name, chain_id_label), healthy in sorted(
        CHAIN_HEALTH_STATUS.items(),
        key=lambda entry: entry[0],
    ):
        status_value = "ok" if healthy else "unhealthy"

        chain_details.append(
            _build_health_entry(
                blockchain=blockchain_name,
                chain_id=chain_id_label,
                status_value=status_value,
                include_details=include_details,
            )
        )

    return overall_status, status_code, chain_details


def _build_health_entry(
    *,
    blockchain: str,
    chain_id: str,
    status_value: str,
    include_details: bool,
) -> Dict[str, str]:
    """Build a health entry dictionary for a blockchain.

    Args:
        blockchain: Blockchain name.
        chain_id: Chain ID label.
        status_value: Status string ("ok" or "unhealthy").
        include_details: If True, include last_success_timestamp in the entry.

    Returns:
        Dictionary containing health information for the blockchain.
    """
    entry: Dict[str, str] = {
        "blockchain": blockchain,
        "chain_id": chain_id,
        "status": status_value,
    }

    if include_details:
        last_success = CHAIN_LAST_SUCCESS.get((blockchain, chain_id))

        if last_success is not None:
            entry["last_success_timestamp"] = datetime.fromtimestamp(
                last_success,
                tz=timezone.utc,
            ).isoformat()

    return entry


def generate_readiness_report() -> Tuple[bool, List[Dict[str, str]]]:
    if not CONFIGURED_BLOCKCHAINS:
        return True, []

    if not CHAIN_HEALTH_STATUS:
        return False, []

    threshold = time.time() - READINESS_STALE_THRESHOLD_SECONDS

    any_ready = False
    chain_entries: List[Dict[str, str]] = []

    for (blockchain_name, chain_id_label), healthy in sorted(
        CHAIN_HEALTH_STATUS.items(),
        key=lambda entry: entry[0],
    ):
        last_success = CHAIN_LAST_SUCCESS.get((blockchain_name, chain_id_label))

        is_recent = last_success is not None and last_success >= threshold
        ready = healthy and is_recent

        if ready:
            any_ready = True

        entry: Dict[str, str] = {
            "blockchain": blockchain_name,
            "chain_id": chain_id_label,
            "status": "ready" if ready else "not_ready",
        }

        if last_success is not None:
            entry["last_success_timestamp"] = datetime.fromtimestamp(
                last_success,
                tz=timezone.utc,
            ).isoformat()

        chain_entries.append(entry)

    return any_ready, chain_entries


def format_metrics_payload(payload: bytes) -> bytes:
    text = payload.decode()

    lines = []

    for line in text.splitlines():
        if not line:
            lines.append(line)

            continue

        if line.startswith("#"):
            if line.startswith("# TYPE blockchain_chain_id"):
                continue

            lines.append(line)

            continue

        parts = line.rsplit(" ", 1)

        if len(parts) != 2:
            lines.append(line)

            continue

        metric, value = parts

        if "e" in value.lower():
            try:
                decimal_value = Decimal(value)

                value = format(decimal_value, "f")
            except Exception:  # noqa: BLE001
                pass

        lines.append(f"{metric} {value}")

    return "\n".join(lines).encode()


__all__ = [
    "format_metrics_payload",
    "generate_health_report",
    "generate_readiness_report",
    "READINESS_STALE_THRESHOLD_SECONDS",
]

