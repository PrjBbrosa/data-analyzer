# mf4_analyzer/ui/side_panels.py
"""Collapsible side panels: HIDDEN/PEEK/PINNED state machine + widgets.

The reducer (``reduce_panel``) is intentionally Qt-free (it makes no Qt calls),
so the transition logic is unit-testable without an event loop.
``SidePanelController`` executes the emitted effects against real Qt widgets.
"""
import time
from enum import Enum, auto

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget


class PanelState(Enum):
    HIDDEN = auto()   # splitter slot 0, panel invisible, strip visible
    PEEK = auto()     # panel reparented into a floating overlay, strip visible
    PINNED = auto()   # panel docked in splitter, pushes canvas, strip hidden


class Side(Enum):
    LEFT = auto()
    RIGHT = auto()


class Ev(Enum):
    HOVER = auto()            # mouse entered strip (after open debounce)
    CLICK = auto()            # strip left-clicked
    OVERLAY_LEFT = auto()     # mouse left (overlay ∪ strip)
    OVERLAY_ENTERED = auto()  # mouse re-entered (overlay ∪ strip)
    COLLAPSE_TIMEOUT = auto() # auto-hide timer fired
    DRAG_COLLAPSED = auto()   # splitter dragged to <= threshold while pinned


class Effect(Enum):
    ENTER_PEEK = auto()       # reparent panel -> overlay, size+position, show, raise
    EXIT_PEEK = auto()        # reparent panel -> splitter slot 0, setVisible(False)
    DOCK = auto()             # reparent -> splitter, restore width, show; (strip hidden via state)
    COLLAPSE_PINNED = auto()  # setVisible(False), slot -> 0 (panel already in splitter)
    START_TIMER = auto()
    STOP_TIMER = auto()


# (current_state, event) -> (next_state, effects tuple). Missing keys are no-ops.
_TRANSITIONS = {
    (PanelState.HIDDEN, Ev.HOVER): (PanelState.PEEK, (Effect.ENTER_PEEK,)),
    (PanelState.HIDDEN, Ev.CLICK): (PanelState.PINNED, (Effect.DOCK,)),
    (PanelState.PEEK, Ev.CLICK): (PanelState.PINNED, (Effect.STOP_TIMER, Effect.DOCK)),
    (PanelState.PEEK, Ev.OVERLAY_LEFT): (PanelState.PEEK, (Effect.START_TIMER,)),
    (PanelState.PEEK, Ev.OVERLAY_ENTERED): (PanelState.PEEK, (Effect.STOP_TIMER,)),
    (PanelState.PEEK, Ev.COLLAPSE_TIMEOUT): (PanelState.HIDDEN, (Effect.EXIT_PEEK,)),
    (PanelState.PINNED, Ev.DRAG_COLLAPSED): (PanelState.HIDDEN, (Effect.COLLAPSE_PINNED,)),
    (PanelState.PINNED, Ev.CLICK): (PanelState.HIDDEN, (Effect.COLLAPSE_PINNED,)),
}


def reduce_panel(state, event):
    """Pure transition: returns ``(next_state, effects)``; no-op stays put."""
    return _TRANSITIONS.get((state, event), (state, ()))


def strip_visible_for(state):
    """Edge strip is shown only while the panel is HIDDEN or PEEK."""
    return state in (PanelState.HIDDEN, PanelState.PEEK)


def _widget_alive(widget):
    if widget is None:
        return False
    try:
        return not sip.isdeleted(widget)
    except (RuntimeError, TypeError):
        return False


# QEvent.Destroy is 16. This PyQt5 build does not export the name, but the
# widget destructor still sends it while child QObjects (this controller) are
# alive — the moment the application filter has to be removed.
_QEVENT_DESTROY = 16

# Events the peek watch has to see. Everything else returns immediately so a
# PEEK-only application filter cannot turn into a poll or eat business input.
_PEEK_WATCH_EVENTS = frozenset({
    int(QEvent.Enter),
    int(QEvent.Leave),
    int(QEvent.MouseButtonPress),
    int(QEvent.MouseButtonRelease),
    int(QEvent.Hide),
    int(QEvent.Close),
    _QEVENT_DESTROY,
    int(QEvent.WindowDeactivate),
    int(QEvent.WindowStateChange),
})


