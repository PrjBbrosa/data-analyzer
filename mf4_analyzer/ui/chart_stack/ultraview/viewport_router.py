"""Application-level routing for UltraView canvas viewport gestures."""
from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QNativeGestureEvent, QWheelEvent
from PyQt5.QtWidgets import QApplication, QWidget


class ViewportGestureRouter(QObject):
    """Keep pan and zoom continuous while Qt changes the event receiver."""

    def __init__(
        self,
        *,
        canvas_host: QWidget,
        viewport,
        begin_pan: Callable[[object], bool],
        update_pan: Callable[[object], None],
        end_pan: Callable[[object], bool],
        zoom_wheel: Callable[[QWheelEvent, QWidget], bool],
        pinch: Callable[[QNativeGestureEvent, QWidget], bool],
        note_space: Callable[[bool], None],
        text_field_has_focus: Callable[[], bool],
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
        self._is_active = is_active
        self._installed = False

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
        # This is an QApplication-level filter solely to keep a gesture alive
        # while Qt changes the receiver beneath it.  It must be inert whenever
        # the Board is hidden or another top-level window is active.
        if self._is_active is not None and not self._is_active():
            return False
        if not self._is_canvas_descendant(watched):
            return False
        event_type = event.type()
        if event_type in (QEvent.KeyPress, QEvent.KeyRelease):
            return self._route_space(event, pressed=event_type == QEvent.KeyPress)
        if event_type == QEvent.MouseButtonPress:
            if self._begin_pan(event):
                event.accept()
                return True
            return False
        if event_type == QEvent.MouseMove:
            if self._viewport.is_panning():
                self._update_pan(event)
                event.accept()
                return True
            return False
        if event_type == QEvent.MouseButtonRelease:
            if self._end_pan(event):
                event.accept()
                return True
            return False
        if event_type == QEvent.Wheel and isinstance(event, QWheelEvent):
            if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
                if self._zoom_wheel(event, watched):
                    event.accept()
                    return True
            return False
        if event_type == QEvent.NativeGesture and isinstance(event, QNativeGestureEvent):
            if self._pinch(event, watched):
                event.accept()
                return True
        return False

    def _route_space(self, event, *, pressed: bool) -> bool:
        if event.key() != Qt.Key_Space or event.isAutoRepeat():
            return False
        if self._text_field_has_focus():
            return False
        self._note_space(pressed)
        event.accept()
        return True

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
