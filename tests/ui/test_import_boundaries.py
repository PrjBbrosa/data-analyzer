"""Static AST-based import-boundary checks for the UI layering.

These tests must NEVER construct ``MainWindow`` or import Qt — they walk
the source files with ``ast`` so they survive even if the runtime import
graph is reachable. They pin the three-way layering between
``mf4_analyzer.ui_kit`` (shared), ``mf4_analyzer.ui`` (Analyzer), and
``mf4_analyzer.acquisition_ui`` (Cockpit, S4):

* ``ui_kit.*`` is the lowest layer — it never imports ``ui.*`` or
  ``acquisition_ui.*``.
* ``ui.*`` never imports ``acquisition_ui.*``. The reverse is
  permitted (Cockpit may, in future, peek at Analyzer's public
  ``MainWindow.load_file`` symbol after Stage 5).
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "mf4_analyzer"


def _iter_py_files(pkg_dir: Path):
    if not pkg_dir.exists():
        return
    for path in pkg_dir.rglob("*.py"):
        # Skip __pycache__ which rglob normally omits but be explicit.
        if "__pycache__" in path.parts:
            continue
        yield path


def _imported_module_names(source_path: Path) -> list[str]:
    """Return every fully-qualified module name imported by ``source_path``.

    Handles both ``import a.b`` and ``from a.b import c`` forms. Relative
    imports (``from . import x``) are resolved against the file's package
    path so they appear as dotted module names rooted at ``mf4_analyzer``.
    """
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source_path))

    # Compute this file's package dotted path so relative imports resolve.
    rel = source_path.relative_to(REPO_ROOT)
    parts = list(rel.with_suffix("").parts)
    # If this file is __init__.py, its package IS its parent's dotted path.
    if parts[-1] == "__init__":
        parts = parts[:-1]
    else:
        parts = parts[:-1]
    pkg_dotted = ".".join(parts)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0:
                imported.append(module)
            else:
                # Resolve relative import against pkg_dotted.
                base_parts = pkg_dotted.split(".") if pkg_dotted else []
                if node.level > len(base_parts):
                    # Malformed; record as-is and let other tests fail.
                    imported.append(module)
                    continue
                anchor = ".".join(base_parts[: len(base_parts) - node.level + 1])
                if module:
                    imported.append(f"{anchor}.{module}" if anchor else module)
                else:
                    imported.append(anchor)
    return imported


def _violations(
    pkg_dir: Path,
    forbidden_prefixes: tuple[str, ...],
) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for src in _iter_py_files(pkg_dir):
        for imp in _imported_module_names(src):
            for prefix in forbidden_prefixes:
                if imp == prefix or imp.startswith(prefix + "."):
                    out.append((src, imp))
                    break
    return out


def test_ui_kit_never_imports_from_analyzer_ui_or_acquisition_ui():
    """``mf4_analyzer.ui_kit.*`` is the bottom of the UI dependency
    graph; it must not depend on Analyzer's ``ui`` package or the
    Cockpit ``acquisition_ui`` package."""
    ui_kit_dir = PACKAGE_ROOT / "ui_kit"
    if not ui_kit_dir.exists():
        pytest.fail(
            "mf4_analyzer/ui_kit/ does not exist; Stage 1 has not run yet.",
        )
    violations = _violations(
        ui_kit_dir,
        forbidden_prefixes=(
            "mf4_analyzer.ui",
            "mf4_analyzer.acquisition_ui",
        ),
    )
    # ``mf4_analyzer.ui_kit`` itself is fine; ``mf4_analyzer.ui`` and
    # ``mf4_analyzer.ui.*`` are not.
    real_violations = [
        (p, imp) for (p, imp) in violations
        if not (imp == "mf4_analyzer.ui_kit" or imp.startswith("mf4_analyzer.ui_kit."))
    ]
    assert not real_violations, (
        "ui_kit must not import from ui or acquisition_ui; offending "
        f"imports: {real_violations!r}"
    )


def test_navigator_order_does_not_import_qt_or_mainwindow():
    """Workspace order is a Qt-free collaborator; it must not pull widgets."""
    src = PACKAGE_ROOT / "ui" / "navigator_order.py"
    imported = _imported_module_names(src)
    forbidden = (
        "PyQt5",
        "pyqtgraph",
        "mf4_analyzer.ui.main_window",
        "mf4_analyzer.ui.file_navigator",
        "mf4_analyzer.ui.widgets",
        "mf4_analyzer.ui.chart_stack",
        "mf4_analyzer.acquisition_ui",
    )
    violations = [
        name
        for name in imported
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert not violations, violations


def test_channel_drag_does_not_import_qt_or_widgets():
    src = PACKAGE_ROOT / "ui" / "channel_drag.py"
    imported = _imported_module_names(src)
    forbidden = (
        "PyQt5",
        "pyqtgraph",
        "mf4_analyzer.ui.main_window",
        "mf4_analyzer.ui.file_navigator",
        "mf4_analyzer.ui.widgets",
        "mf4_analyzer.ui.chart_stack",
        "mf4_analyzer.acquisition_ui",
    )
    violations = [
        name
        for name in imported
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert not violations, violations


def test_analyzer_ui_never_imports_from_acquisition_ui():
    """``mf4_analyzer.ui.*`` (Analyzer) must not import the Cockpit
    package. The Cockpit may import from Analyzer (one-way arrow)."""
    ui_dir = PACKAGE_ROOT / "ui"
    violations = _violations(
        ui_dir,
        forbidden_prefixes=("mf4_analyzer.acquisition_ui",),
    )
    assert not violations, (
        "Analyzer ui must not import from acquisition_ui; offending "
        f"imports: {violations!r}"
    )


def test_resolver_handles_relative_imports_inside_ui_kit():
    """Sanity-check the relative-import resolver: a synthetic
    ``from .icons import X`` inside ``ui_kit/`` must resolve to
    ``mf4_analyzer.ui_kit.icons`` so the forbidden-prefix scan above is
    trustworthy."""
    ui_kit_dir = PACKAGE_ROOT / "ui_kit"
    if not ui_kit_dir.exists():
        pytest.skip("ui_kit/ not present; covered by the first test.")
    # ui_kit/__init__.py exists — pretend a file under ui_kit imports
    # `from .icons import Icons` and assert resolution.
    fake = ui_kit_dir / "__init__.py"
    tree = ast.parse(
        "from .icons import Icons\n",
        filename=str(fake),
    )
    rel = fake.relative_to(REPO_ROOT)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    else:
        parts = parts[:-1]
    pkg_dotted = ".".join(parts)
    assert pkg_dotted == "mf4_analyzer.ui_kit"

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base_parts = pkg_dotted.split(".")
            anchor = ".".join(base_parts[: len(base_parts) - node.level + 1])
            resolved = f"{anchor}.{node.module}"
            assert resolved == "mf4_analyzer.ui_kit.icons"
            return
    pytest.fail("ImportFrom node not found by walk")


def _function_level_import_modules(source_path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def _in_function(node: ast.AST) -> bool:
        cur: ast.AST | None = node
        while cur in parents:
            cur = parents[cur]
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return True
        return False

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not _in_function(node):
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            found.append((node.lineno, node.module or ""))
    return found


def test_ultraview_core_has_no_qt_or_ui_imports():
    """Qt-free core must not import ``mf4_analyzer.ui`` or Qt (Task 5.2)."""
    core_dir = PACKAGE_ROOT / "ultraview_core"
    forbidden = (
        "PyQt5",
        "sip",
        "pyqtgraph",
        "mf4_analyzer.ui",
        "mf4_analyzer.ui_kit",
        "mf4_analyzer.acquisition_ui",
    )
    for src in _iter_py_files(core_dir):
        imported = _imported_module_names(src)
        violations = [
            name
            for name in imported
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
        ]
        assert not violations, (src.name, violations)
        assert not any("card_fit" in name for name in imported)
        assert not any("compositor" in name for name in imported)
    geometry_src = core_dir / "grid_geometry.py"
    geometry_imported = _imported_module_names(geometry_src)
    assert "mf4_analyzer.ui.ultraview_state" not in geometry_imported
    assert any(
        name.endswith(".model") or name == "mf4_analyzer.ultraview_core.model"
        for name in geometry_imported
    )
    board_ops_src = core_dir / "board_ops.py"
    board_ops_imported = _imported_module_names(board_ops_src)
    assert "mf4_analyzer.ui.ultraview_state" not in board_ops_imported
    assert any(
        name.endswith(".model") or name == "mf4_analyzer.ultraview_core.model"
        for name in board_ops_imported
    )


def test_ultraview_free_grid_and_card_fit_have_no_cycle():
    free_grid = PACKAGE_ROOT / "ui" / "chart_stack" / "ultraview" / "free_grid.py"
    card_fit = PACKAGE_ROOT / "ui" / "chart_stack" / "ultraview" / "card_fit.py"
    free_imported = _imported_module_names(free_grid)
    card_imported = _imported_module_names(card_fit)
    assert not any(name.endswith(".card_fit") or name == "card_fit" for name in free_imported)
    assert not any(name.endswith(".free_grid") or name == "free_grid" for name in card_imported)
    nested = [
        (lineno, module)
        for lineno, module in _function_level_import_modules(free_grid)
        if module == "card_fit" or module.endswith(".card_fit")
    ]
    assert nested == []
    assert any(
        name.endswith(".grid_geometry") or name == "mf4_analyzer.ultraview_core.grid_geometry"
        for name in free_imported
    )
    assert any(
        name.endswith(".grid_geometry") or name == "mf4_analyzer.ultraview_core.grid_geometry"
        for name in card_imported
    )


def test_ultraview_core_subprocess_import_does_not_load_qt():
    """Core model, geometry, and board ops must stay importable without Qt."""
    script = """
import json
import sys
import mf4_analyzer.ultraview_core.model
import mf4_analyzer.ultraview_core.grid_geometry
import mf4_analyzer.ultraview_core.board_ops
blocked = sorted(
    name for name in sys.modules
    if name == "PyQt5"
    or name.startswith("PyQt5.")
    or name == "pyqtgraph"
    or name.startswith("pyqtgraph.")
    or name == "mf4_analyzer.ui"
    or name.startswith("mf4_analyzer.ui.")
    or name == "mf4_analyzer.ui.main_window"
    or name.startswith("mf4_analyzer.ui.main_window.")
    or name == "mf4_analyzer.ui.chart_stack.ultraview.compositor"
    or name.endswith(".compositor")
)
print(json.dumps(blocked))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
