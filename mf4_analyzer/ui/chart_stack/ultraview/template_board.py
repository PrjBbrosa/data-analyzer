"""UltraView template Board grid and empty-slot hosts.

Template layout projection only. The free-grid host stays on the widgets
façade until a later Wave 1 commit.
"""
from __future__ import annotations

from typing import Mapping

from PyQt5.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QKeyEvent, QMouseEvent
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import LAYOUT_SLOTS

from .layouts import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    logical_board_size,
    slot_rects,
)
from .ghost_overlay import GhostOverlay
from .viewport import (
    ZOOM_DEFAULT,
    linear_zoom_anchor,
    linear_zoom_point,
    zoomed_viewport_size,
)
from .widgets_common import (
    _accept_ultraview_drag,
    _clear_page_card_selection,
    _drop_on_unplaced_tray,
    _page_of,
    _set_flag,
    _union_pixel_rect,
    extract_ref_strings,
)
from .card_widgets import (
    CardViewModel,
    ReplaceHoverController,
    UltraViewCard,
)


class EmptySlotWidget(QFrame):
    add_clicked = pyqtSignal(str)
    ref_dropped = pyqtSignal(str, str, str)
    drag_entered = pyqtSignal()

    def __init__(self, slot_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewEmptySlot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.TabFocus)
        self._slot_id = slot_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self._label = QLabel("＋\n添加 View", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setObjectName("ultraViewEmptySlotLabel")
        layout.addWidget(self._label, 1)
        self.setAccessibleName(f"空槽 {slot_id} 添加 View")

    def slot_id(self) -> str:
        return self._slot_id

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.add_clicked.emit(self._slot_id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.add_clicked.emit(self._slot_id)
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            _set_flag(self, "dropActive", True)
            self.drag_entered.emit()
            note = getattr(self.parentWidget(), "note_replace_hover", None)
            if callable(note):
                note(None)
            return
        _set_flag(self, "dropActive", False)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            _set_flag(self, "dropActive", True)
            return
        _set_flag(self, "dropActive", False)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        _set_flag(self, "dropActive", False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        _set_flag(self, "dropActive", False)
        extracted = extract_ref_strings(event.mimeData())
        event.acceptProposedAction()
        if extracted is None:
            return
        section, view_id = extracted
        self.ref_dropped.emit(self._slot_id, section, view_id)


class BoardGrid(QWidget):
    add_clicked = pyqtSignal(str)
    ref_dropped = pyqtSignal(str, str, str)
    open_source_requested = pyqtSignal(str, str)
    sync_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    copy_card_image_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()
    slot_swap_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardGrid")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout_id = "hero_left_4"
        self._ratio = 0.67
        self._widgets: dict[str, QWidget] = {}
        self._viewport_size = QSize(0, 0)
        self._zoom = ZOOM_DEFAULT
        # Template-only overlay. FreeGrid paints on ViewportFeedbackSurface.
        self._overlay = GhostOverlay(self)
        self._overlay.hide()
        self._replace = ReplaceHoverController(self)
        self._replace.armed.connect(self._on_replace_armed)
        self._replace.cleared.connect(self._on_replace_cleared)
        self._slot_source: str | None = None
        self._slot_press: QPoint | None = None
        self._slot_active = False

    def layout_id(self) -> str:
        return self._layout_id

    def slot_widget(self, slot_id: str) -> QWidget | None:
        return self._widgets.get(slot_id)

    def card_widgets(self) -> list[UltraViewCard]:
        return [widget for widget in self._widgets.values() if isinstance(widget, UltraViewCard)]

    def card_for(self, section: str, view_id: str) -> UltraViewCard | None:
        for card in self.card_widgets():
            model = card.model()
            if model.section == section and model.view_id == view_id:
                return card
        return None

    def set_grid(
        self,
        layout_id: str,
        primary_ratio: float,
        models: Mapping[str, CardViewModel | None],
    ) -> None:
        self._layout_id = layout_id
        self._ratio = primary_ratio
        wanted = set(LAYOUT_SLOTS[layout_id])
        for slot_id in list(self._widgets):
            if slot_id not in wanted:
                self._discard(slot_id)
        for slot_id in LAYOUT_SLOTS[layout_id]:
            model = models.get(slot_id)
            self._sync_slot(slot_id, model)
        self._sync_logical_size()
        self._relayout()
        self._raise_overlay()

    def set_viewport_size(self, size: QSize) -> None:
        """Record the scroll viewport. Logical canvas is ``BASE_BOARD_SIZE``.

        Window size used to drive slot aspect; that made every card follow the
        chrome-safe fit rect. Keep the setter so callers and tests still have
        a viewport to query, but geometry comes from the export-sized board.
        """
        if size == self._viewport_size:
            return
        if self._slot_active:
            self.cancel_gesture()
        self._viewport_size = QSize(size)
        self._sync_logical_size()

    def set_zoom(self, zoom: float) -> None:
        value = float(zoom)
        if value == self._zoom:
            return
        self._zoom = value
        self._sync_logical_size()

    def zoom_anchor_at(self, point: tuple[float, float]) -> tuple[float, float]:
        """Canvas pixel → zoom-independent anchor. Template geometry is linear."""
        return linear_zoom_anchor(point, self._zoom)

    def point_for_zoom_anchor(self, anchor: tuple[float, float]) -> tuple[float, float]:
        """Inverse of :meth:`zoom_anchor_at` at the zoom currently laid out."""
        return linear_zoom_point(anchor, self._zoom)

    def logical_size(self) -> QSize:
        return QSize(self.size())

    def unzoomed_size(self) -> QSize:
        try:
            width, height = logical_board_size(self._layout_id, BASE_BOARD_SIZE)
        except ValueError:
            return QSize(*BASE_BOARD_SIZE)
        return QSize(width, height)

    def content_rect_1x(self) -> tuple[float, float, float, float] | None:
        """Union of occupied template slots at 1×. Empty board returns None."""
        return _union_pixel_rect(
            self.unzoomed_slot_rect(slot_id)
            for slot_id, widget in self._widgets.items()
            if isinstance(widget, UltraViewCard)
        )

    def content_rect(self) -> tuple[float, float, float, float] | None:
        """Union of occupied template cards at the current zoom."""
        return _union_pixel_rect(
            (float(card.x()), float(card.y()), float(card.width()), float(card.height()))
            for card in self.card_widgets()
        )

    def unzoomed_slot_rect(self, slot_id: str) -> tuple[float, float, float, float] | None:
        size = self.unzoomed_size()
        content = (
            BOARD_PADDING,
            BOARD_PADDING,
            max(0, size.width() - 2 * BOARD_PADDING),
            max(0, size.height() - 2 * BOARD_PADDING),
        )
        try:
            rects = slot_rects(self._layout_id, content, self._ratio)
        except ValueError:
            return None
        rect = rects.get(slot_id)
        if rect is None:
            return None
        return (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))

    def clear_projection(self) -> None:
        if not self._widgets:
            return
        for slot_id in list(self._widgets):
            self._discard(slot_id)

    def cancel_gesture(self) -> bool:
        if self._slot_source is None:
            return False
        source = self._slot_source
        active = self._slot_active
        card = self._widgets.get(source)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if isinstance(card, UltraViewCard):
            card.restore_dim()
        self._overlay.clear()
        self._slot_source = None
        self._slot_press = None
        self._slot_active = False
        if active:
            self.drag_finished.emit()
        return True

    def _sync_logical_size(self) -> None:
        unzoomed = self.unzoomed_size()
        width, height = zoomed_viewport_size(
            (unzoomed.width(), unzoomed.height()), self._zoom
        )
        target = QSize(width, height)
        if self.minimumSize() != target:
            self.setMinimumSize(target)
        if self.size() != target:
            self.resize(target)

    def _scaled_slot_rects(self) -> dict[str, tuple[int, int, int, int]]:
        """1× template slots, then uniform zoom. Padding must not be re-laid out."""
        size = self.unzoomed_size()
        content = (
            BOARD_PADDING,
            BOARD_PADDING,
            max(0, size.width() - 2 * BOARD_PADDING),
            max(0, size.height() - 2 * BOARD_PADDING),
        )
        try:
            rects = slot_rects(self._layout_id, content, self._ratio)
        except ValueError:
            return {}
        z = float(self._zoom)
        if abs(z - 1.0) < 1e-12:
            return rects
        return {
            slot_id: (
                int(round(x * z)),
                int(round(y * z)),
                max(0, int(round(width * z))),
                max(0, int(round(height * z))),
            )
            for slot_id, (x, y, width, height) in rects.items()
        }

    def _discard(self, slot_id: str) -> None:
        widget = self._widgets.pop(slot_id, None)
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()

    def _sync_slot(self, slot_id: str, model: CardViewModel | None) -> None:
        current = self._widgets.get(slot_id)
        if model is None:
            if isinstance(current, EmptySlotWidget):
                return
            self._discard(slot_id)
            empty = EmptySlotWidget(slot_id, self)
            empty.add_clicked.connect(self.add_clicked)
            empty.ref_dropped.connect(self.ref_dropped)
            self._widgets[slot_id] = empty
            empty.show()
            self._raise_overlay()
            return
        if isinstance(current, UltraViewCard):
            current.apply_model(model)
            return
        self._discard(slot_id)
        card = UltraViewCard(model, self)
        card.open_source_requested.connect(self.open_source_requested)
        card.sync_requested.connect(self.sync_requested)
        card.focus_requested.connect(self.focus_requested)
        card.rebind_arm_requested.connect(self.rebind_arm_requested)
        card.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        card.remove_ref_requested.connect(self.remove_ref_requested)
        card.copy_card_image_requested.connect(self.copy_card_image_requested)
        card.selected.connect(self.selected)
        card.ref_dropped.connect(self.ref_dropped)
        card.drag_started.connect(self.drag_started)
        card.drag_finished.connect(self.drag_finished)
        self._widgets[slot_id] = card
        card.show()
        self._raise_overlay()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()
        self._raise_overlay()

    def _raise_overlay(self) -> None:
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

    def _relayout(self) -> None:
        rects = self._scaled_slot_rects()
        for slot_id, (x, y, width, height) in rects.items():
            widget = self._widgets.get(slot_id)
            if widget is not None:
                widget.setGeometry(x, y, max(0, width), max(0, height))

    def slot_id_at(self, pos: QPoint) -> str | None:
        rects = self._scaled_slot_rects()
        px, py = pos.x(), pos.y()
        for slot_id, (x, y, width, height) in rects.items():
            if x <= px <= x + width and y <= py <= y + height:
                return slot_id
        return None

    def note_replace_hover(self, key: str | None) -> None:
        self._replace.hover(key)

    def is_replace_armed(self, key: str) -> bool:
        return self._replace.is_armed(key)

    def clear_replace_hover(self) -> None:
        self._replace.clear()

    def _on_replace_armed(self, key: str) -> None:
        widget = self._widgets.get(key)
        if widget is None:
            return
        geom = widget.geometry()
        self._overlay.set_replace_ring((geom.x(), geom.y(), geom.width(), geom.height()))

    def _on_replace_cleared(self) -> None:
        self._overlay.set_replace_ring(None)

    def is_slot_drag_armed(self) -> bool:
        return self._slot_source is not None

    def is_gesture_active(self) -> bool:
        return bool(self._slot_active)

    def set_preview_quality(self, quality: str) -> None:
        for card in self.card_widgets():
            card.set_preview_quality(quality)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            page = _page_of(self)
            if page is not None:
                page.notify_canvas_click()
            _clear_page_card_selection(self)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._slot_source is not None and (
            event.buttons() & Qt.LeftButton or QWidget.mouseGrabber() is self
        ):
            self._slot_drag_at(event.pos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._slot_source is not None and event.button() == Qt.LeftButton:
            self._finish_slot_drag(event.pos(), event.globalPos())
            return
        super().mouseReleaseEvent(event)

    def handle_card_mouse_press(self, card: UltraViewCard, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._slot_source = card.model().slot_id
        self._slot_press = card.mapTo(self, event.pos())
        self._slot_active = False

    def handle_card_mouse_move(self, card: UltraViewCard, event: QMouseEvent) -> None:
        self._slot_drag_at(card.mapTo(self, event.pos()))

    def handle_card_mouse_release(self, card: UltraViewCard, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._finish_slot_drag(card.mapTo(self, event.pos()), event.globalPos())

    def _slot_drag_at(self, board_pos: QPoint) -> None:
        if self._slot_source is None or self._slot_press is None:
            return
        card = self._widgets.get(self._slot_source)
        if not isinstance(card, UltraViewCard):
            return
        if not self._slot_active:
            if (board_pos - self._slot_press).manhattanLength() < QApplication.startDragDistance():
                return
            self._slot_active = True
            self.drag_started.emit("card")
            if QWidget.mouseGrabber() is None:
                self.grabMouse()
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.4)
            card.setGraphicsEffect(effect)
        target = self.slot_id_at(board_pos)
        geom = card.geometry()
        ghost = (
            geom.x() + board_pos.x() - self._slot_press.x(),
            geom.y() + board_pos.y() - self._slot_press.y(),
            geom.width(),
            geom.height(),
        )
        target_widget = self._widgets.get(target) if target else None
        if target_widget is not None:
            tg = target_widget.geometry()
            highlight = (tg.x(), tg.y(), tg.width(), tg.height())
        else:
            highlight = ghost
        image = getattr(card, "_raw_image", None)
        self._overlay.set_move_preview(
            image,
            ghost,
            highlight,
            legal=target is not None and target != self._slot_source,
        )

    def _finish_slot_drag(self, board_pos: QPoint, global_pos: QPoint | None = None) -> None:
        source = self._slot_source
        active = self._slot_active
        card = self._widgets.get(source) if source else None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if isinstance(card, UltraViewCard):
            card.restore_dim()
        self._overlay.clear()
        self._slot_source = None
        self._slot_press = None
        self._slot_active = False
        if active:
            self.drag_finished.emit()
        if not active or source is None:
            return
        if global_pos is not None and _drop_on_unplaced_tray(self, global_pos):
            if isinstance(card, UltraViewCard):
                model = card.model()
                self.move_to_unplaced_requested.emit(model.section, model.view_id)
            return
        target = self.slot_id_at(board_pos)
        if target is None or target == source:
            return
        self.slot_swap_requested.emit(source, target)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        extracted = extract_ref_strings(event.mimeData())
        pos = QPoint(event.pos())
        event.acceptProposedAction()
        slot_id = self.slot_id_at(pos)
        widget = self._widgets.get(slot_id) if slot_id is not None else None
        occupied = isinstance(widget, UltraViewCard)
        if occupied and (slot_id is None or not self.is_replace_armed(slot_id)):
            self.clear_replace_hover()
            return
        self.clear_replace_hover()
        if extracted is None or slot_id is None:
            return
        self.ref_dropped.emit(slot_id, extracted[0], extracted[1])
