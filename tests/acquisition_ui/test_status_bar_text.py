"""Status-bar text audit for Acquisition Cockpit states."""

from __future__ import annotations

import time

from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_ui.main_window import _connection_mixin as conn_mixin
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
        assert window.statusBar().currentMessage() == "实时流 · 0 evt/s"
    finally:
        window.close()


def test_recording_status_bar_text(qapp):
    window = CockpitMainWindow()
    try:
        _connect(window)
        window.state_machine.request_start_recording()
        assert window.statusBar().currentMessage() == (
            "录制中 · 00:00 · 0 样本 · 缓冲中 · 丢帧 0 · 缓冲 0.0%"
        )
    finally:
        window.close()


def test_probe_rec_uses_writer_write_count_delta(qapp, monkeypatch):
    class Writer:
        write_count = 250

    class Controller:
        writer = Writer()

    window = CockpitMainWindow()
    try:
        window.set_capture_controller(Controller())
        window._fake_rec_state = "recording"
        window._write_rate_prev = (10, 100.0)
        monkeypatch.setattr(conn_mixin.time, "monotonic", lambda: 102.0)
        snap = window._probe_rec()
        assert snap.write_rate_bps == 120.0
    finally:
        window.close()


def test_idle_polling_does_not_fill_ring(qapp):
    """Idle live polling feeds cards directly; ring is recording-only."""
    backend = FakeRecorderBackend(samples_per_second=1000.0)
    window = CockpitMainWindow(backend=backend, allow_fake_backend=True)
    try:
        _connect(window)
        backend.start([SelectedMeasurement(name="DemoSignal")])
        time.sleep(0.02)
        for _ in range(20):
            window._poll_live()
        assert window.ring_buffer.level_pct == 0.0
    finally:
        window.close()
