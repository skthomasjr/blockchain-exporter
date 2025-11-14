"""Tests for RpcClient method implementations."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from blockchain_exporter.config import BlockchainConfig
from blockchain_exporter.exceptions import RpcError
from blockchain_exporter.rpc import RpcClient


@pytest.fixture
def blockchain_config() -> BlockchainConfig:
    return BlockchainConfig(
        name="Test Chain",
        rpc_url="https://rpc.example",
        poll_interval=None,
        contracts=[],
        accounts=[],
    )


def test_rpc_client_get_chain_id(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_chain_id method."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        captured["blockchain"] = blockchain.name
        captured["max_attempts"] = kwargs.get("max_attempts")
        captured["operation_type"] = kwargs.get("operation_type")
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    fake_eth = SimpleNamespace(chain_id=42)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config, chain_id_label="42")

    chain_id = client.get_chain_id()

    assert chain_id == 42
    assert captured["description"] == "eth_chainId"
    assert captured["blockchain"] == "Test Chain"
    assert captured["max_attempts"] == 1
    assert captured["operation_type"] == "get_chain_id"


def test_rpc_client_get_chain_id_with_custom_description(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_chain_id with custom description."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    fake_eth = SimpleNamespace(chain_id=42)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    client.get_chain_id(description="custom_chain_id")

    assert captured["description"] == "custom_chain_id"


def test_rpc_client_get_chain_id_with_extra(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_chain_id with extra context."""
    captured: dict[str, dict] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["context_extra"] = kwargs.get("context_extra")
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    fake_eth = SimpleNamespace(chain_id=42)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    extra = {"custom": "value"}
    client.get_chain_id(extra=extra)

    assert captured["context_extra"] == extra


