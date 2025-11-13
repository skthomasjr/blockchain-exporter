from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .settings import AppSettings, get_settings

DEFAULT_ENV_PATH = Path.cwd().joinpath(".env").resolve()

load_dotenv(DEFAULT_ENV_PATH)


@dataclass(frozen=True, slots=True)
class AccountConfig:
    name: str

    address: str


@dataclass(frozen=True, slots=True)
class ContractConfig:
    name: str

    address: str

    decimals: int | None

    accounts: list["ContractAccountConfig"]

    transfer_lookback_blocks: int | None


@dataclass(frozen=True, slots=True)
class ContractAccountConfig:
    name: str

    address: str


@dataclass(frozen=True, slots=True)
class BlockchainConfig:
    name: str

    rpc_url: str

    poll_interval: str | None

    contracts: list["ContractConfig"]

    accounts: list[AccountConfig]


def load_blockchain_configs(path: Path | None = None) -> list[BlockchainConfig]:
    config_path = path or resolve_config_path()

    data = _read_toml(config_path)

    blockchains_data = data.get("blockchains")

    if blockchains_data is None:
        return []

    if not isinstance(blockchains_data, list):
        raise ValueError("Configuration 'blockchains' section must be an array.")

    if not blockchains_data:
        return []

    seen_blockchain_names: set[str] = set()

    blockchains: list[BlockchainConfig] = []

    for index, entry in enumerate(blockchains_data, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Blockchains[{index}] must be a table.")

        config = _parse_blockchain_config(entry, index)

        normalized_name = config.name.lower()

        if normalized_name in seen_blockchain_names:
            raise ValueError(f"Duplicate blockchain name '{config.name}' detected.")

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

    if poll_interval is not None and not isinstance(poll_interval, str):
        raise ValueError(f"blockchains[{index}].poll_interval must be a string if provided.")

    contracts_data = data.get("contracts", [])

    if not isinstance(contracts_data, list):
        raise ValueError(f"blockchains[{index}].contracts must be an array if provided.")

    accounts_data = data.get("accounts", [])

    if not isinstance(accounts_data, list):
        raise ValueError(f"blockchains[{index}].accounts must be an array if provided.")

    contracts: list[ContractConfig] = []

    seen_contract_addresses: set[str] = set()

    for contract_index, contract_entry in enumerate(contracts_data, start=1):
        if not isinstance(contract_entry, dict):
            raise ValueError(
                f"blockchains[{index}].contracts[{contract_index}] must be a table."
            )

        contract = _parse_contract_config(contract_entry, index, contract_index)

        normalized_address = contract.address.lower()

        if normalized_address in seen_contract_addresses:
            raise ValueError(
                f"Duplicate contract address '{contract.address}' found in blockchains[{index}]."
            )

        seen_contract_addresses.add(normalized_address)

        contracts.append(contract)

    accounts: list[AccountConfig] = []

    seen_account_addresses: set[str] = set()

    for account_index, account_entry in enumerate(accounts_data, start=1):
        if not isinstance(account_entry, dict):
            raise ValueError(
                f"blockchains[{index}].accounts[{account_index}] must be a table."
            )

        account = _parse_account_config(account_entry, index, account_index)

        normalized_address = account.address.lower()

        if normalized_address in seen_account_addresses:
            raise ValueError(
                f"Duplicate account address '{account.address}' found in blockchains[{index}]."
            )

        seen_account_addresses.add(normalized_address)

        accounts.append(account)

    return BlockchainConfig(
        name=name,
        rpc_url=rpc_url,
        poll_interval=poll_interval,
        contracts=contracts,
        accounts=accounts,
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

    address = _require_non_empty_string(
        raw_address,
        f"blockchains[{blockchain_index}].accounts[{index}].address",
    )

    return AccountConfig(name=name, address=address)


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

    address = _require_non_empty_string(
        raw_address,
        f"blockchains[{blockchain_index}].contracts[{index}].address",
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
        raise ValueError(
            f"blockchains[{blockchain_index}].contracts[{index}].accounts must be an array if provided."
        )

    accounts: list[ContractAccountConfig] = []

    seen_account_addresses: set[str] = set()

    for account_index, account_entry in enumerate(accounts_data, start=1):
        if not isinstance(account_entry, dict):
            raise ValueError(
                "blockchains[{blockchain}].contracts[{contract}].accounts[{account}] must be a table.".format(
                    blockchain=blockchain_index,
                    contract=index,
                    account=account_index,
                )
            )

        account = _parse_contract_account_config(
            account_entry,
            blockchain_index,
            index,
            account_index,
        )

        normalized_address = account.address.lower()

        if normalized_address in seen_account_addresses:
            raise ValueError(
                "Duplicate contract account address '{address}' found in blockchains[{blockchain}].contracts[{contract}]".format(
                    address=account.address,
                    blockchain=blockchain_index,
                    contract=index,
                )
            )

        seen_account_addresses.add(normalized_address)

        accounts.append(account)

    return ContractConfig(
        name=name,
        address=address,
        decimals=decimals,
        accounts=accounts,
        transfer_lookback_blocks=transfer_lookback_blocks,
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

    address = _require_non_empty_string(
        raw_address,
        "blockchains[{blockchain}].contracts[{contract}].accounts[{account}].address".format(
            blockchain=blockchain_index,
            contract=contract_index,
            account=index,
        ),
    )

    return ContractAccountConfig(name=name, address=address)


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
        ValueError: If the value is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} must be a non-empty string.")

    return value.strip()


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

        raise ValueError(f"{location} is required.")

    if isinstance(value, bool):
        raise ValueError(f"{location} must be an integer, not a boolean.")

    try:
        coerced_value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{location} must be an integer.") from exc

    if minimum is not None and coerced_value < minimum:
        raise ValueError(
            f"{location} must be greater than or equal to {minimum}."
        )

    return coerced_value

