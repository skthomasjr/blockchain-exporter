"""Tests for connection pooling functionality."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.poller.connection_pool import (
    ConnectionPoolManager,
    get_connection_pool_manager,
    reset_connection_pool_manager,
)


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    """Create a test blockchain configuration."""
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example.com",
        poll_interval="1m",
        accounts=[],
        contracts=[],
    )


@pytest.fixture
def pool_manager() -> ConnectionPoolManager:
    """Create a fresh connection pool manager for testing."""
    return ConnectionPoolManager(pool_size=2)


def test_connection_pool_manager_get_client_creates_new(
    pool_manager: ConnectionPoolManager,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that getting a client from an empty pool creates a new one."""
    client = pool_manager.get_client(blockchain_config)

    assert client is not None
    assert isinstance(client, SimpleNamespace) or hasattr(client, "provider")

    stats = pool_manager.get_pool_stats()
    assert blockchain_config.rpc_url in stats
    assert stats[blockchain_config.rpc_url]["active_count"] == 1
    assert stats[blockchain_config.rpc_url]["pool_size"] == 0


def test_connection_pool_manager_return_client_adds_to_pool(
    pool_manager: ConnectionPoolManager,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that returning a client adds it to the pool."""
    # Get a client
    client = pool_manager.get_client(blockchain_config)

    # Return it
    pool_manager.return_client(blockchain_config, client)

    stats = pool_manager.get_pool_stats()
    assert stats[blockchain_config.rpc_url]["pool_size"] == 1
    assert stats[blockchain_config.rpc_url]["active_count"] == 0


def test_connection_pool_manager_reuses_client_from_pool(
    pool_manager: ConnectionPoolManager,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that getting a client reuses one from the pool if available."""
    # Get and return a client
    client1 = pool_manager.get_client(blockchain_config)
    pool_manager.return_client(blockchain_config, client1)

    # Get another client - should reuse from pool
    client2 = pool_manager.get_client(blockchain_config)

    assert client1 is client2

    stats = pool_manager.get_pool_stats()
    assert stats[blockchain_config.rpc_url]["pool_size"] == 0
    assert stats[blockchain_config.rpc_url]["active_count"] == 1


def test_connection_pool_manager_respects_pool_size_limit(
    pool_manager: ConnectionPoolManager,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that the pool respects the size limit."""
    clients = []

    # Get multiple clients first (all will be active)
    for _ in range(pool_manager._pool_size + 2):
        client = pool_manager.get_client(blockchain_config)
        clients.append(client)

    # Return all clients to the pool (should respect pool size limit)
    for client in clients:
        pool_manager.return_client(blockchain_config, client)

    stats = pool_manager.get_pool_stats()
    # Pool should only have pool_size clients, extra should be discarded
    assert stats[blockchain_config.rpc_url]["pool_size"] == pool_manager._pool_size
    assert stats[blockchain_config.rpc_url]["active_count"] == 0


def test_connection_pool_manager_clear_pool(
    pool_manager: ConnectionPoolManager,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that clearing the pool removes all clients."""
    # Get and return some clients
    client1 = pool_manager.get_client(blockchain_config)
    pool_manager.return_client(blockchain_config, client1)

    # Clear the pool
    pool_manager.clear_pool(blockchain_config.rpc_url)

    stats = pool_manager.get_pool_stats()
    assert blockchain_config.rpc_url not in stats or stats[blockchain_config.rpc_url]["pool_size"] == 0


def test_connection_pool_manager_clear_all_pools(
    pool_manager: ConnectionPoolManager,
    blockchain_config: BlockchainConfig,
) -> None:
    """Test that clearing all pools removes everything."""
    # Create multiple blockchains with different RPC URLs
    blockchain1 = BlockchainConfig(
        name="Chain 1",
        rpc_url="https://rpc1.example.com",
        poll_interval="1m",
        accounts=[],
        contracts=[],
    )
    blockchain2 = BlockchainConfig(
        name="Chain 2",
        rpc_url="https://rpc2.example.com",
        poll_interval="1m",
        accounts=[],
        contracts=[],
    )

    # Get clients for both
    client1 = pool_manager.get_client(blockchain1)
    client2 = pool_manager.get_client(blockchain2)
    pool_manager.return_client(blockchain1, client1)
    pool_manager.return_client(blockchain2, client2)

    # Clear all pools
    pool_manager.clear_pool()

    stats = pool_manager.get_pool_stats()
    assert len(stats) == 0


def test_get_connection_pool_manager_returns_singleton() -> None:
    """Test that get_connection_pool_manager returns the same instance."""
    manager1 = get_connection_pool_manager()
    manager2 = get_connection_pool_manager()

    assert manager1 is manager2


def test_reset_connection_pool_manager_clears_global() -> None:
    """Test that reset_connection_pool_manager clears the global instance."""
    manager1 = get_connection_pool_manager()
    reset_connection_pool_manager()
    manager2 = get_connection_pool_manager()

    assert manager1 is not manager2


def test_connection_pool_manager_different_rpc_urls_separate_pools(
    pool_manager: ConnectionPoolManager,
) -> None:
    """Test that different RPC URLs have separate pools."""
    blockchain1 = BlockchainConfig(
        name="Chain 1",
        rpc_url="https://rpc1.example.com",
        poll_interval="1m",
        accounts=[],
        contracts=[],
    )
    blockchain2 = BlockchainConfig(
        name="Chain 2",
        rpc_url="https://rpc2.example.com",
        poll_interval="1m",
        accounts=[],
        contracts=[],
    )

    # Get clients for both
    client1 = pool_manager.get_client(blockchain1)
    client2 = pool_manager.get_client(blockchain2)

    # They should be different instances (different sessions)
    assert client1 is not client2

    # Return both
    pool_manager.return_client(blockchain1, client1)
    pool_manager.return_client(blockchain2, client2)

    stats = pool_manager.get_pool_stats()
    assert len(stats) == 2
    assert stats[blockchain1.rpc_url]["pool_size"] == 1
    assert stats[blockchain2.rpc_url]["pool_size"] == 1