def test_rpc_client_get_code(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_code method."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        captured["blockchain"] = blockchain.name
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    fake_eth = SimpleNamespace(get_code=lambda address: b"0x1234")
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    code = client.get_code("0xabc")

    assert code == b"0x1234"
    assert captured["description"] == "eth_getCode(0xabc)"
    assert captured["blockchain"] == "Test Chain"


def test_rpc_client_get_code_with_custom_description(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_code with custom description."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    fake_eth = SimpleNamespace(get_code=lambda address: b"0x1234")
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    client.get_code("0xabc", description="custom_get_code")

    assert captured["description"] == "custom_get_code"


def test_rpc_client_get_code_with_extra(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_code with extra context."""
    captured: dict[str, dict] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["context_extra"] = kwargs.get("context_extra")
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    fake_eth = SimpleNamespace(get_code=lambda address: b"0x1234")
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    extra = {"custom": "value"}
    client.get_code("0xabc", extra=extra)

    assert captured["context_extra"] == extra


def test_rpc_client_get_logs(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_logs method."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        captured["blockchain"] = blockchain.name
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    test_logs = [{"address": "0x123", "topics": [], "data": "0x"}]

    def get_logs(params: dict) -> list[dict]:
        return test_logs

    fake_eth = SimpleNamespace(get_logs=get_logs)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    params = {"fromBlock": 100, "toBlock": 200}
    logs = client.get_logs(params)

    assert logs == test_logs
    assert "eth_getLogs" in captured["description"]
    assert captured["blockchain"] == "Test Chain"


def test_rpc_client_get_logs_with_custom_description(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_logs with custom description."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    def get_logs(params: dict) -> list[dict]:
        return []

    fake_eth = SimpleNamespace(get_logs=get_logs)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    params = {"fromBlock": 100, "toBlock": 200}
    client.get_logs(params, description="custom_get_logs")

    assert captured["description"] == "custom_get_logs"


def test_rpc_client_get_logs_with_extra(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.get_logs with extra context."""
    captured: dict[str, dict] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["context_extra"] = kwargs.get("context_extra")
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    def get_logs(params: dict) -> list[dict]:
        return []

    fake_eth = SimpleNamespace(get_logs=get_logs)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    extra = {"custom": "value"}
    params = {"fromBlock": 100, "toBlock": 200}
    client.get_logs(params, extra=extra)

    assert captured["context_extra"] == extra


def test_rpc_client_call_contract_function(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.call_contract_function method."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        captured["blockchain"] = blockchain.name
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    def call_function(contract_address: str, function_call) -> int:
        return function_call()

    fake_eth = SimpleNamespace(call=call_function)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    def contract_function():
        return 42

    result = client.call_contract_function(contract_function, "decimals()")

    assert result == 42
    assert "decimals()" in captured["description"]
    assert captured["blockchain"] == "Test Chain"


def test_rpc_client_call_contract_function_with_custom_description(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.call_contract_function with custom description."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["description"] = description
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    def call_function(contract_address: str, function_call) -> int:
        return function_call()

    fake_eth = SimpleNamespace(call=call_function)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    def contract_function():
        return 42

    # description is a positional argument, not keyword
    client.call_contract_function(contract_function, "custom_call")

    assert captured["description"] == "custom_call"


def test_rpc_client_call_contract_function_with_extra(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient.call_contract_function with extra context."""
    captured: dict[str, dict] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["context_extra"] = kwargs.get("context_extra")
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    def call_function(contract_address: str, function_call) -> int:
        return function_call()

    fake_eth = SimpleNamespace(call=call_function)
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    def contract_function():
        return 42

    extra = {"custom": "value"}
    client.call_contract_function(contract_function, "decimals()", extra=extra)

    assert captured["context_extra"] == extra


def test_rpc_client_properties(blockchain_config: BlockchainConfig) -> None:
    """Test RpcClient properties."""
    fake_web3 = SimpleNamespace(eth=SimpleNamespace(chain_id=1))
    client = RpcClient(fake_web3, blockchain_config, chain_id_label="1")

    assert client.web3 is fake_web3
    assert client.blockchain is blockchain_config


def test_rpc_client_methods_use_chain_id_label(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test that RpcClient methods pass chain_id_label to execute_with_retries."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["chain_id_label"] = kwargs.get("chain_id_label")
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    fake_eth = SimpleNamespace(
        chain_id=1,
        get_balance=lambda address: 123,
        get_code=lambda address: b"0x",
        get_logs=lambda params: [],
        call=lambda address, function_call: function_call(),
    )
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config, chain_id_label="42")

    # Test get_chain_id
    client.get_chain_id()
    assert captured["chain_id_label"] == "42"

    # Test get_balance
    client.get_balance("0xabc")
    assert captured["chain_id_label"] == "42"

    # Test get_code
    client.get_code("0xabc")
    assert captured["chain_id_label"] == "42"

    # Test get_logs
    client.get_logs({"fromBlock": 100, "toBlock": 200})
    assert captured["chain_id_label"] == "42"

    # Test call_contract_function
    client.call_contract_function(lambda: 42, "test()")
    assert captured["chain_id_label"] == "42"


def test_rpc_client_methods_use_operation_type(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test that RpcClient methods pass correct operation_type to execute_with_retries."""
    captured: dict[str, str] = {}

    def fake_execute(operation, description, blockchain, **kwargs):  # type: ignore[no-untyped-def]
        captured["operation_type"] = kwargs.get("operation_type")
        return operation()

    monkeypatch.setattr("blockchain_exporter.rpc.execute_with_retries", fake_execute)

    fake_eth = SimpleNamespace(
        chain_id=1,
        get_balance=lambda address: 123,
        get_code=lambda address: b"0x",
        get_logs=lambda params: [],
        call=lambda address, function_call: function_call(),
    )
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    # Test get_chain_id
    client.get_chain_id()
    assert captured["operation_type"] == "get_chain_id"

    # Test get_balance
    client.get_balance("0xabc")
    assert captured["operation_type"] == "get_balance"

    # Test get_code
    client.get_code("0xabc")
    assert captured["operation_type"] == "get_code"

    # Test get_logs
    client.get_logs({"fromBlock": 100, "toBlock": 200})
    assert captured["operation_type"] == "get_logs"

    # Test call_contract_function
    client.call_contract_function(lambda: 42, "test()")
    assert captured["operation_type"] == "call_contract_function"


def test_rpc_client_methods_error_handling(monkeypatch: pytest.MonkeyPatch, blockchain_config: BlockchainConfig) -> None:
    """Test that RpcClient methods properly handle errors through execute_with_retries.

    Note: Error handling is extensively tested in test_rpc.py and test_rpc_error_categorization.py.
    This test verifies that methods correctly pass through to execute_with_retries.
    """
    monkeypatch.setattr("blockchain_exporter.rpc.time.sleep", lambda _seconds: None)

    # Test that get_balance properly handles errors
    # Error handling is already well tested in test_rpc.py, so we just verify
    # that the method signature and basic flow work correctly
    def failing_get_balance(address: str) -> None:
        raise ValueError("Test error")

    fake_eth = SimpleNamespace(
        chain_id=1,
        get_balance=failing_get_balance,
        get_code=lambda address: b"0x",
        get_logs=lambda params: [],
        call=lambda address, function_call: function_call(),
    )
    fake_web3 = SimpleNamespace(eth=fake_eth)

    client = RpcClient(fake_web3, blockchain_config)

    # get_balance should raise RpcError (wrapped from ValueError)
    # This is tested more thoroughly in test_rpc.py
    with pytest.raises(RpcError):
        client.get_balance("0xabc")

