"""Shared QPainter renderer for persisted UltraView author objects.

The live free-grid layer and PNG compositor intentionally share this module:
it knows how to turn typed, Qt-free state DTOs into pixels, but owns neither
selection chrome nor input/edit widgets.  ``objects`` are painted in their
given order, which is the persisted author z-order contract.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from functools import lru_cache

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QPolygonF

from mf4_analyzer.ui.ultraview_state import (
    ConnectorObject,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
)

from .author_geometry import board_box_to_pixels, board_point_to_pixels, connector_route_points
from .author_style import (
    DEFAULT_THEME,
    TRANSPARENT_TOKEN,
    font_candidates,
    ink_color,
    pen_color,
    sticky_colors,
)
from .free_grid import GridMetrics


_DEFAULT_STICKY_FONT_PX = 15.0
_TEXT_INSET_PX = 7.0
_ARROW_HEAD_PX = 10.0


def draw_author_objects(
    painter: QPainter,
    objects: Iterable[object],
    metrics: GridMetrics,
    *,
    origin_offset: tuple[float, float] = (0.0, 0.0),
    theme: object = DEFAULT_THEME,
    scale: float = 1.0,
) -> None:
    """Paint typed author objects in persisted input order.

    ``metrics`` supplies the board-to-screen/export geometry; ``origin_offset``
    rebases signed Board coordinates without mutating the DTO.  ``scale`` is
    an optional output-raster factor for callers which paint a 2x PNG without
    already scaling their metrics.  The function deliberately draws no
    selection handles, hover affordances, link/lock chrome, or draft paths.
    Unknown/future DTOs are skipped so passthrough persistence never makes a
    compositor fail.
    """
    if not isinstance(painter, QPainter) or not painter.isActive():
        return
    factor = _positive_scale(scale)
    for item in objects:
        painter.save()
        try:
            if isinstance(item, StickyObject):
                _draw_sticky(painter, item, metrics, origin_offset, theme, factor)
            elif isinstance(item, TextObject):
                _draw_text_object(painter, item, metrics, origin_offset, theme, factor)
            elif isinstance(item, ShapeObject):
                _draw_shape(painter, item, metrics, origin_offset, theme, factor)
            elif isinstance(item, StrokeObject):
                _draw_stroke(painter, item, metrics, origin_offset, theme, factor)
            elif isinstance(item, ConnectorObject):
                _draw_connector(painter, item, metrics, origin_offset, theme, factor)
        finally:
            painter.restore()


def _draw_sticky(
    painter: QPainter,
    item: StickyObject,
    metrics: GridMetrics,
    origin: tuple[float, float],
    theme: object,
    factor: float,
) -> None:
    rect = _pixel_rect(item.box, metrics, origin, factor)
    if rect is None:
        return
    fill, border, foreground = sticky_colors(item.palette, theme)
    radius = min(9.0 * factor, max(0.0, min(rect.width(), rect.height()) / 7.0))
    painter.setPen(_pen(border, 1.2 * factor))
    painter.setBrush(QColor(*fill))
    painter.drawRoundedRect(rect, radius, radius)
    font_px = (
        _auto_sticky_font_px(rect, factor)
        if item.font_size == "auto"
        else max(8.0 * factor, float(item.font_size) * factor)
    )
    _draw_plain_text(
        painter,
        rect.adjusted(_TEXT_INSET_PX * factor, _TEXT_INSET_PX * factor,
                      -_TEXT_INSET_PX * factor, -_TEXT_INSET_PX * factor),
        item.text,
        color=QColor(*foreground),
        font_role="sans",
        font_px=font_px,
        align="left",
        bold=False,
        italic=False,
        underline=False,
        list_style="none",
    )


def _draw_text_object(
    painter: QPainter,
    item: TextObject,
    metrics: GridMetrics,
    origin: tuple[float, float],
    theme: object,
    factor: float,
) -> None:
    rect = _pixel_rect(item.box, metrics, origin, factor)
    if rect is None:
        return
    if item.fill_palette is not None and item.fill_palette != TRANSPARENT_TOKEN:
        fill, _border, _foreground = sticky_colors(item.fill_palette, theme)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*fill))
        painter.drawRoundedRect(rect, 4.0 * factor, 4.0 * factor)
    painter.setOpacity(max(0.0, min(1.0, item.opacity / 100.0)))
    _draw_plain_text(
        painter,
        rect.adjusted(_TEXT_INSET_PX * factor, _TEXT_INSET_PX * factor,
                      -_TEXT_INSET_PX * factor, -_TEXT_INSET_PX * factor),
        item.text,
        color=QColor(*ink_color(item.text_palette, theme)),
        font_role=item.font_role,
        font_px=float(item.font_size) * factor,
        align=item.align,
        bold=item.bold,
        italic=item.italic,
        underline=item.underline,
        list_style=item.list_style,
    )


def _draw_shape(
    painter: QPainter,
    item: ShapeObject,
    metrics: GridMetrics,
    origin: tuple[float, float],
    theme: object,
    factor: float,
) -> None:
    rect = _pixel_rect(item.box, metrics, origin, factor)
    if rect is None:
        return
    path = shape_path(item.shape, rect, factor=factor, corner_radius=item.corner_radius)
    if path.isEmpty():
        return
    pen = _pen(ink_color(item.stroke_palette, theme), item.stroke_width * factor, item.line_style)
    painter.setPen(pen)
    if item.fill_palette is None or item.fill_palette == TRANSPARENT_TOKEN:
        painter.setBrush(Qt.NoBrush)
    else:
        fill, _border, _foreground = sticky_colors(item.fill_palette, theme)
        painter.setBrush(QColor(*fill))
    painter.drawPath(path)
    if item.text:
        style = item.text_style
        _draw_plain_text(
            painter,
            rect.adjusted(_TEXT_INSET_PX * factor, _TEXT_INSET_PX * factor,
                          -_TEXT_INSET_PX * factor, -_TEXT_INSET_PX * factor),
            item.text,
            color=QColor(*ink_color(style.text_palette, theme)),
            font_role="sans",
            font_px=float(style.font_size) * factor,
            align=style.align,
            bold=style.bold,
            italic=style.italic,
            underline=style.underline,
            list_style="none",
        )


def _draw_stroke(
    painter: QPainter,
    item: StrokeObject,
    metrics: GridMetrics,
    origin: tuple[float, float],
    theme: object,
    factor: float,
) -> None:
    path = stroke_pixel_path(item.points, metrics, origin, factor)
    if path.isEmpty():
        return
    color = QColor(*pen_color(item.palette, tool=item.tool, theme=theme))
    pen = _pen(color, item.width_px_100 * factor)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)


def _draw_connector(
    painter: QPainter,
    item: ConnectorObject,
    metrics: GridMetrics,
    origin: tuple[float, float],
    theme: object,
    factor: float,
) -> None:
    board_points = _connector_board_points(item)
    points = _pixel_points(board_points, metrics, origin, factor)
    if len(points) < 2:
        return
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    color = QColor(*ink_color(item.stroke_palette, theme))
    pen = _pen(color, item.stroke_width * factor, item.line_style)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    head_size = max(_ARROW_HEAD_PX * factor, pen.widthF() * 3.5)
    if item.start_head == "arrow":
        head = _arrow_head(points[0], points[1], head_size)
        if not head.isEmpty():
            painter.drawPolygon(head)
    if item.end_head == "arrow":
        head = _arrow_head(points[-1], points[-2], head_size)
        if not head.isEmpty():
            painter.drawPolygon(head)
    if item.text:
        style = item.text_style
        mid = points[len(points) // 2]
        label = QRectF(mid.x() - 48.0 * factor, mid.y() - 12.0 * factor, 96.0 * factor, 24.0 * factor)
        _draw_plain_text(
            painter,
            label,
            item.text,
            color=QColor(*ink_color(style.text_palette, theme)),
            font_role="sans",
            font_px=float(style.font_size) * factor,
            align=style.align,
            bold=style.bold,
            italic=style.italic,
            underline=style.underline,
            list_style="none",
        )


def _draw_plain_text(
    painter: QPainter,
    rect: QRectF,
    text: str,
    *,
    color: QColor,
    font_role: object,
    font_px: float,
    align: object,
    bold: object,
    italic: object,
    underline: object,
    list_style: object,
) -> None:
    if rect.width() <= 0.0 or rect.height() <= 0.0 or not text:
        return
    font = QFont(_resolved_font_family(font_role))
    font.setPixelSize(max(1, int(round(font_px))))
    font.setBold(bool(bold))
    font.setItalic(bool(italic))
    font.setUnderline(bool(underline))
    painter.setFont(font)
    painter.setPen(color)
    flags = Qt.TextWordWrap | Qt.AlignTop | _alignment_flag(align)
    painter.drawText(rect, flags, _format_list_text(text, list_style))


def _pixel_rect(
    box: object,
    metrics: GridMetrics,
    origin: tuple[float, float],
    factor: float,
) -> QRectF | None:
    mapped = board_box_to_pixels(
        (box.x, box.y, box.width, box.height), metrics, origin_offset=origin
    )
    if mapped is None:
        return None
    x, y, width, height = mapped
    if width <= 0.0 or height <= 0.0:
        return None
    return QRectF(x * factor, y * factor, width * factor, height * factor)


def stroke_pixel_path(
    points: Iterable[object],
    metrics: GridMetrics,
    origin: tuple[float, float] = (0.0, 0.0),
    factor: float = 1.0,
) -> QPainterPath:
    """Build the screen/export polyline from the same Board points."""
    mapped = _pixel_points(points, metrics, origin, factor)
    path = QPainterPath()
    if len(mapped) < 2:
        return path
    path.moveTo(mapped[0])
    for point in mapped[1:]:
        path.lineTo(point)
    return path


def _point_xy(point: object) -> tuple[float, float] | None:
    try:
        if hasattr(point, "x") and hasattr(point, "y"):
            return float(point.x), float(point.y)
        x, y = point  # type: ignore[misc]
        return float(x), float(y)
    except (TypeError, ValueError):
        return None


def _pixel_points(
    points: Iterable[object],
    metrics: GridMetrics,
    origin: tuple[float, float],
    factor: float,
) -> list[QPointF]:
    mapped: list[QPointF] = []
    for point in points:
        xy = _point_xy(point)
        if xy is None:
            continue
        coordinate = board_point_to_pixels(xy, metrics, origin_offset=origin)
        if coordinate is not None:
            mapped.append(QPointF(coordinate[0] * factor, coordinate[1] * factor))
    return mapped


def shape_path(
    shape: str,
    rect: QRectF,
    *,
    factor: float = 1.0,
    corner_radius: int = 0,
) -> QPainterPath:
    """Qt path for one closed V1 shape. ``diamond`` is an alias of ``rhombus``."""
    path = QPainterPath()
    kind = "rhombus" if shape == "diamond" else str(shape)
    if kind in {"rectangle", "rounded_rectangle"}:
        radius = max(0.0, float(corner_radius) * factor)
        if kind == "rounded_rectangle" and radius <= 0.0:
            radius = 8.0 * factor
        radius = min(radius, max(0.0, min(rect.width(), rect.height()) / 2.0))
        if radius > 0.0:
            path.addRoundedRect(rect, radius, radius)
        else:
            path.addRect(rect)
    elif kind == "oval":
        path.addEllipse(rect)
    elif kind == "rhombus":
        path.addPolygon(QPolygonF([
            QPointF(rect.center().x(), rect.top()),
            QPointF(rect.right(), rect.center().y()),
            QPointF(rect.center().x(), rect.bottom()),
            QPointF(rect.left(), rect.center().y()),
        ]))
    elif kind == "triangle":
        path.addPolygon(QPolygonF([
            QPointF(rect.center().x(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
        ]))
    elif kind == "block_arrow":
        center_y = rect.center().y()
        shaft = max(1.0, rect.height() * 0.28)
        head_x = rect.left() + rect.width() * 0.62
        path.addPolygon(QPolygonF([
            QPointF(rect.left(), center_y - shaft),
            QPointF(head_x, center_y - shaft),
            QPointF(head_x, rect.top()),
            QPointF(rect.right(), center_y),
            QPointF(head_x, rect.bottom()),
            QPointF(head_x, center_y + shaft),
            QPointF(rect.left(), center_y + shaft),
        ]))
    return path


def _shape_path(shape: str, rect: QRectF, factor: float) -> QPainterPath:
    return shape_path(shape, rect, factor=factor)


def _connector_board_points(item: ConnectorObject) -> tuple[object, ...]:
    start = item.start.point
    end = item.end.point
    points = connector_route_points(
        (start.x, start.y), (end.x, end.y), item.route, item.elbow_bias
    )
    cls = type(start)
    return tuple(cls(point[0], point[1]) for point in points)


def _arrow_head(tip: QPointF, prior: QPointF, size: float) -> QPolygonF:
    dx = tip.x() - prior.x()
    dy = tip.y() - prior.y()
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return QPolygonF()
    ux, uy = dx / length, dy / length
    spread = size * 0.48
    base_x = tip.x() - ux * size
    base_y = tip.y() - uy * size
    return QPolygonF([
        tip,
        QPointF(base_x - uy * spread, base_y + ux * spread),
        QPointF(base_x + uy * spread, base_y - ux * spread),
    ])


def _pen(color: object, width: float, line_style: object = "solid") -> QPen:
    pen = QPen(_qcolor(color))
    pen.setWidthF(max(0.5, float(width)))
    if line_style == "dashed":
        pen.setStyle(Qt.DashLine)
    else:
        pen.setStyle(Qt.SolidLine)
    return pen


def _alignment_flag(value: object):
    if value == "center":
        return Qt.AlignHCenter
    if value == "right":
        return Qt.AlignRight
    return Qt.AlignLeft


def _format_list_text(text: str, list_style: object) -> str:
    if list_style not in {"bullet", "number"}:
        return text
    lines = text.splitlines() or [""]
    if list_style == "bullet":
        return "\n".join(f"• {line}" for line in lines)
    return "\n".join(f"{index}. {line}" for index, line in enumerate(lines, 1))


def _auto_sticky_font_px(rect: QRectF, factor: float) -> float:
    target = min(rect.width(), rect.height()) * 0.19
    return max(10.0 * factor, min(22.0 * factor, target))


def _positive_scale(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    return number if math.isfinite(number) and number > 0.0 else 1.0


def _qcolor(value: object) -> QColor:
    if isinstance(value, QColor):
        return QColor(value)
    if isinstance(value, tuple) and len(value) in {3, 4}:
        try:
            return QColor(*(int(component) for component in value))
        except (TypeError, ValueError):
            pass
    return QColor(24, 48, 57)


@lru_cache(maxsize=3)
def _resolved_font_family(role: object) -> str:
    """Pick a locally installed semantic-font candidate once per role.

    Passing an unavailable family straight to ``QFont`` produces a Qt warning
    and an expensive alias search on every new font.  The saved value remains
    the semantic role; this cache only resolves a local drawing choice.
    """
    available = set(QFontDatabase().families())
    for candidate in font_candidates(role):
        if candidate in available:
            return candidate
    return QFont().defaultFamily()


__all__ = ["draw_author_objects"]
