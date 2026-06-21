"""OrderContextual widget."""
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
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
    _enforce_label_widths,
    _fit_field,
    _make_axis_settings_group,
    _make_group_header,
    _make_params_card,
    _no_buttons,
    make_db_reference_spinbox,
    recommend_preset_for_unit,
)
from .collapsible import _CollapsibleParamSection
from .presets import PresetBar


class OrderContextual(QWidget):
    """Order-analysis contextual: source/params/presets + compute action."""

    _AUTO_NFFT_LABEL = "自动"

    order_time_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)  # anchor widget
    signal_changed = pyqtSignal(object)  # (fid, ch) tuple or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("orderContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._applying_preset = False
        self._source_weighting_default = 'None'
        root = QVBoxLayout(self)
        # 2026-06-13 分析信号/谱参数 split: transparent host for two
        # full-width cards (sig_card + params_card); spacing is the gutter.
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # R3 #9: build btn_rebuild before the signal-source group so we
        # can dock it on the group's header row.
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

        # ---- 信号源 (custom header w/ rebuild button) ----
        # 2026-04-26 R3 紧凑化 fix-2: WA_StyledBackground intentionally OFF.
        sig_card = QFrame(self)
        sig_card.setObjectName("orderSignalCard")
        sig_lay = QVBoxLayout(sig_card)
        # 2026-06-13 split: sig_card carries its own 10px inner padding.
        sig_lay.setContentsMargins(10, 8, 10, 10)
        sig_lay.setSpacing(4)
        sig_lay.addWidget(_make_group_header("信号源 + 时间", self.btn_rebuild))
        fl = QFormLayout()
        _configure_form(fl)
        self.combo_sig = SearchableComboBox()
        fl.addRow("信号:", _fit_field(self.combo_sig, max_width=_LONG_FIELD_MAX_WIDTH))
        self.combo_rpm = SearchableComboBox()
        fl.addRow("转速:", _fit_field(self.combo_rpm, max_width=_LONG_FIELD_MAX_WIDTH))
        self.spin_fs = _no_buttons(CompactDoubleSpinBox())
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fl.addRow("Fs:", _fit_field(self.spin_fs, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.spin_rf = _no_buttons(CompactDoubleSpinBox())
        self.spin_rf.setRange(0.0001, 10000)
        self.spin_rf.setDecimals(4)
        self.spin_rf.setValue(1)
        fl.addRow("RPM系数:", _fit_field(self.spin_rf, max_width=_SHORT_FIELD_MAX_WIDTH))
        sig_lay.addLayout(fl)
        self._time_range_slot = QVBoxLayout()
        self._time_range_slot.setContentsMargins(0, 0, 0, 0)
        self._time_range_slot.setSpacing(0)
        sig_lay.addLayout(self._time_range_slot)
        root.addWidget(sig_card)

        # 2026-06-13 split: lower full-width tinted panel (谱参数 +
        # 坐标轴设置 + 预设配置 + 时间-阶次 action).
        params_card, params_lay = _make_params_card(self, "orderParamsCard")

        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.spin_mo = _no_buttons(QSpinBox())
        self.spin_mo.setRange(1, 100)
        self.spin_mo.setValue(20)
        self.spin_mo.setToolTip('分析的最高阶次；越大覆盖越宽、计算量越大。')
        fl.addRow("最大阶次:", _fit_field(self.spin_mo))
        self.spin_order_res = _no_buttons(CompactDoubleSpinBox())
        self.spin_order_res.setRange(0.01, 1.0)
        self.spin_order_res.setValue(0.1)
        self.spin_order_res.setSingleStep(0.05)
        self.spin_order_res.setToolTip('阶次轴细度：越小越细，\n但需更多转数 / 更长数据。')
        fl.addRow("阶次分辨率:", _fit_field(self.spin_order_res))
        self.spin_time_res = _no_buttons(CompactDoubleSpinBox())
        self.spin_time_res.setRange(0.01, 1.0)
        self.spin_time_res.setValue(0.05)
        self.spin_time_res.setSuffix(" s")
        self.spin_time_res.setToolTip('阶次谱图时间轴细度：\n越小时间越细、阶次相应变粗。')
        fl.addRow("时间分辨率:", _fit_field(self.spin_time_res))
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems([
            self._AUTO_NFFT_LABEL, '512', '1024', '2048', '4096', '8192', '16384'
        ])
        self.combo_nfft.setCurrentText(self._AUTO_NFFT_LABEL)
        self.combo_nfft.setToolTip('越大阶次越细、计算量越高；\n「自动」＝按需取 2 的幂。')
        fl.addRow("FFT点数:", _fit_field(self.combo_nfft))
        self.combo_weighting = QComboBox()
        self.combo_weighting.addItems(['None', 'A'])
        self.combo_weighting.setCurrentText('None')
        self.combo_weighting.setToolTip(
            'A 计权（IEC 61672）：相对加权频谱，非绝对 dB SPL'
        )
        fl.addRow(
            "频率加权:",
            _fit_field(self.combo_weighting, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        self.spin_db_ref = make_db_reference_spinbox()
        fl.addRow(
            "dB 参考:",
            _fit_field(self.spin_db_ref, max_width=_SHORT_FIELD_MAX_WIDTH),
        )

        # COT is now the only tracking algorithm (Wave 2 of the
        # 2026-04-28 axis-settings + COT migration plan removed the
        # frequency-domain branch). spin_samples_per_rev is therefore
        # always enabled — no companion algorithm picker gates it.
        self.spin_samples_per_rev = _no_buttons(QSpinBox())
        self.spin_samples_per_rev.setRange(64, 2048)
        self.spin_samples_per_rev.setValue(256)
        self.spin_samples_per_rev.setToolTip("COT 每转角度采样数")
        fl.addRow(
            "每转样本数:",
            _fit_field(self.spin_samples_per_rev, max_width=_SHORT_FIELD_MAX_WIDTH),
        )

        # R3 B: pin label widths and cap field widths so long Chinese
        # labels (e.g. "阶次分辨率:") never wrap or get elided when the
        # Inspector pane is narrow. _enforce_label_widths walks every form
        # in this widget after construction.
        g.setTitle("")
        # The section header already shows the title; drop the title band and
        # let the body carry a hairline top divider (see style.qss
        # #paramsSectionBody) so the expanded detail matches the mockup.
        g.setObjectName("paramsSectionBody")
        self._order_section = _CollapsibleParamSection(
            "谱参数",
            "inspector/order/params_expanded",
            parent=self,
        )
        self._order_section.set_body(g)
        params_lay.addWidget(self._order_section)

        # ---- 坐标轴设置 (Wave 3 of the 2026-04-28 plan; refactored to
        # use the module-level _make_axis_settings_group helper in Wave 4
        # so FFTTimeContextual can reuse the same group construction). ----
        # Replaces the old combo_amp_mode + combo_dynamic combos. The Z
        # row carries the dB ↔ Linear unit dropdown; floor/ceiling spins
        # express the dB color range explicitly. Defaults match the requested
        # first-open UI state (z_auto off, floor=-50, ceiling=-10).
        axis_g = _make_axis_settings_group(
            self,
            x_label="时间 (X):", x_unit='s',
            x_default_min=0.0, x_default_max=0.0,
            y_label="阶次 (Y):", y_unit='',
            y_default_min=0.0, y_default_max=float(self.spin_mo.value()),
            z_default_floor=-50.0, z_default_ceiling=-10.0,
            z_default_auto=False,
            x_default_auto=True,
            y_default_auto=True,
            x_auto_summary="全时段",
            y_auto_summary="0 → 最大阶次",
            z_auto_summary="自动色阶",
        )
        # Order-specific clamp: spin_y_max upper bound tracks spin_mo. The
        # helper uses a generic 1e9 ceiling; tighten it here so the user
        # cannot pick a display range exceeding the max calc order.
        self.spin_y_max.setRange(0.0, float(self.spin_mo.value()))
        params_lay.addWidget(axis_g)

        # ---- order-specific wiring (helper already wired chk_*_auto and
        # combo_amp_unit) ----
        self.spin_mo.valueChanged.connect(self._on_max_order_changed)
        # Seed initial enabled state (per the 2026-04-26 init-sync lesson:
        # signal-only wiring leaves the spinbox enabled flags in their
        # constructor default until the user actually toggles a checkbox).
        self._sync_axis_enabled()

        # Signal-type built-in presets (频率优先 / 均衡 / 时间优先).
        self.preset_bar = PresetBar(
            'order', self._collect_preset, self._apply_preset, parent=self,
            builtin_defaults=self._builtin_preset_defaults(),
            default_params=self._collect_preset(),
        )
        self._order_section.add_persistent(self.preset_bar)

        self.btn_ot = QPushButton("计算阶次图")
        self.btn_ot.setProperty("role", "primary")
        self.btn_ot.setMinimumHeight(32)
        params_lay.addWidget(self.btn_ot)

        self.lbl_progress = QLabel("")
        params_lay.addWidget(self.lbl_progress)

        root.addWidget(params_card)
        root.addStretch()

        self.btn_ot.clicked.connect(self.order_time_requested)
        self._connect_preset_param_signals()
        self._refresh_order_summary()

        # R3 B + 2026-04-26 紧凑化 fix-3: pin labels & cap fields so
        # 阶次分辨率 / 时间分辨率 / RPM分辨率 never wrap when the Inspector
        # pane is narrow, AND short numeric spinners no longer balloon when
        # the splitter widens. _SHORT_FIELD_MAX_WIDTH is enough for a 6-digit
        # spinner with the suffix, and frees space for the long Chinese
        # label column. The signal-source combos in the sig_card retain
        # their _LONG_FIELD_MAX_WIDTH cap (set explicitly above) — the cap
        # below applies only to the spec-param form.
        _enforce_label_widths(
            self,
            max_field_width=_SHORT_FIELD_MAX_WIDTH,
            unify_columns=True,
        )

    def time_range_layout(self):
        return self._time_range_slot

    def is_order_params_expanded(self):
        return self._order_section.is_expanded()

    def _order_summary_text(self):
        nfft_text = self.combo_nfft.currentText()
        if nfft_text == self._AUTO_NFFT_LABEL:
            nfft_text = f"{self._AUTO_NFFT_LABEL}({self._order_nfft_preview()})"
        return (
            f"≤{self.spin_mo.value()}阶 · "
            f"{self.spin_order_res.value():g} · "
            f"{nfft_text}"
        )

    def _refresh_order_summary(self):
        self._order_section.set_summary(self._order_summary_text())

    def _on_preset_param_changed(self, *_):
        if not self._applying_preset:
            self.preset_bar.set_recommended(None)
        self._refresh_order_summary()

    def _connect_preset_param_signals(self):
        for spin in (
            self.spin_mo,
            self.spin_order_res,
            self.spin_time_res,
            self.spin_samples_per_rev,
        ):
            spin.valueChanged.connect(self._on_preset_param_changed)
        self.combo_nfft.currentTextChanged.connect(self._on_preset_param_changed)
        self.combo_weighting.currentTextChanged.connect(self._on_preset_param_changed)

    def _apply_weighting_value(self, value):
        target = 'A' if str(value).upper() == 'A' else 'None'
        i = self.combo_weighting.findText(target)
        if i >= 0:
            self.combo_weighting.setCurrentIndex(i)

    def _sync_source_weighting_defaults(self):
        target = self._source_weighting_default
        bar = getattr(self, 'preset_bar', None)
        builtins = getattr(bar, '_builtins', None)
        if isinstance(builtins, dict):
            for entry in builtins.values():
                if isinstance(entry, dict) and isinstance(entry.get('params'), dict):
                    entry['params']['weighting'] = target
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

    # ---- 2026-04-28: axis settings group helpers (Wave 3 introduced; row-
    # builder lifted to module level in Wave 4 — see _make_axis_settings_group).
    def _sync_axis_enabled(self):
        """Toggle each axis row between auto summary and manual bounds."""
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

    def _on_max_order_changed(self, val):
        """Clamp spin_y_max upper bound to <= spin_mo (max calc order)."""
        self.spin_y_max.setMaximum(float(val))
        if self.spin_y_max.value() > float(val):
            self.spin_y_max.setValue(float(val))

    def _order_nfft_preview(self):
        from ...signal import ceil_pow2

        target = (
            float(self.spin_samples_per_rev.value())
            / float(self.spin_order_res.value())
        )
        nfft = ceil_pow2(target)
        return int(min(max(nfft, 256), 16384))

    # Signal-type built-in preset params (信号专家 校核定稿 — do NOT alter the
    # numeric values). Order presets carry NO window field (COT internally
    # fixes the window); amplitude axis is the legacy ``amplitude_mode`` token
    # ('Amplitude' / 'Amplitude dB') reverse-mapped onto combo_amp_unit.
    _SIGNAL_BUILTIN_PRESETS = {
        'torque': dict(
            max_order=20, order_res=0.05, time_res=0.10, nfft=_AUTO_NFFT_LABEL,
            samples_per_rev=256, amplitude_mode='Amplitude dB',
        ),
        'vibration': dict(
            max_order=50, order_res=0.10, time_res=0.05, nfft=_AUTO_NFFT_LABEL,
            samples_per_rev=512, amplitude_mode='Amplitude dB',
        ),
        'transient': dict(
            max_order=30, order_res=0.25, time_res=0.02, nfft=_AUTO_NFFT_LABEL,
            samples_per_rev=256, amplitude_mode='Amplitude dB',
        ),
    }

    def _builtin_preset_defaults(self):
        return {
            _PRESET_KEY_TO_SLOT[key]: {
                'display_name': BUILTIN_PRESET_DISPLAY[key],
                'params': dict(self._SIGNAL_BUILTIN_PRESETS[key]),
            }
            for key in BUILTIN_PRESET_KEYS
        }

    def set_recommended_for_unit(self, unit):
        """Highlight the preset slot recommended for ``unit`` (or clear)."""
        if unit is None:
            self.preset_bar.set_recommended(None)
            return
        key = recommend_preset_for_unit(unit)
        self.preset_bar.set_recommended(_PRESET_KEY_TO_SLOT[key])

    def _collect_preset(self):
        return dict(
            rpm_factor=self.spin_rf.value(),
            max_order=self.spin_mo.value(),
            order_res=self.spin_order_res.value(),
            time_res=self.spin_time_res.value(),
            nfft=self.combo_nfft.currentText(),
            nfft_mode=(
                'auto'
                if self.combo_nfft.currentText() == self._AUTO_NFFT_LABEL
                else 'fixed'
            ),
            amplitude_mode=(
                'Amplitude dB' if self.combo_amp_unit.currentText() == 'dB'
                else 'Amplitude'
            ),
            weighting=self.combo_weighting.currentText(),
            db_reference=self.spin_db_ref.value(),
            samples_per_rev=int(self.spin_samples_per_rev.value()),
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
            self._refresh_order_summary()

    def _apply_preset_values(self, d):
        if 'rpm_factor' in d:
            self.spin_rf.setValue(float(d['rpm_factor']))
        if 'max_order' in d:
            self.spin_mo.setValue(int(d['max_order']))
        if 'order_res' in d:
            self.spin_order_res.setValue(float(d['order_res']))
        if 'time_res' in d:
            self.spin_time_res.setValue(float(d['time_res']))
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
        if 'samples_per_rev' in d:
            try:
                self.spin_samples_per_rev.setValue(int(d['samples_per_rev']))
            except (TypeError, ValueError):
                pass
        if 'db_reference' in d:
            try:
                self.spin_db_ref.setValue(float(d['db_reference']))
            except (TypeError, ValueError):
                pass
        if 'weighting' in d:
            self._apply_weighting_value(d['weighting'])
        # ---- Wave 3 (2026-04-28 plan): legacy + new axis-key compat ----
        # Legacy 'dynamic' key compat — translate to z_floor/ceiling/auto.
        # Preferred path: explicit z_floor/ceiling/auto keys override the
        # legacy translation when both are present.
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
        # Legacy 'amplitude_mode' key compat — translate to combo_amp_unit.
        # blockSignals so this does NOT trip _on_amp_unit_changed and force
        # z_auto on (which would clobber the dynamic-derived floor/ceiling
        # we just set).
        if 'amplitude_mode' in d:
            val = str(d['amplitude_mode'])
            target = 'dB' if 'dB' in val else 'Linear'
            i = self.combo_amp_unit.findText(target)
            if i >= 0:
                self.combo_amp_unit.blockSignals(True)
                self.combo_amp_unit.setCurrentIndex(i)
                self.combo_amp_unit.blockSignals(False)
        # Apply new axis keys directly when present (preferred path).
        for key, attr in (
            ('z_auto', 'chk_z_auto'), ('y_auto', 'chk_y_auto'), ('x_auto', 'chk_x_auto'),
        ):
            if key in d:
                getattr(self, attr).setChecked(bool(d[key]))
        for key, attr in (
            ('z_floor', 'spin_z_floor'), ('z_ceiling', 'spin_z_ceiling'),
            ('y_min', 'spin_y_min'), ('y_max', 'spin_y_max'),
            ('x_min', 'spin_x_min'), ('x_max', 'spin_x_max'),
        ):
            if key in d:
                try:
                    getattr(self, attr).setValue(float(d[key]))
                except (TypeError, ValueError):
                    pass
        self._sync_axis_enabled()

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    def set_signal_candidates(self, candidates):
        # Preserve the user's current selection across repopulation —
        # see FFTContextual.set_signal_candidates for the same fix
        # (commit 0132253 missed FFT/Order panels).
        prev = self.combo_sig.currentData()
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        keep_idx = -1
        for i, (text, data) in enumerate(candidates):
            self.combo_sig.addItem(text, data)
            if prev is not None and data == prev:
                keep_idx = i
        # No prior selection to preserve -> leave the combo unselected (-1)
        # rather than defaulting to the first signal; see
        # FFTContextual.set_signal_candidates for the phantom-default rationale.
        self.combo_sig.setCurrentIndex(keep_idx)
        self.combo_sig.blockSignals(False)
        try:
            self.combo_sig.currentIndexChanged.disconnect(self._on_sig_index_changed)
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)

    def set_rpm_candidates(self, candidates):
        # Preserve current rpm selection — same regression class as
        # set_signal_candidates above.
        prev = self.combo_rpm.currentData()
        self.combo_rpm.blockSignals(True)
        self.combo_rpm.clear()
        self.combo_rpm.addItem("None", None)
        keep_idx = 0
        for i, (text, data) in enumerate(candidates, start=1):
            self.combo_rpm.addItem(text, data)
            if prev is not None and data == prev:
                keep_idx = i
        if keep_idx > 0:
            self.combo_rpm.setCurrentIndex(keep_idx)
        self.combo_rpm.blockSignals(False)

    def current_signal(self):
        return self.combo_sig.currentData()

    def current_rpm(self):
        return self.combo_rpm.currentData()

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(fs)
        self.spin_fs.blockSignals(False)

    def rpm_factor(self):
        return self.spin_rf.value()

    def get_params(self):
        nfft_text = self.combo_nfft.currentText()
        if nfft_text == self._AUTO_NFFT_LABEL:
            nfft = None
            nfft_mode = 'auto'
            nfft_effective = None
            nfft_preview = self._order_nfft_preview()
        else:
            nfft = int(nfft_text)
            nfft_mode = 'fixed'
            nfft_effective = nfft
            nfft_preview = nfft
        return dict(
            max_order=self.spin_mo.value(),
            order_res=self.spin_order_res.value(),
            time_res=self.spin_time_res.value(),
            nfft=nfft,
            nfft_mode=nfft_mode,
            nfft_preview=nfft_preview,
            nfft_effective=nfft_effective,
            rpm_factor=self.spin_rf.value(),
            fs=self.spin_fs.value(),
            weighting=self.combo_weighting.currentText(),
        )

    # --- Wave 3 (2026-04-28 plan): test-friendly param accessors ---
    # current_params/apply_params extend get_params/_apply_preset with the
    # new 坐标轴设置 group: x/y/z auto + min/max + amplitude unit. The
    # legacy 'amplitude_mode' key is still emitted (mapped from
    # combo_amp_unit) for backwards compatibility with downstream callers
    # that have not yet migrated; Wave 5 will switch the canvas render to
    # consume the explicit z_floor/z_ceiling keys directly.
    def current_params(self):
        p = self.get_params()
        # Map combo_amp_unit ('dB'/'Linear') back to the legacy mode string
        # so existing canvas code (Wave 5 will retire it) keeps working.
        p['amplitude_mode'] = (
            'Amplitude dB' if self.combo_amp_unit.currentText() == 'dB'
            else 'Amplitude'
        )
        # Wave 2 (2026-04-28 plan): combo_algorithm has been removed —
        # COT is the only tracking algorithm. ``samples_per_rev`` stays
        # in the param payload because COT consumes it.
        p['samples_per_rev'] = int(self.spin_samples_per_rev.value())
        # Display-only parameter: dB reference value.
        p['db_reference'] = self.spin_db_ref.value()
        # Axis controls (Wave 3): explicit X/Y/Z range + auto flags.
        p['x_auto'] = bool(self.chk_x_auto.isChecked())
        p['x_min'] = float(self.spin_x_min.value())
        p['x_max'] = float(self.spin_x_max.value())
        p['y_auto'] = bool(self.chk_y_auto.isChecked())
        p['y_min'] = float(self.spin_y_min.value())
        p['y_max'] = float(self.spin_y_max.value())
        p['z_auto'] = bool(self.chk_z_auto.isChecked())
        p['z_floor'] = float(self.spin_z_floor.value())
        p['z_ceiling'] = float(self.spin_z_ceiling.value())
        return p

    def apply_params(self, d):
        if 'max_order' in d:
            try:
                self.spin_mo.setValue(int(d['max_order']))
            except (TypeError, ValueError):
                pass
        if 'order_res' in d:
            try:
                self.spin_order_res.setValue(float(d['order_res']))
            except (TypeError, ValueError):
                pass
        if 'time_res' in d:
            try:
                self.spin_time_res.setValue(float(d['time_res']))
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
        # ---- Wave 3 (2026-04-28 plan): new axis fields (preferred path) ----
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

        # amplitude_mode → combo_amp_unit (blockSignals so the unit-toggle
        # handler does not flip z_auto on and stomp explicit z_floor/ceiling
        # values arriving in the same dict).
        if 'amplitude_mode' in d:
            val = str(d['amplitude_mode'])
            target = 'dB' if 'dB' in val else 'Linear'
            i = self.combo_amp_unit.findText(target)
            if i >= 0:
                self.combo_amp_unit.blockSignals(True)
                self.combo_amp_unit.setCurrentIndex(i)
                self.combo_amp_unit.blockSignals(False)

        # Legacy 'dynamic' key compat — translate to z_floor/ceiling/auto.
        # The new explicit z_floor key (already applied above) takes
        # precedence; we only fall through to dynamic when z_floor is
        # absent.
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

        # Wave 2 (2026-04-28 plan): the algorithm round-trip was dropped
        # along with combo_algorithm. Legacy presets carrying an
        # 'algorithm' key are silently ignored — Wave 6's preset-IO
        # migration covers the on-disk shape.
        if 'samples_per_rev' in d:
            try:
                self.spin_samples_per_rev.setValue(int(d['samples_per_rev']))
            except (TypeError, ValueError):
                pass
        if 'db_reference' in d:
            try:
                self.spin_db_ref.setValue(float(d['db_reference']))
            except (TypeError, ValueError):
                pass
        if 'weighting' in d:
            self._apply_weighting_value(d['weighting'])

        self._sync_axis_enabled()

    def set_progress(self, text):
        self.lbl_progress.setText(text)
