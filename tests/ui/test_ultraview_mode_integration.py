"""UltraView sixth mode: ChartStack, Toolbar, Inspector, MainWindow routing."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QToolButton

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.inspector import Inspector
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.side_panels import PanelState
from mf4_analyzer.ui.ultraview_state import (
    DEFAULT_BOARD_NAME,
    UltraViewRef,
    add_ref,
    membership_set,
)
from mf4_analyzer.ui_kit import load_stylesheet

_CTX_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "inspector_sections"
    / "contextual_ultraview.py"
)


def test_ultraview_contextual_does_not_import_main_window():
    tree = ast.parse(_CTX_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "main_window" not in alias.name
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "main_window" not in node.module


def test_chart_stack_hint_bar_has_quickref_entry(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    bar = cs.hint_bar_for_mode("ultraview")
    button = bar.findChild(QToolButton, "chartHintQuickrefButton")
    assert button is not None
    assert button.text() == "?"


def test_main_window_ultraview_opens_independent_panel_without_stealing_mode(
    qapp, qtbot
):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1450, 850)
    win.show()
    qtbot.waitExposed(win)
    qapp.processEvents()

    role_before = win.navigator.projection_role()
    left_before = win._panel_ctrl_left.snapshot_persistent_state()
    assert win._panel_ctrl_left.state == PanelState.PINNED
    while len(win.view_manager.views) < 2:
        win.view_manager.new_view()
    win.view_manager.set_active(0)
    active_before = win.view_manager.active

    win.open_ultraview()
    qapp.processEvents()

    sheet = win._ultraview_sheet
    assert sheet is not None
    assert sheet.isVisible()
    assert not sheet.isModal()
    assert win.chart_stack.current_mode() == "time"
    assert win.inspector.contextual_widget_name() != "ultraview"
    assert win.navigator.projection_role() == role_before
    assert win._panel_ctrl_left.state == PanelState.PINNED
    assert win.chart_stack.page_ultraview.is_library_visible() is True
    assert win.chart_stack.page_ultraview.parentWidget() is sheet

    win._switch_view_for_active_section(1)
    assert win.view_manager.active != active_before
    assert win.chart_stack.current_mode() == "time"

    win.toolbar.btn_mode_fft.click()
    qapp.processEvents()
    assert win.chart_stack.current_mode() == "fft"
    assert sheet.isVisible()
    assert win._panel_ctrl_left.snapshot_persistent_state()["state"] == left_before["state"]
    assert win._ultraview.last_source_mode == "fft"

    win.open_ultraview()
    qapp.processEvents()
    assert win._ultraview_sheet is sheet



def test_add_non_current_view_does_not_switch_or_render(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    rendered = []
    monkeypatch.setattr(
        win,
        "_render_view_to_canvas",
        lambda *args, **kwargs: rendered.append(args) or True,
    )
    monkeypatch.setattr(
        win,
        "_apply_active_analysis_context",
        lambda *args, **kwargs: rendered.append(("analysis", args)),
    )
    fft_id = str(win.analysis_managers["fft"].get(0).view_id)
    assert win.chart_stack.current_mode() == "time"
    win._ultraview.add_from_source_tab("fft", fft_id)
    assert win.chart_stack.current_mode() == "time"
    assert rendered == []
    assert UltraViewRef("fft", fft_id) in membership_set(win._ultraview.board)


def test_open_source_navigates_by_view_id(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    while len(win.view_manager.views) < 2:
        win.view_manager.new_view()
    win.view_manager.set_active(0)
    target = str(win.view_manager.get(1).view_id)
    win.open_ultraview()
    QCoreApplication.processEvents()
    win._ultraview.open_source("time", target)
    for _ in range(8):
        QCoreApplication.processEvents()
    assert win.chart_stack.current_mode() == "time"
    assert str(win.view_manager.get(win.view_manager.active).view_id) == target


def test_ultraview_teardown_disconnects_page_intents(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    stack = win.chart_stack
    page = stack.page_ultraview
    view_id = str(win.view_manager.get(0).view_id)
    win.close()
    QCoreApplication.processEvents()
    stack.add_to_ultraview_requested.emit("time", view_id)
    page.add_ref_requested.emit("time", view_id)
    page.layout_changed.emit("grid_2x2")
    page.ratio_nudge_requested.emit(1)
    page.focus_requested.emit("time", view_id)
    page.open_source_requested.emit("time", view_id)
    page.copy_board_requested.emit()
    page.export_png_requested.emit(1)
    assert membership_set(win._ultraview.board) == set()
    assert win._ultraview.is_shutdown is True


def test_ultraview_shutdown_is_idempotent_and_clears_store(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    uv.shutdown()
    uv.shutdown()
    assert uv.is_shutdown is True
    assert uv.store.stats().records == 0
    win.close()


def _prime_placeholder_file(win):
    win.files["f1"] = object()
    win.navigator.add_file = lambda *a, **kw: None
    win.navigator.remove_file = lambda *a, **kw: None


def test_reset_project_state_keeps_page_hooks_and_stays_interactive(
    qapp, qtbot, monkeypatch, tmp_path
):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    page = win.chart_stack.page_ultraview
    view_id = str(win.view_manager.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", view_id))
    uv.refresh_page()
    hooks_before = len(uv._page_hooks)
    assert hooks_before > 0
    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window.ultraview_coordinator.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(tmp_path / "reset-hook.png"), "PNG (*.png)"),
    )

    uv.reset_project_state()

    assert len(uv._page_hooks) == hooks_before
    assert uv.board.name == DEFAULT_BOARD_NAME
    assert membership_set(uv.board) == set()
    assert uv.store.stats().records == 0

    page.add_ref_requested.emit("time", view_id)
    assert UltraViewRef("time", view_id) in membership_set(uv.board)
    page.layout_changed.emit("grid_2x2")
    assert uv.board.layout_id == "grid_2x2"
    page.ratio_nudge_requested.emit(-1)
    assert uv.board.primary_ratio < 0.67
    page.focus_requested.emit("time", view_id)
    page.open_source_requested.emit("time", view_id)
    page.copy_board_requested.emit()
    page.export_png_requested.emit(1)
    uv.attach()
    assert len(uv._page_hooks) == hooks_before


def test_close_all_cancel_does_not_reset_ultraview(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    view_id = str(win.view_manager.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", view_id))
    uv.board.name = "保留"
    uv.refresh_page()
    hooks_before = len(uv._page_hooks)
    _prime_placeholder_file(win)
    monkeypatch.setattr(win, "_confirm_global_file_close", lambda *a, **k: False)

    win.close_all()

    assert "f1" in win.files
    assert uv.board.name == "保留"
    assert UltraViewRef("time", view_id) in membership_set(uv.board)
    assert len(uv._page_hooks) == hooks_before


def test_close_all_confirm_resets_board_and_keeps_actions_live(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    page = win.chart_stack.page_ultraview
    view_id = str(win.view_manager.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", view_id))
    uv.refresh_page()
    hooks_before = len(uv._page_hooks)
    _prime_placeholder_file(win)

    win.close_all(force=True)

    assert win.files == {}
    assert membership_set(uv.board) == set()
    assert uv.board.name == DEFAULT_BOARD_NAME
    assert len(uv._page_hooks) == hooks_before
    page.add_ref_requested.emit("time", view_id)
    assert UltraViewRef("time", view_id) in membership_set(uv.board)


def test_close_all_without_files_keeps_restored_board(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    view_id = str(win.view_manager.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", view_id))
    uv.board.name = "已恢复"
    uv.refresh_page()

    win.close_all(force=True)

    assert uv.board.name == "已恢复"
    assert UltraViewRef("time", view_id) in membership_set(uv.board)


def test_reset_during_presentation_restores_inspector(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    right = win._panel_ctrl_right
    before = right.snapshot_persistent_state()
    uv._on_presentation(True)
    assert uv._inspector_snapshot is not None

    uv.reset_project_state()

    assert uv._inspector_snapshot is None
    assert right.snapshot_persistent_state()["state"] == before["state"]


def test_inspector_unknown_mode_falls_back_to_time(qapp):
    insp = Inspector()
    insp.set_mode("ultraview")
    insp.set_mode("mystery")
    assert insp.contextual_widget_name() == "time"


def test_closing_ultraview_panel_restores_page_to_chart_stack(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    page = win.chart_stack.page_ultraview
    stack = win.chart_stack.stack
    win.open_ultraview()
    QCoreApplication.processEvents()
    sheet = win._ultraview_sheet
    assert page.parentWidget() is sheet
    sheet.close()
    QCoreApplication.processEvents()
    assert page.parentWidget() is stack
    assert stack.indexOf(page) >= 0

