from pathlib import Path

import pytest

from blockchain_exporter.config import load_blockchain_configs
from blockchain_exporter.exceptions import ValidationError


def write_config(path: Path, content: str) -> Path:
    config_path = path.joinpath("config.toml")
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_load_blockchain_configs_success(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"
        poll_interval = "5m"

        [[blockchains.accounts]]
        name = "Treasury"
        address = "0x0000000000000000000000000000000000000001"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000002"
        transfer_lookback_blocks = 100
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    config = configs[0]
    assert config.name == "Mainnet"
    assert config.rpc_url == "https://example.com"
    assert config.poll_interval == "5m"
    assert len(config.accounts) == 1
    assert len(config.contracts) == 1


def test_load_blockchain_configs_missing_blockchains_returns_empty(tmp_path: Path) -> None:
    config_file = write_config(tmp_path, "[settings]\nfoo = 'bar'\n")

    configs = load_blockchain_configs(config_file)

    assert configs == []


def test_load_blockchain_configs_allows_empty_array(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        blockchains = []
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert configs == []


def test_load_blockchain_configs_rejects_duplicate_names(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.org"
        """,
    )

    with pytest.raises(ValidationError, match="Duplicate blockchain name"):
        load_blockchain_configs(config_file)


def test_contract_entry_must_be_table(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"
        contracts = ["not-a-table"]
        """,
    )

    with pytest.raises(ValidationError, match="must be a table"):
        load_blockchain_configs(config_file)


def test_contract_decimals_must_be_integer(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"
        decimals = "ten"
        """,
    )

    with pytest.raises(
        ValidationError,
        match=r"blockchains\[1\]\.contracts\[1\]\.decimals must be an integer",
    ):
        load_blockchain_configs(config_file)


def test_transfer_lookback_blocks_enforces_minimum(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"
        transfer_lookback_blocks = 0
        """,
    )

    with pytest.raises(
        ValidationError,
        match=r"transfer_lookback_blocks.*greater than or equal to 1",
    ):
        load_blockchain_configs(config_file)


def test_contract_accounts_must_be_array(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"
        accounts = "not-an-array"
        """,
    )

    with pytest.raises(ValidationError, match="accounts must be an array"):
        load_blockchain_configs(config_file)


def test_contract_account_entry_must_be_table(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"
        accounts = ["invalid-entry"]
        """,
    )

    with pytest.raises(ValidationError, match="accounts\\[1\\] must be a table"):
        load_blockchain_configs(config_file)


def test_duplicate_contract_account_addresses_case_insensitive(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"

        [[blockchains.contracts.accounts]]
        name = "Account 1"
        address = "0x00000000000000000000000000000000000000AA"

        [[blockchains.contracts.accounts]]
        name = "Account 2"
        address = "0x00000000000000000000000000000000000000aa"
        """,
    )

    with pytest.raises(ValidationError, match="Duplicate contract account address"):
        load_blockchain_configs(config_file)


def test_contract_account_requires_name_and_address(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"

        [[blockchains.contracts.accounts]]
        name = ""
        address = ""
        """,
    )

    with pytest.raises(ValidationError, match="must be a non-empty string"):
        load_blockchain_configs(config_file)


def test_rpc_url_expands_environment_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAINNET_RPC_URL", "https://env.example")

    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "${MAINNET_RPC_URL}"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert configs[0].rpc_url == "https://env.example"


def test_enabled_accounts_default_to_true(tmp_path: Path) -> None:
    """Test that accounts default to enabled=True when not specified."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.accounts]]
        name = "Account 1"
        address = "0x0000000000000000000000000000000000000001"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    assert len(configs[0].accounts) == 1
    assert configs[0].accounts[0].enabled is True


def test_disabled_accounts_are_filtered(tmp_path: Path) -> None:
    """Test that disabled accounts are filtered out during parsing."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.accounts]]
        name = "Account 1"
        address = "0x0000000000000000000000000000000000000001"
        enabled = true

        [[blockchains.accounts]]
        name = "Account 2"
        address = "0x0000000000000000000000000000000000000002"
        enabled = false

        [[blockchains.accounts]]
        name = "Account 3"
        address = "0x0000000000000000000000000000000000000003"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    assert len(configs[0].accounts) == 2
    assert configs[0].accounts[0].name == "Account 1"
    assert configs[0].accounts[1].name == "Account 3"
    assert all(account.enabled for account in configs[0].accounts)


def test_enabled_contracts_default_to_true(tmp_path: Path) -> None:
    """Test that contracts default to enabled=True when not specified."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    assert len(configs[0].contracts) == 1
    assert configs[0].contracts[0].enabled is True


def test_disabled_contracts_are_filtered(tmp_path: Path) -> None:
    """Test that disabled contracts are filtered out during parsing."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token 1"
        address = "0x0000000000000000000000000000000000000001"
        enabled = true

        [[blockchains.contracts]]
        name = "Token 2"
        address = "0x0000000000000000000000000000000000000002"
        enabled = false

        [[blockchains.contracts]]
        name = "Token 3"
        address = "0x0000000000000000000000000000000000000003"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    assert len(configs[0].contracts) == 2
    assert configs[0].contracts[0].name == "Token 1"
    assert configs[0].contracts[1].name == "Token 3"
    assert all(contract.enabled for contract in configs[0].contracts)


def test_disabled_contract_accounts_are_filtered(tmp_path: Path) -> None:
    """Test that disabled contract accounts are filtered out during parsing."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"

        [[blockchains.contracts.accounts]]
        name = "Account 1"
        address = "0x00000000000000000000000000000000000000AA"
        enabled = true

        [[blockchains.contracts.accounts]]
        name = "Account 2"
        address = "0x00000000000000000000000000000000000000BB"
        enabled = false

        [[blockchains.contracts.accounts]]
        name = "Account 3"
        address = "0x00000000000000000000000000000000000000CC"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    assert len(configs[0].contracts) == 1
    assert len(configs[0].contracts[0].accounts) == 2
    assert configs[0].contracts[0].accounts[0].name == "Account 1"
    assert configs[0].contracts[0].accounts[1].name == "Account 3"
    assert all(account.enabled for account in configs[0].contracts[0].accounts)


def test_enabled_field_accepts_boolean_strings(tmp_path: Path) -> None:
    """Test that enabled field accepts boolean string values."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.accounts]]
        name = "Account 1"
        address = "0x0000000000000000000000000000000000000001"
        enabled = "true"

        [[blockchains.accounts]]
        name = "Account 2"
        address = "0x0000000000000000000000000000000000000002"
        enabled = "false"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    assert len(configs[0].accounts) == 1
    assert configs[0].accounts[0].name == "Account 1"
    assert configs[0].accounts[0].enabled is True


def test_enabled_field_rejects_invalid_values(tmp_path: Path) -> None:
    """Test that enabled field rejects invalid boolean values."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.accounts]]
        name = "Account 1"
        address = "0x0000000000000000000000000000000000000001"
        enabled = "maybe"
        """,
    )

    with pytest.raises(ValidationError, match="must be a boolean"):
        load_blockchain_configs(config_file)


def test_disabled_contract_with_accounts_filters_all(tmp_path: Path) -> None:
    """Test that disabling a contract also filters its accounts."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000001"
        enabled = false

        [[blockchains.contracts.accounts]]
        name = "Account 1"
        address = "0x00000000000000000000000000000000000000AA"
        enabled = true

        [[blockchains.contracts.accounts]]
        name = "Account 2"
        address = "0x00000000000000000000000000000000000000BB"
        enabled = false
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    assert len(configs[0].contracts) == 0


def test_enabled_field_validation_order(tmp_path: Path) -> None:
    """Test that enabled field validation happens after required fields."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains.accounts]]
        name = ""
        address = "0x0000000000000000000000000000000000000001"
        enabled = false
        """,
    )

    # Should fail on name validation before checking enabled
    with pytest.raises(ValidationError, match="must be a non-empty string"):
        load_blockchain_configs(config_file)
