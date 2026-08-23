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
from dataclasses import dataclass

from mf4_analyzer.ui.ultraview_state import (
    GridBounds,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
)

from .free_grid import GridMetrics

STROKE_MIN_SCREEN_PX = 1.5
STROKE_RDP_SCREEN_PX = 0.75
# 100% micro-cell pitch used by the zoom-independent eraser corridor.
ERASER_CANONICAL_CELL_PX = 120.0
ERASER_MIN_CORRIDOR_BOARD = 0.2
LASSO_MIN_SPAN = 0.35
_SAFETY_X_MAX = SAFETY_COLUMN_MAX - 1e-9
_SAFETY_Y_MAX = SAFETY_ROW_MAX - 1e-9


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


def clamp_stroke_point(point: BoardPoint) -> BoardPoint | None:
    """Keep a finite sample inside the half-open safety area, or drop it."""
    parsed = _finite_point(point)
    if parsed is None:
        return None
    x = min(max(parsed[0], float(SAFETY_COLUMN_MIN)), _SAFETY_X_MAX)
    y = min(max(parsed[1], float(SAFETY_ROW_MIN)), _SAFETY_Y_MAX)
    return (x, y)


def filter_stroke_samples(
    points: Iterable[BoardPoint],
    metrics: GridMetrics,
    *,
    min_screen_px: float = STROKE_MIN_SCREEN_PX,
    dpr: float = 1.0,
) -> tuple[BoardPoint, ...]:
    """Drop samples closer than ``min_screen_px`` after zoom and DPR scaling.

    Distance is measured in device pixels: ``board_delta * pitch * dpr``.
    The first finite point is always kept.  Adjacent exact duplicates collapse.
    """
    geometry = _mapping_geometry(metrics)
    if geometry is None:
        return tuple(
            parsed
            for parsed in (_finite_point(point) for point in points)
            if parsed is not None
        )
    _padding, pitch_x, pitch_y = geometry
    scale = _finite_positive(dpr) or 1.0
    threshold = _finite_nonnegative(min_screen_px)
    if threshold is None:
        threshold = STROKE_MIN_SCREEN_PX
    kept: list[BoardPoint] = []
    for point in points:
        parsed = _finite_point(point)
        if parsed is None:
            continue
        if not kept:
            kept.append(parsed)
            continue
        last = kept[-1]
        if parsed == last:
            continue
        dx_px = (parsed[0] - last[0]) * pitch_x * scale
        dy_px = (parsed[1] - last[1]) * pitch_y * scale
        if math.hypot(dx_px, dy_px) < threshold:
            continue
        kept.append(parsed)
    return tuple(kept)


def persist_stroke_points(
    points: Iterable[BoardPoint],
    metrics: GridMetrics,
    *,
    dpr: float = 1.0,
    max_points: int = 2048,
    rdp_screen_px: float = STROKE_RDP_SCREEN_PX,
) -> tuple[BoardPoint, ...]:
    """Clamp, 1.5 px filter, then deterministic RDP. Empty/1-point strokes vanish."""
    clamped: list[BoardPoint] = []
    for point in points:
        parsed = clamp_stroke_point(point)
        if parsed is not None:
            clamped.append(parsed)
    filtered = filter_stroke_samples(clamped, metrics, dpr=dpr)
    radii = screen_px_tolerance_to_board(rdp_screen_px, metrics)
    tolerance = min(radii)
    simplified = simplify_stroke(filtered, tolerance=tolerance, max_points=max_points)
    if len(simplified) < 2:
        return ()
    return simplified


def stroke_ink_bounds(
    points: Iterable[BoardPoint],
    width_px_100: float,
    metrics: GridMetrics,
) -> GridBounds:
    """Axis-aligned Board bounds covering the polyline, round caps, and width."""
    parsed = [item for item in (clamp_stroke_point(point) for point in points) if item is not None]
    try:
        width = max(0.0, float(width_px_100))
    except (TypeError, ValueError):
        width = 0.0
    pitch_x, pitch_y = (1.0, 1.0)
    geometry = _mapping_geometry(metrics)
    if geometry is not None:
        _padding, pitch_x, pitch_y = geometry
    half = width / 2.0
    inflate_x = half / pitch_x if pitch_x else 0.0
    inflate_y = half / pitch_y if pitch_y else 0.0
    return geometry_grid_bounds(points=parsed, inflate=max(inflate_x, inflate_y))


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


