"""Right pane: persistent top + contextual bottom card.

Owns the inspector_state_dict (per section 12.1 of the design spec):
caches the user's last input on each mode's contextual widget so that
switching modes preserves context.
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .inspector_sections import (
    FFTContextual,
    FFTTimeContextual,
    OrderContextual,
    PersistentTop,
    TimeContextual,
)


# 2026-04-26 R3 紧凑化 fix-1: cap the Inspector's content width so
# Expanding children (QSpinBox / QComboBox / QLineEdit) stop growing
# unboundedly when the right splitter pane is dragged wider. The cap
# should be just wide enough to host the longest legitimate content.
# 2026-06-05 narrow-pane: the inspector was retuned from 360px → 288px so
# its initial width matches the left file column (~250–288). The visible
# right pane is 288px wide; the content body is 272px so the scroll area
# has room for its scrollbar and 2px pane margins. The 坐标轴设置 group
# was made fluid (range editors fill the remaining width, dB/Linear unit
# wraps to its own right-aligned line) so it shrinks with the pane instead
# of forcing a horizontal scrollbar — see _build_axis_row.
_INSPECTOR_CONTENT_MAX_WIDTH = 272


class Inspector(QWidget):
    plot_time_requested = pyqtSignal()
    fft_requested = pyqtSignal()
    fft_time_requested = pyqtSignal()
    order_time_requested = pyqtSignal()
    xaxis_apply_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object, str)  # (anchor, mode: 'fft'|'order')
    tick_density_changed = pyqtSignal(int, int)
    remark_toggled = pyqtSignal(bool)
    # Fs auto-sync: relayed from fft_ctx/order_ctx combo_sig change
    signal_changed = pyqtSignal(str, object)  # (mode, (fid, ch) | None)
    # FFT vs Time signal-change relay (T6 hand-off; reviewer Important #2).
    # The fft_time panel needs its own signal-change channel for downstream
    # listeners (Fs auto-sync, worker invalidation hooks). Kept separate
    # from `signal_changed` so consumers can opt in without filtering on
    # mode strings; the (fid, ch) payload mirrors what fft_time_ctx emits.
    fft_time_signal_changed = pyqtSignal(object)  # (fid, ch) | None
    # Preset save/load acknowledgement (level, message) — surfaced as toasts
    preset_acknowledged = pyqtSignal(str, str)
    gpu_render_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 2026-04-26 fix: cap the inspector widget itself so the splitter cannot
        # allocate more width than its capped content (_INSPECTOR_CONTENT_MAX_WIDTH).
        # Surplus split-pane width was previously absorbed by host_lay.addStretch,
        # producing a visible empty column on the right at large window sizes.
        # +16 covers the QScrollArea vertical scrollbar + 2px-each-side margins.
        self.setFixedWidth(_INSPECTOR_CONTENT_MAX_WIDTH + 16)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("inspectorScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self._scroll)

        # 2026-04-26 R3 紧凑化 fix-1:
        # The scroll uses a *host* widget that fills the viewport horizontally,
        # while ``_scroll_body`` (the actual form host) is capped at
        # ``_INSPECTOR_CONTENT_MAX_WIDTH`` and pushed to the leading edge by a
        # trailing addStretch. Without the cap, Expanding child controls
        # (QSpinBox / QComboBox / QLineEdit) grow unboundedly whenever the
        # splitter widens the right pane, producing the "toggle a checkbox →
        # pane visually balloons" defect that the user reported.
        host = QWidget(self._scroll)
        host_lay = QHBoxLayout(host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(0)

        self._scroll_body = QWidget(host)
        self._scroll_body.setFixedWidth(_INSPECTOR_CONTENT_MAX_WIDTH)
        body_lay = QVBoxLayout(self._scroll_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)

        self.top = PersistentTop(self._scroll_body)
        body_lay.addWidget(self.top)
        self.contextual_stack = QStackedWidget(self._scroll_body)
        self.time_ctx = TimeContextual(self._scroll_body)
        self.fft_ctx = FFTContextual(self._scroll_body)
        self.fft_time_ctx = FFTTimeContextual(self._scroll_body)
        self.order_ctx = OrderContextual(self._scroll_body)
        self.contextual_stack.addWidget(self.time_ctx)
        self.contextual_stack.addWidget(self.fft_ctx)
        self.contextual_stack.addWidget(self.fft_time_ctx)
        self.contextual_stack.addWidget(self.order_ctx)
        body_lay.addWidget(self.contextual_stack)
        self.gpu_toggle = QCheckBox("GPU 加速（时域图）", self._scroll_body)
        self.gpu_toggle.setObjectName("gpuRenderToggle")
        self.gpu_toggle.setToolTip("开启时域图 OpenGL 渲染；导出会临时切回 CPU")
        self.gpu_toggle.toggled.connect(self.gpu_render_toggled)
        body_lay.addWidget(self.gpu_toggle)
        body_lay.addStretch(1)

        # Anchor the capped body to the leading edge; the trailing stretch
        # absorbs any extra width the splitter hands us.
        host_lay.addWidget(self._scroll_body, 0, Qt.AlignTop | Qt.AlignLeft)
        host_lay.addStretch(1)

        self._scroll.setWidget(host)
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
        self.order_ctx.rebuild_time_requested.connect(
            lambda a: self.rebuild_time_requested.emit(a, 'order'))
        self.order_ctx.signal_changed.connect(
            lambda d: self.signal_changed.emit('order', d))
        self.fft_ctx.preset_bar.acknowledged.connect(self.preset_acknowledged)
        self.order_ctx.preset_bar.acknowledged.connect(self.preset_acknowledged)
        # R3 C: FFTTimeContextual now also owns a (builtin-aware) PresetBar.
        self.fft_time_ctx.preset_bar.acknowledged.connect(self.preset_acknowledged)
        # FFT vs Time primary compute relay.
        self.fft_time_ctx.fft_time_requested.connect(self.fft_time_requested)
        # T6 reviewer Important #2: relay rebuild_time_requested and
        # signal_changed from the fft_time contextual. Mirrors the
        # fft_ctx / order_ctx wiring above; the rebuild relay tags the
        # mode string so MainWindow can route to the correct ctx.
        self.fft_time_ctx.rebuild_time_requested.connect(
            lambda a: self.rebuild_time_requested.emit(a, 'fft_time'))
        self.fft_time_ctx.signal_changed.connect(self.fft_time_signal_changed)

    def set_mode(self, mode):
        idx = {'time': 0, 'fft': 1, 'fft_time': 2, 'order': 3}[mode]
        self.contextual_stack.setCurrentIndex(idx)

    def current_mode(self):
        return self.contextual_widget_name()

    def contextual_widget_name(self):
        return {0: 'time', 1: 'fft', 2: 'fft_time', 3: 'order'}[self.contextual_stack.currentIndex()]

    def set_gpu_toggle_checked(self, on: bool):
        was_blocked = self.gpu_toggle.blockSignals(True)
        try:
            self.gpu_toggle.setChecked(bool(on))
        finally:
            self.gpu_toggle.blockSignals(was_blocked)
