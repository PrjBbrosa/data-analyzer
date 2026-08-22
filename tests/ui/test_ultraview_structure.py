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
WORKSPACE_CONTROLLER_PATH = UI_ROOT / "main_window" / "ultraview_workspace_controller.py"
CAPTURE_COORDINATOR_PATH = UI_ROOT / "main_window" / "ultraview_capture_coordinator.py"
WINDOW_PATH = UI_ROOT / "main_window" / "window.py"
CAPTURE_PRIVATE_ATTRS = frozenset(
    {
        "_store",
        "_runtime",
        "_bindings",
        "_queued",
        "_idle_timer",
        "_focus_timer",
        "_sidecar_timer",
        "_sidecar_pending",
        "_hooked_ids",
        "_destroy_watched",
        "_presentation_revision",
        "_unstable",
        "_result_refs",
        "_result_generation",
        "_digest_retries",
        "_hooks",
        "_idle_pending",
        "_sidecar_generation",
    }
)
WORKSPACE_CONTROLLER_PRIVATE_ATTRS = frozenset(
    {
        "_grid_histories",
        "_pending_auto_aspect",
        "_layout_revision",
        "_workspace_controller",
    }
)
WORKSPACE_FORBIDDEN_IMPORTS = frozenset(
    {
        "UltraViewCaptureCoordinator",
        "PreviewStore",
        "QImage",
        "PresentationCaptureFacts",
        "collect_widget_capture_facts",
        "PresentationRuntimeLedger",
    }
)
CAPTURE_FORBIDDEN_IMPORTS = frozenset(
    {
        "UltraViewWorkspaceController",
        "add_ref",
        "set_free_grid_rects",
        "apply_author_nudge",
    }
)
MUTATION_OWNER_PATHS = (
    COORDINATOR_PATH,
    WORKSPACE_CONTROLLER_PATH,
    CAPTURE_COORDINATOR_PATH,
)
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
    paths = (*VIEW_LAYER_PATHS, *MUTATION_OWNER_PATHS)
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


