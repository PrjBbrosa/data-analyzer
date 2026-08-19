"""Qt-free elastic workspace extent, halo, and edge-pan velocity.

Screen widgets own the session high-water mark and the 16 ms edge timer.
This module only computes deterministic geometry: same inputs, same outputs.
It must not import PyQt5, persist extent, or mark the project dirty.
"""
from __future__ import annotations

import math
from typing import Iterable

from mf4_analyzer.ui.ultraview_state import (
    ConnectorObject,
    GRID_RESOLUTION,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    FreeGridPlacement,
    GridBounds,
    GridRect,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
    base_frame_bounds,
    safety_grid_bounds,
)

from .author_geometry import geometry_grid_bounds

# A schema-5 cell is a micro-grid unit.  Keep the physical four-cell halo and
# expansion cadence from schema 4 rather than making the canvas appear to
# contract just because its coordinates gained twice the resolution.
HALO_MIN_CELLS = 4 * GRID_RESOLUTION
EXTENT_CHUNK_COLUMNS = 4 * GRID_RESOLUTION
EXTENT_CHUNK_ROWS = 4 * GRID_RESOLUTION
EDGE_PAN_BAND_PX = 72
EDGE_PAN_SPEED_MIN = 4.0
EDGE_PAN_SPEED_MAX = 22.0

_PlacementLike = FreeGridPlacement | GridRect | GridBounds

# Author line width is measured in 1× pixels while the elastic workspace is
# measured in micro-grid cells.  One cell is deliberately conservative for
# the widest V1 64 px cap/head at the canonical 1600-wide pitch.  It avoids
# clipping ink at Fit/export edges without making the persistent state depend
# on a live widget or zoom factor.
AUTHOR_INK_BOUNDS_INFLATE = 1.0


def author_content_bounds(objects: Iterable[object]) -> GridBounds:
    """Return signed, conservative bounds of renderable author content.

    Future/unknown objects deliberately contribute no geometry: they are
    retained by persistence but the current renderer cannot make a truthful
    promise about their footprint.  Recognized line-like objects receive a
    one-cell ink margin so rounded caps and arrow heads survive crop/fit.
    """
    union = GridBounds(0, 0, 0, 0)
    for item in objects:
        if isinstance(item, (StickyObject, TextObject, ShapeObject)):
            union = union.union(
                geometry_grid_bounds(
                    boxes=((item.box.x, item.box.y, item.box.width, item.box.height),)
                )
            )
        elif isinstance(item, StrokeObject):
            union = union.union(
                geometry_grid_bounds(
                    points=((point.x, point.y) for point in item.points),
                    inflate=AUTHOR_INK_BOUNDS_INFLATE,
                )
            )
        elif isinstance(item, ConnectorObject):
            union = union.union(
                geometry_grid_bounds(
                    points=(
                        (item.start.point.x, item.start.point.y),
                        (item.end.point.x, item.end.point.y),
                    ),
                    inflate=AUTHOR_INK_BOUNDS_INFLATE,
                )
            )
    return union


def content_bounds(
    placements: Iterable[_PlacementLike], *, author_objects: Iterable[object] = ()
) -> GridBounds:
    """Union placed-card and renderable-author geometry.

    Empty input yields empty bounds.  ``author_objects`` is keyword-only so
    historical card-only callers retain their exact public call shape.
    """
    union = GridBounds(0, 0, 0, 0)
    for item in placements:
        if isinstance(item, GridBounds):
            union = union.union(item)
        elif isinstance(item, GridRect):
            union = union.union(GridBounds.from_rect(item))
        else:
            union = union.union(GridBounds.from_rect(item.rect))
    return union.union(author_content_bounds(author_objects))


def desired_extent(
    content: GridBounds,
    viewport_size_px: tuple[float, float],
    cell_pitch: tuple[float, float],
    zoom: float = 1.0,
) -> GridBounds:
    """Base frame ∪ content ∪ viewport halo, snapped outward in 4-cell chunks.

    Halo on each side is ``max(4 cells, 0.5 × current viewport in cells)``.
    The result is clamped to the engineering safety bounds.
    """
    try:
        scale = float(zoom)
    except (TypeError, ValueError):
        scale = 1.0
    if not math.isfinite(scale) or scale <= 0.0:
        scale = 1.0
    width_px, height_px = (float(viewport_size_px[0]), float(viewport_size_px[1]))
    pitch_x, pitch_y = (float(cell_pitch[0]), float(cell_pitch[1]))
    halo_cols = _halo_cells(width_px, pitch_x, scale)
    halo_rows = _halo_cells(height_px, pitch_y, scale)
    core = base_frame_bounds().union(content)
    column, column_end = _expand_axis(
        core.column,
        core.column_end,
        halo_cols,
        EXTENT_CHUNK_COLUMNS,
        SAFETY_COLUMN_MIN,
        SAFETY_COLUMN_MAX,
    )
    row, row_end = _expand_axis(
        core.row,
        core.row_end,
        halo_rows,
        EXTENT_CHUNK_ROWS,
        SAFETY_ROW_MIN,
        SAFETY_ROW_MAX,
    )
    return GridBounds.from_edges(column, row, column_end, row_end)


