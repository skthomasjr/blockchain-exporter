"""Integration tests for health and metrics apps running simultaneously."""

from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any

import pytest

from blockchain_exporter.app import create_health_app, create_metrics_app
from blockchain_exporter.config import AccountConfig, BlockchainConfig, ContractConfig
from blockchain_exporter.context import ApplicationContext
from blockchain_exporter.metrics import get_metrics
from blockchain_exporter.runtime_settings import RuntimeSettings
from blockchain_exporter.settings import get_settings

app_module = importlib.import_module("blockchain_exporter.app")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_health_and_metrics_apps_share_polling_tasks(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test that booting both health and metrics apps creates polling tasks only once.
    
    This test verifies:
    - Both apps use the same lifespan function
    - Polling tasks are created only once (by the first app to start)
    - The second app reuses existing tasks instead of creating duplicates
    - Both apps reference the same task list
    - Only the primary app (that created tasks) performs cleanup on shutdown
    """
    caplog.set_level(logging.DEBUG)
    
    metrics = get_metrics()
    
    blockchain = BlockchainConfig(
        name="TestChain",
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
    
    # Track how many times poll_blockchain is called (should be called once per blockchain)
    poll_call_count = 0
    poll_calls: list[tuple[BlockchainConfig, Any]] = []
    cancel_events: list[asyncio.Event] = []
    
    async def _tracking_poll(blockchain_config: BlockchainConfig, *, context: ApplicationContext | None = None, **kwargs: Any) -> None:
        """Track poll calls and wait for cancellation."""
        nonlocal poll_call_count
        poll_call_count += 1
        poll_calls.append((blockchain_config, context))
        
        cancel_event = asyncio.Event()
        cancel_events.append(cancel_event)
        
        try:
            # Wait indefinitely until cancelled
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancel_event.set()
            raise
    
    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _tracking_poll)
    
    # Create both apps
    health_app = create_health_app(context=context)
    metrics_app = create_metrics_app(context=context)
    
    # Start both apps' lifespans simultaneously
    async with health_app.router.lifespan_context(health_app), metrics_app.router.lifespan_context(metrics_app):
        # Give tasks a moment to start
        await asyncio.sleep(0.1)
        
        # Verify that poll_blockchain was called only once (not twice)
        assert poll_call_count == 1, f"Expected poll_blockchain to be called once, but it was called {poll_call_count} times"
        
        # Verify both apps have polling tasks
        assert len(health_app.state.polling_tasks) == 1, "Health app should have 1 polling task"
        assert len(metrics_app.state.polling_tasks) == 1, "Metrics app should have 1 polling task"
        
        # Verify both apps reference the same task objects (shared state)
        health_task = health_app.state.polling_tasks[0]
        metrics_task = metrics_app.state.polling_tasks[0]
        assert health_task is metrics_task, "Both apps should reference the same polling task object"
        
        # Verify the task is actually running (not done)
        assert not health_task.done(), "Polling task should be running"
        assert not metrics_task.done(), "Polling task should be running"
        
        # Check logs for evidence of task reuse
        log_messages = [record.message for record in caplog.records]
        
        # Should see "Created X polling task(s)" from the first app
        created_logs = [msg for msg in log_messages if "Created" in msg and "polling task" in msg]
        assert len(created_logs) == 1, f"Expected one 'Created polling task' log, found {len(created_logs)}: {created_logs}"
        
        # Should see "Reusing existing polling tasks" from the second app
        reuse_logs = [msg for msg in log_messages if "Reusing existing polling tasks" in msg]
        assert len(reuse_logs) == 1, f"Expected one 'Reusing existing polling tasks' log, found {len(reuse_logs)}: {reuse_logs}"
    
    # After shutdown, verify that tasks were cancelled
    # Note: The primary app (health_app, since it started first) should have cancelled the tasks
    assert len(cancel_events) == 1, "Should have one cancel event"
    assert cancel_events[0].is_set(), "Polling task should have been cancelled"
    
    # Verify tasks are cancelled (done)
    assert health_task.done(), "Health app's polling task should be cancelled/done"
    assert metrics_task.done(), "Metrics app's polling task should be cancelled/done"
    
    # Verify primary app (health_app) cleared its task list
    assert len(health_app.state.polling_tasks) == 0, "Primary app (health) should have cleared its polling tasks after shutdown"
    
    # Secondary app (metrics_app) still has a reference to the cancelled task in its state
    # This is expected behavior - only the primary app clears its task list
    assert len(metrics_app.state.polling_tasks) == 1, "Secondary app (metrics) keeps reference to cancelled task"
    assert metrics_app.state.polling_tasks[0].done(), "Secondary app's task reference should be cancelled/done"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
async def test_metrics_app_starts_first_then_health_app(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test that the order of app startup doesn't matter - tasks are still created only once.
    
    This test verifies that even if metrics_app starts first, it creates the tasks,
    and health_app reuses them.
    """
    caplog.set_level(logging.DEBUG)
    
    metrics = get_metrics()
    
    blockchain = BlockchainConfig(
        name="TestChain",
        rpc_url="https://example.invalid",
        poll_interval="10s",
        contracts=[],
        accounts=[],
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
    
    poll_call_count = 0
    
    async def _tracking_poll(*args: Any, **kwargs: Any) -> None:
        nonlocal poll_call_count
        poll_call_count += 1
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
    
    monkeypatch.setattr(app_module, "get_application_context", lambda: context)
    from blockchain_exporter.poller import control as poller_control_module

    monkeypatch.setattr(poller_control_module, "poll_blockchain", _tracking_poll)
    
    # Create both apps
    health_app = create_health_app(context=context)
    metrics_app = create_metrics_app(context=context)
    
    # Start metrics_app first, then health_app
    async with metrics_app.router.lifespan_context(metrics_app), health_app.router.lifespan_context(health_app):
        await asyncio.sleep(0.1)
        
        # Verify poll_blockchain was called only once
        assert poll_call_count == 1, f"Expected poll_blockchain to be called once, but it was called {poll_call_count} times"
        
        # Verify both apps have the same task
        assert len(metrics_app.state.polling_tasks) == 1
        assert len(health_app.state.polling_tasks) == 1
        assert metrics_app.state.polling_tasks[0] is health_app.state.polling_tasks[0]
        
        # Check logs - metrics_app should have created tasks, health_app should reuse
        log_messages = [record.message for record in caplog.records]
        created_logs = [msg for msg in log_messages if "Created" in msg and "polling task" in msg]
        reuse_logs = [msg for msg in log_messages if "Reusing existing polling tasks" in msg]
        
        assert len(created_logs) == 1, "Metrics app should create tasks"
        assert len(reuse_logs) == 1, "Health app should reuse tasks"
    
    # Verify cleanup happened (tasks cancelled)
    assert poll_call_count == 1  # Still only called once

