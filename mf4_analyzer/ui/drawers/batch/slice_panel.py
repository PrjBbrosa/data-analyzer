"""Spectrogram slice-export controls for the batch dialog.

Only visible for the two spectrogram methods (``fft_time`` / ``order_time``).
Mirrors the "预处理" card skeleton in ``filter_panel.py``: a summary row with
a title, a status note and a ``PillSwitch`` main toggle, with the settings
area collapsing entirely while the switch is off.
"""
from __future__ import annotations

import math

from PyQt5.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ....list_text import split_list_text
from ....ui_kit.widgets.segmented_choice import SegmentedChoice
from ...widgets.pill_switch import PillSwitch
from .optional_eyebrow import BatchOptionalEyebrow


_MAX_POSITIONS = 4


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

        self._eyebrow = BatchOptionalEyebrow("可选 · 导出切片", self)
        root.addWidget(self._eyebrow)

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
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # Hidden combo keeps preset / currentData APIs; SegmentedChoice is the
        # visible binary control (same pattern as Batch 目标策略 / 幅值单位).
        self._axis_combo = QComboBox(form_host)
        self._axis_combo.addItem("固定时间", "time")
        self._axis_combo.addItem("固定频率", "y")
        self._axis_choice = SegmentedChoice(form_host)
        self._axis_choice.bind(self._axis_combo)
        self._axis_choice.setMinimumWidth(0)
        self._axis_choice.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        form.addRow("切片维度", self._axis_choice)

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
            "ⓘ 中英文逗号均可，最多 4 个；一次只切一个维度", self._settings,
        )
        self._note.setWordWrap(True)
        settings_lay.addWidget(self._note)

        root.addWidget(self._settings)

        self._sync_enabled()
        self._refresh_unit()

        self._enable_switch.toggled.connect(self._sync_enabled)
        self._enable_switch.toggled.connect(self.changed)
        self._axis_combo.currentIndexChanged.connect(self._on_axis_changed)
        self._positions_edit.textChanged.connect(self._refresh_summary)
        self._positions_edit.textChanged.connect(self.changed)

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
        count = min(
            len(dict.fromkeys(self._parse_positions())), _MAX_POSITIONS,
        )
        self._summary_note.setText(f"{dim_label} · {count} 处")

    # ------------------------------------------------------------------
    def set_context(self, *, method: str = "fft_time") -> None:
        """Update the second axis option's wording for the active method."""
        self._method = str(method or "fft_time")
        label = "固定阶次" if self._method == "order_time" else "固定频率"
        self._axis_combo.setItemText(1, label)
        self._axis_choice.refresh_from_bound_combo()
        self._refresh_unit()
        self._refresh_summary()

    def _parse_positions(self) -> list[float]:
        values: list[float] = []
        for item in split_list_text(self._positions_edit.text()):
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
        parts = split_list_text(text)
        if any(not item for item in parts):
            return "位置：请输入逗号分隔的数字（中英文均可）"
        try:
            values = [float(item) for item in parts]
        except ValueError:
            return "位置：请输入逗号分隔的数字（中英文均可）"
        if not all(math.isfinite(value) for value in values):
            return "位置：请输入有限数字"
        if self._axis_combo.currentData() == "y" and any(
            value < 0 for value in values
        ):
            return "位置：固定频率或阶次不能为负数"
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
        blockers = [QSignalBlocker(w) for w in (
            self._enable_switch, self._axis_combo, self._positions_edit,
        )]
        try:
            raw = (params or {}).get("slice")
            if raw is None:
                # Normalization removes closed slices. A missing key means a preset did not
                # enable slicing; it does not mean the user's axis or positions should go away.
                self._enable_switch.setChecked(False)
                self._sync_enabled()
            else:
                value = dict(raw)
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
        finally:
            del blockers
        self._axis_choice.sync_from_bound_combo()
        self.changed.emit()
