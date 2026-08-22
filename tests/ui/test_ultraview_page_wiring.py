"""Wave 2 Task 2.5: Page signal wiring is grouped, idempotent, and lambda-free."""
from __future__ import annotations

import ast
from pathlib import Path

from mf4_analyzer.ui.chart_stack.ultraview.author_ui_controller import AuthorUiController
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from tests.ui.test_ultraview_page import _Harness


PAGE_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
    / "page.py"
)

REQUIRED_INIT_CONNECTS = frozenset(
    {
        "_connect_library",
        "_connect_toolbar",
        "_connect_compare_rail",
        "_connect_switcher",
        "_connect_islands",
        "_connect_canvas_host",
        "_connect_grid",
        "_connect_free_grid",
        "_connect_scroll_minimap",
        "_connect_author_ui",
        "_connect_board_context",
        "_connect_viewport_router",
    }
)


def _page_init_connect_names() -> set[str]:
    tree = ast.parse(PAGE_PATH.read_text(encoding="utf-8"), filename=str(PAGE_PATH))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "UltraViewPage":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
                continue
            names: set[str] = set()
            for call in ast.walk(item):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                    continue
                if call.func.attr.startswith("_connect_"):
                    names.add(call.func.attr)
            return names
    raise AssertionError("UltraViewPage.__init__ not found")


def _connect_lambda_count(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "connect" or not node.args:
            continue
        if isinstance(node.args[0], ast.Lambda):
            count += 1
    return count


def test_page_init_calls_named_connect_helpers():
    names = _page_init_connect_names()
    missing = REQUIRED_INIT_CONNECTS - names
    assert not missing, f"__init__ missing {sorted(missing)}"


def test_page_connects_have_no_lambdas():
    assert _connect_lambda_count(PAGE_PATH) == 0


def test_connecting_author_ui_twice_does_not_double_tool_requested(qtbot, monkeypatch):
    calls: list[str] = []
    real = AuthorUiController.on_author_tool_requested

    def spy(self, tool: str) -> None:
        calls.append(tool)
        return real(self, tool)

    monkeypatch.setattr(AuthorUiController, "on_author_tool_requested", spy)
    harness = _Harness(qtbot)
    page = harness.page
    page._author_ui.connect()
    page._author_ui.connect()
    page._connect_author_ui()
    page.tool_rail().tool_requested.emit("select")
    assert calls == ["select"]


def test_toolbar_layout_changed_emits_once_after_second_connect(qtbot):
    harness = _Harness(qtbot)
    harness.layouts.clear()
    harness.page._connect_toolbar()
    harness.page.board_toolbar().layout_changed.emit("split_horizontal")
    assert harness.layouts == ["split_horizontal"]


def test_author_ui_disconnect_is_safe_when_repeated(qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    page._author_ui.disconnect()
    page._author_ui.disconnect()
    page._author_ui.connect()
    rail = page.tool_rail()
    assert rail.receivers(rail.tool_requested) > 0
