"""T1-3 regression: Cockpit Record path swaps to VectorXcpRecorderBackend
when transport + ifdata + measurement pool are all set, and otherwise
emits an unmissable ``[FAKE backend]`` status warning.

Mac coverage only — non-Windows ``VectorXcpRecorderBackend.__init__``
raises ``RecorderBackendUnavailableError``, so we verify the fallback
path here. Real Vector hardware verification lives in PR-4 bench.
"""

from __future__ import annotations

import sys

import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import (
    DaqEventInfo,
    DaqProcessorInfo,
    IfDataXcp,
)
from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.health import HwHealth
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def _stub_ifdata() -> IfDataXcp:
    return IfDataXcp(
        cmd_id=0x6C7,
        resp_id=0x6C6,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=0,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(
            DaqEventInfo(
                number=0,
                name="evt",
                cycle_time_ms=10.0,
                max_odt_entries=16,
                properties=(),
            ),
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=0,
            max_event_channel=1,
            granularity_odt_entry_size_daq=1,
            overload_indication="NO_OVERLOAD_INDICATION",
        ),
    )


def _stub_pool() -> tuple[MeasurementSummary, ...]:
    return (
        MeasurementSummary(
            name="EngineSpeed",
            address=0x40000000,
            datatype="UWORD",
            unit="rpm",
            conversion="",
            available_events=("evt",),
        ),
    )


def _suppress_connection_warning(window: CockpitMainWindow) -> None:
    window._warn_connection_preconditions = lambda _problems: None  # type: ignore[method-assign]


def _capture_connection_warnings(window: CockpitMainWindow) -> list[str]:
    warnings: list[str] = []
    window._warn_connection_preconditions = warnings.extend  # type: ignore[method-assign]
    return warnings


def _select_engine_speed(window: CockpitMainWindow) -> None:
    window._left_pane._selected_names.add("EngineSpeed")
    window._left_pane._refresh_list()


def test_no_swap_when_transport_missing(qapp):
    """No Settings visit → stays on Fake without trying Vector."""

    window = CockpitMainWindow()
    try:
        _suppress_connection_warning(window)
        assert window._maybe_swap_to_vector_backend() is False
        assert isinstance(window._backend, FakeRecorderBackend)
        msg = window._status.currentMessage()
        assert "[FAKE backend]" in msg
        assert "Transport 未配置" in msg
    finally:
        window.deleteLater()


def test_missing_vehicle_preconditions_warn_in_production(qapp):
    """Production connection attempts must surface missing gates as a dialog."""

    window = CockpitMainWindow()
    try:
        warnings = _capture_connection_warnings(window)

        assert window._maybe_swap_to_vector_backend() is False

        assert warnings
        assert any("Transport" in problem for problem in warnings)
        assert "[FAKE backend]" in window._status.currentMessage()
    finally:
        window.deleteLater()


def test_no_swap_when_ifdata_missing(qapp):
    """Operator configured Transport but never picked an A2L."""

    window = CockpitMainWindow()
    try:
        window.set_transport(TransportConfig(app_name="Python", channel=0))
        _suppress_connection_warning(window)
        assert window._maybe_swap_to_vector_backend() is False

        assert isinstance(window._backend, FakeRecorderBackend)
        msg = window._status.currentMessage()
        assert "[FAKE backend]" in msg
        assert "A2L IF_DATA 未加载" in msg
    finally:
        window.deleteLater()


def test_no_swap_when_pool_empty(qapp):
    """Transport + ifdata set but no measurements in the pool."""

    window = CockpitMainWindow()
    try:
        window.set_transport(TransportConfig(app_name="Python", channel=0))
        window._ifdata_xcp = _stub_ifdata()
        _suppress_connection_warning(window)
        assert window._maybe_swap_to_vector_backend() is False

        assert isinstance(window._backend, FakeRecorderBackend)
        msg = window._status.currentMessage()
        assert "[FAKE backend]" in msg
        assert "measurement pool 为空" in msg
    finally:
        window.deleteLater()


