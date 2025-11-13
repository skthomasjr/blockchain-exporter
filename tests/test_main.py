from __future__ import annotations

from typing import Any

import pytest
import uvicorn

import blockchain_exporter.main as main_module


def test_main_run_invokes_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that run() creates and starts both health and metrics servers."""
    captured_configs: list[dict[str, Any]] = []

    async def _fake_serve(self: Any) -> None:
        """Mock Server.serve() to return immediately without starting servers."""
        # Return immediately to avoid actually binding to ports
        return

    original_server_init = uvicorn.Server.__init__

    def _capturing_server_init(self: Any, config: uvicorn.Config) -> None:
        """Capture server configs during Server initialization."""
        captured_configs.append({
            "app": config.app,
            "host": config.host,
            "port": config.port,
            "log_config": config.log_config,
        })
        # Call original __init__ to properly initialize the Server object
        original_server_init(self, config)

    monkeypatch.setattr(uvicorn.Server, "__init__", _capturing_server_init)
    monkeypatch.setattr(uvicorn.Server, "serve", _fake_serve)

    # Mock asyncio.run to actually execute the coroutine but with mocked servers
    async def _run_servers_mocked() -> None:
        """Execute run_servers() with mocked Server.serve()."""
        await main_module.run_servers()

    import asyncio

    # Run the coroutine with a timeout to prevent hanging
    try:
        asyncio.run(asyncio.wait_for(_run_servers_mocked(), timeout=0.1))
    except asyncio.TimeoutError:
        # Expected - servers would run forever, but we've captured the configs
        pass

    assert len(captured_configs) == 2, f"Should create two servers (health and metrics), got {len(captured_configs)}"

    # Find health and metrics configs
    health_config = next((c for c in captured_configs if c["port"] == main_module.SETTINGS.server.health_port), None)
    metrics_config = next((c for c in captured_configs if c["port"] == main_module.SETTINGS.server.metrics_port), None)

    assert health_config is not None, "Health server should be created"
    assert metrics_config is not None, "Metrics server should be created"

    assert health_config["host"] == "0.0.0.0"
    assert health_config["port"] == main_module.SETTINGS.server.health_port
    assert health_config["log_config"] is None

    assert metrics_config["host"] == "0.0.0.0"
    assert metrics_config["port"] == main_module.SETTINGS.server.metrics_port
    assert metrics_config["log_config"] is None

