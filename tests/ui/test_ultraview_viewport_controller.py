"""Wave 2 Task 2.3: ViewportController owns BoardViewport and camera apply."""
from __future__ import annotations

import ast
from pathlib import Path

from mf4_analyzer.ui.chart_stack.ultraview.viewport_controller import ViewportController


ULTRAVIEW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
)
PAGE_PATH = ULTRAVIEW_ROOT / "page.py"
CONTROLLER_PATH = ULTRAVIEW_ROOT / "viewport_controller.py"
VIEWPORT_PATH = ULTRAVIEW_ROOT / "viewport.py"


def _board_viewport_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "BoardViewport":
            lines.append(node.lineno)
        elif isinstance(func, ast.Attribute) and func.attr == "BoardViewport":
            lines.append(node.lineno)
    return lines


def test_board_viewport_is_constructed_in_the_controller_not_page():
    page_hits = _board_viewport_calls(PAGE_PATH)
    controller_hits = _board_viewport_calls(CONTROLLER_PATH)
    definition_hits = _board_viewport_calls(VIEWPORT_PATH)
    assert page_hits == []
    assert len(controller_hits) == 1
    assert definition_hits == []


def test_page_forwards_zoom_fit_and_handle_zoom_wheel():
    source = PAGE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PAGE_PATH))
    bodies: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "zoom_fit",
            "handle_zoom_wheel",
        }:
            bodies[node.name] = node
    assert set(bodies) == {"zoom_fit", "handle_zoom_wheel"}
    assert "self._viewport_ctrl.zoom_fit()" in source
    assert "self._viewport_ctrl.handle_zoom_wheel" in source
    for name, function in bodies.items():
        calls = [
            item
            for item in ast.walk(function)
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr in {name, "handle_zoom_wheel", "zoom_fit"}
        ]
        assert calls, f"UltraViewPage.{name} must forward to ViewportController"


def test_page_composes_one_viewport_controller():
    source = PAGE_PATH.read_text(encoding="utf-8")
    assert "ViewportController(" in source
    assert source.count("ViewportController(") == 1
    public = {
        name
        for name, value in vars(ViewportController).items()
        if callable(value) and not name.startswith("_")
    }
    assert {
        "hide",
        "reset",
        "cancel",
        "zoom_fit",
        "handle_zoom_wheel",
        "fit_on_open",
        "begin_board_pan",
    } <= public
