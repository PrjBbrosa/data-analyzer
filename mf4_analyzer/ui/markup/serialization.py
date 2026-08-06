"""Annotation payload serialization for the markup editor.

``serialize_item`` turns a scene item into a plain tuple and ``deserialize_item``
rebuilds it. The pair backs the editor's annotation clipboard (copy/paste), and
the tuple layout is the contract between them -- nothing validates a payload on
the way back in, so reordering or dropping a field breaks paste silently.
Layouts are pinned per kind in ``tests/ui/test_markup_serialization.py``:

    rect    (kind, rect, pos, color, width)
    line    (kind, line, pos, color, width)
    path    (kind, path, pos, color, width)
    text    (kind, text, pos, color, font_px)
    arrow   (kind, start, end, pos, color, width)
    number  (kind, circle_rect, label_text, label_pos, pos, color, width,
             scale, label_px)

These payloads are session-local: they hold live Qt value objects and never
reach disk (saving an annotated image flattens the scene to a pixmap).

Rebuilding an item has to go through the editor's own item factories, so
``deserialize_item`` takes the editor explicitly rather than hiding that
dependency behind ``self``.
"""
from __future__ import annotations

from PyQt5.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainterPath
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

from .items import _ArrowAnnotationItem


def item_pen(item):
    """Return the pen that carries ``item``'s stroke colour and width, or None
    for items that have no pen of their own (e.g. text)."""
    if isinstance(item, (QGraphicsRectItem, QGraphicsLineItem, QGraphicsPathItem)):
        return item.pen()
    if isinstance(item, _ArrowAnnotationItem):
        return item.pen()
    if isinstance(item, QGraphicsItemGroup):
        for child in item.childItems():
            if isinstance(child, QGraphicsEllipseItem):
                return child.pen()
    return None


def serialize_item(item, *, default_color, default_width, default_text_px,
                   default_number_radius):
    """Return the clipboard payload for ``item``, or None if it is not an
    annotation kind we know how to rebuild.

    The ``default_*`` values stand in for attributes the item does not carry
    itself -- an item with no pen falls back to the editor's active colour and
    width, and a font with no explicit pixel size falls back to the editor's
    defaults.
    """
    pen = item_pen(item)
    color = pen.color() if pen is not None else default_color
    width = pen.width() if pen is not None else default_width
    if isinstance(item, QGraphicsRectItem):
        return ("rect", QRectF(item.rect()), QPointF(item.pos()), QColor(color), width)
    if isinstance(item, QGraphicsLineItem):
        return ("line", QLineF(item.line()), QPointF(item.pos()), QColor(color), width)
    if isinstance(item, QGraphicsPathItem):
        return ("path", QPainterPath(item.path()), QPointF(item.pos()), QColor(color), width)
    if isinstance(item, QGraphicsTextItem):
        font_px = item.font().pixelSize()
        if font_px <= 0:
            font_px = default_text_px
        return ("text", item.toPlainText(), QPointF(item.pos()), QColor(item.defaultTextColor()), font_px)
    if isinstance(item, _ArrowAnnotationItem):
        return (
            "arrow",
            QPointF(item.start),
            QPointF(item.end),
            QPointF(item.pos()),
            QColor(color),
            width,
        )
    if isinstance(item, QGraphicsItemGroup):
        circle = None
        label = None
        for child in item.childItems():
            if isinstance(child, QGraphicsEllipseItem):
                circle = child
            elif isinstance(child, QGraphicsSimpleTextItem):
                label = child
        if circle is not None and label is not None:
            label_px = label.font().pixelSize()
            if label_px <= 0:
                label_px = round(default_number_radius * 1.25)
            return (
                "number",
                QRectF(circle.rect()),
                label.text(),
                QPointF(label.pos()),
                QPointF(item.pos()),
                QColor(color),
                width,
                float(item.scale()),
                label_px,
            )
    return None


def deserialize_item(editor, payload):
    """Rebuild the item described by ``payload`` inside ``editor``.

    The item factories take their colour and width from the editor's active
    style, so the payload's own style is applied to the editor for the duration
    of the rebuild and the user's pen is restored before returning.
    """
    if payload is None:
        return None
    previous_color = QColor(editor._color)
    previous_width = editor._stroke_width
    kind = payload[0]
    if kind == "rect":
        _kind, rect, pos, color, width = payload
        editor._color, editor._stroke_width = QColor(color), width
        item = editor.add_rect_item(rect)
        item.setPos(pos)
    elif kind == "line":
        _kind, line, pos, color, width = payload
        editor._color, editor._stroke_width = QColor(color), width
        item = editor.add_line_item(QRectF(line.p1(), line.p2()))
        item.setPos(pos)
    elif kind == "path":
        _kind, path, pos, color, width = payload
        editor._color, editor._stroke_width = QColor(color), width
        item = editor.add_path_item(path)
        item.setPos(pos)
    elif kind == "text":
        _kind, text, pos, color, font_px = payload
        item = editor._make_text_item(pos, text, QColor(color), font_px)
        item._committed = True
        editor._add_markup_item(item)
        item.setPos(pos)
    elif kind == "arrow":
        _kind, start, end, pos, color, width = payload
        editor._color, editor._stroke_width = QColor(color), width
        item = editor.add_arrow_item(QRectF(start, end))
        item.setPos(pos)
    elif kind == "number":
        _kind, circle_rect, label_text, label_pos, pos, color, width, scale, label_px = payload
        editor._color, editor._stroke_width = QColor(color), width
        circle = QGraphicsEllipseItem(circle_rect)
        circle.setPen(editor._pen())
        circle.setBrush(QBrush(editor._color))
        label = QGraphicsSimpleTextItem(label_text)
        label.setBrush(QBrush(Qt.white))
        label_font = label.font()
        label_font.setBold(True)
        label_font.setPixelSize(max(1, int(label_px)))
        label.setFont(label_font)
        label.setPos(label_pos)
        item = QGraphicsItemGroup()
        item.addToGroup(circle)
        item.addToGroup(label)
        item.setTransformOriginPoint(item.boundingRect().center())
        editor._add_markup_item(item)
        item.setPos(pos)
        item.setScale(scale)
    else:
        item = None
    editor._color = previous_color
    editor._stroke_width = previous_width
    return item
