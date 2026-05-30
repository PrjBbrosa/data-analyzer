# mf4_analyzer/ui/side_panels.py
"""Collapsible side panels: HIDDEN/PEEK/PINNED state machine + widgets.

The reducer (``reduce_panel``) is intentionally Qt-free so the transition
logic is unit-testable without an event loop. ``SidePanelController`` (added
in a later task) executes the emitted effects against real Qt widgets.
"""
from enum import Enum, auto


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
}


def reduce_panel(state, event):
    """Pure transition: returns ``(next_state, effects)``; no-op stays put."""
    return _TRANSITIONS.get((state, event), (state, ()))


def strip_visible_for(state):
    """Edge strip is shown only while the panel is HIDDEN or PEEK."""
    return state in (PanelState.HIDDEN, PanelState.PEEK)


from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame


class SidePanelStrip(QFrame):
    """A thin, faint, clickable edge rail shown when its side is collapsed.

    Hover (after a short debounce) requests a peek; left-click requests a pin.
    """
    peek_requested = pyqtSignal(object)  # Side
    pin_requested = pyqtSignal(object)   # Side

    WIDTH_PX = 12

    def __init__(self, side, hover_delay_ms=150, parent=None):
        super().__init__(parent)
        self._side = side
        self.setObjectName("sidePanelStrip")
        self.setProperty("side", "left" if side == Side.LEFT else "right")
        self.setFixedWidth(self.WIDTH_PX)
        self.setCursor(Qt.PointingHandCursor)
        chevron = "‹" if side == Side.LEFT else "›"  # ‹ / ›  (points inward)
        self.setToolTip("文件 / 通道" if side == Side.LEFT else "Inspector")
        self._chevron = chevron
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(hover_delay_ms)
        self._hover_timer.timeout.connect(lambda: self.peek_requested.emit(self._side))

    def enterEvent(self, event):
        self._hover_timer.start()
        super().enterEvent(event) if event is not None else None

    def leaveEvent(self, event):
        self._hover_timer.stop()
        super().leaveEvent(event) if event is not None else None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._hover_timer.stop()
            self.pin_requested.emit(self._side)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        from PyQt5.QtGui import QPainter, QColor
        p = QPainter(self)
        p.setPen(QColor("#9aa3ad"))
        p.drawText(self.rect(), Qt.AlignCenter, self._chevron)
        p.end()


from PyQt5.QtWidgets import QVBoxLayout


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
