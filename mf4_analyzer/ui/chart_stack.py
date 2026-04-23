"""Center pane: QStackedWidget holding the three canvases + stats strip.

Phase 1: bare-bones container + mode getter/setter. Stats strip and
cursor pill land in Phase 2.
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from .canvases import PlotCanvas, TimeDomainCanvas

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
