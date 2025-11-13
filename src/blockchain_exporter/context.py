"""Runtime dependency container for wiring metrics, configs, and RPC factories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .config import BlockchainConfig
from .metrics import MetricsStoreProtocol, get_metrics
from .rpc import RpcClient, RpcClientProtocol
from .runtime_settings import RuntimeSettings, get_runtime_settings
from .settings import AppSettings


@dataclass(slots=True)
class ApplicationContext:
    """Bundle of services required while the exporter is running."""

    metrics: MetricsStoreProtocol

    runtime: RuntimeSettings

    rpc_factory: Callable[[BlockchainConfig], RpcClientProtocol]

    def create_rpc_client(self, blockchain: BlockchainConfig) -> RpcClientProtocol:
        """Construct an RPC client for the provided blockchain configuration."""

        return self.rpc_factory(blockchain)

    @property
    def settings(self) -> AppSettings:
        """Return resolved environment-driven application settings."""

        return self.runtime.app

    @property
    def blockchains(self) -> list[BlockchainConfig]:
        """Expose configured blockchain definitions."""

        return self.runtime.blockchains


def default_rpc_factory(blockchain: BlockchainConfig) -> RpcClientProtocol:
    """Create a retry-enabled `RpcClient` for the given blockchain."""

    from .poller.intervals import create_web3_client

    web3_client = create_web3_client(blockchain)
    return RpcClient(web3_client, blockchain)


def create_default_context() -> ApplicationContext:
    """Build an application context using the configured blockchains and metrics."""

    runtime_settings = get_runtime_settings()

    return ApplicationContext(
        metrics=get_metrics(),
        runtime=runtime_settings,
        rpc_factory=default_rpc_factory,
    )


_APPLICATION_CONTEXT: ApplicationContext | None = None


def get_application_context() -> ApplicationContext:
    """Return the current application context, creating one when absent."""

    global _APPLICATION_CONTEXT

    if _APPLICATION_CONTEXT is None:
        _APPLICATION_CONTEXT = create_default_context()

    return _APPLICATION_CONTEXT


def set_application_context(context: ApplicationContext | None) -> None:
    """Replace the globally cached application context."""

    global _APPLICATION_CONTEXT

    _APPLICATION_CONTEXT = context


def reset_application_context() -> None:
    """Clear the cached context so the next access rebuilds dependencies."""

    set_application_context(None)


__all__ = [
    "ApplicationContext",
    "create_default_context",
    "default_rpc_factory",
    "get_application_context",
    "reset_application_context",
    "set_application_context",
]
