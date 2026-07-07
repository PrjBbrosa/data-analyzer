"""Capture-session lifecycle: real CaptureController from the record button."""

from pathlib import Path
import time

import pytest
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QLabel

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.state import CockpitState
from mf4_analyzer.io.loader import DataLoader


@pytest.fixture
def cockpit(qtbot, tmp_path):
    window = CockpitMainWindow(allow_fake_backend=True)
    qtbot.addWidget(window)
    window._output_dir_label = str(tmp_path / "runs")
    return window


def test_next_output_path_is_timestamped_and_unique(cockpit):
    p1 = cockpit._next_output_path()
    assert p1.suffix == ".mf4"
    assert p1.name.startswith("capture_")
    assert p1.parent.is_dir()
    p1.touch()
    p2 = cockpit._next_output_path()
    assert p2 != p1
    assert p2.parent == p1.parent


def test_begin_capture_session_builds_controller_demo_fallback(cockpit):
    assert cockpit._begin_capture_session() is True
    ctrl = cockpit._capture_controller
    assert ctrl is not None
    assert ctrl.running
    assert ctrl.config.selected_names == ("DemoSignal",)
    assert ctrl.config.backend == "fake"
    cockpit._teardown_capture_session()
    assert cockpit._capture_controller is None


def test_begin_capture_session_respects_injected_controller(cockpit):
    sentinel = object()
    cockpit.set_capture_controller(sentinel)
    assert cockpit._begin_capture_session() is True
    assert cockpit._capture_controller is sentinel


def _row_event_combo(window: CockpitMainWindow, name: str) -> QComboBox:
    for combo in window.left_pane.findChildren(QComboBox, "measurementEventSelect"):
        if combo.property("measurementName") == name:
            return combo
    raise AssertionError(f"missing row event combo for {name!r}")


def test_sampling_event_choices_feed_capture_controller_config(cockpit, qtbot):
    pool = (
        MeasurementSummary(
            name="FastRotor",
            address=0x40000000,
            datatype="SLONG",
            unit="rpm",
            conversion="",
            available_events=("event_100ms", "event_10ms", "event_1ms"),
        ),
        MeasurementSummary(
            name="MotorTemp",
            address=0x40000004,
            datatype="SWORD",
            unit="degC",
            conversion="",
            available_events=("event_100ms", "event_10ms"),
        ),
    )
    cockpit.left_pane.set_pool(pool, a2l_has_daq_events=True)
    cockpit.left_pane._set_measurement_selected("FastRotor", True)
    cockpit.left_pane._set_measurement_selected("MotorTemp", True)
    qtbot.wait(10)

    batch_combo = cockpit.left_pane.findChild(QComboBox, "batchEventSelect")
    assert batch_combo is not None
    batch_combo.setCurrentText("10ms")
    qtbot.wait(10)
    _row_event_combo(cockpit, "FastRotor").setCurrentText("1ms")
    qtbot.wait(10)

    assert cockpit._begin_capture_session() is True
    controller = cockpit._capture_controller
    assert controller is not None
    try:
        selected = {m.name: m for m in controller.config.selected}
        assert selected["FastRotor"].event == "event_1ms"
        assert selected["FastRotor"].event_rate_hz == 1000.0
        assert selected["MotorTemp"].event == "event_10ms"
        assert selected["MotorTemp"].event_rate_hz == 100.0
    finally:
        controller.stop()
        cockpit._teardown_capture_session()


def test_begin_capture_session_refuses_empty_selection_when_not_demo(qtbot, tmp_path):
    window = CockpitMainWindow(allow_fake_backend=False)
    qtbot.addWidget(window)
    window._output_dir_label = str(tmp_path)
    assert window._begin_capture_session() is False
    assert window._capture_controller is None


def test_demo_window_shows_backend_identity(cockpit):
    assert "演示模式" in cockpit.windowTitle()
    badge = cockpit.findChild(QLabel, "cockpitBackendBadge")
    assert badge is not None
    assert "FAKE" in badge.text()


def test_production_window_title_has_no_demo_suffix(qtbot):
    window = CockpitMainWindow(allow_fake_backend=False)
    qtbot.addWidget(window)
    assert "演示模式" not in window.windowTitle()


def _pump(window, qtbot, predicate, timeout_s=8.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        window._poll_live()
        window._poll_health()
        qtbot.wait(20)
        if predicate():
            return
    raise AssertionError("timed out waiting for cockpit condition")


def test_record_stop_review_writes_real_mf4(cockpit, qtbot):
    w = cockpit
    w._on_main_button()
    _pump(w, qtbot, lambda: w._state_machine.state == CockpitState.CONNECTED_IDLE)

    w._on_main_button()
    assert w._state_machine.state == CockpitState.RECORDING
    assert w._capture_controller is not None
    _pump(w, qtbot, lambda: w._capture_controller.writer.write_count > 0)

    w._on_main_button()
    assert w._last_stop_result is not None
    mf4 = Path(w._last_stop_result.summary.output_mf4)
    assert mf4.exists()
    assert mf4.with_suffix(".session_summary.json").exists()
    assert mf4.with_suffix(".preflight.json").exists()

    _df, channels, _units = DataLoader.load_mf4(mf4)
    assert "DemoSignal" in channels

    assert w._state_machine.state == CockpitState.REVIEW_MODAL
    w._review_modal.reject()
    qtbot.wait(50)
    assert w._state_machine.state == CockpitState.CONNECTED_IDLE
    assert w._capture_controller is None


def test_second_session_produces_distinct_file(cockpit, qtbot):
    w = cockpit
    w._on_main_button()
    _pump(w, qtbot, lambda: w._state_machine.state == CockpitState.CONNECTED_IDLE)

    outputs = []
    for _ in range(2):
        w._on_main_button()
        _pump(w, qtbot, lambda: w._capture_controller.writer.write_count > 0)
        w._on_main_button()
        outputs.append(w.last_session_summary.output_mf4)
        w._review_modal.reject()
        qtbot.wait(50)
        assert w._state_machine.state == CockpitState.CONNECTED_IDLE

    assert outputs[0] != outputs[1]
    assert all(Path(p).exists() for p in outputs)
