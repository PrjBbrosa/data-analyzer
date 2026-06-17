from __future__ import annotations

from PyQt5.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsView,
)

from .commands import _GeometryCommand, _MoveCommand


class _MarkupGraphicsView(QGraphicsView):
    """Mouse interaction layer for the lightweight markup editor."""

    _MIN_DRAG = 3.0

    def __init__(self, editor: "MarkupEditor"):
        super().__init__(editor._scene, editor)
        self._editor = editor
        self._start = QPointF()
        self._path = None
        self._preview = None
        self._dragging_tool = None
        self._move_start = None
        self._move_positions = {}
        self._resize_handle = None
        self._resize_before = None
        self._pending_text_focus_item = None
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def mousePressEvent(self, event):
        tool = self._editor._tool
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        point = self._clamp(self.mapToScene(event.pos()))
        handle = self._editor.handle_at(point)
        if handle is not None:
            self._resize_handle = handle
            target = getattr(handle, "_target", None)
            self._resize_before = (
                self._editor._geometry_snapshot(target) if target is not None else None
            )
            event.accept()
            return

        existing = self._editor.markup_item_at(point)
        if isinstance(existing, QGraphicsTextItem) and tool == "text":
            self._begin_move(existing, point, event.modifiers())
            self._pending_text_focus_item = existing
            event.accept()
            return
        if existing is not None:
            self._begin_move(existing, point, event.modifiers())
            self._pending_text_focus_item = None
            event.accept()
            return

        if tool == "select":
            self._editor.clear_selection()
            event.accept()
            return

        if tool == "number":
            self._editor.clear_selection()
            self._editor.add_number_item(QRectF(point, point))
            event.accept()
            return
        if tool == "text":
            self._editor.clear_selection()
            self._editor.add_text_item(point, "")
            event.accept()
            return

        self._editor.clear_selection()
        self._start = point
        self._dragging_tool = tool
        self._preview = self._create_preview(tool, point)
        event.accept()

    def _begin_move(self, item, point: QPointF, modifiers):
        if not (modifiers & (Qt.ControlModifier | Qt.MetaModifier)):
            self._editor.clear_selection()
        item.setSelected(
            not item.isSelected()
            if modifiers & (Qt.ControlModifier | Qt.MetaModifier)
            else True
        )
        self._move_start = point
        self._move_positions = {
            selected: QPointF(selected.pos())
            for selected in self._editor.selected_markup_items()
        }
        self._editor.refresh_handles()

    def mouseMoveEvent(self, event):
        point = self._clamp(self.mapToScene(event.pos()))
        if self._resize_handle is not None:
            self._editor.drag_handle(self._resize_handle, point)
            event.accept()
            return
        if self._move_start is not None:
            delta = point - self._move_start
            for item, pos in self._move_positions.items():
                item.setPos(pos + delta)
            self._editor.refresh_handles()
            event.accept()
            return
        if self._dragging_tool is None:
            self.viewport().setCursor(self._editor._cursor_for(point))
            super().mouseMoveEvent(event)
            return
        point = self._constrained_point(point, event.modifiers())
        self._update_preview(point)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return

        if self._resize_handle is not None:
            self._commit_resize()
            event.accept()
            return
        if self._move_start is not None:
            moves = [
                (item, old, QPointF(item.pos()))
                for item, old in self._move_positions.items()
                if QPointF(item.pos()) != old
            ]
            pending_text_focus = self._pending_text_focus_item
            if moves:
                self._editor._undo_stack.push(_MoveCommand(moves))
            self._move_start = None
            self._move_positions = {}
            self._pending_text_focus_item = None
            self._editor.refresh_handles()
            if pending_text_focus is not None and not moves:
                self._editor.focus_text_item(pending_text_focus)
            event.accept()
            return
        if self._dragging_tool is None:
            super().mouseReleaseEvent(event)
            return

        point = self._clamp(self.mapToScene(event.pos()))
        point = self._constrained_point(point, event.modifiers())
        tool = self._dragging_tool
        self._remove_preview()
        self._dragging_tool = None

        rect = QRectF(self._start, point).normalized()
        line = QLineF(self._start, point)
        if tool == "crop":
            if rect.width() >= self._MIN_DRAG and rect.height() >= self._MIN_DRAG:
                self._editor.set_active_crop_rect(rect)
        elif tool == "rect":
            if rect.width() >= self._MIN_DRAG and rect.height() >= self._MIN_DRAG:
                self._editor.add_rect_item(rect)
        elif tool == "line":
            if line.length() >= self._MIN_DRAG:
                self._editor.add_line_item(QRectF(self._start, point))
        elif tool == "arrow":
            if line.length() >= self._MIN_DRAG:
                self._editor.add_arrow_item(QRectF(self._start, point))
        elif tool == "pen" and self._path is not None and self._path.elementCount() > 1:
            self._editor.add_path_item(QPainterPath(self._path))
        self._path = None
        event.accept()

    def _commit_resize(self):
        target = (
            getattr(self._resize_handle, "_target", None)
            if self._resize_handle is not None
            else None
        )
        if target is not None and self._resize_before is not None:
            after = self._editor._geometry_snapshot(target)
            if after != self._resize_before:
                self._editor._undo_stack.push(
                    _GeometryCommand(self._editor, target, self._resize_before, after)
                )
        self._resize_handle = None
        self._resize_before = None
        self._editor.refresh_handles()

    def mouseDoubleClickEvent(self, event):
        if self._editor._tool == "crop" and self._editor.active_crop_rect().isValid():
            self._editor.apply_active_crop()
            event.accept()
            return
        point = self._clamp(self.mapToScene(event.pos()))
        existing = self._editor.markup_item_at(point)
        if isinstance(existing, QGraphicsTextItem):
            self._editor.focus_text_item(existing)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        degrees = event.angleDelta().y()
        if degrees == 0:
            super().wheelEvent(event)
            return
        self._editor.zoom_by(1.15 if degrees > 0 else 1 / 1.15)
        event.accept()

    def _create_preview(self, tool: str, point: QPointF):
        pen = self._editor._pen()
        pen.setStyle(Qt.DashLine)
        if tool in {"rect", "crop"}:
            item = QGraphicsRectItem(QRectF(point, point))
            brush = QBrush(QColor(20, 96, 255, 34)) if tool == "crop" else QBrush(Qt.NoBrush)
            item.setBrush(brush)
        elif tool in {"line", "arrow"}:
            item = QGraphicsLineItem(QLineF(point, point))
        elif tool == "pen":
            self._path = QPainterPath(point)
            item = QGraphicsPathItem(self._path)
        else:
            return None
        item.setPen(pen)
        item.setZValue(10)
        item.setAcceptedMouseButtons(Qt.NoButton)
        self._editor._scene.addItem(item)
        return item

    def _update_preview(self, point: QPointF):
        if self._preview is None:
            return
        if isinstance(self._preview, QGraphicsRectItem):
            self._preview.setRect(QRectF(self._start, point).normalized())
        elif isinstance(self._preview, QGraphicsLineItem):
            self._preview.setLine(QLineF(self._start, point))
        elif isinstance(self._preview, QGraphicsPathItem):
            self._path.lineTo(point)
            self._preview.setPath(self._path)

    def _remove_preview(self):
        if self._preview is not None and self._preview.scene() is self._editor._scene:
            self._editor._scene.removeItem(self._preview)
        self._preview = None

    def _clamp(self, point: QPointF) -> QPointF:
        rect = self._editor._scene.sceneRect()
        return QPointF(
            min(max(point.x(), rect.left()), rect.right()),
            min(max(point.y(), rect.top()), rect.bottom()),
        )

    def _constrained_point(self, point: QPointF, modifiers) -> QPointF:
        if not (modifiers & Qt.ShiftModifier):
            return point
        if self._dragging_tool in {"line", "arrow"}:
            dx = point.x() - self._start.x()
            dy = point.y() - self._start.y()
            if abs(dx) >= abs(dy):
                return QPointF(point.x(), self._start.y())
            return QPointF(self._start.x(), point.y())
        if self._dragging_tool == "rect":
            dx = point.x() - self._start.x()
            dy = point.y() - self._start.y()
            side = max(abs(dx), abs(dy))
            return QPointF(
                self._start.x() + (side if dx >= 0 else -side),
                self._start.y() + (side if dy >= 0 else -side),
            )
        return point
