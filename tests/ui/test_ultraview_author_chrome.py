"""Focused contracts for UltraView's authoring rail and creation popovers."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from mf4_analyzer.ui.chart_stack.ultraview.author_style import STICKY_PALETTE_TOKENS
from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    AUTHOR_TOOL_DRAW,
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_SHAPES,
    AUTHOR_TOOL_STICKY,
    AUTHOR_TOOL_TEXT,
    DrawPopover,
    ShapePopover,
    StickyPopover,
    TextFormattingToolbar,
    ToolRail,
)


def test_creation_rail_is_independent_from_panel_selection_and_starts_disabled(qtbot):
    rail = ToolRail()
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
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.resize(56, 432)
    rail.show()
    assert rail.sizeHint().height() <= 432

    previous_bottom = -1
    for tool in (
        AUTHOR_TOOL_SELECT,
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
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

    assert shapes.shape_types() == (
        "line", "arrow", "elbow_arrow", "block_arrow", "rectangle", "oval",
        "rhombus", "triangle", "divider",
    )
    chosen_shapes: list[str] = []
    shapes.shape_selected.connect(chosen_shapes.append)
    shapes.choose_shape("rectangle")
    assert chosen_shapes == ["rectangle"]

    assert draw.subtools() == ("pen", "highlighter", "eraser", "lasso")
    assert len(draw.presets("pen")) == 3
    assert len(draw.presets("highlighter")) == 3
    chosen_draw: list[tuple[str, int]] = []

    def record_draw(tool: str, index: int) -> None:
        chosen_draw.append((tool, index))

    draw.tool_selected.connect(record_draw)
    draw.choose_tool("highlighter", 2)
    assert chosen_draw == [("highlighter", 2)]


def test_text_toolbar_keeps_formatting_as_a_small_typed_surface(qtbot):
    toolbar = TextFormattingToolbar()
    qtbot.addWidget(toolbar)
    toolbar.show()

    changes: list[tuple[str, object]] = []

    def record_change(key: str, value: object) -> None:
        changes.append((key, value))

    toolbar.format_requested.connect(record_change)
    bold = toolbar.button("bold")
    assert bold is not None
    QTest.mouseClick(bold, Qt.LeftButton)
    toolbar.set_font_role("mono")
    toolbar.set_font_size(18)
    toolbar.set_alignment("center")

    state = toolbar.formatting()
    assert state["bold"] is True
    assert state["font_role"] == "mono"
    assert state["font_size"] == 18
    assert state["align"] == "center"
    assert changes == [("bold", True), ("font_role", "mono"), ("font_size", 18), ("align", "center")]
