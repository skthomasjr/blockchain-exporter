import logging
import sys

import pytest

from blockchain_exporter import metrics
from blockchain_exporter.config import BlockchainConfig, ContractConfig
from blockchain_exporter.logging import (
    JsonFormatter,
    StructuredTextFormatter,
    build_log_extra,
    extract_log_context,
    log_duration,
)


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()

        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_build_log_extra_includes_structured_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    blockchain = BlockchainConfig(
        name="Ethereum",
        rpc_url="https://rpc.example",
        poll_interval=None,
        contracts=[],
        accounts=[],
    )

    contract = ContractConfig(
        name="USDC",
        address="0x0000000000000000000000000000000000000000",
        decimals=6,
        accounts=[],
        transfer_lookback_blocks=None,
    )

    key = (blockchain.name, blockchain.rpc_url)

    monkeypatch.setitem(metrics.CHAIN_RESOLVED_IDS, key, "eth-mainnet")

    extra = build_log_extra(
        blockchain=blockchain,
        contract=contract,
        account_name="Treasury",
        account_address="0xabc",
        elapsed=1.2345,
        additional={"operation": "collect"},
    )

    assert extra["blockchain"] == "Ethereum"

    assert extra["chain_id"] == "eth-mainnet"

    assert extra["contract_name"] == "USDC"

    assert extra["contract_address"] == "0x0000000000000000000000000000000000000000"

    assert extra["account_name"] == "Treasury"

    assert extra["account_address"] == "0xabc"

    assert extra["operation"] == "collect"

    expected_elapsed = round(1.2345, 3)

    assert extra["elapsed_seconds"] == expected_elapsed


def test_build_log_extra_excludes_unknown_chain_id() -> None:
    """Test that chain_id is excluded from logs when it's 'unknown'."""
    blockchain = BlockchainConfig(
        name="Ethereum",
        rpc_url="https://rpc.example",
        poll_interval=None,
        contracts=[],
        accounts=[],
    )

    # No chain_id in cache, so it should resolve to "unknown" and be excluded
    extra = build_log_extra(blockchain=blockchain)

    assert extra["blockchain"] == "Ethereum"

    assert "chain_id" not in extra


def test_log_duration_records_elapsed_time() -> None:
    handler = ListHandler()

    logger = logging.getLogger("blockchain_exporter.tests.logging")

    logger.setLevel(logging.DEBUG)

    logger.addHandler(handler)

    try:
        with log_duration(
            logger,
            "collecting metrics",
            level=logging.INFO,
            extra={"stage": "collect"},
        ):
            pass
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1

    record = handler.records[0]

    assert record.levelno == logging.INFO

    assert record.getMessage() == "collecting metrics"

    context = extract_log_context(record)

    assert context["stage"] == "collect"

    assert context["elapsed_seconds"] >= 0


def test_extract_log_context_ignores_color_message() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="Started server process",
        args=(),
        exc_info=None,
    )
    record.color_message = "Started server process [1234]"  # type: ignore[attr-defined]

    context = extract_log_context(record)

    assert "color_message" not in context


def test_structured_formatter_applies_color_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    formatter = StructuredTextFormatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="Started server process [%d]",
        args=(1234,),
        exc_info=None,
    )
    record.color_message = "Started \033[32mserver\033[0m process [%d]"  # type: ignore[attr-defined]
    record.levelcolor = "\033[32m"  # type: ignore[attr-defined]

    formatted = formatter.format(record)

    assert "\033[36m" in formatted  # cyan timestamp
    assert "\033[32mINFO\033[0m" in formatted
    assert "[1234]" in formatted

    record_no_color = logging.LogRecord(
        name="uvicorn.error",
        level=logging.WARNING,
        pathname=__file__,
        lineno=0,
        msg="Reloading application",
        args=(),
        exc_info=None,
    )

    formatted_no_color = formatter.format(record_no_color)

    assert "\033[33mWARNING\033[0m" in formatted_no_color


def test_structured_formatter_can_disable_colors(monkeypatch: pytest.MonkeyPatch) -> None:
    formatter = StructuredTextFormatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        color_enabled=False,
    )

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="Started server process",
        args=(),
        exc_info=None,
    )
    record.color_message = "Started \033[32mserver\033[0m process"  # type: ignore[attr-defined]

    formatted = formatter.format(record)

    assert "\033" not in formatted
    assert "Started server process" in formatted


def test_json_formatter_serializes_color_message_and_context(monkeypatch: pytest.MonkeyPatch) -> None:
    formatter = JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S")

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="Started server process [%d]",
        args=(4321,),
        exc_info=None,
    )
    record.color_message = "Started \033[32mserver\033[0m process [%d]"  # type: ignore[attr-defined]
    record.some_context = "value"  # type: ignore[attr-defined]

    payload = formatter.format(record)

    assert '"logger": "uvicorn.error"' in payload
    assert '"message": "Started server process [4321]"' in payload
    assert '"color_message": "Started \\u001b[32mserver\\u001b[0m process [4321]"' in payload
    assert '"some_context": "value"' in payload


def test_json_formatter_serializes_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    formatter = JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S")

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord(
            name="uvicorn.error",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="Failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = formatter.format(record)

    assert '"level": "ERROR"' in payload
    assert '"exc_info":' in payload
    assert "RuntimeError: boom" in payload
