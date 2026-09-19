"""Application-filter P routing and read-only pointer hit tests.

``PinKeyRouter`` is the unique app-level filter. It never binds a canvas,
never writes a collection, and never constructs an owner. The coordinator
binds only after a confirmed hit.
"""
from __future__ import annotations

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PyQt5.QtGui import QCursor, QKeyEvent
from PyQt5.QtWidgets import QApplication, QWidget

from ...pg_canvas.frf_canvas import PgFrfCanvas
from ...pg_canvas.heatmap_canvas import PgHeatmapCanvas
from ...pg_canvas.line_canvas import PgLineCanvas
from ...pg_canvases import TimeDomainCanvasPG
from ...pinned_cursor_facts import _finite
from ..cursor_pill import CursorPill
from ..ultraview.author_widgets import is_text_input_widget


_P_KEY_EVENTS = frozenset({QEvent.ShortcutOverride, QEvent.KeyPress})


def _widget_alive(widget):
    if widget is None:
        return False
    try:
        return not sip.isdeleted(widget)
    except RuntimeError:
        return False


def _canvas_viewport(canvas):
    glw = getattr(canvas, "_glw", None)
    if glw is None:
        return None
    try:
        viewport = glw.viewport()
    except RuntimeError:
        return None
    return viewport if isinstance(viewport, QWidget) else None


