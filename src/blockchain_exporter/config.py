from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .exceptions import ConfigError, ValidationError
from .settings import AppSettings, get_settings

DEFAULT_ENV_PATH = Path.cwd().joinpath(".env").resolve()

load_dotenv(DEFAULT_ENV_PATH)


@dataclass(frozen=True, slots=True)
class AccountConfig:
    name: str

    address: str

    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ContractConfig:
    name: str

    address: str

    decimals: int | None

    accounts: list["ContractAccountConfig"]

    transfer_lookback_blocks: int | None

    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ContractAccountConfig:
    name: str

    address: str

    enabled: bool = True


@dataclass(frozen=True, slots=True)
class BlockchainConfig:
    name: str

    rpc_url: str

    poll_interval: str | None

    contracts: list["ContractConfig"]

    accounts: list[AccountConfig]

    enabled: bool = True


def load_blockchain_configs(path: Path | None = None) -> list[BlockchainConfig]:
    config_path = path or resolve_config_path()

    data = _read_toml(config_path)

    blockchains_data = data.get("blockchains")

    if blockchains_data is None:
        return []

    if not isinstance(blockchains_data, list):
        raise ConfigError(
            "Configuration 'blockchains' section must be an array.",
            config_section="blockchains",
        )

    if not blockchains_data:
        return []

    seen_blockchain_names: set[str] = set()

    blockchains: list[BlockchainConfig] = []

    for index, entry in enumerate(blockchains_data, start=1):
        if not isinstance(entry, dict):
            raise ValidationError(
                f"Blockchains[{index}] must be a table.",
                config_section=f"blockchains[{index}]",
                expected_type="table",
                value=type(entry).__name__,
            )

        config = _parse_blockchain_config(entry, index)

        # Skip disabled blockchains
        if not config.enabled:
            continue

        normalized_name = config.name.lower()

        if normalized_name in seen_blockchain_names:
            raise ValidationError(
                f"Duplicate blockchain name '{config.name}' detected.",
                config_section=f"blockchains[{index}]",
                config_key="name",
                value=config.name,
            )

        seen_blockchain_names.add(normalized_name)

        blockchains.append(config)

    return blockchains


def resolve_config_path(settings: AppSettings | None = None) -> Path:
    resolved_settings = settings or get_settings()

    return resolved_settings.config.resolve_config_path()


