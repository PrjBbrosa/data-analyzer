"""Qt-free contracts for UltraView author-object geometry primitives."""
from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import (
    LATTICE_STEP,
    board_box_to_pixels,
    board_point_to_pixels,
    geometry_grid_bounds,
    pixels_to_board_box,
    pixels_to_board_point,
    screen_px_tolerance_to_board,
    simplify_stroke,
    snap_board_point,
)
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import GridMetrics
from mf4_analyzer.ui.ultraview_state import GridBounds


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
    / "author_geometry.py"
)


def _metrics(*, scale: float = 1.0) -> GridMetrics:
    base = GridMetrics(
        board_width=1600,
        board_height=900,
        column_width=120,
        row_height=88,
        gutter=16,
        padding=20,
        resolution=2,
    )
    if scale == 1.0:
        return base
    return GridMetrics(
        board_width=round(base.board_width * scale),
        board_height=round(base.board_height * scale),
        column_width=round(base.column_width * scale),
        row_height=round(base.row_height * scale),
        gutter=round(base.gutter * scale),
        padding=round(base.padding * scale),
        resolution=base.resolution,
        scale=scale,
        base=base,
    )


def test_module_has_no_qt_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    assert "PyQt5" not in imported
    assert "sip" not in imported


def test_quarter_micro_cell_snap_is_symmetric_at_half_ties():
    assert LATTICE_STEP == 0.25
    assert snap_board_point((0.124, -0.124)) == (0.0, 0.0)
    assert snap_board_point((0.125, -0.125)) == (0.25, -0.25)
    assert snap_board_point((1.37, -1.37)) == (1.25, -1.25)
    assert snap_board_point((math.nan, 0.0)) is None
    assert snap_board_point((1.0, math.inf)) is None
    assert snap_board_point((1.0, 1.0), lattice=0.0) is None


def test_point_and_box_mapping_round_trip_through_signed_elastic_origin():
    metrics = _metrics(scale=1.35)
    origin = (-48.0, -32.0)
    point = (-3.25, 7.75)
    mapped = board_point_to_pixels(point, metrics, origin_offset=origin)
    assert mapped is not None
    assert pixels_to_board_point(mapped, metrics, origin_offset=origin) == pytest.approx(point)

    box = (-4.5, 1.25, 3.75, 2.5)
    pixel_box = board_box_to_pixels(box, metrics, origin_offset=origin)
    assert pixel_box is not None
    assert pixels_to_board_box(pixel_box, metrics, origin_offset=origin) == pytest.approx(box)


def test_mapping_uses_exact_pitch_instead_of_rounded_scaled_pitch():
    metrics = _metrics(scale=1.35)
    # 1× pitch is (120 + 16) / 2 == 68; exact scaled pitch is 91.8.
    assert board_point_to_pixels((40.0, 0.0), metrics) == pytest.approx((3699.0, 27.0))


def test_box_and_point_union_outward_rounds_to_signed_grid_bounds():
    bounds = geometry_grid_bounds(
        points=[(-3.25, 4.0), (2.0, -2.5)],
        boxes=[(-1.5, -0.25, 2.0, 1.5), (3.1, 2.2, -1.2, 0.3)],
        inflate=0.1,
    )
    assert bounds == GridBounds(-4, -3, 7, 8)


def test_degenerate_and_nonfinite_geometry_have_explicit_bounds_behavior():
    assert geometry_grid_bounds(points=[(-0.0, -0.0)]) == GridBounds(0, 0, 1, 1)
    assert geometry_grid_bounds(boxes=[(-2.0, -3.0, 0.0, 0.0)]) == GridBounds(-2, -3, 1, 1)
    assert geometry_grid_bounds(
        points=[(math.nan, 1.0)], boxes=[(0.0, 0.0, math.inf, 2.0)]
    ).empty()


def test_screen_pixel_hit_tolerance_tracks_exact_zoomed_pitch():
    tolerance = screen_px_tolerance_to_board(6.0, _metrics(scale=1.5))
    # 68 * 1.5 and 52 * 1.5 are the unrounded micro-cell pitches.
    assert tolerance == pytest.approx((6.0 / 102.0, 6.0 / 78.0))
    assert screen_px_tolerance_to_board(-1.0, _metrics()) == (0.0, 0.0)


def test_rdp_is_deterministic_preserves_endpoints_and_drops_bad_samples():
    source = [
        (0.0, 0.0),
        (0.0, 0.0),
        (1.0, 0.02),
        (2.0, -0.01),
        (math.nan, 1.0),
        (3.0, 0.0),
    ]
    first = simplify_stroke(source, tolerance=0.05)
    assert first == ((0.0, 0.0), (3.0, 0.0))
    assert simplify_stroke(iter(source), tolerance=0.05) == first
    assert simplify_stroke([], tolerance=1.0) == ()
    assert simplify_stroke([(2.0, 3.0)], tolerance=1.0) == ((2.0, 3.0),)
    assert simplify_stroke([(2.0, 3.0), (2.0, 3.0)], tolerance=1.0) == ((2.0, 3.0),)


def test_rdp_cap_is_stable_and_keeps_first_last_point():
    source = [(float(index), float(index % 2)) for index in range(30)]
    simplified = simplify_stroke(source, tolerance=0.0, max_points=7)
    assert len(simplified) == 7
    assert simplified[0] == source[0]
    assert simplified[-1] == source[-1]
    assert simplify_stroke(source, tolerance=0.0, max_points=7) == simplified
