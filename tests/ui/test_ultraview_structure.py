"""Shrink-only AST guardrails for UltraView's page/state seams.

The frozen sets below are the Task 0 inventory at ``f85f2323``.  They may
only shrink.  A behavior change that needs a wider set must update the seam
hardening spec first; do not weaken these checks to accommodate implementation.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from mf4_analyzer.ui.ultraview_state import ULTRAVIEW_PAGE_OBJECT_NAME


UI_ROOT = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui"
ULTRAVIEW_ROOT = UI_ROOT / "chart_stack" / "ultraview"
STATE_PATH = UI_ROOT / "ultraview_state.py"
COORDINATOR_PATH = UI_ROOT / "main_window" / "ultraview_coordinator.py"
VIEW_LAYER_PATHS = tuple(sorted(ULTRAVIEW_ROOT.glob("*.py")))

# Measured in Task 0.  ``empty_slots`` is deliberately excluded: despite its
# ``list[str]`` return annotation, it is a pure query and never mutates Board.
FROZEN_STATE_MUTATORS = frozenset(
    {
        "add_ref",
        "apply_free_grid_preset",
        "create_board",
        "delete_board",
        "duplicate_board",
        "free_grid_to_template",
        "mark_workspace_mutated",
        "move_to_unplaced",
        "nudge_ratio",
        "organize_free_grid",
        "place_free_grid_from_unplaced",
        "place_from_unplaced",
        "rebind_ref",
        "remove_ref",
        "rename_board",
        "reorder_board",
        "replace_free_grid_ref",
        "replace_slot",
        "set_active_board",
        "set_free_grid_rect",
        "set_free_grid_rects",
        "set_layout",
        "set_presentation_flags",
        "set_ratio",
        "set_workspace_preview_sidecar",
        "swap_slots",
        "template_to_free_grid",
    }
)

FROZEN_MODEL_FIELD_WRITES = frozenset()

FROZEN_PAGE_OF_SURFACE = frozenset(
    {
        "clear_card_selection",
        "handle_card_double_click",
        "notify_canvas_click",
        "unplaced_tray",
    }
)

FROZEN_MUTATION_FUNNEL_EXCEPTIONS = frozenset(
    {
        "_after_board_mutation",  # the funnel itself marks then refreshes
        "_on_organize_free_grid",  # _record_grid_transition closes indirectly
        "save_preview_sidecar",  # persistence metadata is intentionally not a projection
    }
)

FROZEN_PAGE_PRIVATE_SURFACE = frozenset()

FROZEN_FLOATING_GEOMETRY_LITERALS = Counter(
    {
        # Pre-C3 leaks that D2's setMinimum* scan newly sees. Do not add more.
        ("chrome_islands.py", "setMinimumWidth", (48,)): 1,  # BoardIsland name field
        ("template_board.py", "setMinimumSize", (240,)): 1,  # BoardGrid
        ("free_grid_board.py", "setMinimumSize", (240,)): 1,  # FreeGridBoard
    }
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _callee_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _state_mutators() -> frozenset[str]:
    """Derive the production mutator surface, then compare it to the freeze."""
    names: set[str] = set()
    explicit = {
        "create_board",
        "delete_board",
        "duplicate_board",
        "mark_workspace_mutated",
        "rename_board",
        "reorder_board",
        "set_active_board",
        "set_workspace_preview_sidecar",
    }
    for node in _parse(STATE_PATH).body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name in explicit:
            names.add(node.name)
            continue
        args = {item.arg for item in node.args.args}
        returns = ast.unparse(node.returns) if node.returns is not None else ""
        if {"board", "workspace"} & args and returns == "list[str]" and node.name != "empty_slots":
            names.add(node.name)
    return frozenset(names)


def _view_layer_mutator_calls() -> set[tuple[str, str]]:
    mutators = _state_mutators()
    result: set[tuple[str, str]] = set()
    for path in VIEW_LAYER_PATHS:
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Call) and _callee_name(node) in mutators:
                result.add((path.name, _callee_name(node)))
    return result


def _assignment_targets(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            yield from node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            yield node.target


def _model_field_names() -> frozenset[str]:
    names: set[str] = set()
    for cls_name in ("UltraViewBoardState", "UltraViewWorkspaceState"):
        for node in _parse(STATE_PATH).body:
            if not isinstance(node, ast.ClassDef) or node.name != cls_name:
                continue
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    names.add(item.target.id)
    return frozenset(names)


def _model_field_writes() -> frozenset[tuple[str, str]]:
    fields = _model_field_names()
    result: set[tuple[str, str]] = set()
    paths = (*VIEW_LAYER_PATHS, COORDINATOR_PATH)
    for path in paths:
        for target in _assignment_targets(_parse(path)):
            if isinstance(target, ast.Attribute) and target.attr in fields:
                result.add((path.name, f"{ast.unparse(target.value)}.{target.attr}"))
    return frozenset(result)


_PAGE_OF_SCAN_FILES = (
    "widgets.py",
    "widgets_common.py",
    "library_widgets.py",
    "card_widgets.py",
    "template_board.py",
    "free_grid_board.py",
)


def _page_of_surface() -> frozenset[str]:
    surface: set[str] = set()
    for filename in _PAGE_OF_SCAN_FILES:
        path = ULTRAVIEW_ROOT / filename
        if not path.is_file():
            continue
        tree = _parse(path)
        _collect_page_of_surface(tree, surface)
    return frozenset(surface)


def _collect_page_of_surface(tree: ast.AST, surface: set[str]) -> None:
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        page_names: set[str] = set()
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and _callee_name(node.value) == "_page_of"
            ):
                page_names.add(node.targets[0].id)
        for node in ast.walk(function):
            if not isinstance(node, ast.Attribute):
                continue
            if isinstance(node.value, ast.Name) and node.value.id in page_names:
                surface.add(node.attr)
            elif isinstance(node.value, ast.Call) and _callee_name(node.value) == "_page_of":
                surface.add(node.attr)


def _coordinator_methods() -> tuple[ast.FunctionDef, ...]:
    tree = _parse(COORDINATOR_PATH)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "UltraViewCoordinator":
            return tuple(item for item in node.body if isinstance(item, ast.FunctionDef))
    raise AssertionError("UltraViewCoordinator not found")


def _mutation_funnel_exceptions() -> frozenset[str]:
    mutators = _state_mutators()
    expected_funnels = {"_after_board_mutation", "_commit_grid_change", "_apply_grid_snapshot"}
    exceptions: set[str] = set()
    for function in _coordinator_methods():
        calls = {
            _callee_name(node)
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
        }
        if calls & mutators and not calls & expected_funnels:
            exceptions.add(function.name)
    return frozenset(exceptions)


def _page_private_surface() -> frozenset[str]:
    surface: set[str] = set()
    for node in ast.walk(_parse(COORDINATOR_PATH)):
        if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
            continue
        value = node.value
        if isinstance(value, ast.Name) and value.id == "page":
            surface.add(node.attr)
        elif isinstance(value, ast.Attribute) and value.attr in {"page", "_page"}:
            surface.add(node.attr)
        elif isinstance(value, ast.Call) and _callee_name(value) in {"page", "_page"}:
            surface.add(node.attr)
    return frozenset(surface)


def _floating_geometry_literals() -> Counter[tuple[str, str, tuple[int, ...]]]:
    values = {40, 48, 56, 116, 196, 200, 232, 233, 240, 268}
    result: Counter[tuple[str, str, tuple[int, ...]]] = Counter()
    for path in VIEW_LAYER_PATHS:
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.Call):
                continue
            callee = _callee_name(node)
            if not (
                callee.startswith("setFixed")
                or callee.startswith("setMinimum")
                or callee in {"QSize", "_hint", "resize", "QRect"}
            ):
                continue
            found = tuple(sorted(
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant)
                and type(child.value) is int
                and child.value in values
            ))
            if found:
                result[(path.name, callee, found)] += 1
    return result


def test_view_layer_calls_no_state_mutators():
    assert _state_mutators() == FROZEN_STATE_MUTATORS
    assert _view_layer_mutator_calls() == set()


def test_model_fields_written_only_in_state_module():
    assert _model_field_writes() == FROZEN_MODEL_FIELD_WRITES


def test_page_has_no_back_reference():
    forbidden = {"coordinator", "_ultraview", "MainWindow", "main_window"}
    found: set[tuple[str, str]] = set()
    for path in VIEW_LAYER_PATHS:
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Name) and node.id in forbidden:
                found.add((path.name, node.id))
            elif isinstance(node, ast.Attribute) and node.attr in forbidden:
                found.add((path.name, node.attr))
    assert found == set()


def test_page_of_surface_is_frozen():
    assert _page_of_surface() == FROZEN_PAGE_OF_SURFACE


def test_mutations_end_in_funnel():
    assert _mutation_funnel_exceptions() == FROZEN_MUTATION_FUNNEL_EXCEPTIONS


def test_page_object_name_is_shared_constant():
    literal_sites: list[tuple[str, int]] = []
    for path in (*ULTRAVIEW_ROOT.rglob("*.py"), STATE_PATH):
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Constant) and node.value == "ultraViewPage":
                literal_sites.append((path.name, node.lineno))
    assert [path for path, _line in literal_sites] == ["ultraview_state.py"]
    assert ULTRAVIEW_PAGE_OBJECT_NAME == "ultraViewPage"
    assert "setObjectName(ULTRAVIEW_PAGE_OBJECT_NAME)" in (ULTRAVIEW_ROOT / "page.py").read_text()
    assert "ULTRAVIEW_PAGE_OBJECT_NAME" in (ULTRAVIEW_ROOT / "widgets.py").read_text()


def test_coordinator_uses_page_public_api_only():
    assert _page_private_surface() == FROZEN_PAGE_PRIVATE_SURFACE


def test_zoom_broadcast_single_site():
    controller = _parse(ULTRAVIEW_ROOT / "viewport_controller.py")
    calls = Counter(
        node.func.value.attr
        for node in ast.walk(controller)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_zoom"
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
        and node.func.value.attr in {"_grid", "_free_grid"}
    )
    assert calls == Counter({"_grid": 1, "_free_grid": 1})
    page_source = (ULTRAVIEW_ROOT / "page.py").read_text(encoding="utf-8")
    assert "self._grid.set_zoom" not in page_source
    assert "self._free_grid.set_zoom" not in page_source


def test_floating_geometry_literals_live_only_in_floating_layout():
    assert _floating_geometry_literals() == FROZEN_FLOATING_GEOMETRY_LITERALS


def test_zoom_at_does_not_refresh_workspace_extent():
    controller = _parse(ULTRAVIEW_ROOT / "viewport_controller.py")
    for node in ast.walk(controller):
        if isinstance(node, ast.FunctionDef) and node.name == "_zoom_at":
            calls = {
                _callee_name(item)
                for item in ast.walk(node)
                if isinstance(item, ast.Call)
            }
            assert "_refresh_workspace_extent" not in calls
            assert "refresh_extent" not in calls
            return
    raise AssertionError("_zoom_at not found")
