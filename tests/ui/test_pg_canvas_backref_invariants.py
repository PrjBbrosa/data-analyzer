"""State-ownership invariants for pyqtgraph canvas collaborators."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mf4_analyzer.ui.pg_canvas.annotations import AnnotationManager
from mf4_analyzer.ui.pg_canvas.cursor import CursorController
from mf4_analyzer.ui.pg_canvas.overlay_axes import OverlayAxisManager
from mf4_analyzer.ui.pg_canvas.quality import QualityManager
from mf4_analyzer.ui.pg_canvas.renderer import Renderer
from mf4_analyzer.ui.pg_canvas.tick_density import TickDensityController
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


PG_CANVAS_ROOT = (
    Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui" / "pg_canvas"
)

EXPECTED_WRITE_THROUGH = {
    "Renderer": {
        "_display_x_coverage",
        "_display_x_coverage_by_channel",
        "_last_refresh_signature",
        "_frame_ink_high",
        "_refresh_pending",
    },
    "OverlayAxisManager": set(),
    "CursorController": set(),
    "TickDensityController": set(),
    "AnnotationManager": {"_last_rclick_scene_pos"},
    "QualityManager": set(),
    # _SliceStrip writes its whole state through on purpose, which is why the
    # set is long rather than empty. The slice cursor position, direction and
    # AA flag have to stay readable as canvas._slice_* -- tests and
    # ui/main_window/_order_mixin.py reach for them by name -- so the strip
    # owns the behaviour and the canvas keeps owning the state.
    "_SliceStrip": {
        "_slice_aa_on",
        "_slice_dir",
        "_slice_marker_updating",
        "_slice_x_btn_label",
        "_slice_x_idx",
        "_slice_x_val",
        "_slice_y_btn_label",
        "_slice_y_idx",
        "_slice_y_val",
    },
}

COLLABORATOR_CLASSES = (
    Renderer,
    OverlayAxisManager,
    CursorController,
    TickDensityController,
    AnnotationManager,
    QualityManager,
)


def _string_set_literal(node: ast.AST) -> set[str]:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "frozenset"
    ):
        node = node.args[0] if node.args else ast.Set(elts=[])
    if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return set()
    return {
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }


def _self_assign_targets(class_node: ast.ClassDef) -> set[str]:
    targets = set()
    for node in ast.walk(class_node):
        assigned = []
        if isinstance(node, ast.Assign):
            assigned = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            assigned = [node.target]
        for target in assigned:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                targets.add(target.attr)
    return targets


def _scan_write_through(root: Path = PG_CANVAS_ROOT) -> dict[str, set[str]]:
    result = {}
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            bases = {
                getattr(base, "id", getattr(base, "attr", ""))
                for base in class_node.bases
            }
            if "_CanvasBackref" not in bases:
                continue
            declared = set()
            for statement in class_node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                if any(
                    isinstance(target, ast.Name)
                    and target.id in {"_owned_names", "_delegate_names"}
                    for target in statement.targets
                ):
                    declared.update(_string_set_literal(statement.value))
            result[class_node.name] = (
                _self_assign_targets(class_node) - declared - {"_c"}
            )
    return result


def _assert_expected_write_through(actual: dict[str, set[str]]) -> None:
    assert set(actual) == set(EXPECTED_WRITE_THROUGH), (
        "unknown or missing _CanvasBackref subclasses: "
        f"unknown={sorted(set(actual) - set(EXPECTED_WRITE_THROUGH))}, "
        f"missing={sorted(set(EXPECTED_WRITE_THROUGH) - set(actual))}"
    )
    assert actual == EXPECTED_WRITE_THROUGH


def test_canvas_backref_write_through_matches_explicit_expected_set():
    _assert_expected_write_through(_scan_write_through())


def test_canvas_backref_unknown_subclass_fails_loudly():
    actual = _scan_write_through()
    actual["UnexpectedManager"] = {"_probe"}

    with pytest.raises(AssertionError, match="UnexpectedManager"):
        _assert_expected_write_through(actual)


def test_canvas_backref_delegate_names_do_not_shadow_canvas_state(qapp):
    canvas = TimeDomainCanvasPG()
    canvas_names = set(vars(canvas))

    conflicts = {
        cls.__name__: sorted(set(cls._delegate_names) & canvas_names)
        for cls in COLLABORATOR_CLASSES
        if set(cls._delegate_names) & canvas_names
    }

    assert conflicts == {}