def _class_methods(path: Path, class_name: str) -> tuple[ast.FunctionDef, ...]:
    tree = _parse(path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return tuple(item for item in node.body if isinstance(item, ast.FunctionDef))
    raise AssertionError(f"{class_name} not found in {path.name}")


def _coordinator_methods() -> tuple[ast.FunctionDef, ...]:
    return _class_methods(COORDINATOR_PATH, "UltraViewCoordinator")


def _workspace_controller_methods() -> tuple[ast.FunctionDef, ...]:
    return _class_methods(WORKSPACE_CONTROLLER_PATH, "UltraViewWorkspaceController")


def _capture_coordinator_methods() -> tuple[ast.FunctionDef, ...]:
    return _class_methods(CAPTURE_COORDINATOR_PATH, "UltraViewCaptureCoordinator")


def _mutation_funnel_exceptions() -> frozenset[str]:
    mutators = _state_mutators()
    expected_funnels = {"_after_board_mutation", "_commit_grid_change", "_apply_grid_snapshot"}
    exceptions: set[str] = set()
    for function in (
        *_coordinator_methods(),
        *_workspace_controller_methods(),
        *_capture_coordinator_methods(),
    ):
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
    for path in MUTATION_OWNER_PATHS:
        for node in ast.walk(_parse(path)):
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


def _free_grid_board_class() -> ast.ClassDef:
    tree = _parse(ULTRAVIEW_ROOT / "free_grid_board.py")
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FreeGridBoard":
            return node
    raise AssertionError("FreeGridBoard not found")


def _init_constructor_counts(class_node: ast.ClassDef) -> Counter:
    init = next(
        item
        for item in class_node.body
        if isinstance(item, ast.FunctionDef) and item.name == "__init__"
    )
    counts: Counter[str] = Counter()
    for node in ast.walk(init):
        if isinstance(node, ast.Call):
            counts[_callee_name(node)] += 1
    return counts


def test_free_grid_board_constructs_exactly_one_owner_of_each_controller():
    class_node = _free_grid_board_class()
    counts = _init_constructor_counts(class_node)
    assert counts["BoardInteractionController"] == 1
    assert counts["FreeGridFeedbackController"] == 1
    assert counts["FreeGridAuthorController"] == 1
    assert counts["ViewportFeedbackSurface"] == 1
    assert counts["QTimer"] == 0
    assert counts["GhostOverlay"] == 0
    assert [ast.unparse(base) for base in class_node.bases] == ["QWidget"]
    assert any(
        isinstance(item, ast.FunctionDef) and item.name == "mousePressEvent"
        for item in class_node.body
    )
    mixin_bases = [
        ast.unparse(base)
        for base in class_node.bases
        if "Mixin" in ast.unparse(base)
    ]
    assert mixin_bases == []


def test_free_grid_board_does_not_construct_timers_or_app_filters():
    path = ULTRAVIEW_ROOT / "free_grid_board.py"
    tree = _parse(path)
    source = path.read_text(encoding="utf-8")
    timer_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == "QTimer"
    ]
    filter_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == "installEventFilter"
    ]
    assert timer_calls == []
    assert filter_calls == []
    assert "QTimer" not in source
    assert "edge_pan" not in source
    assert "installEventFilter" not in source
    page_source = (ULTRAVIEW_ROOT / "page.py").read_text(encoding="utf-8")
    assert "_author_geometry_session" not in page_source
    assert "_body_layout" not in page_source
    workspace_source = WORKSPACE_CONTROLLER_PATH.read_text(encoding="utf-8")
    assert "_author_geometry_session" not in workspace_source
    assert "_body_layout" not in workspace_source
    imported = {
        alias.name
        for node in _parse(WORKSPACE_CONTROLLER_PATH).body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "QImage" not in imported
    assert "PreviewStore" not in imported
    capture_imported = {
        alias.name
        for node in _parse(CAPTURE_COORDINATOR_PATH).body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "UltraViewWorkspaceController" not in capture_imported
    assert "add_ref" not in capture_imported
    assert "set_free_grid_rects" not in capture_imported
    assert "apply_author_nudge" not in capture_imported


def test_coordinator_constructs_exactly_one_workspace_controller():
    init = next(
        item
        for item in _coordinator_methods()
        if item.name == "__init__"
    )
    counts = Counter(
        _callee_name(node)
        for node in ast.walk(init)
        if isinstance(node, ast.Call)
    )
    assert counts["UltraViewWorkspaceController"] == 1
    assert counts["UltraViewCaptureCoordinator"] == 1
    assert counts["default_workspace"] == 1
    assert counts.get("PreviewStore", 0) == 0
    assert counts.get("QTimer", 0) == 0
    assert counts.get("PresentationRuntimeLedger", 0) == 0


def test_workspace_mixed_nudge_uses_one_selection_plan():
    nudge = next(
        item
        for item in _workspace_controller_methods()
        if item.name == "_on_selection_nudge"
    )
    commit = next(
        item
        for item in _workspace_controller_methods()
        if item.name == "_commit_selection_mutation"
    )
    nudge_calls = {
        _callee_name(node) for node in ast.walk(nudge) if isinstance(node, ast.Call)
    }
    commit_calls = {
        _callee_name(node) for node in ast.walk(commit) if isinstance(node, ast.Call)
    }
    assert "plan_selection_nudge" in nudge_calls
    assert "_commit_selection_mutation" in nudge_calls
    assert "set_free_grid_rects" not in nudge_calls
    assert "apply_author_nudge" not in nudge_calls
    assert "as_entry" in commit_calls
    assert "apply_board_edit_entry" in commit_calls
    assert "_record_board_edit" in commit_calls
    assert "set_free_grid_rects" not in commit_calls
    assert "apply_author_nudge" not in commit_calls
    coordinator_source = COORDINATOR_PATH.read_text(encoding="utf-8")
    workspace_source = WORKSPACE_CONTROLLER_PATH.read_text(encoding="utf-8")
    assert "SelectionMutationService" not in coordinator_source
    assert "SelectionMutationService" not in workspace_source


def test_coordinator_workspace_identity_is_the_controller_object(qapp):
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.main_window.ultraview_coordinator import UltraViewCoordinator
    from mf4_analyzer.ui.main_window.ultraview_workspace_controller import (
        UltraViewWorkspaceController,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controllers = [
        value
        for value in vars(coordinator).values()
        if isinstance(value, UltraViewWorkspaceController)
    ]
    assert len(controllers) == 1
    controller = coordinator._workspace_controller
    assert controller is controllers[0]
    assert coordinator.workspace is controller.workspace
    assert coordinator.board is controller.board
    assert coordinator._workspace is controller.workspace
    coordinator._on_create_board()
    assert coordinator.workspace is controller.workspace
    assert len(coordinator.workspace.boards) == len(controller.workspace.boards)
    assert coordinator.workspace.boards is controller.workspace.boards


def test_coordinator_constructs_exactly_one_capture_owner(qapp):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.chart_stack.ultraview.preview_store import PreviewStore
    from mf4_analyzer.ui.main_window.ultraview_capture_coordinator import (
        UltraViewCaptureCoordinator,
    )
    from mf4_analyzer.ui.main_window.ultraview_coordinator import UltraViewCoordinator
    from mf4_analyzer.ui.main_window.ultraview_runtime import PresentationRuntimeLedger

    capture_init = next(
        item for item in _capture_coordinator_methods() if item.name == "__init__"
    )
    capture_counts = Counter(
        _callee_name(node)
        for node in ast.walk(capture_init)
        if isinstance(node, ast.Call)
    )
    assert capture_counts["PreviewStore"] == 1
    assert capture_counts["QTimer"] == 3
    assert capture_counts["PresentationRuntimeLedger"] == 1

    funnel_names = {"_after_board_mutation", "_commit_grid_change", "_apply_grid_snapshot"}
    mutators = _state_mutators()
    for function in _capture_coordinator_methods():
        calls = {
            _callee_name(node)
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
        }
        assert not (calls & funnel_names)
        if function.name != "save_preview_sidecar":
            assert not (calls & mutators)

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    captures = [
        value
        for value in vars(coordinator).values()
        if isinstance(value, UltraViewCaptureCoordinator)
    ]
    stores = [
        value
        for value in vars(captures[0]).values()
        if isinstance(value, PreviewStore)
    ]
    ledgers = [
        value
        for value in vars(captures[0]).values()
        if isinstance(value, PresentationRuntimeLedger)
    ]
    named_timers = {
        name: value
        for name, value in vars(captures[0]).items()
        if isinstance(value, QTimer)
    }
    assert len(captures) == 1
    assert coordinator._capture is captures[0]
    assert len(stores) == 1
    assert coordinator.store is stores[0]
    assert coordinator._store is stores[0]
    assert len(ledgers) == 1
    assert coordinator._runtime is ledgers[0]
    assert named_timers.keys() >= {"_idle_timer", "_focus_timer", "_sidecar_timer"}
    assert coordinator._idle_timer is named_timers["_idle_timer"]
    assert coordinator._focus_timer is named_timers["_focus_timer"]
    assert coordinator._sidecar_timer is named_timers["_sidecar_timer"]
    assert not any(isinstance(value, QTimer) for value in vars(coordinator).values())
    assert not any(isinstance(value, PreviewStore) for value in vars(coordinator).values())
    coordinator.clear()
    coordinator.deleteLater()
    host.deleteLater()


def _imported_names(path: Path) -> frozenset[str]:
    names: set[str] = set()
    for node in _parse(path).body:
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[-1] for alias in node.names)
    return frozenset(names)


def _attribute_names(path: Path) -> frozenset[str]:
    return frozenset(
        node.attr
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Attribute)
    )


def _getattr_constant_names(path: Path) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.Call) or _callee_name(node) != "getattr":
            continue
        if len(node.args) < 2:
            continue
        attr = node.args[1]
        if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
            names.add(attr.value)
    return frozenset(names)


