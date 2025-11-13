"""Logging helpers for consistent structured context."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from time import monotonic
from typing import Any, Dict, Iterator

from .config import BlockchainConfig, ContractConfig
from .metrics import get_cached_chain_id_label

_DEFAULT_LOG_KEYS = set(logging.makeLogRecord({}).__dict__.keys())
_EXCLUDED_EXTRA_KEYS = {"message", "asctime", "color_message"}
LEVEL_COLORS = {
    "DEBUG": "\033[90m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
}
TIMESTAMP_COLOR = "\033[36m"
RESET = "\033[0m"


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""

    return logging.getLogger(name)


def extract_log_context(record: logging.LogRecord) -> Dict[str, Any]:
    """Return a dictionary of non-default attributes attached via `extra`."""

    context: Dict[str, Any] = {}

    for key, value in record.__dict__.items():
        if key in _DEFAULT_LOG_KEYS or key in _EXCLUDED_EXTRA_KEYS or key.startswith("_"):
            continue

        context[key] = value

    return context


def build_log_extra(
    *,
    blockchain: BlockchainConfig | None = None,
    chain_id_label: str | None = None,
    contract: ContractConfig | None = None,
    account_name: str | None = None,
    account_address: str | None = None,
    elapsed: float | None = None,
    additional: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Construct an `extra` dict for structured logging."""
    extra: Dict[str, Any] = {}

    if blockchain is not None:
        extra["blockchain"] = blockchain.name

        resolved_chain_id = (
            chain_id_label
            or get_cached_chain_id_label(blockchain)
            or "unknown"
        )

        # Only include chain_id in logs when it's known (not "unknown").
        if resolved_chain_id != "unknown":
            extra["chain_id"] = resolved_chain_id

    if contract is not None:
        extra["contract_name"] = contract.name
        extra["contract_address"] = contract.address

    if account_name is not None:
        extra["account_name"] = account_name

    if account_address is not None:
        extra["account_address"] = account_address

    if elapsed is not None:
        extra["elapsed_seconds"] = round(elapsed, 3)

    if additional:
        extra.update(additional)

    return extra


@contextmanager
def log_duration(
    logger: logging.Logger,
    message: str,
    *,
    level: int = logging.DEBUG,
    extra: Dict[str, Any] | None = None,
) -> Iterator[None]:
    """Context manager to log start and elapsed time for an operation."""

    start = monotonic()
    try:
        yield
    finally:
        elapsed = monotonic() - start
        log_extra = dict(extra or {})
        log_extra["elapsed_seconds"] = round(elapsed, 3)
        logger.log(level, message, extra=log_extra)


def resolve_color_message(record: logging.LogRecord, color_message: str | None) -> str | None:
    if not color_message:
        return color_message

    if record.args:
        try:
            return color_message % record.args
        except Exception:  # pragma: no cover - defensive guard
            return color_message

    return color_message


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "color_message"):
            log_record["color_message"] = resolve_color_message(record, record.color_message)

        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info:
            log_record["stack_info"] = record.stack_info

        context = extract_log_context(record)
        if context:
            log_record.update(context)

        return json.dumps(log_record)


class StructuredTextFormatter(logging.Formatter):
    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: str = "%",
        *,
        color_enabled: bool = True,
    ) -> None:
        super().__init__(fmt, datefmt, style)
        self.color_enabled = color_enabled

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        colored_message = getattr(record, "color_message", None)
        colored_message = resolve_color_message(record, colored_message)

        if colored_message and self.color_enabled:
            plain_message = record.getMessage()

            if plain_message in base:
                base = base.replace(plain_message, colored_message, 1)
            else:
                base = f"{base} {colored_message}"

        timestamp = self.formatTime(record, self.datefmt)
        levelname = record.levelname
        logcolor = getattr(record, "levelcolor", "") or LEVEL_COLORS.get(levelname, "")

        if self.color_enabled:
            base = base.replace(
                timestamp,
                f"{TIMESTAMP_COLOR}{timestamp}{RESET}",
                1,
            )

        if self.color_enabled and logcolor:
            base = base.replace(
                levelname,
                f"{logcolor}{levelname}{RESET}",
                1,
            )

        context = extract_log_context(record)

        if not context:
            return base

        context_str = " ".join(f"{key}={context[key]}" for key in sorted(context))
        return f"{base} | {context_str}"


__all__ = [
    "JsonFormatter",
    "StructuredTextFormatter",
    "build_log_extra",
    "extract_log_context",
    "get_logger",
    "log_duration",
    "resolve_color_message",
]

