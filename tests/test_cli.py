from pathlib import Path

import pytest

from blockchain_exporter.cli import main, validate_config


def write_config(path: Path, content: str) -> Path:
    config_file = path.joinpath("config.toml")
    config_file.write_text(content, encoding="utf-8")
    return config_file


def test_validate_config_success(tmp_path: Path) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Mainnet"
        rpc_url = "https://example.com"
        """,
    )

    validate_config(str(config_file))


def test_validate_config_allows_missing_blockchains(tmp_path: Path, capsys) -> None:
    config_file = write_config(tmp_path, "[foo]\nbar = 'baz'\n")

    exit_code = main(["--config", str(config_file)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Configuration OK" in captured.out


def test_print_runtime_settings_masks_rpc(tmp_path: Path, capsys) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Masked Chain"
        rpc_url = "https://secret.example"
        """,
    )

    exit_code = main(["--config", str(config_file), "--print-resolved"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert '"rpc_url": "<masked>"' in captured.out
    assert '"config_path":' in captured.out


def test_print_runtime_settings_can_show_secrets(tmp_path: Path, capsys) -> None:
    config_file = write_config(
        tmp_path,
        """
        [[blockchains]]
        name = "Visible Chain"
        rpc_url = "https://visible.example"
        """,
    )

    exit_code = main(
        [
            "--config",
            str(config_file),
            "--print-resolved",
            "--show-secrets",
        ]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "https://visible.example" in captured.out


def test_print_resolved_errors_when_config_missing(tmp_path: Path, capsys) -> None:
    missing_path = tmp_path.joinpath("absent.toml")

    with pytest.raises(SystemExit):
        main(["--config", str(missing_path), "--print-resolved"])

    captured = capsys.readouterr()

    assert "Config file not found" in captured.err


def test_print_resolved_reports_validation_errors(tmp_path: Path, capsys) -> None:
    invalid_config = write_config(
        tmp_path,
        """
        [blockchains]
        name = "InvalidChain"
        """,
    )

    with pytest.raises(SystemExit):
        main(["--config", str(invalid_config), "--print-resolved"])

    captured = capsys.readouterr()

    assert "blockchains" in captured.err
