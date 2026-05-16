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
