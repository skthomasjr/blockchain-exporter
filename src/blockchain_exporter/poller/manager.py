"""Poller manager for coordinating blockchain polling tasks across multiple FastAPI apps."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from fastapi import FastAPI

from ..config import BlockchainConfig
from ..context import ApplicationContext
from ..logging import build_log_extra, get_logger
from ..metrics import update_poller_thread_count
from . import control as poller_control

if TYPE_CHECKING:
    from collections.abc import Sequence

LOGGER = get_logger(__name__)


class PollerManager:
    """Manages blockchain polling tasks across multiple FastAPI app instances.

    This class coordinates the creation and lifecycle of polling tasks to ensure
    that tasks are only created once, even when multiple FastAPI apps (health and
    metrics) use the same lifespan. It provides thread-safe operations for
    creating, tracking, and shutting down polling tasks.

    Attributes:
        tasks_created: Whether polling tasks have been created.
        polling_tasks: List of active polling tasks.
        primary_app: The FastAPI app instance that created the tasks (for cleanup).
        _lock: Thread lock for synchronizing access to shared state.
    """

    def __init__(self) -> None:
        """Initialize a new PollerManager instance."""
        self.tasks_created: bool = False
        self.polling_tasks: list[asyncio.Task] = []
        self.primary_app: FastAPI | None = None
        self._lock = threading.Lock()

    def create_tasks(
        self,
        blockchains: Sequence[BlockchainConfig],
        context: ApplicationContext,
        app: FastAPI,
    ) -> list[asyncio.Task]:
        """Create polling tasks for the given blockchains if not already created.

        This method is thread-safe and idempotent. If tasks have already been
        created, it returns a copy of the existing tasks. Otherwise, it creates
        new tasks and stores them for reuse.

        Args:
            blockchains: Sequence of blockchain configurations to poll.
            context: Application context for dependency injection.
            app: FastAPI app instance creating the tasks.

        Returns:
            List of polling tasks (either newly created or existing).
        """
        with self._lock:
            if not self.tasks_created:
                self.tasks_created = True
                self.primary_app = app
                self.polling_tasks = []

                for blockchain in blockchains:
                    poll_task = asyncio.create_task(
                        poller_control.poll_blockchain(blockchain, context=context)
                    )
                    self.polling_tasks.append(poll_task)

                # Update poller thread count metric
                active_count = sum(1 for task in self.polling_tasks if not task.done())
                update_poller_thread_count(active_count)

                LOGGER.debug(
                    "Created %d polling task(s) for %d blockchain(s)",
                    len(self.polling_tasks),
                    len(blockchains),
                    extra=build_log_extra(additional={"blockchain_count": len(blockchains), "task_count": len(self.polling_tasks)}),
                )

                return self.polling_tasks.copy()

            # Tasks already created by another app instance; return a copy
            LOGGER.debug(
                "Reusing existing polling tasks from another app instance",
                extra=build_log_extra(additional={"existing_task_count": len(self.polling_tasks)}),
            )
            return self.polling_tasks.copy()

    def should_cleanup(self, app: FastAPI) -> bool:
        """Check if the given app should perform cleanup.

        Args:
            app: FastAPI app instance to check.

        Returns:
            True if this app created the tasks and should clean them up.
        """
        with self._lock:
            return self.tasks_created and self.primary_app is app

    async def shutdown_tasks(self, timeout_seconds: float = 30.0) -> None:
        """Shutdown all polling tasks gracefully.

        Args:
            timeout_seconds: Maximum time to wait for tasks to complete.
        """
        with self._lock:
            if not self.polling_tasks:
                return

            tasks_to_cancel = [task for task in self.polling_tasks if not task.done()]
            self.polling_tasks = []

        if not tasks_to_cancel:
            # Update poller thread count metric to zero after shutdown
            update_poller_thread_count(0)
            return

        LOGGER.debug(
            "Cancelling %d polling task(s)",
            len(tasks_to_cancel),
            extra=build_log_extra(additional={"task_count": len(tasks_to_cancel)}),
        )

        # Cancel all tasks
        for task in tasks_to_cancel:
            task.cancel()

        # Wait for tasks to complete (with timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            LOGGER.warning(
                "Polling tasks did not complete within %d seconds",
                timeout_seconds,
                extra=build_log_extra(additional={"timeout_seconds": timeout_seconds}),
            )

        # Update poller thread count metric to zero after shutdown
        update_poller_thread_count(0)

        LOGGER.debug(
            "All polling tasks cancelled",
            extra=build_log_extra(additional={"cancelled_count": len(tasks_to_cancel)}),
        )

    def get_active_task_count(self) -> int:
        """Get the count of active (non-done) polling tasks.

        Returns:
            Number of active polling tasks.
        """
        with self._lock:
            return sum(1 for task in self.polling_tasks if not task.done())

    def reset(self) -> None:
        """Reset the manager state (useful for testing)."""
        with self._lock:
            self.tasks_created = False
            self.polling_tasks = []
            self.primary_app = None


# Global singleton instance (for backward compatibility during migration)
_poller_manager: PollerManager | None = None
_manager_lock = threading.Lock()


def get_poller_manager() -> PollerManager:
    """Get the global PollerManager instance (singleton pattern).

    Returns:
        Global PollerManager instance.
    """
    global _poller_manager

    with _manager_lock:
        if _poller_manager is None:
            _poller_manager = PollerManager()

        return _poller_manager


def reset_poller_manager() -> None:
    """Reset the global PollerManager instance (useful for testing)."""
    global _poller_manager

    with _manager_lock:
        if _poller_manager is not None:
            _poller_manager.reset()


__all__ = [
    "PollerManager",
    "get_poller_manager",
    "reset_poller_manager",
]

