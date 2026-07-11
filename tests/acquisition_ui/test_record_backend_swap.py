"""T1-3 regression: Cockpit Record path swaps to VectorXcpRecorderBackend
when transport + ifdata + measurement pool are all set, and otherwise
emits an unmissable ``[FAKE backend]`` status warning.

Mac coverage only — non-Windows ``VectorXcpRecorderBackend.__init__``
raises ``RecorderBackendUnavailableError``, so we verify the fallback
path here. Real Vector hardware verification lives in PR-4 bench.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary
from can_logger.p0.ifdata_xcp import (
    DaqEventInfo,
    DaqProcessorInfo,
    IfDataXcp,
)
from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.health import HwHealth, level_daq
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.state import CockpitState, HealthyPredicateResult


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


class _OwnedVectorStub:
    def __init__(self, diagnostics: dict | None = None) -> None:
        self.stop_called = 0
        self._diagnostics = diagnostics or {}

    def start(self, _selection):
        pass

    def poll(self):
        return []

    def stop(self):
        self.stop_called += 1

    def status(self):
        return SimpleNamespace(started=True, bus_error_count=0)

    def diagnostics(self):
        return dict(self._diagnostics)

    def last_frame_monotonic(self):
        return None


def _arm_owned_connected(window: CockpitMainWindow, backend: _OwnedVectorStub) -> None:
    window.set_transport(TransportConfig(app_name="Python", channel=0))
    window._ifdata_xcp = _stub_ifdata()
    window._left_pane.set_pool(_stub_pool(), a2l_has_daq_events=True)
    _select_engine_speed(window)
    window._backend = backend  # type: ignore[assignment]
    window._owns_vector_backend = True
    window._connection_attempt_started = 1.0
    window._first_frame_ts = 2.0
    window._stream_start_ts = 1.0
    window._fake_xcp_connected = True
    window._fake_can_load_pct = 12.5
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True,
            xcp_connected=True,
            first_frame_received=True,
        )
    )


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
        assert "measurement selection 为空" in window._status.currentMessage()
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


def test_owned_vector_selection_change_stops_backend_and_requires_reconnect(qapp):
    """Writer schema cannot drift from an already programmed Vector DAQ map."""

    class _OwnedVector:
        def __init__(self) -> None:
            self.stop_called = 0

        def start(self, _selection):
            pass

        def poll(self):
            return []

        def stop(self):
            self.stop_called += 1

        def status(self):
            return SimpleNamespace(started=True)

        def last_frame_monotonic(self):
            return None

    pool = _stub_pool() + (
        MeasurementSummary(
            name="BatteryVoltage",
            address=0x40000002,
            datatype="UWORD",
            unit="V",
            conversion="",
            available_events=("evt",),
        ),
    )
    owned = _OwnedVector()
    window = CockpitMainWindow()
    try:
        window._left_pane.set_pool(pool, a2l_has_daq_events=True)
        _select_engine_speed(window)
        window._backend = owned  # type: ignore[assignment]
        window._owns_vector_backend = True
        window._connection_attempt_started = 1.0
        window._fake_xcp_connected = True
        window.state_machine.request_connect(
            HealthyPredicateResult.from_components(
                hw_ok=True,
                xcp_connected=True,
                first_frame_received=True,
            )
        )

        window._left_pane._set_measurement_selected("BatteryVoltage", True)

        assert owned.stop_called == 1
        assert window._owns_vector_backend is False
        assert isinstance(window._backend, FakeRecorderBackend)
        assert window.state_machine.state == CockpitState.DISCONNECTED
        assert window.main_button.text() == "连接 ECU"
        assert "重新连接" in window._status.currentMessage()
        assert window._connection_attempt_started is None
        assert window._fake_xcp_connected is False

        replacement = _OwnedVector()
        window._backend = replacement  # type: ignore[assignment]
        window._owns_vector_backend = True
        window.state_machine.request_connect(
            HealthyPredicateResult.from_components(
                hw_ok=True,
                xcp_connected=True,
                first_frame_received=True,
            )
        )
        assert window.state_machine.state == CockpitState.CONNECTED_IDLE
        assert window.main_button.text() == "● 采集"
        assert window.main_button.isEnabled() is True
    finally:
        window.close()


def test_connected_transport_change_fully_disconnects_owned_vector(qapp):
    owned = _OwnedVectorStub()
    window = CockpitMainWindow()
    try:
        _arm_owned_connected(window, owned)
        replacement = TransportConfig(app_name="PythonChanged", channel=1)

        window.set_transport(replacement)

        assert owned.stop_called == 1
        assert window._transport_config == replacement
        assert window._owns_vector_backend is False
        assert isinstance(window._backend, FakeRecorderBackend)
        assert window.state_machine.state == CockpitState.DISCONNECTED
        assert window._connection_attempt_started is None
        assert window._first_frame_ts is None
        assert window._stream_start_ts is None
        assert window._fake_xcp_connected is False
        assert window._fake_can_load_pct is None
        assert window.main_button.text() == "连接 ECU"
    finally:
        window.close()


def test_unchanged_transport_keeps_connected_owned_vector(qapp):
    """Saving threshold-only settings must not tear down a valid DAQ layout."""

    owned = _OwnedVectorStub()
    window = CockpitMainWindow()
    try:
        _arm_owned_connected(window, owned)
        original_transport = window._transport_config

        assert window.set_transport(original_transport) is True

        assert owned.stop_called == 0
        assert window._backend is owned
        assert window._owns_vector_backend is True
        assert window.state_machine.state == CockpitState.CONNECTED_IDLE
    finally:
        window.close()


def test_connected_a2l_change_fully_disconnects_owned_vector(
    qapp, monkeypatch, tmp_path
):
    from can_logger.p0 import a2l_probe as a2l_probe_module
    from can_logger.p0 import ifdata_xcp as ifdata_module

    owned = _OwnedVectorStub()
    window = CockpitMainWindow()
    replacement = _stub_pool()
    summary = A2LSummary(
        path=str(tmp_path / "replacement.a2l"),
        total_measurements=1,
        measurements=list(replacement),
        a2l_has_daq_events=True,
    )
    monkeypatch.setattr(ifdata_module, "parse_ifdata_xcp_file", lambda _path: (_stub_ifdata(),))
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda _path, *, limit=None: summary,
    )
    try:
        _arm_owned_connected(window, owned)
        path = tmp_path / "replacement.a2l"
        path.write_text("")

        window.apply_a2l_path(path)

        assert owned.stop_called == 1
        assert window.state_machine.state == CockpitState.DISCONNECTED
        assert window._connection_attempt_started is None
        assert window._first_frame_ts is None
        assert window._fake_xcp_connected is False
        assert window.main_button.text() == "连接 ECU"
        assert window._a2l_name == "replacement.a2l"
    finally:
        window.close()


@pytest.mark.parametrize("target_state", [CockpitState.RECORDING, CockpitState.REVIEW_MODAL])
def test_recording_and_review_reject_transport_and_a2l_mutation(
    qapp, tmp_path, target_state
):
    owned = _OwnedVectorStub()
    controller = object()
    window = CockpitMainWindow()
    try:
        _arm_owned_connected(window, owned)
        original_transport = window._transport_config
        window._a2l_name = "original.a2l"
        window._capture_controller = controller  # type: ignore[assignment]
        window.state_machine.request_start_recording()
        if target_state == CockpitState.REVIEW_MODAL:
            window._open_review_modal = lambda: None  # type: ignore[method-assign]
            window.state_machine.request_stop_recording(finalized=True)

        assert window.state_machine.state == target_state
        assert window._settings_action.isEnabled() is False
        assert window._a2l_btn.isEnabled() is False
        assert window._transport_chip.isEnabled() is False
        assert window._left_pane._frozen is True

        selection_before = window._left_pane.current_selection()
        window._left_pane._set_measurement_selected("EngineSpeed", False)
        assert window._left_pane.current_selection() == selection_before

        window.set_transport(TransportConfig(app_name="Forbidden", channel=2))
        window.apply_a2l_path(tmp_path / "forbidden.a2l")

        assert owned.stop_called == 0
        assert window._backend is owned
        assert window._owns_vector_backend is True
        assert window._capture_controller is controller
        assert window._transport_config == original_transport
        assert window._a2l_name == "original.a2l"
        assert "不可修改" in window._status.currentMessage()
        if target_state == CockpitState.REVIEW_MODAL:
            window.state_machine.request_review_close()
            assert window._left_pane._frozen is False
    finally:
        window._capture_controller = None
        window.close()


@pytest.mark.parametrize(
    ("counter", "expected"),
    [
        ("unknown_pid_count", "unknown PID"),
        ("decode_error_count", "DTO decode error"),
        ("policy_error_count", "DAQ policy error"),
    ],
)
def test_vector_daq_diagnostics_errors_are_red(qapp, counter, expected):
    owned = _OwnedVectorStub({counter: 1})
    window = CockpitMainWindow()
    try:
        window._backend = owned  # type: ignore[assignment]
        window._owns_vector_backend = True
        window._ifdata_xcp = _stub_ifdata()

        health = window._probe_daq()

        assert any(expected in item for item in health.overflow)
        assert level_daq(health) == "red"
    finally:
        window.close()
