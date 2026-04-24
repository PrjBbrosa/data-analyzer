"""Right pane: persistent top + contextual bottom card.

Owns the inspector_state_dict (per section 12.1 of the design spec):
caches the user's last input on each mode's contextual widget so that
switching modes preserves context.
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from .inspector_sections import (
    FFTContextual,
    OrderContextual,
    PersistentTop,
    TimeContextual,
)


class Inspector(QWidget):
    plot_time_requested = pyqtSignal()
    fft_requested = pyqtSignal()
    order_time_requested = pyqtSignal()
    order_rpm_requested = pyqtSignal()
    order_track_requested = pyqtSignal()
    xaxis_apply_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object, str)  # (anchor, mode: 'fft'|'order')
    tick_density_changed = pyqtSignal(int, int)
    remark_toggled = pyqtSignal(bool)
    # Fs auto-sync: relayed from fft_ctx/order_ctx combo_sig change
    signal_changed = pyqtSignal(str, object)  # (mode, (fid, ch) | None)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("inspectorScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self._scroll)

        self._scroll_body = QWidget(self._scroll)
        body_lay = QVBoxLayout(self._scroll_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)

        self.top = PersistentTop(self._scroll_body)
        body_lay.addWidget(self.top)
        self.contextual_stack = QStackedWidget(self._scroll_body)
        self.time_ctx = TimeContextual(self._scroll_body)
        self.fft_ctx = FFTContextual(self._scroll_body)
        self.order_ctx = OrderContextual(self._scroll_body)
        self.contextual_stack.addWidget(self.time_ctx)
        self.contextual_stack.addWidget(self.fft_ctx)
        self.contextual_stack.addWidget(self.order_ctx)
        body_lay.addWidget(self.contextual_stack)
        body_lay.addStretch(1)
        self._scroll.setWidget(self._scroll_body)
        self._wire()

    def _wire(self):
        self.top.xaxis_apply_requested.connect(self.xaxis_apply_requested)
        self.top.tick_density_changed.connect(self.tick_density_changed)
        self.time_ctx.plot_time_requested.connect(self.plot_time_requested)
        self.fft_ctx.fft_requested.connect(self.fft_requested)
        self.fft_ctx.rebuild_time_requested.connect(
            lambda a: self.rebuild_time_requested.emit(a, 'fft'))
        self.fft_ctx.remark_toggled.connect(self.remark_toggled)
        # Phase 2 adds signal_changed emitter on FFTContextual
        self.fft_ctx.signal_changed.connect(
            lambda d: self.signal_changed.emit('fft', d))
        self.order_ctx.order_time_requested.connect(self.order_time_requested)
        self.order_ctx.order_rpm_requested.connect(self.order_rpm_requested)
        self.order_ctx.order_track_requested.connect(self.order_track_requested)
        self.order_ctx.rebuild_time_requested.connect(
            lambda a: self.rebuild_time_requested.emit(a, 'order'))
        self.order_ctx.signal_changed.connect(
            lambda d: self.signal_changed.emit('order', d))

    def set_mode(self, mode):
        idx = {'time': 0, 'fft': 1, 'order': 2}[mode]
        self.contextual_stack.setCurrentIndex(idx)

    def contextual_widget_name(self):
        return {0: 'time', 1: 'fft', 2: 'order'}[self.contextual_stack.currentIndex()]
