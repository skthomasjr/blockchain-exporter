import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from .api import register_health_routes, register_metrics_routes, register_routes
from .config import BlockchainConfig, resolve_config_path
from .context import (
    ApplicationContext,
    default_rpc_factory,
    get_application_context,
    reset_application_context,
    set_application_context,
)
from .logging import (
    JsonFormatter,
    StructuredTextFormatter,
    build_log_extra,
    get_logger,
)
from .metrics import (
    MetricsStoreProtocol,
    get_metrics,
    set_configured_blockchains,
    set_metrics,
)
from .poller.manager import get_poller_manager
from .runtime_settings import RuntimeSettings
from .settings import AppSettings, get_settings

SETTINGS = get_settings()


def _configure_logging(settings: AppSettings) -> None:
    """Configure logging based on application settings."""
    log_level = settings.logging.level
    log_format = settings.logging.format

    if log_level not in logging._nameToLevel:
        log_level = "INFO"

    if log_format == "json":
        formatter_config = {
            "()": JsonFormatter,
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        }
    else:
        formatter_config = {
            "()": StructuredTextFormatter,
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            "color_enabled": settings.logging.color_enabled,
        }

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"standard": formatter_config},
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                }
            },
            "root": {"level": log_level, "handlers": ["default"]},
            "loggers": {
                "uvicorn": {
                    "handlers": ["default"],
                    "level": log_level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["default"],
                    "level": log_level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": log_level,
                    "propagate": False,
                },
            },
        }
    )


_configure_logging(SETTINGS)
LOGGER = get_logger(__name__)


APP_TITLE = "Blockchain Prometheus Exporter"
APP_DESCRIPTION = "Exposes Prometheus metrics for blockchain integrations."


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown by coordinating metrics and poller tasks.
    
    On startup:
    - Loads blockchain configuration and application context
    - Sets basic metrics (up, configured_blockchains) early for immediate availability
    - Creates background polling tasks for each configured blockchain
    - Prevents duplicate task creation when multiple apps share the same lifespan
    
    On shutdown:
    - Cancels all polling tasks gracefully with a timeout
    - Resets application context and metrics state
    - Only the primary app (that created the tasks) performs cleanup
    """


    try:
        context = get_application_context()
    except FileNotFoundError:
        config_path = resolve_config_path(SETTINGS)

        LOGGER.warning(
            "Configuration file not found at %s; no blockchains will be polled.",
            config_path,
            extra=build_log_extra(additional={"config_path": str(config_path)}),
        )
        context = ApplicationContext(
            metrics=get_metrics(),
            runtime=RuntimeSettings(
                app=SETTINGS,
                blockchains=[],
                config_path=config_path,
            ),
            rpc_factory=default_rpc_factory,
        )
        set_application_context(context)
    except ValueError as exc:
        LOGGER.error("Configuration validation error: %s", exc)
        raise

    blockchains: list[BlockchainConfig] = context.blockchains

    # Set basic metrics early so they're available immediately when the server starts.
    set_configured_blockchains(blockchains)
    context.metrics.exporter.up.set(1)

    # Store context and initialize application state.
    app.state.context = context
    app.state.blockchain_configs = blockchains
    app.state.polling_tasks: list[asyncio.Task] = []

    # Start blockchain polling in background tasks (non-blocking).
    # Use PollerManager to ensure tasks are only created once across multiple apps.
    manager = get_poller_manager()
    polling_tasks = manager.create_tasks(blockchains, context, app)
    app.state.polling_tasks = polling_tasks

    try:
        # Yield to start the server; background polling tasks continue running.
        yield
    finally:
        # Only shut down tasks if this is the app that created them.
        # This prevents both apps from trying to cancel the same tasks.
        manager = get_poller_manager()

        if manager.should_cleanup(app):
            try:
                context.metrics.exporter.up.set(0)
            except Exception:
                # Ignore errors during shutdown to prevent cascading failures.
                pass

            # Shutdown polling tasks using the manager
            try:
                await manager.shutdown_tasks(timeout_seconds=2.0)
            except Exception:
                # Ignore errors during task shutdown to prevent cascading failures.
                pass

            # Clear app state polling tasks after shutdown
            app.state.polling_tasks.clear()

            # Reset manager state after cleanup
            manager.reset()

            if getattr(app.state, "context", None) is not None:
                try:
                    reset_application_context()
                except Exception:
                    # Ignore errors during context reset to prevent cascading failures.
                    pass
                app.state.context = None

            # Clear connection pools on shutdown
            try:
                from .poller.connection_pool import get_connection_pool_manager

                pool_manager = get_connection_pool_manager()
                pool_manager.clear_pool()
            except Exception:
                # Ignore errors during pool cleanup to prevent cascading failures.
                pass


def create_app(
    *,
    metrics: MetricsStoreProtocol | None = None,
    context: ApplicationContext | None = None,
) -> FastAPI:
    """Create a FastAPI instance configured for the blockchain exporter.
    
    Args:
        metrics: Optional metrics store for dependency injection (defaults to global metrics).
        context: Optional application context for dependency injection (defaults to global context).
    
    Returns:
        FastAPI application instance with all routes registered.
    """

    if metrics is not None:
        set_metrics(metrics)
        reset_application_context()

    if context is not None:
        set_application_context(context)

    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        lifespan=_lifespan,
    )

    register_routes(app)

    return app


def create_health_app(
    *,
    metrics: MetricsStoreProtocol | None = None,
    context: ApplicationContext | None = None,
) -> FastAPI:
    """Create a FastAPI instance for health endpoints only (port 8080).
    
    Args:
        metrics: Optional metrics store for dependency injection (defaults to global metrics).
        context: Optional application context for dependency injection (defaults to global context).
    
    Returns:
        FastAPI application instance with health routes only.
    """

    if metrics is not None:
        set_metrics(metrics)
        reset_application_context()

    if context is not None:
        set_application_context(context)

    app = FastAPI(
        title=f"{APP_TITLE} - Health",
        description="Health check endpoints for the blockchain exporter.",
        lifespan=_lifespan,
    )

    register_health_routes(app)

    return app


def create_metrics_app(
    *,
    metrics: MetricsStoreProtocol | None = None,
    context: ApplicationContext | None = None,
) -> FastAPI:
    """Create a FastAPI instance for metrics endpoint only (port 9100).
    
    Note:
        This app does not create polling tasks; it reuses tasks created by the health app
        to avoid duplicate polling.
    
    Args:
        metrics: Optional metrics store for dependency injection (defaults to global metrics).
        context: Optional application context for dependency injection (defaults to global context).
    
    Returns:
        FastAPI application instance with metrics route only.
    """

    if metrics is not None:
        set_metrics(metrics)
        reset_application_context()

    if context is not None:
        set_application_context(context)

    # Use the same lifespan; it will detect that tasks are already created
    # and reuse them instead of creating duplicates.
    app = FastAPI(
        title=f"{APP_TITLE} - Metrics",
        description="Prometheus metrics endpoint for the blockchain exporter.",
        lifespan=_lifespan,
    )

    register_metrics_routes(app)

    return app


app = create_app()

