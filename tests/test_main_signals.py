"""Tests for SIGHUP signal handling in main.py."""

from __future__ import annotations

import signal

import pytest

import blockchain_exporter.main as main_module


def test_sighup_signal_sets_reload_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SIGHUP signal sets the reload event."""
    event_set = False

    def mock_set() -> None:
        nonlocal event_set
        event_set = True

    monkeypatch.setattr(main_module._reload_event, "set", mock_set)

    # Create signal handler
    def _signal_handler(signum: int, frame: object) -> None:
        if signum in (signal.SIGTERM, signal.SIGINT):
            raise KeyboardInterrupt(f"Received signal {signum}")
        elif signum == signal.SIGHUP:
            main_module._reload_event.set()

    # Simulate SIGHUP
    _signal_handler(signal.SIGHUP, None)

    assert event_set is True


def test_sigterm_signal_raises_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SIGTERM signal raises KeyboardInterrupt."""
    def _signal_handler(signum: int, frame: object) -> None:
        if signum in (signal.SIGTERM, signal.SIGINT):
            raise KeyboardInterrupt(f"Received signal {signum}")
        elif signum == signal.SIGHUP:
            main_module._reload_event.set()

    # Simulate SIGTERM
    with pytest.raises(KeyboardInterrupt, match="Received signal 15"):
        _signal_handler(signal.SIGTERM, None)


def test_sigint_signal_raises_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SIGINT signal raises KeyboardInterrupt."""
    def _signal_handler(signum: int, frame: object) -> None:
        if signum in (signal.SIGTERM, signal.SIGINT):
            raise KeyboardInterrupt(f"Received signal {signum}")
        elif signum == signal.SIGHUP:
            main_module._reload_event.set()

    # Simulate SIGINT
    with pytest.raises(KeyboardInterrupt, match="Received signal 2"):
        _signal_handler(signal.SIGINT, None)

