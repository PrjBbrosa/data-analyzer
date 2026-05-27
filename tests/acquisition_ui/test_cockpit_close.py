"""B4: closing the cockpit window must drain the backend + timers.

Without this, a Vector backend leaks hardware handles and the next
connection attempt fails with 'channel busy'. Test uses the fake
backend (default for headless tests) to record stop() invocations.
"""

from __future__ import annotations

import pytest

from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def test_close_event_stops_backend_and_timers(qapp):
    window = CockpitMainWindow()

    stop_calls = []

    class _BackendSpy:
        def __init__(self, inner) -> None:
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def stop(self):
            stop_calls.append("stop")
            return self._inner.stop()

    window._backend = _BackendSpy(window._backend)
    # The cockpit construction starts the health timer; assert it was
    # active so closeEvent has something to stop.
    assert window._health_timer.isActive() is True

    window.close()
    qapp.processEvents()

    assert stop_calls == ["stop"]
    assert window._health_timer.isActive() is False
    assert window._live_timer.isActive() is False


def test_close_event_tolerates_backend_failure(qapp):
    """closeEvent must not raise even if the backend's stop() throws —
    the window has to come down regardless so Qt doesn't leak."""
    window = CockpitMainWindow()

    class _BrokenBackend:
        def stop(self):
            raise RuntimeError("hw gone")

    window._backend = _BrokenBackend()
    # Just calling close() must not raise.
    window.close()
    qapp.processEvents()
    assert window._health_timer.isActive() is False
