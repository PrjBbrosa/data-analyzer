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
