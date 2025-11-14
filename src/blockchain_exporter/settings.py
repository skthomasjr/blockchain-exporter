"""Application settings and environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _as_int(value: str | None, default: int) -> int:
    """Convert a string value to an integer, returning default on failure.

    Args:
        value: String value to convert, or None.
        default: Default value to return if conversion fails.

    Returns:
        Converted integer value, or default if conversion fails.
    """
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _as_float(value: str | None, default: float) -> float:
    """Convert a string value to a float, returning default on failure.

    Args:
        value: String value to convert, or None.
        default: Default value to return if conversion fails.

    Returns:
        Converted float value, or default if conversion fails.
    """
    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        return default


def _as_bool(value: str | None, default: bool) -> bool:
    """Convert a string value to a boolean, returning default on failure.

    Recognizes truthy values: "1", "true", "yes", "on" (case-insensitive).
    Recognizes falsy values: "0", "false", "no", "off" (case-insensitive).

    Args:
        value: String value to convert, or None.
        default: Default value to return if conversion fails.

    Returns:
        Converted boolean value, or default if conversion fails.
    """
    if value is None:
        return default

    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off"}:
        return False

    return default


@dataclass(slots=True)
class LoggingSettings:
    level: str
    format: str
    color_enabled: bool


@dataclass(slots=True)
class PollerSettings:
    default_interval: str
    max_failure_backoff_seconds: int
    rpc_request_timeout_seconds: float
    warm_poll_enabled: bool
    warm_poll_timeout_seconds: float


@dataclass(slots=True)
class HealthSettings:
    readiness_stale_threshold_seconds: int


@dataclass(slots=True)
class ServerSettings:
    health_port: int
    metrics_port: int


@dataclass(slots=True)
class ConfigSettings:
    config_path_env: str | None
    default_config_filename: str

    def resolve_config_path(self) -> Path:
        if self.config_path_env:
            configured_path = Path(self.config_path_env).expanduser().resolve()

            if configured_path.is_dir():
                return configured_path.joinpath(self.default_config_filename)

            return configured_path

        return Path.cwd().joinpath(self.default_config_filename).resolve()


@dataclass(slots=True)
class AppSettings:
    logging: LoggingSettings
    poller: PollerSettings
    health: HealthSettings
    server: ServerSettings
    config: ConfigSettings


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    logging_settings = LoggingSettings(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format=os.getenv("LOG_FORMAT", "text").lower(),
        color_enabled=_as_bool(os.getenv("LOG_COLOR_ENABLED"), True),
    )

    poller_settings = PollerSettings(
        default_interval=os.getenv("POLL_DEFAULT_INTERVAL", "5m"),
        max_failure_backoff_seconds=_as_int(os.getenv("MAX_FAILURE_BACKOFF_SECONDS"), 900),
        rpc_request_timeout_seconds=_as_float(os.getenv("RPC_REQUEST_TIMEOUT_SECONDS"), 10.0),
        warm_poll_enabled=_as_bool(os.getenv("WARM_POLL_ENABLED"), False),
        warm_poll_timeout_seconds=_as_float(os.getenv("WARM_POLL_TIMEOUT_SECONDS"), 30.0),
    )

    health_settings = HealthSettings(
        readiness_stale_threshold_seconds=_as_int(
            os.getenv("READINESS_STALE_THRESHOLD_SECONDS"),
            300,
        )
    )

    server_settings = ServerSettings(
        health_port=_as_int(os.getenv("HEALTH_PORT"), 8080),
        metrics_port=_as_int(os.getenv("METRICS_PORT"), 9100),
    )

    config_settings = ConfigSettings(
        config_path_env=os.getenv("BLOCKCHAIN_EXPORTER_CONFIG_PATH"),
        default_config_filename="config.toml",
    )

    return AppSettings(
        logging=logging_settings,
        poller=poller_settings,
        health=health_settings,
        server=server_settings,
        config=config_settings,
    )


__all__ = ["AppSettings", "get_settings"]
