"""DPR-aware Laser pointer cursor. Appearance only; not an author object.

Option B (2026-08-23): glowing disc, core 8 px, halo 20 px, hotspot at the
visual centre. Cache key is (DPR, logical size, palette version). The backing
pixmap is rasterized at native pixels, then tagged with ``setDevicePixelRatio``
so ``QCursor`` hotspots stay in the design's logical coordinates.
"""
from __future__ import annotations

import math

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QCursor, QPainter, QPixmap

from mf4_analyzer.ui_kit.icons import (
    LASER_DOT_CORE_DIAMETER,
    LASER_DOT_HALO_DIAMETER,
    paint_laser_glow,
)


LASER_CURSOR_DESIGN_SIZE = 32
LASER_CURSOR_LOGICAL_SIZE = LASER_CURSOR_DESIGN_SIZE
LASER_CURSOR_CORE_DIAMETER = LASER_DOT_CORE_DIAMETER
LASER_CURSOR_HALO_DIAMETER = LASER_DOT_HALO_DIAMETER
LASER_CURSOR_HOTSPOT = (
    LASER_CURSOR_DESIGN_SIZE // 2,
    LASER_CURSOR_DESIGN_SIZE // 2,
)
LASER_CURSOR_PALETTE_VERSION = 2
LASER_CURSOR_OPTION = "B"
LASER_CURSOR_DPR_CHANGE_EVENTS = frozenset(
    value
    for value in (
        getattr(QEvent, "ScreenChangeInternal", None),
        getattr(QEvent, "DevicePixelRatioChange", None),
    )
    if value is not None
)

_laser_cursor_cache: dict[tuple[float, int, int], QCursor] = {}


def _normalize_dpr(dpr: float) -> float:
    try:
        value = float(dpr)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(value) or value <= 0.0:
        return 1.0
    return round(max(1.0, value), 2)


def laser_cursor_cache_key(
    *,
    dpr: float,
    logical_size: int = LASER_CURSOR_LOGICAL_SIZE,
    palette_version: int = LASER_CURSOR_PALETTE_VERSION,
) -> tuple[float, int, int]:
    """Return the identity tuple for one Laser cursor raster."""
    size = int(logical_size)
    if size < 1:
        size = LASER_CURSOR_LOGICAL_SIZE
    return (_normalize_dpr(dpr), size, int(palette_version))


def clear_laser_cursor_cache() -> None:
    """Drop cached cursors so the next lookup rebuilds for the current screen."""
    _laser_cursor_cache.clear()


def laser_pointer_cursor(
    *,
    dpr: float = 1.0,
    logical_size: int = LASER_CURSOR_LOGICAL_SIZE,
    palette_version: int = LASER_CURSOR_PALETTE_VERSION,
) -> QCursor:
    """Return a cached glowing-dot cursor; it has no board overlay."""
    key = laser_cursor_cache_key(
        dpr=dpr,
        logical_size=logical_size,
        palette_version=palette_version,
    )
    cached = _laser_cursor_cache.get(key)
    if cached is not None:
        return cached
    cursor = _build_laser_cursor(dpr=key[0], logical_size=key[1])
    _laser_cursor_cache[key] = cursor
    return cursor


def _logical_hotspot(logical_size: int) -> QPoint:
    scale = float(logical_size) / float(LASER_CURSOR_DESIGN_SIZE)
    hot_x, hot_y = LASER_CURSOR_HOTSPOT
    return QPoint(int(round(hot_x * scale)), int(round(hot_y * scale)))


def _build_laser_cursor(*, dpr: float, logical_size: int) -> QCursor:
    native = max(1, int(round(float(logical_size) * dpr)))
    pixmap = QPixmap(native, native)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(
        dpr * float(logical_size) / float(LASER_CURSOR_DESIGN_SIZE),
        dpr * float(logical_size) / float(LASER_CURSOR_DESIGN_SIZE),
    )
    center = QPointF(
        LASER_CURSOR_DESIGN_SIZE / 2.0,
        LASER_CURSOR_DESIGN_SIZE / 2.0,
    )
    paint_laser_glow(
        painter,
        center,
        core_diameter=LASER_CURSOR_CORE_DIAMETER,
        halo_diameter=LASER_CURSOR_HALO_DIAMETER,
    )
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    hotspot = _logical_hotspot(logical_size)
    return QCursor(pixmap, hotspot.x(), hotspot.y())