class SidePanelStrip(QFrame):
    """A thin, faint, clickable edge rail shown when its side is collapsed.

    Hover (after a short debounce) requests a peek; left-click requests a pin.
    """
    peek_requested = pyqtSignal(object)  # Side
    pin_requested = pyqtSignal(object)   # Side

    WIDTH_PX = 10
    PILL_FILL = "#ffffff"
    PILL_HOVER_FILL = "#f8fbff"
    PILL_BORDER = "#dbe2eb"
    PILL_HOVER_BORDER = "#9fc5ff"
    CHEVRON_COLOR = "#1769e0"
    PILL_RADIUS = 3.0

    def __init__(self, side, hover_delay_ms=150, parent=None):
        super().__init__(parent)
        self._side = side
        self._hovered = False
        self.setObjectName("sidePanelStrip")
        self.setProperty("side", "left" if side == Side.LEFT else "right")
        self.setFixedWidth(self.WIDTH_PX)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setCursor(Qt.PointingHandCursor)
        chevron = "‹" if side == Side.LEFT else "›"  # ‹ / ›  (points inward)
        self.setToolTip("文件 / 通道" if side == Side.LEFT else "Inspector")
        self._chevron = chevron
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(hover_delay_ms)
        self._hover_timer.timeout.connect(lambda: self.peek_requested.emit(self._side))

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        self._hover_timer.start()
        super().enterEvent(event) if event is not None else None

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        self._hover_timer.stop()
        super().leaveEvent(event) if event is not None else None

    def hideEvent(self, event):
        # Window hide/minimize/close hides this rail and must not let a pending
        # 150 ms open timer peek afterwards.
        self._hovered = False
        self._hover_timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._hover_timer.stop()
            self.pin_requested.emit(self._side)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        pill = QRectF(1.0, 2.0, max(1.0, self.width() - 2.0), max(1.0, self.height() - 4.0))
        p.setPen(QPen(QColor(self.PILL_HOVER_BORDER if self._hovered else self.PILL_BORDER), 1.0))
        p.setBrush(QColor(self.PILL_HOVER_FILL if self._hovered else self.PILL_FILL))
        p.drawRoundedRect(pill, self.PILL_RADIUS, self.PILL_RADIUS)

        center = self.rect().center()
        y = float(center.y())
        if self._side == Side.LEFT:
            points = (
                QPointF(6.4, y - 5.0),
                QPointF(3.2, y),
                QPointF(6.4, y + 5.0),
            )
        else:
            points = (
                QPointF(3.6, y - 5.0),
                QPointF(6.8, y),
                QPointF(3.6, y + 5.0),
            )
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(self.CHEVRON_COLOR), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(points[0], points[1])
        p.drawLine(points[1], points[2])
        p.end()


class PeekOverlay(QFrame):
    """Floating container for the peeked panel.

    MUST be a child widget (parent = central widget), never a top-level
    frameless window, so macOS does not paint a native square shadow
    (see commit 44786538). Raised above the canvas via ``raise_()``.
    """
    mouse_entered = pyqtSignal()
    mouse_left = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("peekOverlay")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._panel = None
        self.hide()

    def set_panel(self, panel):
        """Reparent ``panel`` into this overlay (filling it).

        Evicts any previously hosted panel first so the overlay never stacks
        more than one child, regardless of caller discipline.
        """
        if self._panel is panel:
            return
        if self._panel is not None:
            self._lay.removeWidget(self._panel)
        self._panel = panel
        panel.setParent(self)
        self._lay.addWidget(panel)
        panel.show()

    def take_panel(self):
        """Detach the current panel from the layout and return it.

        The returned panel still has this overlay as its Qt parent; the caller
        MUST reparent it synchronously (before yielding to the event loop) so it
        is not destroyed if the overlay is torn down mid-transition.
        """
        panel = self._panel
        if panel is not None:
            self._lay.removeWidget(panel)
            self._panel = None
        return panel

    def enterEvent(self, event):
        self.mouse_entered.emit()
        super().enterEvent(event) if event is not None else None

    def leaveEvent(self, event):
        self.mouse_left.emit()
        super().leaveEvent(event) if event is not None else None