HANDLE_HIT_PX = 18
HANDLE_VISUAL_PX = 10
HANDLE_NAMES = ("nw", "n", "ne", "w", "e", "sw", "s", "se")
_HANDLE_CORNERS = ("nw", "ne", "sw", "se")
CORNER_HANDLES = frozenset(_HANDLE_CORNERS)
SQUARE_SNAP_ENTER_PX = 8.0
SQUARE_SNAP_EXIT_PX = 12.0


def handle_hit_rects(
    box_px: BoardBox, hit: int = HANDLE_HIT_PX
) -> dict[str, tuple[int, int, int, int]]:
    """Axis-aligned 8-handle hit zones. Corners are ``hit×hit`` and take priority."""
    x, y, width, height = (
        int(box_px[0]),
        int(box_px[1]),
        int(box_px[2]),
        int(box_px[3]),
    )
    zone = max(HANDLE_HIT_PX, int(hit))
    inner_w = max(1, width - 2 * zone)
    inner_h = max(1, height - 2 * zone)
    return {
        "nw": (x, y, zone, zone),
        "n": (x + zone, y, inner_w, zone),
        "ne": (x + width - zone, y, zone, zone),
        "w": (x, y + zone, zone, inner_h),
        "e": (x + width - zone, y + zone, zone, inner_h),
        "sw": (x, y + height - zone, zone, zone),
        "s": (x + zone, y + height - zone, inner_w, zone),
        "se": (x + width - zone, y + height - zone, zone, zone),
    }


def hit_box_handle(
    box_px: BoardBox, pos: tuple[int, int], hit: int = HANDLE_HIT_PX
) -> str | None:
    """Return the author resize handle under a pixel point, or ``None``."""
    px, py = int(pos[0]), int(pos[1])
    zones = handle_hit_rects(box_px, hit)
    for name in _HANDLE_CORNERS:
        x, y, width, height = zones[name]
        if x <= px < x + width and y <= py < y + height:
            return name
    for name in ("n", "s", "w", "e"):
        x, y, width, height = zones[name]
        if x <= px < x + width and y <= py < y + height:
            return name
    return None


def _box_anchor(box: BoardBox, handle: str) -> BoardPoint:
    x, y, width, height = box
    ax = x + width if "w" in handle else x
    ay = y + height if "n" in handle else y
    return (ax, ay)


def _box_from_anchor(anchor: BoardPoint, handle: str, width: float, height: float) -> BoardBox:
    ax, ay = anchor
    x = ax - width if "w" in handle else ax
    y = ay - height if "n" in handle else ay
    return (x, y, width, height)


def resize_box_unclamped(
    box: BoardBox, handle: str, dx: float, dy: float
) -> BoardBox:
    """Move the named edges; width and height stay non-negative."""
    x, y, width, height = box
    x2, y2 = x + width, y + height
    if "w" in handle:
        x = x + dx
    if "e" in handle:
        x2 = x2 + dx
    if "n" in handle:
        y = y + dy
    if "s" in handle:
        y2 = y2 + dy
    return (min(x, x2), min(y, y2), abs(x2 - x), abs(y2 - y))


def apply_square_snap(
    original: BoardBox,
    candidate: BoardBox,
    handle: str,
    *,
    pitch_x: float,
    pitch_y: float,
    snapped: bool,
    bypass: bool,
) -> tuple[BoardBox, bool]:
    """Snap a corner resize to a visually square rect using screen-logical pixels.

    Edge midpoints never snap. Enter at ``SQUARE_SNAP_ENTER_PX``, leave at
    ``SQUARE_SNAP_EXIT_PX``. The fixed opposite corner stays the anchor.
    """
    if bypass or handle not in CORNER_HANDLES:
        return candidate, False
    px = float(pitch_x) if math.isfinite(float(pitch_x)) and float(pitch_x) > 0.0 else 1.0
    py = float(pitch_y) if math.isfinite(float(pitch_y)) and float(pitch_y) > 0.0 else 1.0
    _cx, _cy, cand_w, cand_h = candidate
    width_px = abs(float(cand_w)) * px
    height_px = abs(float(cand_h)) * py
    delta = abs(width_px - height_px)
    if snapped:
        still = delta <= SQUARE_SNAP_EXIT_PX + 1e-9
    else:
        still = delta <= SQUARE_SNAP_ENTER_PX + 1e-9
    if not still:
        return candidate, False
    side_px = max(width_px, height_px)
    new_w = side_px / px
    new_h = side_px / py
    return _box_from_anchor(_box_anchor(original, handle), handle, new_w, new_h), True


