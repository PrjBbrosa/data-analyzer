"""Inspector controls for one directional SISO FRF analysis."""
from __future__ import annotations

from collections.abc import Mapping

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...analysis_presets import get_builtin_preset, list_builtin_presets
from ...ui_kit.icons import Icons
from ...ui_kit.widgets.searchable_combo import SearchableComboBox
from ._helpers import (
    CUSTOM_PRESET_SLOTS,
    _LONG_FIELD_MAX_WIDTH,
    _SHORT_FIELD_MAX_WIDTH,
    _configure_form,
    _enforce_label_widths,
    _fit_field,
    _make_group_header,
    _no_buttons,
)
from .presets import PresetBar


class FrfContextual(QWidget):
    """Directional input/output mapping plus compute and display controls."""

    frf_requested = pyqtSignal()
    view_in_time_requested = pyqtSignal()
    pair_changed = pyqtSignal(object, object)
    compute_params_changed = pyqtSignal(object)
    display_params_changed = pyqtSignal(object)
    range_mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("frfContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._applying_preset = False
        self._external_validation = ""
        self._candidate_sources = frozenset()
        self._channel_labels = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel("系统辨识 · 频响（FRF）", self)
        title.setObjectName("frfContextTitle")
        root.addWidget(title)

        mapping_card = QFrame(self)
        mapping_card.setObjectName("frfSignalCard")
        mapping_layout = QVBoxLayout(mapping_card)
        mapping_layout.setContentsMargins(11, 8, 11, 10)
        mapping_layout.setSpacing(5)
        siso = QLabel("SISO", mapping_card)
        siso.setObjectName("frfSisoBadge")
        mapping_layout.addWidget(_make_group_header(
            "输入 / 输出 + 时间", action_button=siso, parent=mapping_card,
        ))
        self.combo_input = SearchableComboBox(mapping_card)
        self.combo_output = SearchableComboBox(mapping_card)
        mapping_layout.addWidget(self._make_signal_row(
            mapping_card, "输入 x", "frfInput", self.combo_input,
        ))
        mapping_layout.addWidget(self._make_system_flow(mapping_card))
        mapping_layout.addWidget(self._make_signal_row(
            mapping_card, "输出 y", "frfOutput", self.combo_output,
        ))
        pair_actions = QHBoxLayout()
        pair_actions.setContentsMargins(0, 0, 0, 0)
        pair_actions.addStretch(1)
        self.btn_swap = QPushButton("交换输入/输出", mapping_card)
        self.btn_swap.setProperty("role", "tool")
        self.btn_swap.setToolTip("交换系统激励输入与响应输出的方向")
        # A narrow Inspector can put this action under vertical pressure during
        # a mode/reparent layout pass.  Pin its natural height so every settled
        # and captured frame is legible.
        self.btn_swap.setMinimumHeight(self.btn_swap.sizeHint().height())
        self.btn_swap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        pair_actions.addWidget(self.btn_swap)
        mapping_layout.addLayout(pair_actions)
        range_form = QFormLayout()
        _configure_form(range_form)
        self.combo_range_mode = QComboBox(mapping_card)
        self.combo_range_mode.addItem("全范围", "full")
        self.combo_range_mode.addItem("使用当前时域范围", "current_time")
        self.combo_range_mode.addItem("手动范围", "manual")
        range_form.addRow(
            "分析范围:",
            _fit_field(self.combo_range_mode, max_width=_LONG_FIELD_MAX_WIDTH),
        )
        mapping_layout.addLayout(range_form)
        self._time_range_slot = QVBoxLayout()
        self._time_range_slot.setContentsMargins(0, 0, 0, 0)
        self._time_range_slot.setSpacing(0)
        mapping_layout.addLayout(self._time_range_slot)
        root.addWidget(mapping_card)

        params_card = QFrame(self)
        params_card.setObjectName("frfParamsCard")
        params_layout = QVBoxLayout(params_card)
        # Match the other Inspector parameter cards' field/button column.
        # The styled card contributes its own one-pixel frame on both sides.
        params_layout.setContentsMargins(10, 8, 10, 10)
        params_layout.setSpacing(7)

        params_layout.addWidget(_make_group_header("辨识参数"))
        self.preset_bar = PresetBar(
            "frf",
            self._collect_preset,
            self._apply_preset,
            parent=params_card,
            builtin_defaults=self._builtin_preset_defaults(),
            default_params=get_builtin_preset("frf", "robust").params_copy(),
            custom_slots=CUSTOM_PRESET_SLOTS,
        )
        params_layout.addWidget(self.preset_bar)
        compute_form = QFormLayout()
        _configure_form(compute_form)

        self.combo_estimator = QComboBox(params_card)
        self.combo_estimator.addItem("H1", "h1")
        self.combo_estimator.addItem("H2", "h2")
        compute_form.addRow(
            "估计器:", _fit_field(self.combo_estimator, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.combo_window = QComboBox(params_card)
        for text in ("hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop"):
            self.combo_window.addItem(text, text)
        compute_form.addRow(
            "窗函数:", _fit_field(self.combo_window, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.chk_periodic = QCheckBox("周期窗", params_card)
        self.chk_periodic.setChecked(True)
        compute_form.addRow("窗语义:", self.chk_periodic)

        self.spin_t_win = _no_buttons(QDoubleSpinBox(params_card))
        self.spin_t_win.setDecimals(3)
        self.spin_t_win.setRange(0.001, 3600.0)
        self.spin_t_win.setValue(2.0)
        self.spin_t_win.setSuffix(" s")
        compute_form.addRow(
            "段长:", _fit_field(self.spin_t_win, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.spin_overlap = _no_buttons(QSpinBox(params_card))
        self.spin_overlap.setRange(0, 95)
        self.spin_overlap.setValue(50)
        self.spin_overlap.setSuffix(" %")
        compute_form.addRow(
            "重叠率:", _fit_field(self.spin_overlap, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.combo_nfft_mode = QComboBox(params_card)
        self.combo_nfft_mode.addItem("自动", "auto")
        self.combo_nfft_mode.addItem("手动", "manual")
        compute_form.addRow(
            "NFFT 模式:",
            _fit_field(self.combo_nfft_mode, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        self.spin_nfft = _no_buttons(QSpinBox(params_card))
        self.spin_nfft.setRange(1, 16_777_216)
        self.spin_nfft.setValue(2048)
        self.spin_nfft.setEnabled(False)
        compute_form.addRow(
            "NFFT:", _fit_field(self.spin_nfft, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.chk_detrend = QCheckBox("每段去均值", params_card)
        self.chk_detrend.setChecked(True)
        compute_form.addRow("去趋势:", self.chk_detrend)
        params_layout.addLayout(compute_form)

        self.lbl_validation = QLabel("", params_card)
        self.lbl_validation.setObjectName("frfValidationMessage")
        self.lbl_validation.setWordWrap(True)
        self.lbl_validation.hide()
        params_layout.addWidget(self.lbl_validation)

        self.btn_compute = QPushButton("计算频响", params_card)
        self.btn_compute.setIcon(Icons.mode_frf())
        self.btn_compute.setIconSize(QSize(16, 16))
        self.btn_compute.setProperty("role", "primary")
        params_layout.addWidget(self.btn_compute)
        self.btn_view_time = QPushButton("在时域查看", params_card)
        self.btn_view_time.setProperty("role", "secondary")
        params_layout.addWidget(self.btn_view_time)
        root.addWidget(params_card)

        display_card = QFrame(self)
        display_card.setObjectName("frfDisplayCard")
        display_layout = QVBoxLayout(display_card)
        display_layout.setContentsMargins(11, 8, 11, 10)
        display_layout.setSpacing(7)
        display_layout.addWidget(_make_group_header("显示与可信度"))
        display_form = QFormLayout()
        _configure_form(display_form)
        self.combo_magnitude_scale = QComboBox(display_card)
        self.combo_magnitude_scale.addItem("dB", "db")
        self.combo_magnitude_scale.addItem("线性", "linear")
        display_form.addRow(
            "幅值:",
            _fit_field(self.combo_magnitude_scale, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        # Retain the two comboboxes as the stable state/API surface used by
        # presets and project restore, but render the choices as the explicit
        # two-state controls from the approved FRF layout.
        self.combo_frequency_scale = QComboBox(display_card)
        self.combo_frequency_scale.addItem("对数", "log")
        self.combo_frequency_scale.addItem("线性", "linear")
        self.combo_frequency_scale.hide()
        frequency_choice, self.btn_frequency_log, self.btn_frequency_linear = (
            self._make_choice_row(display_card, "对数", "线性")
        )
        display_form.addRow(
            "频率轴:", frequency_choice,
        )
        self.combo_phase_mode = QComboBox(display_card)
        self.combo_phase_mode.addItem("展开", "unwrapped")
        self.combo_phase_mode.addItem("包裹", "wrapped")
        self.combo_phase_mode.hide()
        phase_choice, self.btn_phase_unwrapped, self.btn_phase_wrapped = (
            self._make_choice_row(display_card, "展开", "±180°")
        )
        display_form.addRow(
            "相位:", phase_choice,
        )
        self.spin_coherence_threshold = _no_buttons(QDoubleSpinBox(display_card))
        self.spin_coherence_threshold.setDecimals(2)
        self.spin_coherence_threshold.setSingleStep(0.05)
        self.spin_coherence_threshold.setRange(0.0, 1.0)
        self.spin_coherence_threshold.setValue(0.8)
        display_form.addRow(
            "相干阈值:",
            _fit_field(
                self.spin_coherence_threshold, max_width=_SHORT_FIELD_MAX_WIDTH
            ),
        )
        self.chk_fade_low_coherence = QCheckBox(display_card)
        self.chk_fade_low_coherence.setChecked(True)
        self.chk_fade_low_coherence.hide()
        self.btn_fade_low_coherence = QPushButton("淡化", display_card)
        self.btn_fade_low_coherence.setObjectName("frfFadeToggle")
        self.btn_fade_low_coherence.setCheckable(True)
        self.btn_fade_low_coherence.setChecked(True)
        self.btn_fade_low_coherence.setProperty("role", "choice")
        display_form.addRow("低相干区淡化:", self.btn_fade_low_coherence)
        display_layout.addLayout(display_form)
        root.addWidget(display_card)
        root.addStretch(1)

        _enforce_label_widths(self, unify_columns=True)
        self._wire()
        self._refresh_validation()

    @staticmethod
    def _make_signal_row(parent, title, role, combo):
        row = QFrame(parent)
        row.setObjectName("frfSignalRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        dot = QLabel("●", row)
        dot.setObjectName(f"{role}Dot")
        label = QLabel(title, row)
        label.setObjectName("frfSignalRole")
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(dot)
        layout.addWidget(label)
        layout.addWidget(combo, 1)
        return row

    @staticmethod
    def _make_system_flow(parent):
        flow = QFrame(parent)
        flow.setObjectName("frfSystemFlow")
        layout = QHBoxLayout(flow)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        for text, name in (
            ("x(t)", "frfFlowInput"),
            ("→", "frfFlowArrow"),
            ("被辨识系统  H(f)", "frfFlowBlock"),
            ("→", "frfFlowArrow"),
            ("y(t)", "frfFlowOutput"),
        ):
            label = QLabel(text, flow)
            label.setObjectName(name)
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label, 1 if name == "frfFlowBlock" else 0)
        return flow

    @staticmethod
    def _make_choice_row(parent, primary, secondary):
        host = QFrame(parent)
        host.setObjectName("frfSegmentChoice")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        first = QPushButton(primary, host)
        second = QPushButton(secondary, host)
        group = QButtonGroup(host)
        group.setExclusive(True)
        for button in (first, second):
            button.setCheckable(True)
            button.setProperty("role", "frf-segment")
            group.addButton(button)
            layout.addWidget(button, 1)
        return host, first, second

    def _wire(self) -> None:
        self.combo_input.currentIndexChanged.connect(self._on_pair_changed)
        self.combo_output.currentIndexChanged.connect(self._on_pair_changed)
        self.combo_range_mode.currentIndexChanged.connect(
            lambda _index: self.range_mode_changed.emit(self.range_mode())
        )
        self.btn_swap.clicked.connect(self.swap_sources)
        self.combo_nfft_mode.currentIndexChanged.connect(self._sync_nfft_enabled)
        self.btn_compute.clicked.connect(self.frf_requested)
        self.btn_view_time.clicked.connect(self.view_in_time_requested)
        self.btn_frequency_log.clicked.connect(
            lambda: self._set_combo_data(self.combo_frequency_scale, "log")
        )
        self.btn_frequency_linear.clicked.connect(
            lambda: self._set_combo_data(self.combo_frequency_scale, "linear")
        )
        self.btn_phase_unwrapped.clicked.connect(
            lambda: self._set_combo_data(self.combo_phase_mode, "unwrapped")
        )
        self.btn_phase_wrapped.clicked.connect(
            lambda: self._set_combo_data(self.combo_phase_mode, "wrapped")
        )
        self.btn_fade_low_coherence.toggled.connect(
            self.chk_fade_low_coherence.setChecked
        )
        self.chk_fade_low_coherence.toggled.connect(
            self.btn_fade_low_coherence.setChecked
        )
        for combo in (
            self.combo_estimator,
            self.combo_window,
            self.combo_nfft_mode,
            self.combo_magnitude_scale,
            self.combo_frequency_scale,
            self.combo_phase_mode,
        ):
            combo.currentIndexChanged.connect(self._on_param_changed)
        self.combo_frequency_scale.currentIndexChanged.connect(
            self._sync_display_choice_buttons
        )
        self.combo_phase_mode.currentIndexChanged.connect(
            self._sync_display_choice_buttons
        )
        for spin in (
            self.spin_t_win,
            self.spin_overlap,
            self.spin_nfft,
            self.spin_coherence_threshold,
        ):
            spin.valueChanged.connect(self._on_param_changed)
        for check in (
            self.chk_periodic,
            self.chk_detrend,
            self.chk_fade_low_coherence,
        ):
            check.toggled.connect(self._on_param_changed)
        self._sync_display_choice_buttons()

    def _sync_display_choice_buttons(self, *_args) -> None:
        self.btn_frequency_log.setChecked(
            self.combo_frequency_scale.currentData() == "log"
        )
        self.btn_frequency_linear.setChecked(
            self.combo_frequency_scale.currentData() == "linear"
        )
        self.btn_phase_unwrapped.setChecked(
            self.combo_phase_mode.currentData() == "unwrapped"
        )
        self.btn_phase_wrapped.setChecked(
            self.combo_phase_mode.currentData() == "wrapped"
        )

    def time_range_layout(self):
        return self._time_range_slot

    @staticmethod
    def _coerce_key(value):
        if value is None:
            return None
        try:
            fid, channel = value
        except (TypeError, ValueError):
            return None
        return str(fid), str(channel)

    def set_channel_candidates(self, candidates) -> None:
        old_input = self.input_source()
        old_output = self.output_source()
        candidate_items = []
        for candidate in candidates or ():
            if isinstance(candidate, Mapping):
                label = candidate.get("label") or candidate.get("display")
                key = candidate.get("key") or candidate.get("source")
            else:
                try:
                    label, key = candidate
                except (TypeError, ValueError):
                    continue
            composite = self._coerce_key(key)
            if composite is None:
                continue
            rendered_label = str(label)
            self._channel_labels[composite] = rendered_label
            candidate_items.append((rendered_label, composite))
        self._candidate_sources = frozenset(
            source for _label, source in candidate_items
        )
        # Preserve an out-of-scope pair visibly as a disabled-compute state.
        # Dropping it from the combobox makes the live controls disagree with
        # the persisted pane during intermediate View projections (for example
        # while a newly-created FRF time View is still being populated).
        items = list(candidate_items)
        item_sources = set(self._candidate_sources)
        for source in (old_input, old_output):
            if source is None or source in item_sources:
                continue
            label = self._channel_labels.get(source, source[1])
            items.append((f"{label}（当前时域 View 外）", source))
            item_sources.add(source)
        old_input_blocked = self.combo_input.blockSignals(True)
        old_output_blocked = self.combo_output.blockSignals(True)
        try:
            for combo in (self.combo_input, self.combo_output):
                combo.clear()
                combo.addItem("请选择通道", None)
                for label, composite in items:
                    combo.addItem(label, composite)
            self._set_combo_source(self.combo_input, old_input)
            self._set_combo_source(self.combo_output, old_output)
        finally:
            self.combo_output.blockSignals(old_output_blocked)
            self.combo_input.blockSignals(old_input_blocked)

        self._refresh_validation()

    def _candidate_scope_message(self) -> str:
        roles = []
        input_source, output_source = self.pair()
        if input_source is not None and input_source not in self._candidate_sources:
            roles.append("输入")
        if output_source is not None and output_source not in self._candidate_sources:
            roles.append("输出")
        if not roles:
            return ""
        return (
            f"当前时域 View 未包含原{'、'.join(roles)}通道，"
            "请重新选择输入和输出。"
        )

    def _set_combo_source(self, combo, key) -> bool:
        composite = self._coerce_key(key)
        target = 0
        if composite is not None:
            for index in range(1, combo.count()):
                if self._coerce_key(combo.itemData(index)) == composite:
                    target = index
                    break
            else:
                combo.setCurrentIndex(0)
                return False
        combo.setCurrentIndex(target)
        return True

    def set_input_source(self, key) -> bool:
        return self._set_combo_source(self.combo_input, key)

    def set_output_source(self, key) -> bool:
        return self._set_combo_source(self.combo_output, key)

    def input_source(self):
        return self._coerce_key(self.combo_input.currentData())

    def output_source(self):
        return self._coerce_key(self.combo_output.currentData())

    def pair(self):
        return self.input_source(), self.output_source()

    def range_mode(self) -> str:
        return str(self.combo_range_mode.currentData())

    def set_range_mode(self, mode) -> bool:
        return self._set_combo_data(self.combo_range_mode, str(mode))

    def swap_sources(self) -> None:
        input_source, output_source = self.pair()
        old_input = self.combo_input.blockSignals(True)
        old_output = self.combo_output.blockSignals(True)
        try:
            self._set_combo_source(self.combo_input, output_source)
            self._set_combo_source(self.combo_output, input_source)
        finally:
            self.combo_input.blockSignals(old_input)
            self.combo_output.blockSignals(old_output)
        self._on_pair_changed()

    def _on_pair_changed(self, *_args) -> None:
        input_source, output_source = self.pair()
        self._refresh_validation()
        self.pair_changed.emit(input_source, output_source)

    def validation_message(self) -> str:
        return self.lbl_validation.text()

    def set_validation_message(self, message) -> None:
        self._external_validation = str(message or "")
        self._refresh_validation()

    def _refresh_validation(self) -> None:
        input_source, output_source = self.pair()
        candidate_scope_message = self._candidate_scope_message()
        if self._external_validation:
            message = self._external_validation
        elif candidate_scope_message:
            message = candidate_scope_message
        elif input_source is None or output_source is None:
            message = "请选择输入和输出"
        elif input_source == output_source:
            message = "输入和输出不能相同"
        else:
            message = ""
        self.lbl_validation.setText(message)
        self.lbl_validation.setVisible(bool(message))
        self.btn_compute.setEnabled(not message)
        self.btn_view_time.setEnabled(
            input_source is not None
            and output_source is not None
            and not candidate_scope_message
        )

    def compute_params(self) -> dict:
        nfft_mode = str(self.combo_nfft_mode.currentData())
        return {
            "estimator": str(self.combo_estimator.currentData()),
            "t_win_s": float(self.spin_t_win.value()),
            "overlap": float(self.spin_overlap.value()) / 100.0,
            "nfft_mode": nfft_mode,
            "nfft": int(self.spin_nfft.value()) if nfft_mode == "manual" else None,
            "window": str(self.combo_window.currentData()),
            "periodic_window": bool(self.chk_periodic.isChecked()),
            "detrend": "constant" if self.chk_detrend.isChecked() else "none",
        }

    def frf_params(self):
        from ...signal.frf import FrfParams

        return FrfParams(**self.compute_params())

    def display_params(self) -> dict:
        return {
            "magnitude_scale": str(self.combo_magnitude_scale.currentData()),
            "frequency_scale": str(self.combo_frequency_scale.currentData()),
            "phase_mode": str(self.combo_phase_mode.currentData()),
            "coherence_threshold": float(self.spin_coherence_threshold.value()),
            "fade_low_coherence": bool(self.chk_fade_low_coherence.isChecked()),
        }

    def current_params(self) -> dict:
        return {**self.compute_params(), **self.display_params()}

    def get_params(self) -> dict:
        return self.current_params()

    @staticmethod
    def _set_combo_data(combo, value) -> bool:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return True
        return False

    def apply_params(self, params, *, emit_changes=False) -> None:
        values = dict(params or {})
        before_compute = self.compute_params()
        before_display = self.display_params()
        self._applying_preset = True
        try:
            if "estimator" in values:
                self._set_combo_data(self.combo_estimator, str(values["estimator"]).lower())
            if "window" in values:
                self._set_combo_data(self.combo_window, str(values["window"]).lower())
            if "periodic_window" in values:
                self.chk_periodic.setChecked(bool(values["periodic_window"]))
            if "t_win_s" in values:
                self.spin_t_win.setValue(float(values["t_win_s"]))
            if "overlap" in values:
                overlap = float(values["overlap"])
                self.spin_overlap.setValue(round(overlap * 100 if overlap <= 1 else overlap))
            if "nfft_mode" in values:
                token = "manual" if str(values["nfft_mode"]).lower() == "manual" else "auto"
                self._set_combo_data(self.combo_nfft_mode, token)
            if values.get("nfft") is not None:
                self.spin_nfft.setValue(int(values["nfft"]))
            if "detrend" in values:
                self.chk_detrend.setChecked(str(values["detrend"]).lower() == "constant")
            if "magnitude_scale" in values:
                self._set_combo_data(
                    self.combo_magnitude_scale,
                    str(values["magnitude_scale"]).lower(),
                )
            if "frequency_scale" in values:
                self._set_combo_data(
                    self.combo_frequency_scale,
                    str(values["frequency_scale"]).lower(),
                )
            if "phase_mode" in values:
                self._set_combo_data(
                    self.combo_phase_mode, str(values["phase_mode"]).lower()
                )
            if "coherence_threshold" in values:
                self.spin_coherence_threshold.setValue(
                    float(values["coherence_threshold"])
                )
            if "fade_low_coherence" in values:
                self.chk_fade_low_coherence.setChecked(
                    bool(values["fade_low_coherence"])
                )
        finally:
            self._applying_preset = False
        self._sync_nfft_enabled()
        if self.compute_params() != before_compute:
            # A failed preflight can depend on the segment parameters.  Once
            # they change, enable a fresh compute attempt; the preflight will
            # still present any remaining data error.
            self._external_validation = ""
            self._refresh_validation()
        if emit_changes:
            compute = self.compute_params()
            display = self.display_params()
            if compute != before_compute:
                self.compute_params_changed.emit(compute)
            if display != before_display:
                self.display_params_changed.emit(display)

    def _collect_preset(self) -> dict:
        return self.current_params()

    def _apply_preset(self, params) -> None:
        self.apply_params(params, emit_changes=True)

    def apply_builtin_preset(self, key) -> None:
        self.apply_params(
            get_builtin_preset("frf", str(key)).params_copy(),
            emit_changes=True,
        )

    @staticmethod
    def _builtin_preset_defaults() -> dict:
        return {
            preset.slot: {
                "display_name": preset.display_name,
                "params": preset.params_copy(),
                "blurb": preset.blurb,
            }
            for preset in list_builtin_presets("frf")
        }

    def _sync_nfft_enabled(self, *_args) -> None:
        self.spin_nfft.setEnabled(self.combo_nfft_mode.currentData() == "manual")

    def _on_param_changed(self, *_args) -> None:
        if self._applying_preset:
            return
        self.preset_bar.set_custom_active()
        sender = self.sender()
        display_senders = (
            self.combo_magnitude_scale,
            self.combo_frequency_scale,
            self.combo_phase_mode,
            self.spin_coherence_threshold,
            self.chk_fade_low_coherence,
        )
        if sender in display_senders:
            self.display_params_changed.emit(self.display_params())
        else:
            # Compute-parameter edits must not leave a valid pair trapped
            # behind the previous preflight error.
            self._external_validation = ""
            self._refresh_validation()
            self.compute_params_changed.emit(self.compute_params())


__all__ = ["FrfContextual"]
