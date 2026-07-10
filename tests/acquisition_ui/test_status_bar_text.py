"""Status-bar text audit for Acquisition Cockpit states."""

from __future__ import annotations

import time

from PyQt5.QtGui import QFontMetrics

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    DaqHealth,
    HealthSnapshot,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_ui.main_window import _connection_mixin as conn_mixin
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.state import CockpitState, HealthyPredicateResult
from mf4_analyzer.acquisition_ui.widgets.escalation_bar import escalation_state

GB = 1024 ** 3
MB = 1024 ** 2


def _rec_snapshot(*, dropped: int = 0, ring: float = 10.0) -> HealthSnapshot:
    return HealthSnapshot(
        hw=HwHealth(
            ok=True,
            driver_version="t",
            channel_count=1,
            last_probe_ts=time.monotonic(),
            error=None,
        ),
        can=CanHealth(bus_load_pct=10.0),
        xcp=XcpHealth(connected=True, slave_id=0x55),
        daq=DaqHealth(event_capacity={"event_10ms": 32}, event_used={"event_10ms": 1}),
        rec=RecHealth(
            state="recording",
            ring_buffer_fill_pct=ring,
            dropped_frames=dropped,
            write_rate_bps=0.0,
            last_rx_age_s=0.1,
            writer_thread_alive=True,
        ),
        captured_at=time.monotonic(),
    )


def _connect(window: CockpitMainWindow) -> None:
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )


def _pool(n: int) -> tuple[MeasurementSummary, ...]:
    return tuple(
        MeasurementSummary(
            name=f"Sig_{i:02d}",
            address=0x40000000 + i * 4,
            datatype="UWORD",
            unit="",
            conversion="",
            available_events=("event_10ms",),
        )
        for i in range(n)
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
        assert window.statusBar().currentMessage() == "已连接 · 已选 0 · 实时显示 0"
    finally:
        window.close()


def test_idle_status_tracks_selection_and_effective_pins(qapp):
    window = CockpitMainWindow(initial_pool=_pool(6), allow_fake_backend=True)
    try:
        _connect(window)
        for i in range(6):
            window.left_pane._set_measurement_selected(f"Sig_{i:02d}", True)
        assert window.statusBar().currentMessage() == "已连接 · 已选 6 · 实时显示 5"
    finally:
        window.close()


def test_recording_status_bar_text(qapp):
    # Recording status bar now streams neutral FACTS only (Spec §B5):
    # 时长 · 磁盘剩余时长 · 样本数 · 文件大小 · 写入速率. Anomalies (dropped /
    # ring) moved to the escalation ladder + REC chip.
    window = CockpitMainWindow()
    try:
        _connect(window)
        window.state_machine.request_start_recording()
        assert window.statusBar().currentMessage() == (
            "录制中 · 00:00 · 磁盘剩 ∞ · 0 样本 · 缓冲中 · 0 样本/s"
        )
    finally:
        window.close()


def test_recording_facts_full_five_fields(qapp):
    window = CockpitMainWindow()
    try:
        _connect(window)
        window.state_machine.request_start_recording()
        # A roomy budget keeps all five priority-ordered facts.
        assert len(window._recording_fact_parts(1280)) == 5
    finally:
        window.close()


def test_recording_facts_degrade_by_priority_no_partial(qapp):
    window = CockpitMainWindow()
    try:
        _connect(window)
        window.state_machine.request_start_recording()
        full = window._recording_fact_parts(0)  # 0 == no budget -> all five
        assert len(full) == 5
        assert full[0].startswith("录制中 · ")
        assert full[1].startswith("磁盘剩 ")

        fm = QFontMetrics(window.statusBar().font())
        w3 = fm.horizontalAdvance(" · ".join(full[:3]))
        w4 = fm.horizontalAdvance(" · ".join(full[:4]))
        tight = (w3 + w4) // 2  # fits exactly three fields

        kept = window._recording_fact_parts(tight)
        # Dropped lowest-priority-first (文件大小, 写入速率), kept whole.
        assert kept == full[:3]
        assert all(part in full for part in kept)  # no mid-truncated field
    finally:
        window.close()


def test_disk_duration_never_from_write_rate_bytes(qapp, monkeypatch):
    # write_rate_bps is samples/s; disk remaining-time comes from the byte
    # throughput estimator. With an empty selection the byte throughput is 0
    # so the disk-time is ∞ EVEN when the samples/s rate is huge.
    window = CockpitMainWindow()
    try:
        _connect(window)
        window.state_machine.request_start_recording()
        monkeypatch.setattr(
            window, "_recording_write_rate_per_s", lambda: 999_999.0
        )
        parts = window._recording_fact_parts(0)
        assert "∞" in parts[1]                      # disk-time unaffected
        assert parts[4] == "999999 样本/s"           # honest samples/s label
    finally:
        window.close()


def test_escalation_bar_never_shifts_body(qapp):
    # The escalation overlay lives above the status bar (not in the body
    # layout), so appearing / collapsing / recovering must not move the
    # LiveCardGrid a single pixel.
    window = CockpitMainWindow()
    try:
        window.resize(1280, 760)
        window.show()
        qapp.processEvents()
        _connect(window)
        window.state_machine.request_start_recording()
        qapp.processEvents()
        baseline = window._center.geometry()

        states = {
            "green": escalation_state(_rec_snapshot(), disk_free_bytes=10 * GB),
            "yellow": escalation_state(_rec_snapshot(dropped=3), disk_free_bytes=10 * GB),
            "red": escalation_state(_rec_snapshot(dropped=20), disk_free_bytes=512 * MB),
        }
        for name, state in states.items():
            window._escalation_bar.apply(state)
            qapp.processEvents()
            assert window._center.geometry() == baseline, f"body moved on {name}"

        # ack then recovery — still no body shift.
        window._escalation_bar.apply(states["red"])
        window._escalation_bar.acknowledge()
        qapp.processEvents()
        assert window._center.geometry() == baseline, "body moved on ack"
        window._escalation_bar.apply(states["green"])
        qapp.processEvents()
        assert window._center.geometry() == baseline, "body moved on recovery"
        assert window.state_machine.state == CockpitState.RECORDING
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
