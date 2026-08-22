"""Wave 2 Task 2.2: FloatingChromeController composition seam."""
from __future__ import annotations

import ast
from pathlib import Path

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import SelectionToolbar
from mf4_analyzer.ui.chart_stack.ultraview.floating_chrome_controller import (
    FloatingChromeController,
)


ULTRAVIEW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
)
PAGE_PATH = ULTRAVIEW_ROOT / "page.py"
CONTROLLER_PATH = ULTRAVIEW_ROOT / "floating_chrome_controller.py"


def test_page_does_not_read_toolbar_body_layout_or_author_geometry_session():
    source = PAGE_PATH.read_text(encoding="utf-8")
    assert "_body_layout" not in source
    assert "_author_geometry_session" not in source
    assert "interaction_facts" in source
    assert "prepare_layout" not in source or "FloatingChromeController" in source


def test_controller_reuses_place_minimap_not_a_parallel_policy():
    source = CONTROLLER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CONTROLLER_PATH))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            imported.add(node.func.id)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        ):
            imported.add(node.func.attr)
    assert "place_minimap" in imported
    assert "minimap_placement_fingerprint" in imported
    assert "MinimapPlacementFacts" in imported
    assert "FloatingChromePolicy" not in source
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert class_names == {"FloatingChromeController"}


def test_selection_toolbar_prepare_layout_is_the_public_seam():
    assert callable(getattr(SelectionToolbar, "prepare_layout", None))
    controller_source = CONTROLLER_PATH.read_text(encoding="utf-8")
    assert "_body_layout" not in controller_source
    tree = ast.parse(controller_source, filename=str(CONTROLLER_PATH))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "prepare_layout"
    ]
    assert calls, "FloatingChromeController must call SelectionToolbar.prepare_layout"


def test_page_composes_floating_chrome_controller():
    source = PAGE_PATH.read_text(encoding="utf-8")
    assert "FloatingChromeController" in source
    assert "self._floating_chrome.apply()" in source
    public = {
        name
        for name, value in vars(FloatingChromeController).items()
        if callable(value) and not name.startswith("_")
    }
    assert {
        "apply",
        "hide",
        "reset",
        "hide_minimap",
        "reassert_stacking",
        "refresh_author_toolbar",
        "sync_minimap_placement",
        "position_minimap",
        "position_empty_board_hint",
        "minimap_geometry_gesture_active",
    } <= public
