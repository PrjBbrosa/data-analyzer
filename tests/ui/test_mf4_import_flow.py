"""Real MainWindow import path for MF4 shared-axis diagnostics."""
from __future__ import annotations

import pytest

from tests._helpers.mf4_factory import write_signal_groups_mf4


def _window(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


def _capture(monkeypatch, window):
    notices = []

    def capture_notice(message, level="info"):
        notices.append((message, level))

    monkeypatch.setattr(window, "toast", capture_notice)
    return notices


def test_load_mf4_warns_on_alignment(qapp, qtbot, tmp_path, monkeypatch):
    path = write_signal_groups_mf4(tmp_path / "coverage.mf4", [
        [("fast", [0, 1, 2, 3, 4], [0, 0.25, 0.5, 0.75, 1])],
        [("slow", [10, 20, 30], [0, 5, 10])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    window._load_one(str(path))
    assert any(
        level == "warning" and "时间范围" in message
        for message, level in notices
    )


def test_load_mf4_warns_when_duplicate_times_are_collapsed(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = write_signal_groups_mf4(tmp_path / "ties.mf4", [
        [("long", [1, 1, 1, 1], [0, 0.01, 0.02, 0.03])],
        [("short", [0, 1, 5, 9], [0, 0.01, 0.01, 0.03])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    window._load_one(str(path))
    assert any(
        level == "warning" and "最后值" in message
        for message, level in notices
    )
    assert any(level == "success" for _message, level in notices)


def test_load_mf4_warns_when_a_clock_regresses(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = write_signal_groups_mf4(tmp_path / "reset.mf4", [
        [("clock", [0, 0, 0, 0], [0, 1, 2, 3])],
        [("wound", [1, 4, 2, 3], [0, 3, 1, 2])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    window._load_one(str(path))
    assert any(
        level == "warning" and "时间回退" in message
        for message, level in notices
    )
    assert window.files


def test_load_mf4_disagreed_single_points_do_not_open_a_file(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = write_signal_groups_mf4(tmp_path / "split.mf4", [
        [("a", [1.0], [0.0])],
        [("b", [2.0], [10.0])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    errors = []
    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window._project_io_mixin.QMessageBox.critical",
        lambda *args, **kwargs: errors.append(args),
    )
    before = set(window.files)
    window._load_one(str(path))
    assert errors
    assert "单点" in str(errors[-1])
    assert set(window.files) == before
    assert not any(level == "success" for _message, level in notices)


def test_load_mf4_alignment_warnings_stay_bounded(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = write_signal_groups_mf4(tmp_path / "many.mf4", [
        [("fast", [0, 1, 2, 3, 4], [0, 0.25, 0.5, 0.75, 1])],
        [("slow", [10, 20, 30], [0, 5, 10])],
        [("tied", [1, 1, 2], [0, 0, 1])],
        [("wound", [1, 2, 3], [0, 2, 1])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    window._load_one(str(path))
    warnings = [message for message, level in notices if level == "warning"]
    alignment = [
        message for message in warnings
        if message.startswith(("时间整理", "已按公共", "无法对齐"))
        or "时间范围" in message
        or "端点填充" in message
    ]
    assert len(alignment) <= 3
    assert len(alignment) == len(set(alignment))
