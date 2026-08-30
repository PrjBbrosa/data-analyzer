"""Qt-free pin: core chrome/pitch identity with layouts and screen/export.

Does not import Qt. layouts.py constants are read via AST so the pin stays
Qt-free (importing ``ui.chart_stack`` would pull PyQt5).
"""
from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from mf4_analyzer.ultraview_core import grid_geometry
from mf4_analyzer.ultraview_core.grid_geometry import (
    BASE_BOARD_SIZE,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    CARD_IMAGE_PADDING,
    GRID_MIN_COLUMN_WIDTH,
    GridMetrics,
    canonical_export_metrics,
    canonical_screen_metrics,
    contained_preview_rect,
    grid_metrics,
    inner_reading_box,
    reading_fill,
    rect_to_pixels,
)
from mf4_analyzer.ultraview_core.model import FreeGridPlacement, GridRect, UltraViewRef

REPO_ROOT = Path(__file__).resolve().parents[1]
LAYOUTS_PATH = (
    REPO_ROOT / "mf4_analyzer" / "ui" / "chart_stack" / "ultraview" / "layouts.py"
)
FREE_GRID_PATH = (
    REPO_ROOT / "mf4_analyzer" / "ui" / "chart_stack" / "ultraview" / "free_grid.py"
)

WELL_CHOSEN_16X9_RECT = GridRect(0, 0, 16, 13)
ASPECT_16_9 = (16.0, 9.0)