def resize_box_candidate(
    box: BoardBox,
    handle: str,
    dx: float,
    dy: float,
    *,
    pitch_x: float = 1.0,
    pitch_y: float = 1.0,
    square_snap: bool = False,
    snapped: bool = False,
    bypass: bool = False,
) -> tuple[BoardBox, bool]:
    """Shared preview/commit candidate. Caller applies min-size and board clamp."""
    candidate = resize_box_unclamped(box, handle, dx, dy)
    if not square_snap:
        return candidate, False
    return apply_square_snap(
        box,
        candidate,
        handle,
        pitch_x=pitch_x,
        pitch_y=pitch_y,
        snapped=snapped,
        bypass=bypass,
    )


CONNECTOR_ANCHORS = ("n", "e", "s", "w")


def box_side_points(box: BoardBox) -> dict[str, BoardPoint]:
    """Return N/E/S/W outline midpoints for a Board box."""
    parsed = _finite_box(box)
    if parsed is None:
        return {}
    x, y, width, height = parsed
    center_x = x + width / 2.0
    center_y = y + height / 2.0
    return {
        "n": (center_x, y),
        "e": (x + width, center_y),
        "s": (center_x, y + height),
        "w": (x, center_y),
    }


def auto_box_side(box: BoardBox, toward: BoardPoint) -> str:
    """Pick the outline side that faces ``toward`` without searching obstacles."""
    parsed = _finite_box(box)
    probe = _finite_point(toward)
    if parsed is None or probe is None:
        return "e"
    x, y, width, height = parsed
    dx = probe[0] - (x + width / 2.0)
    dy = probe[1] - (y + height / 2.0)
    if abs(dx) * height >= abs(dy) * width:
        return "e" if dx >= 0.0 else "w"
    return "s" if dy >= 0.0 else "n"


def box_anchor_point(
    box: BoardBox, anchor: str, toward: BoardPoint | None = None
) -> BoardPoint | None:
    """Resolve auto/N/E/S/W onto the outline. Display labels are not used."""
    parsed = _finite_box(box)
    if parsed is None:
        return None
    side = str(anchor or "auto")
    if side == "auto":
        fallback = (parsed[0] + parsed[2] + 1.0, parsed[1] + parsed[3] / 2.0)
        side = auto_box_side(parsed, toward if toward is not None else fallback)
    points = box_side_points(parsed)
    return points.get(side)


def point_on_box_outline(
    box: BoardBox, point: BoardPoint, *, epsilon: float = 1e-6
) -> bool:
    """True when ``point`` lies on the box outline within ``epsilon``."""
    parsed = _finite_box(box)
    probe = _finite_point(point)
    if parsed is None or probe is None:
        return False
    x, y, width, height = parsed
    px, py = probe
    on_vertical = (
        abs(px - x) <= epsilon or abs(px - (x + width)) <= epsilon
    ) and (y - epsilon) <= py <= (y + height + epsilon)
    on_horizontal = (
        abs(py - y) <= epsilon or abs(py - (y + height)) <= epsilon
    ) and (x - epsilon) <= px <= (x + width + epsilon)
    return on_vertical or on_horizontal