class SidePanelController(QObject):
    """Drives one side's HIDDEN/PEEK/PINNED lifecycle against real widgets.

    Pass ``parent`` = the owning window/host so the controller shares its
    lifetime. The strip/overlay signals are connected with lambdas that hold a
    strong reference to this controller, so it must not be GC'd before the
    widgets it drives are torn down.
    """

    state_changed = pyqtSignal(object)   # emits new PanelState

    PEEK_EXTRA_PX = 24      # overlay is "a bit wider" than the docked width
    COLLAPSE_THRESHOLD = 24  # drag width <= this => collapsed

    def __init__(self, side, splitter, panel, panel_index, strip, overlay,
                 host, collapse_delay_ms=600, default_width=250,
                 canvas=None, peek_width=None, parent=None):
        super().__init__(parent)
        self._side = side
        self._splitter = splitter
        self._panel = panel
        self._index = panel_index   # insertion position when re-docking
        self._strip = strip
        self._overlay = overlay
        self._host = host
        self._remembered_width = default_width
        # Optional floor for the peek overlay width, used to make the two side
        # overlays symmetric (e.g. the narrow navigator peeks out to the same
        # width as the docked inspector). None = no floor.
        self._peek_width = peek_width
        # The pane that should absorb this panel's width changes (the canvas).
        # Kept as a live widget ref, not a fixed index: when the OTHER side
        # peeks out it reparents its panel and the splitter is renumbered, so
        # fixed indices drift. Look it up via indexOf at use time instead.
        self._canvas = canvas
        self.state = PanelState.PINNED

        self._collapse_delay_ms = int(collapse_delay_ms)
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(self._collapse_delay_ms)
        self._collapse_timer.timeout.connect(self._on_collapse_timeout)
        # Controller-owned transient state. Initialized here and cleared in
        # _clear_peek_tracking on exit, hide, and destroy.
        self._app_filter_installed = False
        self._in_strip = False
        self._in_overlay = False
        self._grace_deadline = None
        self._pressed_inside = False
        self._defer_until_release = False
        self._ending_peek = False
        self._deactivate_pending = False
        self._transient_widget = None
        self._reeval_timer = QTimer(self)
        self._reeval_timer.setSingleShot(True)
        self._reeval_timer.setInterval(0)
        self._reeval_timer.timeout.connect(self._reevaluate_interaction)

        strip.peek_requested.connect(lambda _s: self._dispatch(Ev.HOVER))
        strip.pin_requested.connect(lambda _s: self._dispatch(Ev.CLICK))
        overlay.mouse_left.connect(lambda: self._dispatch(Ev.OVERLAY_LEFT))
        overlay.mouse_entered.connect(lambda: self._dispatch(Ev.OVERLAY_ENTERED))

        self._apply_strip_visibility()

    # ---- event entry points ----
    def _live_index(self):
        """Current index of this panel in the splitter, or -1 if it has been
        reparented out (e.g. the panel is mid-peek in the overlay, or the
        OTHER side's peek renumbered the splitter)."""
        return self._splitter.indexOf(self._panel)

    def on_splitter_moved(self):
        """Call from QSplitter.splitterMoved. Collapse if dragged to the edge."""
        if self.state != PanelState.PINNED:
            return
        idx = self._live_index()
        if idx < 0:
            return  # panel not in the splitter right now
        if self._splitter.sizes()[idx] <= self.COLLAPSE_THRESHOLD:
            self._dispatch(Ev.DRAG_COLLAPSED)

    def _on_collapse_timeout(self):
        # A Qt timer is an earliest-request hint. Re-read the clock, the
        # pointer, an owned popup/dialog, and an in-progress drag. An unrelated
        # activePopupWidget() must not restart this timer.
        if self.state != PanelState.PEEK or self._ending_peek:
            return
        if self._still_inside():
            self._stop_collapse_timer()
            return
        if self._restart_remaining_grace():
            return
        if self._drag_blocks_collapse():
            self._defer_until_release = True
            self._grace_deadline = None
            return
        owned = self._owned_transient()
        if owned is not None:
            self._listen_for_transient_end(owned)
            self._grace_deadline = None
            return
        self._grace_deadline = None
        self._dispatch(Ev.COLLAPSE_TIMEOUT)

    def _stop_strip_hover_timer(self):
        timer = getattr(self._strip, "_hover_timer", None)
        if timer is not None:
            timer.stop()

    def _stop_collapse_timer(self):
        self._collapse_timer.stop()
        self._grace_deadline = None
        delay = self._collapse_delay_ms
        if self._collapse_timer.interval() != delay:
            self._collapse_timer.setInterval(delay)

    def _arm_collapse_once(self):
        """Start the 600 ms grace unless it is already running."""
        if self.state != PanelState.PEEK or self._ending_peek:
            return
        if self._collapse_timer.isActive():
            return
        delay = self._collapse_delay_ms
        if self._collapse_timer.interval() != delay:
            self._collapse_timer.setInterval(delay)
        self._grace_deadline = time.monotonic() + delay / 1000.0
        self._collapse_timer.start()

    def _restart_remaining_grace(self):
        """Qt woke early. Keep the original deadline; do not treat the fire as elapsed."""
        deadline = self._grace_deadline
        if deadline is None:
            return False
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 2:
            return False
        self._collapse_timer.stop()
        self._collapse_timer.setInterval(remaining_ms)
        self._collapse_timer.start()
        return True

    def _install_peek_watch(self):
        if self._app_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._app_filter_installed = True
        self._sync_regions_from_pointer()

    def _remove_app_filter(self):
        if not self._app_filter_installed:
            return
        self._app_filter_installed = False
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.removeEventFilter(self)
        except RuntimeError:
            pass

    def _clear_peek_tracking(self):
        self._stop_collapse_timer()
        self._reeval_timer.stop()
        self._stop_strip_hover_timer()
        self._in_strip = False
        self._in_overlay = False
        self._pressed_inside = False
        self._defer_until_release = False
        self._deactivate_pending = False
        self._drop_transient_listen()
        self._remove_app_filter()

    def _drop_watch_for_destroy(self):
        self._ending_peek = True
        try:
            self._collapse_timer.stop()
            self._reeval_timer.stop()
            self._grace_deadline = None
            self._transient_widget = None
            self._in_strip = False
            self._in_overlay = False
            self._pressed_inside = False
            self._defer_until_release = False
            self._deactivate_pending = False
            self._stop_strip_hover_timer()
            self._remove_app_filter()
        finally:
            self._ending_peek = False

    def _end_peek_lifecycle(self, collapse):
        """Hide, minimize, deactivate, or close: drop timers and the app filter.

        An owned modal/popup keeps the peeked panel mounted so it can finish.
        The close signal re-evaluates afterwards.
        """
        if self._ending_peek:
            return
        self._ending_peek = True
        try:
            owned = self._owned_transient() if self.state == PanelState.PEEK else None
            self._stop_collapse_timer()
            self._reeval_timer.stop()
            self._stop_strip_hover_timer()
            self._pressed_inside = False
            self._defer_until_release = False
            self._deactivate_pending = False
            self._in_strip = False
            self._in_overlay = False
            if owned is not None:
                self._listen_for_transient_end(owned)
                self._remove_app_filter()
                return
            self._drop_transient_listen()
            self._remove_app_filter()
            if collapse and self.state == PanelState.PEEK:
                self._dispatch(Ev.COLLAPSE_TIMEOUT)
        finally:
            self._ending_peek = False

    def _note_region(self, widget, inside):
        if widget is self._strip:
            self._in_strip = bool(inside)
        elif widget is self._overlay:
            self._in_overlay = bool(inside)
        else:
            return
        if self.state != PanelState.PEEK or self._ending_peek:
            return
        if inside:
            self._defer_until_release = False
            self._dispatch(Ev.OVERLAY_ENTERED)
            return
        # Moving onto the other half of the union leaves the pointer inside, so
        # that leave must not arm the grace. A stale region flag cannot swallow
        # a leave once the pointer is actually outside the union.
        if self._pointer_over_surface():
            return
        self._in_strip = False
        self._in_overlay = False
        self._dispatch(Ev.OVERLAY_LEFT)

    def _schedule_reeval(self):
        if self.state != PanelState.PEEK or self._ending_peek:
            return
        if not self._reeval_timer.isActive():
            self._reeval_timer.start()

    def _reevaluate_interaction(self):
        if self.state != PanelState.PEEK or self._ending_peek:
            return
        deferred = self._defer_until_release
        deactivate = self._deactivate_pending
        self._defer_until_release = False
        self._deactivate_pending = False
        if deactivate and self._owned_transient() is None:
            self._remove_app_filter()
            self._dispatch(Ev.COLLAPSE_TIMEOUT)
            return
        if QApplication.mouseButtons() == Qt.NoButton:
            self._pressed_inside = False
        if self._still_inside():
            self._stop_collapse_timer()
            self._install_peek_watch()
            return
        if self._drag_blocks_collapse():
            self._defer_until_release = True
            self._stop_collapse_timer()
            self._install_peek_watch()
            return
        owned = self._owned_transient()
        if owned is not None:
            self._listen_for_transient_end(owned)
            self._stop_collapse_timer()
            self._install_peek_watch()
            return
        if deferred:
            self._dispatch(Ev.COLLAPSE_TIMEOUT)
            return
        self._install_peek_watch()
        self._arm_collapse_once()

    def _still_inside(self):
        # A live hit on the strip, overlay, or panel wins. A live hit on
        # anything else means a stale enter/leave flag must not keep the peek.
        if self._pointer_over_surface():
            return True
        if self._widget_under_pointer() is not None:
            return False
        return self._in_strip or self._in_overlay

    def _pointer_over_surface(self):
        return self._is_surface_descendant(self._widget_under_pointer())

    def _drag_blocks_collapse(self):
        if not self._pressed_inside:
            return False
        return QApplication.mouseButtons() != Qt.NoButton

    def _widget_under_pointer(self):
        app = QApplication.instance()
        if app is None:
            return None
        widget = app.widgetAt(QCursor.pos())
        if _widget_alive(widget):
            return widget
        host = self._host
        if not _widget_alive(host) or not host.isVisible():
            return None
        local = host.mapFromGlobal(QCursor.pos())
        if not host.rect().contains(local):
            return None
        child = host.childAt(local)
        return child if _widget_alive(child) else None

    def _sync_regions_from_pointer(self):
        widget = self._widget_under_pointer()
        self._in_strip = self._is_descendant_of(widget, self._strip)
        self._in_overlay = (
            self._is_descendant_of(widget, self._overlay)
            or self._is_descendant_of(widget, self._panel)
        )

    def _host_window(self):
        host = self._host
        if not _widget_alive(host):
            return None
        window = host.window()
        return window if _widget_alive(window) else None

    def _is_host_or_window(self, widget):
        if not _widget_alive(widget):
            return False
        if widget is self._host:
            return True
        return widget is self._host_window()

    def _is_descendant_of(self, widget, ancestor):
        if not _widget_alive(widget) or not _widget_alive(ancestor):
            return False
        seen = set()
        current = widget
        while _widget_alive(current) and id(current) not in seen:
            if current is ancestor:
                return True
            seen.add(id(current))
            current = current.parentWidget()
        return False

    def _is_surface_descendant(self, widget):
        return (
            self._is_descendant_of(widget, self._strip)
            or self._is_descendant_of(widget, self._overlay)
            or self._is_descendant_of(widget, self._panel)
        )

    def _owned_transient(self):
        app = QApplication.instance()
        if app is None:
            return None
        for widget in (app.activePopupWidget(), app.activeModalWidget()):
            if self._transient_belongs(widget):
                return widget
        return None

    def _transient_belongs(self, widget):
        if not _widget_alive(widget):
            return False
        if self._is_surface_descendant(widget):
            return True
        return self._popup_owned_by_editors(widget)

    def _is_owned_transient_window(self, widget):
        if not isinstance(widget, QWidget) or not _widget_alive(widget):
            return False
        if not widget.isWindow():
            return False
        if self._is_host_or_window(widget):
            return False
        return self._transient_belongs(widget)

    def _popup_owned_by_editors(self, widget):
        panel = self._panel
        if not _widget_alive(panel):
            return False
        from PyQt5.QtWidgets import QComboBox, QLineEdit

        try:
            edits = panel.findChildren(QLineEdit)
            combos = panel.findChildren(QComboBox)
        except RuntimeError:
            return False
        panel_window = panel.window()
        for edit in edits:
            completer = edit.completer()
            if completer is None:
                continue
            popup = completer.popup()
            if not _widget_alive(popup):
                continue
            if widget is popup or self._is_descendant_of(widget, popup):
                return True
            popup_window = popup.window()
            if (
                _widget_alive(popup_window)
                and popup_window is not panel_window
                and (widget is popup_window or widget.window() is popup_window)
            ):
                return True
        for combo in combos:
            view = combo.view()
            if not _widget_alive(view):
                continue
            if widget is view or self._is_descendant_of(widget, view):
                return True
            view_window = view.window()
            if (
                _widget_alive(view_window)
                and view_window is not panel_window
                and (widget is view_window or widget.window() is view_window)
            ):
                return True
        return False

    def _listen_for_transient_end(self, widget):
        if not _widget_alive(widget) or widget is self._transient_widget:
            return
        self._drop_transient_listen()
        self._transient_widget = widget
        about = getattr(widget, "aboutToHide", None)
        if about is not None:
            about.connect(self._on_transient_about_to_hide)
        finished = getattr(widget, "finished", None)
        if finished is not None:
            finished.connect(self._on_transient_finished)
        widget.destroyed.connect(self._on_transient_destroyed)

    def _drop_transient_listen(self):
        widget = self._transient_widget
        self._transient_widget = None
        if not _widget_alive(widget):
            return
        for name, slot in (
            ("aboutToHide", self._on_transient_about_to_hide),
            ("finished", self._on_transient_finished),
            ("destroyed", self._on_transient_destroyed),
        ):
            signal = getattr(widget, name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

    def _on_transient_about_to_hide(self):
        self._schedule_reeval()

    def _on_transient_finished(self, _result=0):
        self._drop_transient_listen()
        self._schedule_reeval()

    def _on_transient_destroyed(self, _obj=None):
        self._transient_widget = None
        if self.state == PanelState.PEEK and not self._ending_peek:
            self._schedule_reeval()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if not self._app_filter_installed or self._ending_peek:
            return False
        # The application filter also sees QWindow and other non-widgets.
        if not isinstance(watched, QWidget):
            return False
        etype = int(event.type())
        if etype not in _PEEK_WATCH_EVENTS:
            return False
        if etype == QEvent.Enter and (
            watched is self._strip or watched is self._overlay
        ):
            self._note_region(watched, True)
            return False
        if etype == QEvent.Leave and (
            watched is self._strip or watched is self._overlay
        ):
            self._note_region(watched, False)
            return False
        if etype == QEvent.MouseButtonPress:
            if self._is_surface_descendant(watched):
                self._pressed_inside = True
            return False
        if etype == QEvent.MouseButtonRelease:
            if self._pressed_inside or self._defer_until_release:
                self._schedule_reeval()
            return False
        if etype in (QEvent.Hide, QEvent.Close):
            if self._is_host_or_window(watched):
                self._end_peek_lifecycle(collapse=True)
                return False
            if self._is_owned_transient_window(watched):
                self._schedule_reeval()
            return False
        if etype == _QEVENT_DESTROY:
            if self._is_host_or_window(watched):
                self._drop_watch_for_destroy()
            return False
        if etype == QEvent.WindowDeactivate:
            # Deactivate can arrive before an owned popup is registered. Drop
            # the grace timer now and re-check on the next turn so a menu or
            # dialog that belongs to this panel is not torn down under itself.
            if watched is self._host_window() and self.state == PanelState.PEEK:
                self._deactivate_pending = True
                self._stop_collapse_timer()
                self._stop_strip_hover_timer()
                self._remove_app_filter()
                self._schedule_reeval()
            return False
        if etype == QEvent.WindowStateChange:
            window = self._host_window()
            if (
                watched is window
                and _widget_alive(window)
                and window.isMinimized()
            ):
                self._end_peek_lifecycle(collapse=True)
            return False
        return False

    # ---- core dispatch ----
    def _dispatch(self, event):
        if (
            event == Ev.HOVER
            and self.state == PanelState.HIDDEN
            and not self._peek_can_fit()
        ):
            return
        new_state, effects = reduce_panel(self.state, event)
        self.state = new_state
        for eff in effects:
            self._run_effect(eff)
        self._apply_strip_visibility()
        self.state_changed.emit(self.state)

    def _run_effect(self, eff):
        if eff == Effect.ENTER_PEEK:
            self._remember_width_if_docked()
            self._overlay.set_panel(self._panel)
            self._position_overlay()
            self._overlay.show()
            self._overlay.raise_()
            self._install_peek_watch()
        elif eff == Effect.EXIT_PEEK:
            self._clear_peek_tracking()
            self._overlay.take_panel()
            self._overlay.hide()
            self._dock_panel_into_splitter(width=0, visible=False)
        elif eff == Effect.DOCK:
            self._clear_peek_tracking()
            if self._overlay.isVisible():
                self._overlay.take_panel()
                self._overlay.hide()
            self._dock_panel_into_splitter(
                width=self._clamp_expanded_width(self._remembered_width),
                visible=True,
            )
        elif eff == Effect.COLLAPSE_PINNED:
            self._remember_width_if_docked()
            # Hide before zeroing the slot so minimumWidth doesn't clamp it open.
            self._panel.setVisible(False)
            self._set_slot_width(0)
        elif eff == Effect.START_TIMER:
            # OVERLAY_LEFT means the union was left. Drop stale region flags so
            # a later timeout re-reads the live pointer instead of the old enter.
            self._in_strip = False
            self._in_overlay = False
            self._arm_collapse_once()
        elif eff == Effect.STOP_TIMER:
            self._stop_collapse_timer()
            self._defer_until_release = False

    # ---- helpers ----
    def _apply_strip_visibility(self):
        self._strip.setVisible(strip_visible_for(self.state))

    def _remember_width_if_docked(self):
        idx = self._live_index()
        if idx < 0:
            return  # panel not in the splitter; nothing to remember
        w = self._splitter.sizes()[idx]
        if w > self.COLLAPSE_THRESHOLD:
            self._remembered_width = self._clamp_expanded_width(w)

    def _dock_panel_into_splitter(self, width, visible):
        # Re-insert if the panel was reparented out (peek), else just resize.
        if self._panel.parent() is not self._splitter:
            self._splitter.insertWidget(self._index, self._panel)
        # setVisible BEFORE _set_slot_width: a hidden widget reports
        # minimumWidth 0, so a width-0 slot is honoured; a visible widget's
        # minimumWidth would otherwise clamp the slot open.
        self._panel.setVisible(visible)
        self._set_slot_width(width if visible else 0)

    def _set_slot_width(self, width):
        sizes = self._splitter.sizes()
        idx = self._live_index()
        if idx < 0 or idx >= len(sizes):
            return  # panel not in the splitter
        delta = width - sizes[idx]
        sizes[idx] = width
        # Absorb the delta from the canvas pane, looked up by LIVE index so it
        # stays correct even when the other side panel has been reparented out
        # and the splitter renumbered. Fall back to the widest non-self pane
        # when the canvas isn't a current child (e.g. the 2-pane tests where
        # canvas is None and the middle widget is the only non-self pane).
        absorb = self._splitter.indexOf(self._canvas) if self._canvas is not None else -1
        if absorb < 0 or absorb == idx or absorb >= len(sizes):
            absorb = max(range(len(sizes)),
                         key=lambda i: sizes[i] if i != idx else -1)
        sizes[absorb] = max(0, sizes[absorb] - delta)
        self._splitter.setSizes(sizes)

    # Qt's "no maximum" sentinel (QWIDGETSIZE_MAX); a panel reporting this has
    # no real width cap. PyQt5 doesn't export the constant cleanly, so inline it.
    _NO_MAX_WIDTH = (1 << 24) - 1  # 16777215

    def _expanded_min_width(self):
        getter = getattr(self._panel, "expanded_minimum_width", None)
        if callable(getter):
            try:
                return max(0, int(getter()))
            except (TypeError, ValueError):
                pass
        return max(0, int(self._panel.minimumWidth()))

    def _clamp_expanded_width(self, width):
        width = int(width)
        if width <= self.COLLAPSE_THRESHOLD:
            return width
        return max(width, self._expanded_min_width())

    def _peek_available_width(self):
        """Host pixels left for the overlay after reserving the edge strip."""
        host_w = int(self._host.width()) if self._host is not None else 0
        return host_w - int(self._strip.WIDTH_PX)

    def _peek_overlay_width(self):
        # Remembered dock width is a preference, not a fit requirement.
        # Clamp into [content min, min(available host, panel max)].
        min_w = self._expanded_min_width()
        available = self._peek_available_width()
        preferred = int(self._remembered_width) + self.PEEK_EXTRA_PX
        if self._peek_width is not None:
            preferred = max(preferred, int(self._peek_width))
        max_w = self._panel.maximumWidth()
        hi = available
        if 0 < max_w < self._NO_MAX_WIDTH:
            hi = min(hi, max_w)
        return max(min_w, min(preferred, hi))

    def _peek_can_fit(self):
        # Same budget as _position_overlay / _peek_overlay_width: refuse only
        # when the content minimum plus the strip cannot fit in the host.
        return self._peek_available_width() >= self._expanded_min_width()

    def _position_overlay(self):
        w = self._peek_overlay_width()
        h = self._host.height()
        # Keep the edge strip exposed (and clickable -> pin) beside the overlay,
        # so the overlay starts just inside the strip rather than covering it.
        strip_w = self._strip.WIDTH_PX
        if self._side == Side.LEFT:
            x = strip_w
        else:
            x = max(0, self._host.width() - strip_w - w)
        self._overlay.setGeometry(x, 0, w, h)

    def reposition(self):
        """Call from MainWindow.resizeEvent / moveEvent while peeking."""
        if self.state != PanelState.PEEK:
            return
        if not self._peek_can_fit():
            self._dispatch(Ev.COLLAPSE_TIMEOUT)
            return
        self._position_overlay()

    def snapshot_persistent_state(self) -> dict:
        """Public HIDDEN/PINNED snapshot. PEEK is stored as HIDDEN."""
        self._remember_width_if_docked()
        persistent = "PINNED" if self.state == PanelState.PINNED else "HIDDEN"
        return {
            "state": persistent,
            "width": int(self._remembered_width),
        }

    def restore_persistent_state(self, snapshot) -> None:
        """Restore a snapshot from :meth:`snapshot_persistent_state`."""
        if not snapshot:
            return
        try:
            width = int(snapshot.get("width") or self._remembered_width)
        except (TypeError, ValueError):
            width = int(self._remembered_width)
        if width > self.COLLAPSE_THRESHOLD:
            self._remembered_width = self._clamp_expanded_width(width)
        want_pinned = str(snapshot.get("state") or "HIDDEN") == "PINNED"
        if want_pinned:
            self._force_pinned()
        else:
            self._force_hidden()

    def _force_hidden(self) -> None:
        if self.state == PanelState.HIDDEN:
            return
        self._collapse_timer.stop()
        if self.state == PanelState.PEEK:
            self._run_effect(Effect.EXIT_PEEK)
        elif self.state == PanelState.PINNED:
            self._run_effect(Effect.COLLAPSE_PINNED)
        self.state = PanelState.HIDDEN
        self._apply_strip_visibility()
        self.state_changed.emit(self.state)

    def _force_pinned(self) -> None:
        self._collapse_timer.stop()
        if self.state == PanelState.PINNED:
            self._run_effect(Effect.DOCK)
            return
        self._run_effect(Effect.DOCK)
        self.state = PanelState.PINNED
        self._apply_strip_visibility()
        self.state_changed.emit(self.state)
