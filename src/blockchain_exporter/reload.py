"""Configuration reload functionality for dynamic configuration updates."""

from __future__ import annotations

from .config import load_blockchain_configs, resolve_config_path
from .context import ApplicationContext, get_application_context, set_application_context
from .exceptions import ConfigError, ValidationError
from .logging import build_log_extra, get_logger
from .metrics import (
    blockchain_identity,
    clear_cached_metrics,
    set_configured_blockchains,
)
from .poller.manager import get_poller_manager
from .runtime_settings import RuntimeSettings, reset_runtime_settings_cache
from .settings import get_settings

LOGGER = get_logger(__name__)


async def reload_configuration() -> tuple[bool, str]:
    """Reload blockchain configuration from disk and update running pollers.

    This function:
    1. Reloads the configuration file
    2. Compares old vs new blockchains
    3. Cleans up metrics for removed blockchains
    4. Updates the application context
    5. Reloads polling tasks (stops removed, starts new)

    Returns:
        Tuple of (success: bool, message: str) indicating the result of the reload.

    Raises:
        ConfigError: If configuration file cannot be read.
        ValidationError: If configuration is invalid.
    """
    try:
        # Get current context
        old_context = get_application_context()
        old_blockchains = old_context.blockchains.copy()

        # Clear caches to force reload
        reset_runtime_settings_cache()

        # Reload configuration
        settings = get_settings()
        config_path = resolve_config_path(settings)
        new_blockchains = load_blockchain_configs(config_path)

        # Create new runtime settings
        new_runtime = RuntimeSettings(
            app=settings,
            blockchains=new_blockchains,
            config_path=config_path,
        )

        # Create new context with same metrics and RPC factory
        new_context = ApplicationContext(
            metrics=old_context.metrics,
            runtime=new_runtime,
            rpc_factory=old_context.rpc_factory,
        )

        # Compare old vs new to find removed blockchains
        old_identities = {blockchain_identity(bc) for bc in old_blockchains}
        new_identities = {blockchain_identity(bc) for bc in new_blockchains}
        removed_identities = old_identities - new_identities

        # Clean up metrics for removed blockchains
        removed_blockchain_map = {blockchain_identity(bc): bc for bc in old_blockchains}
        for identity in removed_identities:
            blockchain = removed_blockchain_map[identity]
            if clear_cached_metrics(blockchain):
                LOGGER.info(
                    "Cleaned up metrics for removed blockchain %s",
                    blockchain.name,
                    extra=build_log_extra(blockchain=blockchain),
                )

        # Update configured blockchains metric
        set_configured_blockchains(new_blockchains)

        # Update application context
        set_application_context(new_context)

        # Reload polling tasks
        manager = get_poller_manager()
        await manager.reload_tasks(old_blockchains, new_blockchains, new_context)

        added_count = len(new_identities - old_identities)
        removed_count = len(removed_identities)

        message = f"Configuration reloaded successfully. Added: {added_count}, Removed: {removed_count}, Total: {len(new_blockchains)}"

        LOGGER.info(
            "Configuration reloaded successfully",
            extra=build_log_extra(
                additional={
                    "added_count": added_count,
                    "removed_count": removed_count,
                    "total_count": len(new_blockchains),
                }
            ),
        )

        return True, message

    except FileNotFoundError as exc:
        error_msg = f"Configuration file not found: {exc}"
        LOGGER.error(error_msg)
        return False, error_msg

    except (ConfigError, ValidationError) as exc:
        error_msg = f"Configuration error: {exc}"
        LOGGER.error(error_msg)
        return False, error_msg

    except Exception as exc:
        error_msg = f"Unexpected error during reload: {exc}"
        LOGGER.exception(error_msg, exc_info=exc)
        return False, error_msg


__all__ = ["reload_configuration"]

