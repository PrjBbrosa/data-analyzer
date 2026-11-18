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


def test_replay_tab_loads_existing_mf4(qtbot, qapp, tmp_path: Path):
    mf4_path = _write_replay_mf4(tmp_path / "source.mf4")
    tab = ReplayTab()
    try:
        tab.load_file(mf4_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)

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


def test_replay_right_panel_survives_capture_refactor(qtbot, qapp, tmp_path: Path):
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
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        qapp.processEvents()
        assert tab.right_panel.isVisible()

        tab.play()
        tab.drain_once()
        assert tab.state == "playing"

        tab.stop()
        assert tab.state == "stopped"
    finally:
        tab.close()


def test_replay_speed_control_changes_emit_rate(qtbot, qapp, tmp_path: Path):
    mf4_path = _write_replay_mf4(tmp_path / "source.mf4")
    tab = ReplayTab()
    try:
        tab.load_file(mf4_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        tab.set_speed_multiplier(4.0)

        tab.play()

        assert tab.backend is not None
        assert tab.backend.speed_multiplier == 4.0
        assert tab.speed_multiplier == 4.0
    finally:
        tab.close()


def test_replay_stop_returns_to_stopped_without_capture_state_change(qtbot, qapp, tmp_path: Path):
    mf4_path = _write_replay_mf4(tmp_path / "source.mf4")
    capture_state = {"value": "ConnectedIdle"}
    tab = ReplayTab()
    try:
        tab.load_file(mf4_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
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


def test_replay_warning_is_visible_before_play_and_follows_the_source(monkeypatch,
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
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        qapp.processEvents()
        warning = tab._alignment_warning
        assert warning.isVisible()
        assert "没有补点" in warning.text()
        assert "端点填充" not in warning.text()
        assert enabled_with_text and "没有补点" in enabled_with_text[-1]
        assert tab._play_btn.isEnabled()
        assert warning.wordWrap()
        assert warning.height() > warning.fontMetrics().lineSpacing() + 2
        assert tab._play_btn.geometry().bottom() <= warning.geometry().top()
        assert tab._play_btn.geometry().right() <= tab.width()

        tab.play()
        tab.pause()
        assert warning.text() == enabled_with_text[-1]
        tab.stop()
        assert "没有补点" in warning.text()
        assert tab.state == "stopped"

        tab.load_file(clean_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        qapp.processEvents()
        assert not warning.isVisible()
        assert warning.text() == ""
        assert tab._play_btn.isEnabled()
        assert tab.state == "idle"

        tab.load_file(warning_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        old_text = warning.text()
        errors = []
        monkeypatch.setattr(
            "mf4_analyzer.acquisition_ui.replay_tab.QMessageBox.critical",
            lambda *args: errors.append(args),
        )
        tab.load_file(tmp_path / "missing.mf4")
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        assert len(errors) == 1
        assert tab._source is not None
        assert tab._source.path == warning_path
        assert warning.text() == old_text
        assert warning.isVisible()
        assert tab._play_btn.isEnabled()
    finally:
        tab.close()


def _write_reset_channel_mf4(path: Path, *, samples=None, timestamps=None,
                             name: str = "Torque", invalid: bool = False) -> Path:
    from asammdf import MDF, Signal
    import numpy as np

    values = np.asarray([0, 1, 2, 3, 4, 5] if samples is None else samples, dtype=float)
    stamps = np.asarray(
        [0.0, 0.1, 0.2, 0.0, 0.1, 0.2] if timestamps is None else timestamps,
        dtype=float,
    )
    kwargs = {}
    if invalid:
        kwargs["invalidation_bits"] = np.ones(values.shape[0], dtype=np.uint8)
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=values, timestamps=stamps, name=name, unit="Nm", **kwargs)])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def _write_grouped_mf4(path: Path, groups) -> Path:
    from tests._helpers.mf4_factory import write_signal_groups_mf4
    return write_signal_groups_mf4(path, groups)


def _segment_combo(tab):
    from PyQt5.QtWidgets import QComboBox
    return tab.findChild(QComboBox, "replaySegmentCombo")


def _choose_segment(tab, segment):
    combo = _segment_combo(tab)
    assert combo is not None and combo.isVisible()
    for index in range(combo.count()):
        if combo.itemData(index) == segment:
            combo.setCurrentIndex(index)
            return combo
    raise AssertionError(segment)


def _card_values(tab, name: str):
    return [value for _ts, value in tab.live_cards.cards[name]._spark._buffer]


def _close_replay(tab, qapp=None):
    tab._timer.stop()
    if tab._backend is not None:
        tab._backend.stop()
    tab.close()
    if qapp is not None:
        qapp.processEvents()


def test_reset_file_disables_play_and_guards_direct_play(qtbot, qapp, tmp_path: Path):
    path = _write_reset_channel_mf4(tmp_path / "reset.mf4")
    tab = ReplayTab()
    qtbot.addWidget(tab)
    tab.resize(1200, 720)
    tab.show()
    try:
        tab.load_file(path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        qapp.processEvents()
        warning = tab._alignment_warning
        assert warning.isVisible()
        assert "段" in warning.text()
        assert tab._play_btn.isEnabled() is False
        assert tab._timer.isActive() is False
        tab._play_btn.setEnabled(True)
        tab.play()
        assert tab.backend is None
        assert tab._timer.isActive() is False
        assert tab.state != "playing"
        assert not tab._source.source_samples

        combo = _choose_segment(tab, 0)
        assert "段 1" in combo.currentText()
        assert "可播放 3" in combo.currentText()
        assert tab._play_btn.isEnabled()
        tab.set_speed_multiplier(1000.0)
        tab.play()
        qtbot.waitUntil(lambda: tab.state == "stopped", timeout=3000)
        assert _card_values(tab, "Torque") == pytest.approx([0.0, 1.0, 2.0])

        tab.play()
        qtbot.waitUntil(lambda: tab.state == "stopped", timeout=3000)
        assert _card_values(tab, "Torque") == pytest.approx([0.0, 1.0, 2.0])

        tab.set_speed_multiplier(0.001)
        tab.play()
        tab._timer.stop()
        tab.drain_once()
        assert tab.state == "playing"
        assert _card_values(tab, "Torque") == pytest.approx([0.0])
        tab.pause()
        assert tab.state == "paused"
        assert tab._timer.isActive() is False
        held = list(_card_values(tab, "Torque"))
        tab.drain_once()
        assert _card_values(tab, "Torque") == held
        tab.play()
        assert tab.state == "playing"
        _choose_segment(tab, 1)
        assert "段 2" in _segment_combo(tab).currentText()
        tab._timer.stop()
        tab.drain_once()
        assert _card_values(tab, "Torque") == pytest.approx([3.0])
        assert tab.position_slider.value() == 0
        assert tab.position_slider.maximum() == 200
        tab.set_speed_multiplier(1000.0)
        tab._timer.start()
        qtbot.waitUntil(lambda: tab.state == "stopped", timeout=3000)
        assert _card_values(tab, "Torque") == pytest.approx([3.0, 4.0, 5.0])

        _choose_segment(tab, None)
        assert tab._play_btn.isEnabled() is False
        assert tab.backend is None or tab.backend.status().started is False
        assert tab._timer.isActive() is False
        assert _card_values(tab, "Torque") == []
        tab.play()
        assert tab.state != "playing"
    finally:
        _close_replay(tab, qapp)


def test_replay_segment_edges_cancel_reload_and_parent_close(qtbot, qapp, tmp_path: Path, monkeypatch):
    from threading import Event
    from PyQt5.QtWidgets import QWidget
    from tests._helpers.mf4_factory import write_single_channel_mf4

    invalid_path = _write_reset_channel_mf4(tmp_path / "invalid.mf4", invalid=True)
    single_path = write_single_channel_mf4(
        tmp_path / "one.mf4", name="Mark", unit="Nm",
        timestamps=[1.25], samples=[4.0],
    )
    shared_path = _write_grouped_mf4(tmp_path / "shared.mf4", [[
        ("Torque", [0, 1, 2, 3, 4, 5], [0.0, 0.1, 0.2, 0.0, 0.1, 0.2], "Nm"),
        ("Speed", [10, 11, 12, 13, 14, 15], [0.0, 0.1, 0.2, 0.0, 0.1, 0.2], "rpm"),
    ]])
    split_path = _write_grouped_mf4(tmp_path / "split.mf4", [
        [("Torque", [0, 1, 2, 3, 4, 5], [0.0, 0.1, 0.2, 0.0, 0.1, 0.2], "Nm")],
        [("Speed", [10, 11, 12], [0.0, 0.1, 0.0], "rpm")],
    ])
    clean_path = _write_replay_mf4(tmp_path / "clean.mf4")
    parent = QWidget()
    qtbot.addWidget(parent)
    tab = ReplayTab(parent=parent)
    parent.resize(1200, 720)
    parent.show()
    release = Event()
    try:
        tab.load_file(invalid_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        _choose_segment(tab, 0)
        assert tab._play_btn.isEnabled() is False
        assert "失效" in tab._alignment_warning.text() or "可播放" in tab._alignment_warning.text()
        tab.play()
        assert tab.backend is None
        assert tab._timer.isActive() is False

        tab.load_file(single_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        qapp.processEvents()
        assert tab._play_btn.isEnabled()
        assert "单点" in tab._alignment_warning.text()
        assert _segment_combo(tab) is None or not _segment_combo(tab).isVisible()
        tab.play()
        assert tab.backend is not None
        assert tab.backend._source[0][1] == pytest.approx(1.25)
        assert tab.backend._source[0][2] == pytest.approx(4.0)
        tab.stop()

        tab.load_file(shared_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        _choose_segment(tab, 0)
        tab.set_speed_multiplier(1000.0)
        tab.play()
        qtbot.waitUntil(lambda: tab.state == "stopped", timeout=3000)
        assert _card_values(tab, "Torque") == pytest.approx([0.0, 1.0, 2.0])
        assert _card_values(tab, "Speed") == pytest.approx([10.0, 11.0, 12.0])

        tab.load_file(split_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        qapp.processEvents()
        assert tab._play_btn.isEnabled() is False
        assert "局部段号" in tab._alignment_warning.text()
        combo = _segment_combo(tab)
        assert combo is None or not combo.isVisible()
        tab.play()
        assert tab.backend is None
        assert tab._source.source_samples == []

        written = []
        monkeypatch.setattr(
            "PyQt5.QtCore.QSettings.setValue",
            lambda *args, **kwargs: written.append(args),
        )
        tab.load_file(clean_path)
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        qapp.processEvents()
        assert tab.source_path == clean_path
        assert tab._play_btn.isEnabled()
        assert _segment_combo(tab) is None or not _segment_combo(tab).isVisible()
        assert "局部段号" not in tab._alignment_warning.text()
        assert written == []
        text = Path(__file__).resolve().parents[2].joinpath(
            "mf4_analyzer", "acquisition_ui", "replay_tab.py",
        ).read_text(encoding="utf-8")
        assert "QSettings" not in text

        stale_path = _write_reset_channel_mf4(tmp_path / "stale.mf4")
        entered, release = Event(), Event()
        real_broker = tab._imports.broker

        def broker(method, path, **kwargs):
            if Path(str(path)) == stale_path:
                entered.set()
                assert release.wait(3)
            return real_broker(method, path, **kwargs)

        tab._imports.broker = broker
        tab.load_file(stale_path)
        qtbot.waitUntil(entered.is_set, timeout=20000)
        tab.load_file(clean_path)
        release.set()
        qtbot.waitUntil(lambda: not tab._imports.busy, timeout=20000)
        assert tab.source_path == clean_path
        assert tab._play_btn.isEnabled()
        parent.close()
        qapp.processEvents()
        assert tab._timer.isActive() is False
        assert tab.backend is None or tab.backend.status().started is False
    finally:
        release.set()
        _close_replay(tab, qapp)
        parent.close()
        qapp.processEvents()


def test_replay_import_keeps_gui_live_and_parent_close_cancels(qtbot, monkeypatch):
    from threading import Event
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QWidget
    from mf4_analyzer.ui.main_window import import_coordinator

    entered, release = Event(), Event()

    def broker(*args, cancel_check, **kwargs):
        entered.set()
        assert release.wait(2)
        assert cancel_check()
        return None  # cancellation discards it before ReplaySource conversion

    monkeypatch.setattr(import_coordinator, 'run_import', broker)
    parent = QWidget()
    qtbot.addWidget(parent)
    tab = ReplayTab(parent=parent)
    parent.show()
    ticks = []
    timer = QTimer(parent)
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    tab.load_file('slow.mf4')
    assert tab.source_path is None
    qtbot.waitUntil(entered.is_set)
    qtbot.waitUntil(lambda: len(ticks) >= 4)
    parent.close()
    assert tab._imports.closing and tab._imports.busy
    release.set()
    qtbot.waitUntil(lambda: not tab._imports.busy)
    qtbot.waitUntil(lambda: not parent.isVisible())
    assert tab.source_path is None
    assert tab.state == 'idle'


def test_replay_resource_failure_uses_the_shared_copy(qtbot, monkeypatch):
    from mf4_analyzer.io.import_limits import parse_resource_envelope, resource_user_text
    from mf4_analyzer.io.import_process import ImportProcessError

    label = "MDF shared-axis conversion/alignment/frame"
    exc = ImportProcessError(
        "resource_limit",
        "导入资源超过预算",
        stage="admission",
        detail="worker detail",
        resource=parse_resource_envelope({
            "schema": 1,
            "resource_kind": "memory_estimate",
            "unit": "bytes",
            "requested": 638_976_000,
            "limit": 498_988_944,
            "phase": "admission",
            "estimate_basis": "test",
            "label": label,
        }),
        request_id="req-replay-1",
    )
    tab = ReplayTab()
    qtbot.addWidget(tab)
    shown = []
    monkeypatch.setattr(
        "mf4_analyzer.acquisition_ui.replay_tab.QMessageBox.critical",
        lambda *args: shown.append(args),
    )
    tab._on_import_done("failed", exc)
    assert shown
    assert shown[-1][1] == "无法加载回放文件"
    assert shown[-1][2] == resource_user_text(exc)
    assert label not in shown[-1][2]
    shown.clear()
    tab._on_import_done("failed", RuntimeError("plain boom"))
    assert "plain boom" in shown[-1][2]
    source = Path(__file__).resolve().parents[2].joinpath(
        "mf4_analyzer", "acquisition_ui", "replay_tab.py",
    ).read_text(encoding="utf-8")
    assert "accept_resource_recheck" not in source
    assert "worker_request_id" not in source
