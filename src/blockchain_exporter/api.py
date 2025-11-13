"""HTTP API surface for the blockchain exporter."""

from __future__ import annotations

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .health import (
    format_metrics_payload,
    generate_health_report,
    generate_readiness_report,
)
from .metrics import get_metrics


def register_health_routes(app: FastAPI) -> None:
    """Register health check endpoints on the health port (8080).
    
    Registers the following endpoints:
    - GET /health: Overall health status with chain details
    - GET /health/details: Detailed health report
    - GET /health/livez: Liveness probe (always returns 200)
    - GET /health/readyz: Readiness probe (returns 200 if ready, 503 if not)
    """
    @app.get("/health", response_class=JSONResponse)
    async def health() -> JSONResponse:
        overall_status, status_code, chain_details = generate_health_report()

        return JSONResponse(
            status_code=status_code,
            content={
                "status": overall_status,
                "chains": chain_details,
            },
        )

    @app.get("/health/details", response_class=JSONResponse)
    async def health_details() -> JSONResponse:
        overall_status, status_code, chain_details = generate_health_report(
            include_details=True
        )

        return JSONResponse(
            status_code=status_code,
            content={
                "status": overall_status,
                "chains": chain_details,
            },
        )

    @app.get("/health/livez", response_class=JSONResponse)
    async def livez() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "alive"},
        )

    @app.get("/health/readyz", response_class=JSONResponse)
    async def readyz() -> JSONResponse:
        ready, readiness_details = generate_readiness_report()

        status_code = (
            status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
        )

        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if ready else "not_ready",
                "chains": readiness_details,
            },
        )


def register_metrics_routes(app: FastAPI) -> None:
    """Register metrics endpoint on the metrics port (9100).
    
    Registers:
    - GET /metrics: Prometheus metrics endpoint (always returns 200)
    """
    @app.get("/metrics", response_class=Response)
    async def metrics() -> Response:
        # Always return metrics (including 'up' and 'configured_blockchains').
        # Readiness can be checked via /health/readyz endpoint.
        metric_data = generate_latest(get_metrics().registry)
        formatted_payload = format_metrics_payload(metric_data)

        return Response(content=formatted_payload, media_type=CONTENT_TYPE_LATEST)


def register_routes(app: FastAPI) -> None:
    """Register all routes (for backward compatibility).
    
    This function registers both health and metrics routes on a single app.
    For dual-port deployments, use register_health_routes() and register_metrics_routes()
    separately on different FastAPI instances.
    """
    register_health_routes(app)
    register_metrics_routes(app)


__all__ = [
    "register_health_routes",
    "register_metrics_routes",
    "register_routes",
]
