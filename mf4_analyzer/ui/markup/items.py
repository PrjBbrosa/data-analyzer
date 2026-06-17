from __future__ import annotations

import math

from PyQt5.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
)
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsTextItem

_HIT_TOLERANCE = 12.0


class _ArrowAnnotationItem(QGraphicsItem):
    """Selectable arrow item with editable local endpoints."""

    def __init__(self, start: QPointF, end: QPointF, pen: QPen, color: QColor):
        super().__init__()
        self.start = QPointF(start)
        self.end = QPointF(end)
        self._pen = QPen(pen)
        self._color = QColor(color)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)

    def boundingRect(self):
        return QRectF(self.start, self.end).normalized().adjusted(-14, -14, 14, 14)

    def shape(self):
        path = QPainterPath()
        path.moveTo(self.start)
        path.lineTo(self.end)
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self._pen.widthF(), _HIT_TOLERANCE))
        shape = stroker.createStroke(path)
        shape.addPolygon(self._arrow_head())
        return shape

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(self._pen)
        painter.drawLine(QLineF(self.start, self.end))
        painter.setBrush(QBrush(self._color))
        painter.drawPolygon(self._arrow_head())
        if self.isSelected():
            handle_pen = QPen(QColor("#1769e0"), 1)
            painter.setPen(handle_pen)
            painter.setBrush(QBrush(QColor("#ffffff")))
            for point in (self.start, self.end):
                painter.drawRect(QRectF(point.x() - 4, point.y() - 4, 8, 8))

    def pen(self):
        return QPen(self._pen)

    def set_pen(self, pen: QPen, color: QColor | None = None):
        self.prepareGeometryChange()
        self._pen = QPen(pen)
        if color is not None:
            self._color = QColor(color)
        self.update()

    def set_endpoint(self, role: str, point: QPointF):
        self.prepareGeometryChange()
        if role == "p1":
            self.start = QPointF(point)
        else:
            self.end = QPointF(point)
        self.update()

    def _arrow_head(self):
        angle = math.atan2(self.end.y() - self.start.y(), self.end.x() - self.start.x())
        length = max(10.0, self._pen.widthF() * 4.0)
        spread = math.radians(26)
        p1 = QPointF(
            self.end.x() - length * math.cos(angle - spread),
            self.end.y() - length * math.sin(angle - spread),
        )
        p2 = QPointF(
            self.end.x() - length * math.cos(angle + spread),
            self.end.y() - length * math.sin(angle + spread),
        )
        return QPolygonF([self.end, p1, p2])


class _TextAnnotationItem(QGraphicsTextItem):
    """Text annotation that leaves edit mode cleanly.

    A plain ``QGraphicsTextItem`` keeps ``TextEditorInteraction`` on forever,
    so once you click away it still swallows ``Delete`` (you can never remove
    the box) and its text-selection highlight stays painted (the grey band
    that "won't go away"). This subclass, on focus-out:

    * drops the text-cursor selection so the highlight band disappears,
    * switches to ``NoTextInteraction`` so ``Delete`` removes the whole box
      while it is graphics-selected, and
    * asks the editor to discard the box if it was left empty.

    ``Delete``/``Backspace`` on an already-empty box exits edit mode, which
    triggers the same empty-box discard.
    """

    def __init__(self, text: str, editor: "MarkupEditor"):
        super().__init__(text)
        self._editor = editor
        self._committed = False

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            self.setTextCursor(cursor)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self._editor._on_text_focus_out(self)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and not self.toPlainText():
            # Empty box: leave edit mode; the editor discards empty boxes on
            # focus-out, which also pulls it out of the scene.
            self.clearFocus()
            event.accept()
            return
        super().keyPressEvent(event)
