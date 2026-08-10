"""Inspector controls for one directional SISO FRF analysis."""
from __future__ import annotations

from collections.abc import Mapping

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
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
from ..widgets.pill_switch import PillSwitch
from ...ui_kit.widgets.segmented_choice import SegmentedChoice
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


_FACTS_PLACEHOLDER = "尚无计算结果；点击『计算频响』后在此显示实际参数。"
_FACTS_STALE_PREFIX = "（已过期）参数已改动，以下为上一次计算的结果"


_FRF_TOOLTIPS = {
    "input": "系统激励输入 x(t)。输入与输出必须来自同一逻辑来源，并共享真实时间轴。",
    "output": "系统响应输出 y(t)。FRF 表示输出相对输入的传递特性。",
    "swap": "交换系统激励输入 x(t) 与响应输出 y(t)；会改变 H(f) 的传递方向。",
    "window": "窗函数控制频谱泄漏与主瓣宽度；它不改变数据本身的物理频率分辨率。",
    "segment": "段越长，频率分辨率越细；同一时长内可用于平均的完整段数通常越少。",
    "overlap": "提高相邻段重叠会增加分段密度和计算量，不等于增加同等数量的独立信息。",
    "nfft_mode": "自动按段长选择 NFFT；手动 NFFT 不得小于段长。",
    "nfft": "零填充只加密频率采样点，不提高由段长决定的物理频率分辨率。",
    "magnitude": "dB 显示传递比的 20 log10(|H|)；线性显示传递比本身，不使用绝对 dB reference。",
    "frequency": "对数轴只在显示层隐藏 DC；不会删除原始 FRF 结果或导出数据。",
    "phase_unwrapped": "展开只移除 ±360° 跳变；真实系统延迟仍完整保留在相位斜率中。",
    "phase_wrapped": "将相位限制在 ±180°；真实系统延迟仍完整保留，未做任何补偿。",
    "delay": "纯延迟会形成随频率下降的线性相位项。相位展开只处理 360° 跳变，不移除该延迟。",
    "coherence": "低于此值只会触发可信度提示/淡化；不会删除数据或改变 FRF 计算。",
    "fade": "仅淡化低相干点的显示，不删除数据，也不会重新计算频响。",
    "compute": "按当前 pane 的输入、输出、时间范围和参数计算频响；不足两个完整段时会阻断。",
    "view_time": "在时域中复用或新建包含该输入、输出和分析范围的独立 View。",
}

_ESTIMATOR_ITEMS = (
    ("H1（输出噪声）", "h1", "H1 = Pxy / Pxx。适合输出侧测量噪声占主导的常见测量；默认。"),
    ("H2（输入噪声）", "h2", "H2 = Pyy / conj(Pxy)。适合输入侧测量噪声占主导；需明确选择。"),
)

_WINDOW_ITEM_TOOLTIPS = {
    "hanning": "Hanning：通用平衡，适合大多数 FRF 测量。",
    "hamming": "Hamming：较低旁瓣，主瓣略宽。",
    "blackman": "Blackman：更强旁瓣抑制，主瓣更宽。",
    "bartlett": "Bartlett：三角窗，简单的泄漏抑制。",
    "kaiser": "Kaiser（β=14）：强旁瓣抑制，主瓣较宽。",
    "flattop": "Flattop：幅值读数更准确，主瓣最宽。",
}


def _install_combo_tooltips(combo: QComboBox, item_tooltips) -> None:
    """Set popup-item tips and keep the collapsed combo's tip in sync."""
    for index, text in enumerate(item_tooltips):
        combo.setItemData(index, text, Qt.ToolTipRole)

    def sync(index: int) -> None:
        combo.setToolTip(item_tooltips[index] if 0 <= index < len(item_tooltips) else "")

    combo.currentIndexChanged.connect(sync)
    sync(combo.currentIndex())


def _fact(facts, name):
    """Read one field off ``FrfEffectiveFacts`` or an equivalent mapping."""
    if isinstance(facts, Mapping):
        return facts.get(name)
    return getattr(facts, name, None)


def _fact_number(facts, name, spec):
    value = _fact(facts, name)
    if value is None:
        return None
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return None


