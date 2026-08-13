"""UltraView sixth mode: ChartStack, Toolbar, Inspector, MainWindow routing."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QLabel, QPushButton, QStackedWidget, QToolButton, QWidget

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.drawers.ultraview import UltraViewSheet
from mf4_analyzer.ui.inspector import Inspector
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.side_panels import PanelState
from mf4_analyzer.ui.ultraview_state import (
    DEFAULT_BOARD_NAME,
    STATUS_FRESH,
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
    page = win.chart_stack.page_ultraview
    assert page.parentWidget() is sheet
    assert page.isVisible()
    assert page.width() > 200
    assert page.height() > 200
    assert page.library_panel().isVisible()
    primary = page.board_grid().slot_widget("primary")
    assert primary is not None
    assert primary.isVisible()
    assert primary.width() > 0
    assert primary.height() > 0
    lib_count = page.library_panel().findChild(QWidget, "ultraViewLibraryCount")
    assert lib_count is not None
    assert int(lib_count.text()) >= 1

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


def test_ultraview_tool_window_is_not_transient_for_analyzer(qapp, qtbot):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    win.open_ultraview()
    qapp.processEvents()

    sheet = win._ultraview_sheet
    assert sheet is not None
    handle = sheet.windowHandle()
    assert handle is not None
    assert handle.transientParent() is None
    add = sheet.findChild(QPushButton, "ultraViewAddButton")
    assert add is not None
    assert add.autoDefault() is False
    assert add.isDefault() is False


def test_ultraview_board_actions_stay_in_the_tool_window(qapp, qtbot):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    win.open_ultraview()
    qapp.processEvents()

    sheet = win._ultraview_sheet
    page = win.chart_stack.page_ultraview
    mode = win.chart_stack.current_mode()
    QTest.keyClick(sheet, Qt.Key_Return)
    qapp.processEvents()
    page.layout_changed.emit("grid_2x2")
    qapp.processEvents()
    rows = page.library_panel().visible_rows()
    assert rows
    page.request_add(rows[0].section, rows[0].view_id)
    qapp.processEvents()
    page.presentation_toggled.emit(True)
    qapp.processEvents()

    assert sheet.isVisible()
    assert page.parentWidget() is sheet
    assert win.chart_stack.current_mode() == mode
    assert win.inspector.contextual_widget_name() != "ultraview"



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
    assert uv._inspector_snapshot is None
    assert right.snapshot_persistent_state()["state"] == before["state"]

    uv.reset_project_state()

    assert uv._inspector_snapshot is None
    assert right.snapshot_persistent_state()["state"] == before["state"]
    assert win.chart_stack.page_ultraview.is_presentation_active() is False


def test_inspector_unknown_mode_falls_back_to_time(qapp):
    insp = Inspector()
    insp.set_mode("ultraview")
    insp.set_mode("mystery")
    assert insp.contextual_widget_name() == "time"


def test_ultraview_sheet_unhides_page_taken_from_stack(qapp, qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(640, 480)
    host.show()
    stack = QStackedWidget(host)
    stack.addWidget(QLabel("time"))
    page = QLabel("board")
    stack.addWidget(page)
    stack.setCurrentIndex(0)
    assert page.isHidden()

    sheet = UltraViewSheet(host, page, stack)
    qtbot.addWidget(sheet)
    sheet.present()
    QCoreApplication.processEvents()

    assert page.parentWidget() is sheet
    assert not page.isHidden()
    assert page.isVisible()
    assert page.width() > 0
    assert page.height() > 0


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
    assert stack.currentWidget() is not page


def test_presentation_does_not_hide_main_inspector(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    right = win._panel_ctrl_right
    left = win._panel_ctrl_left
    right_before = right.snapshot_persistent_state()
    left_before = left.snapshot_persistent_state()
    win.open_ultraview()
    QCoreApplication.processEvents()
    uv._on_presentation(True)
    assert right.snapshot_persistent_state()["state"] == right_before["state"]
    assert left.snapshot_persistent_state()["state"] == left_before["state"]
    page = win.chart_stack.page_ultraview
    assert page.is_presentation_active() is True
    assert page.board_toolbar()._add.isVisible() is False
    uv._on_presentation(False)
    assert right.snapshot_persistent_state()["state"] == right_before["state"]
    assert page.is_presentation_active() is False
    assert page.is_library_visible() is True


def test_closing_ultraview_exits_presentation_and_reopens_in_edit(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    win.open_ultraview()
    QCoreApplication.processEvents()
    page = win.chart_stack.page_ultraview
    uv._on_presentation(True)
    assert page.is_presentation_active() is True
    sheet = win._ultraview_sheet
    sheet.close()
    QCoreApplication.processEvents()
    assert page.is_presentation_active() is False
    win.open_ultraview()
    QCoreApplication.processEvents()
    assert win._ultraview_sheet is not None
    assert page.is_presentation_active() is False
    assert page.board_toolbar()._add.isVisible() is True
    assert page.is_library_visible() is True


def test_ultraview_fast_close_reopen_keeps_single_sheet(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    page = win.chart_stack.page_ultraview
    win.open_ultraview()
    QCoreApplication.processEvents()
    first = win._ultraview_sheet
    first.close()
    QCoreApplication.processEvents()
    win.open_ultraview()
    QCoreApplication.processEvents()
    second = win._ultraview_sheet
    assert second is not None
    assert second.isVisible()
    assert page.parentWidget() is second
    assert page.isVisible()
    win._on_ultraview_sheet_destroyed()
    assert win._ultraview_sheet is second


def test_stale_sheet_destroyed_does_not_clear_new_handle(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    page = win.chart_stack.page_ultraview
    win.open_ultraview()
    QCoreApplication.processEvents()
    first = win._ultraview_sheet
    first.hide()
    win.open_ultraview()
    QCoreApplication.processEvents()
    second = win._ultraview_sheet
    assert second is not None
    assert second is not first
    assert page.parentWidget() is second
    QCoreApplication.processEvents()
    assert win._ultraview_sheet is second


def test_views_changed_add_delete_rename_recolor_sync_library_and_card(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    page = win.chart_stack.page_ultraview
    mgr = win.view_manager
    first_id = str(mgr.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", first_id))
    uv.refresh_page()

    before = {
        row.row().view_id
        for row in page.library_panel().row_widgets()
        if row.row().section == "time"
    }
    idx = mgr.new_view()
    new_id = str(mgr.get(idx).view_id)
    after = {
        row.row().view_id
        for row in page.library_panel().row_widgets()
        if row.row().section == "time"
    }
    assert new_id not in before
    assert new_id in after

    add_ref(uv.board, UltraViewRef("time", new_id))
    uv.refresh_page()
    mgr.rename(idx, "转向力矩")
    mgr.set_color(idx, "#ff3366")
    card = page.card_widget("time", new_id)
    assert card.model().title == "转向力矩"
    assert card.model().tab_color == "#ff3366"
    names = [
        row.row().name
        for row in page.library_panel().row_widgets()
        if row.row().view_id == new_id
    ]
    assert names == ["转向力矩"]

    mgr.delete_view(idx)
    card = page.card_widget("time", new_id)
    assert card.property("orphaned") == "true"
    assert page._ref_exists.get(UltraViewRef("time", new_id)) is False


def test_toolbar_show_titles_sync_cards(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    page = win.chart_stack.page_ultraview
    view_id = str(win.view_manager.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", view_id))
    uv.refresh_page()
    uv._on_show_titles(False)
    uv._on_show_sources(False)
    card = page.card_widget("time", view_id)
    assert card.model().show_title is False
    assert card.model().show_source is False
    assert page.board_toolbar()._act_titles.isChecked() is False
    uv._on_show_titles(True)
    card = page.card_widget("time", view_id)
    assert card.model().show_title is True


def test_coordinator_orphan_rebind_end_to_end(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    orphan = UltraViewRef("time", "gone")
    add_ref(uv.board, orphan)
    fft_id = str(win.analysis_managers["fft"].get(0).view_id)
    uv._on_rebind_ref("time", "gone", "fft", fft_id)
    assert orphan not in membership_set(uv.board)
    assert UltraViewRef("fft", fft_id) in membership_set(uv.board)


def test_open_ultraview_captures_plotted_time_view(qapp, qtbot, loaded_csv):
    """Visible time ink must snapshot even when native-AA curve_count is 0."""
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    win._load_one(loaded_csv)
    fid = next(iter(win.files))
    win.channel_list.check_first_channel(fid)
    qtbot.wait(250)
    QCoreApplication.processEvents()

    canvas = win.chart_stack.canvas_time
    assert len(canvas._channel_lines) > 0
    win.open_ultraview()
    uv = win._ultraview
    view_id = str(win.view_manager.get(0).view_id)
    uv.add_from_source_tab("time", view_id)
    ref = UltraViewRef("time", view_id)
    record = None
    for _ in range(40):
        QCoreApplication.processEvents()
        record = uv.store.get(ref)
        if record is not None and record.image is not None and not record.image.isNull():
            break
        qtbot.wait(50)
    assert record is not None
    assert record.image is not None
    assert record.image.isNull() is False
    page = uv.page()
    assert page is not None
    assert page._status_for(ref) == STATUS_FRESH


def test_add_to_ultraview_from_view_tab_keeps_section_and_view_id(
    qapp, qtbot, monkeypatch,
):
    win = MainWindow()
    qtbot.addWidget(win)
    bar = win.chart_stack.page_fft.tabbar
    view_id = str(win.analysis_managers["fft"].get(0).view_id)
    received = []
    win.chart_stack.add_to_ultraview_requested.connect(
        lambda section, vid: received.append((section, vid))
    )

    def fake_exec(menu, *_args):
        return next(action for action in menu.actions() if action.text() == "加入总览")

    monkeypatch.setattr("mf4_analyzer.ui.view_tabbar.QMenu.exec_", fake_exec)
    rect = bar.tabBar().tabRect(0)
    bar._on_context_menu(rect.center())

    assert received == [("fft", view_id)]
    assert UltraViewRef("fft", view_id) in membership_set(win._ultraview.board)

