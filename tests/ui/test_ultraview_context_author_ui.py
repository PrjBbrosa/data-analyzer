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