def format_effective_facts(facts) -> list[str]:
    """Render the resident "有效事实" rows for one completed FRF run.

    Pure, UI-free formatting so the MainWindow adapter can hand over the raw
    :class:`~mf4_analyzer.signal.frf.FrfEffectiveFacts` (or any mapping with
    the same field names) without knowing how it is presented.  Fields that a
    caller cannot supply are dropped rather than printed as ``None``.
    """
    rows: list[tuple[str, str]] = []
    fs_text = _fact_number(facts, "fs", "g")
    if fs_text is not None:
        rows.append(("实际 Fs", f"{fs_text} Hz"))
    df_text = _fact_number(facts, "df", "g")
    if df_text is not None:
        rows.append(("频率分辨率 df", f"{df_text} Hz"))
    segments = _fact(facts, "segments")
    if segments is not None:
        rows.append(("完整段数", f"{int(segments)}"))
    start = _fact_number(facts, "time_start", "g")
    end = _fact_number(facts, "time_end", "g")
    if start is not None and end is not None:
        rows.append(("有效时间范围", f"{start} – {end} s"))
    jitter_text = _fact_number(facts, "max_time_jitter", ".3g")
    if jitter_text is not None:
        # The numeric core reports jitter relative to the nominal sample step,
        # so the row must not read as seconds.
        rows.append(("最大时间抖动", f"{jitter_text}（相对 dt）"))
    invalid_bins = _fact(facts, "invalid_bins")
    if invalid_bins is not None:
        rows.append(("无效频点", f"{int(invalid_bins)} 个"))
    return [f"{label}：{value}" for label, value in rows]


def normalize_effective_warnings(warnings) -> list[str]:
    """De-duplicate warning lines, keeping first-appearance order."""
    seen: list[str] = []
    for raw in warnings or ():
        text = str(raw).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


