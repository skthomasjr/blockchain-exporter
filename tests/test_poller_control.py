from __future__ import annotations

import asyncio
import importlib
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from blockchain_exporter.config import BlockchainConfig

control_module = importlib.import_module("blockchain_exporter.poller.control")


def _build_blockchain(name: str = "TestChain") -> BlockchainConfig:
    return BlockchainConfig(
        name=name,
        rpc_url="https://rpc.example",
        poll_interval="1m",
        contracts=[],
        accounts=[],
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_blockchain_failure_backoff_and_logging(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    blockchain = _build_blockchain()

    context = SimpleNamespace(metrics=SimpleNamespace(), create_rpc_client=lambda _: None)

    sleep_calls: list[float] = []
    failure_calls: list[BlockchainConfig] = []
    call_count = 0

    async def _collect(*args: Any, **kwargs: Any) -> bool:
        nonlocal call_count

        call_count += 1

        if call_count >= 3:
            raise asyncio.CancelledError

        return False

    async def _sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr(control_module, "determine_poll_interval_seconds", lambda _bc: 1)
    monkeypatch.setattr(control_module, "collect_blockchain_metrics", _collect)
    monkeypatch.setattr(control_module.asyncio, "sleep", _sleep)
    monkeypatch.setattr(control_module, "record_poll_failure", lambda bc: failure_calls.append(bc))

    caplog.set_level(logging.DEBUG)

    with pytest.raises(asyncio.CancelledError):
        await control_module.poll_blockchain(blockchain, context=context)

    assert len(sleep_calls) == 2
    assert sleep_calls == pytest.approx([1, 2], rel=0.05)
    assert failure_calls == []

    messages = caplog.messages

    assert any("Polling TestChain every 1 seconds." in message for message in messages)
    assert any("Backing off 1.00 seconds before next poll" in message for message in messages)
    assert any("Backing off 2.00 seconds before next poll" in message for message in messages)
    assert any("Polling task for TestChain cancelled." in message for message in messages)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_poll_blockchain_logs_cancellation(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    blockchain = _build_blockchain("CancelChain")

    context = SimpleNamespace(metrics=SimpleNamespace(), create_rpc_client=lambda _: None)

    async def _collect(*args: Any, **kwargs: Any) -> bool:
        raise asyncio.CancelledError

    monkeypatch.setattr(control_module, "determine_poll_interval_seconds", lambda _bc: 1)
    monkeypatch.setattr(control_module, "collect_blockchain_metrics", _collect)

    caplog.set_level(logging.DEBUG)

    with pytest.raises(asyncio.CancelledError):
        await control_module.poll_blockchain(blockchain, context=context)

    messages = caplog.messages

    assert any("Polling task for CancelChain cancelled." in message for message in messages)

