"""Focused contract tests for UltraView floating presentation chrome."""
from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QWidget,
)

import mf4_analyzer.ui.chart_stack.ultraview.chrome as ultraview_chrome
from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    BOARD_POPOVER_WIDTH,
    PANEL_FILTER,
    PANEL_LAYOUT,
    PANEL_LIBRARY,
    PANEL_UNPLACED,
    RAIL_BUTTON_SIZE,
    RAIL_CONTENT_HEIGHT,
    RAIL_ICON_SIZE,
    RAIL_WIDTH,
    BoardIsland,
    BoardPopover,
    CanvasHost,
    CardContextIsland,
    GlobalIsland,
    LayoutPicker,
    NavigationIsland,
    StatusIsland,
    ToolRail,
)
from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import (
    BOARD_ISLAND_MAX_WIDTH,
    GLOBAL_ISLAND_WIDTH,
    ISLAND_HEIGHT,
    NAVIGATION_ISLAND_WIDTH,
    RAIL_CONTENT_HEIGHT as FLOATING_RAIL_CONTENT_HEIGHT,
    RAIL_WIDTH as FLOATING_RAIL_WIDTH,
    STATUS_ISLAND_WIDTH,
)
from mf4_analyzer.ui.chart_stack.ultraview.widgets import LAYOUT_LABELS_ZH, CompareRail, make_ref_mime


def test_floating_chrome_dimension_contracts(qtbot):
    rail = ToolRail()
    board = BoardIsland()
    global_island = GlobalIsland()
    status = StatusIsland()
    navigation = NavigationIsland()
    popover = BoardPopover()
    for widget in (rail, board, global_island, status, navigation, popover):
        qtbot.addWidget(widget)
        widget.show()

    assert RAIL_WIDTH == FLOATING_RAIL_WIDTH
    assert RAIL_CONTENT_HEIGHT == FLOATING_RAIL_CONTENT_HEIGHT
    assert rail.sizeHint() == QSize(FLOATING_RAIL_WIDTH, FLOATING_RAIL_CONTENT_HEIGHT)
    assert rail.minimumSizeHint() == rail.sizeHint()
    assert board.maximumHeight() == ISLAND_HEIGHT
    assert board.maximumWidth() == BOARD_ISLAND_MAX_WIDTH
    for island, max_width in (
        (global_island, GLOBAL_ISLAND_WIDTH),
        (status, STATUS_ISLAND_WIDTH),
        (navigation, NAVIGATION_ISLAND_WIDTH),
    ):
        assert island.sizeHint().height() == ISLAND_HEIGHT
        assert island.minimumSizeHint().height() == ISLAND_HEIGHT
        assert island.sizeHint().width() <= max_width
    assert popover.sizeHint().width() == BOARD_POPOVER_WIDTH


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
    assert filter_button.property("panelOpen") == "true"
    assert filter_button.property("modeActive") != "true"

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


