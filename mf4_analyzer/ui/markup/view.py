from __future__ import annotations

from PyQt5.QtCore import QEvent, QLineF, QPoint, QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsView,
)

from .commands import _GeometryCommand, _MoveCommand
from .items import _ArrowAnnotationItem


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
        self._rubber_origin = None
        self._rubber_band = None
        self._text_edit_press = False
        self._space_down = False
        self._pan_button = None
        self._pan_pos = None
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def mousePressEvent(self, event):
        # Right-click ends the active item only. Esc continues the ladder.
        if event.button() == Qt.RightButton:
            self.cancel_in_progress_draft()
            self._editor.clear_selection()
            event.accept()
            return
        # Middle-drag and Space+left-drag pan. They must win before a draw
        # tool or a hit-test can start an annotation.
        if self._start_pan(event):
            return
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        tool = self._editor._tool
        point = self._clamp(self.mapToScene(event.pos()))
        # Any tool: the active item's handle resizes that item. Built-in
        # RubberBandDrag never starts because this method used to return
        # before super(), and a hollow rect's shape includes its interior,
        # so super() would select it. Empty presses rubber-band here; Shift adds.
        handle = self._editor.handle_at(point)
        if handle is not None:
            self._resize_handle = handle
            target = getattr(handle, "_target", None)
            self._resize_before = (
                self._editor._geometry_snapshot(target) if target is not None else None
            )
            event.accept()
            return

        if tool == "select":
            self._press_select(point, event)
            return
        if tool == "text":
            self._press_text(point)
            event.accept()
            return
        if tool == "number":
            self._editor.clear_selection()
            item = self._editor.add_number_item(QRectF(point, point))
            self._editor.activate_markup_item(item)
            event.accept()
            return

        # arrow / line / rect / pen / crop: a press that is not a handle
        # always starts a new annotation or crop, even on an existing stroke.
        self._begin_draw(tool, point)
        event.accept()

    def _press_select(self, point, event):
        hit = self._editor.markup_item_at(point)
        if hit is None:
            hollow = self._editor.hollow_markup_containing(point)
            if hollow is not None and hollow.isSelected():
                hit = hollow
        if hit is not None:
            self._begin_move(hit, point, event.modifiers())
            self._pending_text_focus_item = None
            event.accept()
            return
        self._begin_rubber_band(point)
        event.accept()

    def _press_text(self, point):
        existing = self._editor.markup_item_at(point)
        if isinstance(existing, QGraphicsTextItem):
            self._editor.focus_text_item(existing)
            # Keep the following move/release from reaching the view, which
            # would drop edit focus or drag the label.
            self._text_edit_press = True
            return
        self._editor.clear_selection()
        item = self._editor.add_text_item(point, "")
        item.setSelected(True)
        self._editor.refresh_handles()

    def _begin_draw(self, tool: str, point):
        self._editor.clear_selection()
        self._start = QPointF(point)
        self._dragging_tool = tool
        self._preview = self._create_preview(tool, point)

    def _begin_rubber_band(self, point):
        self._rubber_origin = QPointF(point)
        band = QGraphicsRectItem()
        band.setData(0, "rubber_band")
        pen = QPen(QColor("#1769e0"), 1, Qt.DashLine)
        pen.setCosmetic(True)
        band.setPen(pen)
        band.setBrush(QBrush(QColor(23, 105, 224, 28)))
        band.setZValue(70)
        band.setAcceptedMouseButtons(Qt.NoButton)
        band.setFlag(QGraphicsItem.ItemIsSelectable, False)
        band.setRect(QRectF(point, point))
        self._editor._scene.addItem(band)
        self._rubber_band = band

    def cancel_in_progress_draft(self) -> bool:
        """Drop an in-progress draw or rubber band. Selection is left alone."""
        drawing = self._dragging_tool is not None
        banding = self._rubber_origin is not None
        if not drawing and not banding:
            return False
        self._remove_preview()
        self._dragging_tool = None
        self._path = None
        self._remove_rubber_band()
        return True

    def _remove_rubber_band(self):
        band = self._rubber_band
        if band is not None and band.scene() is self._editor._scene:
            self._editor._scene.removeItem(band)
        self._rubber_band = None
        self._rubber_origin = None

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
        if self._pan_button is not None:
            if not (event.buttons() & self._pan_button):
                self._finish_pan()
            else:
                pos = QPointF(event.pos())
                delta = pos - self._pan_pos
                self._pan_pos = pos
                self._scroll_by(-delta.x(), -delta.y())
                event.accept()
                return
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
        if self._text_edit_press:
            event.accept()
            return
        if self._rubber_origin is not None and self._rubber_band is not None:
            self._rubber_band.setRect(QRectF(self._rubber_origin, point).normalized())
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
        if self._pan_button is not None and event.button() == self._pan_button:
            self._finish_pan()
            event.accept()
            return
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return

        point = self._clamp(self.mapToScene(event.pos()))
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
        if self._text_edit_press:
            self._text_edit_press = False
            event.accept()
            return
        if self._rubber_origin is not None:
            origin = self._rubber_origin
            self._remove_rubber_band()
            rect = QRectF(origin, point).normalized()
            if rect.width() < self._MIN_DRAG and rect.height() < self._MIN_DRAG:
                if not (event.modifiers() & Qt.ShiftModifier):
                    self._editor.clear_selection()
            else:
                self._editor.select_markup_in_rect(
                    rect,
                    additive=bool(event.modifiers() & Qt.ShiftModifier),
                )
            event.accept()
            return
        if self._dragging_tool is None:
            super().mouseReleaseEvent(event)
            return

        point = self._constrained_point(point, event.modifiers())
        tool = self._dragging_tool
        self._remove_preview()
        self._dragging_tool = None

        rect = QRectF(self._start, point).normalized()
        line = QLineF(self._start, point)
        created = None
        if tool == "crop":
            if rect.width() >= self._MIN_DRAG and rect.height() >= self._MIN_DRAG:
                self._editor.set_active_crop_rect(rect)
        elif tool == "rect":
            if rect.width() >= self._MIN_DRAG and rect.height() >= self._MIN_DRAG:
                created = self._editor.add_rect_item(rect)
        elif tool == "line":
            if line.length() >= self._MIN_DRAG:
                created = self._editor.add_line_item(QRectF(self._start, point))
        elif tool == "arrow":
            if line.length() >= self._MIN_DRAG:
                created = self._editor.add_arrow_item(QRectF(self._start, point))
        elif tool == "pen" and self._path is not None and self._path.elementCount() > 1:
            created = self._editor.add_path_item(QPainterPath(self._path))
        self._path = None
        if created is not None:
            self._editor.activate_markup_item(created)
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

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Space and not self._editor._text_item_is_editing():
            if not event.isAutoRepeat():
                self._space_down = True
            event.accept()
            return
        modifiers = event.modifiers()
        command = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))
        # Esc / Ctrl+Enter / Ctrl+S belong to the editor even while text is editing.
        if key == Qt.Key_Escape:
            self._text_edit_press = False
        if key == Qt.Key_Escape or (
            command and key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_S)
        ):
            self._editor.keyPressEvent(event)
            if event.isAccepted():
                return
        super().keyPressEvent(event)
        if not event.isAccepted():
            self._editor.keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not self._editor._text_item_is_editing():
            if not event.isAutoRepeat():
                self._space_down = False
                if self._pan_button == Qt.LeftButton:
                    self._finish_pan()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def viewportEvent(self, event):
        # Key events sent at the viewport (the same target as mouse and wheel)
        # do not reach QGraphicsView.keyPressEvent on their own.
        if event.type() == QEvent.KeyPress:
            self.keyPressEvent(event)
            return True
        if event.type() == QEvent.KeyRelease:
            self.keyReleaseEvent(event)
            return True
        return super().viewportEvent(event)

    def wheelEvent(self, event):
        # Q-1: the wheel keeps zooming. Stroke width stays on [ and ].
        # A trackpad pixel delta without Ctrl pans; Shift pans horizontally.
        modifiers = int(event.modifiers())
        ctrl = bool(modifiers & int(Qt.ControlModifier | Qt.MetaModifier))
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        if ctrl:
            delta = angle.y() or pixel.y() or angle.x() or pixel.x()
            if delta == 0:
                super().wheelEvent(event)
                return
            self._zoom_at_pointer(1.15 if delta > 0 else 1 / 1.15, self._pointer_pos(event))
            event.accept()
            return
        if modifiers & int(Qt.ShiftModifier):
            self._pan_horizontal_wheel(pixel, angle)
            event.accept()
            return
        if pixel.x() != 0 or pixel.y() != 0:
            self._scroll_by(-float(pixel.x()), -float(pixel.y()))
            event.accept()
            return
        if angle.y() != 0:
            self._zoom_at_pointer(
                1.15 if angle.y() > 0 else 1 / 1.15,
                self._pointer_pos(event),
            )
            event.accept()
            return
        super().wheelEvent(event)

    def _create_preview(self, tool: str, point: QPointF):
        # Finished marks and their previews share a type and a solid pen.
        # Dash stays on the crop box and the rubber band only.
        if tool == "crop":
            item = QGraphicsRectItem(QRectF(point, point))
            item.setPen(QPen(QColor("#1769e0"), 1, Qt.DashLine))
            item.setBrush(QBrush(QColor(23, 105, 224, 38)))
        elif tool == "rect":
            item = QGraphicsRectItem(QRectF(point, point))
            item.setPen(self._editor._pen())
            item.setBrush(QBrush(Qt.NoBrush))
        elif tool == "line":
            item = QGraphicsLineItem(QLineF(point, point))
            item.setPen(self._editor._pen())
        elif tool == "arrow":
            item = _ArrowAnnotationItem(
                QPointF(point),
                QPointF(point),
                self._editor._pen(),
                QColor(self._editor._color),
            )
            item.setFlag(QGraphicsItem.ItemIsSelectable, False)
            item.setFlag(QGraphicsItem.ItemIsMovable, False)
        elif tool == "pen":
            self._path = QPainterPath(point)
            item = QGraphicsPathItem(self._path)
            item.setPen(self._editor._pen())
        else:
            return None
        item.setZValue(10)
        item.setData(0, "markup_preview")
        item.setAcceptedMouseButtons(Qt.NoButton)
        item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self._editor._scene.addItem(item)
        return item

    def _update_preview(self, point: QPointF):
        if self._preview is None:
            return
        if isinstance(self._preview, _ArrowAnnotationItem):
            self._preview.set_endpoint("p2", point)
            return
        if isinstance(self._preview, QGraphicsRectItem):
            self._preview.setRect(QRectF(self._start, point).normalized())
            return
        if isinstance(self._preview, QGraphicsLineItem):
            self._preview.setLine(QLineF(self._start, point))
            return
        if isinstance(self._preview, QGraphicsPathItem):
            self._path.lineTo(point)
            self._preview.setPath(self._path)

    def _remove_preview(self):
        if self._preview is not None and self._preview.scene() is self._editor._scene:
            self._editor._scene.removeItem(self._preview)
        self._preview = None

    def _start_pan(self, event) -> bool:
        button = event.button()
        if button != Qt.MiddleButton and not (
            button == Qt.LeftButton and self._space_down
        ):
            return False
        self._pan_button = button
        self._pan_pos = QPointF(event.pos())
        self.viewport().setCursor(Qt.ClosedHandCursor)
        event.accept()
        return True

    def _finish_pan(self) -> None:
        if self._pan_button is None:
            return
        self._pan_button = None
        self._pan_pos = None
        self.viewport().unsetCursor()

    def _pointer_pos(self, event) -> QPointF:
        position = getattr(event, "position", None)
        if callable(position):
            return QPointF(position())
        return QPointF(event.pos())

    def _scroll_by(self, dx: float, dy: float) -> None:
        """Move the scrollbars by viewport pixels.

        Positive ``dx`` / ``dy`` reveal scene content toward the bottom-right.
        A pan that follows the pointer passes the negated pointer delta.
        """
        if dx:
            bar = self.horizontalScrollBar()
            bar.setValue(int(round(bar.value() + dx)))
        if dy:
            bar = self.verticalScrollBar()
            bar.setValue(int(round(bar.value() + dy)))

    def _pan_horizontal_wheel(self, pixel, angle) -> None:
        if pixel.x() != 0 or pixel.y() != 0:
            delta = pixel.x() if pixel.x() != 0 else pixel.y()
            self._scroll_by(-float(delta), 0.0)
            return
        ticks = angle.y() if angle.y() != 0 else angle.x()
        if ticks == 0:
            return
        bar = self.horizontalScrollBar()
        lines = int(QApplication.wheelScrollLines())
        if lines < 1:
            lines = 1
        step = int(bar.singleStep())
        if step < 1:
            step = 1
        page = int(bar.pageStep())
        if page < 1:
            page = 1
        delta = int(ticks) * lines * step // 120
        if delta > page:
            delta = page
        elif delta < -page:
            delta = -page
        self._scroll_by(-float(delta), 0.0)

    def _zoom_at_pointer(self, factor: float, view_pos: QPointF) -> None:
        """Scale around the wheel position, then keep that scene point put.

        ``setTransform`` with ``AnchorUnderMouse`` follows ``QCursor`` and
        misses by about two pixels per notch even when the scroll range can
        hold the point. A fitted view also hides its scrollbars; the first
        zoom that needs them shrinks the viewport on the next layout. Show
        those bars before scaling so the correction runs on the final
        viewport. A scroll value the range cannot represent stays clamped.
        """
        anchor_px = QPoint(int(round(view_pos.x())), int(round(view_pos.y())))
        scene_point = self.mapToScene(anchor_px)
        # Same clamp as MarkupEditor.set_zoom. Predicting the unclamped factor
        # would reserve scrollbars a zoom that cannot happen will not need.
        target = min(8.0, max(0.1, float(self._editor._zoom) * float(factor)))
        saved_policy = (
            self.horizontalScrollBarPolicy(),
            self.verticalScrollBarPolicy(),
        )
        self._show_scrollbars_before_zoom(target)
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        try:
            self._editor.zoom_by(factor)
        finally:
            self.setTransformationAnchor(anchor)
            self.setHorizontalScrollBarPolicy(saved_policy[0])
            self.setVerticalScrollBarPolicy(saved_policy[1])
        self._hold_scene_point(scene_point, QPointF(anchor_px))

    def _show_scrollbars_before_zoom(self, zoom: float) -> None:
        rect = self._editor._scene.sceneRect()
        # A second pass catches the bar that appears only because the first
        # bar made the other viewport edge smaller.
        for _ in range(2):
            viewport = self.viewport()
            horizontal = self.horizontalScrollBar()
            vertical = self.verticalScrollBar()
            if (
                horizontal.maximum() == horizontal.minimum()
                and rect.width() * zoom > viewport.width() + 0.5
            ):
                self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            if (
                vertical.maximum() == vertical.minimum()
                and rect.height() * zoom > viewport.height() + 0.5
            ):
                self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

    def _hold_scene_point(self, scene_point: QPointF, view_pos: QPointF) -> None:
        horizontal = self.horizontalScrollBar()
        vertical = self.verticalScrollBar()
        for _ in range(2):
            mapped = self.mapFromScene(scene_point)
            dx = int(round(mapped.x() - view_pos.x()))
            dy = int(round(mapped.y() - view_pos.y()))
            if dx == 0 and dy == 0:
                return
            before_x = horizontal.value()
            before_y = vertical.value()
            if dx:
                horizontal.setValue(before_x + dx)
            if dy:
                vertical.setValue(before_y + dy)
            if horizontal.value() == before_x and vertical.value() == before_y:
                return

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
