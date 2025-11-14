from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from blockchain_exporter.app import _configure_logging, _lifespan
from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.logging import JsonFormatter, StructuredTextFormatter
from blockchain_exporter.metrics import get_metrics
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import AppSettings, LoggingSettings, get_settings

app_module = importlib.import_module("blockchain_exporter.app")


def _build_settings(level: str, log_format: str) -> AppSettings:
    base_settings = get_settings()

    return replace(
        base_settings,
        logging=LoggingSettings(
            level=level,
            format=log_format,
            color_enabled=base_settings.logging.color_enabled,
        ),
    )


def test_configure_logging_uses_json_formatter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_config: dict[str, Any] = {}

    def _capture_config(config: dict[str, Any]) -> None:
        captured_config["value"] = config

    monkeypatch.setattr(logging.config, "dictConfig", _capture_config)

    settings = _build_settings(level="INFO", log_format="json")

    _configure_logging(settings)

    assert "value" in captured_config

    formatter_config = captured_config["value"]["formatters"]["standard"]

    assert formatter_config["()"] is JsonFormatter
    assert captured_config["value"]["root"]["level"] == "INFO"
    uvicorn_logger = captured_config["value"]["loggers"]["uvicorn"]
    assert uvicorn_logger["handlers"] == ["default"]
    assert uvicorn_logger["propagate"] is False


def test_configure_logging_invalid_level_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_config: dict[str, Any] = {}

    def _capture_config(config: dict[str, Any]) -> None:
        captured_config["value"] = config

    monkeypatch.setattr(logging.config, "dictConfig", _capture_config)

    settings = _build_settings(level="not-a-level", log_format="text")

    _configure_logging(settings)

    assert "value" in captured_config

    formatter_config = captured_config["value"]["formatters"]["standard"]

    assert formatter_config["()"] is StructuredTextFormatter
    assert captured_config["value"]["root"]["level"] == "INFO"
    access_logger = captured_config["value"]["loggers"]["uvicorn.access"]
    assert access_logger["handlers"] == ["default"]
    assert access_logger["propagate"] is False
    assert formatter_config["color_enabled"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_lifespan_handles_missing_config(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)

    fake_path = Path("/tmp/missing-config.toml")

    monkeypatch.setattr(
        app_module,
        "get_application_context",
        lambda: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(
        app_module,
        "resolve_config_path",
        lambda _settings: fake_path,
    )

    async def _no_op_poll(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0)

    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _no_op_poll)

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        context = app.state.context

        assert context is not None
        assert app.state.blockchain_configs == []

    warning_messages = [record.message for record in caplog.records]

    assert any(
        f"Configuration file not found at {fake_path}" in message
        for message in warning_messages
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_lifespan_starts_polling_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that lifespan starts polling tasks in the background."""
    metrics = get_metrics()

    blockchain = BlockchainConfig(
        name="SampleChain",
        rpc_url="https://example.invalid",
        poll_interval="10s",
        contracts=[
            ContractConfig(
                name="Token",
                address="0x0000000000000000000000000000000000000010",
                decimals=None,
                accounts=[],
                transfer_lookback_blocks=None,
            )
        ],
        accounts=[
            AccountConfig(
                name="Treasury",
                address="0x0000000000000000000000000000000000000005",
            )
        ],
    )

    runtime = RuntimeSettings(
        app=get_settings(),
        blockchains=[blockchain],
        config_path=Path("config.toml"),
    )

    context = ApplicationContext(
        metrics=metrics,
        runtime=runtime,
        rpc_factory=lambda _: None,
    )

    cancel_event = asyncio.Event()

    async def _waiting_poll(*args: Any, **kwargs: Any) -> None:
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancel_event.set()
            raise

    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _waiting_poll)

    app = FastAPI(lifespan=_lifespan)

    async with app.router.lifespan_context(app):
        # Verify that polling tasks were started
        assert len(app.state.polling_tasks) == 1
        # Give the task a moment to start
        await asyncio.sleep(0.1)

    # Verify that tasks were cancelled on shutdown
    assert cancel_event.is_set()
    assert len(app.state.polling_tasks) == 0