def expand_extent(current: GridBounds, desired: GridBounds) -> GridBounds:
    """Session high-water mark: union that only grows, never escapes safety.

    ``current`` is session-only state owned by the Page.  It normally already
    comes from :func:`desired_extent`, but re-clamping here makes the pure
    safety contract survive a stale or corrupt high-water value as well.
    """
    current = _clamp_bounds_to_safety(current)
    desired = _clamp_bounds_to_safety(desired)
    if current.empty():
        return desired
    if desired.empty():
        return current
    return _clamp_bounds_to_safety(current.union(desired))


def edge_pan_velocity(
    local_pos: tuple[float, float],
    viewport_size: tuple[float, float],
    band_px: float = EDGE_PAN_BAND_PX,
) -> tuple[float, float]:
    """Return ``(vx, vy)`` px/tick for an in-widget pointer.

    The 72 px activation band is independent per axis. Speed is 4 px/tick at
    the inner face of the band and 22 px/tick at the widget edge. Pointers
    outside the widget or outside the band yield 0.
    """
    return (
        _axis_velocity(local_pos[0], viewport_size[0], band_px),
        _axis_velocity(local_pos[1], viewport_size[1], band_px),
    )


def _halo_cells(viewport_px: float, pitch: float, zoom: float) -> float:
    cell = pitch * zoom
    if not math.isfinite(cell) or cell <= 0.0:
        return float(HALO_MIN_CELLS)
    viewport_cells = max(0.0, float(viewport_px)) / cell
    return max(float(HALO_MIN_CELLS), 0.5 * viewport_cells)


def _clamp_bounds_to_safety(bounds: GridBounds) -> GridBounds:
    """Intersect an extent with the non-persistent engineering guard."""
    safety = safety_grid_bounds()
    column = max(safety.column, bounds.column)
    row = max(safety.row, bounds.row)
    column_end = min(safety.column_end, bounds.column_end)
    row_end = min(safety.row_end, bounds.row_end)
    if column_end <= column or row_end <= row:
        return GridBounds(0, 0, 0, 0)
    return GridBounds.from_edges(column, row, column_end, row_end)


def _expand_axis(
    start: int,
    end: int,
    halo: float,
    chunk: int,
    limit_min: int,
    limit_max: int,
) -> tuple[int, int]:
    chunk = max(1, int(chunk))
    raw_start = float(start) - float(halo)
    raw_end = float(end) + float(halo)
    chunked_start = int(math.floor(raw_start / chunk) * chunk)
    chunked_end = int(math.ceil(raw_end / chunk) * chunk)
    return max(limit_min, chunked_start), min(limit_max, chunked_end)


def _axis_velocity(pos: float, size: float, band: float) -> float:
    try:
        coord = float(pos)
        length = float(size)
        width = float(band)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(coord) or not math.isfinite(length) or length <= 0.0:
        return 0.0
    if not math.isfinite(width) or width <= 0.0:
        return 0.0
    if coord < 0.0 or coord > length:
        return 0.0
    speed_span = EDGE_PAN_SPEED_MAX - EDGE_PAN_SPEED_MIN
    velocity = 0.0
    left_depth = width - coord
    if left_depth > 0.0:
        t = min(1.0, left_depth / width)
        velocity -= EDGE_PAN_SPEED_MIN + t * speed_span
    right_depth = coord - (length - width)
    if right_depth > 0.0:
        t = min(1.0, right_depth / width)
        velocity += EDGE_PAN_SPEED_MIN + t * speed_span
    return velocity


__all__ = [
    "EDGE_PAN_BAND_PX",
    "EDGE_PAN_SPEED_MAX",
    "EDGE_PAN_SPEED_MIN",
    "EXTENT_CHUNK_COLUMNS",
    "EXTENT_CHUNK_ROWS",
    "HALO_MIN_CELLS",
    "AUTHOR_INK_BOUNDS_INFLATE",
    "author_content_bounds",
    "content_bounds",
    "desired_extent",
    "edge_pan_velocity",
    "expand_extent",
    "base_frame_bounds",
    "safety_grid_bounds",
]
