"""Qt-free contracts for UltraView author-object geometry primitives."""
from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import (
    CORNER_HANDLES,
    LATTICE_STEP,
    SQUARE_SNAP_ENTER_PX,
    SQUARE_SNAP_EXIT_PX,
    apply_square_snap,
    board_box_to_pixels,
    board_point_to_pixels,
    geometry_grid_bounds,
    pixels_to_board_box,
    pixels_to_board_point,
    resize_box_candidate,
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


def test_square_snap_corners_quadrants_hysteresis_and_bypass():
    box = (10.0, 20.0, 4.0, 3.0)
    pitch = 10.0
    # 4x3 at 10 px/unit = 40x30. SE dy=0.4 -> 40x34, delta=6 <= 8 enter.
    entered, snapped = resize_box_candidate(
        box, "se", 0.0, 0.4, pitch_x=pitch, pitch_y=pitch, square_snap=True
    )
    assert snapped is True
    assert entered[2] == pytest.approx(entered[3])
    assert entered[0] == pytest.approx(10.0)
    assert entered[1] == pytest.approx(20.0)

    # dy=0.1 -> 40x31, delta=9 > 8 stay free
    open_box, open_snapped = resize_box_candidate(
        box, "se", 0.0, 0.1, pitch_x=pitch, pitch_y=pitch, square_snap=True
    )
    assert open_snapped is False
    assert open_box[3] == pytest.approx(3.1)

    held, still = apply_square_snap(
        box,
        (10.0, 20.0, 4.0, 3.0 + 1.1),
        "se",
        pitch_x=pitch,
        pitch_y=pitch,
        snapped=True,
        bypass=False,
    )
    # delta = |40 - 41| wait 3+1.1=4.1 -> 41px vs 40px = 1 <= 12, still snapped
    assert still is True
    assert held[2] == pytest.approx(held[3])

    released, left = apply_square_snap(
        box,
        (10.0, 20.0, 4.0, 5.4),
        "se",
        pitch_x=pitch,
        pitch_y=pitch,
        snapped=True,
        bypass=False,
    )
    # 54 vs 40 px, delta=14 > 12 leave
    assert left is False
    assert released[3] == pytest.approx(5.4)

    bypassed, flag = resize_box_candidate(
        box, "se", 0.0, 0.4, pitch_x=pitch, pitch_y=pitch, square_snap=True, bypass=True
    )
    assert flag is False
    assert bypassed[3] == pytest.approx(3.4)

    near = (10.0, 20.0, 4.0, 3.9)
    for handle in CORNER_HANDLES:
        candidate, snapped = resize_box_candidate(
            near, handle, 0.0, 0.0, pitch_x=pitch, pitch_y=pitch, square_snap=True
        )
        assert snapped is True
        assert candidate[2] == pytest.approx(candidate[3])

    edge, edge_snap = resize_box_candidate(
        box, "e", 0.4, 0.4, pitch_x=pitch, pitch_y=pitch, square_snap=True
    )
    assert edge_snap is False
    assert edge[2] != pytest.approx(edge[3])


def test_square_snap_keeps_fixed_opposite_corner():
    box = (8.0, 6.0, 5.0, 2.0)
    pitch = 8.0
    nw, snapped = resize_box_candidate(
        box, "nw", 0.0, -2.9, pitch_x=pitch, pitch_y=pitch, square_snap=True
    )
    assert snapped is True
    assert nw[0] + nw[2] == pytest.approx(13.0)
    assert nw[1] + nw[3] == pytest.approx(8.0)
    assert simplify_stroke([(2.0, 3.0), (2.0, 3.0)], tolerance=1.0) == ((2.0, 3.0),)


def test_rdp_cap_is_stable_and_keeps_first_last_point():
    source = [(float(index), float(index % 2)) for index in range(30)]
    simplified = simplify_stroke(source, tolerance=0.0, max_points=7)
    assert len(simplified) == 7
    assert simplified[0] == source[0]
    assert simplified[-1] == source[-1]
    assert simplify_stroke(source, tolerance=0.0, max_points=7) == simplified
