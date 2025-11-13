"""Command-line helpers for blockchain exporter tooling."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .config import load_blockchain_configs
from .runtime_settings import RuntimeSettings, get_runtime_settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate blockchain-exporter configuration files.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Path to config.toml (defaults to BLOCKCHAIN_EXPORTER_CONFIG_PATH or ./config.toml).",
    )
    parser.add_argument(
        "--print-resolved",
        action="store_true",
        help="Output the resolved runtime settings (with secrets masked by default).",
    )
    parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="Include sensitive values such as RPC URLs when printing the resolved configuration.",
    )
    return parser


def _load_configs(config_path: Path | None) -> list[Any]:
    return load_blockchain_configs(config_path)


def validate_config(config_path: str | None = None) -> None:
    """Load and validate configuration, matching the legacy public API."""

    path = Path(config_path).expanduser().resolve() if config_path else None
    _load_configs(path)


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serialize(val) for key, val in asdict(value).items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(val) for key, val in value.items()}
    return value


def _render_runtime_settings(runtime: RuntimeSettings, *, show_secrets: bool) -> str:
    blockchains = []
    for chain in runtime.blockchains:
        chain_dict = _serialize(chain)
        if not show_secrets and "rpc_url" in chain_dict:
            chain_dict["rpc_url"] = "<masked>"
        blockchains.append(chain_dict)

    payload = {
        "config_path": str(runtime.config_path),
        "settings": _serialize(runtime.app),
        "blockchains": blockchains,
    }

    return json.dumps(payload, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by Poetry scripts."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config_path).expanduser().resolve() if args.config_path else None

    try:
        if args.print_resolved:
            runtime = get_runtime_settings(config_path=config_path)
            print(_render_runtime_settings(runtime, show_secrets=args.show_secrets))
            return 0

        _load_configs(config_path)
    except FileNotFoundError as exc:
        parser.error(f"Config file not found: {exc}")
    except ValueError as exc:
        parser.error(str(exc))

    print("Configuration OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