def test_no_swap_when_real_selection_empty(qapp):
    """Vehicle path requires an actual selected measurement, not DemoSignal."""

    window = CockpitMainWindow()
    try:
        window.set_transport(TransportConfig(app_name="Python", channel=0))
        window._ifdata_xcp = _stub_ifdata()
        window._left_pane.set_pool(_stub_pool(), a2l_has_daq_events=True)
        _select_engine_speed(window)
        _suppress_connection_warning(window)

        assert window._maybe_swap_to_vector_backend(selection=()) is False
        assert isinstance(window._backend, FakeRecorderBackend)
        assert "measurement selection ä¸ºç©º" in window._status.currentMessage()
    finally:
        window.deleteLater()


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Vector backend constructs successfully on Windows; this test "
    "covers the Mac fallback path.",
)
def test_non_windows_falls_back_to_fake_with_warning(qapp):
    """All preconditions met but we're on Mac → keep Fake, surface
    the RecorderBackendUnavailableError reason in the status bar."""

    window = CockpitMainWindow()
    try:
        window.set_transport(TransportConfig(app_name="Python", channel=0))
        window._ifdata_xcp = _stub_ifdata()
        window._left_pane.set_pool(_stub_pool(), a2l_has_daq_events=True)
        _select_engine_speed(window)
        _suppress_connection_warning(window)

        assert window._maybe_swap_to_vector_backend() is False

        assert isinstance(window._backend, FakeRecorderBackend)
        msg = window._status.currentMessage()
        assert "[FAKE backend]" in msg
        assert "Vector 不可用" in msg
        # The underlying message names Windows.
        assert "Windows" in msg
    finally:
        window.deleteLater()


def test_health_timer_starts_on_window_init(qapp):
    window = CockpitMainWindow()
    try:
        assert window._health_timer.isActive()
    finally:
        window.deleteLater()


def test_begin_connection_blocks_fake_when_vehicle_preconditions_missing(qapp):
    """Vehicle path must not start synthetic data when Vector preconditions fail."""

    class _SpyFake(FakeRecorderBackend):
        def __init__(self) -> None:
            super().__init__()
            self.start_called = 0

        def start(self, selected):  # type: ignore[override]
            self.start_called += 1
            return super().start(selected)

    backend = _SpyFake()
    window = CockpitMainWindow(backend=backend)
    try:
        warnings = _capture_connection_warnings(window)
        window._ifdata_xcp = _stub_ifdata()
        window._left_pane.set_pool(_stub_pool(), a2l_has_daq_events=True)

        window._begin_connection_attempt()

        assert backend.start_called == 0
        assert window._connection_attempt_started is None
        assert window._stream_start_ts is None
        assert window._fake_xcp_connected is False
        assert window._fake_can_load_pct is None
        assert window._fake_rec_state == "off"
        assert any("Transport" in problem for problem in warnings)
        assert "[FAKE backend]" in window._status.currentMessage()
        assert "Transport 未配置" in window._status.currentMessage()
    finally:
        window.deleteLater()


def test_begin_connection_blocks_fake_when_vector_unavailable(qapp):
    """All vehicle inputs present but Vector unavailable must still block Fake."""

    class _SpyFake(FakeRecorderBackend):
        def __init__(self) -> None:
            super().__init__()
            self.start_called = 0

        def start(self, selected):  # type: ignore[override]
            self.start_called += 1
            return super().start(selected)

    backend = _SpyFake()
    window = CockpitMainWindow(backend=backend)
    try:
        warnings = _capture_connection_warnings(window)
        window.set_transport(TransportConfig(app_name="Python", channel=0))
        window._ifdata_xcp = _stub_ifdata()
        window._left_pane.set_pool(_stub_pool(), a2l_has_daq_events=True)
        _select_engine_speed(window)

        window._begin_connection_attempt()

        assert backend.start_called == 0
        assert window._connection_attempt_started is None
        assert window._stream_start_ts is None
        assert window._fake_xcp_connected is False
        assert window._fake_can_load_pct is None
        assert window._fake_rec_state == "off"
        assert any("Vector" in problem for problem in warnings)
        assert "[FAKE backend]" in window._status.currentMessage()
        assert "Vector 不可用" in window._status.currentMessage()
    finally:
        window.deleteLater()


