"""Focused contracts for UltraView's authoring rail and creation popovers."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QFrame, QMenu, QToolButton

from mf4_analyzer.ui.chart_stack.ultraview.author_tools import CLOSED_SHAPE_TYPES

from mf4_analyzer.ui.chart_stack.ultraview.author_style import STICKY_PALETTE_TOKENS

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import (
    SelectionToolbar,
    ToolFlyoutSurface,
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
    RELEASE_AUTHOR_TOOLS,
    ShapePopover,
    StickyPopover,
    ToolRail,
)


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
    rail.resize(52, 468)
    rail.show()
    assert rail.sizeHint().height() <= 520

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
        assert button.y() > previous_bottom
        assert button.geometry().bottom() < rail.height()
        assert button.focusPolicy() == Qt.TabFocus
        previous_bottom = button.geometry().bottom()


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
    assert rail.tool_button(AUTHOR_TOOL_TEXT) is not None
    assert rail.tool_button(AUTHOR_TOOL_SHAPES) is not None
    assert rail.tool_button(AUTHOR_TOOL_CONNECTOR) is None
    assert rail.tool_button(AUTHOR_TOOL_DRAW) is not None


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
