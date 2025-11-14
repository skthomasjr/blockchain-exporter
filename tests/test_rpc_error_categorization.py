"""Tests for RPC error categorization and wrapping edge cases."""

from __future__ import annotations

import pytest
from web3.exceptions import Web3RPCError

from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.exceptions import (
    RpcConnectionError,
    RpcError,
    RpcProtocolError,
    RpcTimeoutError,
)
from blockchain_exporter.rpc import _categorize_error, _wrap_rpc_exception  # noqa: PLC2701


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval=None,
        contracts=[],
        accounts=[],
    )


def test_categorize_error_timeout_exceptions(blockchain_config: BlockchainConfig) -> None:
    """Test that timeout exceptions are correctly categorized."""
    # Test RpcTimeoutError
    timeout_error = RpcTimeoutError(
        "Timeout",
        blockchain=blockchain_config.name,
        rpc_url=blockchain_config.rpc_url,
    )
    assert _categorize_error(timeout_error) == "timeout"

    # Test timeout in exception type name
    class TimeoutException(Exception):
        pass

    assert _categorize_error(TimeoutException("timeout occurred")) == "timeout"

    # Test timeout in exception message
    assert _categorize_error(ValueError("Request timeout")) == "timeout"


def test_categorize_error_connection_exceptions(blockchain_config: BlockchainConfig) -> None:
    """Test that connection exceptions are correctly categorized."""
    # Test RpcConnectionError
    conn_error = RpcConnectionError(
        "Connection failed",
        blockchain=blockchain_config.name,
        rpc_url=blockchain_config.rpc_url,
    )
    assert _categorize_error(conn_error) == "connection_error"

    # Test ConnectionError
    assert _categorize_error(ConnectionError("Connection refused")) == "connection_error"

    # Test OSError with connection-related messages
    assert _categorize_error(OSError("Connection refused")) == "connection_error"
    assert _categorize_error(OSError("Network unreachable")) == "connection_error"
    assert _categorize_error(OSError("Name resolution failed")) == "connection_error"
    assert _categorize_error(OSError("Name or service not known")) == "connection_error"
    assert _categorize_error(OSError("Connection aborted")) == "connection_error"
    assert _categorize_error(OSError("Connection reset")) == "connection_error"

    # Test connection in exception type name
    class ConnectionException(Exception):
        pass

    assert _categorize_error(ConnectionException("connection failed")) == "connection_error"

    # Test connection in exception message
    assert _categorize_error(ValueError("Connection error occurred")) == "connection_error"


def test_categorize_error_rpc_exceptions(blockchain_config: BlockchainConfig) -> None:
    """Test that RPC exceptions are correctly categorized."""
    # Test RpcProtocolError
    rpc_error = RpcProtocolError(
        "RPC error",
        blockchain=blockchain_config.name,
        rpc_url=blockchain_config.rpc_url,
    )
    assert _categorize_error(rpc_error) == "rpc_error"

    # Test generic RpcError
    generic_rpc_error = RpcError(
        "RPC failed",
        blockchain=blockchain_config.name,
        rpc_url=blockchain_config.rpc_url,
    )
    assert _categorize_error(generic_rpc_error) == "rpc_error"

    # Test RpcError with timeout in message
    timeout_rpc_error = RpcError(
        "RPC timeout",
        blockchain=blockchain_config.name,
        rpc_url=blockchain_config.rpc_url,
    )
    assert _categorize_error(timeout_rpc_error) == "timeout"

    # Test RpcError with connection in message
    conn_rpc_error = RpcError(
        "RPC connection failed",
        blockchain=blockchain_config.name,
        rpc_url=blockchain_config.rpc_url,
    )
    assert _categorize_error(conn_rpc_error) == "connection_error"

    # Test Web3RPCError
    web3_rpc_error = Web3RPCError({"message": "RPC error"})
    assert _categorize_error(web3_rpc_error) == "rpc_error"

    # Test RPC in exception type name
    class RpcException(Exception):
        pass

    assert _categorize_error(RpcException("rpc failed")) == "rpc_error"

    # Test RPC in exception message
    assert _categorize_error(ValueError("RPC error occurred")) == "rpc_error"


def test_categorize_error_value_exceptions(blockchain_config: BlockchainConfig) -> None:
    """Test that value/type exceptions are correctly categorized."""
    assert _categorize_error(ValueError("Invalid value")) == "value_error"
    assert _categorize_error(TypeError("Invalid type")) == "value_error"
    assert _categorize_error(AttributeError("No attribute")) == "value_error"
    assert _categorize_error(KeyError("Missing key")) == "value_error"


