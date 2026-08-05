"""State-ownership ratchet for the ``ui/main_window`` mixin assembly.

``MainWindow`` is assembled from eight mixins (``window.py`` MRO), but the
split is nominal: methods moved into separate files while the state they
mutate stayed shared.  The attributes written from *more than one file* are the
dangerous class -- no file boundary contains a change to them, and nothing
stops a new one from appearing.

This test freezes that set.  The whitelist may only ever **shrink**: every
migration that gives a cluster of state a real owner deletes its entries, and
any newly introduced multi-file attribute turns the suite red immediately.

Precedent for the AST technique: ``test_pg_canvas_backref_invariants.py``.

What counts as a *write* to ``self.X``
-------------------------------------
================================================  =====  ==================
form                                              write  why
================================================  =====  ==================
``self.X = v`` / ``self.X: T = v`` / ``self.X +=`` yes    rebinding
``for self.X in`` / ``with .. as self.X`` / walrus yes    rebinding
``self.X[k] = v`` / ``del self.X[k]``             yes    ``X`` is a *bare*
                                                         container; item
                                                         writes are ungoverned
                                                         shared state
``self.X.field = v``                              no     ``X`` is a *named
                                                         holder*; the write
                                                         goes through its own
                                                         typed surface -- the
                                                         shape this package is
                                                         migrating **towards**
``self.X.method(...)``                            no     holder keeps its own
                                                         invariants
================================================  =====  ==================

That distinction is the whole point: the migrations below convert bare
scattered state into holder-owned state, so the ratchet dropping is a real
transfer of ownership rather than a counting trick.

Only ``MainWindow`` and the ``*Mixin`` classes are scanned.  Collaborator
classes that merely live in the same directory (``FftTimeCoordinator``, small
widget helpers in ``window.py``) own their state legitimately and must not
collide with it.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

MAIN_WINDOW_ROOT = (
    Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui" / "main_window"
)

# Attribute -> files that write it, measured on `main` @ b886a30e (Task 0).
#
# THIS SET MAY ONLY SHRINK.  Adding an entry means a new piece of MainWindow
# state escaped its owner; fix the code, not the whitelist.
FROZEN_MULTI_FILE_STATE: dict[str, tuple[str, ...]] = {
    # -- progress tokens / restore guard (Task 5) ---------------------------
    "_analysis_progress_tokens": (
        "_fft_time_mixin.py",
        "_order_mixin.py",
        "window.py",
    ),
    "_restoring_project": ("_channel_scope_mixin.py", "_project_io_mixin.py"),
    # -- file/session identity; dispositions recorded in Task 6 -------------
    "_active": ("_project_io_mixin.py", "window.py"),
    "_analysis_restore_pending": ("_project_io_mixin.py", "window.py"),
    "_applying_analysis_view": ("_analysis_mixin.py", "window.py"),
    "_blf_dbc_history": ("_project_io_mixin.py", "window.py"),
    "_fc": ("_project_io_mixin.py", "window.py"),
    "_project_path": ("_project_io_mixin.py", "window.py"),
    "files": ("_project_io_mixin.py", "window.py"),
}


def _writes_in(node: ast.AST) -> set[str]:
    """Attribute names written by a single assignment target."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return {node.attr}
    if isinstance(node, ast.Subscript):
        base = node.value
        if (
            isinstance(base, ast.Attribute)
            and isinstance(base.value, ast.Name)
            and base.value.id == "self"
        ):
            return {base.attr}
        return set()
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_writes_in(e) for e in node.elts)) if node.elts else set()
    if isinstance(node, ast.Starred):
        return _writes_in(node.value)
    return set()


def _self_writes(class_node: ast.ClassDef) -> set[str]:
    written: set[str] = set()
    for node in ast.walk(class_node):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.For)):
            targets = [node.target]
        elif isinstance(node, ast.NamedExpr):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = node.targets
        elif isinstance(node, ast.With):
            targets = [i.optional_vars for i in node.items if i.optional_vars]
        else:
            continue
        for target in targets:
            written |= _writes_in(target)
    return written


def _is_main_window_class(class_node: ast.ClassDef) -> bool:
    return class_node.name == "MainWindow" or class_node.name.endswith("Mixin")


def _scan_multi_file_state(
    root: Path = MAIN_WINDOW_ROOT,
) -> dict[str, tuple[str, ...]]:
    per_attr: dict[str, set[str]] = defaultdict(set)
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for class_node in ast.walk(tree):
            if not isinstance(class_node, ast.ClassDef):
                continue
            if not _is_main_window_class(class_node):
                continue
            for attr in _self_writes(class_node):
                per_attr[attr].add(path.name)
    return {
        attr: tuple(sorted(files))
        for attr, files in per_attr.items()
        if len(files) >= 2
    }


def _assert_matches_whitelist(actual: dict[str, tuple[str, ...]]) -> None:
    escaped = sorted(set(actual) - set(FROZEN_MULTI_FILE_STATE))
    migrated = sorted(set(FROZEN_MULTI_FILE_STATE) - set(actual))
    assert not escaped, (
        "new multi-file MainWindow state -- give it an owner instead of "
        "widening the whitelist: "
        + ", ".join(f"{a} written by {list(actual[a])}" for a in escaped)
    )
    assert not migrated, (
        "these attributes no longer have multi-file writes; the ratchet only "
        "counts when the whitelist shrinks with them -- delete them from "
        f"FROZEN_MULTI_FILE_STATE: {migrated}"
    )


def test_multi_file_state_matches_frozen_whitelist():
    _assert_matches_whitelist(_scan_multi_file_state())


def test_whitelist_records_the_current_writer_files():
    actual = _scan_multi_file_state()
    drifted = {
        attr: {"recorded": files, "actual": actual[attr]}
        for attr, files in FROZEN_MULTI_FILE_STATE.items()
        if attr in actual and actual[attr] != files
    }
    assert drifted == {}, f"whitelist file annotations are stale: {drifted}"


def test_ratchet_rejects_a_newly_escaped_attribute():
    actual = _scan_multi_file_state()
    actual["_newly_scattered"] = ("_view_mixin.py", "window.py")

    with pytest.raises(AssertionError, match="_newly_scattered"):
        _assert_matches_whitelist(actual)


def test_ratchet_requires_whitelist_to_shrink_after_a_migration():
    actual = _scan_multi_file_state()
    actual.pop(next(iter(FROZEN_MULTI_FILE_STATE)))

    with pytest.raises(AssertionError, match="delete them from"):
        _assert_matches_whitelist(actual)


def test_scan_ignores_non_mainwindow_collaborator_classes():
    """FftTimeCoordinator owns its own state; it must not feed the ratchet."""
    coordinator = MAIN_WINDOW_ROOT / "fft_time_coordinator.py"
    tree = ast.parse(coordinator.read_text(encoding="utf-8"))
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]

    assert classes, "expected FftTimeCoordinator to still live here"
    assert not any(_is_main_window_class(c) for c in classes)
