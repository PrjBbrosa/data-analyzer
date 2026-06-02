from __future__ import annotations

import math
from typing import Callable

from PyQt5.QtCore import QLineF, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QUndoCommand,
    QUndoStack,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

import qtawesome as qta

_HIT_TOLERANCE = 12.0
_HIT_SCREEN_PX = 8.0
_HANDLE_HIT_SCREEN_PX = 14.0


def _pixmap_as_device_pixels(pixmap: QPixmap) -> QPixmap:
    copy = QPixmap(pixmap)
    if copy.isNull() or abs(copy.devicePixelRatioF() - 1.0) < 1e-9:
        return copy
    normalized = QPixmap.fromImage(copy.toImage())
    normalized.setDevicePixelRatio(1.0)
    return normalized


class _AddItemCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem):
        super().__init__("添加标注")
        self._scene = scene
        self._item = item

    def redo(self):
        if self._item.scene() is None:
            self._scene.addItem(self._item)

    def undo(self):
        if self._item.scene() is self._scene:
            self._scene.removeItem(self._item)


class _CropCommand(QUndoCommand):
    def __init__(self, editor: "MarkupEditor", crop_rect: QRect):
        super().__init__("裁剪")
        self._editor = editor
        self._before_pixmap = QPixmap(editor._current_pixmap)
        self._before_positions = editor._item_positions()
        self._after_pixmap = editor._current_pixmap.copy(crop_rect)
        offset = crop_rect.topLeft()
        self._after_positions = {
            item: QPointF(pos.x() - offset.x(), pos.y() - offset.y())
            for item, pos in self._before_positions.items()
        }

    def redo(self):
        self._editor._apply_crop_state(self._after_pixmap, self._after_positions)

    def undo(self):
        self._editor._apply_crop_state(self._before_pixmap, self._before_positions)


class _MoveCommand(QUndoCommand):
    def __init__(self, moves):
        super().__init__("移动标注")
        self._moves = [(item, QPointF(old), QPointF(new)) for item, old, new in moves]

    def redo(self):
        for item, _old, new in self._moves:
            item.setPos(new)

    def undo(self):
        for item, old, _new in self._moves:
            item.setPos(old)


class _DeleteCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, items):
        super().__init__("删除标注")
        self._scene = scene
        self._items = list(items)

    def redo(self):
        for item in self._items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)

    def undo(self):
        for item in self._items:
            if item.scene() is None:
                self._scene.addItem(item)


class _GeometryCommand(QUndoCommand):
    def __init__(self, editor: "MarkupEditor", item, before, after):
        super().__init__("调整标注")
        self._editor = editor
        self._item = item
        self._before = before
        self._after = after

    def redo(self):
        self._editor._restore_geometry(self._item, self._after)

    def undo(self):
        self._editor._restore_geometry(self._item, self._before)


class _StyleCommand(QUndoCommand):
    def __init__(self, editor: "MarkupEditor", entries):
        super().__init__("修改样式")
        self._editor = editor
        self._entries = entries

    def redo(self):
        for item, _before, after in self._entries:
            self._editor._apply_style_to(item, after[0], after[1])

    def undo(self):
        for item, before, _after in self._entries:
            self._editor._apply_style_to(item, before[0], before[1])


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


