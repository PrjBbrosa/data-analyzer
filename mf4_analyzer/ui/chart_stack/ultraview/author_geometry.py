"""Qt-free geometry primitives for UltraView author-created Board objects.

Author coordinates use the canonical schema-5 micro-grid, but remain floats:
one coordinate unit is one micro-cell.  This module deliberately knows no
author-object DTOs and no Qt painting classes.  State normalization decides
which objects are valid; renderers and interaction code consume the precise
mapping and conservative grid bounds defined here.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

from mf4_analyzer.ui.ultraview_state import GridBounds

from .free_grid import GridMetrics


BoardPoint = tuple[float, float]
"""A floating Board coordinate in canonical micro-cell units."""

BoardBox = tuple[float, float, float, float]
"""A floating Board box as ``(x, y, width, height)`` in Board units."""

LATTICE_STEP = 0.25


def snap_board_point(
    point: BoardPoint, *, lattice: float = LATTICE_STEP
) -> BoardPoint | None:
    """Snap a finite point to a lattice with half-away-from-zero ties.

    ``None`` is returned for malformed/non-finite input or a non-positive
    lattice.  Returning no point is safer for the state/gesture boundary than
    silently introducing a fabricated location such as the Board origin.
    """
    parsed = _finite_point(point)
    step = _finite_positive(lattice)
    if parsed is None or step is None:
        return None
    return (_snap_scalar(parsed[0], step), _snap_scalar(parsed[1], step))


def board_point_to_pixels(
    point: BoardPoint,
    metrics: GridMetrics,
    *,
    origin_offset: BoardPoint = (0.0, 0.0),
) -> BoardPoint | None:
    """Map a Board point to a precise pixel point.

    The caller performs any final integer rounding.  Like the card map, this
    uses ``GridMetrics.exact_*`` values and therefore never multiplies an
    already-rounded pitch by a signed elastic cell index.
    """
    parsed = _finite_point(point)
    origin = _finite_point(origin_offset)
    geometry = _mapping_geometry(metrics)
    if parsed is None or origin is None or geometry is None:
        return None
    padding, pitch_x, pitch_y = geometry
    return (
        padding + (parsed[0] - origin[0]) * pitch_x,
        padding + (parsed[1] - origin[1]) * pitch_y,
    )


def pixels_to_board_point(
    pixel: BoardPoint,
    metrics: GridMetrics,
    *,
    origin_offset: BoardPoint = (0.0, 0.0),
) -> BoardPoint | None:
    """Inverse of :func:`board_point_to_pixels` for finite inputs."""
    parsed = _finite_point(pixel)
    origin = _finite_point(origin_offset)
    geometry = _mapping_geometry(metrics)
    if parsed is None or origin is None or geometry is None:
        return None
    padding, pitch_x, pitch_y = geometry
    return (
        origin[0] + (parsed[0] - padding) / pitch_x,
        origin[1] + (parsed[1] - padding) / pitch_y,
    )


def board_box_to_pixels(
    box: BoardBox,
    metrics: GridMetrics,
    *,
    origin_offset: BoardPoint = (0.0, 0.0),
) -> BoardBox | None:
    """Map a floating ``(x, y, width, height)`` Board box to pixels.

    The mapping is continuous: a width of one Board unit occupies one exact
    micro-cell pitch.  This is intentionally different from ``GridRect``'s
    reading-card geometry, whose visible card body omits the inter-card gutter.
    """
    parsed = _finite_box(box)
    if parsed is None:
        return None
    x, y, width, height = parsed
    start = board_point_to_pixels((x, y), metrics, origin_offset=origin_offset)
    end = board_point_to_pixels(
        (x + width, y + height), metrics, origin_offset=origin_offset
    )
    if start is None or end is None:
        return None
    return (start[0], start[1], end[0] - start[0], end[1] - start[1])


def pixels_to_board_box(
    box: BoardBox,
    metrics: GridMetrics,
    *,
    origin_offset: BoardPoint = (0.0, 0.0),
) -> BoardBox | None:
    """Inverse continuous mapping for a pixel ``(x, y, width, height)`` box."""
    parsed = _finite_box(box)
    if parsed is None:
        return None
    x, y, width, height = parsed
    start = pixels_to_board_point((x, y), metrics, origin_offset=origin_offset)
    end = pixels_to_board_point(
        (x + width, y + height), metrics, origin_offset=origin_offset
    )
    if start is None or end is None:
        return None
    return (start[0], start[1], end[0] - start[0], end[1] - start[1])


def screen_px_tolerance_to_board(
    pixels: float, metrics: GridMetrics
) -> BoardPoint:
    """Convert a screen-pixel tolerance into independent Board-unit radii.

    Invalid/negative values have no hit extent and return ``(0.0, 0.0)``.
    This makes a 6 px guide or stroke corridor track zoom without giving a
    malformed zoom calculation an unbounded Board hit region.
    """
    amount = _finite_nonnegative(pixels)
    geometry = _mapping_geometry(metrics)
    if amount is None or geometry is None:
        return (0.0, 0.0)
    _padding, pitch_x, pitch_y = geometry
    return (amount / pitch_x, amount / pitch_y)


def geometry_grid_bounds(
    *,
    points: Iterable[BoardPoint] = (),
    boxes: Iterable[BoardBox] = (),
    inflate: float = 0.0,
) -> GridBounds:
    """Return outward-rounded signed bounds for finite points and boxes.

    Boxes accept negative widths/heights and are normalized through their two
    corners.  Degenerate finite geometry still occupies its containing
    micro-cell, while empty or entirely non-finite input returns empty bounds.
    ``inflate`` is a Board-unit radius (for example a stroke half-width).
    """
    radius = _finite_nonnegative(inflate)
    if radius is None:
        radius = 0.0
    min_x: float | None = None
    min_y: float | None = None
    max_x: float | None = None
    max_y: float | None = None

    def include(x0: float, y0: float, x1: float, y1: float) -> None:
        nonlocal min_x, min_y, max_x, max_y
        left, right = sorted((x0 - radius, x1 + radius))
        top, bottom = sorted((y0 - radius, y1 + radius))
        min_x = left if min_x is None else min(min_x, left)
        min_y = top if min_y is None else min(min_y, top)
        max_x = right if max_x is None else max(max_x, right)
        max_y = bottom if max_y is None else max(max_y, bottom)

    for point in points:
        parsed = _finite_point(point)
        if parsed is not None:
            include(parsed[0], parsed[1], parsed[0], parsed[1])
    for box in boxes:
        parsed = _finite_box(box)
        if parsed is not None:
            x, y, width, height = parsed
            include(x, y, x + width, y + height)

    if min_x is None or min_y is None or max_x is None or max_y is None:
        return GridBounds(0, 0, 0, 0)
    column = math.floor(min_x)
    row = math.floor(min_y)
    column_end = math.ceil(max_x)
    row_end = math.ceil(max_y)
    # A zero-area finite point/box must still keep the Board extent and Fit
    # from treating visible author content as absent.
    if column_end <= column:
        column_end = column + 1
    if row_end <= row:
        row_end = row + 1
    return GridBounds.from_edges(column, row, column_end, row_end)


def simplify_stroke(
    points: Iterable[BoardPoint],
    *,
    tolerance: float,
    max_points: int = 2048,
) -> tuple[BoardPoint, ...]:
    """Return a deterministic Ramer-Douglas-Peucker simplification.

    Non-finite points are discarded, adjacent exact duplicates are collapsed,
    and the first/last valid points are retained whenever the result has two
    or more points.  A non-finite/negative tolerance becomes zero.  The hard
    cap is deterministic and also preserves endpoints.
    """
    normalized: list[BoardPoint] = []
    for point in points:
        parsed = _finite_point(point)
        if parsed is not None and (not normalized or parsed != normalized[-1]):
            normalized.append(parsed)
    if len(normalized) < 3:
        return tuple(normalized)

    error = _finite_nonnegative(tolerance)
    if error is None:
        error = 0.0
    simplified = _rdp(normalized, error)
    limit = max(2, int(max_points))
    if len(simplified) <= limit:
        return tuple(simplified)
    return tuple(_evenly_limited(simplified, limit))


def _mapping_geometry(metrics: GridMetrics) -> tuple[float, float, float] | None:
    try:
        padding = float(metrics.exact_padding())
        pitch_x, pitch_y = metrics.exact_pitch()
        pitch_x = float(pitch_x)
        pitch_y = float(pitch_y)
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        not math.isfinite(padding)
        or not math.isfinite(pitch_x)
        or not math.isfinite(pitch_y)
        or pitch_x <= 0.0
        or pitch_y <= 0.0
    ):
        return None
    return padding, pitch_x, pitch_y


def _finite_point(value: object) -> BoardPoint | None:
    try:
        x, y = value  # type: ignore[misc]
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return x, y


def _finite_box(value: object) -> BoardBox | None:
    try:
        x, y, width, height = value  # type: ignore[misc]
        x = float(x)
        y = float(y)
        width = float(width)
        height = float(height)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x, y, width, height)):
        return None
    return x, y, width, height


def _finite_positive(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _finite_nonnegative(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0.0:
        return None
    return number


def _snap_scalar(value: float, step: float) -> float:
    scaled = value / step
    if scaled >= 0.0:
        snapped = math.floor(scaled + 0.5)
    else:
        snapped = -math.floor(-scaled + 0.5)
    return float(snapped * step)


def _rdp(points: list[BoardPoint], tolerance: float) -> list[BoardPoint]:
    """Iterative RDP; equal-distance ties choose the earliest point."""
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    pending: list[tuple[int, int]] = [(0, len(points) - 1)]
    tolerance_sq = tolerance * tolerance
    while pending:
        start, end = pending.pop()
        index = -1
        max_distance_sq = -1.0
        first = points[start]
        last = points[end]
        for candidate in range(start + 1, end):
            distance_sq = _segment_distance_sq(points[candidate], first, last)
            if distance_sq > max_distance_sq:
                index = candidate
                max_distance_sq = distance_sq
        if index >= 0 and max_distance_sq > tolerance_sq:
            keep[index] = True
            pending.append((start, index))
            pending.append((index, end))
    return [point for index, point in enumerate(points) if keep[index]]


def _segment_distance_sq(point: BoardPoint, start: BoardPoint, end: BoardPoint) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        offset_x = point[0] - start[0]
        offset_y = point[1] - start[1]
        return offset_x * offset_x + offset_y * offset_y
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    projection = min(1.0, max(0.0, projection))
    closest_x = start[0] + projection * dx
    closest_y = start[1] + projection * dy
    offset_x = point[0] - closest_x
    offset_y = point[1] - closest_y
    return offset_x * offset_x + offset_y * offset_y


def _evenly_limited(points: list[BoardPoint], limit: int) -> list[BoardPoint]:
    if len(points) <= limit:
        return points
    last = len(points) - 1
    # Integer arithmetic avoids platform-dependent floating rounding.
    indexes = [(position * last) // (limit - 1) for position in range(limit)]
    return [points[index] for index in indexes]


__all__ = [
    "BoardBox",
    "BoardPoint",
    "LATTICE_STEP",
    "board_box_to_pixels",
    "board_point_to_pixels",
    "geometry_grid_bounds",
    "pixels_to_board_box",
    "pixels_to_board_point",
    "screen_px_tolerance_to_board",
    "simplify_stroke",
    "snap_board_point",
]