def test_owned_vector_backend_is_rechecked_after_ifdata_clears(qapp):
    """A backend created by Cockpit must not bypass later precondition failures."""

    class _OwnedVector:
        def __init__(self) -> None:
            self.stop_called = 0

        def start(self, _selection):
            pass

        def poll(self):
            return []

        def stop(self):
            self.stop_called += 1
            return None

        def status(self):
            return None

        def last_frame_monotonic(self):
            return None

    owned = _OwnedVector()
    window = CockpitMainWindow()
    try:
        window.set_transport(TransportConfig(app_name="Python", channel=0))
        window._backend = owned  # type: ignore[assignment]
        window._owns_vector_backend = True
        window._ifdata_xcp = None
        window._left_pane.set_pool(_stub_pool(), a2l_has_daq_events=True)
        _suppress_connection_warning(window)

        assert window._maybe_swap_to_vector_backend(selection=()) is False
        assert owned.stop_called == 1
        assert isinstance(window._backend, FakeRecorderBackend)
        assert window._owns_vector_backend is False
        assert "A2L IF_DATA" in window._status.currentMessage()
    finally:
        window.deleteLater()


def test_demo_opt_in_allows_fake_backend(qapp):
    """The Stage 4 demo entrypoint can still opt into synthetic data."""

    class _SpyFake(FakeRecorderBackend):
        def __init__(self) -> None:
            super().__init__()
            self.start_called = 0

        def start(self, selected):  # type: ignore[override]
            self.start_called += 1
            return super().start(selected)

    backend = _SpyFake()
    window = CockpitMainWindow(
        backend=backend,
        initial_pool=_stub_pool(),
        allow_fake_backend=True,
    )
    try:
        window._begin_connection_attempt()

        assert backend.start_called == 1
        assert "Demo backend" in window._status.currentMessage()
    finally:
        window.deleteLater()


def test_connection_precondition_warning_uses_nonblocking_message_box(
    qapp, monkeypatch
):
    opened = []

    def fake_open(box):
        opened.append(box)

    monkeypatch.setattr(QMessageBox, "open", fake_open)
    window = CockpitMainWindow()
    try:
        window.show()
        window._warn_connection_preconditions(["Transport missing"])

        box = window._connection_warning_box
        assert isinstance(box, QMessageBox)
        assert box.windowModality() == Qt.WindowModal
        assert box.icon() == QMessageBox.Warning
        assert "Transport missing" in box.text()
        assert opened == [box]
        box.close()
    finally:
        window.deleteLater()


def test_probe_hw_reports_missing_transport(qapp):
    window = CockpitMainWindow()
    try:
        result = window._probe_hw()

        assert result.ok is False
        assert result.error == "transport not configured"
    finally:
        window.deleteLater()


def test_probe_hw_uses_vector_hw_probe_when_transport_configured(qapp, monkeypatch):
    calls = []

    def fake_probe(transport):
        calls.append(transport)
        return HwHealth(
            ok=True,
            driver_version="26.10.2",
            channel_count=7,
            last_probe_ts=123.0,
            error=None,
        )

    monkeypatch.setattr(
        "mf4_analyzer.acquisition_capture.vector_hw_probe.vector_hw_probe",
        fake_probe,
    )

    window = CockpitMainWindow()
    try:
        transport = TransportConfig(app_name="Python", channel=0)
        window.set_transport(transport)

        result = window._probe_hw()

        assert result.ok is True
        assert result.driver_version == "26.10.2"
        assert calls == [transport]
    finally:
        window.deleteLater()


def test_swap_no_op_when_caller_injected_non_fake_backend(qapp):
    """If a test (or future replay flow) injected a non-Fake backend at
    construction time, the swap path must respect that contract and
    never overwrite the injection."""

    class _Sentinel(FakeRecorderBackend):
        pass

    sentinel = _Sentinel()
    # Use a normal injection — the isinstance() check uses FakeRecorderBackend,
    # so we use a deliberately *non*-Fake stub here to prove the gate.
    class _NonFake:
        def start(self, _selection):
            pass

        def poll(self):
            return []

        def stop(self):
            return None

        def status(self):
            return None

        def last_frame_monotonic(self):
            return None

    non_fake = _NonFake()
    window = CockpitMainWindow(backend=non_fake)  # type: ignore[arg-type]
    try:
        window.set_transport(TransportConfig(app_name="Python", channel=0))
        window._ifdata_xcp = _stub_ifdata()
        window._left_pane.set_pool(_stub_pool(), a2l_has_daq_events=True)

        before = window._backend
        assert window._maybe_swap_to_vector_backend() is True
        # Caller-injected backend untouched.
        assert window._backend is before
    finally:
        window.deleteLater()