def _parse_blockchain_config(data: dict[str, Any], index: int) -> BlockchainConfig:
    """Parse a blockchain configuration entry from TOML data.

    Args:
        data: Dictionary containing blockchain configuration.
        index: One-based index of the blockchain entry (for error messages).

    Returns:
        Parsed BlockchainConfig instance.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    raw_name = data.get("name")

    name = _require_non_empty_string(raw_name, f"blockchains[{index}].name")

    raw_rpc_url = data.get("rpc_url")

    rpc_url = _require_non_empty_string(raw_rpc_url, f"blockchains[{index}].rpc_url")

    poll_interval = data.get("poll_interval")

    if poll_interval is not None:
        if not isinstance(poll_interval, str):
            raise ValidationError(
                f"blockchains[{index}].poll_interval must be a string if provided.",
                config_section=f"blockchains[{index}]",
                config_key="poll_interval",
                expected_type="string",
                value=type(poll_interval).__name__,
            )
        poll_interval = _validate_poll_interval(poll_interval, f"blockchains[{index}].poll_interval")

    contracts_data = data.get("contracts", [])

    if not isinstance(contracts_data, list):
        raise ValidationError(
            f"blockchains[{index}].contracts must be an array if provided.",
            config_section=f"blockchains[{index}]",
            config_key="contracts",
            expected_type="array",
            value=type(contracts_data).__name__,
        )

    accounts_data = data.get("accounts", [])

    if not isinstance(accounts_data, list):
        raise ValidationError(
            f"blockchains[{index}].accounts must be an array if provided.",
            config_section=f"blockchains[{index}]",
            config_key="accounts",
            expected_type="array",
            value=type(accounts_data).__name__,
        )

    contracts: list[ContractConfig] = []

    seen_contract_addresses: set[str] = set()

    for contract_index, contract_entry in enumerate(contracts_data, start=1):
        if not isinstance(contract_entry, dict):
            raise ValidationError(
                f"blockchains[{index}].contracts[{contract_index}] must be a table.",
                config_section=f"blockchains[{index}].contracts[{contract_index}]",
                expected_type="table",
                value=type(contract_entry).__name__,
            )

        contract = _parse_contract_config(contract_entry, index, contract_index)

        # Skip disabled contracts
        if not contract.enabled:
            continue

        normalized_address = contract.address.lower()

        if normalized_address in seen_contract_addresses:
            raise ValidationError(
                f"Duplicate contract address '{contract.address}' found in blockchains[{index}].",
                config_section=f"blockchains[{index}].contracts[{contract_index}]",
                config_key="address",
                value=contract.address,
            )

        seen_contract_addresses.add(normalized_address)

        contracts.append(contract)

    accounts: list[AccountConfig] = []

    seen_account_addresses: set[str] = set()

    for account_index, account_entry in enumerate(accounts_data, start=1):
        if not isinstance(account_entry, dict):
            raise ValidationError(
                f"blockchains[{index}].accounts[{account_index}] must be a table.",
                config_section=f"blockchains[{index}].accounts[{account_index}]",
                expected_type="table",
                value=type(account_entry).__name__,
            )

        account = _parse_account_config(account_entry, index, account_index)

        # Skip disabled accounts
        if not account.enabled:
            continue

        normalized_address = account.address.lower()

        if normalized_address in seen_account_addresses:
            raise ValidationError(
                f"Duplicate account address '{account.address}' found in blockchains[{index}].",
                config_section=f"blockchains[{index}].accounts[{account_index}]",
                config_key="address",
                value=account.address,
            )

        seen_account_addresses.add(normalized_address)

        accounts.append(account)

    raw_enabled = data.get("enabled")

    enabled = _coerce_optional_bool(
        raw_enabled,
        f"blockchains[{index}].enabled",
        default=True,
    )

    return BlockchainConfig(
        name=name,
        rpc_url=rpc_url,
        poll_interval=poll_interval,
        contracts=contracts,
        accounts=accounts,
        enabled=enabled,
    )


def _parse_account_config(data: dict[str, Any], blockchain_index: int, index: int) -> AccountConfig:
    """Parse an account configuration entry from TOML data.

    Args:
        data: Dictionary containing account configuration.
        blockchain_index: One-based index of the parent blockchain (for error messages).
        index: One-based index of the account entry (for error messages).

    Returns:
        Parsed AccountConfig instance.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    raw_name = data.get("name")

    name = _require_non_empty_string(
        raw_name,
        f"blockchains[{blockchain_index}].accounts[{index}].name",
    )

    raw_address = data.get("address")

    address_str = _require_non_empty_string(
        raw_address,
        f"blockchains[{blockchain_index}].accounts[{index}].address",
    )

    address = _validate_ethereum_address(
        address_str,
        f"blockchains[{blockchain_index}].accounts[{index}].address",
    )

    raw_enabled = data.get("enabled")

    enabled = _coerce_optional_bool(
        raw_enabled,
        f"blockchains[{blockchain_index}].accounts[{index}].enabled",
        default=True,
    )

    return AccountConfig(name=name, address=address, enabled=enabled)