class PinKeyRouter(QObject):
    """One application event filter for unmodified P.

    Each ShortcutOverride/KeyPress computes a fresh read-only hit. The two
    events never share a cached result, so window and target are re-validated
    on KeyPress. Within one eventFilter call the hit is used once (accept or
    pin), never computed a second time for the same QEvent.
    """

    def __init__(self, parent, ports):
        super().__init__(parent)
        self._ports = ports
        self._filter_installed = False
        self.last_mouse_global = QPoint()
        self._hit_generation = 0

    @property
    def application_filter_installed(self) -> bool:
        return bool(self._filter_installed)

    def invalidate_tokens(self) -> None:
        self._hit_generation += 1

    def install_application_filter(self) -> None:
        if self._filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._filter_installed = True

    def remove_application_filter(self) -> None:
        if not self._filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except RuntimeError:
                pass
        self._filter_installed = False

    def sync_application_filter(self) -> None:
        host = self._ports.host_widget()
        if _widget_alive(host) and host.isVisible():
            self.install_application_filter()
            return
        self.remove_application_filter()

    def eventFilter(self, watched, event):  # noqa: N802
        etype = event.type()
        if etype not in _P_KEY_EVENTS:
            return False
        if not self._is_unmodified_p(event):
            return False
        if event.isAutoRepeat():
            return False
        # Fresh hit per Qt event. Do not cache by id(event): CPython reuses ids.
        hit = self._compute_hit()
        if etype == QEvent.ShortcutOverride:
            if hit is not None:
                event.accept()
                return True
            return False
        if hit is None:
            return False
        on_hit = getattr(self._ports, "on_confirmed_hit", None)
        if callable(on_hit):
            on_hit(hit)
        event.accept()
        return True

    def hit_owner(self):
        """Read-only hit. Does not bind a canvas or mint an owner."""
        return self._compute_hit()

    def pin_eligible(self) -> bool:
        return self.hit_owner() is not None

    def _compute_hit(self):
        app = QApplication.instance()
        if app is None:
            return None
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return None
        focus = app.focusWidget()
        if focus is not None and (
            bool(focus.testAttribute(Qt.WA_InputMethodEnabled))
            or is_text_input_widget(focus)
        ):
            return None
        host = self._ports.host_widget()
        widget = self.widget_under_mouse()
        if widget is None:
            return None
        ultraview = self._ports.ultraview_widget()
        if ultraview is not None and self._is_under(widget, ultraview):
            return None
        if self._is_under_type(widget, CursorPill):
            return None
        canvas = self.canvas_from_widget(widget)
        if canvas is None or isinstance(canvas, PgHeatmapCanvas):
            return None
        if not _widget_alive(canvas) or not canvas.isVisible():
            return None
        if _widget_alive(host) and not canvas.isVisibleTo(host):
            return None
        window = canvas.window()
        active = app.activeWindow()
        if window is None or active is None or window is not active:
            return None
        belongs = bool(self._ports.canvas_belongs(canvas))
        if not belongs:
            return None
        if not self._ports.source_on_screen(canvas):
            return None
        mode = self._ports.cursor_mode(canvas)
        if mode not in {"single", "dual"}:
            return None
        if self._ports.gesture_busy(canvas):
            return None
        domain = self._ports.domain_for(canvas)
        if domain is None:
            return None
        viewport = _canvas_viewport(canvas)
        if viewport is None or not viewport.isVisible():
            return None
        global_pos = self.mouse_global()
        local = viewport.mapFromGlobal(global_pos)
        if not viewport.rect().contains(local):
            return None
        if not self.in_data_viewport(canvas, domain, local):
            return None
        return canvas, domain, local

    def in_data_viewport(self, canvas, domain, viewport_pos) -> bool:
        if domain in {"time", "channel"}:
            return _finite(self.physical_x(canvas, domain, viewport_pos)) is not None
        if domain == "frequency":
            host_rect = getattr(canvas, "frequency_cursor_host_rect", None)
            rect = host_rect() if callable(host_rect) else None
            if rect is None or not QRect(rect).isValid():
                return False
            viewport = _canvas_viewport(canvas)
            if viewport is None:
                return False
            if isinstance(rect, QRect):
                # Descendant ← ancestor. Never canvas.mapTo(viewport, …).
                top_left = viewport.mapFrom(canvas, rect.topLeft())
                bottom_right = viewport.mapFrom(canvas, rect.bottomRight())
                local_rect = QRect(top_left, bottom_right)
                if not local_rect.contains(viewport_pos):
                    return False
            return _finite(self.physical_x(canvas, domain, viewport_pos)) is not None
        if domain == "frf":
            return _finite(self.physical_x(canvas, domain, viewport_pos)) is not None
        return False

    def physical_x(self, canvas, domain, viewport_pos):
        if domain in {"time", "channel"}:
            fn = getattr(canvas, "data_x_from_viewport_pos", None)
            return _finite(fn(viewport_pos) if callable(fn) else None)
        glw = getattr(canvas, "_glw", None)
        if glw is None:
            return None
        try:
            scene_pos = glw.mapToScene(viewport_pos)
        except (RuntimeError, TypeError):
            return None
        if domain == "frequency":
            plot = getattr(canvas, "_plot_amp", None)
            vb = getattr(plot, "vb", None)
            if vb is None:
                return None
            try:
                if not vb.sceneBoundingRect().contains(scene_pos):
                    return None
                return _finite(vb.mapSceneToView(scene_pos).x())
            except (RuntimeError, TypeError, ValueError):
                return None
        plots = getattr(canvas, "plots", None) or ()
        for plot in plots:
            vb = getattr(plot, "vb", None)
            if vb is None:
                continue
            try:
                if not vb.sceneBoundingRect().contains(scene_pos):
                    continue
                view_x = float(vb.mapSceneToView(scene_pos).x())
            except (RuntimeError, TypeError, ValueError):
                continue
            converter = getattr(canvas, "_view_x_to_hz", None)
            if callable(converter):
                return _finite(converter(view_x))
            return _finite(view_x)
        return None

    def widget_under_mouse(self):
        app = QApplication.instance()
        pos = self.mouse_global()
        widget = app.widgetAt(pos) if app is not None else None
        if _widget_alive(widget):
            return widget
        fallback = getattr(self._ports, "fallback_widget_at", None)
        if callable(fallback):
            child = fallback(pos)
            if _widget_alive(child):
                return child
        return None

    def mouse_global(self) -> QPoint:
        pos = QCursor.pos()
        app = QApplication.instance()
        if app is not None and app.widgetAt(pos) is not None:
            return pos
        stored = self.last_mouse_global
        if stored is not None and not QPoint(stored).isNull():
            return QPoint(stored)
        return pos

    @staticmethod
    def _is_unmodified_p(event: QKeyEvent) -> bool:
        if event.key() != Qt.Key_P:
            return False
        mods = event.modifiers()
        blocked = Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier | Qt.ShiftModifier
        return not bool(mods & blocked)

    @staticmethod
    def _is_under(widget, ancestor) -> bool:
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def _is_under_type(widget, cls) -> bool:
        current = widget
        while current is not None:
            if isinstance(current, cls):
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def canvas_from_widget(widget):
        current = widget
        while current is not None:
            if isinstance(current, PgHeatmapCanvas):
                return None
            if isinstance(current, (TimeDomainCanvasPG, PgLineCanvas, PgFrfCanvas)):
                return current
            current = current.parentWidget()
        return None
