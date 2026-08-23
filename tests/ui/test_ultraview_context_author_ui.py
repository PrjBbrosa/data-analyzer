"""Wave 2 Task 2.4: board context + author UI controllers stay a UI bridge."""
from __future__ import annotations

import ast
from pathlib import Path

from mf4_analyzer.ui.chart_stack.ultraview.author_tools import BoardInteractionController
from mf4_analyzer.ui.chart_stack.ultraview.board_context_controller import (
    BOARD_MENU_FIT,
    BOARD_MENU_OBJECT_NAME,
    BoardContextController,
)
from mf4_analyzer.ui.chart_stack.ultraview.page import (
    BOARD_MENU_FIT as PAGE_BOARD_MENU_FIT,
    BOARD_MENU_OBJECT_NAME as PAGE_BOARD_MENU_OBJECT_NAME,
    UltraViewPage,
)


ULTRAVIEW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
)


def test_page_still_exposes_board_menu_and_tool_rail():
    assert callable(UltraViewPage.make_board_context_menu)
    assert callable(UltraViewPage.tool_rail)
    assert PAGE_BOARD_MENU_OBJECT_NAME == "ultraViewBoardContextMenu"
    assert PAGE_BOARD_MENU_FIT == "适应内容"


def test_board_interaction_controller_is_defined_only_in_author_tools():
    found: list[str] = []
    for path in sorted(ULTRAVIEW_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "BoardInteractionController":
                found.append(path.name)
    assert found == ["author_tools.py"]
    assert BoardInteractionController.__module__.endswith("author_tools")


def test_board_context_controller_builds_named_fit_menu(qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    assert isinstance(page._board_context, BoardContextController)
    menu = page._board_context.make_board_context_menu()
    qtbot.addWidget(menu)
    assert menu.objectName() == BOARD_MENU_OBJECT_NAME
    assert any(action.text() == BOARD_MENU_FIT for action in menu.actions())
    forwarded = page.make_board_context_menu()
    qtbot.addWidget(forwarded)
    assert forwarded.objectName() == BOARD_MENU_OBJECT_NAME
    assert any(action.text() == BOARD_MENU_FIT for action in forwarded.actions())


def test_author_ui_controller_uses_page_interaction_session(qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    assert page._author_ui._interaction is page.interaction()
    assert page.interaction() is page._free_grid.interaction()
    assert isinstance(page.interaction(), BoardInteractionController)
    rail = page.tool_rail()
    assert rail.receivers(rail.tool_requested) > 0
    assert rail.receivers(rail.tool_pinned_changed) > 0


def _wait_layout(qtbot, page) -> None:
    qtbot.wait(40)
    page._apply_floating_layout()


def _popup_tracks_trigger(page, trigger, popup) -> None:
    host = page.canvas_host()
    size = popup.content_size() if callable(getattr(popup, "content_size", None)) else popup.size()
    expected = page._author_ui.author_flyout_rect(trigger, size)
    popup_rect = popup.geometry()
    assert popup.isVisible()
    assert popup_rect == expected, (popup_rect, expected, trigger.geometry())
    assert host.contentsRect().intersects(popup_rect)
    assert popup.vertical_scroll_enabled() is (
        popup.content_size().height() > popup_rect.height()
    )


def test_open_author_flyouts_reanchor_on_resize_and_stay_closed_when_closed(qtbot):
    from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
        POINTER_MODE_LASER,
        POINTER_MODE_MOUSE,
        TOOL_DRAW,
        TOOL_SELECT,
        TOOL_SHAPES,
        TOOL_STICKY,
    )
    from mf4_analyzer.ui.chart_stack.ultraview.author_ui_controller import ActiveTransientFacts

    page = UltraViewPage()
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)
    sizes = ((1280, 800), (800, 560), (1440, 900), (1280, 800))
    openers = (
        (TOOL_SELECT, page._author_ui.show_pointer_popover, page.pointer_popover),
        (TOOL_STICKY, page._author_ui.show_sticky_popover, page.sticky_popover),
        (TOOL_SHAPES, page._author_ui.show_shape_popover, page.shape_popover),
        (TOOL_DRAW, page._author_ui.show_draw_popover, page.draw_popover),
    )
    interaction = page.interaction()
    for tool, opener, popup_getter in openers:
        page.resize(1280, 800)
        _wait_layout(qtbot, page)
        opener()
        _wait_layout(qtbot, page)
        popup = popup_getter()
        assert popup.isVisible(), tool
        before_tool = interaction.active_tool()
        before_mode = interaction.pointer_mode()
        facts = page._author_ui.active_transient_facts()
        assert isinstance(facts, ActiveTransientFacts)
        assert facts.visible is True
        for width, height in sizes:
            page.resize(width, height)
            _wait_layout(qtbot, page)
            trigger = page.tool_rail().tool_button(tool)
            assert trigger is not None, tool
            _popup_tracks_trigger(page, trigger, popup)
            assert interaction.active_tool() == before_tool
            assert interaction.pointer_mode() == before_mode
            assert page._author_ui.active_transient_facts() is not None
        popup.close()
        page.canvas_host().close_active_overlay(restore_focus=False)
        _wait_layout(qtbot, page)
        assert not popup.isVisible()
        assert page._author_ui.active_transient_facts() is None
        page.resize(800, 560)
        _wait_layout(qtbot, page)
        page.resize(1440, 900)
        _wait_layout(qtbot, page)
        assert not popup.isVisible()
        assert page._author_ui.active_transient_facts() is None
    page._author_ui.apply_pointer_mode(POINTER_MODE_LASER)
    page._author_ui.show_pointer_popover()
    _wait_layout(qtbot, page)
    page.resize(800, 560)
    _wait_layout(qtbot, page)
    assert page.interaction().pointer_mode() == POINTER_MODE_LASER
    page._author_ui.apply_pointer_mode(POINTER_MODE_MOUSE)
    page.canvas_host().close_active_overlay(restore_focus=False)
