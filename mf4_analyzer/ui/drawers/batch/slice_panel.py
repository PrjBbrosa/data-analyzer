"""Spectrogram slice-export controls for the batch dialog.

Only visible for the two spectrogram methods (``fft_time`` / ``order_time``).
Mirrors the "预处理" card skeleton in ``filter_panel.py``: a summary row with
a title, a status note and a ``PillSwitch`` main toggle, with the settings
area collapsing entirely while the switch is off.
"""
from __future__ import annotations

import math

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
    QWidget,
)

from ...widgets.pill_switch import PillSwitch


_MAX_POSITIONS = 4


def _field(widget: QWidget, max_width: int | None = None) -> QWidget:
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    if max_width is not None:
        widget.setMaximumWidth(max_width)
    lay.addWidget(widget)
    lay.addStretch(1)
    return host


def _format_number(value: float) -> str:
    return f"{float(value):g}"


class SlicePanel(QWidget):
    """Fixed-position slice export controls, single dimension per run."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchSlicePanel")
        self._method = "fft_time"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._summary_row = QWidget(self)
        self._summary_row.setObjectName("BatchFilterSummary")
        self._summary_row.setAttribute(Qt.WA_StyledBackground, True)
        top_lay = QHBoxLayout(self._summary_row)
        top_lay.setContentsMargins(9, 7, 9, 7)
        top_lay.setSpacing(7)
        self._summary_title = QLabel("切片", self._summary_row)
        self._summary_title.setObjectName("BatchFilterSummaryTitle")
        top_lay.addWidget(self._summary_title)
        self._summary_note = QLabel("切片关闭 · 仅导出谱图", self._summary_row)
        self._summary_note.setObjectName("BatchFilterSummaryNote")
        top_lay.addWidget(self._summary_note, 1)
        self._enable_switch = PillSwitch(
            self._summary_row,
            object_name="batchSliceEnableSwitch",
            accessible_name="切片",
        )
        self._enable_switch.setChecked(False)
        top_lay.addWidget(self._enable_switch, 0, Qt.AlignVCenter | Qt.AlignRight)
        root.addWidget(self._summary_row)

        self._settings = QWidget(self)
        settings_lay = QVBoxLayout(self._settings)
        settings_lay.setContentsMargins(0, 0, 0, 0)
        settings_lay.setSpacing(4)

        form_host = QWidget(self._settings)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._axis_combo = QComboBox(form_host)
        self._axis_combo.addItem("固定时间", "time")
        self._axis_combo.addItem("固定频率", "y")
        form.addRow("切片维度", _field(self._axis_combo, 140))

        position_row = QWidget(form_host)
        position_lay = QHBoxLayout(position_row)
        position_lay.setContentsMargins(0, 0, 0, 0)
        position_lay.setSpacing(6)
        self._positions_edit = QLineEdit(position_row)
        self._positions_edit.setPlaceholderText("5, 15, 25")
        position_lay.addWidget(self._positions_edit, 1)
        self._unit_label = QLabel("s", position_row)
        position_lay.addWidget(self._unit_label)
        form.addRow("位置", position_row)

        settings_lay.addWidget(form_host)

        self._note = QLabel(
            "ⓘ 逗号分隔，最多 4 个；一次只切一个维度", self._settings,
        )
        self._note.setWordWrap(True)
        settings_lay.addWidget(self._note)

        root.addWidget(self._settings)

        self._sync_enabled()
        self._refresh_unit()

        self._enable_switch.toggled.connect(self._sync_enabled)
        self._enable_switch.toggled.connect(lambda *_: self.changed.emit())
        self._axis_combo.currentIndexChanged.connect(self._on_axis_changed)
        self._positions_edit.textChanged.connect(self._refresh_summary)
        self._positions_edit.textChanged.connect(lambda *_: self.changed.emit())

    # ------------------------------------------------------------------
    def _sync_enabled(self, *_args) -> None:
        enabled = self._enable_switch.isChecked()
        self._settings.setVisible(enabled)
        self._refresh_summary()

    def _on_axis_changed(self, *_args) -> None:
        self._refresh_unit()
        self._refresh_summary()
        self.changed.emit()

    def _refresh_unit(self) -> None:
        axis = self._axis_combo.currentData()
        if axis == "time":
            unit = "s"
        elif self._method == "order_time":
            unit = ""
        else:
            unit = "Hz"
        self._unit_label.setText(unit)

    def _refresh_summary(self, *_args) -> None:
        if not self._enable_switch.isChecked():
            self._summary_note.setText("切片关闭 · 仅导出谱图")
            return
        dim_label = self._axis_combo.currentText()
        count = len(self._parse_positions())
        self._summary_note.setText(f"{dim_label} · {count} 处")

    # ------------------------------------------------------------------
    def set_context(self, *, method: str = "fft_time") -> None:
        """Update the second axis option's wording for the active method."""
        self._method = str(method or "fft_time")
        label = "固定阶次" if self._method == "order_time" else "固定频率"
        self._axis_combo.setItemText(1, label)
        self._refresh_unit()
        self._refresh_summary()

    def _parse_positions(self) -> list[float]:
        text = self._positions_edit.text().strip()
        if not text:
            return []
        values: list[float] = []
        for item in text.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                value = float(item)
            except ValueError:
                continue
            if math.isfinite(value):
                values.append(value)
        return values

    def positions_error(self) -> str:
        if not self._enable_switch.isChecked():
            return ""
        text = self._positions_edit.text().strip()
        if not text:
            return "位置：切片已启用，请填写至少一个位置"
        parts = [item.strip() for item in text.split(",")]
        if any(not item for item in parts):
            return "位置：请输入以逗号分隔的数字"
        try:
            values = [float(item) for item in parts]
        except ValueError:
            return "位置：请输入以逗号分隔的数字"
        if not all(math.isfinite(value) for value in values):
            return "位置：请输入有限数字"
        if len(values) > _MAX_POSITIONS:
            return f"位置：最多 {_MAX_POSITIONS} 个位置"
        return ""

    def get_params(self) -> dict:
        if not self._enable_switch.isChecked():
            return {}
        return {
            "slice": {
                "enabled": True,
                "axis": str(self._axis_combo.currentData() or "time"),
                "positions": self._parse_positions(),
            }
        }

    def apply_params(self, params: dict | None) -> None:
        value = dict((params or {}).get("slice") or {})
        axis = str(value.get("axis") or "time")
        idx = self._axis_combo.findData(axis)
        self._axis_combo.setCurrentIndex(idx if idx >= 0 else 0)
        positions = value.get("positions") or []
        self._positions_edit.setText(
            ", ".join(_format_number(item) for item in positions)
        )
        self._enable_switch.setChecked(bool(value.get("enabled", False)))
        self._sync_enabled()
        self._refresh_unit()
