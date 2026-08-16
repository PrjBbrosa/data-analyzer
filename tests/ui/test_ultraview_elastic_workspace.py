"""Qt-free elastic workspace extent, halo, and edge-pan contracts."""
from __future__ import annotations

import ast
from pathlib import Path

from mf4_analyzer.ui.chart_stack.ultraview.elastic_workspace import (
    EDGE_PAN_BAND_PX,
    EDGE_PAN_SPEED_MAX,
    EDGE_PAN_SPEED_MIN,
    EXTENT_CHUNK_COLUMNS,
    HALO_MIN_CELLS,
    content_bounds,
    desired_extent,
    edge_pan_velocity,
    expand_extent,
)
from mf4_analyzer.ui.ultraview_state import (
    GRID_COLUMNS,
    MAX_GRID_ROWS,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    FreeGridPlacement,
    GridBounds,
    GridRect,
    base_frame_bounds,
    make_ref,
    safety_grid_bounds,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
    / "elastic_workspace.py"
)


def _placement(view_id: str, rect: GridRect) -> FreeGridPlacement:
    return FreeGridPlacement(make_ref("time", view_id), rect)


def test_module_has_no_qt_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    assert "PyQt5" not in imported
    assert "sip" not in imported


def test_grid_bounds_is_immutable_half_open():
    bounds = GridBounds(-4, -8, 20, 16)
    assert bounds.column_end == 16
    assert bounds.row_end == 8
    assert bounds.empty() is False
    merged = bounds.union(GridBounds(10, 0, 6, 4))
    assert merged == GridBounds(-4, -8, 20, 16)
    assert GridBounds(0, 0, 0, 0).empty()
    assert GridBounds(0, 0, 0, 0).union(bounds) == bounds


def test_content_bounds_unions_placed_rects_and_empty_is_empty():
    assert content_bounds([]) == GridBounds(0, 0, 0, 0)
    assert content_bounds(()).empty()
    placements = [
        _placement("a", GridRect(-4, 2, 4, 3)),
        _placement("b", GridRect(10, -2, 6, 3)),
    ]
    union = content_bounds(placements)
    assert union == GridBounds(-4, -2, 20, 7)
    assert content_bounds(placements) == union


def test_base_frame_and_safety_bounds_match_the_product_contract():
    base = base_frame_bounds()
    assert base == GridBounds(0, 0, GRID_COLUMNS, MAX_GRID_ROWS)
    safety = safety_grid_bounds()
    assert safety.column == SAFETY_COLUMN_MIN
    assert safety.column_end == SAFETY_COLUMN_MAX
    assert safety.row == SAFETY_ROW_MIN
    assert safety.row_end == SAFETY_ROW_MAX


def test_desired_extent_gives_halo_slack_for_empty_and_single_card():
    pitch = (128.0, 96.0)
    viewport = (200.0, 160.0)
    empty = desired_extent(GridBounds(0, 0, 0, 0), viewport, pitch, zoom=1.0)
    single_content = content_bounds([_placement("a", GridRect(0, 0, 4, 3))])
    single = desired_extent(single_content, viewport, pitch, zoom=1.0)
    base = base_frame_bounds()
    for extent, source in ((empty, GridBounds(0, 0, 0, 0)), (single, single_content)):
        assert extent.column <= base.column - HALO_MIN_CELLS
        assert extent.column_end >= base.column_end + HALO_MIN_CELLS
        assert extent.row <= base.row - HALO_MIN_CELLS
        assert extent.row_end >= base.row_end + HALO_MIN_CELLS
        assert extent.column % EXTENT_CHUNK_COLUMNS == 0
        assert extent.column_end % EXTENT_CHUNK_COLUMNS == 0
        assert extent == desired_extent(source, viewport, pitch, zoom=1.0)


def test_desired_extent_uses_half_viewport_when_larger_than_min_halo():
    pitch = (100.0, 100.0)
    viewport = (2000.0, 800.0)
    extent = desired_extent(GridBounds(0, 0, 0, 0), viewport, pitch, zoom=1.0)
    assert extent.column <= -10
    assert extent.column_end >= GRID_COLUMNS + 10
    assert extent.row <= -4
    assert extent.row_end >= MAX_GRID_ROWS + 4


def test_desired_extent_and_expand_extent_are_deterministic():
    content = GridBounds(-6, 2, 18, 9)
    viewport = (1600.0, 900.0)
    pitch = (128.0, 96.0)
    first = desired_extent(content, viewport, pitch, zoom=0.66)
    second = desired_extent(content, viewport, pitch, zoom=0.66)
    assert first == second
    grown = expand_extent(first, second)
    assert grown == first
    assert expand_extent(first, second) == grown


def test_expand_extent_never_shrinks():
    current = GridBounds(-16, -16, 48, 80)
    desired = GridBounds(-4, -4, 20, 56)
    kept = expand_extent(current, desired)
    assert kept.column == current.column
    assert kept.row == current.row
    assert kept.column_end == current.column_end
    assert kept.row_end == current.row_end
    wider = expand_extent(current, GridBounds(-24, -16, 20, 80))
    assert wider.column == -24
    assert wider.column_end == current.column_end
    assert expand_extent(GridBounds(0, 0, 0, 0), desired) == desired


def test_expand_extent_keeps_high_water_inside_safety_bounds():
    """Even a stale/corrupt runtime extent cannot turn the guard into an
    unbounded scroll surface.  Normal callers provide ``desired_extent``
    results, but this pure helper is the final safety boundary."""
    corrupted = GridBounds(-999, -999, 2_000, 2_000)
    desired = GridBounds(-8, -8, 24, 64)

    extent = expand_extent(corrupted, desired)

    assert extent == safety_grid_bounds()


def test_edge_pan_velocity_is_zero_outside_the_band():
    size = (800.0, 600.0)
    assert edge_pan_velocity((400.0, 300.0), size) == (0.0, 0.0)
    assert edge_pan_velocity((EDGE_PAN_BAND_PX, 300.0), size) == (0.0, 0.0)
    assert edge_pan_velocity((400.0, size[1] - EDGE_PAN_BAND_PX), size) == (0.0, 0.0)
    assert edge_pan_velocity((-1.0, 300.0), size) == (0.0, 0.0)
    assert edge_pan_velocity((801.0, 300.0), size) == (0.0, 0.0)


def test_edge_pan_velocity_ramps_from_band_to_widget_edge():
    size = (800.0, 600.0)
    left_edge = edge_pan_velocity((0.0, 300.0), size)
    right_edge = edge_pan_velocity((800.0, 300.0), size)
    top_edge = edge_pan_velocity((400.0, 0.0), size)
    bottom_edge = edge_pan_velocity((400.0, 600.0), size)
    assert left_edge[0] == -EDGE_PAN_SPEED_MAX
    assert left_edge[1] == 0.0
    assert right_edge[0] == EDGE_PAN_SPEED_MAX
    assert top_edge[1] == -EDGE_PAN_SPEED_MAX
    assert bottom_edge[1] == EDGE_PAN_SPEED_MAX
    inner_left = edge_pan_velocity((EDGE_PAN_BAND_PX - 1.0, 300.0), size)
    assert inner_left[0] < 0.0
    assert abs(inner_left[0] + EDGE_PAN_SPEED_MIN) < 1.0
    diagonal = edge_pan_velocity((0.0, 0.0), size)
    assert diagonal[0] == -EDGE_PAN_SPEED_MAX
    assert diagonal[1] == -EDGE_PAN_SPEED_MAX
    assert edge_pan_velocity((0.0, 0.0), size) == diagonal
