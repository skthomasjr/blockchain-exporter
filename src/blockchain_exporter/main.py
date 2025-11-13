import asyncio
import signal
import sys

import uvicorn

from .app import create_health_app, create_metrics_app
from .settings import get_settings

SETTINGS = get_settings()


async def run_servers() -> None:
    """Run both health and metrics servers concurrently.

    Creates separate FastAPI applications for health (port 8080) and metrics (port 9100),
    then runs both Uvicorn servers in parallel using asyncio.gather().

    Both servers will shut down gracefully when a termination signal (SIGTERM, SIGINT)
    is received, triggering FastAPI lifespan cleanup and polling task cancellation.
    """
    health_app = create_health_app()
    metrics_app = create_metrics_app()

    config_health = uvicorn.Config(
        health_app,
        host="0.0.0.0",
        port=SETTINGS.server.health_port,
        log_config=None,
    )
    config_metrics = uvicorn.Config(
        metrics_app,
        host="0.0.0.0",
        port=SETTINGS.server.metrics_port,
        log_config=None,
    )

    server_health = uvicorn.Server(config_health)
    server_metrics = uvicorn.Server(config_metrics)

    # Create tasks so we can cancel both servers when a signal is received.
    health_task = asyncio.create_task(server_health.serve())
    metrics_task = asyncio.create_task(server_metrics.serve())

    try:
        await asyncio.gather(health_task, metrics_task)
    except asyncio.CancelledError:
        # Cancel both servers when shutdown is requested.
        health_task.cancel()
        metrics_task.cancel()
        # Wait for both to finish cancellation.
        await asyncio.gather(health_task, metrics_task, return_exceptions=True)
        raise


def run() -> None:
    """Run both health and metrics servers with graceful signal handling.

    Registers signal handlers for SIGTERM (Kubernetes pod termination) and SIGINT (Ctrl-C)
    to ensure graceful shutdown of both Uvicorn servers and FastAPI lifespan cleanup.
    """
    # Uvicorn's Server.serve() handles signals internally, but we register handlers
    # here to ensure proper propagation when running two servers concurrently.
    # The handlers convert signals to KeyboardInterrupt, which asyncio.run() handles gracefully.
    def _signal_handler(signum: int, frame: object) -> None:
        """Handle termination signals by raising KeyboardInterrupt."""
        raise KeyboardInterrupt(f"Received signal {signum}")

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        asyncio.run(run_servers())
    except KeyboardInterrupt:
        # Gracefully handle termination signals without showing traceback.
        sys.exit(0)


if __name__ == "__main__":
    run()

