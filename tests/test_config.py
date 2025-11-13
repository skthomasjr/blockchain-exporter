from pathlib import Path

import pytest

from blockchain_exporter.config import load_blockchain_configs


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

    with pytest.raises(ValueError, match="Duplicate blockchain name"):
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

    with pytest.raises(ValueError, match="must be a table"):
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
        ValueError,
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
        ValueError,
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

    with pytest.raises(ValueError, match="accounts must be an array"):
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

    with pytest.raises(ValueError, match="accounts\\[1\\] must be a table"):
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

    with pytest.raises(ValueError, match="Duplicate contract account address"):
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

    with pytest.raises(ValueError, match="must be a non-empty string"):
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
