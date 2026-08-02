"""Time-chart statistics controls kept outside the dynamic method form."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QStackedLayout,
    QVBoxLayout, QWidget,
)

from mf4_analyzer.ui.widgets.compact_spinbox import CompactDoubleSpinBox, no_buttons


class ChartStatisticsPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchChartStatistics")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 4)
        root.setSpacing(5)
        head = QHBoxLayout()
        head.addWidget(QLabel("图内统计", self))
        head.addStretch(1)
        self.enabled = QCheckBox("启用", self)
        head.addWidget(self.enabled)
        root.addLayout(head)

        self._divider = QFrame(self)
        self._divider.setFrameShape(QFrame.HLine)
        self._divider.setFrameShadow(QFrame.Plain)
        root.addWidget(self._divider)

        self.range_row = QWidget(self)
        range_lay = QHBoxLayout(self.range_row)
        range_lay.setContentsMargins(0, 0, 0, 0)
        range_lay.setSpacing(6)
        self._range_label = QLabel("统计区间", self.range_row)
        self._range_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        range_lay.addWidget(self._range_label)
        self.auto_range = QCheckBox("自动", self.range_row)
        self.auto_range.setChecked(True)
        self.auto_range.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        range_lay.addWidget(self.auto_range)

        self._range_value_host = QWidget(self.range_row)
        self._range_stack = QStackedLayout(self._range_value_host)
        self._range_stack.setContentsMargins(0, 0, 0, 0)
        self._range_stack.setSpacing(0)
        self._auto_range_page = QWidget(self._range_value_host)
        auto_range_lay = QHBoxLayout(self._auto_range_page)
        auto_range_lay.setContentsMargins(0, 0, 0, 0)
        self.range_summary = QLabel("全时段", self._auto_range_page)
        self.range_summary.setObjectName("BatchChartStatisticsRangeSummary")
        self.range_summary.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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
            spin.setMinimumWidth(84)
            spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._min_label = QLabel("最小", self._manual_range_page)
        self._max_label = QLabel("最大", self._manual_range_page)
        self._range_dash = QLabel("—", self._manual_range_page)
        self._range_unit = QLabel("", self._manual_range_page)
        manual_range_lay.addWidget(self._min_label)
        manual_range_lay.addWidget(self.x_min, 1)
        manual_range_lay.addWidget(self._range_dash)
        manual_range_lay.addWidget(self._max_label)
        manual_range_lay.addWidget(self.x_max, 1)
        manual_range_lay.addWidget(self._range_unit)
        self._range_stack.addWidget(self._auto_range_page)
        self._range_stack.addWidget(self._manual_range_page)
        range_lay.addWidget(self._range_value_host, 1)
        root.addWidget(self.range_row)

        metrics = QWidget(self)
        metrics_lay = QHBoxLayout(metrics)
        metrics_lay.setContentsMargins(0, 0, 0, 0)
        metrics_lay.setSpacing(8)
        metrics_lay.addWidget(QLabel("统计项目", metrics))
        self.maximum = QCheckBox("最大值", metrics)
        self.minimum = QCheckBox("最小值", metrics)
        self.mean = QCheckBox("样本平均", metrics)
        for check in (self.maximum, self.minimum, self.mean):
            check.setChecked(True)
            metrics_lay.addWidget(check)
            check.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        metrics_lay.addStretch(1)
        root.addWidget(metrics)
        self.note = QLabel("ⓘ 同一 X 对应多个 Y 时，按采集路径分别统计", self)
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        self.context = QLabel("", self)
        self.context.setObjectName("BatchChartStatisticsContext")
        root.addWidget(self.context)
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
        self._sync()

    def _sync(self, *_args) -> None:
        active = self.enabled.isChecked()
        automatic = self.auto_range.isChecked()
        self.auto_range.setEnabled(active)
        self._range_stack.setCurrentWidget(
            self._auto_range_page if automatic else self._manual_range_page
        )
        for spin in (self.x_min, self.x_max):
            spin.setEnabled(active and not automatic)
        for check in (self.maximum, self.minimum, self.mean):
            check.setEnabled(active)
        self.note.setEnabled(active)
        self.context.setEnabled(active)

    def set_context(self, *, x_source="time", x_channel="", unit="s") -> None:
        unit_text = str(unit or "").strip()
        if x_source == "channel":
            channel_text = x_channel or "请选择通道"
            self.context.setText(
                f"自定义 X：{channel_text} ({unit_text})"
                if unit_text else f"自定义 X：{channel_text}"
            )
            self.range_summary.setText("全范围")
        else:
            self.context.setText("时间 X：秒")
            self.range_summary.setText("全时段")
        self._range_unit.setText(unit_text)

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
        value = dict((params or {}).get("chart_statistics") or {})
        self.enabled.setChecked(bool(value.get("enabled", False)))
        self.auto_range.setChecked(str(value.get("range_mode", "full")) != "custom")
        for spin, key in ((self.x_min, "x_min"), (self.x_max, "x_max")):
            if value.get(key) is not None: spin.setValue(float(value[key]))
        wanted = set(value.get("metrics") or ("max", "min", "mean"))
        for name, check in (("max", self.maximum), ("min", self.minimum), ("mean", self.mean)):
            check.setChecked(name in wanted)
        self._sync()
