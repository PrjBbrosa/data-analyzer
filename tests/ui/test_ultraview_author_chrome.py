"""Focused contracts for UltraView's authoring rail and creation popovers."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PyQt5.QtGui import QColor, QHoverEvent, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QMenu, QToolButton, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.author_tools import CLOSED_SHAPE_TYPES

from mf4_analyzer.ui.chart_stack.ultraview.author_style import STICKY_PALETTE_TOKENS

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import (
    FormatChoiceFlyout,
    PointerPopover,
    SelectionToolbar,
    ToolFlyoutSurface,
)
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    POINTER_MODE_LASER,
    POINTER_MODE_MOUSE,
)
from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    AUTHOR_TOOL_CONNECTOR,
    AUTHOR_TOOL_DRAW,
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_SHAPES,
    AUTHOR_TOOL_STICKY,
    AUTHOR_TOOL_TEXT,
    AUTHOR_TOOLS,
    ConnectorPopover,
    DrawPopover,
    OVERLAY_AUTHOR_FORMAT,
    OVERLAY_AUTHOR_POINTER,
    PANEL_LAYOUT,
    PANEL_LIBRARY,
    RAIL_BUTTON_SIZE,
    RAIL_BUTTON_SIZE_COMPACT,
    RAIL_DIVIDER_CLEAR,
    RAIL_DIVIDER_CLEAR_COMPACT,
    RAIL_GROUP_GAP,
    RAIL_GROUP_GAP_COMPACT,
    RAIL_ICON_SIZE,
    RAIL_ICON_SIZE_COMPACT,
    RELEASE_AUTHOR_TOOLS,
    ShapePopover,
    StickyPopover,
    ToolRail,
)
from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import (
    ISLAND_GAP,
    SAFE_MARGIN,
    calculate_floating_layout,
)
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.ultraview_state import BoardBox, ShapeObject, StickyObject, TextObject, default_board, board_to_payload
from mf4_analyzer.ui_kit.stylesheet import load_stylesheet
from mf4_analyzer.ui_kit.ultraview_style import ULTRAVIEW_TITANIUM
from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid


def test_creation_rail_is_independent_from_panel_selection_and_starts_disabled(qtbot):
    rail = ToolRail(visible_author_tools=AUTHOR_TOOLS)
    qtbot.addWidget(rail)
    rail.show()

    requested: list[str] = []
    panels: list[str] = []
    rail.tool_requested.connect(requested.append)
    rail.panel_requested.connect(panels.append)

    ordered = (
        AUTHOR_TOOL_SELECT,
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_CONNECTOR,
        AUTHOR_TOOL_DRAW,
    )
    buttons = [rail.tool_button(tool) for tool in ordered]
    assert all(button is not None for button in buttons)
    assert all(not button.isEnabled() for button in buttons if button is not None)
    assert rail.active_tool() == AUTHOR_TOOL_SELECT

    rail.set_creation_enabled(True)
    sticky = rail.tool_button(AUTHOR_TOOL_STICKY)
    assert sticky is not None and sticky.isEnabled()
    QTest.mouseClick(sticky, Qt.LeftButton)
    assert requested == [AUTHOR_TOOL_STICKY]
    assert panels == []

    rail.set_active_tool(AUTHOR_TOOL_STICKY, pinned=True)
    assert sticky.property("active") == "true"
    assert sticky.property("pinned") == "true"
    assert sticky.property("panelOpen") == "false"
    assert sticky.property("modeActive") == "false"
    assert rail.active_panel() is None

    rail.set_creation_enabled(False, "模板布局中不能创建")
    assert all(not button.isEnabled() for button in buttons if button is not None)
    assert sticky.toolTip() == "模板布局中不能创建"
    assert rail.active_tool() == AUTHOR_TOOL_SELECT


def test_creation_rail_stays_whole_and_keyboard_reachable_in_compact_safe_band(qtbot):
    rail = ToolRail(visible_author_tools=AUTHOR_TOOLS)
    qtbot.addWidget(rail)
    rail.set_compact(True)
    rail.show()
    rail.adjustSize()
    rail.resize(rail.sizeHint())
    QApplication.processEvents()
    assert rail.sizeHint().height() <= 560

    previous_bottom = -1
    for tool in (
        AUTHOR_TOOL_SELECT,
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_CONNECTOR,
        AUTHOR_TOOL_DRAW,
    ):
        button = rail.tool_button(tool)
        assert button is not None
        top = button.mapTo(rail, button.rect().topLeft()).y()
        bottom = button.mapTo(rail, button.rect().bottomRight()).y()
        assert top > previous_bottom
        assert bottom < rail.height()
        assert button.focusPolicy() == Qt.TabFocus
        previous_bottom = bottom


def test_creation_popovers_expose_miro_v1_choices_and_typed_intents(qtbot):
    sticky = StickyPopover()
    shapes = ShapePopover()
    draw = DrawPopover()
    for widget in (sticky, shapes, draw):
        qtbot.addWidget(widget)

    assert sticky.palette_tokens() == STICKY_PALETTE_TOKENS
    assert len(sticky.palette_buttons()) == 16
    palettes: list[str] = []
    stacks: list[str] = []
    sticky.palette_selected.connect(palettes.append)
    sticky.stack_requested.connect(stacks.append)
    sticky.choose_palette("teal")
    sticky.request_stack()
    assert palettes == ["teal"]
    assert stacks == ["teal"]

    assert shapes.shape_types() == CLOSED_SHAPE_TYPES
    catalog = {button.property("catalogKind") for button in shapes.cell_buttons()}
    assert {"line", "arrow", "elbow_arrow"} <= catalog
    assert set(CLOSED_SHAPE_TYPES) <= catalog
    assert "block_arrow" not in catalog
    assert len(shapes.cell_buttons()) == 8
    chosen_shapes: list[str] = []
    shapes.shape_selected.connect(chosen_shapes.append)
    shapes.choose_shape("rectangle")
    assert chosen_shapes == ["rectangle"]

    assert draw.subtools() == ("pen", "highlighter", "eraser", "lasso")
    assert len(draw.presets("pen")) == 3
    assert len(draw.presets("highlighter")) == 3
    names = " ".join(child.objectName() for child in draw.findChildren(QToolButton)).lower()
    assert "eraser" in names
    assert "lasso" in names
    assert "precision" not in names
    eraser = draw.session_button("eraser")
    assert eraser is not None
    assert "整笔擦除" in eraser.toolTip()
    chosen_draw: list[tuple[str, int]] = []

    def record_draw(tool: str, index: int) -> None:
        chosen_draw.append((tool, index))

    draw.tool_selected.connect(record_draw)
    draw.choose_tool("highlighter", 2)
    assert chosen_draw == [("highlighter", 2)]


def test_sticky_popover_is_a_frame_flyout_not_a_menu(qtbot):
    sticky = StickyPopover()
    qtbot.addWidget(sticky)
    assert isinstance(sticky, ToolFlyoutSurface)
    assert isinstance(sticky, QFrame)
    assert not isinstance(sticky, QMenu)


def test_shape_popover_is_a_frame_flyout_not_a_menu(qtbot):
    shapes = ShapePopover()
    qtbot.addWidget(shapes)
    assert isinstance(shapes, ToolFlyoutSurface)
    assert isinstance(shapes, QFrame)
    assert not isinstance(shapes, QMenu)
    assert shapes.shape_types() == CLOSED_SHAPE_TYPES


def test_connector_popover_is_a_frame_flyout_not_a_menu(qtbot):
    connectors = ConnectorPopover()
    qtbot.addWidget(connectors)
    assert isinstance(connectors, ToolFlyoutSurface)
    assert isinstance(connectors, QFrame)
    assert not isinstance(connectors, QMenu)
    assert connectors.connector_types() == ("line", "arrow", "elbow_arrow")


def test_draw_popover_is_a_frame_flyout_not_a_menu(qtbot):
    draw = DrawPopover()
    qtbot.addWidget(draw)
    assert isinstance(draw, ToolFlyoutSurface)
    assert isinstance(draw, QFrame)
    assert not isinstance(draw, QMenu)
    assert draw.subtools() == ("pen", "highlighter", "eraser", "lasso")
    assert draw.findChildren(QMenu) == []


def test_release_rail_constructs_select_sticky_text_shapes_and_draw():
    assert RELEASE_AUTHOR_TOOLS == ("select", "sticky", "text", "shapes", "draw")
    rail = ToolRail()
    assert rail.visible_author_tools() == (
        AUTHOR_TOOL_SELECT,
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_DRAW,
    )
    assert rail.tool_button(AUTHOR_TOOL_SELECT) is not None
    assert rail.tool_button(AUTHOR_TOOL_TEXT) is not None
    assert rail.tool_button(AUTHOR_TOOL_SHAPES) is not None
    assert rail.tool_button(AUTHOR_TOOL_CONNECTOR) is None
    assert rail.tool_button(AUTHOR_TOOL_DRAW) is not None
    rail.set_creation_enabled(True)
    rail.set_active_tool(AUTHOR_TOOL_SELECT)
    assert rail.active_tool() == AUTHOR_TOOL_SELECT
    pointer = rail.tool_button(AUTHOR_TOOL_SELECT)
    sticky = rail.tool_button(AUTHOR_TOOL_STICKY)
    assert pointer is not None and pointer.property("active") == "true"
    assert sticky is not None
    assert sticky.property("active") != "true"


def test_panel_and_tool_active_states_are_orthogonal(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.set_creation_enabled(True)
    rail.set_active_tool(AUTHOR_TOOL_STICKY)
    rail.set_active_panel("library")
    sticky = rail.tool_button(AUTHOR_TOOL_STICKY)
    library = rail.panel_button("library")
    assert sticky is not None and library is not None
    assert sticky.property("active") == "true"
    assert sticky.property("panelOpen") == "false"
    assert library.property("panelOpen") == "true"
    assert library.property("active") != "true"


def test_selection_toolbar_is_single_row_and_overflows_when_compact(qtbot):
    toolbar = SelectionToolbar()
    qtbot.addWidget(toolbar)
    toolbar.show()
    toolbar.set_kind("sticky")
    assert toolbar.height() == 48
    assert toolbar.kind() == "sticky"
    toolbar.resize(220, 48)
    toolbar.set_compact(True)
    assert toolbar.height() == 48


def _rail_icon_buttons(rail: ToolRail) -> list[QToolButton]:
    return [
        button
        for button in rail.findChildren(QToolButton)
        if button.property("chrome") == "ultraview" and button.property("role") == "icon"
    ]


def _button_image(button: QToolButton) -> QImage:
    image = QImage(button.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    button.render(painter)
    painter.end()
    return image


def _prepare_page(qtbot, qapp, size=(1280, 720)) -> UltraViewPage:
    load_stylesheet(qapp)
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(*size)
    page.show()
    page.set_board(default_board())
    QApplication.processEvents()
    page.tool_rail().set_creation_enabled(True)
    QApplication.processEvents()
    return page


def test_release_rail_shows_pointer_as_the_default_select_tool(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.set_creation_enabled(True)
    assert AUTHOR_TOOL_SELECT in rail.visible_author_tools()
    pointer = rail.tool_button(AUTHOR_TOOL_SELECT)
    assert pointer is not None
    assert pointer.objectName() == "ultraViewRailPointerButton"
    assert rail.active_tool() == AUTHOR_TOOL_SELECT
    assert pointer.property("active") == "true"
    assert pointer.property("primaryFill") == "true"
    for tool in rail.visible_author_tools():
        if tool == AUTHOR_TOOL_SELECT:
            continue
        button = rail.tool_button(tool)
        assert button is not None
        assert button.property("active") != "true"


def test_author_button_geometry_does_not_change_across_click_and_active_repolish(qtbot, qapp):
    page = _prepare_page(qtbot, qapp)
    rail = page.tool_rail()
    before = {button.objectName(): QRect(button.geometry()) for button in _rail_icon_buttons(rail)}
    sticky = rail.tool_button(AUTHOR_TOOL_STICKY)
    assert sticky is not None
    QTest.mouseClick(sticky, Qt.LeftButton)
    QApplication.processEvents()
    after = {button.objectName(): QRect(button.geometry()) for button in _rail_icon_buttons(rail)}
    assert before == after
    assert sticky.size().width() == RAIL_BUTTON_SIZE
    assert sticky.size().height() == RAIL_BUTTON_SIZE


def test_all_toolrail_buttons_share_one_outer_and_icon_size_per_breakpoint(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()
    QApplication.processEvents()
    desktop = _rail_icon_buttons(rail)
    assert desktop
    sizes = {(button.width(), button.height()) for button in desktop}
    assert sizes == {(RAIL_BUTTON_SIZE, RAIL_BUTTON_SIZE)}
    assert {button.iconSize().width() for button in desktop} == {RAIL_ICON_SIZE}
    rail.set_compact(True)
    QApplication.processEvents()
    compact = _rail_icon_buttons(rail)
    assert {button.size().width() for button in compact} == {RAIL_BUTTON_SIZE_COMPACT}
    assert {button.iconSize().width() for button in compact} == {RAIL_ICON_SIZE_COMPACT}


def test_author_active_button_renders_selected_blue_wash(qtbot, qapp):
    page = _prepare_page(qtbot, qapp)
    sticky = page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    assert sticky is not None
    QTest.mouseClick(sticky, Qt.LeftButton)
    QApplication.processEvents()
    image = _button_image(sticky)
    start = image.pixelColor(2, 2)
    end = image.pixelColor(image.width() - 3, image.height() - 3)
    wash = QColor(ULTRAVIEW_TITANIUM["selected_wash"])
    selected = QColor(ULTRAVIEW_TITANIUM["selected"])
    assert start.blue() >= start.red()
    assert end.blue() >= end.red()
    assert abs(start.red() - wash.red()) < 48
    assert abs(start.green() - wash.green()) < 48
    assert abs(start.blue() - wash.blue()) < 48
    assert abs(end.red() - start.red()) < 36
    assert selected.red() != selected.green()


def test_author_active_icon_remains_visible_on_blue_wash(qtbot, qapp):
    page = _prepare_page(qtbot, qapp)
    sticky = page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    assert sticky is not None
    QTest.mouseClick(sticky, Qt.LeftButton)
    QApplication.processEvents()
    image = _button_image(sticky)
    blue_ink = 0
    samples = 0
    for x in range(8, image.width() - 8):
        for y in range(8, image.height() - 8):
            color = image.pixelColor(x, y)
            if color.alpha() < 20:
                continue
            samples += 1
            if color.blue() > color.red() + 20 and color.blue() > 120:
                blue_ink += 1
    assert samples > 0
    assert blue_ink > 8


def test_shape_flyout_contains_last_item_without_scroll_at_1280x720(qtbot, qapp):
    page = _prepare_page(qtbot, qapp, (1280, 720))
    shapes = page.tool_rail().tool_button(AUTHOR_TOOL_SHAPES)
    QTest.mouseClick(shapes, Qt.LeftButton)
    QApplication.processEvents()
    flyout = page.shape_popover()
    assert flyout.isVisible()
    last = flyout.cell_buttons()[-1]
    content = flyout.content_widget()
    assert last.geometry().bottom() <= content.height()
    assert flyout._scroll.verticalScrollBar().maximum() == 0
    assert last.isVisible()


def test_shape_flyout_contains_last_item_without_scroll_at_800x560(qtbot, qapp):
    page = _prepare_page(qtbot, qapp, (800, 560))
    shapes = page.tool_rail().tool_button(AUTHOR_TOOL_SHAPES)
    QTest.mouseClick(shapes, Qt.LeftButton)
    QApplication.processEvents()
    flyout = page.shape_popover()
    assert flyout.isVisible()
    last = flyout.cell_buttons()[-1]
    host = flyout.rect()
    mapped = last.mapTo(flyout, last.rect().bottomRight())
    assert mapped.y() <= host.height()
    assert last.isVisible()


def test_sticky_swatches_remain_square_after_popup_polish(qtbot, qapp):
    page = _prepare_page(qtbot, qapp)
    sticky = page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    QTest.mouseClick(sticky, Qt.LeftButton)
    QApplication.processEvents()
    flyout = page.sticky_popover()
    for button in flyout.palette_buttons():
        assert button.width() == button.height()
        assert button.width() == 48


def test_draw_color_swatches_remain_square_after_popup_polish(qtbot, qapp):
    page = _prepare_page(qtbot, qapp)
    draw = page.tool_rail().tool_button(AUTHOR_TOOL_DRAW)
    QTest.mouseClick(draw, Qt.LeftButton)
    QApplication.processEvents()
    flyout = page.draw_popover()
    flyout.show_preset_editor(True)
    QApplication.processEvents()
    for token, button in flyout._color_buttons.items():
        del token
        assert button.isVisible()
        assert button.width() == button.height()


def test_draw_tool_width_and_color_changes_keep_flyout_open(qtbot, qapp):
    page = _prepare_page(qtbot, qapp)
    draw = page.tool_rail().tool_button(AUTHOR_TOOL_DRAW)
    QTest.mouseClick(draw, Qt.LeftButton)
    QApplication.processEvents()
    flyout = page.draw_popover()
    assert flyout.isVisible()
    highlighter = flyout._tool_buttons["highlighter"]
    QTest.mouseClick(highlighter, Qt.LeftButton)
    QApplication.processEvents()
    assert flyout.isVisible()
    width = flyout.preset_buttons("pen")[1]
    QTest.mouseClick(width, Qt.LeftButton)
    QApplication.processEvents()
    assert flyout.isVisible()
    flyout.show_preset_editor(True)
    QApplication.processEvents()
    color = flyout._color_buttons["red"]
    QTest.mouseClick(color, Qt.LeftButton)
    QApplication.processEvents()
    assert flyout.isVisible()


def test_active_sticky_click_closes_then_third_click_reopens_palette(qtbot, qapp):
    page = _prepare_page(qtbot, qapp)
    button = page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    flyout = page.sticky_popover()
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    assert flyout.isVisible()
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    assert not flyout.isVisible()
    assert page.interaction().active_tool() == AUTHOR_TOOL_STICKY
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    assert flyout.isVisible()


def test_selection_toolbar_is_clamped_inside_host_safe_rect_on_all_four_edges(qtbot, qapp):
    from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid

    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    harness.page.resize(1280, 720)
    free, _cards = _prepare_free_grid(harness, qtbot, "edge-0")
    note = StickyObject("edge-note", "sticky", box=BoardBox(2.0, 28.0, 3.0, 2.0), text="边")
    harness.board.author_objects = [note]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().select_only_author("edge-note")
    free.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    toolbar = harness.page.selection_toolbar()
    host = harness.page.canvas_host()
    assert toolbar.isVisible()
    safe = host.contentsRect().adjusted(SAFE_MARGIN, SAFE_MARGIN, -SAFE_MARGIN, -SAFE_MARGIN)
    geom = toolbar.geometry()
    assert geom.left() >= safe.left()
    assert geom.top() >= safe.top()
    assert geom.right() <= safe.right()
    assert geom.bottom() <= safe.bottom()


def _map_top(widget, host) -> int:
    return widget.mapTo(host, QPoint(0, 0)).y()


def _map_bottom(widget, host) -> int:
    return widget.mapTo(host, widget.rect().bottomLeft()).y()


def _ink_bounds(image: QImage) -> QRect:
    left, top, right, bottom = image.width(), image.height(), -1, -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() < 24:
                continue
            left = min(left, x)
            right = max(right, x)
            top = min(top, y)
            bottom = max(bottom, y)
    if right < 0:
        return QRect()
    return QRect(left, top, right - left + 1, bottom - top + 1)


def test_release_rail_has_minimum_intragroup_gaps_and_divider_clear_space(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()
    QApplication.processEvents()
    library = rail.panel_button(PANEL_LIBRARY)
    free = rail.free_grid_button()
    layout = rail.panel_button(PANEL_LAYOUT)
    filt = rail.panel_button("filter")
    sticky = rail.tool_button(AUTHOR_TOOL_STICKY)
    text = rail.tool_button(AUTHOR_TOOL_TEXT)
    assert None not in (library, free, layout, filt, sticky, text)
    assert _map_top(free, rail) - _map_bottom(library, rail) - 1 == RAIL_GROUP_GAP
    assert _map_top(text, rail) - _map_bottom(sticky, rail) - 1 == RAIL_GROUP_GAP
    divider = rail.findChild(QFrame, "ultraViewToolRailCreationDivider")
    assert divider is not None
    assert _map_top(divider, rail) - _map_bottom(filt, rail) - 1 == RAIL_DIVIDER_CLEAR
    rail.set_compact(True)
    rail.adjustSize()
    rail.resize(rail.sizeHint())
    QApplication.processEvents()
    assert _map_top(free, rail) - _map_bottom(library, rail) - 1 == RAIL_GROUP_GAP_COMPACT
    assert _map_top(divider, rail) - _map_bottom(filt, rail) - 1 == RAIL_DIVIDER_CLEAR_COMPACT


def test_compact_release_rail_size_hint_fits_800x560_band(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.set_creation_enabled(True)
    rail.set_compact(True)
    rail.show()
    rail.adjustSize()
    QApplication.processEvents()
    layout = calculate_floating_layout((800, 560))
    band = layout.status_island.top - ISLAND_GAP - (layout.board_island.bottom + ISLAND_GAP)
    assert rail.sizeHint().height() <= band
    assert AUTHOR_TOOL_SELECT in RELEASE_AUTHOR_TOOLS
    for tool in RELEASE_AUTHOR_TOOLS:
        button = rail.tool_button(tool)
        assert button is not None and button.isVisible()
        assert button.size() == QSize(RAIL_BUTTON_SIZE_COMPACT, RAIL_BUTTON_SIZE_COMPACT)


def test_only_one_rail_button_uses_primary_filled_state(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.set_creation_enabled(True)
    rail.set_free_grid_enabled(True)
    rail.set_active_panel(PANEL_LAYOUT)
    rail.set_active_tool(AUTHOR_TOOL_DRAW)
    filled = [
        button.objectName()
        for button in rail.findChildren(QToolButton)
        if button.property("primaryFill") == "true"
    ]
    assert filled == ["ultraViewRailDrawButton"]
    rail.set_active_tool(AUTHOR_TOOL_SELECT)
    filled = [
        button.objectName()
        for button in rail.findChildren(QToolButton)
        if button.property("primaryFill") == "true"
    ]
    assert filled == ["ultraViewRailPointerButton"]


def test_author_active_hover_and_pressed_keep_blue_wash(qtbot, qapp):
    page = _prepare_page(qtbot, qapp)
    sticky = page.tool_rail().tool_button(AUTHOR_TOOL_STICKY)
    assert sticky is not None
    QTest.mouseClick(sticky, Qt.LeftButton)
    QApplication.processEvents()
    sticky.setAttribute(Qt.WA_Hover, True)
    QApplication.sendEvent(
        sticky,
        QHoverEvent(QEvent.HoverEnter, QPoint(12, 12), QPoint(12, 12)),
    )
    sticky.update()
    QApplication.processEvents()
    hover = _button_image(sticky)
    hover_color = hover.pixelColor(2, 2)
    assert hover_color.blue() >= hover_color.red()
    sticky.setDown(True)
    QApplication.processEvents()
    pressed = _button_image(sticky)
    pressed_color = pressed.pixelColor(2, 2)
    assert pressed_color.blue() >= pressed_color.red()
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    assert 'primaryFill="true"]:hover' in qss
    assert "UV_SELECTED_WASH" in qss


def test_author_icons_share_rendered_ink_bounds_and_draw_icon_is_stable_across_subtools(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.set_creation_enabled(True)
    rail.show()
    QApplication.processEvents()
    boxes = []
    for tool in (
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_DRAW,
    ):
        button = rail.tool_button(tool)
        pixmap = button.icon().pixmap(RAIL_ICON_SIZE, RAIL_ICON_SIZE)
        boxes.append(_ink_bounds(pixmap.toImage()))
    widths = {box.width() for box in boxes}
    heights = {box.height() for box in boxes}
    assert max(widths) - min(widths) <= 2
    assert max(heights) - min(heights) <= 2
    draw = rail.tool_button(AUTHOR_TOOL_DRAW)
    before = draw.icon().pixmap(RAIL_ICON_SIZE, RAIL_ICON_SIZE).toImage()
    rail.set_draw_subtool("eraser")
    after = draw.icon().pixmap(RAIL_ICON_SIZE, RAIL_ICON_SIZE).toImage()
    assert before == after


def test_sticky_palette_is_two_columns_eight_rows_and_width_is_bounded(qtbot):
    sticky = StickyPopover()
    qtbot.addWidget(sticky)
    sticky.show()
    sticky.adjustSize()
    buttons = sticky.palette_buttons()
    assert len(buttons) == 16
    columns = {button.x() for button in buttons}
    rows = {button.y() for button in buttons}
    assert len(columns) == 2
    assert len(rows) == 8
    assert 120 <= sticky.width() <= 160
    stack = sticky.findChild(QToolButton, "ultraViewStickyStackButton")
    assert stack is not None
    assert stack.width() <= 120


def test_shapes_catalog_is_one_column_with_visible_labels_and_shortcuts(qtbot):
    shapes = ShapePopover()
    qtbot.addWidget(shapes)
    shapes.show()
    shapes.adjustSize()
    rows = shapes.cell_buttons()
    assert len(rows) == 8
    xs = {button.x() for button in rows}
    assert len(xs) == 1
    labels = " ".join(button.catalog_title() for button in rows)
    assert "直线" in labels
    assert "矩形" in labels
    assert all(not button.text() for button in rows)
    assert all(36 <= button.height() <= 38 for button in rows)
    assert 200 <= shapes.width() <= 216
    assert any("L" in (getattr(row, "_shortcut", "") or "") for row in rows)


def test_pointer_popover_has_two_36px_rows_and_blue_selected_mode(qtbot):
    popover = PointerPopover()
    qtbot.addWidget(popover)
    popover.show()
    popover.adjustSize()
    mouse = popover.row_button(POINTER_MODE_MOUSE)
    laser = popover.row_button(POINTER_MODE_LASER)
    assert mouse is not None and laser is not None
    assert mouse.height() == 36
    assert laser.height() == 36
    assert mouse.property("selected") == "true"
    assert laser.property("selected") == "false"
    laser_hint = laser.findChild(QLabel, "ultraViewPointerModeHint")
    assert laser_hint is not None
    assert laser_hint.text() == "选择、移动、缩放；仅换成发光圆点光标"
    chosen: list[str] = []
    popover.mode_selected.connect(chosen.append)
    QTest.mouseClick(laser, Qt.LeftButton)
    assert chosen == [POINTER_MODE_LASER]
    assert popover.current_mode() == POINTER_MODE_LASER
    assert laser.property("selected") == "true"
    assert mouse.property("selected") == "false"
    size = popover.content_size()
    assert size.width() >= 200
    assert size.height() >= 80


@pytest.mark.parametrize(
    ("compact", "expected_size"),
    ((False, RAIL_BUTTON_SIZE), (True, RAIL_BUTTON_SIZE_COMPACT)),
)
def test_pointer_tile_any_click_or_keyboard_activation_opens_menu_without_selecting(qtbot, compact, expected_size):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.set_creation_enabled(True)
    rail.set_compact(compact)
    rail.show()
    QApplication.processEvents()
    pointer = rail.tool_button(AUTHOR_TOOL_SELECT)
    assert pointer is not None
    tools: list[str] = []
    menus: list[int] = []
    rail.tool_requested.connect(tools.append)
    rail.pointer_menu_requested.connect(lambda: menus.append(1))
    assert pointer.size() == QSize(expected_size, expected_size)

    QTest.mouseClick(pointer, Qt.LeftButton, Qt.NoModifier, QPoint(3, 3))
    QTest.mouseClick(pointer, Qt.LeftButton, Qt.NoModifier, QPoint(pointer.width() - 3, 3))
    pointer.setFocus(Qt.OtherFocusReason)
    QTest.keyClick(pointer, Qt.Key_Space)

    assert menus == [1, 1, 1]
    assert tools == []


def test_pointer_standard_click_emits_menu_requested_once(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.set_creation_enabled(True)
    rail.show()
    QApplication.processEvents()
    pointer = rail.tool_button(AUTHOR_TOOL_SELECT)
    assert pointer is not None
    menus: list[int] = []
    tools: list[str] = []
    rail.pointer_menu_requested.connect(lambda: menus.append(1))
    rail.tool_requested.connect(tools.append)
    assert pointer.accessibleName() == "选择鼠标或激光笔 (V)"
    assert pointer.property("role") == "icon"
    assert pointer.property("open") == "false"
    assert pointer.property("panelOpen") == "false"

    pointer.click()
    assert menus == [1]
    QTest.mouseClick(pointer, Qt.LeftButton)
    assert menus == [1, 1]
    pointer.setFocus(Qt.OtherFocusReason)
    QTest.keyClick(pointer, Qt.Key_Return)
    assert menus == [1, 1, 1]
    assert tools == []


def test_opening_pointer_popup_does_not_change_mode_selection_history_or_zoom(qtbot):
    harness = _Harness(qtbot)
    _prepare_free_grid(harness, qtbot, "ptr-0")
    page = harness.page
    interaction = page.interaction()
    before_mode = interaction.pointer_mode()
    before_selection = tuple(interaction.selection())
    before_zoom = page.board_zoom()
    before_payload = board_to_payload(harness.board)
    pointer = page.tool_rail().tool_button(AUTHOR_TOOL_SELECT)
    assert pointer is not None
    pointer.click()
    QApplication.processEvents()
    popover = page.pointer_popover()
    assert popover.isVisible()
    assert page.canvas_host().active_overlay() == OVERLAY_AUTHOR_POINTER
    assert pointer.property("open") == "true"
    assert pointer.property("panelOpen") == "true"
    assert pointer.accessibleName() == "选择鼠标或激光笔 (V)"
    assert interaction.pointer_mode() == before_mode
    assert tuple(interaction.selection()) == before_selection
    assert page.board_zoom() == before_zoom
    assert board_to_payload(harness.board) == before_payload
    pointer.click()
    QApplication.processEvents()
    assert not popover.isVisible()
    assert pointer.property("open") == "false"
    assert pointer.property("panelOpen") == "false"
    assert interaction.pointer_mode() == before_mode
    assert tuple(interaction.selection()) == before_selection
    assert page.board_zoom() == before_zoom
    assert board_to_payload(harness.board) == before_payload


def test_author_rail_uses_native_desktop_and_compact_icon_targets():
    """Readable tool glyphs use the 24/20px sources without widening hits."""
    assert (RAIL_ICON_SIZE, RAIL_ICON_SIZE_COMPACT) == (24, 20)


def test_draw_popover_is_vertical_and_exposes_three_presets_not_an_always_visible_color_matrix(qtbot):
    draw = DrawPopover()
    qtbot.addWidget(draw)
    draw.resize(draw.content_size())
    draw.show()
    QApplication.processEvents()
    tools = [draw._tool_buttons[name] for name in ("pen", "highlighter", "eraser", "lasso")]
    xs = {button.x() for button in tools}
    assert max(xs) - min(xs) <= 2
    assert tools[0].y() < tools[1].y() < tools[2].y() < tools[3].y()
    assert {button.size().width() for button in tools} == {48}
    assert {button.iconSize().width() for button in tools} == {28}
    presets = draw.preset_buttons("pen")
    assert len(presets) == 3
    assert not draw.preset_editor_visible()
    for button in draw._color_buttons.values():
        assert not button.isVisible()
    assert 76 <= draw.width() <= 104
    draw.show_preset_editor(True)
    QApplication.processEvents()
    assert any(button.isVisible() for button in draw._color_buttons.values())
    assert draw.findChild(QWidget, "ultraViewDrawColorRow") is not None


def test_selection_toolbar_cells_do_not_inherit_global_button_border_or_gradient(qtbot, qapp):
    load_stylesheet(qapp)
    toolbar = SelectionToolbar()
    qtbot.addWidget(toolbar)
    toolbar.show()
    QApplication.processEvents()
    button = toolbar.button("palette") or toolbar.button("font_role") or toolbar.button("font_size")
    assert button is not None
    assert button.property("role") == "selectionToolbarCell"
    image = QImage(button.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    button.render(painter)
    painter.end()
    corner = image.pixelColor(1, 1)
    assert corner.alpha() < 40


def test_selection_toolbar_has_expected_group_dividers(qtbot):
    toolbar = SelectionToolbar()
    qtbot.addWidget(toolbar)
    toolbar.set_kind("shape")
    assert len(toolbar.group_dividers()) >= 1
    toolbar.set_kind("text")
    assert len(toolbar.group_dividers()) >= 2


def test_font_and_size_pickers_are_single_column_content_driven_surfaces(qtbot):
    picker = FormatChoiceFlyout()
    qtbot.addWidget(picker)
    picker.present_labels(
        (("sans", "Sans"), ("serif", "Serif"), ("mono", "Mono")),
        current="sans",
        presentation="font",
    )
    picker.adjustSize()
    picker.show()
    QApplication.processEvents()
    assert picker.column_count() == 1
    assert 112 <= picker.width() <= 120
    picker.present_labels(
        tuple((size, str(size)) for size in ("auto", 12, 14, 18, 24)),
        current=14,
        presentation="font_size",
    )
    picker.adjustSize()
    QApplication.processEvents()
    assert picker.column_count() == 1
    assert 104 <= picker.width() <= 120


def test_format_picker_is_anchored_to_trigger_and_inside_safe_rect(qtbot, qapp):
    from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid

    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    harness.page.resize(1280, 720)
    free, _cards = _prepare_free_grid(harness, qtbot, "picker-0")
    note = StickyObject("picker-note", "sticky", box=BoardBox(4.0, 8.0, 3.0, 2.0), text="字")
    harness.board.author_objects = [note]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().select_only_author("picker-note")
    free.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    toolbar = harness.page.selection_toolbar()
    size_btn = toolbar.button("font_size")
    assert size_btn is not None
    QTest.mouseClick(size_btn, Qt.LeftButton)
    QApplication.processEvents()
    picker = harness.page.format_picker()
    assert picker.isVisible()
    host = harness.page.canvas_host()
    trigger = size_btn.mapTo(host, QPoint(0, size_btn.height()))
    gap = picker.y() - trigger.y()
    assert 4 <= gap <= 8 or picker.y() + picker.height() <= size_btn.mapTo(host, QPoint(0, 0)).y()
    safe = host.contentsRect().adjusted(SAFE_MARGIN, SAFE_MARGIN, -SAFE_MARGIN, -SAFE_MARGIN)
    assert picker.geometry().left() >= safe.left()
    assert picker.geometry().right() <= safe.right()
    assert picker.column_count() == 1


def test_format_picker_stays_above_shapes_without_covering_selected_object(qtbot, qapp):
    harness = _prepare_text_selection(
        qtbot, qapp, (1182, 768), box=BoardBox(3.0, 8.0, 4.0, 2.0)
    )
    page = harness.page
    shapes_button = page.tool_rail().tool_button(AUTHOR_TOOL_SHAPES)
    assert shapes_button is not None
    QTest.mouseClick(shapes_button, Qt.LeftButton)
    QApplication.processEvents()
    shapes = page.shape_popover()
    assert shapes.isVisible()

    list_button = page.selection_toolbar().button("list_style")
    assert list_button is not None
    QTest.mouseClick(list_button, Qt.LeftButton)
    QApplication.processEvents()

    picker = page.format_picker()
    host = page.canvas_host()
    bounds = page._selection_bounds_in_host()
    assert bounds is not None
    assert host.active_overlay() == OVERLAY_AUTHOR_FORMAT
    assert picker.isVisible()
    assert not shapes.isVisible()
    assert not picker.geometry().intersects(bounds)
    page._reassert_host_stacking()
    children = [child for child in host.children() if isinstance(child, QWidget) and child.isVisible()]
    assert children[-1] is picker


def test_shape_picker_moves_beside_the_selected_shape_when_below_would_overlap(qtbot, qapp):
    from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid

    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    harness.page.resize(1182, 768)
    free, _cards = _prepare_free_grid(harness, qtbot, "shape-picker-0")
    shape = ShapeObject(
        "shape-picker",
        "shape",
        box=BoardBox(2.0, 8.0, 4.0, 3.0),
        shape="rectangle",
    )
    harness.board.author_objects = [shape]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().select_only_author("shape-picker")
    free.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()

    button = harness.page.selection_toolbar().button("shape")
    assert button is not None
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()

    picker = harness.page.format_picker()
    bounds = harness.page._selection_bounds_in_host()
    assert picker.isVisible()
    assert bounds is not None
    assert not picker.geometry().intersects(bounds)


def test_flyout_corner_pixels_are_transparent_without_rectangular_backing(qtbot, qapp):
    load_stylesheet(qapp)
    sticky = StickyPopover()
    qtbot.addWidget(sticky)
    sticky.resize(128, 280)
    sticky.show()
    QApplication.processEvents()
    image = QImage(sticky.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    sticky.render(painter)
    painter.end()
    for x, y in ((0, 0), (image.width() - 1, 0), (0, image.height() - 1), (image.width() - 1, image.height() - 1)):
        assert image.pixelColor(x, y).alpha() < 30
    center = image.pixelColor(image.width() // 2, 24)
    assert center.alpha() > 200


def _visible_control_keys(toolbar: SelectionToolbar) -> tuple[str, ...]:
    keys = []
    for index in range(toolbar._body_layout.count()):
        widget = toolbar._body_layout.itemAt(index).widget()
        if isinstance(widget, QToolButton) and widget.isVisible():
            key = widget.property("formatKey")
            if key:
                keys.append(str(key))
    return tuple(keys)


def _visible_choice_count(picker: FormatChoiceFlyout) -> int:
    return sum(
        1
        for child in picker.findChildren(QToolButton)
        if child.isVisible() and child.property("choiceValue") is not None
    )


def _author_session(page, key: str) -> dict:
    toolbar = page.selection_toolbar()
    picker = page.format_picker()
    trigger = toolbar.button(key)
    snapshot = {
        "overlay": page.canvas_host().active_overlay(),
        "picker_key": page._format_picker_key,
        "toolbar": QRect(toolbar.geometry()),
        "hint": QSize(toolbar.sizeHint()),
        "keys": _visible_control_keys(toolbar),
        "trigger": QRect(trigger.geometry()) if trigger is not None else QRect(),
        "picker": QRect(picker.geometry()),
        "content": QSize(picker.content_size()),
        "choices": _visible_choice_count(picker),
        "picker_visible": picker.isVisible(),
    }
    QApplication.processEvents()
    after = {
        "overlay": page.canvas_host().active_overlay(),
        "picker_key": page._format_picker_key,
        "toolbar": QRect(toolbar.geometry()),
        "hint": QSize(toolbar.sizeHint()),
        "keys": _visible_control_keys(toolbar),
        "trigger": QRect(trigger.geometry()) if trigger is not None else QRect(),
        "picker": QRect(picker.geometry()),
        "content": QSize(picker.content_size()),
        "choices": _visible_choice_count(picker),
        "picker_visible": picker.isVisible(),
    }
    assert after == snapshot
    return snapshot


def _prepare_text_selection(qtbot, qapp, size, box=BoardBox(4.0, 8.0, 4.0, 2.0)):
    from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid

    load_stylesheet(qapp)
    harness = _Harness(qtbot)
    harness.page.resize(*size)
    QApplication.processEvents()
    free, _cards = _prepare_free_grid(harness, qtbot, "txt-0")
    text = TextObject("t1", "text", box=box, text="Hello")
    harness.board.author_objects = [text]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().select_only_author("t1")
    free.sync_selection_projection()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    return harness


def _open_format_key(page, key: str):
    toolbar = page.selection_toolbar()
    button = toolbar.button(key)
    assert button is not None
    QTest.mouseClick(button, Qt.LeftButton)
    QApplication.processEvents()
    return button


def _assert_picker_open_inside_safe(
    harness, key: str, expected_choices: int, *, require_gap: bool = True
) -> dict:
    page = harness.page
    toolbar = page.selection_toolbar()
    picker = page.format_picker()
    host = page.canvas_host()
    snapshot = _author_session(page, key)
    assert snapshot["overlay"] == OVERLAY_AUTHOR_FORMAT
    assert snapshot["picker_key"] == key
    assert snapshot["picker_visible"] is True
    assert snapshot["choices"] == expected_choices
    safe = host.contentsRect().adjusted(SAFE_MARGIN, SAFE_MARGIN, -SAFE_MARGIN, -SAFE_MARGIN)
    assert snapshot["picker"].left() >= safe.left()
    assert snapshot["picker"].top() >= safe.top()
    assert snapshot["picker"].right() <= safe.right()
    assert snapshot["picker"].bottom() <= safe.bottom()
    assert snapshot["toolbar"].left() >= safe.left()
    assert snapshot["toolbar"].top() >= safe.top()
    assert snapshot["toolbar"].right() <= safe.right()
    assert snapshot["toolbar"].bottom() <= safe.bottom()
    assert not snapshot["picker"].intersects(snapshot["toolbar"])
    trigger = toolbar.button(key)
    assert trigger is not None
    origin = trigger.mapTo(host, QPoint(0, 0))
    below_gap = snapshot["picker"].top() - (origin.y() + trigger.height())
    above_gap = origin.y() - snapshot["picker"].bottom()
    if require_gap:
        assert 4 <= below_gap <= 8 or 4 <= above_gap <= 8
    return snapshot


def _assert_picker_closed(page, key: str, toolbar_rect: QRect, keys: tuple[str, ...]) -> None:
    snapshot = _author_session(page, key)
    assert snapshot["picker_visible"] is False
    assert snapshot["overlay"] != OVERLAY_AUTHOR_FORMAT
    assert snapshot["picker_key"] == ""
    assert snapshot["toolbar"] == toolbar_rect
    assert snapshot["keys"] == keys


@pytest.mark.parametrize("size", [(1182, 768), (800, 560)])
@pytest.mark.parametrize(
    ("key", "expected_choices", "min_w", "max_w"),
    [
        ("font_role", 3, 112, 120),
        ("font_size", 9, 104, 120),
    ],
)
def test_font_and_size_pickers_open_close_open_keep_geometry(
    qtbot, qapp, size, key, expected_choices, min_w, max_w
):
    harness = _prepare_text_selection(qtbot, qapp, size)
    page = harness.page
    toolbar = page.selection_toolbar()
    picker = page.format_picker()
    assert toolbar.isVisible()
    toolbar_before = QRect(toolbar.geometry())
    keys_before = _visible_control_keys(toolbar)

    _open_format_key(page, key)
    first = _assert_picker_open_inside_safe(
        harness, key, expected_choices, require_gap=(key == "font_role" and size[1] >= 720)
    )
    assert min_w <= first["picker"].width() <= max_w
    assert first["toolbar"] == toolbar_before
    assert first["keys"] == keys_before

    _open_format_key(page, key)
    _assert_picker_closed(page, key, toolbar_before, keys_before)

    _open_format_key(page, key)
    third = _assert_picker_open_inside_safe(
        harness, key, expected_choices, require_gap=(key == "font_role" and size[1] >= 720)
    )
    assert third["picker"] == first["picker"]
    assert third["content"] == first["content"]
    assert third["choices"] == first["choices"]
    assert third["toolbar"] == toolbar_before
    assert picker.isVisible() is True


@pytest.mark.parametrize("size", [(1182, 768), (800, 560)])
def test_font_role_then_size_then_role_does_not_inherit_geometry(qtbot, qapp, size):
    harness = _prepare_text_selection(qtbot, qapp, size)
    page = harness.page
    toolbar = page.selection_toolbar()
    toolbar_rect = QRect(toolbar.geometry())
    keys = _visible_control_keys(toolbar)

    _open_format_key(page, "font_role")
    font = _assert_picker_open_inside_safe(
        harness, "font_role", 3, require_gap=size[1] >= 720
    )
    assert 112 <= font["picker"].width() <= 120

    _open_format_key(page, "font_size")
    size_shot = _assert_picker_open_inside_safe(harness, "font_size", 9, require_gap=False)
    assert 104 <= size_shot["picker"].width() <= 120
    assert size_shot["picker"].width() != font["picker"].width()
    assert size_shot["picker"].height() != font["picker"].height()
    assert size_shot["toolbar"] == toolbar_rect
    assert size_shot["keys"] == keys

    _open_format_key(page, "font_role")
    again = _assert_picker_open_inside_safe(
        harness, "font_role", 3, require_gap=size[1] >= 720
    )
    assert again["picker"] == font["picker"]
    assert again["content"] == font["content"]
    assert again["choices"] == 3
    assert again["toolbar"] == toolbar_rect


@pytest.mark.parametrize("size", [(1182, 768), (800, 560)])
def test_picker_open_same_schema_refresh_keeps_toolbar_and_picker(qtbot, qapp, size):
    harness = _prepare_text_selection(qtbot, qapp, size)
    page = harness.page
    _open_format_key(page, "font_role")
    before = _assert_picker_open_inside_safe(
        harness, "font_role", 3, require_gap=size[1] >= 720
    )
    font_btn = page.selection_toolbar().button("font_role")
    page._refresh_author_toolbar()
    QApplication.processEvents()
    after = _assert_picker_open_inside_safe(
        harness, "font_role", 3, require_gap=size[1] >= 720
    )
    assert after["toolbar"] == before["toolbar"]
    assert after["picker"] == before["picker"]
    assert after["keys"] == before["keys"]
    assert page.selection_toolbar().button("font_role") is font_btn
    assert page.format_picker().isVisible() is True


@pytest.mark.parametrize("size", [(1182, 768), (800, 560)])
@pytest.mark.parametrize(
    "box",
    [
        BoardBox(8.0, 1.0, 4.0, 2.0),
        BoardBox(8.0, 24.0, 4.0, 2.0),
        BoardBox(0.5, 10.0, 4.0, 2.0),
        BoardBox(18.0, 10.0, 4.0, 2.0),
    ],
)
def test_text_toolbar_and_picker_stay_inside_safe_edges(qtbot, qapp, size, box):
    harness = _prepare_text_selection(qtbot, qapp, size, box=box)
    page = harness.page
    toolbar = page.selection_toolbar()
    assert toolbar.isVisible()
    _open_format_key(page, "font_size")
    _assert_picker_open_inside_safe(harness, "font_size", 9, require_gap=False)
    _open_format_key(page, "font_size")
    _assert_picker_closed(page, "font_size", QRect(toolbar.geometry()), _visible_control_keys(toolbar))


def test_ink_swatch_is_not_sticky_yellow(qtbot):
    from mf4_analyzer.ui.chart_stack.ultraview.author_selection import ToolbarControl
    from mf4_analyzer.ui.chart_stack.ultraview.author_style import ink_color, sticky_colors

    toolbar = SelectionToolbar()
    qtbot.addWidget(toolbar)
    ink = ToolbarControl(
        "color", "颜色", "颜色", icon_role="swatch", value="ink", swatch_role="ink", group="ink"
    )
    sticky = ToolbarControl(
        "palette", "色板", "色板", icon_role="swatch", value="yellow", swatch_role="sticky", group="style"
    )
    toolbar._clear_body()
    toolbar._add_control(ink)
    image = QImage(toolbar.button("color").size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    toolbar.button("color").render(painter)
    painter.end()
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    expected = QColor(*ink_color("ink"))
    yellow = QColor(*sticky_colors("yellow")[0])
    assert abs(center.red() - expected.red()) < 40
    assert abs(center.red() - yellow.red()) > 40
    toolbar._clear_body()
    toolbar._add_control(sticky)
    sticky_img = QImage(toolbar.button("palette").size(), QImage.Format_ARGB32)
    sticky_img.fill(Qt.transparent)
    painter = QPainter(sticky_img)
    toolbar.button("palette").render(painter)
    painter.end()
    sticky_px = sticky_img.pixelColor(sticky_img.width() // 2, sticky_img.height() // 2)
    assert abs(sticky_px.red() - yellow.red()) < 40


def test_transparent_swatch_draws_white_fill_and_red_hatch(qtbot):
    picker = FormatChoiceFlyout()
    qtbot.addWidget(picker)
    picker.present_palette((None, "yellow"), current=None, swatch_role="fill")
    picker.adjustSize()
    picker.show()
    QApplication.processEvents()
    chip = next(
        child
        for child in picker.findChildren(QToolButton)
        if child.property("choiceValue") is None
    )
    assert chip.toolTip() == "透明"
    image = QImage(chip.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    chip.render(painter)
    painter.end()
    whiteish = 0
    redish = 0
    for x in range(image.width()):
        for y in range(image.height()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() < 40:
                continue
            if pixel.red() > 230 and pixel.green() > 230 and pixel.blue() > 230:
                whiteish += 1
            if pixel.red() > 180 and pixel.green() < 90 and pixel.blue() < 90:
                redish += 1
    assert whiteish > 20
    assert redish > 5


@pytest.mark.parametrize(
    ("presentation", "choices", "min_w", "max_w"),
    [
        ("font", (("sans", "Sans"), ("serif", "Serif"), ("mono", "Mono")), 112, 120),
        ("font_size", tuple((n, str(n)) for n in (8, 12, 24)), 104, 120),
        ("line_width", ((1, "1 px"), (2, "2 px"), (8, "8 px")), 120, 144),
        ("dash", (("solid", "实线"), ("dashed", "虚线")), 120, 144),
        ("route", (("straight", "直线"), ("elbow", "折线")), 120, 144),
        ("head", (("none", "无"), ("arrow", "箭头")), 120, 144),
        ("align", (("left", "左"), ("center", "中"), ("right", "右")), 120, 144),
        ("list", (("none", "无"), ("bullet", "项目符号"), ("number", "编号")), 136, 168),
        ("tool", (("pen", "钢笔"), ("highlighter", "荧光笔")), 136, 168),
        ("corner", ((0, "0"), (8, "8"), (24, "24")), 120, 144),
    ],
)
def test_picker_presentation_roles_own_width_and_payload(qtbot, presentation, choices, min_w, max_w):
    picker = FormatChoiceFlyout()
    qtbot.addWidget(picker)
    received = []
    picker.choice_selected.connect(received.append)
    picker.present_labels(choices, current=choices[0][0], presentation=presentation)
    picker.adjustSize()
    picker.show()
    QApplication.processEvents()
    assert picker.presentation_role() == presentation
    assert min_w <= picker.width() <= max_w
    buttons = [
        child
        for child in picker.findChildren(QToolButton)
        if child.property("choiceValue") is not None
    ]
    assert buttons
    assert buttons[0].property("presentationRole") == presentation
    QTest.mouseClick(buttons[-1], Qt.LeftButton)
    QApplication.processEvents()
    assert received == [choices[-1][0]]


def test_long_choice_label_does_not_cover_checked_mark(qtbot):
    picker = FormatChoiceFlyout()
    qtbot.addWidget(picker)
    picker.present_labels(
        (("left", "左对齐并且这是一段很长的中文和 English mixed label"),),
        current="left",
        presentation="align",
    )
    picker.adjustSize()
    picker.show()
    QApplication.processEvents()
    button = next(
        child
        for child in picker.findChildren(QToolButton)
        if child.property("choiceValue") == "left"
    )
    image = QImage(button.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    button.render(painter)
    painter.end()
    found_check = False
    for x in range(image.width() - 18, image.width()):
        for y in range(image.height()):
            pixel = image.pixelColor(x, y)
            if pixel.blue() > 180 and pixel.red() < 120:
                found_check = True
    assert found_check


def test_sticky_toolbar_hides_shape_and_text_hides_link(qtbot, qapp):
    load_stylesheet(qapp)
    sticky = SelectionToolbar()
    qtbot.addWidget(sticky)
    sticky.set_kind("sticky")
    sticky.show()
    QApplication.processEvents()
    assert sticky.button("shape") is None
    assert sticky.button("palette") is not None
    text = SelectionToolbar()
    qtbot.addWidget(text)
    text.set_kind("text")
    assert text.button("link") is None
    mixed = SelectionToolbar()
    qtbot.addWidget(mixed)
    mixed.set_kind("mixed")
    assert mixed.button("duplicate") is None
    assert mixed.button("lock") is not None


def test_format_picker_visible_gap_is_at_least_six_px(qtbot, qapp):
    harness = _prepare_text_selection(qtbot, qapp, (1280, 800))
    page = harness.page
    _open_format_key(page, "font_role")
    toolbar = page.selection_toolbar()
    picker = page.format_picker()
    host = page.canvas_host()
    trigger = toolbar.button("font_role")
    origin = trigger.mapTo(host, QPoint(0, 0))
    below = picker.y() - (origin.y() + trigger.height())
    above = origin.y() - (picker.y() + picker.height())
    assert below >= 6 or above >= 6
    assert not picker.geometry().intersects(toolbar.geometry())
