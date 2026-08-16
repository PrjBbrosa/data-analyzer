"""UltraView Board persistence through MainWindow save/open."""
from __future__ import annotations

import csv
import json
import pytest
from PyQt5.QtGui import QColor, QImage

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.ultraview_state import (
    LAYOUT_MODE_FREE_GRID,
    PreviewMeta,
    UltraViewRef,
    add_ref,
    default_workspace,
    free_grid_placement_for,
    membership_set,
    normalize_workspace_payload,
    workspace_to_payload,
)
from tests.ui.ultraview_fakes import ComputeProbe


def _write_csv(path, n=40):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "rpm"])
        for i in range(n):
            writer.writerow([i / 100.0, float(i)])


def _preview_image():
    image = QImage(32, 24, QImage.Format_ARGB32)
    image.fill(QColor("#336699"))
    return image


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
    win.open_ultraview()
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
    board = raw["ultraview"]["workspace"]["boards"][0]
    assert board["name"] == "整车问题总览"
    assert board["layout_id"] == "grid_2x2"
    assert board["show_titles"] is False
    view_ids = {item["view_id"] for item in board["placements"]} | {
        item["view_id"] for item in board["unplaced"]
    }
    assert time_id in view_ids
    assert fft_id in view_ids
    assert "ghost-view" in view_ids
    assert raw["ultraview"]["schema"] == 4
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
    win.open_ultraview()
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
    # No sidecar / no capture in this fixture: reopen is missing, not a
    # loosely accepted fresh/stale/missing union (UV-P3-A14).
    assert page._status_for(live_time) == "missing"
    assert page._status_for(ghost) == "orphaned"
    assert restored._analysis_restore_pending == set() or all(
        section != "ultraview" for section, _view_id in restored._analysis_restore_pending
    )