def test_categorize_error_unknown_exceptions(blockchain_config: BlockchainConfig) -> None:
    """Test that unknown exceptions are categorized as unknown."""
    assert _categorize_error(RuntimeError("Unknown error")) == "unknown"
    assert _categorize_error(Exception("Generic error")) == "unknown"


def test_wrap_rpc_exception_preserves_rpc_error(blockchain_config: BlockchainConfig) -> None:
    """Test that _wrap_rpc_exception preserves existing RpcError instances."""
    original_error = RpcTimeoutError(
        "Original timeout",
        blockchain=blockchain_config.name,
        rpc_url=blockchain_config.rpc_url,
    )

    wrapped = _wrap_rpc_exception(
        original_error,
        blockchain_config,
        "get_balance",
        "eth_getBalance",
        1,
        3,
    )

    assert wrapped is original_error  # Should return the same instance


def test_wrap_rpc_exception_wraps_timeout(blockchain_config: BlockchainConfig) -> None:
    """Test that timeout exceptions are wrapped in RpcTimeoutError."""
    timeout_exception = TimeoutError("Request timeout")

    wrapped = _wrap_rpc_exception(
        timeout_exception,
        blockchain_config,
        "get_balance",
        "eth_getBalance",
        1,
        3,
    )

    assert isinstance(wrapped, RpcTimeoutError)
    assert wrapped.blockchain == blockchain_config.name
    assert wrapped.rpc_url == blockchain_config.rpc_url
    assert wrapped.operation == "get_balance"
    assert wrapped.attempt == 1
    assert wrapped.max_attempts == 3


def test_wrap_rpc_exception_wraps_connection_error(blockchain_config: BlockchainConfig) -> None:
    """Test that connection errors are wrapped in RpcConnectionError."""
    conn_exception = ConnectionError("Connection refused")

    wrapped = _wrap_rpc_exception(
        conn_exception,
        blockchain_config,
        "get_block",
        "eth_getBlock",
        2,
        3,
    )

    assert isinstance(wrapped, RpcConnectionError)
    assert wrapped.blockchain == blockchain_config.name
    assert wrapped.rpc_url == blockchain_config.rpc_url
    assert wrapped.operation == "get_block"
    assert wrapped.attempt == 2
    assert wrapped.max_attempts == 3


def test_wrap_rpc_exception_wraps_web3_rpc_error(blockchain_config: BlockchainConfig) -> None:
    """Test that Web3RPCError is wrapped in RpcProtocolError with error code/message."""
    web3_error = Web3RPCError({"code": -32000, "message": "Server error"})

    wrapped = _wrap_rpc_exception(
        web3_error,
        blockchain_config,
        "get_logs",
        "eth_getLogs",
        1,
        3,
    )

    assert isinstance(wrapped, RpcProtocolError)
    assert wrapped.blockchain == blockchain_config.name
    assert wrapped.rpc_url == blockchain_config.rpc_url
    assert wrapped.operation == "get_logs"
    assert wrapped.rpc_error_code == -32000
    assert wrapped.rpc_error_message == "Server error"


def test_wrap_rpc_exception_wraps_value_error(blockchain_config: BlockchainConfig) -> None:
    """Test that value errors are wrapped in RpcError."""
    value_error = ValueError("Invalid address format")

    wrapped = _wrap_rpc_exception(
        value_error,
        blockchain_config,
        "get_balance",
        "eth_getBalance",
        1,
        3,
    )

    assert isinstance(wrapped, RpcError)
    assert not isinstance(wrapped, (RpcTimeoutError, RpcConnectionError, RpcProtocolError))
    assert wrapped.blockchain == blockchain_config.name
    assert wrapped.rpc_url == blockchain_config.rpc_url


def test_wrap_rpc_exception_wraps_unknown_error(blockchain_config: BlockchainConfig) -> None:
    """Test that unknown errors are wrapped in RpcError."""
    unknown_error = RuntimeError("Unexpected error")

    wrapped = _wrap_rpc_exception(
        unknown_error,
        blockchain_config,
        "get_block",
        "eth_getBlock",
        1,
        3,
    )

    assert isinstance(wrapped, RpcError)
    assert not isinstance(wrapped, (RpcTimeoutError, RpcConnectionError, RpcProtocolError))
    assert wrapped.blockchain == blockchain_config.name
    assert wrapped.rpc_url == blockchain_config.rpc_url