def _module_literals(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            values[target.id] = ast.literal_eval(node.value)
        except ValueError:
            continue
    return values


def _calls_in_function(path: Path, func_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != func_name:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                names.append(child.func.id)
    return names


def _scale_metrics(metrics: GridMetrics, scale: float) -> GridMetrics:
    base = metrics.base if metrics.base is not None else metrics
    if abs(float(scale) - 1.0) < 1e-12:
        return base
    return GridMetrics(
        board_width=max(1, int(round(base.board_width * scale))),
        board_height=max(1, int(round(base.board_height * scale))),
        column_width=max(1, int(round(base.column_width * scale))),
        row_height=max(1, int(round(base.row_height * scale))),
        gutter=max(0, int(round(base.gutter * scale))),
        padding=max(0, int(round(base.padding * scale))),
        resolution=base.resolution,
        scale=float(scale),
        base=base,
    )


def test_chrome_and_board_size_match_layouts_literals():
    layouts = _module_literals(LAYOUTS_PATH)
    assert CARD_HEADER_HEIGHT == layouts["CARD_HEADER_HEIGHT"] == 34
    assert CARD_FOOTER_HEIGHT == layouts["CARD_FOOTER_HEIGHT"] == 24
    assert CARD_IMAGE_PADDING == layouts["CARD_IMAGE_PADDING"] == 8
    assert BASE_BOARD_SIZE == layouts["BASE_BOARD_SIZE"] == (1600, 900)
    assert grid_geometry.BOARD_PADDING == layouts["BOARD_PADDING"] == 16
    assert grid_geometry.SLOT_GUTTER == layouts["SLOT_GUTTER"] == 12


def test_canonical_screen_export_share_1x_pitch_not_96px_columns():
    ref = UltraViewRef("time", "metric")
    rect = GridRect(2, 4, 16, 12)
    placements = (FreeGridPlacement(ref, rect),)
    screen = canonical_screen_metrics(placements)
    export = canonical_export_metrics(placements)
    planner = grid_metrics((1600, 0), placements)
    px_screen = rect_to_pixels(rect, screen)
    assert px_screen == rect_to_pixels(rect, export) == rect_to_pixels(rect, planner)
    assert screen.column_width == export.column_width == planner.column_width
    assert screen.column_width == grid_metrics((BASE_BOARD_SIZE[0], 0), placements).column_width
    assert screen.column_width > GRID_MIN_COLUMN_WIDTH
    assert screen.board_width == 1600
    assert export.board_width == 1600


def test_canonical_column_width_ignores_window_width():
    placements = (FreeGridPlacement(UltraViewRef("time", "w"), GridRect(0, 0, 8, 6)),)
    canonical = canonical_screen_metrics(placements).column_width
    assert canonical == canonical_export_metrics(placements).column_width
    assert canonical == grid_metrics((1600, 0), placements).column_width
    assert canonical != grid_metrics((2000, 0), placements).column_width


def test_dpr_scale_recovers_logical_rect_within_1px():
    rect = GridRect(4, 6, 12, 10)
    placements = (FreeGridPlacement(UltraViewRef("time", "dpr"), rect),)
    screen = canonical_screen_metrics(placements)
    px_1x = rect_to_pixels(rect, screen)
    scaled = _scale_metrics(screen, 2.0)
    assert scaled.exact_padding() == pytest.approx(screen.exact_padding() * 2.0)
    pitch_1x = screen.exact_pitch()
    pitch_2x = scaled.exact_pitch()
    assert pitch_2x[0] == pytest.approx(pitch_1x[0] * 2.0)
    assert pitch_2x[1] == pytest.approx(pitch_1x[1] * 2.0)
    px_2x = rect_to_pixels(rect, scaled)
    logical_from_dpr2 = tuple(component / 2.0 for component in px_2x)
    for recovered, original in zip(logical_from_dpr2, px_1x):
        assert abs(recovered - original) <= 1.0


def test_inner_reading_box_deducts_chrome_and_16x9_fill():
    placements = (FreeGridPlacement(UltraViewRef("time", "fit"), WELL_CHOSEN_16X9_RECT),)
    metrics = canonical_screen_metrics(placements)
    outer = rect_to_pixels(WELL_CHOSEN_16X9_RECT, metrics)
    reading = inner_reading_box(WELL_CHOSEN_16X9_RECT, metrics)
    assert reading[0] == outer[0] + CARD_IMAGE_PADDING
    assert reading[1] == outer[1] + CARD_HEADER_HEIGHT + CARD_IMAGE_PADDING
    assert reading[2] == outer[2] - 2 * CARD_IMAGE_PADDING
    assert reading[3] == (
        outer[3] - CARD_HEADER_HEIGHT - CARD_FOOTER_HEIGHT - 2 * CARD_IMAGE_PADDING
    )
    preview = contained_preview_rect(reading, ASPECT_16_9)
    px, py, pw, ph = preview
    rx, ry, rw, rh = reading
    assert pw > 0 and ph > 0
    assert px >= rx and py >= ry
    assert px + pw <= rx + rw
    assert py + ph <= ry + rh
    fill = reading_fill(preview, reading)
    assert math.isfinite(fill)
    assert fill >= 0.82
    assert reading_fill((0, 0, 10, 10), (0, 0, 0, 10)) == 0.0


def test_contained_preview_prefers_side_gaps_on_wide_box():
    # Wider than 16:9: height-first contain leaves leftover on the sides.
    reading = (0, 0, 320, 90)
    preview = contained_preview_rect(reading, ASPECT_16_9)
    _px, py, pw, ph = preview
    assert ph == 90
    assert pw < 320
    assert py == 0
    assert pw / ph == pytest.approx(16.0 / 9.0, rel=0.02)


def test_free_grid_wrappers_delegate_to_canonical_owner():
    assert "canonical_export_metrics" in _calls_in_function(
        FREE_GRID_PATH, "export_grid_metrics"
    )
    assert "canonical_screen_metrics" in _calls_in_function(
        FREE_GRID_PATH, "screen_grid_metrics"
    )
    assert "grid_metrics" not in _calls_in_function(FREE_GRID_PATH, "export_grid_metrics")
    assert "grid_metrics" not in _calls_in_function(FREE_GRID_PATH, "screen_grid_metrics")
