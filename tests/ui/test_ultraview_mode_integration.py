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
from mf4_analyzer.ui.ultraview_state import UltraViewRef, membership_set
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


def test_main_window_ultraview_mode_hides_nav_and_ignores_alt_shortcuts(
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

    win.toolbar.btn_mode_ultraview.click()
    qapp.processEvents()

    assert win.chart_stack.current_mode() == "ultraview"
    assert win.inspector.contextual_widget_name() == "ultraview"
    assert win.navigator.projection_role() == role_before
    assert win._visible_view_tabbar() is None
    assert win._panel_ctrl_left.state == PanelState.HIDDEN
    assert win.chart_stack.page_ultraview.is_library_visible() is True

    win._switch_view_for_active_section(1)
    assert win.view_manager.active == active_before
    assert win.chart_stack.current_mode() == "ultraview"

    page = win.chart_stack.page_ultraview
    win._on_nav_panel_toggled()
    assert page.is_library_visible() is False
    win._on_nav_panel_toggled()
    assert page.is_library_visible() is True
    assert win._panel_ctrl_left.state == PanelState.HIDDEN

    win.toolbar.btn_mode_time.click()
    qapp.processEvents()
    assert win.chart_stack.current_mode() == "time"
    assert win._panel_ctrl_left.snapshot_persistent_state()["state"] == left_before["state"]
    assert win._ultraview.last_source_mode == "time"


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
    win.toolbar.btn_mode_ultraview.click()
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
    win.close()
    QCoreApplication.processEvents()
    stack.add_to_ultraview_requested.emit("time", "gone")
    stack.page_ultraview.add_ref_requested.emit("time", "gone")


def test_inspector_unknown_mode_falls_back_to_time(qapp):
    insp = Inspector()
    insp.set_mode("ultraview")
    insp.set_mode("mystery")
    assert insp.contextual_widget_name() == "time"
