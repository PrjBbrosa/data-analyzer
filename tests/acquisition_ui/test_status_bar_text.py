"""Status-bar text audit for Acquisition Cockpit states."""

from __future__ import annotations

import time

import pytest
from PyQt5.QtGui import QFontMetrics

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture.backends import (
    BackendStatus,
    FakeRecorderBackend,
    RecorderBackend,
)
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
            "录制中 · 00:00 · 磁盘剩 ∞ · 0 样本 · 0.0 MB · 0 样本/s"
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


class _ControllableClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt)


class _QueuedBackend(RecorderBackend):
    """Deterministic idle-poll source: samples are queued, not wall-clock."""

    def __init__(self) -> None:
        self.pending: list[tuple[str, float, float]] = []
        self.rx_count = 0
        self.started = False
        self._last_frame: float | None = None

    def start(self, selected) -> None:
        self.started = True
        self.rx_count = 0
        self._last_frame = None

    def stop(self) -> BackendStatus:
        self.started = False
        return self.status()

    def poll(self) -> list[tuple[str, float, float]]:
        out = list(self.pending)
        self.pending.clear()
        self.rx_count += len(out)
        if out:
            self._last_frame = out[-1][1]
        return out

    def status(self) -> BackendStatus:
        return BackendStatus(
            started=self.started,
            rx_count=self.rx_count,
            bus_error_count=0,
            queue_overflow_count=0,
        )

    def last_frame_monotonic(self) -> float | None:
        return self._last_frame


def _one_second_samples(name: str, *, sps: float = 20.0) -> list[tuple[str, float, float]]:
    count = int(sps)
    dt = 1.0 / sps
    return [(name, (i + 1) * dt, float(i + 1)) for i in range(count)]


def _card_sample_count(window: CockpitMainWindow, name: str) -> int:
    card = window._center.cards.get(name)
    if card is None:
        return 0
    return int(card._spark.sample_count)


def _assert_idle_samples_processed_without_ring(
    window: CockpitMainWindow,
    *,
    channel: str,
    min_samples: int,
    ring_puts: list,
) -> None:
    assert window._cumulative_rx_count >= min_samples, (
        f"idle poll processed no samples (rx={window._cumulative_rx_count})"
    )
    assert _card_sample_count(window, channel) >= min_samples, (
        f"cards did not receive {channel!r} data"
    )
    assert ring_puts == [], f"idle poll must not write the ring: {ring_puts!r}"
    assert window.ring_buffer.level_pct == 0.0


def _prepare_idle_demo(window: CockpitMainWindow, backend: RecorderBackend) -> None:
    _connect(window)
    selected = [SelectedMeasurement(name="DemoSignal")]
    window._refresh_center_cards(explicit=selected)
    backend.start(selected)
    assert "DemoSignal" in window._center.cards


def test_idle_polling_does_not_fill_ring(qapp, monkeypatch):
    """Idle live polling feeds cards directly; ring is recording-only."""
    backend = _QueuedBackend()
    window = CockpitMainWindow(backend=backend, allow_fake_backend=True)
    ring_puts: list = []
    orig_put = window.ring_buffer.put

    def _spy_put(item):
        ring_puts.append(item)
        return orig_put(item)

    monkeypatch.setattr(window.ring_buffer, "put", _spy_put)
    try:
        _prepare_idle_demo(window, backend)
        samples = _one_second_samples("DemoSignal")
        backend.pending.extend(samples)
        window._poll_live()
        _assert_idle_samples_processed_without_ring(
            window,
            channel="DemoSignal",
            min_samples=len(samples),
            ring_puts=ring_puts,
        )
        assert samples[0][1] == pytest.approx(0.05)
        assert samples[-1][1] == pytest.approx(1.0)
    finally:
        window.close()


def test_idle_polling_real_fake_backend_owner(qapp, monkeypatch):
    """Keep FakeRecorderBackend as the owner/integration idle path."""
    clock = _ControllableClock()
    monkeypatch.setattr(
        "mf4_analyzer.acquisition_capture.backends.time.monotonic",
        clock,
    )
    backend = FakeRecorderBackend(samples_per_second=20.0)
    window = CockpitMainWindow(backend=backend, allow_fake_backend=True)
    ring_puts: list = []
    monkeypatch.setattr(
        window.ring_buffer,
        "put",
        lambda item: ring_puts.append(item),
    )
    try:
        _prepare_idle_demo(window, backend)
        clock.advance(1.0)
        window._poll_live()
        _assert_idle_samples_processed_without_ring(
            window,
            channel="DemoSignal",
            min_samples=20,
            ring_puts=ring_puts,
        )
    finally:
        window.close()


def test_idle_polling_no_samples_is_not_success(qapp, monkeypatch):
    backend = _QueuedBackend()
    window = CockpitMainWindow(backend=backend, allow_fake_backend=True)
    ring_puts: list = []
    monkeypatch.setattr(window.ring_buffer, "put", lambda item: ring_puts.append(item))
    try:
        _prepare_idle_demo(window, backend)
        window._poll_live()
        with pytest.raises(AssertionError, match="processed no samples"):
            _assert_idle_samples_processed_without_ring(
                window,
                channel="DemoSignal",
                min_samples=1,
                ring_puts=ring_puts,
            )
    finally:
        window.close()


def test_idle_polling_dropped_delivery_is_not_success(qapp, monkeypatch):
    backend = _QueuedBackend()
    window = CockpitMainWindow(backend=backend, allow_fake_backend=True)
    ring_puts: list = []
    monkeypatch.setattr(window.ring_buffer, "put", lambda item: ring_puts.append(item))
    monkeypatch.setattr(window._center, "push_sample", lambda *args, **kwargs: None)
    try:
        _prepare_idle_demo(window, backend)
        backend.pending.extend(_one_second_samples("DemoSignal"))
        window._poll_live()
        with pytest.raises(AssertionError, match="cards did not receive"):
            _assert_idle_samples_processed_without_ring(
                window,
                channel="DemoSignal",
                min_samples=1,
                ring_puts=ring_puts,
            )
    finally:
        window.close()


def test_idle_polling_ring_write_error_is_not_success(qapp, monkeypatch):
    backend = _QueuedBackend()
    window = CockpitMainWindow(backend=backend, allow_fake_backend=True)

    def _failing_put(_item):
        raise RuntimeError("error writing the ring")

    monkeypatch.setattr(window.ring_buffer, "put", _failing_put)
    try:
        _prepare_idle_demo(window, backend)
        samples = _one_second_samples("DemoSignal")
        backend.pending.extend(samples)
        window._poll_live()
        # Idle path must not call ring.put; a recording-path write error
        # would raise here. Discriminate by feeding the helper a recorded put.
        with pytest.raises(AssertionError, match="must not write the ring"):
            _assert_idle_samples_processed_without_ring(
                window,
                channel="DemoSignal",
                min_samples=len(samples),
                ring_puts=[("DemoSignal", 1.0, 1.0)],
            )
        assert window.ring_buffer.level_pct == 0.0
        assert window._cumulative_rx_count == len(samples)
    finally:
        window.close()
