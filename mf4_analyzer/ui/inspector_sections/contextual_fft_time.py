"""FFTTimeContextual widget."""
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.icons import Icons
from ...ui_kit.widgets.searchable_combo import SearchableComboBox
from ..widgets.compact_spinbox import CompactDoubleSpinBox
from .._axis_defaults import z_range_for
from ._helpers import (
    BUILTIN_PRESET_DISPLAY,
    BUILTIN_PRESET_KEYS,
    _LONG_FIELD_MAX_WIDTH,
    _PRESET_KEY_TO_SLOT,
    _SHORT_FIELD_MAX_WIDTH,
    _configure_form,
    _dynamic_to_floor,
    _enforce_label_widths,
    _fit_field,
    _make_axis_settings_group,
    _make_group_header,
    _make_params_card,
    _no_buttons,
    recommend_preset_for_unit,
)
from .collapsible import _CollapsibleParamSection
from .presets import PresetBar


class FFTTimeContextual(QWidget):
    """FFT vs Time contextual: signal / time-frequency params / amplitude /
    range-and-color / presets / actions.

    Public surface consumed by ``Inspector`` and ``MainWindow``:

    Signals
    -------
    - ``fft_time_requested`` — primary "compute" button click.

    Widgets (referenced by name from MainWindow / tests)
    ---------------------------------------------------
    - ``combo_sig`` — analysis signal candidate (``(fid, ch)`` userData).
    - ``spin_fs`` — sampling frequency (Hz).
    - ``btn_rebuild`` — relay anchor for "rebuild time axis" host action.
    - ``combo_nfft`` / ``combo_win`` / ``spin_overlap`` /
      ``chk_remove_mean`` — analysis parameters.
    - ``spin_db_ref`` — dB reference (linear amplitude).
    - 坐标轴设置 group (2026-04-29 B polish):
      ``chk_x_auto`` / ``spin_x_min`` / ``spin_x_max`` — X time (s);
      ``chk_y_auto`` / ``spin_y_min`` / ``spin_y_max`` — Y frequency (Hz);
      ``chk_z_auto`` / ``spin_z_floor`` / ``spin_z_ceiling`` — Z (color
      scale); ``combo_amp_unit`` — dB ↔ Linear (replaces the legacy
      ``combo_amp_mode``). All four feed the spectrogram render.
    - Backward-compat aliases for downstream MainWindow callers (Wave 5
      will retire the legacy names): ``chk_freq_auto`` IS ``chk_y_auto``;
      ``spin_freq_min`` IS ``spin_y_min``; ``spin_freq_max`` IS
      ``spin_y_max``. ``spin_freq_max == 0.0`` still means "use Nyquist".
    - ``btn_compute`` — primary action; disabled iff no candidate.

    ``get_params()`` returns a dict whose keys match exactly what
    ``MainWindow._fft_time_cache_key`` expects: ``signal``, ``fs``,
    ``nfft``, ``window``, ``overlap``, ``remove_mean``, ``amplitude_mode``,
    ``db_reference``, ``freq_auto``, ``freq_min``, ``freq_max``,
    ``dynamic``, ``cmap``. Wave 4 also adds the explicit axis keys
    ``x_auto``/``x_min``/``x_max``, ``y_auto``/``y_min``/``y_max``,
    ``z_auto``/``z_floor``/``z_ceiling`` alongside the legacy keys.

    Built-in presets: ``torque``, ``vibration``, ``transient``. Legacy keys
    (``diagnostic``, ``amplitude_accuracy``, ``high_frequency``) remain aliases
    for old regression callers.
    """

    fft_time_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)  # anchor widget
    signal_changed = pyqtSignal(object)  # emits (fid, ch) or None
    _AUTO_NFFT_LABEL = "自动"
    # 2026-06-19: 时频图色图固定为 turbo（用户要求移除可切换的色图控件）。
    # get_params()/_collect_preset() 以此常量发出 cmap 键，保持下游契约不变。
    _FIXED_CMAP = "turbo"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fftTimeContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._applying_preset = False
        self._t_win_s = 1.5
        root = QVBoxLayout(self)
        # 2026-06-13 分析信号/谱参数 split: transparent host for two
        # full-width cards (sig_card + params_card); spacing is the gutter.
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ---- 分析信号 (R3 #9: btn_rebuild docked on header bar) ----
        # 2026-04-26 R3 紧凑化 fix-4: setFixedSize(24, 24).
        self.btn_rebuild = QPushButton("")
        self.btn_rebuild.setIcon(Icons.rebuild_time())
        self.btn_rebuild.setIconSize(QSize(16, 16))
        self.btn_rebuild.setFixedSize(QSize(24, 24))
        self.btn_rebuild.setProperty("role", "tool")
        self.btn_rebuild.setToolTip("重建时间轴")
        self.btn_rebuild.clicked.connect(
            lambda: self.rebuild_time_requested.emit(self.btn_rebuild)
        )
        # 2026-04-26 R3 紧凑化 fix-2: WA_StyledBackground intentionally OFF.
        sig_card = QFrame(self)
        sig_card.setObjectName("fftTimeSignalCard")
        sig_lay = QVBoxLayout(sig_card)
        # 2026-06-13 split: sig_card carries its own 10px inner padding.
        sig_lay.setContentsMargins(10, 8, 10, 10)
        sig_lay.setSpacing(4)
        sig_lay.addWidget(_make_group_header("分析信号 + 时间", self.btn_rebuild))
        fl = QFormLayout()
        _configure_form(fl)
        self.combo_sig = SearchableComboBox()
        fl.addRow("信号:", _fit_field(self.combo_sig, max_width=_LONG_FIELD_MAX_WIDTH))
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

        # 2026-06-13 split: lower full-width tinted panel hosts 时频参数 +
        # 幅值 + 坐标轴设置 + 预设 + 计算时频图（色图固定 turbo，无色标控件）.
        params_card, params_lay = _make_params_card(self, "fftTimeParamsCard")

        # ---- 时频参数 ----
        # 2026-04-26 R3 紧凑化 fix-3: cap each short field.
        g = QGroupBox("时频参数")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems([
            self._AUTO_NFFT_LABEL, '512', '1024', '2048', '4096', '8192',
        ])
        self.combo_nfft.setCurrentText(self._AUTO_NFFT_LABEL)
        self.combo_nfft.setToolTip('越大频率越细、计算量越高；\n「自动」＝按窗长取 2 的幂。')
        fl.addRow("FFT 点数:", _fit_field(self.combo_nfft, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.combo_win = QComboBox()
        self.combo_win.addItems(
            ['hanning', 'flattop', 'hamming', 'blackman', 'kaiser', 'bartlett']
        )
        self.combo_win.setToolTip('抑制频谱泄漏：flattop 幅值最准、\nhanning 最均衡、blackman 旁瓣最低。')
        fl.addRow("窗函数:", _fit_field(self.combo_win, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.spin_overlap = _no_buttons(QSpinBox())
        # Requested first-open default: 80% overlap. Keep the 95% ceiling so
        # existing high-overlap presets and user-tuned values remain valid.
        self.spin_overlap.setRange(0, 95)
        self.spin_overlap.setValue(80)
        self.spin_overlap.setSuffix(" %")
        self.spin_overlap.setToolTip('相邻时间帧的重叠：越高时频图越平滑、\n计算量越大。')
        fl.addRow("重叠:", _fit_field(self.spin_overlap, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.chk_remove_mean = QCheckBox("去均值")
        self.chk_remove_mean.setChecked(True)
        self.chk_remove_mean.setToolTip('减去直流，避免 0 Hz 大值压低低频成分。')
        fl.addRow(self.chk_remove_mean)
        g.setTitle("")
        # The section header already shows the title; drop the title band and
        # let the body carry a hairline top divider (see style.qss
        # #paramsSectionBody) so the expanded detail matches the mockup.
        g.setObjectName("paramsSectionBody")
        self._tf_section = _CollapsibleParamSection(
            "时频参数",
            "inspector/fft_time/params_expanded",
            parent=self,
        )
        self._tf_section.set_body(g)
        params_lay.addWidget(self._tf_section)

        # ---- 幅值 (Wave 4: combo_amp_mode dropped — amplitude unit now
        # lives on the Z row of 坐标轴设置 as combo_amp_unit. spin_db_ref
        # stays because main_window's SpectrogramParams still consumes
        # ``db_reference``). ----
        g = QGroupBox("幅值")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.spin_db_ref = _no_buttons(CompactDoubleSpinBox())
        self.spin_db_ref.setRange(1e-9, 1e9)
        self.spin_db_ref.setDecimals(6)
        self.spin_db_ref.setValue(1.0)
        self.spin_db_ref.setToolTip('0 dB 对应的线性幅值，仅平移 dB 刻度、不改波形。')
        fl.addRow("dB 参考:", _fit_field(self.spin_db_ref, max_width=_SHORT_FIELD_MAX_WIDTH))
        params_lay.addWidget(g)

        # ---- 坐标轴设置 (2026-04-29 B polish) ----
        # The rendered FFT-vs-Time spectrogram is X = time, Y = frequency,
        # Z/color = amplitude. The old Wave 4 labels had X=freq/Y=amp,
        # which did not match the actual plot and is the user-reported bug.
        # Default y_max=0.0 means "use Nyquist" — main_window's existing
        # spin_freq_max==0.0 sentinel survives unchanged via Y aliases.
        # Default z range is -70..-20 dB per the requested first-open UI state.
        axis_g = _make_axis_settings_group(
            self,
            x_label="时间 (X):", x_unit='s',
            x_default_min=0.0, x_default_max=0.0,
            y_label="频率 (Y):", y_unit='Hz',
            y_default_min=0.0, y_default_max=0.0,
            z_default_floor=-70.0, z_default_ceiling=-20.0,
            z_default_auto=False,
            x_default_auto=True,
            y_default_auto=True,
            x_auto_summary="全时段",
            y_auto_summary="0 → Nyquist",
            z_auto_summary="自动色阶",
        )
        params_lay.addWidget(axis_g)
        # Tooltips for widgets created inside _make_axis_settings_group.
        self.combo_amp_unit.setToolTip('dB 看宽动态，Linear 看绝对幅值。')
        self.spin_z_floor.setToolTip('颜色映射区间(dB)：缩小区间增强弱信号对比。')
        self.spin_z_ceiling.setToolTip('颜色映射区间(dB)：缩小区间增强弱信号对比。')
        # Backward-compat aliases (per plan): downstream main_window callers
        # still read chk_freq_auto / spin_freq_min / spin_freq_max.
        # MUST be set inside __init__ so test_fft_time_contextual_has_axis_
        # settings_group sees them at construction time.
        self.chk_freq_auto = self.chk_y_auto
        self.spin_freq_min = self.spin_y_min
        self.spin_freq_max = self.spin_y_max
        # Tighten the freq spin caps so the unit-suffixed Hz column matches
        # the legacy A1 cap (the helper uses 72px which is plenty for 5
        # digits + Hz suffix; no change needed here).

        # ---- 色标 ----
        # 2026-06-19：用户要求移除可切换的色图控件，时频图色图固定为 turbo。
        # 原 combo_cmap + 「色标」分组已删除；色图由 _FIXED_CMAP 常量经
        # get_params()/_collect_preset() 下发，main_window._render_fft_time
        # 与预设保存的字段契约保持不变。

        # ---- 预设 (R3 C: builtin-aware PresetBar) ----
        # The preset_bar is single-row, builtin-aware: each slot starts with
        # its signal-type display name (频率优先 / 均衡 / 时间优先), left-click
        # loads (override-or-builtin), right-click menu integrates 保存当前 /
        # 重命名 / 重置为默认. Slot order is the shared BUILTIN_PRESET_KEYS
        # contract so unit-推荐 highlighting lines up across all three views.
        builtin_defaults = {
            _PRESET_KEY_TO_SLOT[key]: {
                'display_name': self._BUILTIN_PRESET_DISPLAY[key],
                'params': self._builtin_preset_full_params(key),
            }
            for key in BUILTIN_PRESET_KEYS
        }
        self.preset_bar = PresetBar(
            'fft_time',
            self._collect_preset,
            self._apply_preset,
            parent=self,
            builtin_defaults=builtin_defaults,
            default_params=self._collect_preset(),
        )
        self._tf_section.add_persistent(self.preset_bar)

        # ---- 操作 ----
        self.btn_compute = QPushButton("计算时频图")
        self.btn_compute.setProperty("role", "primary")
        # Disabled until a signal candidate is provided. The
        # ``set_signal_candidates`` hook keeps this in sync with the
        # candidate list.
        self.btn_compute.setEnabled(False)
        params_lay.addWidget(self.btn_compute)

        root.addWidget(params_card)
        root.addStretch()

        # 2026-04-27 fix-4: unify label-column width across the sig_card
        # form and every QGroupBox form so all field columns share the
        # same width and right edge (see FFTContextual for rationale).
        _enforce_label_widths(self, unify_columns=True)

        # ---- wiring ----
        self.btn_compute.clicked.connect(self.fft_time_requested)
        # Wave 4/B polish: chk_freq_auto / spin_freq_min/max alias the
        # Y-frequency row of the 坐标轴设置 group; their enabled state is
        # driven by _sync_axis_enabled, which the helper wired to
        # chk_y_auto.toggled.
        # Seed the initial enabled state once at __init__ end (per the
        # 2026-04-26 init-sync lesson).
        self._connect_preset_param_signals()
        self._refresh_tf_summary()
        self._sync_axis_enabled()

    # ---- helpers ----
    def time_range_layout(self):
        return self._time_range_slot

    def is_tf_expanded(self):
        return self._tf_section.is_expanded()

    def _tf_summary_text(self):
        nfft_text = self.combo_nfft.currentText()
        if nfft_text == self._AUTO_NFFT_LABEL:
            nfft_text = f"{self._AUTO_NFFT_LABEL}({self._nfft_preview()})"
        return (
            f"{nfft_text} · "
            f"{self.combo_win.currentText()} · "
            f"{self.spin_overlap.value()}%"
        )

    def _refresh_tf_summary(self):
        self._tf_section.set_summary(self._tf_summary_text())

    def _on_preset_param_changed(self, *_):
        if not self._applying_preset:
            self.preset_bar.set_recommended(None)
        self._refresh_tf_summary()

    def _connect_preset_param_signals(self):
        self.combo_nfft.currentTextChanged.connect(self._on_preset_param_changed)
        self.combo_win.currentTextChanged.connect(self._on_preset_param_changed)
        self.spin_overlap.valueChanged.connect(self._on_preset_param_changed)
        self.chk_remove_mean.toggled.connect(self._on_preset_param_changed)

    def _sync_axis_enabled(self):
        """Toggle each axis row between auto summary and manual bounds.

        Identical body to OrderContextual._sync_axis_enabled — kept as an
        instance method per the Wave 4 plan note (helper wires the signal
        but each class owns the slot so the implementation stays
        overrideable / inspectable).
        """
        for key in ('x', 'y', 'z'):
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

    def _on_amp_unit_changed(self, text):
        """Switching dB↔Linear forces z_auto on AND resets z_floor/z_ceiling
        to the new unit's defaults so the previous unit's numeric range
        cannot bleed into the new unit. Per the
        2026-05-01-codex-review-fixes-design.md spec §1.4 contract.

        Order matters: chk_z_auto must be set to True FIRST so that
        ``_sync_axis_enabled`` (called at the end) sees the auto-on state
        and disables both spinboxes.
        """
        floor, ceiling = z_range_for(text)
        self.chk_z_auto.setChecked(True)
        self.spin_z_floor.setValue(floor)
        self.spin_z_ceiling.setValue(ceiling)
        self._sync_axis_enabled()

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    # ---- public API consumed by MainWindow / tests ----
    def set_signal_candidates(self, candidates):
        """Repopulate the signal combo, preserving an existing selection
        (matched by userData) when it remains in the new candidate list.

        The compute button is enabled iff the combo ends with at least one
        item — this hook is part of the contract verified by
        ``test_fft_time_compute_button_tracks_signal_candidates``.
        """
        prev = self.combo_sig.currentData()
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        keep_idx = -1
        for i, (text, data) in enumerate(candidates):
            self.combo_sig.addItem(text, data)
            if prev is not None and data == prev:
                keep_idx = i
        # No prior selection to preserve -> leave unselected (-1) instead of
        # sitting on the first signal; see FFTContextual.set_signal_candidates
        # for the phantom-default rationale.
        self.combo_sig.setCurrentIndex(keep_idx)
        self.combo_sig.blockSignals(False)
        # Re-attach signal_changed listener exactly once.
        try:
            self.combo_sig.currentIndexChanged.disconnect(
                self._on_sig_index_changed
            )
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)
        # Compute is enabled iff there is a valid candidate. This is the
        # T2 hook the mode-plumbing tests rely on — keep it as the LAST
        # statement so it always reflects the final combo state.
        self.btn_compute.setEnabled(self.combo_sig.count() > 0)

    def current_signal(self):
        return self.combo_sig.currentData()

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(float(fs))
        self.spin_fs.blockSignals(False)
        self._refresh_tf_summary()

    def _nfft_preview(self):
        from ...signal import ceil_pow2

        nfft = ceil_pow2(float(self.spin_fs.value()) * float(self._t_win_s))
        return int(min(max(nfft, 64), 8192))

    def get_params(self):
        # Wave 4: amplitude_mode now derives from combo_amp_unit (the dB↔
        # Linear dropdown on the Z axis row). Stays lowercase
        # ('amplitude_db' / 'amplitude') so main_window._render_fft_time →
        # SpectrogramCanvas.plot_result keeps round-tripping unchanged
        # (Wave 5 will retire the key entirely).
        unit = self.combo_amp_unit.currentText()
        amp_mode = 'amplitude_db' if unit == 'dB' else 'amplitude'
        # Wave 4: combo_dynamic dropped; legacy ``dynamic`` string is
        # synthesised from the explicit Z-row floor (the spectrogram canvas
        # consumes this until Wave 5 wires it to z_floor / z_ceiling).
        # When z_auto is on the canvas chooses its own range, hence 'Auto'.
        if self.chk_z_auto.isChecked():
            dynamic_legacy = 'Auto'
        else:
            span = abs(float(self.spin_z_floor.value()))
            dynamic_legacy = f"{int(round(span))} dB"
        nfft_text = self.combo_nfft.currentText()
        if nfft_text == self._AUTO_NFFT_LABEL:
            nfft = None
            nfft_mode = 'auto'
            nfft_effective = None
            nfft_preview = self._nfft_preview()
        else:
            nfft = int(nfft_text)
            nfft_mode = 'fixed'
            nfft_effective = nfft
            nfft_preview = nfft
        params = dict(
            signal=self.combo_sig.currentData(),
            fs=self.spin_fs.value(),
            nfft=nfft,
            nfft_mode=nfft_mode,
            t_win_s=float(self._t_win_s),
            nfft_preview=nfft_preview,
            nfft_effective=nfft_effective,
            window=self.combo_win.currentText(),
            overlap=self.spin_overlap.value() / 100.0,
            remove_mean=self.chk_remove_mean.isChecked(),
            amplitude_mode=amp_mode,
            db_reference=self.spin_db_ref.value(),
            # Legacy freq_* keys are aliases of the Y-frequency axis.
            freq_auto=bool(self.chk_y_auto.isChecked()),
            freq_min=float(self.spin_y_min.value()),
            freq_max=float(self.spin_y_max.value()),
            dynamic=dynamic_legacy,
            cmap=self._FIXED_CMAP,
        )
        # Wave 4 (2026-04-28 plan): explicit X/Y/Z range + auto flags for
        # the new 坐标轴设置 group. These coexist with the legacy keys
        # above; Wave 5 will trim the duplicates once the canvas reads the
        # explicit z_floor/ceiling directly.
        params['x_auto'] = bool(self.chk_x_auto.isChecked())
        params['x_min'] = float(self.spin_x_min.value())
        params['x_max'] = float(self.spin_x_max.value())
        params['y_auto'] = bool(self.chk_y_auto.isChecked())
        params['y_min'] = float(self.spin_y_min.value())
        params['y_max'] = float(self.spin_y_max.value())
        params['z_auto'] = bool(self.chk_z_auto.isChecked())
        params['z_floor'] = float(self.spin_z_floor.value())
        params['z_ceiling'] = float(self.spin_z_ceiling.value())
        return params

    # Wave 4 alias (mirrors OrderContextual.current_params) so the test
    # `test_fft_time_contextual_current_params_emits_axis_keys` finds
    # current_params; runtime callers continue to use get_params.
    def current_params(self):
        return self.get_params()

    def apply_params(self, d):
        """Round-trip every key get_params emits back onto its control.

        V5b: the per-section multiview bridge calls apply_params_from_state →
        ctx.apply_params(...). Mirrors FFTContextual/OrderContextual.apply_params:
        each key is fault-tolerant (`if 'k' in d:` so partial dicts are fine)
        and `apply_params(get_params())` is idempotent.

        Three get_params shapes need reverse mapping, not a naive setter:
        - ``overlap`` is a FRACTION (0.75); spin_overlap holds the percent (75).
        - ``amplitude_mode`` is the lowercase token 'amplitude_db' / 'amplitude';
          combo_amp_unit shows 'dB' / 'Linear'. We match on ``'db' in lower``
          (the legacy '_apply_preset' `'dB' in val` form would mis-read the
          lowercase token). blockSignals so _on_amp_unit_changed does not force
          z_auto on and stomp the explicit z_floor/z_ceiling arriving alongside.
        - ``dynamic`` / ``freq_*`` are derived aliases of z_floor / the Y row;
          they are skipped whenever the authoritative explicit key is present
          (always true for get_params output) so they cannot break idempotency.
        """
        if 'signal' in d and d['signal'] is not None:
            i = self.combo_sig.findData(d['signal'])
            if i >= 0:
                self.combo_sig.setCurrentIndex(i)
        if 'fs' in d:
            try:
                self.spin_fs.setValue(float(d['fs']))
            except (TypeError, ValueError):
                pass
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
            if d.get('nfft_mode') == 'auto' or d['nfft'] is None:
                i = self.combo_nfft.findText(self._AUTO_NFFT_LABEL)
            else:
                i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'overlap' in d:
            try:
                # get_params stores overlap as a fraction; the spin is percent.
                self.spin_overlap.setValue(int(round(float(d['overlap']) * 100)))
            except (TypeError, ValueError):
                pass
        if 'remove_mean' in d:
            self.chk_remove_mean.setChecked(bool(d['remove_mean']))
        if 'db_reference' in d:
            try:
                self.spin_db_ref.setValue(float(d['db_reference']))
            except (TypeError, ValueError):
                pass
        # cmap 固定 turbo：无控件可应用，预设/视图状态里的 cmap 键被忽略。

        # amplitude_mode token → combo_amp_unit. Reverse-map on a
        # case-insensitive 'db' substring so the lowercase 'amplitude_db'
        # token from get_params lands on 'dB' (and the legacy 'Amplitude dB'
        # preset string keeps working). blockSignals so _on_amp_unit_changed
        # does not flip z_auto on and clobber the explicit z range below.
        if 'amplitude_mode' in d:
            val = str(d['amplitude_mode'])
            target = 'dB' if 'db' in val.lower() else 'Linear'
            i = self.combo_amp_unit.findText(target)
            if i >= 0:
                self.combo_amp_unit.blockSignals(True)
                self.combo_amp_unit.setCurrentIndex(i)
                self.combo_amp_unit.blockSignals(False)

        # Legacy ``dynamic`` only fires when no explicit z_floor accompanies
        # it (get_params always emits z_floor, so this is a partial-dict
        # safety net, never reached on a full round-trip).
        if 'dynamic' in d and 'z_floor' not in d:
            raw = str(d['dynamic'])
            if raw == 'Auto':
                self.chk_z_auto.setChecked(True)
            else:
                try:
                    n = float(raw.replace('dB', '').strip())
                    self.chk_z_auto.setChecked(False)
                    self.spin_z_floor.setValue(-abs(n))
                    self.spin_z_ceiling.setValue(0.0)
                except ValueError:
                    pass

        # Legacy ``freq_*`` alias the Y-frequency row; only applied when the
        # explicit ``y_*`` key is absent so they cannot fight the round-trip.
        if 'freq_auto' in d and 'y_auto' not in d:
            self.chk_y_auto.setChecked(bool(d['freq_auto']))
        if 'freq_min' in d and 'y_min' not in d:
            try:
                self.spin_y_min.setValue(float(d['freq_min']))
            except (TypeError, ValueError):
                pass
        if 'freq_max' in d and 'y_max' not in d:
            try:
                self.spin_y_max.setValue(float(d['freq_max']))
            except (TypeError, ValueError):
                pass

        # Explicit axis keys (preferred path, authoritative).
        for key, attr in (
            ('x_auto', 'chk_x_auto'),
            ('y_auto', 'chk_y_auto'),
            ('z_auto', 'chk_z_auto'),
        ):
            if key in d:
                getattr(self, attr).setChecked(bool(d[key]))
        for key, attr in (
            ('x_min', 'spin_x_min'), ('x_max', 'spin_x_max'),
            ('y_min', 'spin_y_min'), ('y_max', 'spin_y_max'),
            ('z_floor', 'spin_z_floor'), ('z_ceiling', 'spin_z_ceiling'),
        ):
            if key in d:
                try:
                    getattr(self, attr).setValue(float(d[key]))
                except (TypeError, ValueError):
                    pass

        self._sync_axis_enabled()

    # ---- built-in presets (design §7) ----
    #
    # NEW-1 (Wave 4 audit): the 'amplitude_mode' / 'dynamic' /
    # 'freq_auto/min/max' keys below are the LEGACY shape. After Wave 4
    # the underlying widgets (combo_amp_mode + combo_dynamic + the freq
    # QFormLayout block) are gone, so these dicts can no longer be applied
    # naively. _apply_preset performs read-side migration (legacy keys are
    # translated to the new chk_z_auto / spin_z_floor / spin_z_ceiling /
    # combo_amp_unit + chk_y_auto / spin_y_min/max), so the literals here
    # survive untouched. Wave 5 / 6 will rewrite them in the new shape.
    # DEPRECATED key form; survives via _apply_preset legacy migration on load.
    #
    # Signal-type built-in presets (信号专家 校核定稿 — do NOT alter the numeric
    # values). The compact shape (window/nfft/overlap/amplitude_mode/freq_auto/
    # dynamic/cmap) is preserved; _builtin_preset_full_params spreads it to the
    # full collect-preset shape and parses ``dynamic`` ('Auto' / 'NN dB') into
    # z_auto / z_floor.
    _BUILTIN_PRESETS = {
        'torque': dict(
            window='flattop',
            t_win_s=2.5,
            overlap=75,
            amplitude_mode='Amplitude dB',
            freq_auto=True,
            dynamic='Auto',
            cmap='viridis',
        ),
        'vibration': dict(
            window='hanning',
            t_win_s=1.5,
            overlap=50,
            amplitude_mode='Amplitude dB',
            freq_auto=True,
            dynamic='80 dB',
            cmap='turbo',
        ),
        'transient': dict(
            window='hanning',
            t_win_s=0.6,
            overlap=75,
            amplitude_mode='Amplitude dB',
            freq_auto=True,
            dynamic='60 dB',
            cmap='turbo',
        ),
    }
    _LEGACY_BUILTIN_PRESET_ALIASES = {
        'diagnostic': 'vibration',
        'amplitude_accuracy': 'torque',
        'high_frequency': 'transient',
    }

    # User-facing display names for the three builtin slots — shared signal-type
    # labels (频率优先 / 均衡 / 时间优先).
    _BUILTIN_PRESET_DISPLAY = dict(BUILTIN_PRESET_DISPLAY)

    def _resolve_builtin_preset_key(self, name):
        return self._LEGACY_BUILTIN_PRESET_ALIASES.get(name, name)

    def _builtin_preset_full_params(self, name):
        """Return a JSON-serializable param dict for a builtin preset.

        Mirrors the keys we collect in ``_collect_preset`` so the
        builtin-aware PresetBar can save / reset / load the same shape
        round-trip.
        """
        cfg = self._BUILTIN_PRESETS.get(self._resolve_builtin_preset_key(name), {})
        # Spread the legacy compact dict to the full collect_preset shape
        # — fields we don't override default to "the same value the
        # widget has at construction time" so an unspecified field doesn't
        # silently mutate.
        return {
            'window': cfg.get('window', 'hanning'),
            'nfft': self._AUTO_NFFT_LABEL,
            'nfft_mode': 'auto',
            't_win_s': cfg.get('t_win_s', 1.5),
            'overlap': cfg.get('overlap', 75),
            'amplitude_mode': cfg.get('amplitude_mode', 'Amplitude dB'),
            'remove_mean': True,
            'db_reference': 1.0,
            'freq_auto': cfg.get('freq_auto', True),
            'freq_min': 0.0,
            'freq_max': 0.0,
            'dynamic': cfg.get('dynamic', '80 dB'),
            'cmap': cfg.get('cmap', 'turbo'),
            'x_auto': True,
            'x_min': 0.0,
            'x_max': 0.0,
            'y_auto': cfg.get('freq_auto', True),
            'y_min': 0.0,
            'y_max': 0.0,
            'z_auto': cfg.get('dynamic') == 'Auto',
            'z_floor': _dynamic_to_floor(cfg.get('dynamic', '80 dB')),
            'z_ceiling': 0.0,
        }

    def _collect_preset(self):
        """Snapshot the current time-frequency params for PresetBar save.

        Wave 4: combo_amp_mode + combo_dynamic dropped. ``amplitude_mode``
        is now derived from ``combo_amp_unit`` (mirroring step 3.4 for
        OrderContextual); ``dynamic`` is synthesised from
        ``spin_z_floor`` so the persisted preset shape stays
        backward-compatible with main_window's _render_fft_time consumer
        (Wave 5 will retire both legacy keys).
        """
        unit = self.combo_amp_unit.currentText()
        amp_mode = 'Amplitude dB' if unit == 'dB' else 'Amplitude'
        if self.chk_z_auto.isChecked():
            dynamic_legacy = 'Auto'
        else:
            span = abs(float(self.spin_z_floor.value()))
            dynamic_legacy = f"{int(round(span))} dB"
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
            amplitude_mode=amp_mode,
            remove_mean=self.chk_remove_mean.isChecked(),
            db_reference=self.spin_db_ref.value(),
            freq_auto=bool(self.chk_y_auto.isChecked()),
            freq_min=float(self.spin_y_min.value()),
            freq_max=float(self.spin_y_max.value()),
            dynamic=dynamic_legacy,
            cmap=self._FIXED_CMAP,
            x_auto=bool(self.chk_x_auto.isChecked()),
            x_min=float(self.spin_x_min.value()),
            x_max=float(self.spin_x_max.value()),
            y_auto=bool(self.chk_y_auto.isChecked()),
            y_min=float(self.spin_y_min.value()),
            y_max=float(self.spin_y_max.value()),
            z_auto=bool(self.chk_z_auto.isChecked()),
            z_floor=float(self.spin_z_floor.value()),
            z_ceiling=float(self.spin_z_ceiling.value()),
        )

    def _apply_preset(self, d):
        self._applying_preset = True
        try:
            self._apply_preset_values(d)
        finally:
            self._applying_preset = False
            self._refresh_tf_summary()

    def _apply_preset_values(self, d):
        """Restore previously-saved params from PresetBar load (R3 C).

        Wave 4: legacy ``amplitude_mode`` / ``dynamic`` / ``freq_*`` keys
        are migrated to the new chk_z_auto / spin_z_floor / spin_z_ceiling
        / combo_amp_unit / chk_y_auto / spin_y_min/max widgets. New keys
        (z_auto, z_floor, z_ceiling, x_auto, x_min, x_max, y_*) are
        applied directly when present and override the legacy translation.
        """
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
            if d.get('nfft_mode') == 'auto' or d['nfft'] is None:
                i = self.combo_nfft.findText(self._AUTO_NFFT_LABEL)
            else:
                i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'overlap' in d:
            try:
                self.spin_overlap.setValue(int(d['overlap']))
            except (TypeError, ValueError):
                pass
        if 'remove_mean' in d:
            self.chk_remove_mean.setChecked(bool(d['remove_mean']))
        if 'db_reference' in d:
            try:
                self.spin_db_ref.setValue(float(d['db_reference']))
            except (TypeError, ValueError):
                pass
        # cmap 固定 turbo：无控件可应用，预设/视图状态里的 cmap 键被忽略。

        # ---- Wave 4 axis-key migration (legacy + new) ----
        # Legacy ``dynamic`` translates to z_floor / z_ceiling / z_auto.
        # The explicit z_floor key (applied below) takes precedence when
        # both are present in the same dict.
        if 'dynamic' in d and 'z_floor' not in d:
            raw = str(d['dynamic'])
            if raw == 'Auto':
                self.chk_z_auto.setChecked(True)
            else:
                try:
                    n = float(raw.replace('dB', '').strip())
                    self.chk_z_auto.setChecked(False)
                    self.spin_z_floor.setValue(-abs(n))
                    self.spin_z_ceiling.setValue(0.0)
                except ValueError:
                    pass
        # Legacy 'amplitude_mode' → combo_amp_unit. blockSignals so
        # _on_amp_unit_changed does not flip z_auto on and clobber the
        # dynamic-derived floor/ceiling we just set (mirroring Wave 3
        # OrderContextual step 3.4).
        if 'amplitude_mode' in d:
            val = str(d['amplitude_mode'])
            target = 'dB' if 'dB' in val else 'Linear'
            i = self.combo_amp_unit.findText(target)
            if i >= 0:
                self.combo_amp_unit.blockSignals(True)
                self.combo_amp_unit.setCurrentIndex(i)
                self.combo_amp_unit.blockSignals(False)
        # Legacy ``freq_auto/min/max`` map onto the Y-frequency row of the
        # axis group (chk_y_auto / spin_y_min/max via the alias attributes).
        if 'freq_auto' in d:
            self.chk_y_auto.setChecked(bool(d['freq_auto']))
        if 'freq_min' in d:
            try:
                self.spin_y_min.setValue(float(d['freq_min']))
            except (TypeError, ValueError):
                pass
        if 'freq_max' in d:
            try:
                self.spin_y_max.setValue(float(d['freq_max']))
            except (TypeError, ValueError):
                pass

        # New explicit axis keys (preferred path; override the legacy
        # translation when both are present).
        for key, attr in (
            ('x_auto', 'chk_x_auto'),
            ('y_auto', 'chk_y_auto'),
            ('z_auto', 'chk_z_auto'),
        ):
            if key in d:
                getattr(self, attr).setChecked(bool(d[key]))
        for key, attr in (
            ('x_min', 'spin_x_min'), ('x_max', 'spin_x_max'),
            ('y_min', 'spin_y_min'), ('y_max', 'spin_y_max'),
            ('z_floor', 'spin_z_floor'), ('z_ceiling', 'spin_z_ceiling'),
        ):
            if key in d:
                try:
                    getattr(self, attr).setValue(float(d[key]))
                except (TypeError, ValueError):
                    pass

        self._sync_axis_enabled()

    def apply_builtin_preset(self, name):
        """Apply one of the built-in presets by key (``'torque'`` /
        ``'vibration'`` / ``'transient'``).

        Legacy keys (``'diagnostic'``, ``'amplitude_accuracy'``,
        ``'high_frequency'``) are accepted as aliases for the closest new
        signal-type preset so old regression paths do not silently no-op.
        """
        key = self._resolve_builtin_preset_key(name)
        cfg = self._BUILTIN_PRESETS.get(key)
        if not cfg:
            return
        self._apply_preset(self._builtin_preset_full_params(key))

    def set_recommended_for_unit(self, unit):
        """Highlight the preset slot recommended for ``unit`` (or clear)."""
        if unit is None:
            self.preset_bar.set_recommended(None)
            return
        key = recommend_preset_for_unit(unit)
        self.preset_bar.set_recommended(_PRESET_KEY_TO_SLOT[key])
