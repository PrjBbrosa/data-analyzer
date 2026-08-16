"""UltraView independent panel: ChartStack host, Toolbar, Inspector, MainWindow routing."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QComboBox, QLabel, QPushButton, QStackedWidget, QToolButton, QWidget

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.drawers.ultraview import UltraViewSheet
from mf4_analyzer.ui.inspector import Inspector
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.side_panels import PanelState
from mf4_analyzer.ui.ultraview_state import (
    DEFAULT_BOARD_NAME,
    GridAnchor,
    STATUS_FRESH,
    UltraViewRef,
    add_ref,
    free_grid_placement_for,
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


def test_ultraview_contextual_module_is_removed():
    assert not _CTX_PATH.is_file()


def test_chart_stack_hint_bar_has_quickref_entry(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    bar = cs.page_ultraview.hint_bar()
    button = bar.findChild(QToolButton, "chartHintQuickrefButton")
    assert button is not None
    assert button.text() == "?"


def test_ultraview_status_island_keeps_read_only_copy_inside_under_qss(qapp, qtbot):
    from PyQt5.QtWidgets import QLabel

    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage

    old_sheet = qapp.styleSheet()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        page = UltraViewPage()
        qtbot.addWidget(page)
        page.resize(1200, 720)
        page.show()
        qtbot.waitExposed(page)
        qapp.processEvents()

        status = page.status_island()
        assert status.height() == 40
        assert status.width() >= 96
        message = status.findChild(QLabel, "ultraViewStatusMessage")
        assert message is not None
        assert "只读预览" in message.toolTip()
        assert "不计算" in message.toolTip()
        message_rect = message.geometry()
        assert message_rect.top() >= status.rect().top()
        assert message_rect.bottom() <= status.rect().bottom()
        assert status.help_button().toolTip()
    finally:
        qapp.setStyleSheet(old_sheet)


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
    assert win.chart_stack.page_ultraview.is_library_visible() is False
    page = win.chart_stack.page_ultraview
    assert page.parentWidget() is sheet
    assert page.isVisible()
    assert page.width() > 200
    assert page.height() > 200
    assert not page.library_panel().isVisible()
    page.tool_rail().panel_button("library").click()
    qapp.processEvents()
    assert page.library_panel().isVisible()
    assert page.board().layout_mode == "free_grid"
    assert page.tool_rail().free_grid_button().property("modeActive") == "true"
    assert page._free_grid.isVisible()
    assert page._free_grid.width() > 0
    assert page._free_grid.height() > 0
    lib_count = page.library_panel().findChild(QWidget, "ultraViewLibraryCount")
    assert lib_count is not None
    digits = "".join(ch for ch in lib_count.text() if ch.isdigit())
    assert int(digits or "0") >= 1

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
    assert sheet.windowTitle() == "UltraView"
    copy = sheet.findChild(QPushButton, "ultraViewCopyBoardButton")
    assert copy is not None
    assert copy.autoDefault() is False
    assert copy.isDefault() is False


def test_ultraview_entry_marks_configured_workspace(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    docks = _source_ultraview_docks(win)
    assert not any(dock.has_content() for dock in docks)

    view_id = str(win.view_manager.get(0).view_id)
    win._ultraview.add_from_source_tab("time", view_id)

    QCoreApplication.processEvents()
    assert all(dock.has_content() for dock in docks)

    win._ultraview.reset_project_state()
    assert not any(dock.has_content() for dock in docks)


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


def test_toast_and_export_dialog_use_visible_sheet_host(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.open_ultraview()
    QCoreApplication.processEvents()
    sheet = win._ultraview_sheet
    assert sheet is not None
    assert sheet.isVisible()
    page = win.chart_stack.page_ultraview
    assert page.window() is sheet

    sheet_msgs = []
    win_msgs = []
    monkeypatch.setattr(
        sheet, "toast", lambda msg, level="info": sheet_msgs.append((msg, level))
    )
    monkeypatch.setattr(
        win, "toast", lambda msg, level="info": win_msgs.append((msg, level))
    )
    win._ultraview._toast("已复制整板图", "success")
    assert sheet_msgs == [("已复制整板图", "success")]
    assert win_msgs == []

    parents = []

    def fake_save(parent, *args, **kwargs):
        parents.append(parent)
        return ("", "")

    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window.ultraview_coordinator.QFileDialog.getSaveFileName",
        fake_save,
    )
    assert win._ultraview.choose_and_export_png(1) is False
    assert parents == [sheet]

    sheet.hide()
    QCoreApplication.processEvents()
    win._ultraview._toast("回落主窗", "info")
    assert win_msgs == [("回落主窗", "info")]


def test_open_source_raises_main_window_and_keeps_sheet(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    while len(win.view_manager.views) < 2:
        win.view_manager.new_view()
    win.view_manager.set_active(0)
    target = str(win.view_manager.get(1).view_id)
    win.open_ultraview()
    QCoreApplication.processEvents()
    sheet = win._ultraview_sheet
    sheet_id = id(sheet)
    raised = []
    monkeypatch.setattr(win, "raise_", lambda: raised.append("raise"))
    monkeypatch.setattr(win, "activateWindow", lambda: raised.append("activate"))
    win._ultraview.open_source("time", target)
    for _ in range(8):
        QCoreApplication.processEvents()
    assert raised == ["raise", "activate"]
    assert win._ultraview_sheet is sheet
    assert id(win._ultraview_sheet) == sheet_id
    assert sheet.isVisible()
    assert str(win.view_manager.get(win.view_manager.active).view_id) == target


def test_focus_requested_shows_overlay_once(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    page = win.chart_stack.page_ultraview
    view_id = str(win.view_manager.get(0).view_id)
    add_ref(win._ultraview.board, UltraViewRef("time", view_id))
    win._ultraview.refresh_page()
    calls = []
    orig = page.focus_layer().show_ref

    def spy(section, view_id, title, image):
        calls.append((section, view_id))
        return orig(section, view_id, title, image)

    page.focus_layer().show_ref = spy
    page._on_focus("time", view_id)
    assert calls == [("time", view_id)]


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


def test_attach_reconnects_page_hooks_when_stack_already_connected(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    page = win.chart_stack.page_ultraview
    assert uv._page_hooks
    assert uv._stack_hooks
    uv._disconnect_page_hooks()
    assert not uv._page_hooks
    assert uv._stack_hooks
    uv.attach()
    assert uv._page_hooks
    view_id = str(win.view_manager.get(0).view_id)
    page.add_ref_requested.emit("time", view_id)
    assert UltraViewRef("time", view_id) in membership_set(uv.board)


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


def test_reset_during_presentation_keeps_analyzer_inspector(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    right = win._panel_ctrl_right
    before = right.snapshot_persistent_state()
    uv._on_presentation(True)
    assert right.snapshot_persistent_state()["state"] == before["state"]

    uv.reset_project_state()

    assert right.snapshot_persistent_state()["state"] == before["state"]
    assert win.chart_stack.page_ultraview.is_presentation_active() is False


def test_inspector_unknown_mode_falls_back_to_time(qapp):
    insp = Inspector()
    insp.set_mode("fft")
    insp.set_mode("ultraview")
    assert insp.contextual_widget_name() == "time"
    assert not hasattr(insp, "ultraview_ctx")
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
    assert page.tool_rail().isVisible() is False
    assert page.global_island().display_button().isVisible() is False
    uv._on_presentation(False)
    assert right.snapshot_persistent_state()["state"] == right_before["state"]
    assert page.is_presentation_active() is False
    assert page.is_library_visible() is False
    assert page.tool_rail().isVisible() is True


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
    assert page.global_island().display_button().isVisible() is True
    assert page.tool_rail().isVisible() is True
    assert page.is_library_visible() is False


def test_reopening_ultraview_fits_instead_of_restoring_zoom(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1200, 800)
    win.show()
    win.open_ultraview()
    QCoreApplication.processEvents()
    page = win.chart_stack.page_ultraview
    page.set_board_zoom(2.0)
    sheet = win._ultraview_sheet
    sheet.close()
    QCoreApplication.processEvents()
    win.open_ultraview()
    QCoreApplication.processEvents()
    opened = page.board_zoom()
    page.zoom_fit()
    assert abs(opened - page.board_zoom()) < 1e-6
    page.set_board_zoom(2.0)
    win.open_ultraview()
    QCoreApplication.processEvents()
    raised = page.board_zoom()
    page.zoom_fit()
    assert abs(raised - page.board_zoom()) < 1e-6


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
    uv._on_show_card_actions(False)
    card = page.card_widget("time", view_id)
    assert card.model().show_title is False
    assert card.model().show_source is False
    assert card.model().show_card_actions is False
    assert page.board_toolbar()._act_titles.isChecked() is False
    assert page.board_toolbar()._act_card_actions.isChecked() is False
    uv._on_show_titles(True)
    card = page.card_widget("time", view_id)
    assert card.model().show_title is True


def test_card_action_preference_survives_board_lifecycle_and_sheet_reopen(qapp, qtbot):
    """Card-action visibility is a workspace preference, not Board content."""
    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    page = win.chart_stack.page_ultraview

    assert uv.workspace.show_card_actions is False
    uv._on_show_card_actions(True)
    first_id = uv.board.board_id
    assert uv.workspace.show_card_actions is True

    uv._on_create_board()
    second_id = uv.board.board_id
    assert second_id != first_id
    assert uv.workspace.show_card_actions is True

    uv._on_select_board(first_id)
    assert uv.board.board_id == first_id
    assert uv.workspace.show_card_actions is True
    uv._on_duplicate_board(first_id)
    assert uv.workspace.show_card_actions is True
    assert page.board_toolbar()._act_card_actions.isChecked() is True
    assert page._display_card_actions.isChecked() is True

    win.open_ultraview()
    QCoreApplication.processEvents()
    sheet = win._ultraview_sheet
    assert sheet is not None
    sheet.close()
    QCoreApplication.processEvents()
    win.open_ultraview()
    QCoreApplication.processEvents()

    assert uv.workspace.show_card_actions is True
    assert page.board_toolbar()._act_card_actions.isChecked() is True
    assert page._display_card_actions.isChecked() is True


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


def test_idle_pan_and_markup_recaptures_time_preview(qapp, qtbot, loaded_csv):
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
    first_digest = record.captured_digest
    page = uv.page()
    assert page is not None
    assert page._status_for(ref) == STATUS_FRESH

    xlim = canvas.get_visible_xlim()
    assert xlim is not None
    lo, hi = xlim
    canvas.restore_visible_xlim((lo + 0.1 * (hi - lo), hi))
    recaptured = None
    for _ in range(40):
        QCoreApplication.processEvents()
        recaptured = uv.store.get(ref)
        if (
            recaptured is not None
            and recaptured.captured_digest != first_digest
            and page._status_for(ref) == STATUS_FRESH
        ):
            break
        qtbot.wait(50)
    assert recaptured is not None
    assert recaptured.captured_digest != first_digest
    assert page._status_for(ref) == STATUS_FRESH
    pan_digest = recaptured.captured_digest

    canvas._annotations._bump_markup_revision()
    marked = None
    for _ in range(40):
        QCoreApplication.processEvents()
        marked = uv.store.get(ref)
        if (
            marked is not None
            and marked.captured_digest != pan_digest
            and page._status_for(ref) == STATUS_FRESH
        ):
            break
        qtbot.wait(50)
    assert marked is not None
    assert marked.captured_digest != pan_digest
    assert page._status_for(ref) == STATUS_FRESH


def _source_ultraview_docks(win):
    cs = win.chart_stack
    return (
        cs.ultraview_entry,
        cs.page_fft.ultraview_entry,
        cs.page_fft_time.ultraview_entry,
        cs.page_frf.ultraview_entry,
        cs.page_order.ultraview_entry,
    )


def test_each_source_dock_opens_the_same_ultraview_sheet(qapp, qtbot):
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    qapp.processEvents()

    docks = _source_ultraview_docks(win)
    assert all(dock is not None and dock.isEnabled() for dock in docks)
    assert win.chart_stack.page_ultraview.findChild(QWidget, "ultraViewEntry") is None

    hits = []
    win.chart_stack.open_ultraview_requested.connect(lambda *_args: hits.append(True))
    sheet = None
    for dock in docks:
        dock.click()
        qapp.processEvents()
        if sheet is None:
            sheet = win._ultraview_sheet
            assert sheet is not None
        else:
            assert win._ultraview_sheet is sheet
    assert len(hits) == 5
    docks[0].click()
    qapp.processEvents()
    assert win._ultraview_sheet is sheet
    assert len(hits) == 6


def test_toolbar_has_no_visible_ultraview_entry(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    tb = win.toolbar
    assert not hasattr(tb, "btn_mode_ultraview")
    assert not hasattr(tb, "btn_ultraview") or tb.btn_ultraview.isHidden()
    left = tb.findChild(QWidget, "toolbarLeftGroup")
    visible = [
        button.text()
        for button in left.findChildren(QPushButton)
        if button.isVisible() and button.text()
    ]
    assert "总览" not in visible
    assert "UltraView" not in visible


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


def test_free_grid_collision_commit_is_one_undo_restoring_all_cards(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack.ultraview.free_grid import LAYOUT_MOVE, plan_layout

    win = MainWindow()
    qtbot.addWidget(win)
    uv = win._ultraview
    time_ref = UltraViewRef("time", str(win.view_manager.get(0).view_id))
    fft_ref = UltraViewRef("fft", str(win.analysis_managers["fft"].get(0).view_id))
    add_ref(uv.board, time_ref)
    add_ref(uv.board, fft_ref)
    uv._on_free_grid_toggled(True)
    placements = list(uv.board.free_grid)
    assert len(placements) == 2
    mover = placements[0]
    other = placements[1]
    before = {item.ref: item.rect for item in placements}
    plan = plan_layout(
        placements,
        mover.ref,
        other.rect,
        LAYOUT_MOVE,
        preferred=(1, 0),
    )
    assert plan.accepted is True
    payload = tuple(
        (
            ref.section,
            ref.view_id,
            rect.column,
            rect.row,
            rect.column_span,
            rect.row_span,
        )
        for ref, rect in plan.committed_updates()
    )
    uv._on_free_grid_group_geometry(payload)
    history = uv._grid_histories[uv.board.board_id]
    assert len(history.undo) == 1
    after = {item.ref: item.rect for item in uv.board.free_grid}
    assert after != before
    uv._on_free_grid_undo()
    restored = {item.ref: item.rect for item in uv.board.free_grid}
    assert restored == before
    uv._on_free_grid_redo()
    redone = {item.ref: item.rect for item in uv.board.free_grid}
    assert redone == after


def test_free_grid_insert_intent_reaches_coordinator_once_with_its_anchor(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_ultraview()
    qapp.processEvents()
    page = win.chart_stack.page_ultraview
    view_id = str(win.view_manager.get(0).view_id)
    ref = UltraViewRef("time", view_id)

    page.free_grid_insert_requested.emit("time", view_id, GridAnchor(8.0, 9.5))
    qapp.processEvents()

    item = free_grid_placement_for(win._ultraview.board, ref)
    assert item is not None
    assert item.rect.column == 6
    assert item.rect.row == 8