def _parse_contract_config(
    data: dict[str, Any],
    blockchain_index: int,
    index: int,
) -> ContractConfig:
    """Parse a contract configuration entry from TOML data.

    Args:
        data: Dictionary containing contract configuration.
        blockchain_index: One-based index of the parent blockchain (for error messages).
        index: One-based index of the contract entry (for error messages).

    Returns:
        Parsed ContractConfig instance.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    raw_name = data.get("name")

    name = _require_non_empty_string(
        raw_name,
        f"blockchains[{blockchain_index}].contracts[{index}].name",
    )

    raw_address = data.get("address")

    address_str = _require_non_empty_string(
        raw_address,
        f"blockchains[{blockchain_index}].contracts[{index}].address",
    )

    address = _validate_ethereum_address(
        address_str,
        f"blockchains[{blockchain_index}].contracts[{index}].address",
    )

    raw_enabled = data.get("enabled")

    enabled = _coerce_optional_bool(
        raw_enabled,
        f"blockchains[{blockchain_index}].contracts[{index}].enabled",
        default=True,
    )

    decimals_value = data.get("decimals")

    decimals = _coerce_optional_int(
        decimals_value,
        f"blockchains[{blockchain_index}].contracts[{index}].decimals",
        allow_none=True,
        minimum=0,
    )

    transfer_lookback_value = data.get("transfer_lookback_blocks")

    transfer_lookback_blocks = _coerce_optional_int(
        transfer_lookback_value,
        f"blockchains[{blockchain_index}].contracts[{index}].transfer_lookback_blocks",
        allow_none=True,
        minimum=1,
    )

    accounts_data = data.get("accounts", [])

    if not isinstance(accounts_data, list):
        raise ValidationError(
            f"blockchains[{blockchain_index}].contracts[{index}].accounts must be an array if provided.",
            config_section=f"blockchains[{blockchain_index}].contracts[{index}]",
            config_key="accounts",
            expected_type="array",
            value=type(accounts_data).__name__,
        )

    accounts: list[ContractAccountConfig] = []

    seen_account_addresses: set[str] = set()

    for account_index, account_entry in enumerate(accounts_data, start=1):
        if not isinstance(account_entry, dict):
            section = f"blockchains[{blockchain_index}].contracts[{index}].accounts[{account_index}]"
            raise ValidationError(
                f"{section} must be a table.",
                config_section=section,
                expected_type="table",
                value=type(account_entry).__name__,
            )

        account = _parse_contract_account_config(
            account_entry,
            blockchain_index,
            index,
            account_index,
        )

        # Skip disabled contract accounts
        if not account.enabled:
            continue

        normalized_address = account.address.lower()

        if normalized_address in seen_account_addresses:
            section = f"blockchains[{blockchain_index}].contracts[{index}].accounts[{account_index}]"
            raise ValidationError(
                f"Duplicate contract account address '{account.address}' found in blockchains[{blockchain_index}].contracts[{index}].",
                config_section=section,
                config_key="address",
                value=account.address,
            )

        seen_account_addresses.add(normalized_address)

        accounts.append(account)

    return ContractConfig(
        name=name,
        address=address,
        decimals=decimals,
        accounts=accounts,
        transfer_lookback_blocks=transfer_lookback_blocks,
        enabled=enabled,
    )


def _parse_contract_account_config(
    data: dict[str, Any],
    blockchain_index: int,
    contract_index: int,
    index: int,
) -> ContractAccountConfig:
    """Parse a contract account configuration entry from TOML data.

    Args:
        data: Dictionary containing contract account configuration.
        blockchain_index: One-based index of the parent blockchain (for error messages).
        contract_index: One-based index of the parent contract (for error messages).
        index: One-based index of the contract account entry (for error messages).

    Returns:
        Parsed ContractAccountConfig instance.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    raw_name = data.get("name")

    name = _require_non_empty_string(
        raw_name,
        "blockchains[{blockchain}].contracts[{contract}].accounts[{account}].name".format(
            blockchain=blockchain_index,
            contract=contract_index,
            account=index,
        ),
    )

    raw_address = data.get("address")

    address_location = "blockchains[{blockchain}].contracts[{contract}].accounts[{account}].address".format(
        blockchain=blockchain_index,
        contract=contract_index,
        account=index,
    )

    address_str = _require_non_empty_string(
        raw_address,
        address_location,
    )

    address = _validate_ethereum_address(
        address_str,
        address_location,
    )

    raw_enabled = data.get("enabled")

    enabled = _coerce_optional_bool(
        raw_enabled,
        "blockchains[{blockchain}].contracts[{contract}].accounts[{account}].enabled".format(
            blockchain=blockchain_index,
            contract=contract_index,
            account=index,
        ),
        default=True,
    )

    return ContractAccountConfig(name=name, address=address, enabled=enabled)


def _read_toml(path: Path) -> dict[str, Any]:
    """Read and parse a TOML configuration file with environment variable expansion.

    Args:
        path: Path to the TOML file to read.

    Returns:
        Parsed TOML data as a dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
        tomllib.TOMLDecodeError: If the TOML is invalid.
    """
    with path.open("r", encoding="utf-8") as file:
        raw_toml = file.read()

    expanded_toml = os.path.expandvars(raw_toml)

    return tomllib.loads(expanded_toml)


