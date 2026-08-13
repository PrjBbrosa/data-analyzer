"""UltraView Board persistence through MainWindow save/open."""
from __future__ import annotations

import csv
import json

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.ultraview_state import (
    UltraViewRef,
    add_ref,
    membership_set,
)
from tests.ui.ultraview_fakes import ComputeProbe


def _write_csv(path, n=40):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "rpm"])
        for i in range(n):
            writer.writerow([i / 100.0, float(i)])


def test_save_from_ultraview_writes_last_source_mode_and_board(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a)
    proj = tmp_path / "uv.tlproj"
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    time_id = str(win.view_manager.get(0).view_id)
    fft_id = str(win.analysis_managers["fft"].get(0).view_id)
    uv = win._ultraview

    win.toolbar.btn_mode_fft.click()
    QCoreApplication.processEvents()
    win.toolbar.btn_mode_ultraview.click()
    QCoreApplication.processEvents()
    uv.add_from_source_tab("time", time_id)
    uv.add_from_source_tab("fft", fft_id)
    add_ref(uv.board, UltraViewRef("fft", "ghost-view"))
    uv.board.name = "整车问题总览"
    uv._on_layout("grid_2x2")
    uv._on_show_titles(False)
    uv._on_show_sources(True)
    probe = ComputeProbe().install(win)
    pending_before = set(win._analysis_restore_pending)
    try:
        assert win.save_project(proj) is True
        assert probe.compute_total == 0
        assert probe.job_total == 0
        assert probe.store_new_key_writes == 0
        assert set(win._analysis_restore_pending) == pending_before
    finally:
        probe.restore()

    raw = json.loads(proj.read_text(encoding="utf-8"))
    assert raw["current_mode"] == "fft"
    assert raw["schema_version"] == 2
    board = raw["ultraview"]["board"]
    assert board["name"] == "整车问题总览"
    assert board["layout_id"] == "grid_2x2"
    assert board["show_titles"] is False
    view_ids = {item["view_id"] for item in board["placements"]} | {
        item["view_id"] for item in board["unplaced"]
    }
    assert time_id in view_ids
    assert fft_id in view_ids
    assert "ghost-view" in view_ids
    text = json.dumps(raw["ultraview"])
    for needle in ("digest", "selected", "presentation", "QImage", "captured_digest"):
        assert needle not in text


def test_reopen_restores_board_without_entering_ultraview(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a)
    proj = tmp_path / "uv.tlproj"
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    time_id = str(win.view_manager.get(0).view_id)
    fft_id = str(win.analysis_managers["fft"].get(0).view_id)
    uv = win._ultraview
    win.toolbar.btn_mode_fft.click()
    QCoreApplication.processEvents()
    win.toolbar.btn_mode_ultraview.click()
    QCoreApplication.processEvents()
    uv.add_from_source_tab("time", time_id)
    uv.add_from_source_tab("fft", fft_id)
    add_ref(uv.board, UltraViewRef("order", "ghost-view"))
    uv.board.name = "重开对比"
    uv._on_layout("grid_2x2")
    win.save_project(proj)

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    QCoreApplication.processEvents()

    assert restored.chart_stack.current_mode() == "fft"
    assert restored.toolbar.current_mode() == "fft"
    board = restored._ultraview.board
    assert board.name == "重开对比"
    assert board.layout_id == "grid_2x2"
    page = restored.chart_stack.page_ultraview
    live_time = UltraViewRef("time", str(restored.view_manager.get(0).view_id))
    ghost = UltraViewRef("order", "ghost-view")
    assert live_time in membership_set(board)
    assert ghost in membership_set(board)
    assert restored._ultraview.store.get(live_time) is None
    assert page._status_for(live_time) == "missing"
    assert page._status_for(ghost) == "orphaned"
    assert restored._analysis_restore_pending == set() or all(
        section != "ultraview" for section, _view_id in restored._analysis_restore_pending
    )


def test_open_project_parse_failure_keeps_board(qapp, qtbot, tmp_path):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    view_id = str(win.view_manager.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", view_id))
    uv.board.name = "解析失败保留"
    bad = tmp_path / "broken.tlproj"
    bad.write_text("{not-json", encoding="utf-8")
    try:
        win.open_project(bad)
        raise AssertionError("open_project should reject invalid JSON")
    except ValueError:
        pass
    assert uv.board.name == "解析失败保留"
    assert UltraViewRef("time", view_id) in membership_set(uv.board)


def test_open_project_cancel_keeps_board(qapp, qtbot, tmp_path, monkeypatch):
    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a)
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    uv = win._ultraview
    view_id = str(win.view_manager.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", view_id))
    uv.board.name = "取消打开保留"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    win._open_paths([str(tmp_path / "other.tlproj")])
    assert uv.board.name == "取消打开保留"
    assert UltraViewRef("time", view_id) in membership_set(uv.board)


def test_open_project_keeps_page_hooks_and_toasts_ultraview_warnings(
    qapp, qtbot, tmp_path, monkeypatch
):
    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a)
    proj = tmp_path / "uv.tlproj"
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    win.save_project(proj)
    raw = json.loads(proj.read_text(encoding="utf-8"))
    raw["ultraview"] = {
        "schema": 1,
        "board": {
            "board_id": "board-1",
            "name": "坏布局",
            "layout_id": "not-a-layout",
            "primary_ratio": 0.67,
            "show_titles": True,
            "show_sources": True,
            "placements": [
                {"slot_id": "primary", "section": "time", "view_id": "keep"},
            ],
            "unplaced": [],
        },
    }
    proj.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    restored = MainWindow()
    qtbot.addWidget(restored)
    uv = restored._ultraview
    page = restored.chart_stack.page_ultraview
    hooks_before = len(uv._page_hooks)
    toasts = []
    monkeypatch.setattr(
        restored, "toast", lambda msg, level="info": toasts.append((msg, level)),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)

    restored.open_project(proj)
    QCoreApplication.processEvents()

    assert restored._ultraview.board.layout_id == "hero_left_4"
    assert any("总览布局" in msg for msg, level in toasts if level == "warning")
    assert len(uv._page_hooks) == hooks_before
    view_id = str(restored.view_manager.get(0).view_id)
    page.add_ref_requested.emit("time", view_id)
    assert UltraViewRef("time", view_id) in membership_set(uv.board)
    page.layout_changed.emit("grid_2x2")
    assert uv.board.layout_id == "grid_2x2"