def _coordinator_method(name: str) -> ast.FunctionDef:
    for item in _coordinator_methods():
        if item.name == name:
            return item
    raise AssertionError(f"{name} not found on UltraViewCoordinator")


def _effective_body(function: ast.FunctionDef) -> list[ast.stmt]:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _is_self_owner_call(call: ast.AST, owner_attr: str, method_name: str) -> bool:
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != method_name:
        return False
    owner = func.value
    if not isinstance(owner, ast.Attribute) or owner.attr != owner_attr:
        return False
    return isinstance(owner.value, ast.Name) and owner.value.id == "self"


def _is_thin_owner_forward(function: ast.FunctionDef, owner_attr: str) -> bool:
    body = _effective_body(function)
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Return):
        call = stmt.value
    elif isinstance(stmt, ast.Expr):
        call = stmt.value
    else:
        return False
    return _is_self_owner_call(call, owner_attr, function.name)


def _direct_callee_names(function: ast.FunctionDef) -> list[str]:
    names: list[str] = []
    for stmt in function.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                names.append(_callee_name(node))
    return names


def test_workspace_and_capture_do_not_read_each_others_private_fields():
    workspace_imported = _imported_names(WORKSPACE_CONTROLLER_PATH)
    capture_imported = _imported_names(CAPTURE_COORDINATOR_PATH)
    assert not (workspace_imported & WORKSPACE_FORBIDDEN_IMPORTS)
    assert not (capture_imported & CAPTURE_FORBIDDEN_IMPORTS)
    frozen_mutators = _state_mutators()
    assert capture_imported & frozen_mutators == {"set_workspace_preview_sidecar"}

    workspace_attrs = _attribute_names(WORKSPACE_CONTROLLER_PATH)
    capture_attrs = _attribute_names(CAPTURE_COORDINATOR_PATH)
    assert not (workspace_attrs & CAPTURE_PRIVATE_ATTRS)
    assert not (capture_attrs & WORKSPACE_CONTROLLER_PRIVATE_ATTRS)
    assert not (_getattr_constant_names(WORKSPACE_CONTROLLER_PATH) & CAPTURE_PRIVATE_ATTRS)
    assert not (
        _getattr_constant_names(CAPTURE_COORDINATOR_PATH)
        & WORKSPACE_CONTROLLER_PRIVATE_ATTRS
    )