class FrfContextual(QWidget):
    """Directional input/output mapping plus compute and display controls."""

    frf_requested = pyqtSignal()
    view_in_time_requested = pyqtSignal()
    pair_changed = pyqtSignal(object, object)
    compute_params_changed = pyqtSignal(object)
    display_params_changed = pyqtSignal(object)

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

        mapping_card = QFrame(self)
        mapping_card.setObjectName("frfSignalCard")
        mapping_layout = QVBoxLayout(mapping_card)
        mapping_layout.setContentsMargins(11, 8, 11, 10)
        mapping_layout.setSpacing(5)
        siso = QLabel("SISO", mapping_card)
        siso.setObjectName("frfSisoBadge")
        # Lead with the signal-flow model so FRF's input/output relationship
        # is visible before any field; the redundant outer heading is gone.
        mapping_layout.addWidget(self._make_system_flow(mapping_card))
        mapping_layout.addWidget(_make_group_header(
            "输入 / 输出 + 时间", action_button=siso, parent=mapping_card,
        ))
        self.combo_input = SearchableComboBox(mapping_card)
        self.combo_output = SearchableComboBox(mapping_card)
        self.combo_input.setToolTip(_FRF_TOOLTIPS["input"])
        self.combo_output.setToolTip(_FRF_TOOLTIPS["output"])
        mapping_layout.addWidget(self._make_signal_row(
            mapping_card, "输入 x", "frfInput", self.combo_input,
        ))
        mapping_layout.addWidget(self._make_signal_row(
            mapping_card, "输出 y", "frfOutput", self.combo_output,
        ))
        pair_actions = QHBoxLayout()
        pair_actions.setContentsMargins(0, 0, 0, 0)
        pair_actions.addStretch(1)
        self.btn_swap = QPushButton("交换输入/输出", mapping_card)
        # ``tool`` is reserved for icon-only controls: its QSS deliberately
        # removes the height floor.  This text action needs its own role.
        self.btn_swap.setProperty("role", "frf-swap")
        self.btn_swap.setToolTip(_FRF_TOOLTIPS["swap"])
        # A narrow Inspector can put this action under vertical pressure during
        # a mode/reparent layout pass.  Pin its natural height so every settled
        # and captured frame is legible.
        self.btn_swap.setMinimumHeight(self.btn_swap.sizeHint().height())
        self.btn_swap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        pair_actions.addWidget(self.btn_swap)
        mapping_layout.addLayout(pair_actions)
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
        for text, token, tooltip in _ESTIMATOR_ITEMS:
            self.combo_estimator.addItem(text, token)
        _install_combo_tooltips(
            self.combo_estimator,
            [item[2] for item in _ESTIMATOR_ITEMS],
        )
        self.choice_estimator = SegmentedChoice(params_card)
        self.choice_estimator.bind(self.combo_estimator, labels=("H1", "H2"))
        compute_form.addRow(
            "估计器:", _fit_field(self.choice_estimator, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.combo_window = QComboBox(params_card)
        for text in ("hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop"):
            self.combo_window.addItem(text, text)
        _install_combo_tooltips(
            self.combo_window,
            [_WINDOW_ITEM_TOOLTIPS[text] for text in (
                "hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop",
            )],
        )
        compute_form.addRow(
            "窗函数:", _fit_field(self.combo_window, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.spin_t_win = _no_buttons(QDoubleSpinBox(params_card))
        self.spin_t_win.setDecimals(3)
        self.spin_t_win.setRange(0.001, 3600.0)
        self.spin_t_win.setValue(2.0)
        self.spin_t_win.setSuffix(" s")
        self.spin_t_win.setToolTip(_FRF_TOOLTIPS["segment"])
        compute_form.addRow(
            "段长:", _fit_field(self.spin_t_win, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.spin_overlap = _no_buttons(QSpinBox(params_card))
        self.spin_overlap.setRange(0, 95)
        self.spin_overlap.setValue(50)
        self.spin_overlap.setSuffix(" %")
        self.spin_overlap.setToolTip(_FRF_TOOLTIPS["overlap"])
        compute_form.addRow(
            "重叠率:", _fit_field(self.spin_overlap, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

        self.combo_nfft_mode = QComboBox(params_card)
        self.combo_nfft_mode.addItem("自动", "auto")
        self.combo_nfft_mode.addItem("手动", "manual")
        _install_combo_tooltips(
            self.combo_nfft_mode,
            (
                "自动：按段长选择 NFFT。零填充只加密频率采样，不提升物理分辨率。",
                "手动：NFFT 不得小于段长。零填充只加密频率采样，不提升物理分辨率。",
            ),
        )
        self.choice_nfft_mode = SegmentedChoice(params_card)
        self.choice_nfft_mode.bind(self.combo_nfft_mode)
        compute_form.addRow(
            "NFFT 模式:",
            _fit_field(self.choice_nfft_mode, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        self.spin_nfft = _no_buttons(QSpinBox(params_card))
        self.spin_nfft.setRange(1, 16_777_216)
        self.spin_nfft.setValue(2048)
        self.spin_nfft.setEnabled(False)
        self.spin_nfft.setToolTip(_FRF_TOOLTIPS["nfft"])
        compute_form.addRow(
            "NFFT:", _fit_field(self.spin_nfft, max_width=_SHORT_FIELD_MAX_WIDTH)
        )

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
        self.btn_compute.setToolTip(_FRF_TOOLTIPS["compute"])
        params_layout.addWidget(self.btn_compute)
        self.btn_view_time = QPushButton("在时域查看", params_card)
        self.btn_view_time.setProperty("role", "secondary")
        self.btn_view_time.setToolTip(_FRF_TOOLTIPS["view_time"])
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
        _install_combo_tooltips(
            self.combo_magnitude_scale,
            (
                "dB：显示传递比的 20 log10(|H|)，不是绝对 dB reference。",
                "线性：显示传递比本身，不使用绝对 dB reference。",
            ),
        )
        self.choice_magnitude_scale = SegmentedChoice(display_card)
        self.choice_magnitude_scale.bind(self.combo_magnitude_scale)
        display_form.addRow(
            "幅值:",
            _fit_field(self.choice_magnitude_scale, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        # Retain the two comboboxes as the stable state/API surface used by
        # presets and project restore, but render the choices as the explicit
        # two-state controls from the approved FRF layout.
        self.combo_frequency_scale = QComboBox(display_card)
        self.combo_frequency_scale.addItem("对数", "log")
        self.combo_frequency_scale.addItem("线性", "linear")
        _install_combo_tooltips(
            self.combo_frequency_scale,
            (
                "对数轴只在显示层隐藏 DC；不会删除原始 FRF 结果或导出数据。",
                "线性轴保留等距频率显示；不会改变原始 FRF 结果或导出数据。",
            ),
        )
        self.choice_frequency_scale = SegmentedChoice(display_card)
        self.choice_frequency_scale.bind(self.combo_frequency_scale)
        self.btn_frequency_log, self.btn_frequency_linear = self.choice_frequency_scale.buttons()
        display_form.addRow(
            "频率轴:", _fit_field(self.choice_frequency_scale, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        self.btn_frequency_log.setToolTip(_FRF_TOOLTIPS["frequency"])
        self.btn_frequency_linear.setToolTip(
            "线性轴保留等距频率显示；不会改变原始 FRF 结果或导出数据。"
        )
        self.combo_phase_mode = QComboBox(display_card)
        self.combo_phase_mode.addItem("展开", "unwrapped")
        self.combo_phase_mode.addItem("包裹", "wrapped")
        _install_combo_tooltips(
            self.combo_phase_mode,
            (_FRF_TOOLTIPS["phase_unwrapped"], _FRF_TOOLTIPS["phase_wrapped"]),
        )
        self.choice_phase_mode = SegmentedChoice(display_card)
        self.choice_phase_mode.bind(self.combo_phase_mode, labels=("展开", "±180°"))
        self.btn_phase_unwrapped, self.btn_phase_wrapped = self.choice_phase_mode.buttons()
        display_form.addRow(
            "相位:", _fit_field(self.choice_phase_mode, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        self.btn_phase_unwrapped.setToolTip(_FRF_TOOLTIPS["phase_unwrapped"])
        self.btn_phase_wrapped.setToolTip(_FRF_TOOLTIPS["phase_wrapped"])
        self.lbl_delay_retention = QLabel("系统延迟：保留（不补偿）", display_card)
        self.lbl_delay_retention.setObjectName("frfDelayRetention")
        self.lbl_delay_retention.setToolTip(_FRF_TOOLTIPS["delay"])
        self.lbl_delay_retention.setTextInteractionFlags(Qt.NoTextInteraction)
        self.spin_coherence_threshold = _no_buttons(QDoubleSpinBox(display_card))
        self.spin_coherence_threshold.setDecimals(2)
        self.spin_coherence_threshold.setSingleStep(0.05)
        self.spin_coherence_threshold.setRange(0.0, 1.0)
        self.spin_coherence_threshold.setValue(0.8)
        self.spin_coherence_threshold.setToolTip(_FRF_TOOLTIPS["coherence"])
        display_form.addRow(
            "相干阈值:",
            _fit_field(
                self.spin_coherence_threshold, max_width=_SHORT_FIELD_MAX_WIDTH
            ),
        )
        self.chk_fade_low_coherence = QCheckBox(display_card)
        self.chk_fade_low_coherence.setChecked(True)
        self.chk_fade_low_coherence.hide()
        self.btn_fade_low_coherence = PillSwitch(
            display_card,
            object_name="frfFadeToggle",
            accessible_name="低相干区淡化",
        )
        self.btn_fade_low_coherence.setChecked(True)
        self.btn_fade_low_coherence.setToolTip(_FRF_TOOLTIPS["fade"])
        display_form.addRow("低相干区淡化:", self.btn_fade_low_coherence)
        display_layout.addLayout(display_form)
        display_layout.addWidget(self.lbl_delay_retention)
        root.addWidget(display_card)

        # Resident measured facts (spec §5.3/§13). The status bar message is
        # transient, so the numbers a reading depends on — and every warning
        # the numeric core produced — must also live somewhere permanent.
        facts_card = QFrame(self)
        facts_card.setObjectName("frfFactsCard")
        facts_layout = QVBoxLayout(facts_card)
        facts_layout.setContentsMargins(11, 8, 11, 10)
        facts_layout.setSpacing(6)
        facts_layout.addWidget(_make_group_header("有效事实", parent=facts_card))
        self.lbl_facts_placeholder = QLabel(_FACTS_PLACEHOLDER, facts_card)
        self.lbl_facts_placeholder.setObjectName("frfFactsPlaceholder")
        self.lbl_facts_placeholder.setWordWrap(True)
        facts_layout.addWidget(self.lbl_facts_placeholder)
        self.lbl_effective_facts = QLabel("", facts_card)
        self.lbl_effective_facts.setObjectName("frfEffectiveFacts")
        self.lbl_effective_facts.setWordWrap(True)
        self.lbl_effective_facts.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.lbl_effective_facts.hide()
        facts_layout.addWidget(self.lbl_effective_facts)
        self.lbl_effective_warnings = QLabel("", facts_card)
        self.lbl_effective_warnings.setObjectName("frfEffectiveWarnings")
        self.lbl_effective_warnings.setWordWrap(True)
        self.lbl_effective_warnings.setProperty("factsRole", "warning")
        self.lbl_effective_warnings.hide()
        facts_layout.addWidget(self.lbl_effective_warnings)
        root.addWidget(facts_card)
        root.addStretch(1)

        self._effective_facts_rows = []
        self._effective_warnings = []
        self._effective_facts_stale = False
        self._refresh_effective_facts()

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

    def _wire(self) -> None:
        self.combo_input.currentIndexChanged.connect(self._on_pair_changed)
        self.combo_output.currentIndexChanged.connect(self._on_pair_changed)
        self.btn_swap.clicked.connect(self.swap_sources)
        self.combo_nfft_mode.currentIndexChanged.connect(self._sync_nfft_enabled)
        self.btn_compute.clicked.connect(self.frf_requested)
        self.btn_view_time.clicked.connect(self.view_in_time_requested)
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
        for spin in (
            self.spin_t_win,
            self.spin_overlap,
            self.spin_nfft,
            self.spin_coherence_threshold,
        ):
            spin.valueChanged.connect(self._on_param_changed)
        for check in (self.chk_fade_low_coherence,):
            check.toggled.connect(self._on_param_changed)
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
            items.append((f"{label}（来源不可用）", source))
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
            f"当前分析 View 未包含原{'、'.join(roles)}通道（来源不可用），"
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

    # -- resident effective facts ---------------------------------------

    def set_effective_facts(self, facts, warnings=()) -> None:
        """Publish one completed run's measured facts and its warnings.

        ``facts`` is the raw :class:`FrfEffectiveFacts` (or an equivalent
        mapping) so the MainWindow adapter only moves data; every formatting
        decision stays here.  Publishing always clears any stale marking —
        these numbers describe the result now on screen.
        """
        self._effective_facts_rows = format_effective_facts(facts)
        self._effective_warnings = normalize_effective_warnings(warnings)
        self._effective_facts_stale = False
        self._refresh_effective_facts()

    def clear_effective_facts(self) -> None:
        self._effective_facts_rows = []
        self._effective_warnings = []
        self._effective_facts_stale = False
        self._refresh_effective_facts()

    def mark_effective_facts_stale(self) -> None:
        """Age the shown facts without dropping them.

        Compute parameters changed but nothing was recomputed: the previous
        numbers are still the user's only reference, so they stay readable and
        are only labelled and dimmed.  An empty card has nothing to age.
        """
        if not self._effective_facts_rows and not self._effective_warnings:
            return
        if self._effective_facts_stale:
            return
        self._effective_facts_stale = True
        self._refresh_effective_facts()

    def effective_facts_text(self) -> str:
        return self.lbl_effective_facts.text()

    def effective_warnings_text(self) -> str:
        return self.lbl_effective_warnings.text()

    def effective_facts_is_stale(self) -> bool:
        return bool(self._effective_facts_stale)

    def _refresh_effective_facts(self) -> None:
        rows = list(self._effective_facts_rows)
        if rows and self._effective_facts_stale:
            rows.insert(0, _FACTS_STALE_PREFIX)
        has_content = bool(rows or self._effective_warnings)
        self.lbl_effective_facts.setText("\n".join(rows))
        self.lbl_effective_facts.setVisible(bool(rows))
        self.lbl_effective_warnings.setText(
            "\n".join(f"• {line}" for line in self._effective_warnings)
        )
        self.lbl_effective_warnings.setVisible(bool(self._effective_warnings))
        self.lbl_facts_placeholder.setVisible(not has_content)
        state = "stale" if self._effective_facts_stale else "fresh"
        for widget in (
            self.lbl_effective_facts,
            self.lbl_effective_warnings,
            self.lbl_facts_placeholder,
        ):
            if widget.property("factsState") == state:
                continue
            widget.setProperty("factsState", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def compute_params(self) -> dict:
        nfft_mode = str(self.combo_nfft_mode.currentData())
        return {
            "estimator": str(self.combo_estimator.currentData()),
            "t_win_s": float(self.spin_t_win.value()),
            "overlap": float(self.spin_overlap.value()) / 100.0,
            "nfft_mode": nfft_mode,
            "nfft": int(self.spin_nfft.value()) if nfft_mode == "manual" else None,
            "window": str(self.combo_window.currentData()),
            "periodic_window": True,
            "detrend": "constant",
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

    def reset_to_defaults(self) -> None:
        """Restore construction-time defaults for a blank analysis View."""
        bar = getattr(self, "preset_bar", None)
        defaults = getattr(bar, "_default_params", None) if bar is not None else None
        if isinstance(defaults, dict) and defaults:
            self.apply_params(dict(defaults))

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


__all__ = [
    "FrfContextual",
    "format_effective_facts",
    "normalize_effective_warnings",
]
