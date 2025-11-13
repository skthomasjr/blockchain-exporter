"""Utilities for resolving application settings alongside blockchain configs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import BlockchainConfig, load_blockchain_configs, resolve_config_path
from .settings import AppSettings, get_settings


@dataclass(slots=True)
class RuntimeSettings:
    """Resolved environment settings paired with configured blockchains."""

    app: AppSettings

    blockchains: list[BlockchainConfig]

    config_path: Path


@lru_cache(maxsize=1)
def get_runtime_settings(*, config_path: Path | None = None) -> RuntimeSettings:
    """Load environment settings and blockchain configs as a single bundle."""

    app_settings = get_settings()

    resolved_path = config_path or resolve_config_path(app_settings)

    blockchains = load_blockchain_configs(resolved_path)

    return RuntimeSettings(
        app=app_settings,
        blockchains=blockchains,
        config_path=resolved_path,
    )


def reset_runtime_settings_cache() -> None:
    """Clear the runtime settings cache so fresh configuration is loaded."""

    get_runtime_settings.cache_clear()


__all__ = [
    "RuntimeSettings",
    "get_runtime_settings",
    "reset_runtime_settings_cache",
]

