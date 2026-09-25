"""Tests for the read-only Acquisition Cockpit Replay tab."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt5.QtWidgets import QLabel

from mf4_analyzer.acquisition_capture.backends import ReplayRecorderBackend
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.writer import Mf4Writer
from mf4_analyzer.acquisition_ui.replay_tab import ReplayTab


def _write_replay_mf4(path: Path) -> Path:
    selected = (
        SelectedMeasurement(name="EngSpdAvg", unit="rpm"),
        SelectedMeasurement(name="EngTrqAct", unit="Nm"),
    )
    writer = Mf4Writer(path, selected)
    for ts, a, b in (
        (0.0, 1000.0, 10.0),
        (0.05, 1010.0, 11.0),
        (0.10, 1020.0, 12.0),
    ):
        writer.append("EngSpdAvg", ts, a)
        writer.append("EngTrqAct", ts, b)
    return writer.finalize()


def test_replay_placeholder_copy_is_replay_specific(qtbot):
    tab = ReplayTab()
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)

    canvas = tab._live_cards._disconnected_canvas
    title = canvas.findChild(QLabel, "cockpitDisconnectedTitle").text()
    action = canvas.findChild(QLabel, "cockpitDisconnectedAction").text()
    assert title == "未加载 MF4"
    assert "连接 ECU" not in action
    assert not tab._right_panel.isVisible()


def test_replay_has_no_connection_checklist(qtbot):
    """B-5: the shared ``LiveCardGrid`` checklist API defaults to ``None``,
    so Replay — which never calls ``set_connection_checklist`` — shows the
    plain ``未加载 MF4`` placeholder with NO ECU-semantic checklist rows.

    Calling the Replay-specific ``set_placeholder_copy`` must not surface an
    ECU checklist either."""
    from PyQt5.QtWidgets import QFrame

    tab = ReplayTab()
    qtbot.addWidget(tab)

    frame = tab._live_cards.findChild(QFrame, "cockpitConnectionChecklist")
    assert frame is not None
    assert frame.isHidden()
    assert frame.findChildren(QLabel, "cockpitChecklistLabel") == []

    # Re-applying the Replay placeholder copy leaves the checklist hidden.
    tab._live_cards.set_placeholder_copy(
        title="未加载 MF4",
        body="回放会在这里显示信号趋势与当前值。",
        action="使用左上「选择 MF4」打开录制文件",
    )
    assert frame.isHidden()
    assert frame.findChildren(QLabel, "cockpitChecklistLabel") == []


def test_replay_tab_loads_existing_mf4(qapp, tmp_path: Path):
    mf4_path = _write_replay_mf4(tmp_path / "source.mf4")
    tab = ReplayTab()
    try:
        tab.load_file(mf4_path)

        assert tab.source_path == mf4_path
        assert tab.state == "idle"
        assert set(tab.live_cards.cards) == {"EngSpdAvg", "EngTrqAct"}

        tab.play()
        tab.drain_once()

        assert tab.state == "playing"
        assert isinstance(tab.backend, ReplayRecorderBackend)
        assert tab.position_slider.maximum() == 100
    finally:
        tab.close()


def test_replay_right_panel_survives_capture_refactor(qapp, tmp_path: Path):
    """B-4 boundary: dropping the *capture* right pane must NOT touch Replay.

    ``ReplayTab`` still owns its own ``RightPanel`` via the public accessor,
    shows it after loading an MF4, and play/stop keep working.
    """
    mf4_path = _write_replay_mf4(tmp_path / "source.mf4")
    tab = ReplayTab()
    try:
        tab.show()
        qapp.processEvents()
        assert tab.right_panel is tab._right_panel

        tab.load_file(mf4_path)
        qapp.processEvents()
        assert tab.right_panel.isVisible()

        tab.play()
        tab.drain_once()
        assert tab.state == "playing"

        tab.stop()
        assert tab.state == "stopped"
    finally:
        tab.close()


def test_replay_speed_control_changes_emit_rate(qapp, tmp_path: Path):
    mf4_path = _write_replay_mf4(tmp_path / "source.mf4")
    tab = ReplayTab()
    try:
        tab.load_file(mf4_path)
        tab.set_speed_multiplier(4.0)

        tab.play()

        assert tab.backend is not None
        assert tab.backend.speed_multiplier == 4.0
        assert tab.speed_multiplier == 4.0
    finally:
        tab.close()


def test_replay_stop_returns_to_stopped_without_capture_state_change(qapp, tmp_path: Path):
    mf4_path = _write_replay_mf4(tmp_path / "source.mf4")
    capture_state = {"value": "ConnectedIdle"}
    tab = ReplayTab()
    try:
        tab.load_file(mf4_path)
        tab.play()
        tab.drain_once()

        tab.stop()

        assert tab.state == "stopped"
        assert capture_state["value"] == "ConnectedIdle"
        assert not list(tmp_path.glob("*.session_summary.json"))
        assert not (tmp_path / "manifest.json").exists()
    finally:
        tab.close()


def _late_replay_mf4(tmp_path: Path) -> Path:
    from tests._helpers.mf4_factory import write_signal_groups_mf4

    ref = [0.0, 1.0, 2.0, 3.0, 4.0]
    return write_signal_groups_mf4(tmp_path / "late.mf4", [
        [("ref", [0.0, 1.0, 2.0, 3.0, 4.0], ref, "V")],
        [("late", [10.0, 20.0, 30.0], [2.0, 2.5, 3.0], "Nm")],
    ])


def test_replay_warning_is_visible_before_play_and_follows_the_source(
    qapp, qtbot, tmp_path: Path,
):
    warning_path = _late_replay_mf4(tmp_path)
    clean_path = _write_replay_mf4(tmp_path / "clean.mf4")
    tab = ReplayTab()
    qtbot.addWidget(tab)
    tab.resize(960, 600)
    tab.show()
    qapp.processEvents()
    enabled_with_text = []
    real_enable = tab._set_transport_enabled

    def _record_enable(enabled):
        if enabled:
            enabled_with_text.append(tab._alignment_warning.text())
        real_enable(enabled)

    tab._set_transport_enabled = _record_enable
    try:
        tab.load_file(warning_path)
        qapp.processEvents()
        warning = tab._alignment_warning
        assert warning.isVisible()
        assert "已按公共时间轴对齐，可能包含非原始测量值" in warning.text()
        assert "端点填充" in warning.text()
        assert enabled_with_text and "端点填充" in enabled_with_text[-1]
        assert tab._play_btn.isEnabled()
        assert warning.wordWrap()
        assert warning.height() > warning.fontMetrics().lineSpacing() + 2
        assert tab._play_btn.geometry().bottom() <= warning.geometry().top()
        assert tab._play_btn.geometry().right() <= tab.width()

        tab.play()
        tab.pause()
        assert warning.text() == enabled_with_text[-1]
        tab.stop()
        assert "端点填充" in warning.text()
        assert tab.state == "stopped"

        tab.load_file(clean_path)
        qapp.processEvents()
        assert not warning.isVisible()
        assert warning.text() == ""
        assert tab._play_btn.isEnabled()
        assert tab.state == "idle"

        tab.load_file(warning_path)
        old_text = warning.text()
        with pytest.raises(Exception):
            tab.load_file(tmp_path / "missing.mf4")
        assert tab._source is not None
        assert tab._source.path == warning_path
        assert warning.text() == old_text
        assert warning.isVisible()
        assert tab._play_btn.isEnabled()
    finally:
        tab.close()
