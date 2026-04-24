"""Center pane: QStackedWidget holding the three canvases + stats strip.

Phase 1: bare-bones container + mode getter/setter. Stats strip and
cursor pill land in Phase 2.
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from .canvases import PlotCanvas, TimeDomainCanvas
from .widgets import StatsStrip

_MODE_TO_INDEX = {'time': 0, 'fft': 1, 'order': 2}
_INDEX_TO_MODE = {v: k for k, v in _MODE_TO_INDEX.items()}


class _ChartCard(QWidget):
    """Canvas + its NavigationToolbar in a vertical layout."""
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = canvas
        self.toolbar = NavigationToolbar(canvas, self)
        lay.addWidget(self.toolbar)
        lay.addWidget(canvas, stretch=1)


class ChartStack(QWidget):
    mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self)
        self.canvas_time = TimeDomainCanvas(self)
        self.canvas_fft = PlotCanvas(self)
        self.canvas_order = PlotCanvas(self)
        self.stack.addWidget(_ChartCard(self.canvas_time))
        self.stack.addWidget(_ChartCard(self.canvas_fft))
        self.stack.addWidget(_ChartCard(self.canvas_order))
        lay.addWidget(self.stack, stretch=1)

        # Stats strip mounted at the bottom (Task 2.10)
        self.stats_strip = StatsStrip(self)
        lay.addWidget(self.stats_strip)

        # Cursor pill (owned by ChartStack; floats over active canvas)
        self._cursor_pill = QLabel("", self.stack)
        self._cursor_pill.setObjectName("cursorPill")
        self._cursor_pill.setVisible(False)
        self._cursor_dual_pill = QLabel("", self.stack)
        self._cursor_dual_pill.setObjectName("cursorPill")
        self._cursor_dual_pill.setWordWrap(True)
        self._cursor_dual_pill.setVisible(False)
        self.canvas_time.cursor_info.connect(self._on_cursor_info)
        self.canvas_time.dual_cursor_info.connect(self._on_dual_cursor_info)
        self.stack.currentChanged.connect(lambda _i: self._reposition_pills())

    def count(self):
        return self.stack.count()

    def set_mode(self, mode):
        idx = _MODE_TO_INDEX[mode]
        if self.stack.currentIndex() == idx:
            return
        self.stack.setCurrentIndex(idx)
        self.mode_changed.emit(mode)

    def current_mode(self):
        return _INDEX_TO_MODE[self.stack.currentIndex()]

    def full_reset_all(self):
        self.canvas_time.full_reset()
        self.canvas_fft.full_reset()
        self.canvas_order.full_reset()

    def _on_cursor_info(self, text):
        self._cursor_pill.setText(text)
        self._cursor_pill.adjustSize()
        self._cursor_pill.setVisible(self.current_mode() == 'time')
        self._reposition_pills()

    def _on_dual_cursor_info(self, text):
        self._cursor_dual_pill.setText(text)
        self._cursor_dual_pill.adjustSize()
        self._cursor_dual_pill.setVisible(bool(text) and self.current_mode() == 'time')
        self._reposition_pills()

    def _reposition_pills(self):
        visible = self.current_mode() == 'time'
        if not visible:
            self._cursor_pill.setVisible(False)
            self._cursor_dual_pill.setVisible(False)
            return
        card = self.stack.currentWidget()
        h = card.height() if card is not None else self.stack.height()
        pill_h = self._cursor_pill.sizeHint().height()
        self._cursor_pill.move(8, max(h - pill_h - 8, 0))
        if self._cursor_dual_pill.text():
            dh = self._cursor_dual_pill.sizeHint().height()
            self._cursor_dual_pill.move(8, max(h - pill_h - dh - 12, 0))
        self._cursor_pill.raise_()
        self._cursor_dual_pill.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_pills()

    def cursor_pill_text(self):
        return self._cursor_pill.text()

    def cursor_pill_visible(self):
        return self._cursor_pill.isVisible()