def test_tool_rail_free_grid_sits_between_library_and_layout(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()
    QTest.qWait(1)
    library = rail.panel_button(PANEL_LIBRARY)
    layout = rail.panel_button(PANEL_LAYOUT)
    free = rail.free_grid_button()
    filter_button = rail.panel_button(PANEL_FILTER)
    assert library is not None and layout is not None and filter_button is not None
    assert library.y() < free.y() < layout.y() < filter_button.y()


def test_tool_rail_layout_is_active_when_a_template_is_current(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    layout = rail.panel_button(PANEL_LAYOUT)
    free = rail.free_grid_button()
    assert layout is not None
    rail.set_free_grid_enabled(False)
    assert layout.property("modeActive") == "true"
    assert layout.property("panelOpen") != "true"
    assert free.property("modeActive") != "true"
    rail.set_free_grid_enabled(True)
    assert layout.property("modeActive") != "true"
    assert free.property("modeActive") == "true"
    rail.set_active_panel(PANEL_LAYOUT)
    assert layout.property("panelOpen") == "true"
    assert layout.property("modeActive") != "true"
    assert free.property("modeActive") == "true"
    rail.set_active_panel(None)
    assert layout.property("panelOpen") != "true"
    rail.set_free_grid_enabled(False)
    assert layout.property("modeActive") == "true"
    assert layout.property("panelOpen") != "true"


def test_tool_rail_free_grid_is_a_mode_toggle_not_a_panel(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()

    panels: list[str] = []
    modes: list[bool] = []
    rail.panel_requested.connect(panels.append)
    rail.free_grid_toggled.connect(modes.append)
    button = rail.free_grid_button()
    assert button.text() == ""
    assert button.toolTip()
    assert button.accessibleName()
    assert button.focusPolicy() == Qt.TabFocus

    QTest.mouseClick(button, Qt.LeftButton)
    assert modes == [True]
    assert panels == []
    rail.set_free_grid_enabled(True)
    assert button.isChecked()
    assert button.property("modeActive") == "true"
    rail.set_active_panel(PANEL_FILTER)
    assert button.isChecked()
    assert button.property("modeActive") == "true"
    assert panels == []


def test_tool_rail_sync_all_sits_below_unplaced_and_is_not_a_panel(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()
    QTest.qWait(1)

    unplaced = rail.panel_button(PANEL_UNPLACED)
    button = rail.sync_all_button()
    assert unplaced is not None
    assert unplaced.y() < button.y()
    assert button.objectName() == "ultraViewRailSyncAllButton"
    assert button.text() == ""
    assert button.toolTip() == "没有需要更新的预览"
    assert "一键更新源" in button.accessibleName()
    assert button.focusPolicy() == Qt.TabFocus
    assert not button.isEnabled()
    assert rail.stale_count() == 0

    panels: list[str] = []
    syncs: list[int] = []
    rail.panel_requested.connect(panels.append)
    rail.sync_all_requested.connect(lambda: syncs.append(1))
    QTest.mouseClick(button, Qt.LeftButton)
    assert panels == []
    assert syncs == []

    rail.set_stale_count(3)
    assert rail.stale_count() == 3
    assert button.isEnabled()
    assert button.toolTip() == "一键更新源"
    assert button.accessibleName() == "一键更新全部已变化的预览"
    assert button.property("attention") == "true"
    badge = rail.findChild(QLabel, "ultraViewRailSyncAllBadge")
    assert badge is not None and badge.isVisible()
    assert badge.text() == "3"
    assert badge.width() <= 28
    assert badge.height() <= 20
    QTest.mouseClick(button, Qt.LeftButton)
    assert syncs == [1]
    assert panels == []

    rail.set_stale_count(0)
    assert not button.isEnabled()
    assert not badge.isVisible()
    assert button.property("attention") == "false"


def test_compare_rail_stacks_filters_vertically(qtbot):
    rail = CompareRail()
    qtbot.addWidget(rail)
    rail.resize(180, 240)
    rail.show()
    QTest.qWait(1)
    buttons = [
        child
        for child in rail.findChildren(QPushButton)
        if child.objectName() == "ultraViewCompareButton"
    ]
    assert len(buttons) == 5
    for previous, current in zip(buttons, buttons[1:]):
        assert current.y() > previous.y()
        assert current.x() == previous.x()


def test_layout_picker_omits_free_grid_entry_and_keeps_template_thumbs(qtbot):
    picker = LayoutPicker(LAYOUT_LABELS_ZH)
    qtbot.addWidget(picker)
    picker.show()
    QTest.qWait(1)
    assert picker.findChild(QToolButton, "ultraViewLayoutPopoverFreeGrid") is None
    assert picker.findChild(QPushButton, "ultraViewLayoutPopoverOrganize") is None
    assert picker.findChild(QPushButton, "ultraViewLayoutPopoverUndo") is None
    assert picker.findChild(QPushButton, "ultraViewLayoutPopoverRedo") is None
    assert list(picker._buttons) == list(LAYOUT_LABELS_ZH)
    thumb = picker.thumb_button("hero_left_4")
    assert thumb is not None
    assert thumb.minimumHeight() >= 104
    assert thumb.iconSize() == QSize(88, 54)
    assert "左主图 + 3 辅图" in thumb.text()
    left = picker.thumb_button("split_horizontal")
    right = picker.thumb_button("split_vertical")
    below = picker.thumb_button("grid_2x2")
    assert left is not None and right is not None and below is not None
    assert right.x() > left.x()
    assert abs(right.y() - left.y()) <= 8
    assert below.y() > left.y()
    picker.set_current("grid_2x2", free_grid=False, view_count=3)
    assert picker.thumb_button("grid_2x2").isChecked()
    assert "当前" in picker.thumb_button("grid_2x2").text()
    assert not picker.thumb_button("hero_left_4").isChecked()
    assert "选择模板" in picker.intro_label().text()
    assert "3 个 View" in picker.intro_label().text()
    picker.set_current("grid_2x2", free_grid=True)
    assert not any(button.isChecked() for button in picker._buttons.values())
    assert "自由网格" in picker.intro_label().text()
    chosen: list[str] = []
    picker.layout_id_chosen.connect(chosen.append)
    picker.thumb_button("hero_left_4").click()
    assert chosen == ["hero_left_4"]


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
    assert trigger.hasFocus() is False


def test_canvas_host_escape_restores_trigger_focus(qtbot):
    host = CanvasHost()
    qtbot.addWidget(host)
    host.resize(640, 420)
    canvas = QFrame()
    trigger = QToolButton(host)
    trigger.setFocusPolicy(Qt.TabFocus)
    trigger.setGeometry(8, 8, 32, 32)
    overlay = QFrame()
    overlay.setMinimumSize(180, 120)
    host.set_canvas_widget(canvas)
    host.register_overlay("library", overlay, trigger=trigger)
    host.show()
    trigger.show()
    QTest.qWait(1)
    assert host.open_overlay("library", QRect(40, 40, 200, 160))
    host.setFocus(Qt.OtherFocusReason)
    QTest.keyClick(host, Qt.Key_Escape)
    assert host.active_overlay() is None
    assert trigger.hasFocus()


def test_canvas_host_pinned_overlay_ignores_canvas_click(qtbot):
    host = CanvasHost()
    qtbot.addWidget(host)
    host.resize(640, 420)
    canvas = QFrame()
    overlay = QFrame()
    overlay.setMinimumSize(180, 120)
    host.set_canvas_widget(canvas)
    host.register_overlay("library", overlay)
    host.show()
    QTest.qWait(1)

    assert host.open_overlay("library", QRect(40, 40, 200, 160))
    host.set_overlay_close_on_canvas("library", False)
    assert host.overlay_closes_on_canvas("library") is False
    QTest.mouseClick(canvas, Qt.LeftButton)
    assert host.active_overlay() == "library"
    assert overlay.isVisible()

    host.set_overlay_close_on_canvas("library", True)
    QTest.mouseClick(canvas, Qt.LeftButton)
    assert host.active_overlay() is None
    assert not overlay.isVisible()


def test_tool_rail_accepts_a_real_view_ref_drop_for_unplaced(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.resize(RAIL_WIDTH, RAIL_CONTENT_HEIGHT)
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


def test_global_island_size_hint_ignores_unshown_ancestors(qtbot):
    island = GlobalIsland()
    qtbot.addWidget(island)
    assert island.isVisible() is False
    assert island.display_button().isVisible() is False
    assert island.sizeHint().width() >= 8 + 32 * 3
    island.resize(island.sizeHint())
    island.show()
    qtbot.waitExposed(island)

    buttons = (
        island.display_button(),
        island.export_button(),
        island.presentation_button(),
    )
    boxes = [button.geometry() for button in buttons]
    assert all(box.width() >= 24 and box.height() >= 24 for box in boxes)
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            assert not first.intersects(second), (first, second)

    island.set_edit_visible(False)
    assert island.sizeHint().width() == 8 + 32
    island.resize(island.sizeHint())
    assert island.display_button().isHidden() is True
    assert island.export_button().isHidden() is True
    assert island.presentation_button().isHidden() is False


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
    QTest.keyClick(board, Qt.Key_F2)
    editor = _visible_rename_editor(board, "ultraViewBoardIslandRename")
    assert editor is not None
    assert editor.isVisible()
    assert editor.text() == "全局对比 Board"
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
    overflow = context.make_overflow_menu()
    labels = [action.text() for action in overflow.actions() if action.text()]
    assert "复制本卡图像" in labels
    assert "重新绑定" in labels
    next(action for action in overflow.actions() if action.text() == "复制本卡图像").trigger()
    next(action for action in overflow.actions() if action.text() == "重新绑定").trigger()
    assert copied == [("time", "view-1")]
    assert rebound == [("time", "view-1")]
    assert context.property("orphaned") == "true"

    context.show_for("time", "view-1", stale=True)
    synced: list[tuple[str, str]] = []

    def record_synced(section: str, view_id: str) -> None:
        synced.append((section, view_id))

    context.sync_requested.connect(record_synced)
    sync_button = context.button("sync")
    assert sync_button is not None
    assert sync_button.isVisible()
    QTest.mouseClick(sync_button, Qt.LeftButton)
    assert synced == [("time", "view-1")]
    context.show_for("time", "view-1", orphaned=True, stale=True)
    assert not context.button("sync").isVisible()


def _visible_rename_editor(host: QWidget, object_name: str) -> QLineEdit | None:
    for widget in host.findChildren(QLineEdit):
        if widget.objectName() == object_name and widget.isVisible():
            return widget
    return None


def _rename_board_dialogs() -> list[QInputDialog]:
    return [
        widget
        for widget in QApplication.allWidgets()
        if isinstance(widget, QInputDialog) and widget.windowTitle() == "重命名 Board"
    ]


def test_board_island_name_double_click_uses_inline_edit_not_dialog(qtbot, qapp):
    board = BoardIsland()
    qtbot.addWidget(board)
    board.set_current_board("board-a", "全局对比 Board")
    board.show()
    board.resize(board.sizeHint())
    qapp.processEvents()

    QTest.mouseDClick(board.board_name_label(), Qt.LeftButton)
    qapp.processEvents()

    editor = _visible_rename_editor(board, "ultraViewBoardIslandRename")
    assert editor is not None
    assert editor.isVisible()
    assert editor.text() == "全局对比 Board"
    assert editor.selectedText() == "全局对比 Board"
    assert _rename_board_dialogs() == []


def test_board_island_inline_rename_commits_cancels_and_rejects_empty(qtbot, qapp):
    board = BoardIsland()
    qtbot.addWidget(board)
    board.set_current_board("board-a", "全局对比 Board")
    board.show()
    board.resize(board.sizeHint())
    qapp.processEvents()
    renamed: list[str] = []
    board.rename_requested.connect(renamed.append)

    QTest.keyClick(board, Qt.Key_F2)
    editor = _visible_rename_editor(board, "ultraViewBoardIslandRename")
    assert editor is not None
    editor.setText("NVH 复查")
    QTest.keyClick(editor, Qt.Key_Return)
    qapp.processEvents()
    assert renamed == ["NVH 复查"]
    assert _rename_board_dialogs() == []

    QTest.keyClick(board, Qt.Key_F2)
    editor = _visible_rename_editor(board, "ultraViewBoardIslandRename")
    assert editor is not None
    editor.setText("草稿")
    QTest.keyClick(editor, Qt.Key_Escape)
    qapp.processEvents()
    assert renamed == ["NVH 复查"]
    assert board.board_name_label().full_text() == "全局对比 Board"

    QTest.keyClick(board, Qt.Key_F2)
    editor = _visible_rename_editor(board, "ultraViewBoardIslandRename")
    assert editor is not None
    editor.setText("   ")
    QTest.keyClick(editor, Qt.Key_Return)
    qapp.processEvents()
    assert renamed == ["NVH 复查"]
    assert board.board_name_label().full_text() == "全局对比 Board"

    QTest.mouseDClick(board.menu_button(), Qt.LeftButton)
    qapp.processEvents()
    leftover = _visible_rename_editor(board, "ultraViewBoardIslandRename")
    assert leftover is None or not leftover.isVisible()


def test_board_popover_f2_renames_inline_without_closing(qtbot, qapp):
    popover = BoardPopover()
    qtbot.addWidget(popover)
    popover.set_boards(
        (
            SimpleNamespace(board_id="a", name="全局对比"),
            SimpleNamespace(board_id="b", name="台架 vs 路试"),
        ),
        "a",
    )
    popover.show()
    popover.resize(popover.sizeHint())
    qapp.processEvents()
    renamed: list[tuple[str, str]] = []
    popover.rename_requested.connect(lambda board_id, name: renamed.append((board_id, name)))

    QTest.keyClick(popover.list_widget(), Qt.Key_F2)
    qapp.processEvents()
    editor = _visible_rename_editor(popover, "ultraViewBoardRowRename")
    assert editor is not None
    assert editor.isVisible()
    assert editor.text() == "全局对比"
    assert popover.isVisible()
    assert _rename_board_dialogs() == []

    editor.setText("整车问题总览")
    QTest.keyClick(editor, Qt.Key_Return)
    qapp.processEvents()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert renamed == [("a", "整车问题总览")]
    assert popover.isVisible()
    assert _rename_board_dialogs() == []

    name_rect = popover.name_rect_for("a")
    assert name_rect.isValid()
    QTest.mouseDClick(popover.list_widget().viewport(), Qt.LeftButton, pos=name_rect.center())
    qapp.processEvents()
    editor = _visible_rename_editor(popover, "ultraViewBoardRowRename")
    assert editor is not None and editor.isVisible()
    assert popover.isVisible()
    assert _rename_board_dialogs() == []


def test_tool_rail_mode_active_is_independent_of_panel_open(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    layout = rail.panel_button(PANEL_LAYOUT)
    free = rail.free_grid_button()
    library = rail.panel_button(PANEL_LIBRARY)
    assert layout is not None and library is not None
    rail.set_free_grid_enabled(False)
    assert layout.property("modeActive") == "true"
    assert layout.property("panelOpen") != "true"
    assert free.property("modeActive") != "true"
    rail.set_active_panel(PANEL_LAYOUT)
    assert layout.property("modeActive") == "true"
    assert layout.property("panelOpen") == "true"
    assert library.property("panelOpen") != "true"
    rail.set_active_panel(None)
    assert layout.property("modeActive") == "true"
    assert layout.property("panelOpen") != "true"
    rail.set_free_grid_enabled(True)
    rail.set_active_panel(PANEL_LAYOUT)
    assert free.property("modeActive") == "true"
    assert layout.property("modeActive") != "true"
    assert layout.property("panelOpen") == "true"
    rail.set_active_panel(None)
    assert free.property("modeActive") == "true"
    assert layout.property("panelOpen") != "true"


def test_card_context_residents_are_open_sync_focus_and_more(qtbot):
    context = CardContextIsland()
    qtbot.addWidget(context)
    context.show()
    context.show_for("time", "view-1", stale=False)
    visible = [
        action
        for action, button in context._buttons.items()
        if button.isVisible()
    ]
    assert visible == ["open", "focus", "fit", "more"]
    assert context.button("sync") is not None and not context.button("sync").isVisible()
    for action in ("copy", "unplaced", "rebind", "remove"):
        button = context.button(action)
        assert button is None or not button.isVisible()
    copied = []
    unplaced = []
    context.copy_image_requested.connect(lambda section, view_id: copied.append((section, view_id)))
    context.move_to_unplaced_requested.connect(
        lambda section, view_id: unplaced.append((section, view_id))
    )
    menu = context.make_overflow_menu()
    labels = [action.text() for action in menu.actions() if action.text()]
    assert "复制本卡图像" in labels
    assert "移到未放置" in labels
    copy_act = next(action for action in menu.actions() if action.text() == "复制本卡图像")
    copy_act.trigger()
    assert copied == [("time", "view-1")]
    context.show_for("time", "view-1", stale=True)
    assert context.button("sync").isVisible()
    assert [action for action, button in context._buttons.items() if button.isVisible()] == [
        "open",
        "sync",
        "focus",
        "fit",
        "more",
    ]
    for button in context.findChildren(QToolButton):
        if button.isVisible():
            assert button.toolTip()
            assert button.accessibleName()
            assert button.focusPolicy() == Qt.TabFocus


def test_card_context_and_board_row_use_normalized_font_awesome_icons(qtbot, monkeypatch):
    """Presentation-only regression: no card intent or popover entry changes."""
    calls: list[str] = []
    real_icon = ultraview_chrome.qta.icon

    def record_icon(name, *args, **kwargs):
        calls.append(str(name))
        return real_icon(name, *args, **kwargs)

    monkeypatch.setattr(ultraview_chrome.qta, "icon", record_icon)
    context = CardContextIsland()
    qtbot.addWidget(context)
    context.show()
    assert calls[:5] == [
        "fa5s.external-link-alt",
        "fa5s.sync-alt",
        "fa5s.expand",
        "fa5s.vector-square",
        "fa5s.ellipsis-v",
    ]

    ultraview_chrome._BoardListDelegate()
    assert calls[-2:] == ["fa5s.clone", "fa5s.trash-alt"]


def test_overflow_menu_is_deleted_after_closing_instead_of_leaking_per_open(qtbot):
    """§4.3: every "more" open must not permanently grow ``_card_context``.

    ``make_overflow_menu`` re-creates a ``QMenu`` parented to the long-lived
    card-context island on every open.  Without ``WA_DeleteOnClose`` those
    menus are never freed — each open leaks one more ``QMenu`` (and its
    actions) for the life of the application.
    """
    context = CardContextIsland()
    qtbot.addWidget(context)
    context.show_for("time", "view-1")

    first = context.make_overflow_menu()
    assert first.testAttribute(Qt.WA_DeleteOnClose)
    first.close()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(first)

    # Repeated opens must not accumulate live menus as children either.
    second = context.make_overflow_menu()
    third = context.make_overflow_menu()
    second.close()
    third.close()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(second)
    assert sip.isdeleted(third)


_EXIT_FILL = QColor("#24697C")
_QSS_PATH = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui_kit" / "style.qss"


def test_presentation_exit_qss_does_not_use_page_descendant_id():
    import re

    qss = re.sub(r"/\*.*?\*/", "", _QSS_PATH.read_text(encoding="utf-8"), flags=re.S)
    assert "QWidget#ultraViewPage[presentation" not in qss
    assert "QToolButton#ultraViewGlobalPresentationButton" not in qss
    assert 'QToolButton[chrome="ultraview"][role="presentationExit"]' in qss


def _accent_fill_hits(widget: QWidget) -> int:
    image = widget.grab().toImage()
    hits = 0
    for x in range(2, max(3, image.width() - 2), 3):
        for y in range(2, max(3, image.height() - 2), 3):
            pixel = QColor(image.pixel(x, y))
            if (
                abs(pixel.red() - _EXIT_FILL.red()) < 18
                and abs(pixel.green() - _EXIT_FILL.green()) < 18
                and abs(pixel.blue() - _EXIT_FILL.blue()) < 18
            ):
                hits += 1
    return hits


def _center_luma_hits(button: QToolButton, *, max_luma: float | None = None, min_luma: float | None = None) -> int:
    image = button.grab().toImage()
    cx, cy = image.width() // 2, image.height() // 2
    hits = 0
    for x in range(cx - 6, cx + 7):
        for y in range(cy - 6, cy + 7):
            pixel = QColor(image.pixel(x, y))
            luma = 0.299 * pixel.red() + 0.587 * pixel.green() + 0.114 * pixel.blue()
            if max_luma is not None and luma < max_luma:
                hits += 1
            if min_luma is not None and luma > min_luma:
                hits += 1
    return hits


def _white_padding_hits(widget: QWidget) -> int:
    image = widget.grab().toImage()
    width, height = image.width(), image.height()
    samples = (
        (width // 2, 2),
        (width // 2, max(2, height - 3)),
        (2, height // 2),
        (max(2, width - 3), height // 2),
    )
    hits = 0
    for x, y in samples:
        pixel = QColor(image.pixel(x, y))
        if pixel.red() > 240 and pixel.green() > 240 and pixel.blue() > 240:
            hits += 1
    return hits


def test_idle_presentation_button_is_not_exit_fill(qapp, qtbot):
    from mf4_analyzer.ui_kit import load_stylesheet

    previous = qapp.styleSheet()
    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    try:
        host = QWidget()
        host.setObjectName("ultraViewPage")
        host.setProperty("presentation", "false")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(8, 8, 8, 8)
        island = GlobalIsland(host)
        layout.addWidget(island)
        qtbot.addWidget(host)
        host.show()
        qtbot.waitExposed(host)
        qapp.processEvents()

        button = island.presentation_button()
        assert button.property("role") == "icon"
        assert _accent_fill_hits(button) == 0

        island.set_presentation_checked(True)
        host.setProperty("presentation", "true")
        host.style().unpolish(host)
        host.style().polish(host)
        qapp.processEvents()
        assert button.isChecked()
        assert button.property("role") == "presentationExit"
        assert button.property("active") == "true"
        assert island.property("presentation") == "true"
        assert _accent_fill_hits(button) >= 6
        assert _white_padding_hits(island) == 0
        # The titanium end of the gradient is deliberately darker than the
        # former flat blue fill.  Verify the light glyph itself, not a fake
        # all-bright centre region that would reject a legitimate gradient.
        assert _center_luma_hits(button, min_luma=200) >= 4

        island.set_presentation_checked(False)
        host.setProperty("presentation", "false")
        host.style().unpolish(host)
        host.style().polish(host)
        qapp.processEvents()
        assert not button.isChecked()
        assert button.property("role") == "icon"
        assert button.property("active") == "false"
        assert island.property("presentation") == "false"
        assert _accent_fill_hits(button) == 0
    finally:
        qapp.setStyleSheet(previous)


def test_presentation_click_cycle_restores_idle_role(qtbot):
    island = GlobalIsland()
    qtbot.addWidget(island)
    island.show()
    button = island.presentation_button()
    QTest.mouseClick(button, Qt.LeftButton)
    assert button.isChecked()
    assert button.property("role") == "presentationExit"
    QTest.mouseClick(button, Qt.LeftButton)
    assert not button.isChecked()
    assert button.property("role") == "icon"
    assert button.property("active") == "false"
    assert not button.isDown()


def _icon_mean_color(button: QToolButton) -> QColor:
    size = button.iconSize()
    side = max(16, int(size.width()), int(size.height()))
    image = button.icon().pixmap(side, side).toImage()
    total = [0, 0, 0]
    count = 0
    for x in range(image.width()):
        for y in range(image.height()):
            # ``QColor(QImage.pixel())`` discards the alpha from an ARGB
            # icon pixmap, turning its transparent background into opaque
            # black and masking a white active glyph.
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < 40:
                continue
            total[0] += pixel.red()
            total[1] += pixel.green()
            total[2] += pixel.blue()
            count += 1
    if count == 0:
        return QColor(0, 0, 0)
    return QColor(total[0] // count, total[1] // count, total[2] // count)


def _color_distance(left: QColor, right: QColor) -> float:
    return (
        (left.red() - right.red()) ** 2
        + (left.green() - right.green()) ** 2
        + (left.blue() - right.blue()) ** 2
    ) ** 0.5


def test_canvas_host_paints_titanium_amber_field(qtbot):
    host = CanvasHost()
    qtbot.addWidget(host)
    host.resize(240, 160)
    host.show()
    qtbot.waitExposed(host)
    image = host.grab().toImage()
    expected = QColor("#F7F8F7")
    for x, y in ((12, 12), (60, 40), (180, 20), (30, 140)):
        pixel = QColor(image.pixel(x, y))
        assert abs(pixel.red() - expected.red()) < 28
        assert abs(pixel.green() - expected.green()) < 28
        assert abs(pixel.blue() - expected.blue()) < 28
    assert host._dot_tile is not None
    assert host._dot_tile_key == (
        expected.name(),
        QColor(44, 82, 93, 43).rgba(),
        host._canvas_dpr(),
    )
    tile = host._dot_tile.toImage()
    alphas = [
        tile.pixelColor(x, y).alpha()
        for x in range(tile.width())
        for y in range(tile.height())
        if tile.pixelColor(x, y).alpha() > 0
    ]
    assert alphas, "dot tile must contain a visible mark"
    assert max(alphas) in (41, 42, 43, 44)


def test_canvas_host_background_is_rasterized_at_device_pixel_ratio(qtbot, monkeypatch):
    host = CanvasHost()
    qtbot.addWidget(host)
    host.resize(120, 80)
    host.show()
    qtbot.waitExposed(host)
    host.grab()

    native_dpr = host._canvas_dpr()
    background = host._background
    assert background is not None
    assert background.devicePixelRatioF() == pytest.approx(native_dpr)
    assert background.width() == max(1, int(round(host.width() * native_dpr)))
    assert background.height() == max(1, int(round(host.height() * native_dpr)))
    assert host._background_dpr == native_dpr
    assert host._dot_tile is not None
    assert host._dot_tile.devicePixelRatioF() == pytest.approx(native_dpr)
    assert host._dot_tile.width() == max(
        1, int(round(ultraview_chrome._DOT_PITCH_PX * native_dpr))
    )

    target_dpr = 2.0 if native_dpr != 2.0 else 3.0
    monkeypatch.setattr(host, "devicePixelRatioF", lambda: target_dpr)
    host.grab()
    rebuilt = host._background
    assert rebuilt is not None
    assert rebuilt is not background
    assert rebuilt.devicePixelRatioF() == pytest.approx(target_dpr)
    assert rebuilt.width() == max(1, int(round(host.width() * target_dpr)))
    assert rebuilt.height() == max(1, int(round(host.height() * target_dpr)))
    assert host._background_dpr == target_dpr
    assert host._dot_tile.devicePixelRatioF() == pytest.approx(target_dpr)

    screen_change = getattr(QEvent, "ScreenChangeInternal", None)
    if screen_change is not None:
        QApplication.sendEvent(host, QEvent(screen_change))
        assert host._background is None
        host.grab()
        assert host._background is not None
        assert host._background.devicePixelRatioF() == pytest.approx(target_dpr)


def test_tool_rail_icon_color_tracks_mode_and_panel_open(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()
    layout = rail.panel_button(PANEL_LAYOUT)
    library = rail.panel_button(PANEL_LIBRARY)
    free = rail.free_grid_button()
    assert layout is not None and library is not None
    rail.set_free_grid_enabled(False)
    layout_mode = _icon_mean_color(layout)
    library_rest = _icon_mean_color(library)
    free_rest = _icon_mean_color(free)
    assert _color_distance(layout_mode, library_rest) > 12
    assert layout_mode.blue() >= layout_mode.red()
    # QIcon pixels are baked at creation time, so QSS ``color`` cannot rescue
    # a dark glyph over the filled mode gradient.  Active rail glyphs must be
    # explicitly rendered in the high-contrast light role.
    assert min(layout_mode.red(), layout_mode.green(), layout_mode.blue()) >= 230
    rail.set_free_grid_enabled(True)
    layout_rest = _icon_mean_color(layout)
    free_mode = _icon_mean_color(free)
    assert _color_distance(layout_mode, layout_rest) > 12
    assert _color_distance(free_rest, free_mode) > 12
    assert min(free_mode.red(), free_mode.green(), free_mode.blue()) >= 230
    rail.set_active_panel(PANEL_LIBRARY)
    library_open = _icon_mean_color(library)
    assert _color_distance(library_rest, library_open) > 12
    assert min(library_open.red(), library_open.green(), library_open.blue()) >= 230
    # Every rail destination carries the same explicit open feedback; the
    # gradient is not reserved for the free-grid toggle alone.
    for panel_id in (PANEL_LAYOUT, PANEL_FILTER, PANEL_UNPLACED):
        rail.set_active_panel(panel_id)
        opened = rail.panel_button(panel_id)
        assert opened is not None
        color = _icon_mean_color(opened)
        assert min(color.red(), color.green(), color.blue()) >= 230
    rail.set_active_panel(None)
    assert library.property("panelOpen") != "true"
    assert layout.property("modeActive") != "true"
    assert free.property("modeActive") == "true"
    island = GlobalIsland()
    qtbot.addWidget(island)
    island.set_active_panel("display")
    display_open = _icon_mean_color(island.display_button())
    assert min(display_open.red(), display_open.green(), display_open.blue()) >= 230
    island.set_active_panel("export")
    export_open = _icon_mean_color(island.export_button())
    assert min(export_open.red(), export_open.green(), export_open.blue()) >= 230
    island.set_active_panel(None)
    rest_presentation = _icon_mean_color(island.presentation_button())
    island.set_presentation_checked(True)
    presented = _icon_mean_color(island.presentation_button())
    assert island.presentation_button().property("role") == "presentationExit"
    assert _color_distance(presented, rest_presentation) > 12
    island.set_presentation_checked(False)
    idle = _icon_mean_color(island.presentation_button())
    assert island.presentation_button().property("role") == "icon"
    assert _color_distance(idle, rest_presentation) < 12


def test_tool_rail_empty_board_paints_library_as_primary_cta(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()
    library = rail.panel_button(PANEL_LIBRARY)
    layout = rail.panel_button(PANEL_LAYOUT)
    assert library is not None and layout is not None
    assert rail.sizeHint().width() == RAIL_WIDTH
    assert rail.sizeHint().height() >= RAIL_CONTENT_HEIGHT
    assert library.size() == QSize(RAIL_BUTTON_SIZE, RAIL_BUTTON_SIZE)
    assert library.iconSize() == QSize(RAIL_ICON_SIZE, RAIL_ICON_SIZE)
    assert library.property("emptyCta") != "true"
    rest = _icon_mean_color(library)
    rail.set_empty_board(True)
    assert library.property("emptyCta") == "true"
    assert layout.property("emptyCta") != "true"
    cta = _icon_mean_color(library)
    assert _color_distance(rest, cta) > 12
    assert (cta.red() + cta.green() + cta.blue()) > (
        rest.red() + rest.green() + rest.blue()
    ) + 30
    rail.set_active_panel(PANEL_LIBRARY)
    still_cta = _icon_mean_color(library)
    assert library.property("panelOpen") == "true"
    assert library.property("emptyCta") == "true"
    assert _color_distance(still_cta, cta) < 12
    rail.set_empty_board(False)
    assert library.property("emptyCta") != "true"
    retracted = _icon_mean_color(library)
    # The empty-board CTA has retracted, but the library remains the visible
    # destination; panel-open chrome deliberately keeps its filled treatment.
    assert _color_distance(retracted, cta) < 12
    rail.set_active_panel(None)
    closed = _icon_mean_color(library)
    assert _color_distance(closed, cta) > 12
    assert closed.blue() >= closed.red()


class TestChromeGeometryUnderProductionQss:
    """User-visible sizes must match Python constants after production QSS polish."""

    def test_rail_buttons_warning_dot_and_layout_thumbs_match_python_constants(
        self, qapp, qtbot
    ):
        from mf4_analyzer.ui_kit.stylesheet import load_stylesheet

        load_stylesheet(qapp)
        rail = ToolRail()
        picker = LayoutPicker(LAYOUT_LABELS_ZH)
        qtbot.addWidget(rail)
        qtbot.addWidget(picker)
        rail.show()
        picker.show()
        qapp.processEvents()

        library = rail.panel_button(PANEL_LIBRARY)
        assert library is not None
        assert library.size() == QSize(RAIL_BUTTON_SIZE, RAIL_BUTTON_SIZE)
        assert rail._filter_dot.size() == QSize(8, 8)
        thumbs = list(picker._buttons.values())
        assert thumbs
        for thumb in thumbs:
            assert thumb.minimumHeight() >= 104
            assert thumb.minimumWidth() >= 168
