"""Right pane: persistent top + contextual bottom card.

Owns the inspector_state_dict (per section 12.1 of the design spec):
caches the user's last input on each mode's contextual widget so that
switching modes preserves context.
"""
import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
from .inspector_sections.time_filter import FilterPanel
from .widgets.pill_switch import PillSwitch, PillSwitchLabel


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

_GPU_RENDER_TOOLTIP = (
    "大图 / 多通道 / 高分屏卡顿时开启。\n"
    "渲染效果与 CPU 一致，导出正常。"
)

# viewport 级 GL 在 macOS 与 冻结包（PyInstaller）上都不合成曲线（曲线整体消失），
# 故这两种情况隐藏该开关；功能正确性由 canvas.set_gpu_render 的平台兜底强制 CPU
# 保证。冻结包实证：desktop GL 4.6 正确 + 关 UPX 仍失效（见 canvas gate 注释）。
# 其它平台的源码运行保留。
_GPU_RENDER_UI_SUPPORTED = sys.platform != "darwin" and not getattr(sys, "frozen", False)


class Inspector(QWidget):
    plot_time_requested = pyqtSignal()
    fft_requested = pyqtSignal()
    fft_time_requested = pyqtSignal()
    order_time_requested = pyqtSignal()
    xaxis_apply_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object, str)  # (anchor, mode: 'fft'|'order')
    gpu_render_toggled = pyqtSignal(bool)  # True = GPU on
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

    def __init__(self, parent=None):
        super().__init__(parent)
        # QSS (Inspector { border-radius:10px; background:#fff }) only paints on a
        # plain QWidget subclass once WA_StyledBackground is set; without it Qt
        # skips the styled fill/border and the rounded card never renders.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        # 2026-04-26 fix: cap the inspector widget itself so the splitter cannot
        # allocate more width than its capped content (_INSPECTOR_CONTENT_MAX_WIDTH).
        # Surplus split-pane width was previously absorbed by host_lay.addStretch,
        # producing a visible empty column on the right at large window sizes.
        # +16 covers the QScrollArea vertical scrollbar + 2px-each-side margins.
        self.setFixedWidth(_INSPECTOR_CONTENT_MAX_WIDTH + 16)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("inspectorScroll")
        self._scroll.setAutoFillBackground(False)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
        self._scroll.viewport().setAttribute(Qt.WA_NoSystemBackground, True)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self._scroll, 1)

        # 2026-06-22 unify-help-link: one persistent '?  使用说明' link pinned
        # to the Inspector's bottom-right, OUTSIDE the scroll area, so it sits
        # at the same visual position in every mode regardless of how tall the
        # current contextual content is — and never scrolls out of view. The
        # per-contextual help rows that used to float just under each panel's
        # last control (visibly mid-pane for the short Time mode) were removed
        # in favour of this single link. Its target guide is rebound per mode
        # in set_mode → _update_help_guide.
        self._help_guide_name = 'time'
        help_row = QFrame(self)
        help_row.setObjectName("inspectorHelpRow")
        help_box = QHBoxLayout(help_row)
        help_box.setContentsMargins(0, 2, 3, 0)
        help_box.setSpacing(0)
        help_box.addStretch(1)
        self._help_link = QPushButton("?  使用说明", help_row)
        self._help_link.setObjectName("inspectorHelpLink")
        self._help_link.setProperty("role", "link")
        self._help_link.setCursor(Qt.PointingHandCursor)
        self._help_link.setToolTip("打开本面板的使用说明")
        self._help_link.setFlat(True)
        self._help_link.clicked.connect(self._open_current_guide)
        help_box.addWidget(self._help_link, 0)
        lay.addWidget(help_row, 0)

        # 2026-04-26 R3 紧凑化 fix-1:
        # The scroll uses a *host* widget that fills the viewport horizontally,
        # while ``_scroll_body`` (the actual form host) is capped at
        # ``_INSPECTOR_CONTENT_MAX_WIDTH`` and pushed to the leading edge by a
        # trailing addStretch. Without the cap, Expanding child controls
        # (QSpinBox / QComboBox / QLineEdit) grow unboundedly whenever the
        # splitter widens the right pane, producing the "toggle a checkbox →
        # pane visually balloons" defect that the user reported.
        host = QWidget(self._scroll)
        host.setAutoFillBackground(False)
        host.setAttribute(Qt.WA_TranslucentBackground, True)
        host.setAttribute(Qt.WA_NoSystemBackground, True)
        host_lay = QHBoxLayout(host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(0)

        self._scroll_body = QWidget(host)
        self._scroll_body.setObjectName("inspectorScrollBody")
        self._scroll_body.setAttribute(Qt.WA_StyledBackground, True)
        self._scroll_body.setFixedWidth(_INSPECTOR_CONTENT_MAX_WIDTH)
        body_lay = QVBoxLayout(self._scroll_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)

        self._current_mode = 'time'
        self._time_domain_card = QFrame(self._scroll_body)
        self._time_domain_card.setObjectName("timeDomainSettingsCard")
        self._time_domain_card.setAttribute(Qt.WA_StyledBackground, True)
        time_card_lay = QVBoxLayout(self._time_domain_card)
        time_card_lay.setContentsMargins(0, 0, 0, 0)
        time_card_lay.setSpacing(0)
        self.top = PersistentTop(self._time_domain_card)
        time_card_lay.addWidget(self.top)
        # 2026-06-22 卡片重组 (Task 4): the persistent top now exposes TWO
        # independent white cards — ① 横坐标 (xaxis + 「应用」) and ② 时间范围·滤波.
        # Expose them on the Inspector for structural assertions and downstream
        # use. The FilterPanel is mounted INSIDE card ②, below the time-range
        # group, and the single contextual 「绘图」 button is the card's bottom
        # action so range + filter submit together. `filter_changed` is
        # intentionally NOT wired to a replot — the filter is read on the next
        # 「绘图」 submit (avoids recompute on every keystroke). Filtering is
        # opt-in via the panel's 「滤波」 checkbox (default OFF), placed as the
        # filter section title row.
        self._xaxis_card = self.top.xaxis_card()
        self._range_filter_card = self.top.range_card()
        self.filter_panel = FilterPanel(self._range_filter_card)
        self.top.range_card_layout().addWidget(self.filter_panel)
        self.time_ctx = TimeContextual(self._range_filter_card)
        self.top.range_card_layout().addWidget(self.time_ctx)
        body_lay.addWidget(self._time_domain_card)

        self.contextual_stack = QStackedWidget(self._scroll_body)
        self.fft_ctx = FFTContextual(self._scroll_body)
        self.fft_time_ctx = FFTTimeContextual(self._scroll_body)
        self.order_ctx = OrderContextual(self._scroll_body)
        self.contextual_stack.addWidget(self.fft_ctx)
        self.contextual_stack.addWidget(self.fft_time_ctx)
        self.contextual_stack.addWidget(self.order_ctx)
        body_lay.addWidget(self.contextual_stack)
        self.contextual_stack.setVisible(False)

        # GPU 加速开关：仅时域图使用；FFT / Order 面板不显示，避免误导。
        self._gpu_row = QFrame(self._scroll_body)
        self._gpu_row.setObjectName("gpuToggleRow")
        gpu_row_lay = QHBoxLayout(self._gpu_row)
        gpu_row_lay.setContentsMargins(4, 4, 4, 4)
        gpu_row_lay.setSpacing(4)
        gpu_row_lay.addStretch(1)
        self._gpu_switch = PillSwitch(
            self._gpu_row,
            object_name="gpuRenderSwitch",
            accessible_name="GPU 加速",
        )
        self._gpu_switch.setToolTip(_GPU_RENDER_TOOLTIP)
        self._gpu_switch.setChecked(False)
        self._gpu_switch.toggled.connect(self.gpu_render_toggled)
        self._gpu_label = PillSwitchLabel(
            "GPU 加速", self._gpu_switch, self._gpu_row,
            object_name="gpuRenderLabel",
        )
        self._gpu_label.setToolTip(_GPU_RENDER_TOOLTIP)
        gpu_row_lay.addWidget(self._gpu_label, 0)
        gpu_row_lay.addWidget(self._gpu_switch, 0)
        body_lay.addWidget(self._gpu_row)

        body_lay.addStretch(1)

        # Anchor the capped body to the leading edge; the trailing stretch
        # absorbs any extra width the splitter hands us.
        host_lay.addWidget(self._scroll_body, 0, Qt.AlignTop | Qt.AlignLeft)
        host_lay.addStretch(1)

        self._scroll.setWidget(host)
        self._range_group_owner_layout = self.top.range_group_layout()
        self._wire()
        self._place_range_group_for_mode('time')

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
        self._current_mode = mode
        if mode == 'time':
            self._time_domain_card.setVisible(True)
            self.contextual_stack.setVisible(False)
        else:
            idx = {'fft': 0, 'fft_time': 1, 'order': 2}[mode]
            self._time_domain_card.setVisible(False)
            self.contextual_stack.setVisible(True)
            self.contextual_stack.setCurrentIndex(idx)
        # GPU 开关仅时域显示，且 macOS 上隐藏（viewport-GL 在 macOS 画不出曲线）。
        self._gpu_row.setVisible(mode == 'time' and _GPU_RENDER_UI_SUPPORTED)
        self._place_range_group_for_mode(mode)
        self._update_help_guide(mode)

    def _update_help_guide(self, mode):
        # The persistent bottom-right help link targets the current mode's
        # guide; mode strings map 1:1 to open_guide() names.
        self._help_guide_name = mode if mode in (
            'time', 'fft', 'fft_time', 'order',
        ) else 'time'

    def _open_current_guide(self):
        from ..help import open_guide
        open_guide(self._help_guide_name)

    def _place_range_group_for_mode(self, mode):
        # Decouple the shared chk_range checked state per mode BEFORE the
        # group is reparented, so an FFT time-window drag's force-check does
        # not leak into Time-Domain (and vice versa). The checkbox INSTANCE is
        # shared across modes; only its per-mode intent must be restored here.
        self.top.checkout_range_for_mode(mode)
        group = self.top.range_group()
        old_layout = self._range_group_owner_layout
        if old_layout is not None:
            old_layout.removeWidget(group)
        if mode == 'time':
            target_layout = self.top.range_group_layout()
            self.top.set_range_group_embedded(False)
            self.top.set_xaxis_section_visible(True)
            self.top.setVisible(True)
            # The range card hosts [range_group, filter_panel]; re-insert the
            # group ABOVE the filter panel (addWidget would append it below).
            target_layout.insertWidget(0, group)
        else:
            ctx = {
                'fft': self.fft_ctx,
                'fft_time': self.fft_time_ctx,
                'order': self.order_ctx,
            }[mode]
            target_layout = ctx.time_range_layout()
            self.top.set_range_group_embedded(True)
            self.top.setVisible(False)
            target_layout.addWidget(group)
        self._range_group_owner_layout = target_layout
        group.setVisible(True)

    def set_gpu_render_checked(self, on: bool):
        """Set the GPU render switch without emitting gpu_render_toggled."""
        self._gpu_switch.blockSignals(True)
        self._gpu_switch.setChecked(bool(on))
        self._gpu_switch.blockSignals(False)

    def current_mode(self):
        return self.contextual_widget_name()

    def contextual_widget_name(self):
        return self._current_mode
