"""Tests for BlockchainConfig enabled field functionality."""

from pathlib import Path

import pytest

from blockchain_exporter.config import load_blockchain_configs
from blockchain_exporter.exceptions import ValidationError


def write_config(path: Path, content: str) -> Path:
    """Write a test config file."""
    config_path = path.joinpath("config.toml")
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_enabled_blockchains_default_to_true(tmp_path: Path) -> None:
    """Test that BlockchainConfig defaults enabled to True."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 1
    assert configs[0].enabled is True


def test_disabled_blockchains_are_filtered(tmp_path: Path) -> None:
    """Test that disabled blockchains are filtered during parsing."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"

        [[blockchains]]
        name = "Testnet"
        rpc_url = "https://testnet.example.com"
        enabled = false

        [[blockchains]]
        name = "Another Chain"
        rpc_url = "https://another.example.com"
        """,
    )

    configs = load_blockchain_configs(config_file)

    assert len(configs) == 2
    assert all(config.enabled for config in configs)
    assert all(config.name != "Testnet" for config in configs)


def test_enabled_field_accepts_boolean_strings(tmp_path: Path) -> None:
    """Test that enabled field accepts string representations of booleans."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Chain1"
        rpc_url = "https://example.com"
        enabled = "true"

        [[blockchains]]
        name = "Chain2"
        rpc_url = "https://example.com"
        enabled = "false"

        [[blockchains]]
        name = "Chain3"
        rpc_url = "https://example.com"
        enabled = "1"

        [[blockchains]]
        name = "Chain4"
        rpc_url = "https://example.com"
        enabled = "0"
        """,
    )

    configs = load_blockchain_configs(config_file)

    # Chain1 and Chain3 should be enabled (true, 1)
    # Chain2 and Chain4 should be filtered out (false, 0)
    assert len(configs) == 2
    assert all(config.name in ("Chain1", "Chain3") for config in configs)


def test_enabled_field_rejects_invalid_values(tmp_path: Path) -> None:
    """Test that enabled field rejects invalid boolean string values."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"
        enabled = "invalid"
        """,
    )

    with pytest.raises(ValidationError, match="must be a boolean"):
        load_blockchain_configs(config_file)


def test_disabled_blockchain_with_accounts_and_contracts_filters_all(tmp_path: Path) -> None:
    """Test that disabling a blockchain filters all its child accounts and contracts."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"
        enabled = false

        [[blockchains.accounts]]
        name = "Treasury"
        address = "0x0000000000000000000000000000000000000001"

        [[blockchains.contracts]]
        name = "Token"
        address = "0x0000000000000000000000000000000000000002"
        """,
    )

    configs = load_blockchain_configs(config_file)

    # Disabled blockchain should be filtered out entirely
    assert len(configs) == 0


def test_enabled_field_validation_order(tmp_path: Path) -> None:
    """Test that enabled field validation happens after required fields."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = ""
        rpc_url = "https://example.com"
        enabled = false
        """,
    )

    # Should fail on name validation before checking enabled
    with pytest.raises(ValidationError, match="must be a non-empty string"):
        load_blockchain_configs(config_file)