def test_coordinator_facade_is_stable_has_no_host_walk_body():
    stable = _coordinator_method("_is_stable")
    commit = _coordinator_method("_commit_grid_change")
    grab = _coordinator_method("_grab_image")
    assert _is_thin_owner_forward(stable, "_capture")
    assert _is_thin_owner_forward(commit, "_workspace_controller")
    assert _is_thin_owner_forward(grab, "_capture")
    walked = {
        node.attr
        for node in ast.walk(stable)
        if isinstance(node, ast.Attribute)
    }
    assert walked.isdisjoint(
        {
            "_cursor",
            "_dense_raster",
            "_interaction_state",
            "_aa_idle_timer",
            "_refresh_pending",
        }
    )
    callees = {
        _callee_name(node)
        for node in ast.walk(stable)
        if isinstance(node, ast.Call)
    }
    assert callees == {"_is_stable"}
    assert "collect_widget_capture_facts" not in callees


def test_coordinator_has_exactly_one_preview_store_and_no_second_capture_timer():
    init = _coordinator_method("__init__")
    counts = Counter(
        _callee_name(node)
        for node in ast.walk(init)
        if isinstance(node, ast.Call)
    )
    assert counts["UltraViewWorkspaceController"] == 1
    assert counts["UltraViewCaptureCoordinator"] == 1
    assert counts.get("PreviewStore", 0) == 0
    assert counts.get("QTimer", 0) == 0
    assert counts.get("PresentationRuntimeLedger", 0) == 0
    window_source = WINDOW_PATH.read_text(encoding="utf-8")
    assert "self._ultraview = UltraViewCoordinator(" in window_source
    assert "_ultraview_workspace" not in window_source
    assert "_ultraview_capture" not in window_source


def test_shutdown_reset_restore_stop_capture_then_workspace_then_page():
    for name, capture_call in (
        ("shutdown", "shutdown_capture"),
        ("reset_project_state", "reset_capture_state"),
        ("restore_project_state", "reset_capture_state"),
    ):
        calls = _direct_callee_names(_coordinator_method(name))
        assert capture_call in calls, (name, calls)
        assert "_clear_placement_runtime" in calls, (name, calls)
        assert "_reset_page_runtime" in calls, (name, calls)
        assert calls.index(capture_call) < calls.index("_clear_placement_runtime")
        assert calls.index("_clear_placement_runtime") < calls.index("_reset_page_runtime")
