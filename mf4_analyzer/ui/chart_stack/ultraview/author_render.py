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

from .author_geometry import board_box_to_pixels, board_point_to_pixels
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
    path = _shape_path(item.shape, rect, factor)
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
    points = _pixel_points(item.points, metrics, origin, factor)
    if len(points) < 2:
        return
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    color = QColor(*pen_color(item.palette, tool=item.tool, theme=theme))
    pen = _pen(color, item.width_px_100 * factor)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
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


def _pixel_points(
    points: Iterable[object],
    metrics: GridMetrics,
    origin: tuple[float, float],
    factor: float,
) -> list[QPointF]:
    mapped: list[QPointF] = []
    for point in points:
        coordinate = board_point_to_pixels((point.x, point.y), metrics, origin_offset=origin)
        if coordinate is not None:
            mapped.append(QPointF(coordinate[0] * factor, coordinate[1] * factor))
    return mapped


def _shape_path(shape: str, rect: QRectF, factor: float) -> QPainterPath:
    path = QPainterPath()
    if shape == "rectangle":
        radius = min(6.0 * factor, max(0.0, min(rect.width(), rect.height()) / 8.0))
        path.addRoundedRect(rect, radius, radius)
    elif shape == "oval":
        path.addEllipse(rect)
    elif shape == "rhombus":
        path.addPolygon(QPolygonF([
            QPointF(rect.center().x(), rect.top()),
            QPointF(rect.right(), rect.center().y()),
            QPointF(rect.center().x(), rect.bottom()),
            QPointF(rect.left(), rect.center().y()),
        ]))
    elif shape == "triangle":
        path.addPolygon(QPolygonF([
            QPointF(rect.center().x(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
        ]))
    elif shape == "block_arrow":
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


def _connector_board_points(item: ConnectorObject) -> tuple[object, ...]:
    start = item.start.point
    end = item.end.point
    if item.route != "elbow" or (start.x == end.x and start.y == end.y):
        return start, end
    bias = 0.5 if item.elbow_bias is None else item.elbow_bias
    # The axis with the larger displacement takes the first leg.  This keeps
    # a saved elbow deterministic while still avoiding an unnecessarily long
    # first segment for ordinary diagonal endpoints; there is no obstacle
    # routing or hidden graph search in this V1 renderer.
    if abs(end.x - start.x) >= abs(end.y - start.y):
        middle = type(start)(start.x + (end.x - start.x) * bias, start.y)
        corner = type(start)(middle.x, end.y)
    else:
        middle = type(start)(start.x, start.y + (end.y - start.y) * bias)
        corner = type(start)(end.x, middle.y)
    return start, middle, corner, end


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
