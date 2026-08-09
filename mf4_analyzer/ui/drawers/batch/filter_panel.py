"""Filter/preprocessing controls for the batch dialog."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ....signal.filters import FilterSpec
from ...inspector_sections._helpers import _fit_field, _pair_field
from ...widgets.pill_switch import PillSwitch
from ...widgets.compact_spinbox import CompactDoubleSpinBox, no_buttons
from .optional_eyebrow import BatchOptionalEyebrow


_KIND_LABEL_TO_KEY = {
    "低通": "low",
    "高通": "high",
    "带通": "band",
    "带阻": "bandstop",
}
_KIND_KEY_TO_LABEL = {value: key for key, value in _KIND_LABEL_TO_KEY.items()}


class BatchFilterPanel(QWidget):
    """Small filter editor shared by all batch analysis methods."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchFilterPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._eyebrow = BatchOptionalEyebrow("可选 · 预处理", self)
        root.addWidget(self._eyebrow)

        self._summary_row = QWidget(self)
        self._summary_row.setObjectName("BatchFilterSummary")
        self._summary_row.setAttribute(Qt.WA_StyledBackground, True)
        top_lay = QHBoxLayout(self._summary_row)
        top_lay.setContentsMargins(9, 7, 9, 7)
        top_lay.setSpacing(7)
        self._summary_title = QLabel("预处理", self._summary_row)
        self._summary_title.setObjectName("BatchFilterSummaryTitle")
        top_lay.addWidget(self._summary_title)
        self._summary_note = QLabel("滤波关闭 · 保留原始数据", self._summary_row)
        self._summary_note.setObjectName("BatchFilterSummaryNote")
        top_lay.addWidget(self._summary_note, 1)
        self._enable_switch = PillSwitch(
            self._summary_row,
            object_name="batchFilterEnableSwitch",
            accessible_name="滤波",
        )
        self._enable_switch.setChecked(False)
        top_lay.addWidget(self._enable_switch, 0, Qt.AlignVCenter | Qt.AlignRight)
        root.addWidget(self._summary_row)

        self._settings = QWidget(self)
        form = QFormLayout(self._settings)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # macOS defaults to FieldsStayAtSizeHint, which parks each editor at
        # its own sizeHint and makes 类型 / 截止 / 阶数 look jagged. Match the
        # time-domain FilterPanel: expand every field to one shared column.
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.combo_kind = QComboBox(self._settings)
        self.combo_kind.addItems(tuple(_KIND_LABEL_TO_KEY))
        form.addRow("类型", _fit_field(self.combo_kind))

        self.spin_cutoff = no_buttons(CompactDoubleSpinBox(self._settings))
        self.spin_cutoff.setDecimals(1)
        self.spin_cutoff.setRange(0.0, 1e6)
        self.spin_cutoff.setSuffix(" Hz")
        self.spin_cutoff.setValue(100.0)
        self._single_label = QLabel("截止", self._settings)
        self._single_row = _fit_field(self.spin_cutoff)
        form.addRow(self._single_label, self._single_row)

        self.spin_cutoff_lo = no_buttons(CompactDoubleSpinBox(self._settings))
        self.spin_cutoff_lo.setDecimals(1)
        self.spin_cutoff_lo.setRange(0.0, 1e6)
        self.spin_cutoff_lo.setSuffix(" Hz")
        self.spin_cutoff_lo.setValue(100.0)
        self.spin_cutoff_hi = no_buttons(CompactDoubleSpinBox(self._settings))
        self.spin_cutoff_hi.setDecimals(1)
        self.spin_cutoff_hi.setRange(0.0, 1e6)
        self.spin_cutoff_hi.setSuffix(" Hz")
        self.spin_cutoff_hi.setValue(2000.0)
        self._band_label = QLabel("频段", self._settings)
        self._band_row = _pair_field(self.spin_cutoff_lo, "–", self.spin_cutoff_hi)
        form.addRow(self._band_label, self._band_row)

        self.combo_order = QComboBox(self._settings)
        self.combo_order.addItems(("2", "4", "6", "8"))
        self.combo_order.setCurrentText("4")
        form.addRow("阶数", _fit_field(self.combo_order))

        root.addWidget(self._settings)

        self._time_options = QWidget(self)
        time_lay = QHBoxLayout(self._time_options)
        time_lay.setContentsMargins(0, 0, 0, 0)
        time_lay.setSpacing(10)
        self.chk_show_original = QCheckBox("导出原始", self._time_options)
        self.chk_show_original.setChecked(True)
        self.chk_show_filtered = QCheckBox("导出滤波后", self._time_options)
        self.chk_show_filtered.setChecked(True)
        time_lay.addWidget(self.chk_show_original)
        time_lay.addWidget(self.chk_show_filtered)
        time_lay.addStretch(1)
        root.addWidget(self._time_options)

        self._method = "fft"
        self._sync_enabled()
        self._sync_kind_rows()
        self.set_method("fft")

        self._enable_switch.toggled.connect(self._sync_enabled)
        self._enable_switch.toggled.connect(lambda *_: self.changed.emit())
        self.combo_kind.currentTextChanged.connect(self._sync_kind_rows)
        self.combo_kind.currentTextChanged.connect(lambda *_: self.changed.emit())
        self.combo_order.currentTextChanged.connect(self._refresh_summary)
        self.combo_order.currentTextChanged.connect(lambda *_: self.changed.emit())
        for spin in (self.spin_cutoff, self.spin_cutoff_lo, self.spin_cutoff_hi):
            spin.valueChanged.connect(self._refresh_summary)
            spin.valueChanged.connect(lambda *_: self.changed.emit())
        for chk in (self.chk_show_original, self.chk_show_filtered):
            chk.toggled.connect(lambda *_: self.changed.emit())

    def _sync_enabled(self, *_args) -> None:
        enabled = self._enable_switch.isChecked()
        self._settings.setVisible(enabled)
        self._time_options.setVisible(enabled and self._method == "time")
        self._refresh_summary()

    def _sync_kind_rows(self, *_args) -> None:
        is_band = self._kind_key() in {"band", "bandstop"}
        self._single_label.setVisible(not is_band)
        self._single_row.setVisible(not is_band)
        self.spin_cutoff.setVisible(not is_band)
        self._band_label.setVisible(is_band)
        self._band_row.setVisible(is_band)
        self.spin_cutoff_lo.setVisible(is_band)
        self.spin_cutoff_hi.setVisible(is_band)
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        if not self._enable_switch.isChecked():
            self._summary_note.setText("滤波关闭 · 保留原始数据")
            return
        order = int(self.combo_order.currentText())
        if self._kind_key() in {"band", "bandstop"}:
            range_text = (
                f"{self.spin_cutoff_lo.value():g}–{self.spin_cutoff_hi.value():g} Hz"
            )
        else:
            range_text = f"{self.spin_cutoff.value():g} Hz"
        self._summary_note.setText(
            f"{self.combo_kind.currentText()} · {range_text} · {order} 阶"
        )

    def _kind_key(self) -> str:
        return _KIND_LABEL_TO_KEY.get(self.combo_kind.currentText(), "low")

    def set_method(self, method: str) -> None:
        self._method = str(method)
        self._time_options.setVisible(
            self._method == "time" and self._enable_switch.isChecked()
        )

    def time_output_options_visible(self) -> bool:
        return not self._time_options.isHidden()

    def filter_params(self) -> dict:
        return {
            "enabled": self._enable_switch.isChecked(),
            "spec": self.filter_spec().to_dict(),
            "show_original": self.chk_show_original.isChecked(),
            "show_filtered": self.chk_show_filtered.isChecked(),
        }

    def apply_filter_params(self, params: dict | None) -> None:
        data = dict(params or {})
        spec_data = data.get("spec")
        if spec_data is None:
            spec = FilterSpec("low", order=4, cutoff=100.0)
        else:
            spec = FilterSpec.from_dict(spec_data)
        self._enable_switch.setChecked(bool(data.get("enabled", False)))
        self.apply_filter_spec(spec)
        self.chk_show_original.setChecked(bool(data.get("show_original", True)))
        self.chk_show_filtered.setChecked(bool(data.get("show_filtered", True)))

    def filter_spec(self) -> FilterSpec:
        kind = self._kind_key()
        order = int(self.combo_order.currentText())
        if kind in {"band", "bandstop"}:
            return FilterSpec(
                kind=kind,
                order=order,
                cutoff_lo=float(self.spin_cutoff_lo.value()),
                cutoff_hi=float(self.spin_cutoff_hi.value()),
            )
        return FilterSpec(
            kind=kind,
            order=order,
            cutoff=float(self.spin_cutoff.value()),
        )

    def apply_filter_spec(self, spec: FilterSpec) -> None:
        label = _KIND_KEY_TO_LABEL.get(spec.kind, "低通")
        self.combo_kind.setCurrentText(label)
        self.combo_order.setCurrentText(str(int(spec.order)))
        if spec.kind in {"band", "bandstop"}:
            self.spin_cutoff_lo.setValue(float(spec.cutoff_lo))
            self.spin_cutoff_hi.setValue(float(spec.cutoff_hi))
        else:
            self.spin_cutoff.setValue(float(spec.cutoff))