def constrain_shift_point(origin: BoardPoint, current: BoardPoint) -> BoardPoint:
    """Constrain ``current`` to horizontal, vertical, or 45° from ``origin``."""
    start = _finite_point(origin)
    probe = _finite_point(current)
    if start is None or probe is None:
        return current
    dx = probe[0] - start[0]
    dy = probe[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        return probe
    snapped = round(math.atan2(dy, dx) / (math.pi / 4.0)) * (math.pi / 4.0)
    return (start[0] + length * math.cos(snapped), start[1] + length * math.sin(snapped))


def elbow_path(
    start: BoardPoint, end: BoardPoint, bias: float = 0.5
) -> tuple[BoardPoint, ...]:
    """Deterministic orthogonal H-V or V-H path. No obstacle routing."""
    first = _finite_point(start)
    last = _finite_point(end)
    if first is None or last is None:
        return ()
    if first == last:
        return (first, last)
    amount = 0.5 if _finite_nonnegative(bias) is None else min(1.0, max(0.0, float(bias)))
    if abs(last[0] - first[0]) >= abs(last[1] - first[1]):
        middle = (first[0] + (last[0] - first[0]) * amount, first[1])
        corner = (middle[0], last[1])
    else:
        middle = (first[0], first[1] + (last[1] - first[1]) * amount)
        corner = (last[0], middle[1])
    return (first, middle, corner, last)


def connector_route_points(
    start: BoardPoint,
    end: BoardPoint,
    route: str = "straight",
    elbow_bias: float | None = None,
) -> tuple[BoardPoint, ...]:
    """Return the persisted connector polyline for ``straight`` or ``elbow``."""
    first = _finite_point(start)
    last = _finite_point(end)
    if first is None or last is None:
        return ()
    if str(route) != "elbow" or first == last:
        return (first, last)
    return elbow_path(first, last, 0.5 if elbow_bias is None else float(elbow_bias))


def _connector_corridor(stroke_width: object) -> float:
    try:
        width = float(stroke_width)
    except (TypeError, ValueError):
        width = 1.0
    return max(0.35, max(1.0, width) * 0.12)


def hit_connector(
    start: BoardPoint,
    end: BoardPoint,
    probe: BoardPoint,
    *,
    route: str = "straight",
    stroke_width: int = 1,
    start_head: str = "none",
    end_head: str = "none",
    elbow_bias: float | None = None,
    radius: float | None = None,
) -> bool:
    """True when ``probe`` hits the polyline, stroke corridor, or arrowhead."""
    point = _finite_point(probe)
    points = connector_route_points(start, end, route, elbow_bias)
    if point is None or len(points) < 2:
        return False
    corridor = _connector_corridor(stroke_width) if radius is None else max(0.0, float(radius))
    for index in range(len(points) - 1):
        if _segment_distance_sq(point, points[index], points[index + 1]) <= corridor * corridor:
            return True
    head = corridor * 2.5
    if end_head == "arrow" and _segment_distance_sq(point, points[-1], points[-1]) <= head * head:
        return True
    if start_head == "arrow" and _segment_distance_sq(point, points[0], points[0]) <= head * head:
        return True
    return False


def connector_hit_bounds(
    start: BoardPoint,
    end: BoardPoint,
    *,
    route: str = "straight",
    stroke_width: int = 1,
    start_head: str = "none",
    end_head: str = "none",
    elbow_bias: float | None = None,
) -> BoardBox:
    """Axis-aligned bounds covering the route, stroke, and arrowheads."""
    points = connector_route_points(start, end, route, elbow_bias)
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    inflate = _connector_corridor(stroke_width)
    if start_head == "arrow" or end_head == "arrow":
        inflate = max(inflate, 0.8)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (
        min(xs) - inflate,
        min(ys) - inflate,
        max(xs) - min(xs) + 2.0 * inflate,
        max(ys) - min(ys) + 2.0 * inflate,
    )


def connection_anchor_hit_rects(
    box_px: BoardBox, hit: int = HANDLE_HIT_PX
) -> dict[str, tuple[int, int, int, int]]:
    """18 px N/E/S/W connection-anchor hit zones on a pixel box."""
    x, y, width, height = (
        int(box_px[0]),
        int(box_px[1]),
        int(box_px[2]),
        int(box_px[3]),
    )
    zone = max(HANDLE_HIT_PX, int(hit))
    half = zone // 2
    anchors = {
        "n": (x + width // 2, y),
        "e": (x + width, y + height // 2),
        "s": (x + width // 2, y + height),
        "w": (x, y + height // 2),
    }
    return {
        name: (ax - half, ay - half, zone, zone) for name, (ax, ay) in anchors.items()
    }


def hit_connection_anchor(
    box_px: BoardBox, pos: tuple[int, int], hit: int = HANDLE_HIT_PX
) -> str | None:
    """Return ``n``/``e``/``s``/``w`` when a connection anchor is under ``pos``."""
    px, py = int(pos[0]), int(pos[1])
    for name, (x, y, width, height) in connection_anchor_hit_rects(box_px, hit).items():
        if x <= px < x + width and y <= py < y + height:
            return name
    return None


def connector_handle_points(
    start: BoardPoint,
    end: BoardPoint,
    *,
    route: str = "straight",
    elbow_bias: float | None = None,
) -> dict[str, BoardPoint]:
    """Start/end handles plus the single Elbow control, in Board units."""
    points = connector_route_points(start, end, route, elbow_bias)
    if len(points) < 2:
        return {}
    handles = {"start": points[0], "end": points[-1]}
    if str(route) == "elbow" and len(points) >= 3:
        handles["elbow"] = points[1]
    return handles


def hit_connector_handle(
    handles_px: dict[str, BoardPoint],
    pos: tuple[int, int],
    hit: int = HANDLE_HIT_PX,
) -> str | None:
    """Hit-test endpoint/control handles. These sit above object hit."""
    px, py = int(pos[0]), int(pos[1])
    zone = max(HANDLE_HIT_PX, int(hit))
    half = zone // 2
    for name in ("start", "end", "elbow"):
        point = handles_px.get(name)
        if point is None:
            continue
        x = int(round(point[0])) - half
        y = int(round(point[1])) - half
        if x <= px < x + zone and y <= py < y + zone:
            return name
    return None


def eraser_corridor_board(width_px_100: object) -> float:
    """Board-unit hit radius for whole-stroke erase. Independent of zoom/DPR."""
    try:
        width = max(0.0, float(width_px_100))
    except (TypeError, ValueError):
        width = 0.0
    half = (width / 2.0) / ERASER_CANONICAL_CELL_PX
    return max(ERASER_MIN_CORRIDOR_BOARD, half)


@dataclass(frozen=True)
class StrokeHitRecord:
    """AABB + polyline for one persisted stroke. Owned by author geometry."""

    object_id: str
    points: tuple[BoardPoint, ...]
    radius: float
    min_x: float
    min_y: float
    max_x: float
    max_y: float


def stroke_hit_record(
    object_id: str,
    points: Iterable[BoardPoint],
    width_px_100: object = 2,
) -> StrokeHitRecord | None:
    """Build one zoom-independent hit record. Callers skip locked/non-strokes."""
    parsed = tuple(
        item for item in (_finite_point(point) for point in points) if item is not None
    )
    if len(parsed) < 2:
        return None
    ident = str(object_id or "").strip()
    if not ident:
        return None
    radius = eraser_corridor_board(width_px_100)
    xs = [point[0] for point in parsed]
    ys = [point[1] for point in parsed]
    return StrokeHitRecord(
        ident,
        parsed,
        radius,
        min(xs) - radius,
        min(ys) - radius,
        max(xs) + radius,
        max(ys) + radius,
    )


def hit_stroke(record: StrokeHitRecord, probe: BoardPoint) -> bool:
    """True when ``probe`` sits in the stroke corridor."""
    point = _finite_point(probe)
    if point is None:
        return False
    px, py = point
    if px < record.min_x or px > record.max_x or py < record.min_y or py > record.max_y:
        return False
    radius_sq = record.radius * record.radius
    points = record.points
    for index in range(len(points) - 1):
        if _segment_distance_sq(point, points[index], points[index + 1]) <= radius_sq:
            return True
    return False


def strokes_hit_by_segment(
    records: Iterable[StrokeHitRecord],
    start: BoardPoint,
    end: BoardPoint,
) -> tuple[str, ...]:
    """Return ids whose segment corridor the eraser segment crosses.

    Tests the eraser *segment* against each stroke *segment*. Sample-point
    proximity alone is not enough for a fast crossing between sparse events.
    """
    first = _finite_point(start)
    last = _finite_point(end)
    if first is None or last is None:
        return ()
    hits: list[str] = []
    seen: set[str] = set()
    for record in records:
        if record.object_id in seen:
            continue
        if not _segment_overlaps_record_aabb(first, last, record):
            continue
        if _polyline_hits_segment(record.points, first, last, record.radius):
            seen.add(record.object_id)
            hits.append(record.object_id)
    return tuple(hits)


def box_center(box: BoardBox) -> BoardPoint | None:
    parsed = _finite_box(box)
    if parsed is None:
        return None
    x, y, width, height = parsed
    return (x + width / 2.0, y + height / 2.0)


def polyline_center(points: Iterable[BoardPoint]) -> BoardPoint | None:
    parsed = [item for item in (_finite_point(point) for point in points) if item is not None]
    if not parsed:
        return None
    xs = [point[0] for point in parsed]
    ys = [point[1] for point in parsed]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def lasso_is_usable(path: Iterable[BoardPoint]) -> bool:
    """Reject empty, 1–2 point, and click-sized paths. Self-intersection is ok."""
    parsed = [item for item in (_finite_point(point) for point in path) if item is not None]
    unique: list[BoardPoint] = []
    for point in parsed:
        if not unique or point != unique[-1]:
            unique.append(point)
    if len(unique) < 3:
        return False
    xs = [point[0] for point in unique]
    ys = [point[1] for point in unique]
    return (max(xs) - min(xs) >= LASSO_MIN_SPAN) or (max(ys) - min(ys) >= LASSO_MIN_SPAN)


def point_in_lasso(point: BoardPoint, path: Iterable[BoardPoint]) -> bool:
    """Even-odd inclusion. Unclosed paths close implicitly; self-crossing is valid."""
    probe = _finite_point(point)
    ring = [item for item in (_finite_point(vertex) for vertex in path) if item is not None]
    if probe is None or len(ring) < 3:
        return False
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    x, y = probe
    inside = False
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        if (y1 > y) != (y2 > y):
            at = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < at:
                inside = not inside
    return inside


def _segment_overlaps_record_aabb(
    start: BoardPoint, end: BoardPoint, record: StrokeHitRecord
) -> bool:
    min_x = min(start[0], end[0])
    max_x = max(start[0], end[0])
    min_y = min(start[1], end[1])
    max_y = max(start[1], end[1])
    return not (
        max_x < record.min_x
        or min_x > record.max_x
        or max_y < record.min_y
        or min_y > record.max_y
    )


def _polyline_hits_segment(
    points: tuple[BoardPoint, ...],
    start: BoardPoint,
    end: BoardPoint,
    radius: float,
) -> bool:
    for index in range(len(points) - 1):
        if _segments_within_corridor(start, end, points[index], points[index + 1], radius):
            return True
    return False


def _segments_within_corridor(
    a0: BoardPoint,
    a1: BoardPoint,
    b0: BoardPoint,
    b1: BoardPoint,
    radius: float,
) -> bool:
    if _segments_intersect(a0, a1, b0, b1):
        return True
    limit = max(0.0, float(radius))
    limit_sq = limit * limit
    return (
        _segment_distance_sq(a0, b0, b1) <= limit_sq
        or _segment_distance_sq(a1, b0, b1) <= limit_sq
        or _segment_distance_sq(b0, a0, a1) <= limit_sq
        or _segment_distance_sq(b1, a0, a1) <= limit_sq
    )


def _segments_intersect(
    a0: BoardPoint, a1: BoardPoint, b0: BoardPoint, b1: BoardPoint
) -> bool:
    d1 = _orientation(a0, a1, b0)
    d2 = _orientation(a0, a1, b1)
    d3 = _orientation(b0, b1, a0)
    d4 = _orientation(b0, b1, a1)
    return (d1 > 0.0) != (d2 > 0.0) and (d3 > 0.0) != (d4 > 0.0)


def _orientation(start: BoardPoint, end: BoardPoint, probe: BoardPoint) -> float:
    return (end[0] - start[0]) * (probe[1] - start[1]) - (end[1] - start[1]) * (
        probe[0] - start[0]
    )


__all__ = [
    "BoardBox",
    "BoardPoint",
    "CONNECTOR_ANCHORS",
    "CORNER_HANDLES",
    "HANDLE_HIT_PX",
    "HANDLE_NAMES",
    "HANDLE_VISUAL_PX",
    "SQUARE_SNAP_ENTER_PX",
    "SQUARE_SNAP_EXIT_PX",
    "LATTICE_STEP",
    "apply_square_snap",
    "auto_box_side",
    "board_box_to_pixels",
    "board_point_to_pixels",
    "box_anchor_point",
    "box_center",
    "box_side_points",
    "connection_anchor_hit_rects",
    "connector_handle_points",
    "connector_hit_bounds",
    "connector_route_points",
    "constrain_shift_point",
    "elbow_path",
    "eraser_corridor_board",
    "geometry_grid_bounds",
    "handle_hit_rects",
    "hit_box_handle",
    "hit_connection_anchor",
    "hit_connector",
    "hit_connector_handle",
    "hit_stroke",
    "lasso_is_usable",
    "pixels_to_board_box",
    "pixels_to_board_point",
    "point_in_lasso",
    "point_on_box_outline",
    "polyline_center",
    "resize_box_candidate",
    "resize_box_unclamped",
    "screen_px_tolerance_to_board",
    "simplify_stroke",
    "snap_board_point",
    "clamp_stroke_point",
    "filter_stroke_samples",
    "persist_stroke_points",
    "stroke_hit_record",
    "stroke_ink_bounds",
    "strokes_hit_by_segment",
    "StrokeHitRecord",
    "STROKE_MIN_SCREEN_PX",
    "STROKE_RDP_SCREEN_PX",
    "ERASER_CANONICAL_CELL_PX",
    "ERASER_MIN_CORRIDOR_BOARD",
    "LASSO_MIN_SPAN",
]
