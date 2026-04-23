"""Inspector section widgets. Phase 1 stubs; real content in Phase 2."""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


class PersistentTop(QWidget):
    """Xaxis / Range / Ticks sections (always visible)."""
    xaxis_apply_requested = pyqtSignal()
    tick_density_changed = pyqtSignal(int, int)
    range_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[persistent-top stub]", self))


class TimeContextual(QWidget):
    plot_time_requested = pyqtSignal()
    cursor_mode_changed = pyqtSignal(str)  # 'off' | 'single' | 'dual'
    plot_mode_changed = pyqtSignal(str)    # 'subplot' | 'overlay'

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[time-contextual stub]", self))


class FFTContextual(QWidget):
    fft_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    remark_toggled = pyqtSignal(bool)
    signal_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[fft-contextual stub]", self))


class OrderContextual(QWidget):
    order_time_requested = pyqtSignal()
    order_rpm_requested = pyqtSignal()
    order_track_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    signal_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[order-contextual stub]", self))
