"""PersistentTop and _AxisRangeHost widgets."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.widgets.searchable_combo import SearchableComboBox
from ...ui_kit.widgets.segmented_choice import SegmentedChoice
from ..chart_stack.toolbar import DEFAULT_CHART_TICK_DENSITY
from ..widgets.compact_spinbox import CompactDoubleSpinBox
from ._helpers import (
    _SHORT_FIELD_MAX_WIDTH,
    _LONG_FIELD_MAX_WIDTH,
    _configure_form,
    _fit_field,
    _no_buttons,
    _pair_field,
    _preset_settings,
    _set_form_row_visible,
    _AxisRangeHost,
)


class PersistentTop(QWidget):
    """Xaxis / Range sections plus hidden tick-density compatibility state.

    R3 #6: the three sections live inside a collapsible container that
    defaults to collapsed (single-row affordance reading "▶ 图表设置 (横坐标
    · 时间范围)"). The collapsed state is persisted via QSettings under
    ``_SETTINGS_KEY`` so layouts survive between sessions.

    All public attributes / methods documented on the class remain
    reachable regardless of collapser state — programmatic getters / setters
    work even while the body widget is hidden.
    """

    _SETTINGS_KEY = "inspector/persistent_top/expanded_v2"

    xaxis_apply_requested = pyqtSignal()
    tick_density_changed = pyqtSignal(int, int)
    # 「全部」按钮：查看全部（复位到已绘制通道最长全程）；不勾选「使用选定时间范围」。
    # 控件只负责发信号，由 MainWindow 按当前模式复位视口。
    max_range_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        # 紧凑化【3】: tightened from 10 → 6 (2026-04-26).
        root.setSpacing(6)
        root.setContentsMargins(0, 0, 0, 0)

        # ------- Collapser handle -------
        # R3 #6: single-row toggle that reveals the inner three groups.
        # We use QToolButton so the arrow icon is rendered natively (no
        # painter call into icons.py for an admin affordance) and so the
        # button gets a proper "checkable" semantics.
        self.btn_collapser = QToolButton(self)
        self.btn_collapser.setObjectName("inspectorCollapser")
        self.btn_collapser.setCheckable(True)
        self.btn_collapser.setAutoRaise(True)
        self.btn_collapser.setText("图表设置 (横坐标 · 时间范围)")
        self.btn_collapser.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_collapser.setArrowType(Qt.RightArrow)
        self.btn_collapser.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed,
        )
        # Stylistic tweak — left-align the text so the arrow + label hug
        # the leading edge as a normal collapser would.
        try:
            self.btn_collapser.setStyleSheet(
                "QToolButton#inspectorCollapser { "
                "  text-align: left; padding: 4px 6px; font-weight: 600; "
                "  border: none; background: transparent; "
                "}"
                "QToolButton#inspectorCollapser:hover { background: #eef2f7; }"
            )
        except Exception:  # pragma: no cover — defensive on Qt style failures
            pass
        root.addWidget(self.btn_collapser)

        # ------- Collapser body (the two cards live here) -------
        # 2026-06-22 卡片重组: the persistent-top body now hosts TWO independent
        # white cards inside the collapser, replacing the previous single
        # body that stacked both groups in one card:
        #   ① _xaxis_card    — 横坐标 group + 「应用」 (semantics unchanged)
        #   ② _range_card    — 时间范围 group; the host Inspector adds the
        #                       FilterPanel here, below the range group, and the
        #                       contextual 「绘图」 button submits both.
        # The collapser still toggles both cards together. Card surfaces reuse
        # the existing white-card QSS (objectName-keyed) so neither shows a
        # default gray QFrame fill.
        self._collapser_body = QFrame(self)
        body_lay = QVBoxLayout(self._collapser_body)
        self._body_lay = body_lay
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)
        root.addWidget(self._collapser_body)

        def _make_card(object_name):
            card = QFrame(self._collapser_body)
            card.setObjectName(object_name)
            card.setAttribute(Qt.WA_StyledBackground, True)
            card_lay = QVBoxLayout(card)
            # 10px horizontal breathing room (matches the previous body inset)
            # now lives inside each card so the white surface hugs the content.
            card_lay.setContentsMargins(10, 6, 10, 8)
            card_lay.setSpacing(6)
            return card, card_lay

        # ------- Card ①: Xaxis -------
        self._xaxis_card, xaxis_card_lay = _make_card("timeXaxisCard")
        g = QGroupBox("横坐标")
        self._xaxis_group = g
        fl = QFormLayout(g)
        _configure_form(fl)
        self._xaxis_form = fl
        self._xlabel_auto_from_channel = False
        self.combo_xaxis = QComboBox()
        self.combo_xaxis.addItems(['自动(时间)', '指定通道'])
        self.choice_xaxis = SegmentedChoice()
        self.choice_xaxis.bind(self.combo_xaxis)
        fl.addRow("来源:", _fit_field(self.choice_xaxis))
        self._combo_xaxis_ch = SearchableComboBox()
        self._combo_xaxis_ch.setEnabled(False)
        fl.addRow("通道:", _fit_field(self._combo_xaxis_ch))
        self.edit_xlabel = QWidget()
        from PyQt5.QtWidgets import QLineEdit
        self.edit_xlabel = QLineEdit()
        self.edit_xlabel.setPlaceholderText("Time (s)")
        fl.addRow("标签:", _fit_field(self.edit_xlabel))
        self.btn_apply_xaxis = QPushButton("应用")
        self.btn_apply_xaxis.setProperty("role", "primary")
        fl.addRow(self.btn_apply_xaxis)
        xaxis_card_lay.addWidget(g)
        body_lay.addWidget(self._xaxis_card)

        # ------- Card ②: Range (+ FilterPanel, mounted by Inspector) -------
        self._range_card, range_card_lay = _make_card("timeRangeFilterCard")
        self._range_card_lay = range_card_lay
        # ------- Range group -------
        g = QGroupBox("时间范围")
        self._range_group = g
        g.setToolTip("限制参与绘图、统计、单次分析和导出的时间窗口（单位：秒）。")
        fl = QFormLayout(g)
        _configure_form(fl)
        self._range_form = fl
        self.chk_range = QCheckBox("使用选定时间范围")
        self.chk_range.setToolTip(
            "勾选后，只使用开始到结束之间的数据；取消勾选则使用全时段。"
        )
        # 「全部」停靠在勾选框这一行右端：查看全部（已绘制通道最长），不启用过滤。
        # 用扁平 QToolButton 复用 inspectorCollapser 的轻量观感。
        self.btn_range_max = QToolButton(self)
        self.btn_range_max.setObjectName("inspectorRangeMax")
        self.btn_range_max.setText("全部")
        self.btn_range_max.setToolTip(
            "查看全部：X 轴回到图面已绘制通道的最长全程"
            "（不启用「使用选定时间范围」）"
        )
        self.btn_range_max.setAutoRaise(True)
        self.btn_range_max.setCursor(Qt.PointingHandCursor)
        self.btn_range_max.setStyleSheet(
            "QToolButton#inspectorRangeMax { "
            "  padding: 2px 8px; border: none; background: transparent; "
            "  color: #2563eb; font-weight: 600; "
            "}"
            "QToolButton#inspectorRangeMax:hover { background: #eef2f7; }"
        )
        # Host row: [chk_range][stretch][全部].
        self._chk_range_host = QWidget()
        self._chk_range_host.setObjectName("timeRangeToggleRow")
        self._chk_range_host.setAutoFillBackground(False)
        self._chk_range_host.setAttribute(Qt.WA_StyledBackground, False)
        _chk_host_lay = QHBoxLayout(self._chk_range_host)
        _chk_host_lay.setContentsMargins(0, 0, 0, 0)
        _chk_host_lay.setSpacing(6)
        _chk_host_lay.addWidget(self.chk_range)
        _chk_host_lay.addStretch(1)
        _chk_host_lay.addWidget(self.btn_range_max)
        # Use the regular field column, rather than a spanning row, so the
        # checkbox border begins on the same x-coordinate as the start/end
        # editors in every mode that reparents this shared range group.
        fl.addRow("", self._chk_range_host)
        # 紧凑化【1】: 开始 / 结束 share one form row.
        self.spin_start = _no_buttons(CompactDoubleSpinBox())
        self.spin_start.setDecimals(3)
        self.spin_start.setSuffix(" s")
        self.spin_start.setRange(0, 1e9)
        self.spin_start.setToolTip("时间范围起点，单位为秒。")
        self.spin_end = _no_buttons(CompactDoubleSpinBox())
        self.spin_end.setDecimals(3)
        self.spin_end.setSuffix(" s")
        self.spin_end.setRange(0, 1e9)
        self.spin_end.setToolTip("时间范围终点，单位为秒。")
        self._range_row_host = _pair_field(
            self.spin_start, "– 结束", self.spin_end,
        )
        fl.addRow("开始:", self._range_row_host)
        range_card_lay.addWidget(g)
        body_lay.addWidget(self._range_card)

        # ------- Tick density compatibility state -------
        # The visible control moved to the chart toolbar popout. Keep these
        # hidden spin boxes so existing view-state/project plumbing can keep
        # using ``PersistentTop.tick_density()`` without a broad rewrite.
        self.spin_xt = _no_buttons(QSpinBox(self))
        self.spin_xt.setRange(3, 30)
        default_x, default_y = DEFAULT_CHART_TICK_DENSITY
        self.spin_xt.setValue(default_x)
        self.spin_xt.setToolTip("X 轴主刻度的大致数量，范围 3–30。")
        self.spin_xt.hide()
        self.spin_yt = _no_buttons(QSpinBox(self))
        self.spin_yt.setRange(3, 20)
        self.spin_yt.setValue(default_y)
        self.spin_yt.setToolTip("Y 轴主刻度的大致数量，范围 3–20。")
        self.spin_yt.hide()

        # Per-mode range-checkbox state. ``chk_range`` is a SINGLE QCheckBox
        # instance reparented across time/fft/fft_time/order modes by
        # inspector._place_range_group_for_mode. Its checked state must NOT
        # leak between modes (e.g. an FFT time-window drag force-checking the
        # box must not arrive checked when the user switches back to
        # Time-Domain). We snapshot/restore the checked flag per mode so each
        # mode keeps its own intent. Defaults to unchecked for every mode.
        self._range_mode = 'time'
        self._range_checked_by_mode = {}

        self._wire()
        self._xaxis_section_visible = True
        # Restore persisted collapser state (defaults to expanded).
        try:
            persisted = _preset_settings().value(self._SETTINGS_KEY, True)
            # QSettings can return strings on some platforms.
            if isinstance(persisted, str):
                persisted = persisted.lower() in ("true", "1", "yes")
            initial_expanded = bool(persisted)
        except Exception:  # pragma: no cover
            initial_expanded = True
        self.btn_collapser.setChecked(initial_expanded)
        self._sync_collapser(initial_expanded)
        # 紧凑化【2】: apply initial conditional visibility once everything
        # is wired (so a programmatic reset before show() also lands).
        self._update_xaxis_channel_row_visible(self.combo_xaxis.currentIndex())
        self._update_range_rows_visible()

        # 2026-04-26 R3 紧凑化 fix-3: cap the short numeric fields so toggling
        # 时间范围 / 通道 visibility no longer makes the pane look wider.
        # The label / xlabel fields keep room for representative text.
        for sp in (self.spin_start, self.spin_end, self.spin_xt, self.spin_yt):
            sp.setMaximumWidth(_SHORT_FIELD_MAX_WIDTH)
        # Long-text fields: xaxis source combo + label LineEdit may host
        # representative text; keep a generous (but not unbounded) cap.
        for w in (self.choice_xaxis, self._combo_xaxis_ch, self.edit_xlabel):
            w.setMaximumWidth(_LONG_FIELD_MAX_WIDTH)

    def _wire(self):
        self.combo_xaxis.currentIndexChanged.connect(
            lambda i: self._combo_xaxis_ch.setEnabled(i == 1)
        )
        # 紧凑化【2】: hide (not just disable) the 通道 row when 自动(时间).
        self.combo_xaxis.currentIndexChanged.connect(
            self._update_xaxis_channel_row_visible
        )
        self.chk_range.toggled.connect(self._update_range_rows_visible)
        # 「全部」只转发信号；MainWindow 负责按当前模式复位视口。
        self.btn_range_max.clicked.connect(self.max_range_requested)
        self.btn_apply_xaxis.clicked.connect(self.xaxis_apply_requested)
        self.spin_xt.valueChanged.connect(self._emit_ticks)
        self.spin_yt.valueChanged.connect(self._emit_ticks)
        # Sync label field when user changes channel selection interactively.
        # blockSignals during restore/repopulate suppresses this correctly.
        self._combo_xaxis_ch.currentIndexChanged.connect(self._sync_xlabel_from_channel)
        self.combo_xaxis.currentIndexChanged.connect(self._sync_xlabel_for_xaxis_mode)
        self.edit_xlabel.textEdited.connect(
            lambda _text: setattr(self, '_xlabel_auto_from_channel', False)
        )
        # R3 #6: collapser toggle reveals/hides the inner three groups
        # and persists the choice via QSettings.
        self.btn_collapser.toggled.connect(self._sync_collapser)

    def _sync_collapser(self, expanded):
        """Apply the collapser state to the body widget and arrow icon,
        then persist the choice. Safe to call before show().
        """
        expanded = bool(expanded)
        self._collapser_body.setVisible(expanded)
        self.btn_collapser.setArrowType(
            Qt.DownArrow if expanded else Qt.RightArrow,
        )
        try:
            _preset_settings().setValue(self._SETTINGS_KEY, expanded)
        except Exception:  # pragma: no cover
            pass

    def set_xaxis_section_visible(self, visible):
        """Show/hide the global custom-X controls for modes that use them."""
        self._xaxis_section_visible = bool(visible)
        self._xaxis_group.setVisible(self._xaxis_section_visible)
        text = (
            "图表设置 (横坐标 · 时间范围)"
            if self._xaxis_section_visible
            else "图表设置 (时间范围)"
        )
        self.btn_collapser.setText(text)

    def range_group(self):
        return self._range_group

    def range_group_layout(self):
        # 2026-06-22 卡片重组: the range group's home in time mode is now the
        # 时间范围·滤波 card's layout (was self._body_lay). The contextual modes
        # still reparent the group out via inspector._place_range_group_for_mode.
        return self._range_card_lay

    def xaxis_card(self):
        return self._xaxis_card

    def range_card(self):
        return self._range_card

    def range_card_layout(self):
        return self._range_card_lay

    def set_range_group_embedded(self, embedded):
        self._range_group.setTitle("分析时间" if embedded else "时间范围")

    def _sync_xlabel_from_channel(self, idx):
        if idx < 0:
            return
        data = self._combo_xaxis_ch.itemData(idx)
        if data is not None:
            try:
                _resolver, _fid, ch = data
            except (TypeError, ValueError):
                return
            self.edit_xlabel.setText(ch)
            self._xlabel_auto_from_channel = True

    def _sync_xlabel_for_xaxis_mode(self, idx):
        if idx == 1:
            self._sync_xlabel_from_channel(self._combo_xaxis_ch.currentIndex())
            return
        if self._xlabel_auto_from_channel:
            self.edit_xlabel.clear()
            self._xlabel_auto_from_channel = False

    def _update_xaxis_channel_row_visible(self, index):
        _set_form_row_visible(self._xaxis_form, self._combo_xaxis_ch, index == 1)

    def _update_range_rows_visible(self):
        _set_form_row_visible(self._range_form, self._range_row_host, True)

    def _emit_ticks(self):
        self.tick_density_changed.emit(self.spin_xt.value(), self.spin_yt.value())

    # ---- public getters/setters used by MainWindow ----
    def xaxis_mode(self):
        return 'channel' if self.combo_xaxis.currentIndex() == 1 else 'time'

    def set_xaxis_mode(self, mode):
        self.combo_xaxis.setCurrentIndex(1 if mode == 'channel' else 0)

    def xaxis_channel_data(self):
        """Return ``(resolver, fid, channel)`` tagged triple or ``None``."""
        if self.combo_xaxis.currentIndex() != 1:
            return None
        return self._combo_xaxis_ch.currentData()

    def xaxis_label(self):
        return self.edit_xlabel.text().strip()

    def set_xaxis_candidates(self, candidates):
        """Set ``(display_text, (resolver, fid, channel))`` candidates."""
        prev = self._combo_xaxis_ch.currentData()
        self._combo_xaxis_ch.blockSignals(True)
        _le = self._combo_xaxis_ch.lineEdit()
        _old_le = _le.blockSignals(True) if _le is not None else False
        try:
            self._combo_xaxis_ch.clear()
            keep_idx = -1
            for i, (text, data) in enumerate(candidates):
                self._combo_xaxis_ch.addItem(text, data)
                if prev is not None and data == prev:
                    keep_idx = i
            if keep_idx >= 0:
                self._combo_xaxis_ch.setCurrentIndex(keep_idx)
        finally:
            self._combo_xaxis_ch.blockSignals(False)
            if _le is not None:
                _le.blockSignals(_old_le)
        # Fresh population (no previous match): auto-fill label if empty.
        if keep_idx < 0 and self._combo_xaxis_ch.count() > 0 and not self.edit_xlabel.text():
            self._sync_xlabel_from_channel(0)

    def range_enabled(self):
        return self.chk_range.isChecked()

    def range_values(self):
        return (self.spin_start.value(), self.spin_end.value())

    def set_range_values(self, xmin, xmax):
        old_start = self.spin_start.blockSignals(True)
        old_end = self.spin_end.blockSignals(True)
        try:
            self.spin_start.setValue(float(xmin))
            self.spin_end.setValue(float(xmax))
        finally:
            self.spin_start.blockSignals(old_start)
            self.spin_end.blockSignals(old_end)

    def set_range_from_span(self, xmin, xmax):
        # Explicit arming path (FRF「取时域范围」, compute confirm, tests).
        # Stages start/end AND enables the range filter so the next analysis
        # compute (which reads range_enabled()) uses the window. 「全部」/
        # preview pan/zoom do NOT call this — they only draft via
        # set_range_values (manual check, same as Time-Domain). The checked
        # flag is recorded against the CURRENT mode so it does not leak into
        # Time-Domain on mode switch.
        self.set_range_values(xmin, xmax)
        old = self.chk_range.blockSignals(True)
        try:
            self.chk_range.setChecked(True)
        finally:
            self.chk_range.blockSignals(old)
        self._range_checked_by_mode[self._range_mode] = True
        self._update_range_rows_visible()

    def checkout_range_for_mode(self, mode):
        """Snapshot the outgoing mode's range-checkbox state and restore the
        incoming mode's. Called by inspector._place_range_group_for_mode on
        every mode switch so the SINGLE shared ``chk_range`` instance carries
        per-mode intent instead of leaking a force-checked state across modes.

        Restoring is done with signals blocked: the mode switch drives its own
        replot pipeline, and main_window wires ``chk_range.toggled`` to a
        replot slot that must not fire spuriously here.
        """
        if mode == self._range_mode:
            return
        # Save current mode's state before leaving it. Applying a restored
        # analysis view can seed the target mode before its card is visible;
        # a same-mode checkout must not overwrite that seed with the still
        # displayed previous checkbox value.
        self._range_checked_by_mode[self._range_mode] = self.chk_range.isChecked()
        target = bool(self._range_checked_by_mode.get(mode, False))
        old = self.chk_range.blockSignals(True)
        try:
            self.chk_range.setChecked(target)
        finally:
            self.chk_range.blockSignals(old)
        self._range_mode = mode
        self._update_range_rows_visible()

    def set_range_limits(self, lo, hi):
        # F14: setRange may clamp the current value and emit valueChanged.
        # There is no subscriber today, but the next connected slot would see
        # a programmatic limit refresh as a user edit — block while applying.
        for sp in (self.spin_start, self.spin_end):
            old = sp.blockSignals(True)
            try:
                sp.setRange(lo, hi)
            finally:
                sp.blockSignals(old)

    def tick_density(self):
        return (self.spin_xt.value(), self.spin_yt.value())