class MarkupEditor(QWidget):
    """Lightweight image markup editor backed by a QGraphicsScene."""

    TOOLS = ("select", "crop", "arrow", "line", "rect", "pen", "text", "number")
    _TOOL_ICONS = {
        "select": "ph.cursor",
        "crop": "ph.crop",
        "arrow": "ph.arrow-up-right",
        "line": "ph.line-segment",
        "rect": "ph.rectangle",
        "pen": "ph.pencil-simple",
        "text": "ph.text-t",
        "number": "ph.number-circle-one",
    }
    _TOOL_ICON_COLOR = "#1769e0"          # blue tool glyphs
    _TOOL_ICON_COLOR_ACTIVE = "#ffffff"   # contrast glyph on the selected chip
    _HANDLE_CURSORS = {
        "tl": Qt.SizeFDiagCursor,
        "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor,
        "bl": Qt.SizeBDiagCursor,
        "top": Qt.SizeVerCursor,
        "bottom": Qt.SizeVerCursor,
        "left": Qt.SizeHorCursor,
        "right": Qt.SizeHorCursor,
    }

    def __init__(
        self,
        pixmap: QPixmap,
        on_done: Callable[[QPixmap], None] | None = None,
        parent=None,
    ):
        super().__init__(parent, Qt.Window)
        self.setObjectName("MarkupEditor")
        self.setWindowTitle("图片标注")

        self._on_done = on_done
        self._current_pixmap = _pixmap_as_device_pixels(pixmap)
        self._tool = "select"
        self._color = QColor("#e53935")
        self._stroke_width = 4
        self._text_px = self._default_text_px(self._current_pixmap)
        self._number_radius = self._default_number_radius(self._current_pixmap)
        self._undo_stack = QUndoStack(self)
        self._zoom = 1.0
        self._handles = []
        self._active_crop_rect = QRectF()
        self._crop_item = None
        self._annotation_clipboard = []
        self._initial_fit_done = False
        self._auto_fit = True

        self._scene = QGraphicsScene(self)
        self._background_item = QGraphicsPixmapItem(self._current_pixmap)
        self._background_item.setZValue(0)
        self._background_item.setAcceptedMouseButtons(Qt.NoButton)
        self._background_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self._background_item.setFlag(QGraphicsItem.ItemIsMovable, False)
        self._scene.addItem(self._background_item)
        self._set_scene_to_pixmap_size()
        self._scene.selectionChanged.connect(self.refresh_handles)

        self._view = _MarkupGraphicsView(self)
        self._view.setObjectName("markupGraphicsView")
        self._view.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.RubberBandDrag)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._view, 1)
        self.resize(960, 640)
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QTimer.singleShot(0, self.fit_to_window)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._initial_fit_done and self._auto_fit:
            QTimer.singleShot(0, self.fit_to_window)

    def add_rect_item(self, rect: QRectF) -> QGraphicsRectItem:
        item = QGraphicsRectItem(rect)
        item.setPen(self._pen())
        item.setBrush(QBrush(Qt.NoBrush))
        self._add_markup_item(item)
        return item

    def add_line_item(self, rect: QRectF) -> QGraphicsLineItem:
        item = QGraphicsLineItem(rect.left(), rect.top(), rect.right(), rect.bottom())
        item.setPen(self._pen())
        self._add_markup_item(item)
        return item

    def add_arrow_item(self, rect: QRectF) -> QGraphicsItem:
        item = _ArrowAnnotationItem(
            QPointF(rect.left(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            self._pen(),
            self._color,
        )
        self._add_markup_item(item)
        return item

    def add_path_item(self, path: QPainterPath) -> QGraphicsPathItem:
        item = QGraphicsPathItem(path)
        item.setPen(self._pen())
        item.setTransformOriginPoint(item.boundingRect().topLeft())
        self._add_markup_item(item)
        return item

    @staticmethod
    def _default_text_px(pixmap: QPixmap) -> int:
        # Text lives in image-pixel space and is viewed fit-to-window, so a
        # fixed point size renders tiny on a chart copy (the source is grabbed
        # at 2x hi-DPI). Scale the default to ~3.5% of the copied image height,
        # clamped to a legible band; users can still fine-tune via the corner
        # scale handle.
        height = max(1, pixmap.height())
        return int(min(64, max(24, round(height * 0.035))))

    def _make_text_item(self, point: QPointF, text: str, color, font_px) -> _TextAnnotationItem:
        item = _TextAnnotationItem(text, self)
        item.setDefaultTextColor(QColor(color))
        font = item.font()
        font.setPixelSize(max(1, int(font_px)))
        item.setFont(font)
        item.setPos(point)
        item.setFlag(QGraphicsItem.ItemIsFocusable, True)
        return item

    def add_text_item(self, point: QPointF, text: str = "") -> QGraphicsTextItem:
        item = self._make_text_item(point, text, self._color, self._text_px)
        item.setZValue(1)
        item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        item.setFlag(QGraphicsItem.ItemIsMovable, True)
        item._committed = False
        # Add to the scene immediately but defer the undo entry until the box
        # has content, so an empty box that is abandoned leaves no add/delete
        # noise in the undo history.
        self._scene.addItem(item)
        self._begin_text_edit(item)
        self.refresh_handles()
        return item

    def _begin_text_edit(self, item) -> None:
        item.setTextInteractionFlags(Qt.TextEditorInteraction)
        item.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self._view.setFocus(Qt.MouseFocusReason)
        item.setFocus(Qt.MouseFocusReason)
        self._scene.setFocusItem(item, Qt.MouseFocusReason)

    def _on_text_focus_out(self, item) -> None:
        # Defer so we never mutate the scene from inside the item's own event.
        QTimer.singleShot(0, lambda: self._finalize_text_item(item))

    def _finalize_text_item(self, item) -> None:
        if item.scene() is not self._scene:
            return
        has_text = bool(item.toPlainText().strip())
        committed = getattr(item, "_committed", False)
        if not has_text:
            if committed:
                self._undo_stack.push(_DeleteCommand(self._scene, [item]))
            else:
                self._scene.removeItem(item)
            self.refresh_handles()
            return
        if not committed:
            item._committed = True
            self._undo_stack.push(_AddItemCommand(self._scene, item))
        self.refresh_handles()

    def focus_text_item(self, item: QGraphicsTextItem):
        self.clear_selection()
        item.setSelected(True)
        self._begin_text_edit(item)
        self.refresh_handles()

    @staticmethod
    def _default_number_radius(pixmap: QPixmap) -> int:
        # Badges share the text scaling rationale: a fixed radius is tiny on a
        # hi-DPI chart copy. Track ~3% of image height, clamped to a legible
        # band.
        height = max(1, pixmap.height())
        return int(min(48, max(16, round(height * 0.03))))

    def _next_number(self) -> int:
        # Derive the next badge value from the badges already in the scene so
        # undo/redo and deletion never produce a duplicate number.
        used = []
        for item in self._markup_items():
            if isinstance(item, QGraphicsItemGroup):
                for child in item.childItems():
                    if isinstance(child, QGraphicsSimpleTextItem):
                        try:
                            used.append(int(child.text()))
                        except ValueError:
                            pass
        return (max(used) + 1) if used else 1

    def add_number_item(self, rect: QRectF) -> QGraphicsItemGroup:
        number = self._next_number()
        x = rect.left()
        y = rect.top()

        label = QGraphicsSimpleTextItem(str(number))
        label.setBrush(QBrush(Qt.white))
        font = label.font()
        font.setBold(True)
        font.setPixelSize(max(1, round(self._number_radius * 1.25)))
        label.setFont(font)
        text_rect = label.boundingRect()
        radius = max(
            self._stroke_width * 3,
            self._number_radius,
            text_rect.width() / 2 + 6,
            text_rect.height() / 2 + 4,
        )

        circle = QGraphicsEllipseItem(QRectF(-radius, -radius, radius * 2, radius * 2))
        circle.setPen(self._pen())
        circle.setBrush(QBrush(self._color))
        label.setPos(-text_rect.width() / 2, -text_rect.height() / 2)

        group = QGraphicsItemGroup()
        group.addToGroup(circle)
        group.addToGroup(label)
        group.setPos(QPointF(x, y))
        group.setTransformOriginPoint(group.boundingRect().center())
        self._add_markup_item(group)
        return group

    def apply_crop_rect(self, crop_rect: QRectF) -> None:
        bounds = QRectF(
            0, 0, self._current_pixmap.width(), self._current_pixmap.height()
        )
        rect = crop_rect.normalized().intersected(bounds)
        if rect.isEmpty():
            return

        qrect = QRect(
            int(round(rect.left())),
            int(round(rect.top())),
            int(round(rect.width())),
            int(round(rect.height())),
        ).intersected(self._current_pixmap.rect())
        if qrect.isEmpty():
            return

        self._undo_stack.push(_CropCommand(self, qrect))

    def render_result(self) -> QPixmap:
        self._scene.clearSelection()
        hidden_items = list(self._handles)
        if self._crop_item is not None:
            hidden_items.append(self._crop_item)
        previous_visibility = [(item, item.isVisible()) for item in hidden_items]
        for item, _visible in previous_visibility:
            item.setVisible(False)
        width = self._current_pixmap.width()
        height = self._current_pixmap.height()
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        source = QRectF(0, 0, width, height)
        self._scene.render(painter, QRectF(image.rect()), source)
        painter.end()
        for item, visible in previous_visibility:
            item.setVisible(visible)
        return QPixmap.fromImage(image)

    def finish_and_copy(self) -> QPixmap:
        result = self.render_result()
        if self._on_done is not None:
            self._on_done(result)
        self.close()
        return result

    def save_result(self) -> bool:
        path = self._get_save_path()
        if not path:
            return False
        return self.render_result().save(path)

    def _get_save_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存标注图片",
            "",
            "PNG (*.png);;JPEG (*.jpg)",
        )
        return path

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget(self)
        toolbar.setObjectName("markupEditorToolbar")
        layout = QGridLayout(toolbar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(0)

        def make_group(name: str):
            group = QWidget(toolbar)
            group.setObjectName(name)
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(6)
            return group, group_layout

        left_group, left_layout = make_group("markupToolbarLeftGroup")
        center_group, center_layout = make_group("markupToolbarCenterGroup")
        right_group, right_layout = make_group("markupToolbarRightGroup")

        close_btn = QToolButton(left_group)
        close_btn.setObjectName("markupCloseButton")
        close_btn.setText("")
        close_btn.setIcon(qta.icon("ph.x", color="#dc2626"))
        close_btn.setIconSize(QSize(24, 24))
        close_btn.setToolTip("关闭")
        close_btn.setAutoRaise(True)
        close_btn.setFixedSize(QSize(44, 44))
        close_btn.setStyleSheet(
            "QToolButton#markupCloseButton {"
            "padding: 0px;"
            "border: 1px solid #f2b8b8; border-radius: 6px;"
            "background: #fffafa;"
            "}"
            "QToolButton#markupCloseButton:hover {"
            "background: #fee2e2; border-color: #dc2626;"
            "}"
        )
        close_btn.clicked.connect(self.close)
        left_layout.addWidget(close_btn)

        self._style_button = QToolButton(center_group)
        self._style_button.setObjectName("markupStyleButton")
        self._style_button.setToolTip("样式（颜色 / 线宽）")
        self._style_button.setAutoRaise(True)
        self._style_button.setIconSize(QSize(54, 24))
        self._style_button.setFixedSize(QSize(76, 44))
        self._style_button.setPopupMode(QToolButton.InstantPopup)
        self._style_button.setStyleSheet(self._compact_tool_button_qss())
        style_menu = QMenu(self._style_button)
        style_menu.setObjectName("markupStyleMenu")
        # Match the rounded-popup shell contract: QSS radius needs a transparent
        # menu window, and macOS needs native frame/shadow disabled so no square
        # backing remains behind the rounded style panel.
        style_menu.setWindowFlags(
            style_menu.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        style_menu.setAttribute(Qt.WA_TranslucentBackground, True)
        # Make the menu a transparent shell: the rounded surface lives on the
        # inner panel below. Otherwise the global QMenu rule paints a square
        # white rect (radius 12 > padding) that pokes past the rounded corners.
        style_menu.setStyleSheet(
            "QMenu#markupStyleMenu { background: transparent; border: none; padding: 0px; }"
        )
        style_action = QWidgetAction(style_menu)
        style_action.setDefaultWidget(self._build_style_panel(style_menu))
        style_menu.addAction(style_action)
        self._style_button.setMenu(style_menu)
        center_layout.addWidget(self._style_button)
        self._refresh_style_button_icon()

        tool_group = QButtonGroup(toolbar)
        tool_group.setExclusive(True)
        labels = {
            "select": "选择",
            "crop": "裁剪",
            "arrow": "箭头",
            "line": "直线",
            "rect": "矩形",
            "pen": "画笔",
            "text": "文字",
            "number": "序号",
        }
        self._tool_buttons = {}
        for tool in self.TOOLS:
            active = tool == self._tool
            button = QToolButton(center_group)
            button.setText("")
            button.setIcon(self._tool_icon(tool, active))
            button.setIconSize(QSize(24, 24))
            button.setToolTip(f"{labels[tool]} ({tool[0].upper()})")
            button.setObjectName(f"markupTool_{tool}")
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setFixedSize(QSize(44, 44))
            button.setStyleSheet(self._compact_tool_button_qss())
            button.clicked.connect(
                lambda checked=False, name=tool: self.set_tool(name)
            )
            if active:
                button.setChecked(True)
            tool_group.addButton(button)
            center_layout.addWidget(button)
            self._tool_buttons[tool] = button

        undo_btn = QToolButton(center_group)
        undo_btn.setObjectName("markupUndoButton")
        undo_btn.setText("")
        undo_btn.setIcon(qta.icon("ph.arrow-counter-clockwise", color="#374151"))
        undo_btn.setIconSize(QSize(24, 24))
        undo_btn.setToolTip("撤销")
        undo_btn.setAutoRaise(True)
        undo_btn.setFixedSize(QSize(44, 44))
        undo_btn.setStyleSheet(self._compact_tool_button_qss())
        undo_btn.clicked.connect(self._undo_stack.undo)
        center_layout.addWidget(undo_btn)

        redo_btn = QToolButton(center_group)
        redo_btn.setObjectName("markupRedoButton")
        redo_btn.setText("")
        redo_btn.setIcon(qta.icon("ph.arrow-clockwise", color="#374151"))
        redo_btn.setIconSize(QSize(24, 24))
        redo_btn.setToolTip("重做")
        redo_btn.setAutoRaise(True)
        redo_btn.setFixedSize(QSize(44, 44))
        redo_btn.setStyleSheet(self._compact_tool_button_qss())
        redo_btn.clicked.connect(self._undo_stack.redo)
        center_layout.addWidget(redo_btn)

        save_btn = QPushButton("保存", right_group)
        save_btn.setObjectName("markupSaveButton")
        save_btn.clicked.connect(self.save_result)
        right_layout.addWidget(save_btn)

        done_btn = QPushButton("完成复制", right_group)
        done_btn.setObjectName("markupDoneButton")
        done_btn.setProperty("variant", "primary")
        done_btn.setStyleSheet(
            "QPushButton#markupDoneButton {"
            "background: #1769e0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 14px; font-weight: 600;"
            "}"
            "QPushButton#markupDoneButton:hover { background: #0f5ec8; }"
        )
        done_btn.clicked.connect(self.finish_and_copy)
        right_layout.addWidget(done_btn)

        layout.addWidget(left_group, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(center_group, 0, 1, Qt.AlignCenter)
        layout.addWidget(right_group, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 1)
        return toolbar

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self._zoom * factor)

    def zoom_in(self) -> None:
        self.zoom_by(1.15)

    def zoom_out(self) -> None:
        self.zoom_by(1 / 1.15)

    def set_zoom(self, zoom: float) -> None:
        self._auto_fit = False
        self._zoom = min(8.0, max(0.1, float(zoom)))
        self._view.setTransform(QTransform().scale(self._zoom, self._zoom))

    def actual_size(self) -> None:
        self.set_zoom(1.0)

    def fit_to_window(self) -> None:
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._zoom = self._view.transform().m11()
        self._auto_fit = True

    def set_color(self, color: QColor) -> None:
        entries = []
        for item in self.selected_markup_items():
            before = self._item_style(item)
            entries.append((item, before, (QColor(color), before[1])))
        self._color = QColor(color)
        if entries:
            self._undo_stack.push(_StyleCommand(self, entries))
        self._refresh_style_button_icon()
        self._sync_style_panel()
        self.refresh_handles()

    def set_stroke_width(self, width: int) -> None:
        entries = []
        for item in self.selected_markup_items():
            if isinstance(item, QGraphicsTextItem):
                # Stroke width is meaningless for text; recording a style
                # change here would just litter the undo stack with no-ops.
                continue
            before = self._item_style(item)
            entries.append((item, before, (before[0], int(width))))
        self._stroke_width = int(width)
        if entries:
            self._undo_stack.push(_StyleCommand(self, entries))
        self._refresh_style_button_icon()
        self._sync_style_panel()
        self.refresh_handles()

    def set_tool(self, tool: str) -> None:
        if tool not in self.TOOLS:
            raise ValueError(f"unknown markup tool: {tool}")
        self._tool = tool
        self._view.setDragMode(
            QGraphicsView.RubberBandDrag if tool == "select" else QGraphicsView.NoDrag
        )
        if tool != "crop":
            self.cancel_active_crop()
        self._sync_tool_buttons()

    def _set_scene_to_pixmap_size(self) -> None:
        self._scene.setSceneRect(self._background_item.boundingRect())

    def _pen(self) -> QPen:
        pen = QPen(self._color, self._stroke_width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def _compact_tool_button_qss(self) -> str:
        return (
            "QToolButton {"
            "padding: 0px;"
            "border: 1px solid #c9d6ea; border-radius: 6px;"
            "background: #ffffff;"
            "}"
            "QToolButton:hover { background: #eef4ff; border-color: #1769e0; }"
            # Selected tool: solid accent fill behind the white (contrast) glyph.
            "QToolButton:checked { background: #1769e0; border-color: #1769e0; }"
        )

    def _color_button_qss(self) -> str:
        # Same rounded chip as the tools; selected swatch gets a blue ring
        # (not a fill) so the colour stays readable.
        return (
            "QToolButton {"
            "padding: 0px;"
            "border: 1px solid #c9d6ea; border-radius: 6px;"
            "background: #ffffff;"
            "}"
            "QToolButton:hover { background: #eef4ff; border-color: #1769e0; }"
            "QToolButton:checked { border: 2px solid #1769e0; background: #eaf2ff; }"
        )

    def _tool_icon(self, tool: str, active: bool) -> QIcon:
        color = self._TOOL_ICON_COLOR_ACTIVE if active else self._TOOL_ICON_COLOR
        return qta.icon(self._TOOL_ICONS[tool], color=color)

    def _sync_tool_buttons(self) -> None:
        for tool, button in getattr(self, "_tool_buttons", {}).items():
            active = tool == self._tool
            if button.isChecked() != active:
                button.setChecked(active)
            button.setIcon(self._tool_icon(tool, active))

    def _sync_style_panel(self) -> None:
        # Reflect the current colour/width in the popup so the active choice is
        # visible (rounded chip + selected highlight, like the tool buttons).
        target = QColor(self._color).name().lower()
        for hexname, button in getattr(self, "_color_buttons", {}).items():
            button.setChecked(hexname == target)
        for width, button in getattr(self, "_width_buttons", {}).items():
            active = width == self._stroke_width
            button.setChecked(active)
            button.setIcon(self._width_icon(width, "#ffffff" if active else "#374151"))

    def _add_markup_item(self, item):
        item.setZValue(1)
        item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        item.setFlag(QGraphicsItem.ItemIsMovable, True)
        self._undo_stack.push(_AddItemCommand(self._scene, item))
        self.refresh_handles()

    def _apply_style(self, item):
        self._apply_style_to(item, self._color, self._stroke_width)

    def _apply_style_to(self, item, color, width):
        pen = QPen(QColor(color), int(width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if isinstance(item, QGraphicsRectItem):
            item.setPen(pen)
        elif isinstance(item, QGraphicsLineItem):
            item.setPen(pen)
        elif isinstance(item, QGraphicsPathItem):
            item.setPen(pen)
        elif isinstance(item, QGraphicsTextItem):
            item.setDefaultTextColor(QColor(color))
        elif isinstance(item, _ArrowAnnotationItem):
            item.set_pen(pen, QColor(color))
        elif isinstance(item, QGraphicsItemGroup):
            for child in item.childItems():
                if isinstance(child, QGraphicsEllipseItem):
                    child.setPen(pen)
                    child.setBrush(QBrush(QColor(color)))

    def _refresh_style_button_icon(self):
        button = getattr(self, "_style_button", None)
        if button is not None:
            button.setIcon(self._style_button_icon(self._color, self._stroke_width))
            button.setIconSize(QSize(54, 24))

    def _build_style_panel(self, menu):
        panel = QWidget()
        panel.setObjectName("markupStylePanel")
        # The panel is the only visible surface inside the transparent menu
        # shell, so it carries the rounded background/border itself.
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setStyleSheet(
            "QWidget#markupStylePanel {"
            "background: #ffffff;"
            "border: 1px solid #c9d6ea;"
            "border-radius: 10px;"
            "}"
        )
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        self._color_buttons = {}
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        for name, color in (
            ("红色", "#e53935"),
            ("橙色", "#f97316"),
            ("黄色", "#eab308"),
            ("绿色", "#059669"),
            ("蓝色", "#2563eb"),
            ("黑色", "#111827"),
        ):
            button = QToolButton(panel)
            button.setObjectName(f"markupColor_{color[1:]}")
            button.setIcon(self._color_icon(QColor(color)))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(name)
            button.setAutoRaise(True)
            button.setCheckable(True)
            button.setFixedSize(QSize(30, 30))
            button.setStyleSheet(self._color_button_qss())
            button.clicked.connect(
                lambda checked=False, c=color, m=menu: (
                    self.set_color(QColor(c)),
                    m.hide(),
                )
            )
            color_row.addWidget(button)
            self._color_buttons[color.lower()] = button
        outer.addLayout(color_row)

        self._width_buttons = {}
        width_row = QHBoxLayout()
        width_row.setSpacing(8)
        for width in (2, 4, 6, 8):
            button = QToolButton(panel)
            button.setObjectName(f"markupWidth_{width}")
            button.setIcon(self._width_icon(width))
            button.setIconSize(QSize(24, 18))
            button.setToolTip(f"{width}px")
            button.setAutoRaise(True)
            button.setCheckable(True)
            button.setFixedSize(QSize(34, 30))
            button.setStyleSheet(self._compact_tool_button_qss())
            button.clicked.connect(
                lambda checked=False, w=width, m=menu: (
                    self.set_stroke_width(w),
                    m.hide(),
                )
            )
            width_row.addWidget(button)
            self._width_buttons[width] = button
        outer.addLayout(width_row)
        self._sync_style_panel()
        return panel

    def selected_markup_items(self):
        items = []
        seen = set()
        for item in self._scene.selectedItems():
            markup = self._as_markup_item(item)
            if markup is None or id(markup) in seen:
                continue
            seen.add(id(markup))
            items.append(markup)
        return items

    def clear_selection(self):
        for item in self.selected_markup_items():
            item.setSelected(False)
        self.refresh_handles()

    def select_all_annotations(self):
        for item in self._markup_items():
            item.setSelected(True)
        self.refresh_handles()

    def move_selection_by(self, dx: float, dy: float):
        moves = [
            (
                item,
                QPointF(item.pos()),
                QPointF(item.pos().x() + dx, item.pos().y() + dy),
            )
            for item in self.selected_markup_items()
        ]
        if moves:
            self._undo_stack.push(_MoveCommand(moves))
        self.refresh_handles()

    def delete_selected_annotations(self):
        items = [
            item for item in self.selected_markup_items()
            if item.scene() is self._scene
        ]
        if items:
            self._undo_stack.push(_DeleteCommand(self._scene, items))
        self.refresh_handles()

    def copy_selected_annotations(self):
        self._annotation_clipboard = [
            self._serialize_item(item) for item in self.selected_markup_items()
        ]

    def paste_annotations(self):
        payloads = [payload for payload in self._annotation_clipboard if payload is not None]
        if not payloads:
            return []
        self.clear_selection()
        pasted = []
        self._undo_stack.beginMacro("粘贴标注")
        for payload in payloads:
            item = self._deserialize_item(payload)
            if item is None:
                continue
            item.moveBy(12, 12)
            item.setSelected(True)
            pasted.append(item)
        self._undo_stack.endMacro()
        self.refresh_handles()
        return pasted

    def markup_item_at(self, point: QPointF):
        exact = self._first_markup(self._scene.items(point))
        if exact is not None:
            return exact
        tol = _HIT_SCREEN_PX / max(self._zoom, 0.1)
        region = QRectF(point.x() - tol, point.y() - tol, tol * 2, tol * 2)
        return self._first_markup(
            self._scene.items(region, Qt.IntersectsItemShape, Qt.DescendingOrder)
        )

    def _first_markup(self, items):
        seen = set()
        for item in items:
            markup = self._as_markup_item(item)
            if markup is None or id(markup) in seen:
                continue
            seen.add(id(markup))
            return markup
        return None

    def _as_markup_item(self, item):
        while item is not None and item.parentItem() is not None:
            item = item.parentItem()
        if item is None or item is self._background_item:
            return None
        if item.data(0) in {"editor_handle", "crop_overlay"}:
            return None
        return item

    def set_active_crop_rect(self, rect: QRectF):
        rect = rect.normalized().intersected(self._scene.sceneRect())
        if rect.isEmpty():
            return
        self._active_crop_rect = QRectF(rect)
        if self._crop_item is None:
            self._crop_item = QGraphicsRectItem()
            self._crop_item.setData(0, "crop_overlay")
            self._crop_item.setZValue(40)
            self._crop_item.setPen(QPen(QColor("#1769e0"), 1, Qt.DashLine))
            self._crop_item.setBrush(QBrush(QColor(23, 105, 224, 38)))
            self._crop_item.setAcceptedMouseButtons(Qt.NoButton)
            self._scene.addItem(self._crop_item)
        self._crop_item.setRect(self._active_crop_rect)
        self.refresh_handles()

    def active_crop_rect(self):
        return QRectF(self._active_crop_rect)

    def apply_active_crop(self):
        if not self._active_crop_rect.isValid() or self._active_crop_rect.isEmpty():
            return
        rect = QRectF(self._active_crop_rect)
        self.cancel_active_crop()
        self.apply_crop_rect(rect)

    def cancel_active_crop(self):
        self._active_crop_rect = QRectF()
        if self._crop_item is not None and self._crop_item.scene() is self._scene:
            self._scene.removeItem(self._crop_item)
        self._crop_item = None
        self.refresh_handles()

    def handle_at(self, point: QPointF):
        tol = _HANDLE_HIT_SCREEN_PX / max(self._zoom, 0.1)
        nearest = None
        nearest_distance = None
        for handle in self._handles:
            center = handle.sceneBoundingRect().center()
            hit_rect = QRectF(
                center.x() - tol,
                center.y() - tol,
                tol * 2,
                tol * 2,
            )
            if hit_rect.contains(point):
                distance = (center.x() - point.x()) ** 2 + (center.y() - point.y()) ** 2
                if nearest_distance is None or distance < nearest_distance:
                    nearest = handle
                    nearest_distance = distance
        return nearest

    def _cursor_for(self, point: QPointF):
        handle = self.handle_at(point)
        if handle is not None:
            role = getattr(handle, "_role", "")
            if role.startswith("crop_"):
                role = role[5:]
            return self._HANDLE_CURSORS.get(role, Qt.SizeAllCursor)
        if self.markup_item_at(point) is not None:
            return Qt.SizeAllCursor
        return Qt.ArrowCursor if self._tool == "select" else Qt.CrossCursor

    def drag_handle(self, handle, point: QPointF):
        role = getattr(handle, "_role", "")
        target = getattr(handle, "_target", None)
        if role.startswith("crop_"):
            self._drag_crop_handle(role, point)
        elif isinstance(target, QGraphicsRectItem):
            self._drag_rect_handle(target, role, point)
        elif isinstance(target, QGraphicsLineItem):
            local = target.mapFromScene(point)
            line = target.line()
            if role == "p1":
                line.setP1(local)
            else:
                line.setP2(local)
            target.setLine(line)
        elif isinstance(target, _ArrowAnnotationItem):
            target.set_endpoint(role, target.mapFromScene(point))
        elif isinstance(target, (QGraphicsTextItem, QGraphicsPathItem, QGraphicsItemGroup)):
            self._drag_scale_handle(target, point)
        self.refresh_handles()

    def refresh_handles(self):
        self._clear_handles()
        if self._tool == "crop" and self._crop_item is not None:
            self._add_crop_handles()
            return
        for item in self.selected_markup_items():
            self._add_handles_for_item(item)

    def _clear_handles(self):
        for handle in self._handles:
            if handle.scene() is self._scene:
                self._scene.removeItem(handle)
        self._handles = []

    def _make_handle(self, point: QPointF, role: str, target=None):
        handle = QGraphicsRectItem(-4, -4, 8, 8)
        handle.setData(0, "editor_handle")
        handle._role = role
        handle._target = target
        handle.setZValue(80)
        handle.setPos(point)
        handle.setPen(QPen(QColor("#1769e0"), 1))
        handle.setBrush(QBrush(QColor("#ffffff")))
        self._scene.addItem(handle)
        self._handles.append(handle)

    def _add_handles_for_item(self, item):
        if isinstance(item, QGraphicsRectItem):
            rect = item.rect()
            points = {
                "tl": rect.topLeft(),
                "top": QPointF(rect.center().x(), rect.top()),
                "tr": rect.topRight(),
                "right": QPointF(rect.right(), rect.center().y()),
                "br": rect.bottomRight(),
                "bottom": QPointF(rect.center().x(), rect.bottom()),
                "bl": rect.bottomLeft(),
                "left": QPointF(rect.left(), rect.center().y()),
            }
            for role, point in points.items():
                self._make_handle(item.mapToScene(point), role, item)
        elif isinstance(item, QGraphicsLineItem):
            line = item.line()
            self._make_handle(item.mapToScene(line.p1()), "p1", item)
            self._make_handle(item.mapToScene(line.p2()), "p2", item)
        elif isinstance(item, _ArrowAnnotationItem):
            self._make_handle(item.mapToScene(item.start), "p1", item)
            self._make_handle(item.mapToScene(item.end), "p2", item)
        elif isinstance(item, QGraphicsTextItem):
            self._add_scale_handle(item)
        elif isinstance(item, (QGraphicsPathItem, QGraphicsItemGroup)):
            self._add_scale_handle(item)

    def _add_scale_handle(self, item):
        rect = item.boundingRect()
        self._make_handle(item.mapToScene(rect.bottomRight()), "scale", item)

    def _add_crop_handles(self):
        rect = self._active_crop_rect
        for role, point in {
            "crop_tl": rect.topLeft(),
            "crop_top": QPointF(rect.center().x(), rect.top()),
            "crop_tr": rect.topRight(),
            "crop_right": QPointF(rect.right(), rect.center().y()),
            "crop_br": rect.bottomRight(),
            "crop_bottom": QPointF(rect.center().x(), rect.bottom()),
            "crop_bl": rect.bottomLeft(),
            "crop_left": QPointF(rect.left(), rect.center().y()),
        }.items():
            self._make_handle(point, role, None)

    def _drag_crop_handle(self, role: str, point: QPointF):
        rect = QRectF(self._active_crop_rect)
        if role == "crop_tl":
            rect.setTopLeft(point)
        elif role == "crop_top":
            rect.setTop(point.y())
        elif role == "crop_tr":
            rect.setTopRight(point)
        elif role == "crop_right":
            rect.setRight(point.x())
        elif role == "crop_br":
            rect.setBottomRight(point)
        elif role == "crop_bottom":
            rect.setBottom(point.y())
        elif role == "crop_bl":
            rect.setBottomLeft(point)
        elif role == "crop_left":
            rect.setLeft(point.x())
        self.set_active_crop_rect(rect.normalized())

    def _drag_rect_handle(self, item: QGraphicsRectItem, role: str, point: QPointF):
        local = item.mapFromScene(point)
        rect = QRectF(item.rect())
        if role == "tl":
            rect.setTopLeft(local)
        elif role == "top":
            rect.setTop(local.y())
        elif role == "tr":
            rect.setTopRight(local)
        elif role == "right":
            rect.setRight(local.x())
        elif role == "br":
            rect.setBottomRight(local)
        elif role == "bottom":
            rect.setBottom(local.y())
        elif role == "bl":
            rect.setBottomLeft(local)
        elif role == "left":
            rect.setLeft(local.x())
        item.setRect(rect.normalized())

    def _drag_scale_handle(self, item, point: QPointF):
        rect = item.boundingRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        if isinstance(item, QGraphicsItemGroup):
            center = rect.center()
            center_scene = item.mapToScene(center)
            half_width = max(rect.width() / 2.0, 0.001)
            half_height = max(rect.height() / 2.0, 0.001)
            scale = max(
                abs(point.x() - center_scene.x()) / half_width,
                abs(point.y() - center_scene.y()) / half_height,
                0.25,
            )
            item.setTransformOriginPoint(center)
            item.setScale(scale)
            return
        top_left = rect.topLeft()
        top_left_scene = item.mapToScene(top_left)
        item.setTransformOriginPoint(top_left)
        candidates = []
        if rect.width() > 0.001:
            candidates.append((point.x() - top_left_scene.x()) / rect.width())
        if rect.height() > 0.001:
            candidates.append((point.y() - top_left_scene.y()) / rect.height())
        if not candidates:
            return
        scale = max(max(candidates), 0.25)
        current = float(item.scale())
        if abs(scale - current) < 1e-9:
            scale = current
        item.setScale(scale)

    def _item_style(self, item):
        if isinstance(item, QGraphicsTextItem):
            return (QColor(item.defaultTextColor()), self._stroke_width)
        pen = self._item_pen(item)
        if pen is not None:
            return (QColor(pen.color()), pen.width())
        return (QColor(self._color), self._stroke_width)

    def _geometry_snapshot(self, item):
        if isinstance(item, QGraphicsRectItem):
            return ("rect", QRectF(item.rect()), QPointF(item.pos()))
        if isinstance(item, _ArrowAnnotationItem):
            return (
                "arrow",
                QPointF(item.start),
                QPointF(item.end),
                QPointF(item.pos()),
            )
        if isinstance(item, QGraphicsLineItem):
            return ("line", QLineF(item.line()), QPointF(item.pos()))
        return ("scale", float(item.scale()), QPointF(item.pos()))

    def _restore_geometry(self, item, snapshot):
        kind = snapshot[0]
        if kind == "rect":
            item.setRect(snapshot[1])
            item.setPos(snapshot[2])
        elif kind == "arrow":
            item.prepareGeometryChange()
            item.start = QPointF(snapshot[1])
            item.end = QPointF(snapshot[2])
            item.setPos(snapshot[3])
            item.update()
        elif kind == "line":
            item.setLine(snapshot[1])
            item.setPos(snapshot[2])
        else:
            item.setScale(snapshot[1])
            item.setPos(snapshot[2])
        self.refresh_handles()

    def _markup_items(self):
        items = []
        seen = set()
        for item in self._scene.items():
            markup = self._as_markup_item(item)
            if markup is None or markup.scene() is not self._scene:
                continue
            if id(markup) in seen:
                continue
            seen.add(id(markup))
            items.append(markup)
        return items

    def _item_positions(self):
        return {item: QPointF(item.pos()) for item in self._markup_items()}

    def _apply_crop_state(self, pixmap: QPixmap, positions):
        self._current_pixmap = _pixmap_as_device_pixels(pixmap)
        self._background_item.setPixmap(self._current_pixmap)
        for item, pos in positions.items():
            if item.scene() is self._scene:
                item.setPos(pos)
        self._set_scene_to_pixmap_size()
        self.fit_to_window()

    def _serialize_item(self, item):
        pen = self._item_pen(item)
        color = pen.color() if pen is not None else self._color
        width = pen.width() if pen is not None else self._stroke_width
        if isinstance(item, QGraphicsRectItem):
            return ("rect", QRectF(item.rect()), QPointF(item.pos()), QColor(color), width)
        if isinstance(item, QGraphicsLineItem):
            return ("line", QLineF(item.line()), QPointF(item.pos()), QColor(color), width)
        if isinstance(item, QGraphicsPathItem):
            return ("path", QPainterPath(item.path()), QPointF(item.pos()), QColor(color), width)
        if isinstance(item, QGraphicsTextItem):
            font_px = item.font().pixelSize()
            if font_px <= 0:
                font_px = self._text_px
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
                    label_px = round(self._number_radius * 1.25)
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

    def _deserialize_item(self, payload):
        if payload is None:
            return None
        previous_color = QColor(self._color)
        previous_width = self._stroke_width
        kind = payload[0]
        if kind == "rect":
            _kind, rect, pos, color, width = payload
            self._color, self._stroke_width = QColor(color), width
            item = self.add_rect_item(rect)
            item.setPos(pos)
        elif kind == "line":
            _kind, line, pos, color, width = payload
            self._color, self._stroke_width = QColor(color), width
            item = self.add_line_item(QRectF(line.p1(), line.p2()))
            item.setPos(pos)
        elif kind == "path":
            _kind, path, pos, color, width = payload
            self._color, self._stroke_width = QColor(color), width
            item = self.add_path_item(path)
            item.setPos(pos)
        elif kind == "text":
            _kind, text, pos, color, font_px = payload
            item = self._make_text_item(pos, text, QColor(color), font_px)
            item._committed = True
            self._add_markup_item(item)
            item.setPos(pos)
        elif kind == "arrow":
            _kind, start, end, pos, color, width = payload
            self._color, self._stroke_width = QColor(color), width
            item = self.add_arrow_item(QRectF(start, end))
            item.setPos(pos)
        elif kind == "number":
            _kind, circle_rect, label_text, label_pos, pos, color, width, scale, label_px = payload
            self._color, self._stroke_width = QColor(color), width
            circle = QGraphicsEllipseItem(circle_rect)
            circle.setPen(self._pen())
            circle.setBrush(QBrush(self._color))
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
            self._add_markup_item(item)
            item.setPos(pos)
            item.setScale(scale)
        else:
            item = None
        self._color = previous_color
        self._stroke_width = previous_width
        return item

    def _item_pen(self, item):
        if isinstance(item, (QGraphicsRectItem, QGraphicsLineItem, QGraphicsPathItem)):
            return item.pen()
        if isinstance(item, _ArrowAnnotationItem):
            return item.pen()
        if isinstance(item, QGraphicsItemGroup):
            for child in item.childItems():
                if isinstance(child, QGraphicsEllipseItem):
                    return child.pen()
        return None

    def _color_icon(self, color: QColor):
        pix = QPixmap(18, 18)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#d0d7e2"), 1))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QRectF(3, 3, 12, 12))
        painter.end()
        return QIcon(pix)

    def _width_icon(self, width: int, color: str = "#374151"):
        pix = QPixmap(24, 18)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(4, 9), QPointF(20, 9))
        painter.end()
        return QIcon(pix)

    def _style_button_icon(self, color: QColor, width: int):
        pix = QPixmap(44, 18)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#d0d7e2"), 1))
        painter.setBrush(QBrush(QColor(color)))
        painter.drawEllipse(QRectF(2, 4, 11, 11))
        painter.setPen(
            QPen(QColor("#374151"), max(1, int(width)), Qt.SolidLine, Qt.RoundCap)
        )
        painter.drawLine(QPointF(20, 9), QPointF(40, 9))
        painter.end()
        return QIcon(pix)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        command = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))

        if key == Qt.Key_Escape:
            focused = self._scene.focusItem()
            if isinstance(focused, QGraphicsTextItem):
                focused.clearFocus()
            elif self.active_crop_rect().isValid():
                self.cancel_active_crop()
            else:
                self.close()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            # Enter never finishes the copy (too easy to fire by accident); it
            # only confirms an in-progress crop. While editing text the text
            # item consumes Enter as a newline before we ever reach here.
            if self.active_crop_rect().isValid():
                self.apply_active_crop()
                event.accept()
                return
            super().keyPressEvent(event)
            return
        if command and key == Qt.Key_Z:
            self._undo_stack.undo()
            event.accept()
            return
        if command and key == Qt.Key_Y:
            self._undo_stack.redo()
            event.accept()
            return
        if command and key == Qt.Key_A:
            self.select_all_annotations()
            event.accept()
            return
        if command and key == Qt.Key_C:
            self.copy_selected_annotations()
            event.accept()
            return
        if command and key == Qt.Key_V:
            self.paste_annotations()
            event.accept()
            return
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_annotations()
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if modifiers & Qt.ShiftModifier else 1
            dx = (-step if key == Qt.Key_Left else step if key == Qt.Key_Right else 0)
            dy = (-step if key == Qt.Key_Up else step if key == Qt.Key_Down else 0)
            self.move_selection_by(dx, dy)
            event.accept()
            return
        if command and key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_in()
            event.accept()
            return
        if command and key == Qt.Key_Minus:
            self.zoom_out()
            event.accept()
            return
        if key == Qt.Key_0:
            self.actual_size()
            event.accept()
            return
        if key == Qt.Key_BracketLeft:
            self.set_stroke_width(max(1, self._stroke_width - 1))
            event.accept()
            return
        if key == Qt.Key_BracketRight:
            self.set_stroke_width(self._stroke_width + 1)
            event.accept()
            return

        shortcuts = {
            Qt.Key_V: "select",
            Qt.Key_A: "arrow",
            Qt.Key_L: "line",
            Qt.Key_R: "rect",
            Qt.Key_P: "pen",
            Qt.Key_T: "text",
            Qt.Key_N: "number",
            Qt.Key_C: "crop",
        }
        if key in shortcuts and not command:
            self.set_tool(shortcuts[key])
            event.accept()
            return
        super().keyPressEvent(event)
