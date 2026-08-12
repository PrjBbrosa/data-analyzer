"""FFTContextual widget."""
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...analysis_presets import list_builtin_presets
from ...signal.analysis_defaults import ANALYSIS_WINDOW_CANDIDATES
from ...ui_kit.icons import Icons
from ...ui_kit.widgets.segmented_choice import SegmentedChoice
from ...ui_kit.widgets.searchable_combo import SearchableComboBox
from ..widgets.compact_spinbox import CompactDoubleSpinBox
from ._helpers import (
    CUSTOM_PRESET_SLOTS,
    _LONG_FIELD_MAX_WIDTH,
    _PRESET_KEY_TO_SLOT,
    _SHORT_FIELD_MAX_WIDTH,
    _configure_form,
    _enforce_label_widths,
    _fit_field,
    _make_axis_settings_group,
    _make_group_header,
    _make_params_card,
    _no_buttons,
    apply_db_reference_partial,
    apply_db_reference_preset,
    db_reference_params,
    make_db_reference_control,
    recommend_preset_for_unit,
)
from .collapsible import _CollapsibleParamSection
from .presets import PresetBar


class FFTContextual(QWidget):
    """FFT contextual: signal/Fs/params/options + compute button."""

    fft_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    remark_toggled = pyqtSignal(bool)
    signal_changed = pyqtSignal(object)  # emits (fid, ch) or None
    compute_params_changed = pyqtSignal(object)
    display_params_changed = pyqtSignal(object)
    _AUTO_NFFT_LABEL = "自动"
    _NO_SOURCE_SUMMARY = "未选通道，使用单信号"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fftContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._applying_preset = False
        self._source_weighting_default = 'None'
        self._t_win_s = 1.5
        # Auto-NFFT preview data hook: a callable returning the available sample
        # count for the current FFT signal (or None when no data is loaded). Set
        # by the main window so the collapsed 自动(N) mirrors the data-aware
        # ``_resolve_fft_effective_params`` (whole-signal length for single-frame,
        # the shared ``resolve_nfft`` segment for averaging modes).
        self._auto_nfft_provider = None
        root = QVBoxLayout(self)
        # 2026-06-13 分析信号/谱参数 split: the contextual is a transparent
        # host for two full-width cards (sig_card + params_card). Zero
        # horizontal margins so each card spans the pane edge-to-edge; the
        # spacing is the 8px gutter between the two cards.
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # R3 #9: build btn_rebuild *before* the analyse-signal group so we
        # can hand it off to the group's header row instead of attaching
        # it to the Fs form field.
        # 2026-04-26 R3 紧凑化 fix-4: setFixedSize(24, 24) replaces the
        # earlier setMaximumWidth(30) — the icon stays 16x16 but the outer
        # chrome is no longer big enough to hold two icons side-by-side.
        self.btn_rebuild = QPushButton("")
        self.btn_rebuild.setIcon(Icons.rebuild_time())
        self.btn_rebuild.setIconSize(QSize(16, 16))
        self.btn_rebuild.setFixedSize(QSize(24, 24))
        self.btn_rebuild.setProperty("role", "icon")
        self.btn_rebuild.setToolTip("重建时间轴")
        self.btn_rebuild.setAccessibleName("重建时间轴")

        # ---- 分析信号 (custom header so btn_rebuild docks top-right) ----
        # 2026-04-26 R3 紧凑化 fix-2: do NOT enable WA_StyledBackground on
        # this QFrame. Without a paired QSS rule it would render with the
        # default white QFrame fill and break the tinted contextual card
        # background bleed-through (see lesson
        # 2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md).
        sig_card = QFrame(self)
        sig_card.setObjectName("fftSignalCard")
        sig_lay = QVBoxLayout(sig_card)
        # 2026-06-13 split: sig_card now carries its own 10px inner padding
        # (the outer contextual no longer supplies it) so it reads as a
        # self-contained full-width panel whose fields stay column-aligned
        # with the params_card below.
        sig_lay.setContentsMargins(10, 8, 10, 10)
        sig_lay.setSpacing(4)
        sig_lay.addWidget(_make_group_header("分析信号 + 时间", self.btn_rebuild))
        fl = QFormLayout()
        _configure_form(fl)
        self.lbl_source_summary = QWidget()
        from PyQt5.QtWidgets import QLabel
        self.lbl_source_summary = QLabel(self._NO_SOURCE_SUMMARY)
        self.lbl_source_summary.setObjectName("fftSourceSummary")
        self.lbl_source_summary.setWordWrap(False)
        fl.addRow(
            "输入源:",
            _fit_field(self.lbl_source_summary, max_width=_LONG_FIELD_MAX_WIDTH),
        )
        self.combo_sig = SearchableComboBox()
        # combo_sig hosts long signal names — keep the long-text cap.
        self.lbl_single_signal = QLabel("单信号:")
        fl.addRow(
            self.lbl_single_signal,
            _fit_field(self.combo_sig, max_width=_LONG_FIELD_MAX_WIDTH),
        )
        self.spin_fs = _no_buttons(CompactDoubleSpinBox())
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fl.addRow("Fs:", _fit_field(self.spin_fs, max_width=_SHORT_FIELD_MAX_WIDTH))
        sig_lay.addLayout(fl)
        self._time_range_slot = QVBoxLayout()
        self._time_range_slot.setContentsMargins(0, 0, 0, 0)
        self._time_range_slot.setSpacing(0)
        sig_lay.addLayout(self._time_range_slot)
        root.addWidget(sig_card)

        # 2026-06-13 split: everything below the green analysis-signal card
        # lives in its own full-width tinted panel (谱参数 + 坐标轴设置 +
        # 预设配置 + 计算 FFT).
        params_card, params_lay = _make_params_card(self, "fftParamsCard")

        g = QWidget()
        from PyQt5.QtWidgets import QGroupBox
        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        _configure_form(fl)
        # R3 change A: revert R1's inline 窗函数+NFFT pair — three
        # independent rows match FFTTimeContextual's 时频参数 group.
        # 2026-04-26 R3 紧凑化 fix-3: cap each short field so the row
        # column never balloons when the splitter widens.
        self.combo_win = QComboBox()
        self.combo_win.addItems(list(ANALYSIS_WINDOW_CANDIDATES))
        self.combo_win.setToolTip('抑制频谱泄漏：flattop 幅值最准、\nhanning 最均衡、blackman 旁瓣最低。')
        fl.addRow("窗函数:", _fit_field(self.combo_win, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(
            [self._AUTO_NFFT_LABEL, '512', '1024', '2048', '4096', '8192', '16384']
        )
        self.combo_nfft.setToolTip('越大频率越细、计算量越高；\n「自动」＝按窗长取 2 的幂。')
        fl.addRow("NFFT:", _fit_field(self.combo_nfft, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.spin_overlap = _no_buttons(QSpinBox())
        self.spin_overlap.setRange(0, 90)
        self.spin_overlap.setValue(50)
        self.spin_overlap.setSuffix(" %")
        self.spin_overlap.setToolTip('相邻分析帧的重叠：越高频谱越平滑、计算量越大。')
        fl.addRow("重叠:", _fit_field(self.spin_overlap, max_width=_SHORT_FIELD_MAX_WIDTH))

        # --- Averaging (Welch / peak-hold) — Wave 2 / SP2 / Task 2.1 ---
        # 单帧 = single FFT snapshot (legacy default).
        # 线性平均 = Welch averaging (噪声地板下降).
        # 峰值保持 = per-frequency max across overlapping segments.
        self.combo_avg_mode = QComboBox()
        self.combo_avg_mode.addItems(['单帧', '线性平均', '峰值保持'])
        self.combo_avg_mode.setCurrentText('单帧')
        self.combo_avg_mode.setToolTip(
            "单帧：单次快照，显示瞬时幅值（峰值口径）。\n"
            "线性平均：多段 RMS 平均（均方根口径），相比单帧约低 3 dB——\n"
            "    对于纯正弦信号这是正常的能量等价，并非缺陷。\n"
            "峰值保持：每个频率保留多段中的最大值（峰值口径），\n"
            "    适合捕捉瞬态，幅值与单帧一致。"
        )
        fl.addRow(
            "平均模式:",
            _fit_field(self.combo_avg_mode, max_width=_SHORT_FIELD_MAX_WIDTH),
        )

        self.spin_avg_overlap = _no_buttons(QSpinBox())
        self.spin_avg_overlap.setRange(0, 95)
        self.spin_avg_overlap.setValue(50)
        self.spin_avg_overlap.setSuffix(" %")
        self.spin_avg_overlap.setEnabled(False)
        self.spin_avg_overlap.setToolTip("仅在平均/峰值保持模式下生效")
        fl.addRow(
            "重叠率:",
            _fit_field(self.spin_avg_overlap, max_width=_SHORT_FIELD_MAX_WIDTH),
        )

        self.combo_avg_mode.currentTextChanged.connect(
            lambda txt: self.spin_avg_overlap.setEnabled(txt != '单帧')
        )

        # ``combo_amp_y`` is the preserved ``amp_y`` preset/project state
        # surface.  Its visible host moves below the Y-axis row in 坐标轴设置;
        # it must not be replaced by the helper's different combo_amp_unit.
        self.combo_amp_y = QComboBox()
        self.combo_amp_y.addItems(['Linear', 'dB'])
        self.combo_amp_y.setCurrentText('Linear')
        self.combo_amp_y.setToolTip('dB 看宽动态，Linear 看绝对幅值。')
        self.choice_amp_y = SegmentedChoice()
        self.choice_amp_y.bind(self.combo_amp_y)
        self.combo_weighting = QComboBox()
        self.combo_weighting.addItems(['None', 'A'])
        self.combo_weighting.setCurrentText('None')
        self.combo_weighting.setToolTip(
            'A 计权（IEC 61672）：相对加权频谱，非绝对 dB SPL'
        )
        self.choice_weighting = SegmentedChoice()
        self.choice_weighting.bind(self.combo_weighting)
        fl.addRow(
            "频率加权:",
            _fit_field(self.choice_weighting, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        self.db_reference_control = make_db_reference_control(self)
        self.spin_db_ref = self.db_reference_control.editor
        g.setTitle("")
        # The section header already shows the title; drop the title band and
        # let the body carry a hairline top divider (see style.qss
        # #paramsSectionBody) so the expanded detail matches the mockup.
        g.setObjectName("paramsSectionBody")
        self._fft_section = _CollapsibleParamSection(
            "谱参数",
            "inspector/fft/params_expanded",
            parent=self,
        )
        self._fft_section.set_body(g)
        params_lay.addWidget(self._fft_section)

        axis_g = _make_axis_settings_group(
            self,
            x_label="频率 (X):", x_unit='Hz',
            x_default_min=0.0, x_default_max=0.0,
            y_label="幅值 (Y):", y_unit='',
            y_default_min=0.0, y_default_max=0.0,
            x_default_auto=True,
            y_default_auto=True,
            x_auto_summary="自适应频率",
            y_auto_summary="自动范围",
            include_z=False,
            pre_header_rows=(("dB 参考:", self.db_reference_control),),
            amplitude_unit_row_label="幅值单位:",
            amplitude_unit_widget=self.choice_amp_y,
        )
        # The relocated 32px host adds one axis-layout gap while the removed
        # form row removes one.  This local 2px rhythm preserves the measured
        # 748px → 740px compacting contract at a 288px Inspector width; other
        # analysis panels (including FRF) keep their own vertical spacing.
        axis_g.layout().setSpacing(2)
        for spin in (self.spin_y_min, self.spin_y_max):
            spin.setRange(-1e12, 1e12)
        params_lay.addWidget(axis_g)
        # Backward-compatible alias for old presets and rendering code:
        # legacy "autoscale" is now the X-axis auto toggle.
        self.chk_autoscale = self.chk_x_auto
        # Backward-compatible state holder for old presets/signals. The
        # user-facing annotation control now lives on the chart toolbar.
        self.chk_remark = QCheckBox("点击标注", self)
        self.chk_remark.setVisible(False)

        # Signal-type built-in presets (频率 / 均衡 / 时间) plus one separate
        # user snapshot slot. Builtin order remains the shared recommendation
        # contract from BUILTIN_PRESET_KEYS.
        self.preset_bar = PresetBar(
            'fft', self._collect_preset, self._apply_preset, parent=self,
            builtin_defaults=self._builtin_preset_defaults(),
            default_params=self._collect_preset(),
            custom_slots=CUSTOM_PRESET_SLOTS,
        )
        self._fft_section.add_persistent(self.preset_bar)

        self.btn_fft = QPushButton("计算 FFT")
        self.btn_fft.setIcon(Icons.mode_fft())
        self.btn_fft.setIconSize(QSize(16, 16))
        self.btn_fft.setProperty("role", "primary")
        params_lay.addWidget(self.btn_fft)
        root.addWidget(params_card)
        root.addStretch()

        # 2026-04-27 fix-4: unify the label-column width across the
        # sig_card form ("信号" / "Fs") and the 谱参数 QGroupBox form
        # ("窗函数" / "NFFT" / "重叠"). QFormLayout pins each form's label
        # column to the *form's own* max sizeHint, so without this call
        # sig_card labels render in a 36px column while the 谱参数 labels
        # use a 60px column, and the field columns drift apart by ~24px.
        # ``unify_columns=True`` pins every label to the global max so all
        # five fields share the same field-column width and right edge.
        _enforce_label_widths(self, unify_columns=True)

        self.btn_fft.clicked.connect(self.fft_requested)
        self.btn_rebuild.clicked.connect(
            lambda: self.rebuild_time_requested.emit(self.btn_rebuild)
        )
        self.chk_remark.toggled.connect(self.remark_toggled)
        self._connect_preset_param_signals()
        self._refresh_fft_summary()
        self._sync_axis_enabled()
        # §6.3 Fs rule: spin_fs reflects selected signal's source file Fs.
        # MainWindow will call set_fs via the signal_changed relay.

    def time_range_layout(self):
        return self._time_range_slot

    def is_fft_params_expanded(self):
        return self._fft_section.is_expanded()

    def set_auto_nfft_provider(self, provider):
        """Register the available-samples hook for the auto-NFFT summary.

        ``provider`` is a zero-arg callable returning the sample count of the
        current FFT signal (int) or ``None`` when no usable data is loaded.
        Passing ``None`` clears the hook. Refreshes the collapsed summary so the
        displayed 自动(N) updates at once.
        """
        self._auto_nfft_provider = provider
        self._refresh_fft_summary()

    def _fft_nfft_preview(self):
        """Data-aware effective NFFT for the auto summary, or None if unknown.

        Mirrors ``_fft_mixin._resolve_fft_effective_params``: single-frame auto
        keeps whole-signal semantics (full sample count); averaging / peak-hold
        modes resolve a segment length via the shared ``resolve_nfft``. Returns
        None when no data provider is wired (header then shows a bare 自动).
        """
        if self._auto_nfft_provider is None:
            return None
        try:
            n_samples = self._auto_nfft_provider()
        except Exception:
            return None
        if n_samples is None or int(n_samples) <= 1:
            return None
        n_samples = int(n_samples)
        if self.combo_avg_mode.currentText() in ('线性平均', '峰值保持'):
            from ...signal import resolve_nfft

            overlap = float(self.spin_avg_overlap.value()) / 100.0
            return int(
                resolve_nfft(
                    float(self.spin_fs.value()),
                    n_samples,
                    float(self._t_win_s),
                    overlap,
                )
            )
        # 单帧 auto = whole-signal FFT → the effective length is the data length.
        return n_samples

    def _fft_summary_text(self):
        nfft_text = self.combo_nfft.currentText()
        if nfft_text == self._AUTO_NFFT_LABEL:
            preview = self._fft_nfft_preview()
            if preview is not None:
                nfft_text = f"{self._AUTO_NFFT_LABEL}({preview})"
        return (
            f"{nfft_text} · "
            f"{self.combo_win.currentText()} · "
            f"{self.spin_overlap.value()}%"
        )

    def _refresh_fft_summary(self):
        self._fft_section.set_summary(self._fft_summary_text())

    def _on_preset_param_changed(self, *_):
        if not self._applying_preset:
            self.preset_bar.set_recommended(None)
        self._refresh_fft_summary()
        if self._applying_preset:
            return
        sender = self.sender()
        if sender in self._display_param_widgets:
            self.display_params_changed.emit(self.display_params())
        else:
            self.compute_params_changed.emit(self.compute_params())

    def _connect_preset_param_signals(self):
        for combo in (
            self.combo_win,
            self.combo_nfft,
            self.combo_avg_mode,
            self.combo_amp_y,
            self.combo_weighting,
        ):
            combo.currentTextChanged.connect(self._on_preset_param_changed)
        for spin in (self.spin_overlap, self.spin_avg_overlap):
            spin.valueChanged.connect(self._on_preset_param_changed)
        self._display_param_widgets = (
            self.combo_amp_y,
            self.spin_overlap,
            self.chk_x_auto,
            self.spin_x_min,
            self.spin_x_max,
            self.chk_y_auto,
            self.spin_y_min,
            self.spin_y_max,
            self.chk_remark,
        )
        for check in (self.chk_x_auto, self.chk_y_auto, self.chk_remark):
            check.toggled.connect(self._on_preset_param_changed)
        for spin in (
            self.spin_x_min, self.spin_x_max,
            self.spin_y_min, self.spin_y_max,
        ):
            spin.valueChanged.connect(self._on_preset_param_changed)

    def _apply_weighting_value(self, value):
        target = 'A' if str(value).upper() == 'A' else 'None'
        i = self.combo_weighting.findText(target)
        if i >= 0:
            self.combo_weighting.setCurrentIndex(i)

    def _sync_source_weighting_defaults(self):
        target = self._source_weighting_default
        bar = getattr(self, 'preset_bar', None)
        default_params = getattr(bar, '_default_params', None)
        if isinstance(default_params, dict):
            default_params['weighting'] = target

    def set_weighting_default(self, mode):
        if self._applying_preset:
            return
        self._source_weighting_default = (
            'A' if str(mode).upper() == 'A' else 'None'
        )
        self._sync_source_weighting_defaults()
        self._apply_weighting_value(self._source_weighting_default)

    def _sync_axis_enabled(self):
        for key in ('x', 'y'):
            parts = self._axis_row_parts[key]
            auto = parts['checkbox'].isChecked()
            parts['stack'].setCurrentWidget(
                parts['summary_page'] if auto else parts['manual_page']
            )
            parts['summary_page'].setVisible(auto)
            parts['manual_page'].setVisible(not auto)
            parts['summary'].setVisible(auto)
            for w in (parts['spin_min'], parts['arrow'], parts['spin_max']):
                w.setVisible(not auto)
            for s in (parts['spin_min'], parts['spin_max']):
                s.setEnabled(not auto)

    def _apply_axis_params(self, d):
        if 'autoscale' in d and 'x_auto' not in d:
            self.chk_x_auto.setChecked(bool(d['autoscale']))
        for key, attr in (
            ('x_auto', 'chk_x_auto'),
            ('y_auto', 'chk_y_auto'),
        ):
            if key in d:
                getattr(self, attr).setChecked(bool(d[key]))
        for key, attr in (
            ('x_min', 'spin_x_min'), ('x_max', 'spin_x_max'),
            ('y_min', 'spin_y_min'), ('y_max', 'spin_y_max'),
        ):
            if key in d:
                try:
                    getattr(self, attr).setValue(float(d[key]))
                except (TypeError, ValueError):
                    pass
        self._sync_axis_enabled()

    # Signal-type built-in preset params (信号专家 校核定稿 — do NOT alter the
    # numeric values). FFT-1D has NO remove_mean field; amplitude axis is
    # ``amp_y`` ('Linear'/'dB'); 平均模式 text is 单帧/线性平均/峰值保持.
    _SIGNAL_BUILTIN_PRESETS = {
        preset.key: preset.params_copy()
        for preset in list_builtin_presets('fft')
    }

    def _builtin_preset_defaults(self):
        return {
            preset.slot: {
                'display_name': preset.display_name,
                'params': preset.params_copy(),
            }
            for preset in list_builtin_presets('fft')
        }

    def set_recommended_for_unit(self, unit):
        """Highlight the preset slot recommended for ``unit`` (or clear).

        ``unit=None`` clears the highlight (used when the selection is empty).
        """
        if unit is None:
            self.preset_bar.set_recommended(None)
            return
        key = recommend_preset_for_unit(unit)
        self.preset_bar.set_recommended(_PRESET_KEY_TO_SLOT[key])

    def _collect_preset(self):
        return dict(
            window=self.combo_win.currentText(),
            nfft=self.combo_nfft.currentText(),
            nfft_mode=(
                'auto'
                if self.combo_nfft.currentText() == self._AUTO_NFFT_LABEL
                else 'fixed'
            ),
            t_win_s=float(self._t_win_s),
            overlap=self.spin_overlap.value(),
            avg_mode=self.combo_avg_mode.currentText(),
            avg_overlap=self.spin_avg_overlap.value(),
            amp_y=self.combo_amp_y.currentText(),
            weighting=self.combo_weighting.currentText(),
            **db_reference_params(self.db_reference_control),
            autoscale=self.chk_x_auto.isChecked(),
            x_auto=self.chk_x_auto.isChecked(),
            x_min=float(self.spin_x_min.value()),
            x_max=float(self.spin_x_max.value()),
            y_auto=self.chk_y_auto.isChecked(),
            y_min=float(self.spin_y_min.value()),
            y_max=float(self.spin_y_max.value()),
            remark=self.chk_remark.isChecked(),
        )

    def _apply_preset(self, d):
        before_compute = self.compute_params()
        before_display = self.display_params()
        self._applying_preset = True
        try:
            self._apply_preset_values(d)
        finally:
            self._applying_preset = False
            self._refresh_fft_summary()
        self._emit_param_deltas(before_compute, before_display)

    def _apply_preset_values(self, d):
        if 'window' in d:
            i = self.combo_win.findText(str(d['window']))
            if i >= 0:
                self.combo_win.setCurrentIndex(i)
        if 't_win_s' in d:
            try:
                self._t_win_s = float(d['t_win_s'])
            except (TypeError, ValueError):
                pass
        if 'nfft' in d:
            if (
                d.get('nfft_mode') == 'auto'
                or d['nfft'] is None
                or str(d['nfft']) == self._AUTO_NFFT_LABEL
            ):
                i = self.combo_nfft.findText(self._AUTO_NFFT_LABEL)
            else:
                i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'overlap' in d:
            self.spin_overlap.setValue(int(d['overlap']))
        self._apply_axis_params(d)
        if 'remark' in d:
            self.chk_remark.setChecked(bool(d['remark']))
        if 'avg_mode' in d:
            i = self.combo_avg_mode.findText(str(d['avg_mode']))
            if i >= 0:
                self.combo_avg_mode.setCurrentIndex(i)
        if 'avg_overlap' in d:
            try:
                self.spin_avg_overlap.setValue(int(d['avg_overlap']))
            except (TypeError, ValueError):
                pass
        if 'amp_y' in d:
            i = self.combo_amp_y.findText(str(d['amp_y']))
            if i >= 0:
                self.combo_amp_y.setCurrentIndex(i)
        apply_db_reference_preset(self.db_reference_control, d)
        if 'weighting' in d:
            self._apply_weighting_value(d['weighting'])

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    def set_source_summary(self, labels):
        labels = [str(v) for v in (labels or []) if str(v)]
        if labels:
            n = len(labels)
            suffix = " · 叠加" if n > 1 else ""
            self.lbl_source_summary.setText(f"左侧已选 {n} 个信号{suffix}")
            self.lbl_source_summary.setToolTip("\n".join(labels))
            self.lbl_single_signal.setVisible(False)
            self.combo_sig.setVisible(False)
        else:
            self.lbl_source_summary.setText(self._NO_SOURCE_SUMMARY)
            self.lbl_source_summary.setToolTip("")
            self.lbl_single_signal.setVisible(True)
            self.combo_sig.setVisible(True)

    def set_signal_candidates(self, candidates):
        # Preserve the user's current selection across repopulation —
        # editing channels / loading a new file refreshes candidates,
        # and dropping back to index 0 was a regression (commit
        # 0132253 fixed xaxis + fft_time but missed FFT/Order).
        prev = self.combo_sig.currentData()
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        keep_idx = -1
        for i, (text, data) in enumerate(candidates):
            self.combo_sig.addItem(text, data)
            if prev is not None and data == prev:
                keep_idx = i
        # No prior selection to preserve -> leave the combo unselected (-1)
        # instead of defaulting to the first signal. The old auto-select + emit
        # planted a phantom default (drew a time preview / looked like a
        # configured analysis) on project open even when nothing was ever
        # computed. The saved-source restore (_apply_analysis_sources) selects
        # the signal explicitly when the project did compute this analysis, so
        # the "previously computed -> preselect" case is unaffected.
        self.combo_sig.setCurrentIndex(keep_idx)
        self.combo_sig.blockSignals(False)
        try:
            self.combo_sig.currentIndexChanged.disconnect(self._on_sig_index_changed)
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)

    def current_signal(self):
        return self.combo_sig.currentData()

    def compute_params(self):
        nfft_text = self.combo_nfft.currentText()
        auto = nfft_text == self._AUTO_NFFT_LABEL
        nfft = None if auto else int(nfft_text)
        return dict(
            window=self.combo_win.currentText(),
            nfft=nfft,
            nfft_mode='auto' if auto else 'fixed',
            t_win_s=float(self._t_win_s),
            nfft_effective=None if auto else nfft,
            avg_mode=self.combo_avg_mode.currentText(),
            avg_overlap=int(self.spin_avg_overlap.value()),
            weighting=self.combo_weighting.currentText(),
        )

    def display_params(self):
        return dict(
            # This legacy overlap knob is retained in the View/preset payload,
            # but Welch uses avg_overlap and it is deliberately not part of the
            # spectrum cache identity.
            overlap=self.spin_overlap.value() / 100.0,
            **db_reference_params(self.db_reference_control),
            autoscale=self.chk_x_auto.isChecked(),
            x_auto=bool(self.chk_x_auto.isChecked()),
            x_min=float(self.spin_x_min.value()),
            x_max=float(self.spin_x_max.value()),
            y_auto=bool(self.chk_y_auto.isChecked()),
            y_min=float(self.spin_y_min.value()),
            y_max=float(self.spin_y_max.value()),
            remark=self.chk_remark.isChecked(),
            amp_y=self.combo_amp_y.currentText(),
        )

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(fs)
        self.spin_fs.blockSignals(False)
        # Source/Fs change is the data-context hook: repaint the collapsed
        # summary so the data-aware 自动(N) tracks the new selection (mirrors
        # FFTTimeContextual.set_fs).
        self._refresh_fft_summary()

    def current_params(self):
        return {**self.compute_params(), **self.display_params()}

    def get_params(self):
        """Compatibility name for the complete, View-persistent payload."""
        return self.current_params()

    def _emit_param_deltas(self, before_compute, before_display):
        compute = self.compute_params()
        display = self.display_params()
        if compute != before_compute:
            self.compute_params_changed.emit(compute)
        if display != before_display:
            self.display_params_changed.emit(display)

    def apply_params(self, d):
        if 'window' in d:
            i = self.combo_win.findText(str(d['window']))
            if i >= 0:
                self.combo_win.setCurrentIndex(i)
        if 't_win_s' in d:
            try:
                self._t_win_s = float(d['t_win_s'])
            except (TypeError, ValueError):
                pass
        if 'nfft' in d:
            if (
                d.get('nfft_mode') == 'auto'
                or d['nfft'] is None
                or str(d['nfft']) == self._AUTO_NFFT_LABEL
            ):
                i = self.combo_nfft.findText(self._AUTO_NFFT_LABEL)
            else:
                i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'overlap' in d:
            # get_params() emits overlap as a FRACTION (0.5); the spinbox is in
            # PERCENT. Accept either: <= 1 is treated as a fraction, > 1 as an
            # already-percent value. Without this, a view-restore round-trip
            # would do int(0.5) == 0 and drift the overlap toward 0 %.
            try:
                v = float(d['overlap'])
                self.spin_overlap.setValue(int(v * 100) if v <= 1 else int(v))
            except (TypeError, ValueError):
                pass
        self._apply_axis_params(d)
        if 'remark' in d:
            self.chk_remark.setChecked(bool(d['remark']))
        if 'avg_mode' in d:
            i = self.combo_avg_mode.findText(str(d['avg_mode']))
            if i >= 0:
                self.combo_avg_mode.setCurrentIndex(i)
        if 'avg_overlap' in d:
            try:
                self.spin_avg_overlap.setValue(int(d['avg_overlap']))
            except (TypeError, ValueError):
                pass
        if 'amp_y' in d:
            i = self.combo_amp_y.findText(str(d['amp_y']))
            if i >= 0:
                self.combo_amp_y.setCurrentIndex(i)
        apply_db_reference_partial(self.db_reference_control, d)
        if 'weighting' in d:
            self._apply_weighting_value(d['weighting'])

    def reset_to_defaults(self):
        """Restore construction-time defaults for a blank analysis View."""
        bar = getattr(self, 'preset_bar', None)
        defaults = getattr(bar, '_default_params', None) if bar is not None else None
        if isinstance(defaults, dict) and defaults:
            self.apply_params(dict(defaults))
