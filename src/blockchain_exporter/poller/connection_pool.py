"""Connection pool manager for RPC clients to reuse HTTP connections."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from web3 import HTTPProvider, Web3

from ..config import BlockchainConfig
from ..logging import get_logger
from ..settings import get_settings

if TYPE_CHECKING:
    from requests import Session

LOGGER = get_logger(__name__)
SETTINGS = get_settings()

# Default connection pool size per RPC endpoint
DEFAULT_POOL_SIZE = 10
# Maximum number of connections to keep alive
DEFAULT_MAX_POOL_SIZE = 50


class ConnectionPoolManager:
    """Manages connection pools for Web3 RPC clients.

    This manager maintains a pool of Web3 client instances per RPC URL,
    enabling connection reuse and improved performance when making frequent
    requests to the same blockchain RPC endpoint.

    Thread-safe: All operations are protected by a lock to ensure safe
    concurrent access from multiple polling threads.
    """

    def __init__(
        self,
        timeout_seconds: float | None = None,
        pool_size: int = DEFAULT_POOL_SIZE,
    ) -> None:
        """Initialize the connection pool manager.

        Args:
            timeout_seconds: RPC request timeout in seconds. Defaults to configured timeout.
            pool_size: Maximum number of connections to pool per RPC URL. Defaults to 10.
        """
        self._timeout_seconds = timeout_seconds or SETTINGS.poller.rpc_request_timeout_seconds
        self._pool_size = pool_size
        self._lock = threading.Lock()
        # Map of RPC URL -> list of Web3 client instances (pool)
        self._pools: dict[str, list[Web3]] = {}
        # Map of RPC URL -> count of active clients (not in pool)
        self._active_counts: dict[str, int] = {}
        # Map of RPC URL -> requests.Session for connection reuse
        self._sessions: dict[str, Session] = {}

    def get_client(self, blockchain: BlockchainConfig) -> Web3:
        """Get a Web3 client from the pool or create a new one.

        This method tries to reuse an existing client from the pool first.
        If the pool is empty, it creates a new client. The client should be
        returned to the pool via `return_client` when done.

        Args:
            blockchain: Blockchain configuration with RPC URL.

        Returns:
            A Web3 client instance ready to use.
        """
        rpc_url = blockchain.rpc_url

        with self._lock:
            # Check if we have a client in the pool
            if rpc_url in self._pools and self._pools[rpc_url]:
                client = self._pools[rpc_url].pop()
                self._active_counts[rpc_url] = self._active_counts.get(rpc_url, 0) + 1
                LOGGER.debug(
                    "Reusing pooled Web3 client for %s (pool size: %d, active: %d)",
                    blockchain.name,
                    len(self._pools.get(rpc_url, [])),
                    self._active_counts.get(rpc_url, 0),
                    extra={"blockchain": blockchain.name, "rpc_url": rpc_url},
                )
                return client

            # Create a new client
            self._active_counts[rpc_url] = self._active_counts.get(rpc_url, 0) + 1

            # Get or create a session for this RPC URL to enable connection pooling
            session = self._get_session(rpc_url)

            provider = HTTPProvider(
                rpc_url,
                request_kwargs={"timeout": self._timeout_seconds},
                session=session,
            )

            client = Web3(provider)

            LOGGER.debug(
                "Created new Web3 client for %s (active: %d)",
                blockchain.name,
                self._active_counts.get(rpc_url, 0),
                extra={"blockchain": blockchain.name, "rpc_url": rpc_url},
            )

            return client

    def return_client(self, blockchain: BlockchainConfig, client: Web3) -> None:
        """Return a Web3 client to the pool for reuse.

        If the pool is full, the client is discarded. This prevents unbounded
        growth of the pool.

        Args:
            blockchain: Blockchain configuration with RPC URL.
            client: The Web3 client instance to return.
        """
        rpc_url = blockchain.rpc_url

        with self._lock:
            active_count = self._active_counts.get(rpc_url, 0)
            if active_count > 0:
                self._active_counts[rpc_url] = active_count - 1

            # Check if pool has space
            pool = self._pools.setdefault(rpc_url, [])
            if len(pool) < self._pool_size:
                pool.append(client)
                LOGGER.debug(
                    "Returned Web3 client to pool for %s (pool size: %d, active: %d)",
                    blockchain.name,
                    len(pool),
                    self._active_counts.get(rpc_url, 0),
                    extra={"blockchain": blockchain.name, "rpc_url": rpc_url},
                )
            else:
                LOGGER.debug(
                    "Pool full for %s, discarding client (pool size: %d, active: %d)",
                    blockchain.name,
                    len(pool),
                    self._active_counts.get(rpc_url, 0),
                    extra={"blockchain": blockchain.name, "rpc_url": rpc_url},
                )
                # Close the client's session if possible
                try:
                    if hasattr(client.provider, "session") and client.provider.session:
                        client.provider.session.close()
                except Exception:  # noqa: BLE001
                    pass  # Ignore errors during cleanup

    def _get_session(self, rpc_url: str) -> Session:
        """Get or create a requests.Session for the given RPC URL.

        Sessions are reused to enable HTTP connection pooling within the
        requests library.

        Args:
            rpc_url: The RPC URL to get a session for.

        Returns:
            A requests.Session instance.
        """
        if rpc_url not in self._sessions:
            import requests

            session = requests.Session()
            # Configure session for connection pooling
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=self._pool_size,
                pool_maxsize=self._pool_size,
                max_retries=0,  # Retries handled by our RPC client
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            self._sessions[rpc_url] = session
            LOGGER.debug(
                "Created new requests.Session for connection pooling: %s",
                rpc_url,
                extra={"rpc_url": rpc_url},
            )

        return self._sessions[rpc_url]

    def clear_pool(self, rpc_url: str | None = None) -> None:
        """Clear the connection pool for a specific RPC URL or all pools.

        Args:
            rpc_url: The RPC URL to clear. If None, clears all pools.
        """
        with self._lock:
            if rpc_url is None:
                # Clear all pools
                for url, pool in list(self._pools.items()):
                    for client in pool:
                        try:
                            if hasattr(client.provider, "session") and client.provider.session:
                                client.provider.session.close()
                        except Exception:  # noqa: BLE001
                            pass
                self._pools.clear()
                self._active_counts.clear()

                # Close all sessions
                for url, session in list(self._sessions.items()):
                    try:
                        session.close()
                    except Exception:  # noqa: BLE001
                        pass
                self._sessions.clear()

                LOGGER.debug("Cleared all connection pools")
            else:
                # Clear specific pool
                if rpc_url in self._pools:
                    for client in self._pools[rpc_url]:
                        try:
                            if hasattr(client.provider, "session") and client.provider.session:
                                client.provider.session.close()
                        except Exception:  # noqa: BLE001
                            pass
                    del self._pools[rpc_url]

                if rpc_url in self._active_counts:
                    del self._active_counts[rpc_url]

                if rpc_url in self._sessions:
                    try:
                        self._sessions[rpc_url].close()
                    except Exception:  # noqa: BLE001
                        pass
                    del self._sessions[rpc_url]

                LOGGER.debug("Cleared connection pool for %s", rpc_url)

    def get_pool_stats(self) -> dict[str, dict[str, int]]:
        """Get statistics about connection pools.

        Returns:
            Dictionary mapping RPC URL to pool statistics (pool_size, active_count).
        """
        with self._lock:
            return {
                url: {
                    "pool_size": len(self._pools.get(url, [])),
                    "active_count": self._active_counts.get(url, 0),
                }
                for url in set(list(self._pools.keys()) + list(self._active_counts.keys()))
            }


# Global connection pool manager instance
_GLOBAL_POOL_MANAGER: ConnectionPoolManager | None = None


def get_connection_pool_manager() -> ConnectionPoolManager:
    """Get the global connection pool manager instance.

    Returns:
        The global ConnectionPoolManager instance.
    """
    global _GLOBAL_POOL_MANAGER

    if _GLOBAL_POOL_MANAGER is None:
        _GLOBAL_POOL_MANAGER = ConnectionPoolManager()

    return _GLOBAL_POOL_MANAGER


def reset_connection_pool_manager() -> None:
    """Reset the global connection pool manager.

    This clears all pools and creates a new manager instance. Useful for testing.
    """
    global _GLOBAL_POOL_MANAGER

    if _GLOBAL_POOL_MANAGER is not None:
        _GLOBAL_POOL_MANAGER.clear_pool()

    _GLOBAL_POOL_MANAGER = None


__all__ = [
    "ConnectionPoolManager",
    "DEFAULT_MAX_POOL_SIZE",
    "DEFAULT_POOL_SIZE",
    "get_connection_pool_manager",
    "reset_connection_pool_manager",
]
