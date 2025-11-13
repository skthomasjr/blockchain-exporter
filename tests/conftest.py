import pytest

from blockchain_exporter.context import reset_application_context
from blockchain_exporter.health import CHAIN_HEALTH_STATUS, CHAIN_LAST_SUCCESS
from blockchain_exporter.metrics import reset_metrics_state
from blockchain_exporter.runtime_settings import reset_runtime_settings_cache


@pytest.fixture(autouse=True)
def reset_exporter_state() -> None:
    reset_metrics_state()
    reset_application_context()
    reset_runtime_settings_cache()
    CHAIN_HEALTH_STATUS.clear()
    CHAIN_LAST_SUCCESS.clear()
    yield
    reset_metrics_state()
    reset_application_context()
    reset_runtime_settings_cache()
    CHAIN_HEALTH_STATUS.clear()
    CHAIN_LAST_SUCCESS.clear()
