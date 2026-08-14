"""Focused contract tests for UltraView floating presentation chrome."""
from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QFrame, QLabel, QToolButton

from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    PANEL_FILTER,
    PANEL_UNPLACED,
    BoardIsland,
    CanvasHost,
    CardContextIsland,
    GlobalIsland,
    NavigationIsland,
    StatusIsland,
    ToolRail,
)
from mf4_analyzer.ui.chart_stack.ultraview.widgets import make_ref_mime


def test_tool_rail_emits_requested_panel_and_projects_active_badge(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()

    requested: list[str] = []
    rail.panel_requested.connect(requested.append)
    filter_button = rail.panel_button(PANEL_FILTER)
    assert filter_button is not None
    assert filter_button.text() == ""
    assert filter_button.toolTip()
    assert filter_button.accessibleName()
    assert filter_button.focusPolicy() == Qt.TabFocus

    QTest.mouseClick(filter_button, Qt.LeftButton)
    assert requested == [PANEL_FILTER]
    rail.set_active_panel(PANEL_FILTER)
    assert rail.active_panel() == PANEL_FILTER
    assert filter_button.property("active") == "true"

    rail.set_badge(PANEL_UNPLACED, 3)
    assert rail.badge_text(PANEL_UNPLACED) == "3"
    badge = rail.findChild(QLabel, "ultraViewRailUnplacedBadge")
    assert badge is not None and badge.isVisible()
    assert badge.width() <= 28
    assert badge.height() <= 20
    assert badge.x() >= 0
    unplaced_button = rail.panel_button(PANEL_UNPLACED)
    assert unplaced_button is not None
    rail.set_badge(PANEL_UNPLACED, 0)
    assert rail.badge_text(PANEL_UNPLACED) == "0"
    assert not badge.isVisible()
    rail.set_filter_warning(True)
    assert rail.filter_warning() is True
    dot = rail.findChild(QLabel, "ultraViewRailFilterWarningDot")
    assert dot is not None and dot.isVisible()
    assert dot.width() == 8
    rail.set_filter_warning(False)
    assert not dot.isVisible()


def test_canvas_host_overlay_does_not_resize_canvas_and_closes_to_trigger(qtbot):
    host = CanvasHost()
    qtbot.addWidget(host)
    host.resize(640, 420)
    canvas = QFrame()
    trigger = QToolButton(host)
    trigger.setGeometry(8, 8, 32, 32)
    overlay = QFrame()
    overlay.setMinimumSize(180, 120)
    host.set_canvas_widget(canvas)
    host.register_overlay("library", overlay, trigger=trigger)
    host.show()
    trigger.show()
    QTest.qWait(1)
    canvas_rect_before = canvas.geometry()

    assert host.open_overlay("library", QRect(500, 340, 220, 160))
    assert host.active_overlay() == "library"
    assert overlay.isVisible()
    assert canvas.geometry() == canvas_rect_before
    assert overlay.geometry().right() <= host.contentsRect().right()
    assert overlay.geometry().bottom() <= host.contentsRect().bottom()

    canvas_rect_before_close = canvas.geometry()
    QTest.mouseClick(canvas, Qt.LeftButton)
    assert host.active_overlay() is None
    assert not overlay.isVisible()
    assert canvas.geometry() == canvas_rect_before_close
    assert trigger.hasFocus()


def test_tool_rail_accepts_a_real_view_ref_drop_for_unplaced(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.resize(48, 220)
    rail.show()
    mime = make_ref_mime("time", "view-12")
    received: list[tuple[str, str]] = []

    def record_drop(section: str, view_id: str) -> None:
        received.append((section, view_id))

    rail.ref_dropped.connect(record_drop)

    enter = QDragEnterEvent(
        QPoint(16, 120), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    enter._mime_ref = mime
    rail.dragEnterEvent(enter)
    assert enter.isAccepted()
    assert rail.panel_button(PANEL_UNPLACED).property("attention") == "true"

    drop = QDropEvent(
        QPoint(16, 120), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    drop._mime_ref = mime
    rail.dropEvent(drop)
    assert drop.isAccepted()
    assert received == [("time", "view-12")]
    assert rail.panel_button(PANEL_UNPLACED).property("attention") == "false"


def test_island_actions_are_icon_only_and_forward_existing_typed_intents(qtbot):
    global_island = GlobalIsland()
    navigation = NavigationIsland()
    board = BoardIsland()
    status = StatusIsland()
    context = CardContextIsland()
    for widget in (global_island, navigation, board, status, context):
        qtbot.addWidget(widget)
        widget.show()

    for island in (global_island, navigation, board, status, context):
        for button in island.findChildren(QToolButton):
            assert button.text() == ""
            assert button.toolTip()
            assert button.accessibleName()
            assert button.focusPolicy() == Qt.TabFocus

    presentation: list[bool] = []
    global_island.presentation_toggled.connect(presentation.append)
    QTest.mouseClick(global_island.presentation_button(), Qt.LeftButton)
    assert presentation == [True]
    assert global_island.presentation_button().property("active") == "true"

    nav_actions: list[str] = []

    def record_fit() -> None:
        nav_actions.append("fit")

    navigation.zoom_fit_requested.connect(record_fit)
    fit_button = navigation.button("fit")
    assert fit_button is not None
    QTest.mouseClick(fit_button, Qt.LeftButton)
    assert nav_actions == ["fit"]
    navigation.set_zoom_percent(125)
    assert navigation.zoom_label().text() == "125%"

    board.set_current_board("board-a", "全局对比 Board")
    renamed = []

    def record_rename() -> None:
        renamed.append(True)

    board.rename_requested.connect(record_rename)
    QTest.keyClick(board, Qt.Key_F2)
    assert renamed == [True]
    assert board.board_name_label().accessibleName() == "全局对比 Board"

    help_requested = []

    def record_help() -> None:
        help_requested.append(True)

    status.quickref_requested.connect(record_help)
    QTest.mouseClick(status.help_button(), Qt.LeftButton)
    assert help_requested == [True]
    status.set_status("轴范围不一致", level="warning")
    assert status.property("statusLevel") == "warning"
    assert status.message_label().full_text() == "轴范围不一致"

    context.show_for("time", "view-1", orphaned=True)
    copied: list[tuple[str, str]] = []
    rebound: list[tuple[str, str]] = []
    def record_copied(section: str, view_id: str) -> None:
        copied.append((section, view_id))

    def record_rebound(section: str, view_id: str) -> None:
        rebound.append((section, view_id))

    context.copy_image_requested.connect(record_copied)
    context.rebind_requested.connect(record_rebound)
    copy_button = context.button("copy")
    rebind_button = context.button("rebind")
    assert copy_button is not None and rebind_button is not None
    QTest.mouseClick(copy_button, Qt.LeftButton)
    QTest.mouseClick(rebind_button, Qt.LeftButton)
    assert copied == [("time", "view-1")]
    assert rebound == [("time", "view-1")]
    assert context.property("orphaned") == "true"
