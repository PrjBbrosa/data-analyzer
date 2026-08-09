"""Time-chart statistics controls kept outside the dynamic method form."""
from __future__ import annotations

from PyQt5.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QSizePolicy, QStackedLayout,
    QVBoxLayout, QWidget,
)

from mf4_analyzer.ui_kit.widgets.segmented_choice import SegmentedChoice
from mf4_analyzer.ui.widgets.compact_spinbox import CompactDoubleSpinBox, no_buttons
from mf4_analyzer.ui.widgets.pill_switch import PillSwitch

from .optional_eyebrow import BatchOptionalEyebrow


_LABEL_COL_WIDTH = 56


class ChartStatisticsPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchChartStatistics")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._eyebrow = BatchOptionalEyebrow("可选 · 图内统计", self)
        root.addWidget(self._eyebrow)

        self._summary_row = QWidget(self)
        self._summary_row.setObjectName("BatchFilterSummary")
        self._summary_row.setAttribute(Qt.WA_StyledBackground, True)
        top_lay = QHBoxLayout(self._summary_row)
        top_lay.setContentsMargins(9, 7, 9, 7)
        top_lay.setSpacing(7)
        self._summary_title = QLabel("图内统计", self._summary_row)
        self._summary_title.setObjectName("BatchFilterSummaryTitle")
        top_lay.addWidget(self._summary_title)
        self._summary_note = QLabel("统计关闭 · 图上不加标注", self._summary_row)
        self._summary_note.setObjectName("BatchFilterSummaryNote")
        top_lay.addWidget(self._summary_note, 1)
        self.enabled = PillSwitch(
            self._summary_row,
            object_name="batchChartStatisticsEnableSwitch",
            accessible_name="图内统计",
        )
        self.enabled.setChecked(False)
        top_lay.addWidget(self.enabled, 0, Qt.AlignVCenter | Qt.AlignRight)
        root.addWidget(self._summary_row)

        self._settings = QWidget(self)
        settings_lay = QVBoxLayout(self._settings)
        settings_lay.setContentsMargins(0, 0, 0, 0)
        settings_lay.setSpacing(8)

        # ----- 统计区间：SegmentedChoice + 下方展开自动说明 / 手动双 spin -----
        # ``auto_range`` stays the boolean state owner (get/apply/tests); the
        # visible control is a SegmentedChoice bound to a hidden combo.
        self.range_row = QWidget(self._settings)
        range_outer = QVBoxLayout(self.range_row)
        range_outer.setContentsMargins(0, 0, 0, 0)
        range_outer.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        self._range_label = QLabel("统计区间", self.range_row)
        self._range_label.setObjectName("BatchChartStatisticsRowLabel")
        self._range_label.setFixedWidth(_LABEL_COL_WIDTH)
        self._range_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        mode_row.addWidget(self._range_label, 0, Qt.AlignVCenter)

        self.auto_range = QCheckBox("自动", self.range_row)
        self.auto_range.setChecked(True)
        self.auto_range.hide()

        self._range_mode_combo = QComboBox(self.range_row)
        self._range_mode_combo.addItem("自动", "auto")
        self._range_mode_combo.addItem("手动", "manual")
        self._range_mode_choice = SegmentedChoice(self.range_row)
        self._range_mode_choice.bind(self._range_mode_combo)
        self._range_mode_choice.setMinimumWidth(0)
        self._range_mode_choice.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed,
        )
        mode_row.addWidget(self._range_mode_choice, 1)
        range_outer.addLayout(mode_row)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(8)
        value_indent = QWidget(self.range_row)
        value_indent.setFixedWidth(_LABEL_COL_WIDTH)
        value_row.addWidget(value_indent)

        self._range_value_host = QWidget(self.range_row)
        self._range_stack = QStackedLayout(self._range_value_host)
        self._range_stack.setContentsMargins(0, 0, 0, 0)
        self._range_stack.setSpacing(0)

        self._auto_range_page = QWidget(self._range_value_host)
        auto_range_lay = QHBoxLayout(self._auto_range_page)
        auto_range_lay.setContentsMargins(0, 0, 0, 0)
        self.range_summary = QLabel("全时段", self._auto_range_page)
        self.range_summary.setObjectName("BatchChartStatisticsRangeSummary")
        self.range_summary.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        auto_range_lay.addWidget(self.range_summary)
        auto_range_lay.addStretch(1)

        self._manual_range_page = QWidget(self._range_value_host)
        manual_range_lay = QHBoxLayout(self._manual_range_page)
        manual_range_lay.setContentsMargins(0, 0, 0, 0)
        manual_range_lay.setSpacing(6)
        self.x_min = no_buttons(CompactDoubleSpinBox(self._manual_range_page))
        self.x_max = no_buttons(CompactDoubleSpinBox(self._manual_range_page))
        for spin in (self.x_min, self.x_max):
            spin.setRange(-1e12, 1e12)
            spin.setDecimals(6)
            spin.setMinimumWidth(72)
            spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._min_label = QLabel("最小", self._manual_range_page)
        self._max_label = QLabel("最大", self._manual_range_page)
        for lab in (self._min_label, self._max_label):
            lab.setObjectName("BatchChartStatisticsSpinLab")
        self._range_dash = QLabel("—", self._manual_range_page)
        self._range_dash.setObjectName("BatchChartStatisticsDash")
        self._range_unit = QLabel("", self._manual_range_page)
        self._range_unit.setObjectName("BatchChartStatisticsUnit")
        manual_range_lay.addWidget(self._min_label)
        manual_range_lay.addWidget(self.x_min, 1)
        manual_range_lay.addWidget(self._range_dash)
        manual_range_lay.addWidget(self._max_label)
        manual_range_lay.addWidget(self.x_max, 1)
        manual_range_lay.addWidget(self._range_unit)
        self._range_stack.addWidget(self._auto_range_page)
        self._range_stack.addWidget(self._manual_range_page)
        value_row.addWidget(self._range_value_host, 1)
        range_outer.addLayout(value_row)
        settings_lay.addWidget(self.range_row)

        # ----- 统计项目：仍是 QCheckBox（接线不变），外观做成 HTML .mchip -----
        metrics = QWidget(self._settings)
        metrics_lay = QHBoxLayout(metrics)
        metrics_lay.setContentsMargins(0, 0, 0, 0)
        metrics_lay.setSpacing(6)
        metrics_label = QLabel("统计项目", metrics)
        metrics_label.setObjectName("BatchChartStatisticsRowLabel")
        metrics_label.setFixedWidth(_LABEL_COL_WIDTH)
        metrics_lay.addWidget(metrics_label, 0, Qt.AlignVCenter)
        self.maximum = QCheckBox("最大值", metrics)
        self.minimum = QCheckBox("最小值", metrics)
        self.mean = QCheckBox("样本平均", metrics)
        for check in (self.maximum, self.minimum, self.mean):
            check.setObjectName("BatchChartStatisticsMetric")
            check.setAttribute(Qt.WA_StyledBackground, True)
            check.setChecked(True)
            check.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            metrics_lay.addWidget(check)
        metrics_lay.addStretch(1)
        settings_lay.addWidget(metrics)

        self.note = QLabel(
            "ⓘ 同一 X 对应多个 Y 时，按采集路径分别统计", self._settings,
        )
        self.note.setObjectName("BatchChartStatisticsNote")
        self.note.setWordWrap(True)
        settings_lay.addWidget(self.note)

        # HTML .field：前缀 X · 主文案 · 右侧单位（避免「X 时间 X：秒」叠字）
        self._context_field = QWidget(self._settings)
        self._context_field.setObjectName("BatchChartStatisticsContextField")
        self._context_field.setAttribute(Qt.WA_StyledBackground, True)
        context_lay = QHBoxLayout(self._context_field)
        context_lay.setContentsMargins(8, 0, 8, 0)
        context_lay.setSpacing(6)
        self._context_prefix = QLabel("X", self._context_field)
        self._context_prefix.setObjectName("BatchChartStatisticsContextPrefix")
        context_lay.addWidget(self._context_prefix, 0)
        self.context = QLabel("", self._context_field)
        self.context.setObjectName("BatchChartStatisticsContext")
        self.context.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.context.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        context_lay.addWidget(self.context, 1)
        self._context_unit = QLabel("", self._context_field)
        self._context_unit.setObjectName("BatchChartStatisticsContextUnit")
        context_lay.addWidget(self._context_unit, 0)
        settings_lay.addWidget(self._context_field)
        root.addWidget(self._settings)

        for widget in (
            self.enabled, self.auto_range, self.x_min, self.x_max,
            self.maximum, self.minimum, self.mean,
        ):
            signal = (
                getattr(widget, "toggled", None)
                or getattr(widget, "currentIndexChanged", None)
                or getattr(widget, "valueChanged")
            )
            signal.connect(self._sync)
            signal.connect(self.changed)
        self._range_mode_combo.currentIndexChanged.connect(self._on_range_mode_ui)
        self._sync()

    def _on_range_mode_ui(self, index: int) -> None:
        """SegmentedChoice → hidden auto_range checkbox (state owner)."""
        automatic = int(index) == 0
        if self.auto_range.isChecked() != automatic:
            self.auto_range.setChecked(automatic)

    def _sync_range_mode_ui(self) -> None:
        want = 0 if self.auto_range.isChecked() else 1
        if self._range_mode_combo.currentIndex() != want:
            with QSignalBlocker(self._range_mode_combo):
                self._range_mode_combo.setCurrentIndex(want)
            self._range_mode_choice.sync_from_bound_combo()

    def _sync(self, *_args) -> None:
        active = self.enabled.isChecked()
        self._settings.setVisible(active)
        automatic = self.auto_range.isChecked()
        self.auto_range.setEnabled(active)
        self._range_mode_choice.setEnabled(active)
        self._sync_range_mode_ui()
        self._range_stack.setCurrentWidget(
            self._auto_range_page if automatic else self._manual_range_page
        )
        for spin in (self.x_min, self.x_max):
            spin.setEnabled(active and not automatic)
        for check in (self.maximum, self.minimum, self.mean):
            check.setEnabled(active)
        self.note.setEnabled(active)
        self.context.setEnabled(active)
        self._context_field.setEnabled(active)
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        if not self.enabled.isChecked():
            self._summary_note.setText("统计关闭 · 图上不加标注")
            return
        names = []
        if self.maximum.isChecked():
            names.append("最大")
        if self.minimum.isChecked():
            names.append("最小")
        if self.mean.isChecked():
            names.append("平均")
        metrics_text = "/".join(names) if names else "未选统计项目"
        if self.auto_range.isChecked():
            range_text = self.range_summary.text() or "全时段"
        else:
            unit = self._range_unit.text().strip()
            range_text = f"{self.x_min.value():g}–{self.x_max.value():g}"
            if unit:
                range_text = f"{range_text} {unit}"
        self._summary_note.setText(f"{range_text} · {metrics_text}")

    def set_context(self, *, x_source="time", x_channel="", unit="s") -> None:
        unit_text = str(unit or "").strip()
        if x_source == "channel":
            channel_text = x_channel or "请选择通道"
            self.context.setText(channel_text)
            self._context_unit.setText(unit_text)
            self.range_summary.setText("全范围")
        else:
            display_unit = "秒" if unit_text.lower() in ("", "s", "sec", "秒") else unit_text
            self.context.setText("时间")
            self._context_unit.setText(display_unit)
            self.range_summary.setText("全时段")
            unit_text = display_unit
        self._range_unit.setText(unit_text)
        self._refresh_summary()

    def get_params(self) -> dict:
        if not self.enabled.isChecked():
            return {}
        metrics = [
            name for name, check in (
                ("max", self.maximum), ("min", self.minimum),
                ("mean", self.mean),
            ) if check.isChecked()
        ]
        automatic = self.auto_range.isChecked()
        return {
            "chart_statistics": {
                "enabled": True,
                "range_mode": "full" if automatic else "custom",
                "x_min": None if automatic else float(self.x_min.value()),
                "x_max": None if automatic else float(self.x_max.value()),
                "metrics": metrics,
            },
        }

    def apply_params(self, params) -> None:
        blockers = [QSignalBlocker(w) for w in (
            self.enabled, self.auto_range, self._range_mode_combo,
            self.x_min, self.x_max,
            self.maximum, self.minimum, self.mean,
        )]
        try:
            raw = (params or {}).get("chart_statistics")
            if raw is None:
                # Our own normalization pops the key out entirely once the card
                # is disabled (`enabled: False` never round-trips). Treating a
                # missing key as "reset to auto" silently threw away a filled-in
                # custom range on a plain disable -> re-enable cycle: the switch
                # correctly went back to off, but auto_range/x_min/x_max should
                # stay exactly as the user left them.
                self.enabled.setChecked(False)
                self._sync()
            else:
                value = dict(raw)
                self.enabled.setChecked(bool(value.get("enabled", False)))
                self.auto_range.setChecked(
                    str(value.get("range_mode", "full")) != "custom"
                )
                for spin, key in ((self.x_min, "x_min"), (self.x_max, "x_max")):
                    if value.get(key) is not None:
                        spin.setValue(float(value[key]))
                wanted = set(value.get("metrics") or ("max", "min", "mean"))
                for name, check in (
                    ("max", self.maximum),
                    ("min", self.minimum),
                    ("mean", self.mean),
                ):
                    check.setChecked(name in wanted)
                self._sync()
        finally:
            del blockers
        self.changed.emit()
