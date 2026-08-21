"""Live FreeGrid/Page integration for persisted author-created objects."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QPlainTextEdit, QTextEdit

from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import board_box_to_pixels
from mf4_analyzer.ui.chart_stack.ultraview.elastic_workspace import author_content_bounds
from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    AUTHOR_TOOL_CONNECTOR,
    AUTHOR_TOOL_DRAW,
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_SHAPES,
    AUTHOR_TOOL_STICKY,
    AUTHOR_TOOL_TEXT,
    AUTHOR_TOOLS,
    ToolRail,
)
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    StickyObject,
    TextObject,
    default_board,
)


def _author_board():
    board = default_board()
    board.author_objects = [
        StickyObject(
            "negative-note",
            "sticky",
            box=BoardBox(-6.0, -3.0, 2.0, 2.0),
            text="负坐标便签",
            palette="yellow",
        ),
        TextObject(
            "label",
            "text",
            box=BoardBox(8.0, 5.0, 3.0, 1.5),
            text="右下标签",
        ),
    ]
    return board


def test_set_board_projects_author_objects_into_live_layer_signed_extent_and_fit(qapp, qtbot):
    board = _author_board()
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(1280, 760)
    page.show()
    qapp.processEvents()

    page.set_board(board)
    qapp.processEvents()

    grid = page._free_grid
    layer = grid.author_paint_layer()
    bounds = author_content_bounds(board.author_objects)
    assert layer.parentWidget() is grid
    assert layer.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert layer.model().objects == tuple(board.author_objects)
    assert grid.workspace_extent() is not None
    assert grid.workspace_extent().column <= bounds.column
    assert grid.workspace_extent().row <= bounds.row
    assert layer.model().origin_offset == (
        grid.workspace_extent().column,
        grid.workspace_extent().row,
    )

    expected = board_box_to_pixels(
        (bounds.column, bounds.row, bounds.column_span, bounds.row_span),
        grid._base_metrics,
        origin_offset=layer.model().origin_offset,
    )
    assert expected is not None
    assert grid.content_rect_1x() == expected

    page.zoom_fit()
    qapp.processEvents()
    # Fit must see author-only content rather than parking on the empty-board
    # working frame.  The canvas's current bounds remain the fitted target.
    assert grid.content_rect() is not None
    assert page._viewport.zoom() > 0.0

    # A later zoom reprojects with the live metrics and same signed origin;
    # no stale pixel coordinates may remain on the author layer.
    page.set_board_zoom(1.4)
    qapp.processEvents()
    assert layer.model().metrics is grid.metrics()
    assert layer.model().origin_offset == (
        grid.workspace_extent().column,
        grid.workspace_extent().row,
    )


def test_author_direct_text_editor_is_not_a_canvas_shortcut_target(qapp, qtbot):
    board = _author_board()
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(1100, 700)
    page.show()
    page.set_board(board)
    qapp.processEvents()

    grid = page._free_grid
    editor = grid.author_text_editor()
    text = board.author_objects[1]
    assert isinstance(text, TextObject)
    editor.begin_edit(
        object_id=text.object_id,
        box=text.box,
        text=text.text,
        metrics=grid.metrics(),
        origin_offset=grid.author_paint_layer().model().origin_offset,
        style=text,
    )
    qapp.processEvents()

    assert editor.parentWidget() is grid
    assert isinstance(qapp.focusWidget(), QPlainTextEdit)
    assert page._text_field_has_focus() is True
    editor.cancel()

    # The guard is deliberately future-proof for rich-text shape labels too;
    # a QTextEdit must not let Escape/undo leak to the canvas router.
    rich = QTextEdit(page)
    rich.show()
    rich.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    assert page._text_field_has_focus() is True


def test_release_tool_rail_hides_unfinished_creation_tools(qtbot):
    rail = ToolRail()
    qtbot.addWidget(rail)
    rail.show()
    assert rail.visible_author_tools() == (
        AUTHOR_TOOL_SELECT,
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_DRAW,
    )
    assert rail.creation_section_visible() is True
    assert rail.tool_button(AUTHOR_TOOL_SELECT) is not None
    assert rail.tool_button(AUTHOR_TOOL_STICKY) is not None
    assert rail.tool_button(AUTHOR_TOOL_TEXT) is not None
    assert rail.tool_button(AUTHOR_TOOL_SHAPES) is not None
    assert rail.tool_button(AUTHOR_TOOL_CONNECTOR) is None
    assert rail.tool_button(AUTHOR_TOOL_DRAW) is not None


def test_creation_rail_tracks_editable_free_grid_state(qapp, qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(1100, 700)
    page.show()
    qapp.processEvents()

    rail = page.tool_rail()
    assert rail.visible_author_tools() == (
        AUTHOR_TOOL_SELECT,
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_DRAW,
    )
    assert rail.tool_button(AUTHOR_TOOL_TEXT) is not None

    page.set_board(default_board())
    qapp.processEvents()
    assert rail.creation_section_visible() is True
    assert set(rail.visible_enabled_author_tools()) == {
        AUTHOR_TOOL_SELECT,
        AUTHOR_TOOL_STICKY,
        AUTHOR_TOOL_TEXT,
        AUTHOR_TOOL_SHAPES,
        AUTHOR_TOOL_DRAW,
    }

    page.show_overview()
    assert rail.visible_enabled_author_tools() == ()
    page.hide_overview()
    page.set_presentation_active(True)
    assert rail.visible_enabled_author_tools() == ()