def test_save_reopen_restores_workspace_card_action_preference(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "workspace-preference.csv"
    proj = tmp_path / "workspace-preference.tlproj"
    _write_csv(csv_a)
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    uv = win._ultraview

    assert uv.workspace.show_card_actions is False
    uv._on_show_card_actions(True)
    assert win.save_project(proj) is True

    raw = json.loads(proj.read_text(encoding="utf-8"))["ultraview"]
    assert raw["schema"] == 4
    assert raw["workspace"]["show_card_actions"] is True
    assert all(
        "show_card_actions" not in board
        for board in raw["workspace"]["boards"]
    )

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    QCoreApplication.processEvents()
    page = restored.chart_stack.page_ultraview
    assert restored._ultraview.workspace.show_card_actions is True
    assert page.board_toolbar()._act_card_actions.isChecked() is True
    assert page._display_card_actions.isChecked() is True


def test_project_restore_and_reset_clear_transient_filter_and_library_pin(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    page = win.chart_stack.page_ultraview

    page.set_compare_filter("frequency")
    page.set_library_visible(True)
    page.library_panel().set_pinned(True)
    assert page.compare_filter() == "frequency"
    assert page.library_panel().is_pinned() is True

    assert uv.restore_project_state(workspace_to_payload(default_workspace())) == []
    assert page.compare_filter() == "all"
    assert page.library_panel().is_pinned() is False

    page.set_compare_filter("frequency")
    page.set_library_visible(True)
    page.library_panel().set_pinned(True)
    uv.reset_project_state()
    assert page.compare_filter() == "all"
    assert page.library_panel().is_pinned() is False


def test_project_sidecar_restores_shared_preview_without_compute(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "sidecar.csv"
    proj = tmp_path / "sidecar.tlproj"
    _write_csv(csv_a)
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    add_ref(uv.board, ref)
    from mf4_analyzer.ui.ultraview_state import PreviewMeta
    assert uv.store.publish(
        ref, _preview_image(), digest="snapshot", meta=PreviewMeta(ref=ref, title="Sidecar")
    )
    assert win.save_project(proj)
    raw = json.loads(proj.read_text(encoding="utf-8"))
    assert raw["ultraview"]["preview_sidecar"]["path"].endswith(".uvpz")
    restored = MainWindow()
    qtbot.addWidget(restored)
    probe = ComputeProbe().install(restored)
    try:
        restored.open_project(proj)
        QCoreApplication.processEvents()
        new_ref = UltraViewRef("time", str(restored.view_manager.get(0).view_id))
        assert restored._ultraview.store.get(new_ref) is not None
        assert probe.compute_total == probe.job_total == probe.store_new_key_writes == 0
    finally:
        probe.restore()


def test_sidecar_lazy_load_decodes_after_restore_returns(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "lazy.csv"
    proj = tmp_path / "lazy.tlproj"
    _write_csv(csv_a)
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    add_ref(uv.board, ref)
    from mf4_analyzer.ui.ultraview_state import PreviewMeta
    assert uv.store.publish(
        ref, _preview_image(), digest="snapshot", meta=PreviewMeta(ref=ref)
    )
    assert win.save_project(proj)
    payload = json.loads(proj.read_text(encoding="utf-8"))["ultraview"]
    restored = MainWindow()
    qtbot.addWidget(restored)
    restored_uv = restored._ultraview
    restored_uv.restore_project_state(payload, project_path=str(proj))
    restored_uv._sidecar_timer.stop()
    assert restored_uv.store.get(ref) is None
    assert restored_uv._sidecar_pending
    restored_uv._on_sidecar_load_timeout()
    assert restored_uv.store.get(ref) is not None


def test_failed_sidecar_save_as_drops_old_project_relative_descriptor(qapp, qtbot, tmp_path, monkeypatch):
    csv_a = tmp_path / "sidecar-save-as.csv"
    source_project = tmp_path / "source.tlproj"
    target_project = tmp_path / "target.tlproj"
    _write_csv(csv_a)
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    add_ref(uv.board, ref)
    from mf4_analyzer.ui.ultraview_state import PreviewMeta
    assert uv.store.publish(ref, _preview_image(), digest="snapshot", meta=PreviewMeta(ref=ref))
    assert win.save_project(source_project)
    assert uv.workspace.preview_sidecar is not None

    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window.ultraview_coordinator.save_preview_sidecar",
        lambda *_args, **_kwargs: type("Result", (), {"ok": False, "warnings": ()})(),
    )
    assert win.save_project(target_project)
    raw = json.loads(target_project.read_text(encoding="utf-8"))
    assert "preview_sidecar" not in raw["ultraview"]


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


def test_free_grid_project_roundtrip_keeps_layout_id_and_placements(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "grid.csv"
    _write_csv(csv_a)
    proj = tmp_path / "grid.tlproj"
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    time_id = str(win.view_manager.get(0).view_id)
    fft_id = str(win.analysis_managers["fft"].get(0).view_id)
    uv = win._ultraview
    win.open_ultraview()
    QCoreApplication.processEvents()
    uv.add_from_source_tab("time", time_id)
    uv.add_from_source_tab("fft", fft_id)
    uv._on_layout("grid_3x3")
    uv._on_free_grid_toggled(True)
    assert uv.board.layout_mode == LAYOUT_MODE_FREE_GRID
    assert uv.board.layout_id == "grid_3x3"
    assert len(uv.board.free_grid) == 2
    assert win.save_project(proj)

    raw = json.loads(proj.read_text(encoding="utf-8"))
    saved = raw["ultraview"]["workspace"]["boards"][0]
    assert saved["layout_id"] == "grid_3x3"
    assert saved["layout_mode"] == LAYOUT_MODE_FREE_GRID
    assert "primary_ratio" in saved
    assert len(saved["free_grid"]["placements"]) == 2

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    QCoreApplication.processEvents()
    board = restored._ultraview.board
    assert board.layout_id == "grid_3x3"
    assert board.layout_mode == LAYOUT_MODE_FREE_GRID
    assert len(board.free_grid) == 2
    restored._ultraview._on_free_grid_toggled(False)
    assert restored._ultraview.board.layout_id == "split_horizontal"
    assert len(restored._ultraview.board.placements) == 2


def test_viewport_is_not_written_into_saved_project(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a)
    proj = tmp_path / "uv-zoom.tlproj"
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    win.open_ultraview()
    QCoreApplication.processEvents()
    page = win.chart_stack.page_ultraview
    page.set_board_zoom(1.5)
    assert win.save_project(proj) is True
    raw = json.loads(proj.read_text(encoding="utf-8"))
    saved = raw["ultraview"]["workspace"]["boards"][0]
    assert "viewport" not in saved
    text = json.dumps(raw["ultraview"])
    assert "captured_digest" not in text

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    QCoreApplication.processEvents()
    restored.open_ultraview()
    QCoreApplication.processEvents()
    page = restored.chart_stack.page_ultraview
    opened = page.board_zoom()
    page.zoom_fit()
    assert opened == pytest.approx(page.board_zoom())


def test_switching_boards_fits_instead_of_restoring_saved_camera(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "switch-viewport.csv"
    _write_csv(csv_a)
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    win.open_ultraview()
    QCoreApplication.processEvents()
    coordinator = win._ultraview
    page = win.chart_stack.page_ultraview
    first = coordinator.board

    page.set_board_zoom(1.5)
    leftover = page.board_zoom()
    coordinator._on_create_board()
    second = coordinator.board

    assert second.board_id != first.board_id
    assert leftover == pytest.approx(1.5)

    coordinator._on_select_board(first.board_id)
    QCoreApplication.processEvents()
    opened = page.board_zoom()
    page.zoom_fit()
    assert opened == pytest.approx(page.board_zoom())

    restored_workspace, warnings = normalize_workspace_payload(
        coordinator.to_project_payload()
    )
    assert warnings == []
    restored_first = next(
        board for board in restored_workspace.boards if board.board_id == first.board_id
    )
    assert not hasattr(restored_first, "viewport")
    payload = coordinator.to_project_payload()
    assert "viewport" not in json.dumps(payload)


def test_reopened_placed_card_does_not_auto_aspect(qapp, qtbot, tmp_path):
    csv_a = tmp_path / "aspect.csv"
    _write_csv(csv_a)
    proj = tmp_path / "aspect.tlproj"
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(csv_a))
    uv = win._ultraview
    ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    uv._apply_add_ref(ref)
    original = free_grid_placement_for(uv.board, ref).rect
    assert original.column_span == 4
    assert original.row_span == 3
    assert win.save_project(proj) is True

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    QCoreApplication.processEvents()
    ruv = restored._ultraview
    assert ruv._pending_auto_aspect == {}
    image = QImage(800, 200, QImage.Format_ARGB32)
    image.fill(QColor("#336699"))
    ruv.store.publish(
        ref, image, digest="hydrate", meta=PreviewMeta(ref=ref, title="time")
    )
    ruv._push_preview(ref)
    assert free_grid_placement_for(ruv.board, ref).rect == original
    assert ruv._pending_auto_aspect == {}
