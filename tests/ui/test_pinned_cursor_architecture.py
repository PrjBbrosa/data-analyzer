"""T0–T3 architecture guards for Pin/View structure governance.

These tests lock unique-commit ownership, pinning reverse-imports, the
Router-backed app-filter sentinel, and the committed/presentation state split.
They are not T6/T7 polish/reflow contracts.
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "mf4_analyzer" / "ui"
CHART_STACK_ROOT = UI_ROOT / "chart_stack"
CONTROLLER_PATH = CHART_STACK_ROOT / "pinned_cursor_controller.py"
CONFTEST_PATH = REPO_ROOT / "tests" / "ui" / "conftest.py"
PINNING_ROOT = CHART_STACK_ROOT / "pinning"

# Unique-commit target after T2/T3: collection writes and intent_changed.emit
# stay on PinnedCursorController (or a later explicit commit_user_change on the
# same façade). Collaborators return results; they must not grow a second emit.
UNIQUE_COMMIT_OWNER = "PinnedCursorController"

CONTROLLER_FACT_WRAPPERS = (
    "_reconcile_sample",
    "_binding_key",
    "_key_in",
    "_identity_key",
    "_hidden_channel_row",
    "_sample_has_numeric",
    "_sample_has_hidden",
    "_sample_has_unchecked",
    "_hidden_keys_from_sample",
    "_primary_html",
    "_status_primary_html",
    "_live_primary_html",
    "_coord_html",
    "_format_coord_html",
    "_format_dual_html",
    "_format_value",
    "_format_number",
)

CONTROLLER_SAMPLING_WRAPPERS = (
    "_evaluate",
    "_evaluate_intent",
    "_sample_fn",
    "_wrap_channels",
    "_wrap_frf",
    "_sample_has_result",
    "_axis_compatible",
    "_canvas_generations",
    "_stamp_sample",
    "_sample_matches_generation",
    "_bound_identity_keys",
    "_hidden_identity_keys",
    "_axis_status",
    "_status_for_sample",
    "_log_unavailable",
    "_canvas_compute_pending",
    "_axis_identity",
    "_x_unit",
    "_bindings_from_sample",
    "_domain_for",
)

CONTROLLER_COMMAND_FACADE = (
    "unpin_record",
    "close_record",
    "toggle_record_panel",
    "collapse_record_panel",
    "begin_axis_edit",
    "preview_axis_edit",
    "commit_axis_edit",
    "cancel_axis_edit",
    "nudge_axis_edit",
    "flush_layout",
    "reflow_visible",
)

OWNER_STATE_COMMITTED_FIELDS = frozenset({
    "collection", "samples",
})
OWNER_STATE_PRESENTATION_FIELDS = frozenset({
    "pills", "axis_labels",
})


def _iter_py_files(root: Path):
    if not root.exists():
        return
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_module_names(path: Path) -> list[str]:
    tree = _parse(path)
    rel = path.relative_to(REPO_ROOT)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    else:
        parts = parts[:-1]
    pkg_dotted = ".".join(parts)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0:
                if module:
                    imported.append(module)
                continue
            base_parts = pkg_dotted.split(".") if pkg_dotted else []
            if node.level > len(base_parts):
                if module:
                    imported.append(module)
                continue
            anchor = ".".join(base_parts[: len(base_parts) - node.level + 1])
            if module:
                imported.append(f"{anchor}.{module}" if anchor else module)
            elif anchor:
                imported.append(anchor)
    return imported


def _call_qualname(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
        return ".".join(reversed(parts))
    return None


def _files_with_intent_changed_emit() -> set[str]:
    found: set[str] = set()
    roots = (CHART_STACK_ROOT, UI_ROOT / "pg_canvas")
    for root in roots:
        for path in _iter_py_files(root) or ():
            tree = _parse(path)
            for node in ast.walk(tree):
                name = _call_qualname(node)
                if name is not None and name.endswith("intent_changed.emit"):
                    found.add(path.name)
    return found


def _walk_store_targets(target: ast.AST):
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _walk_store_targets(elt)
        return
    yield target


def _files_with_owner_collection_assignment() -> set[str]:
    found: set[str] = set()
    for path in _iter_py_files(CHART_STACK_ROOT) or ():
        tree = _parse(path)
        for node in ast.walk(tree):
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                targets.extend(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.target is not None:
                targets.append(node.target)
            elif isinstance(node, ast.AugAssign):
                targets.append(node.target)
            for target in targets:
                for item in _walk_store_targets(target):
                    if isinstance(item, ast.Attribute) and item.attr == "collection":
                        found.add(path.name)
    return found


def _class_def(tree: ast.AST, name: str) -> ast.ClassDef:
    for node in tree.body if isinstance(tree, ast.Module) else ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _owner_state_field_names() -> set[str]:
    tree = _parse(CONTROLLER_PATH)
    cls = _class_def(tree, "_OwnerState")
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _method_names(class_name: str) -> set[str]:
    tree = _parse(CONTROLLER_PATH)
    cls = _class_def(tree, class_name)
    return {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_intent_changed_emit_is_owned_by_controller():
    """Unique-commit target: only PinnedCursorController emits intent_changed."""
    emit_files = _files_with_intent_changed_emit()
    assert emit_files == {"pinned_cursor_controller.py"}, (
        f"{UNIQUE_COMMIT_OWNER} must remain the unique intent_changed.emit "
        f"owner; found {sorted(emit_files)}"
    )
    collection_files = _files_with_owner_collection_assignment()
    assert collection_files == {"pinned_cursor_controller.py"}, (
        f"{UNIQUE_COMMIT_OWNER} must remain the unique owner.collection writer; "
        f"found {sorted(collection_files)}"
    )
    methods = _method_names("PinnedCursorController")
    assert "_mark_user_intent" in methods
    assert "intent_changed" not in methods  # signal, not a method


def test_pinning_collaborators_do_not_reverse_import_facade():
    """pinning/ exists after T2; reverse imports of façade/stack/window are forbidden."""
    assert PINNING_ROOT.exists(), "chart_stack.pinning must exist after T2"
    forbidden = (
        "mf4_analyzer.ui.chart_stack.pinned_cursor_controller",
        "PinnedCursorController",
        "mf4_analyzer.ui.chart_stack.stack",
        "mf4_analyzer.ui.main_window",
    )
    violations: list[tuple[str, str]] = []
    for path in _iter_py_files(PINNING_ROOT) or ():
        imported = _imported_module_names(path)
        blob = " ".join(imported)
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            if name == "PinnedCursorController":
                if "PinnedCursorController" in source and path.name != "__init__.py":
                    # Allow a comment mentioning the façade; fail on an import.
                    if any(
                        item.endswith("pinned_cursor_controller")
                        or item.endswith("PinnedCursorController")
                        for item in imported
                    ):
                        violations.append((path.name, name))
                continue
            if any(item == name or item.startswith(name + ".") for item in imported):
                violations.append((path.name, name))
            elif name in blob:
                violations.append((path.name, name))
    assert not violations, violations


def test_conftest_sentinel_uses_controller_filter_install_flag():
    """Façade ``_application_filter_installed`` tracks the real Router install.

    The sentinel must see Router's live install state. Never leave the
    controller flag False while a Router filter is still installed.
    """
    conftest = CONFTEST_PATH.read_text(encoding="utf-8")
    assert "PinnedCursorController" in conftest
    assert "PinKeyRouter" in conftest
    assert "_assert_pinned_cursor_filters_not_accumulated" in conftest
    assert "_application_filter_installed" in conftest
    assert "type(obj) is not PinnedCursorController" in conftest
    controller_src = CONTROLLER_PATH.read_text(encoding="utf-8")
    router_path = PINNING_ROOT / "key_router.py"
    router_src = router_path.read_text(encoding="utf-8")
    assert "def _application_filter_installed" in controller_src
    assert "application_filter_installed" in controller_src
    assert "self._router.install_application_filter()" in controller_src
    assert "self._router.remove_application_filter()" in controller_src
    assert "app.installEventFilter(self)" not in controller_src
    assert "app.installEventFilter(self)" in router_src
    assert "app.removeEventFilter(self)" in router_src


def test_owner_state_splits_committed_logic_from_presentation_maps():
    """Committed ``_OwnerState`` holds collection/samples; pills live on Projector."""
    names = _owner_state_field_names()
    assert OWNER_STATE_COMMITTED_FIELDS <= names
    assert OWNER_STATE_PRESENTATION_FIELDS.isdisjoint(names)
    assert "reproject_timer" in names
    assert "axis_edit" in names
    presentation_src = (PINNING_ROOT / "presentation.py").read_text(encoding="utf-8")
    assert "class _PresentationState" in presentation_src
    assert "pills:" in presentation_src
    assert "axis_labels:" in presentation_src


def test_controller_keeps_extracted_method_names_as_wrappers():
    """Existing tests and static self-calls keep PinnedCursorController names."""
    methods = _method_names("PinnedCursorController")
    missing = [name for name in CONTROLLER_FACT_WRAPPERS if name not in methods]
    assert missing == []
    missing_sampling = [
        name for name in CONTROLLER_SAMPLING_WRAPPERS if name not in methods
    ]
    assert missing_sampling == []
    missing_commands = [
        name for name in CONTROLLER_COMMAND_FACADE if name not in methods
    ]
    assert missing_commands == []
    source = CONTROLLER_PATH.read_text(encoding="utf-8")
    assert "from ..pinned_cursor_facts import" in source
    assert "pin_primary_html" in source
    assert "def _evaluate(" in source
    assert "def _axis_compatible(" in source
    assert "def _canvas_generations(" in source
    assert "def _bound_identity_keys(" in source
    assert "from .pinning.sampling import" in source
    assert "from .pinning.commands import" in source
    assert "from .pinning.key_router import" in source
    assert "from .pinning.presentation import" in source
    assert "def flush_layout(" in source
    assert "def reflow_visible(" in source
    assert "# ---- unpin / close / undo" not in source
    assert "undo_close" not in methods
    assert "_ClosedPin" not in source


def test_commands_and_sampling_do_not_emit_or_write_collection():
    """Unique commit: collaborators return results; only the façade emits."""
    emit_files = _files_with_intent_changed_emit()
    assert emit_files == {"pinned_cursor_controller.py"}
    collection_files = _files_with_owner_collection_assignment()
    assert collection_files == {"pinned_cursor_controller.py"}
    pinning_files = list(_iter_py_files(PINNING_ROOT) or ())
    assert pinning_files, "T2 pinning package must contain modules"
    for path in pinning_files:
        source = path.read_text(encoding="utf-8")
        assert "intent_changed.emit" not in source
        tree = _parse(path)
        for node in ast.walk(tree):
            name = _call_qualname(node)
            if name is not None:
                assert not name.endswith("intent_changed.emit")


def test_pinning_package_init_stays_light():
    init_path = PINNING_ROOT / "__init__.py"
    imported = _imported_module_names(init_path)
    blob = " ".join(imported)
    assert "pg_canvas" not in blob
    assert "pinned_cursor_controller" not in blob
    assert "main_window" not in blob
    assert "chart_stack.stack" not in blob
    assert not any(
        item.endswith(suffix)
        for item in imported
        for suffix in (".sampling", ".commands", ".key_router", ".presentation")
    )


def test_projector_owns_single_geometry_timer_and_does_not_sample():
    """T7: one QObject-parented layout timer; geometry paths do not evaluate."""
    presentation = (PINNING_ROOT / "presentation.py").read_text(encoding="utf-8")
    assert "QTimer(self)" in presentation
    assert "setSingleShot(True)" in presentation
    assert "def request_reflow(" in presentation
    assert "def flush_layout(" in presentation
    assert "def reflow_now(" in presentation
    assert "_evaluate_intent" not in presentation
    assert "_mark_user_intent" not in presentation
    controller = CONTROLLER_PATH.read_text(encoding="utf-8")
    assert "reproject_timer" in controller
    assert "self._projector.request_reflow" in controller
    assert "self._projector.flush_layout" in controller
    overlay = (
        UI_ROOT / "pg_canvas" / "pinned_cursor_overlay.py"
    ).read_text(encoding="utf-8")
    assert "_geom_timer" in overlay
