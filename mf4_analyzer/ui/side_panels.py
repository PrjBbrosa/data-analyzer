# mf4_analyzer/ui/side_panels.py
"""Collapsible side panels: HIDDEN/PEEK/PINNED state machine + widgets.

The reducer (``reduce_panel``) is intentionally Qt-free (it makes no Qt calls),
so the transition logic is unit-testable without an event loop.
``SidePanelController`` executes the emitted effects against real Qt widgets.
"""
from enum import Enum, auto

from PyQt5.QtCore import QObject, QPointF, QRectF, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QFrame, QVBoxLayout


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

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(collapse_delay_ms)
        self._collapse_timer.timeout.connect(self._on_collapse_timeout)

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
        # Popup guard: a context menu opened from inside the peeked panel makes
        # the mouse "leave" the overlay; don't auto-collapse while it's open.
        if QApplication.activePopupWidget() is not None:
            self._collapse_timer.start()  # re-arm; re-check shortly
            return
        self._dispatch(Ev.COLLAPSE_TIMEOUT)

    # ---- core dispatch ----
    def _dispatch(self, event):
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
        elif eff == Effect.EXIT_PEEK:
            self._overlay.take_panel()
            self._overlay.hide()
            self._dock_panel_into_splitter(width=0, visible=False)
        elif eff == Effect.DOCK:
            if self._overlay.isVisible():
                self._overlay.take_panel()
                self._overlay.hide()
            self._dock_panel_into_splitter(width=self._remembered_width, visible=True)
        elif eff == Effect.COLLAPSE_PINNED:
            self._remember_width_if_docked()
            # Hide before zeroing the slot so minimumWidth doesn't clamp it open.
            self._panel.setVisible(False)
            self._set_slot_width(0)
        elif eff == Effect.START_TIMER:
            self._collapse_timer.start()
        elif eff == Effect.STOP_TIMER:
            self._collapse_timer.stop()

    # ---- helpers ----
    def _apply_strip_visibility(self):
        self._strip.setVisible(strip_visible_for(self.state))

    def _remember_width_if_docked(self):
        idx = self._live_index()
        if idx < 0:
            return  # panel not in the splitter; nothing to remember
        w = self._splitter.sizes()[idx]
        if w > self.COLLAPSE_THRESHOLD:
            self._remembered_width = w

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

    def _position_overlay(self):
        w = self._remembered_width + self.PEEK_EXTRA_PX
        # Floor the width for L/R symmetry (a narrow panel peeks out to at least
        # peek_width); a wider-docked panel still peeks at its own larger width.
        if self._peek_width is not None:
            w = max(w, self._peek_width)
        # Don't let the overlay exceed the panel's own max width: width-capped
        # panels (e.g. the inspector is pinned to a fixed width) can't stretch
        # to fill the surplus, so it would otherwise show as a blank band of
        # overlay background. Uncapped panels (navigator) still get the +EXTRA.
        max_w = self._panel.maximumWidth()
        if 0 < max_w < self._NO_MAX_WIDTH:
            w = min(w, max_w)
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
        if self.state == PanelState.PEEK:
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
            self._remembered_width = width
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
