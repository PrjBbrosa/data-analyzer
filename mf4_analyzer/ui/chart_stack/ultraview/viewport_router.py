"""Application-level routing for UltraView canvas viewport gestures."""
from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QMouseEvent, QNativeGestureEvent, QWheelEvent
from PyQt5.QtWidgets import QApplication, QWidget

from .pointer_router import pointer_button_is_down


class ViewportGestureRouter(QObject):
    """Keep pan and zoom continuous while Qt changes the event receiver."""

    _HANDLED_TYPES = frozenset(
        {
            QEvent.KeyPress,
            QEvent.KeyRelease,
            QEvent.MouseButtonPress,
            QEvent.MouseMove,
            QEvent.MouseButtonRelease,
            QEvent.ContextMenu,
            QEvent.Wheel,
            QEvent.NativeGesture,
            QEvent.UngrabMouse,
        }
    )

    def __init__(
        self,
        *,
        canvas_host: QWidget,
        viewport,
        begin_pan: Callable[[object, object], bool],
        update_pan: Callable[[object], None],
        end_pan: Callable[[object], bool],
        zoom_wheel: Callable[[QWheelEvent, QWidget], bool],
        pinch: Callable[[QNativeGestureEvent, QWidget], bool],
        note_space: Callable[[bool], None],
        text_field_has_focus: Callable[[], bool],
        suppress_context_menu: Callable[[object], bool] | None = None,
        is_active: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._canvas_host = canvas_host
        self._viewport = viewport
        self._begin_pan = begin_pan
        self._update_pan = update_pan
        self._end_pan = end_pan
        self._zoom_wheel = zoom_wheel
        self._pinch = pinch
        self._note_space = note_space
        self._text_field_has_focus = text_field_has_focus
        self._suppress_context_menu = suppress_context_menu
        self._is_active = is_active
        self._installed = False
        self._hover_board = None

    def install(self) -> None:
        if self._installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._installed = False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        # Application-level filter: keep a gesture alive while Qt changes the
        # receiver.  Bail out on unrelated event types before walking the
        # parent chain or consulting Board activity.
        if event.type() not in self._HANDLED_TYPES:
            return False
        if self._is_active is not None and not self._is_active():
            return False
        if not self._is_canvas_descendant(watched):
            return False
        event_type = event.type()
        if event_type in (QEvent.KeyPress, QEvent.KeyRelease):
            return self._route_space(event, pressed=event_type == QEvent.KeyPress)
        if event_type == QEvent.MouseButtonPress:
            if self._right_press_cancels_left_gesture(watched, event):
                event.accept()
                return True
            if self._begin_pan(event, watched):
                event.accept()
                return True
            return False
        if event_type == QEvent.MouseMove:
            self._cancel_lost_button_gestures(watched, event)
            if self._viewport.is_panning():
                self._update_pan(event)
                event.accept()
                return True
            self._forward_buttonless_hover(watched, event)
            return False
        if event_type == QEvent.UngrabMouse:
            self._cancel_lost_grab(watched)
            return False
        if event_type == QEvent.MouseButtonRelease:
            if self._end_pan(event):
                event.accept()
                return True
            return False
        if event_type == QEvent.ContextMenu:
            if self._suppress_context_menu is not None and self._suppress_context_menu(event):
                event.accept()
                return True
            return False
        if event_type == QEvent.Wheel and isinstance(event, QWheelEvent):
            # Ctrl/Meta zoom, Shift line-scroll, and pixel-delta scroll are
            # decided in the controller. A plain angle wheel returns False
            # so the scroll area keeps its current vertical step.
            if self._zoom_wheel(event, watched):
                event.accept()
                return True
            return False
        if event_type == QEvent.NativeGesture and isinstance(event, QNativeGestureEvent):
            if self._pinch(event, watched):
                event.accept()
                return True
        return False

    def _right_press_cancels_left_gesture(self, watched, event) -> bool:
        if not isinstance(event, QMouseEvent) or event.button() != Qt.RightButton:
            return False
        cancelled = False
        if (
            self._viewport.is_panning()
            and self._viewport.pan_button() == int(Qt.LeftButton)
        ):
            self._abandon_pan()
            cancelled = True
        host = self._gesture_host(watched)
        if host is not None and self._left_gesture_active(host):
            host.cancel_gesture()
            cancelled = True
        return cancelled

    def _cancel_lost_button_gestures(self, watched, event) -> None:
        if self._viewport.is_panning() and not pointer_button_is_down(
            int(event.buttons()), self._viewport.pan_button()
        ):
            self._abandon_pan()
        host = self._gesture_host(watched)
        if host is None or not isinstance(event, QMouseEvent):
            return
        if self._left_gesture_active(host) and not pointer_button_is_down(
            int(event.buttons()), int(Qt.LeftButton)
        ):
            host.cancel_gesture()

    def _cancel_lost_grab(self, watched) -> None:
        if self._viewport.is_panning():
            self._abandon_pan()
        host = self._gesture_host(watched)
        if host is not None and self._left_gesture_active(host):
            host.cancel_gesture()

    def _abandon_pan(self) -> None:
        """Stop a pan whose button or grab disappeared. Do not scroll further."""
        owner = getattr(self._update_pan, "__self__", None)
        abandon = getattr(owner, "abandon_board_pan", None)
        if callable(abandon):
            abandon()
            return
        end_pan = getattr(owner, "end_board_pan", None)
        if callable(end_pan):
            end_pan()
            return
        self._viewport.end_pan(None)

    def _gesture_host(self, watched):
        if not isinstance(watched, QWidget):
            return None
        current: QWidget | None = watched
        while current is not None:
            if current is self._canvas_host:
                return None
            cancel = getattr(current, "cancel_gesture", None)
            gesture = getattr(current, "gesture", None)
            slot = getattr(current, "is_slot_drag_armed", None)
            if callable(cancel) and (callable(gesture) or callable(slot)):
                return current
            current = current.parentWidget()
        return None

    @staticmethod
    def _left_gesture_active(host) -> bool:
        gesture = getattr(host, "gesture", None)
        if callable(gesture):
            state = gesture()
            if state.is_armed() or state.marquee() is not None:
                return True
        slot = getattr(host, "is_slot_drag_armed", None)
        return bool(callable(slot) and slot())

    def _route_space(self, event, *, pressed: bool) -> bool:
        if event.key() != Qt.Key_Space or event.isAutoRepeat():
            return False
        if self._text_field_has_focus():
            return False
        self._note_space(pressed)
        event.accept()
        return True

    def _forward_buttonless_hover(self, watched, event) -> None:
        """Resolve one buttonless move on the board. Do not consume it."""
        if not isinstance(event, QMouseEvent) or event.buttons() != Qt.NoButton:
            return
        board = self._board_for_hover(watched)
        if board is None:
            # An unaccepted move bubbles to the canvas stack. That receiver is
            # not inside the board, but the pointer has not left it.
            if self._event_still_over_tracked_board(event):
                return
            self._clear_tracked_hover()
            return
        self._hover_board = board
        try:
            board.note_buttonless_hover(watched, event)
        except RuntimeError:
            self._hover_board = None

    def _board_for_hover(self, watched):
        if not isinstance(watched, QWidget):
            return None
        current: QWidget | None = watched
        while current is not None:
            note = getattr(current, "note_buttonless_hover", None)
            if callable(note):
                return current
            if current is self._canvas_host:
                return None
            current = current.parentWidget()
        return None

    def _event_still_over_tracked_board(self, event) -> bool:
        board = self._hover_board
        if board is None or not isinstance(board, QWidget):
            return False
        if not isinstance(event, QMouseEvent):
            return False
        try:
            if not board.isVisible():
                return False
            local = board.mapFromGlobal(event.globalPos())
        except RuntimeError:
            return False
        return board.rect().contains(local)

    def _clear_tracked_hover(self) -> None:
        board = self._hover_board
        self._hover_board = None
        if board is None:
            return
        clear = getattr(board, "clear_buttonless_hover", None)
        if not callable(clear):
            return
        try:
            clear()
        except RuntimeError:
            return

    def _is_canvas_descendant(self, watched) -> bool:
        if not self._canvas_host.isVisible():
            return False
        if not isinstance(watched, QWidget):
            return False
        current: QWidget | None = watched
        while current is not None:
            if current is self._canvas_host:
                return True
            current = current.parentWidget()
        return False