def _require_non_empty_string(value: Any, location: str) -> str:
    """Validate that a value is a non-empty string.

    Args:
        value: Value to validate.
        location: Location string for error messages (e.g., "blockchains[0].name").

    Returns:
        Stripped string value.

    Raises:
        ValidationError: If the value is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            f"{location} must be a non-empty string.",
            config_section=location,
            expected_type="string",
            value=value if value is None or isinstance(value, str) else type(value).__name__,
        )

    return value.strip()


# Ethereum address format: 0x followed by 40 hex characters (42 characters total)
ETH_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _validate_ethereum_address(address: str, location: str) -> str:
    """Validate that a string is a valid Ethereum address format.

    Checks for:
    - Starts with '0x' prefix
    - Exactly 42 characters total (0x + 40 hex digits)
    - Contains only valid hexadecimal characters

    Note: This validates format only, not checksum validity (EIP-55).
    For checksum validation, use web3.py's `to_checksum_address()`.

    Args:
        address: Address string to validate.
        location: Location string for error messages (e.g., "blockchains[0].accounts[0].address").

    Returns:
        Normalized lowercase address string.

    Raises:
        ValidationError: If the address format is invalid.
    """
    normalized = address.strip().lower()

    if not ETH_ADDRESS_PATTERN.match(normalized):
        raise ValidationError(
            f"{location} must be a valid Ethereum address format (0x followed by 40 hex characters).",
            config_section=location,
            config_key="address",
            expected_type="ethereum_address",
            value=address,
        )

    return normalized


def _validate_poll_interval(interval: str, location: str) -> str:
    """Validate that a string is a valid poll interval format.

    Valid formats: 'N', 'Ns', 'Nm', 'Nh' where N is a positive integer.
    Case-insensitive for unit letters.

    Args:
        interval: Interval string to validate (e.g., "5m", "10s", "1h").
        location: Location string for error messages (e.g., "blockchains[0].poll_interval").

    Returns:
        Validated interval string.

    Raises:
        ValidationError: If the interval format is invalid.
    """
    from .poller.intervals import parse_duration_to_seconds

    if parse_duration_to_seconds(interval) is None:
        raise ValidationError(
            f"{location} must be a valid duration format (e.g., '5m', '10s', '1h'). Format: number optionally followed by unit (s/m/h).",
            config_section=location,
            config_key="poll_interval",
            expected_type="duration_string",
            value=interval,
        )

    return interval


def _coerce_optional_int(
    value: Any,
    location: str,
    *,
    allow_none: bool,
    minimum: int | None = None,
) -> int | None:
    """Coerce a value to an integer with optional validation.

    Args:
        value: Value to coerce to an integer.
        location: Location string for error messages (e.g., "blockchains[0].decimals").
        allow_none: If True, None values are allowed; if False, raises ValueError.
        minimum: Optional minimum value constraint.

    Returns:
        Coerced integer value, or None if allow_none is True and value is None.

    Raises:
        ValueError: If the value cannot be coerced, is a boolean, or violates constraints.
    """
    if value is None:
        if allow_none:
            return None

        raise ValidationError(
            f"{location} is required.",
            config_section=location,
            config_key=location.split(".")[-1] if "." in location else location,
        )

    if isinstance(value, bool):
        raise ValidationError(
            f"{location} must be an integer, not a boolean.",
            config_section=location,
            expected_type="integer",
            value=type(value).__name__,
        )

    try:
        coerced_value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"{location} must be an integer.",
            config_section=location,
            expected_type="integer",
            value=value,
        ) from exc

    if minimum is not None and coerced_value < minimum:
        raise ValidationError(
            f"{location} must be greater than or equal to {minimum}.",
            config_section=location,
            value=coerced_value,
            expected_type=f"integer >= {minimum}",
        )

    return coerced_value


def _coerce_optional_bool(value: Any, location: str, *, default: bool = True) -> bool:
    """Coerce a value to a boolean with optional default.

    Args:
        value: Value to coerce to a boolean.
        location: Location string for error messages (e.g., "blockchains[0].enabled").
        default: Default value if value is None or not provided.

    Returns:
        Coerced boolean value, or default if value is None.

    Raises:
        ValueError: If the value cannot be coerced to a boolean.
    """
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        value_lower = value.lower().strip()
        if value_lower in ("true", "1", "yes", "on"):
            return True
        if value_lower in ("false", "0", "no", "off"):
            return False

    raise ValidationError(
        f"{location} must be a boolean (true/false).",
        config_section=location,
        expected_type="boolean",
        value=value,
    )
