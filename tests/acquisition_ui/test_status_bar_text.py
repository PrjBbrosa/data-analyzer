"""Status-bar text audit for Acquisition Cockpit states."""

from __future__ import annotations

from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.state import HealthyPredicateResult


def _connect(window: CockpitMainWindow) -> None:
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )


def test_disconnected_status_bar_text(qapp):
    window = CockpitMainWindow()
    try:
        assert window.statusBar().currentMessage() == "未连接 · A2L: 未加载"
    finally:
        window.close()


def test_connected_idle_status_bar_text(qapp):
    window = CockpitMainWindow()
    try:
        _connect(window)
        assert window.statusBar().currentMessage() == "streaming · 0 evt/s · buf 0.0%"
    finally:
        window.close()


def test_recording_status_bar_text(qapp):
    window = CockpitMainWindow()
    try:
        _connect(window)
        window.state_machine.request_start_recording()
        assert window.statusBar().currentMessage() == (
            "RECORDING · 00:00 · 0 samples · 0.0 MB · drop 0 · buf 0.0%"
        )
    finally:
        window.close()
