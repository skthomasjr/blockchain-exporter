"""Tests for enhanced config validation (address format, poll interval, etc.)."""

from pathlib import Path

import pytest

from blockchain_exporter.config import load_blockchain_configs
from blockchain_exporter.exceptions import ValidationError


def write_config(path: Path, content: str) -> Path:
    """Write a test config file."""
    config_path = path.joinpath("config.toml")
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_invalid_address_format_rejected(tmp_path: Path) -> None:
    """Test that invalid Ethereum address formats are rejected."""
    invalid_addresses = [
        ("0x123", "too short"),
        ("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef", "too long"),
        ("1234567890abcdef1234567890abcdef12345678", "missing 0x prefix"),
        ("0xg1234567890abcdef1234567890abcdef12345678", "invalid hex character"),
    ]

    for invalid_address, description in invalid_addresses:
        config_file = write_config(
            tmp_path,
            f"""
            [[blockchains]]
            name = "Test"
            rpc_url = "https://example.com"

            [[blockchains.accounts]]
            name = "Test Account"
            address = "{invalid_address}"
            """,
        )

        with pytest.raises(ValidationError, match="must be a valid Ethereum address format"):
            load_blockchain_configs(config_file)


def test_valid_address_format_accepted(tmp_path: Path) -> None:
    """Test that valid Ethereum address formats are accepted."""
    valid_addresses = [
        "0x1234567890abcdef1234567890abcdef12345678",  # Lowercase
        "0xABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD",  # Uppercase
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # Mixed case
        "0x0000000000000000000000000000000000000000",  # Zero address
    ]

    for valid_address in valid_addresses:
        config_file = write_config(
            tmp_path,
            f"""
            [[blockchains]]
            name = "Test"
            rpc_url = "https://example.com"

            [[blockchains.accounts]]
            name = "Test Account"
            address = "{valid_address}"
            """,
        )

        configs = load_blockchain_configs(config_file)
        assert len(configs) == 1
        assert len(configs[0].accounts) == 1
        # Address should be normalized to lowercase
        assert configs[0].accounts[0].address == valid_address.lower()


def test_invalid_poll_interval_format_rejected(tmp_path: Path) -> None:
    """Test that invalid poll interval formats are rejected."""
    invalid_intervals = [
        "5x",  # Invalid unit
        "abc",  # Not a number
        "5d",  # Invalid unit (days not supported)
    ]

    for invalid_interval in invalid_intervals:
        config_file = write_config(
            tmp_path,
            f"""
            [[blockchains]]
            name = "Test"
            rpc_url = "https://example.com"
            poll_interval = "{invalid_interval}"
            """,
        )

        with pytest.raises(ValidationError, match="must be a valid duration format"):
            load_blockchain_configs(config_file)


def test_valid_poll_interval_format_accepted(tmp_path: Path) -> None:
    """Test that valid poll interval formats are accepted."""
    valid_intervals = [
        "5s",
        "10m",
        "1h",
        "30",  # Defaults to seconds
    ]

    for valid_interval in valid_intervals:
        config_file = write_config(
            tmp_path,
            f"""
            [[blockchains]]
            name = "Test"
            rpc_url = "https://example.com"
            poll_interval = "{valid_interval}"
            """,
        )

        configs = load_blockchain_configs(config_file)
        assert len(configs) == 1
        assert configs[0].poll_interval == valid_interval


def test_address_validation_applies_to_contracts(tmp_path: Path) -> None:
    """Test that address validation applies to contract addresses."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Test"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Test Contract"
        address = "0x123"  # Invalid format
        """,
    )

    with pytest.raises(ValidationError, match="must be a valid Ethereum address format"):
        load_blockchain_configs(config_file)


def test_address_validation_applies_to_contract_accounts(tmp_path: Path) -> None:
    """Test that address validation applies to contract account addresses."""
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Test"
        rpc_url = "https://example.com"

        [[blockchains.contracts]]
        name = "Test Contract"
        address = "0x1234567890abcdef1234567890abcdef12345678"

        [[blockchains.contracts.accounts]]
        name = "Test Account"
        address = "0x123"  # Invalid format
        """,
    )

    with pytest.raises(ValidationError, match="must be a valid Ethereum address format"):
        load_blockchain_configs(config_file)

