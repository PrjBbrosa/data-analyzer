"""Output column for the batch dialog.

Mirrors the pre-W4 ``batch_sheet.py`` output group (recovered from commit
``ad28d29~1``): directory ``QLineEdit`` + 选择… ``QPushButton`` opening
``QFileDialog.getExistingDirectory``, ``chk_data`` / ``chk_image`` checkboxes,
and a ``csv``/``xlsx`` format ``QComboBox``.

Note: ``BatchOutput`` in ``mf4_analyzer.batch`` does NOT carry a ``directory``
field — the directory is owned by this panel and threaded into
``BatchRunner.run`` separately. ``apply_outputs`` therefore only consumes the
three persisted fields (``export_data``, ``export_image``, ``data_format``).
"""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from ....batch import BatchOutput
from ..._axis_defaults import z_range_for
from ...widgets.compact_spinbox import CompactDoubleSpinBox


def _axis_spin(parent, lo=-1e9, hi=1e9, value=0.0):
    spin = CompactDoubleSpinBox(parent)
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    spin.setRange(float(lo), float(hi))
    spin.setDecimals(6)
    spin.setValue(float(value))
    return spin


class OutputPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchOutputPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        title = QLabel("OUTPUT")
        title.setStyleSheet("color:#f59e0b;font-weight:600;font-size:13px;")
        outer.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        # Directory
        self._dir_edit = QLineEdit(self)
        self._dir_edit.setText(str(Path.home() / "Desktop" / "mf4_batch_output"))
        self._btn_browse = QPushButton("选择…", self)
        self._btn_browse.clicked.connect(self._choose_dir)
        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(0, 0, 0, 0)
        dir_row.addWidget(self._dir_edit, 1)
        dir_row.addWidget(self._btn_browse)
        form.addRow("输出目录", dir_row)

        # Export checkboxes
        self._chk_data = QCheckBox("数据文件", self)
        self._chk_data.setChecked(True)
        self._chk_image = QCheckBox("图片", self)
        self._chk_image.setChecked(True)
        chk_row = QHBoxLayout()
        chk_row.setContentsMargins(0, 0, 0, 0)
        chk_row.addWidget(self._chk_data)
        chk_row.addWidget(self._chk_image)
        chk_row.addStretch(1)
        form.addRow("导出内容", chk_row)

        # Format
        self._combo_format = QComboBox(self)
        self._combo_format.addItems(["csv", "xlsx"])
        form.addRow("数据格式", self._combo_format)
        outer.addLayout(form)

        axis_group = QGroupBox("坐标轴设置", self)
        axis_form = QFormLayout(axis_group)
        axis_form.setContentsMargins(0, 0, 0, 0)
        axis_form.setHorizontalSpacing(6)
        axis_form.setVerticalSpacing(4)

        self.chk_x_auto = QCheckBox("自动", axis_group)
        self.chk_x_auto.setChecked(True)
        self.spin_x_min = _axis_spin(axis_group, value=0.0)
        self.spin_x_max = _axis_spin(axis_group, value=0.0)
        self._x_axis_row = self._make_axis_row(
            self.chk_x_auto, self.spin_x_min, self.spin_x_max,
        )
        axis_form.addRow("X 范围", self._x_axis_row)

        self.chk_y_auto = QCheckBox("自动", axis_group)
        self.chk_y_auto.setChecked(True)
        self.spin_y_min = _axis_spin(axis_group, value=0.0)
        self.spin_y_max = _axis_spin(axis_group, value=0.0)
        self._y_axis_row = self._make_axis_row(
            self.chk_y_auto, self.spin_y_min, self.spin_y_max,
        )
        axis_form.addRow("Y 范围", self._y_axis_row)

        self.chk_z_auto = QCheckBox("自动", axis_group)
        self.chk_z_auto.setChecked(True)
        self.spin_z_floor = _axis_spin(axis_group, lo=-200.0, hi=200.0, value=-80.0)
        self.spin_z_ceiling = _axis_spin(axis_group, lo=-200.0, hi=200.0, value=0.0)
        self.combo_amp_unit = QComboBox(axis_group)
        self.combo_amp_unit.addItems(["dB", "Linear"])
        self._z_axis_row = self._make_axis_row(
            self.chk_z_auto, self.spin_z_floor, self.spin_z_ceiling,
            self.combo_amp_unit,
        )
        axis_form.addRow("Z 色阶", self._z_axis_row)

        outer.addWidget(axis_group)
        outer.addStretch(1)

        # Wiring
        self._dir_edit.textChanged.connect(lambda *_: self.changed.emit())
        self._chk_data.toggled.connect(lambda *_: self.changed.emit())
        self._chk_image.toggled.connect(lambda *_: self.changed.emit())
        self._combo_format.currentTextChanged.connect(lambda *_: self.changed.emit())
        # User-driven dB↔Linear toggle: per spec §1.4 reset z_auto/z_range
        # to the new unit's defaults. Programmatic ``apply_axis_params``
        # path wraps its own ``setCurrentIndex`` in ``blockSignals`` so
        # preset loads do NOT re-enter this handler. Coalesce the three
        # internal mutations (chk + 2 spins) into a single ``changed``
        # emit (§5 风险 OutputPanel emits).
        self.combo_amp_unit.currentTextChanged.connect(self._on_amp_unit_changed)
        for chk in (self.chk_x_auto, self.chk_y_auto, self.chk_z_auto):
            chk.toggled.connect(self._sync_axis_enabled)
            chk.toggled.connect(lambda *_: self.changed.emit())
        for spin in (
            self.spin_x_min, self.spin_x_max,
            self.spin_y_min, self.spin_y_max,
            self.spin_z_floor, self.spin_z_ceiling,
        ):
            spin.valueChanged.connect(lambda *_: self.changed.emit())
        self._sync_axis_enabled()

    def _make_axis_row(self, chk, spin_min, spin_max, unit_widget=None):
        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(chk)
        lay.addWidget(spin_min, 1)
        lay.addWidget(QLabel("→", row))
        lay.addWidget(spin_max, 1)
        if unit_widget is not None:
            unit_widget.setMinimumWidth(72)
            lay.addWidget(unit_widget)
        return row

    def _on_amp_unit_changed(self, text: str) -> None:
        """User toggled dB↔Linear on ``combo_amp_unit``.

        Per spec §1.2/§1.4 (2026-05-01-codex-review-fixes): force
        ``z_auto`` ON and reset (z_floor, z_ceiling) to the new unit's
        defaults so the previous unit's numeric range cannot bleed into
        the new unit. Mirrors ``OrderContextual._on_amp_unit_changed`` /
        ``FFTTimeContextual._on_amp_unit_changed`` in
        ``inspector_sections.py``.

        Emit-once mitigation (§5 风险 OutputPanel emits): each mutated
        child widget's own ``toggled`` / ``valueChanged`` signal is
        normally re-emitted as ``self.changed``. To avoid the batch
        preset becoming dirty 3+ times for one user action, block the
        children only (NOT ``self``) while mutating, then emit
        ``changed`` once at the end.
        """
        floor, ceiling = z_range_for(text)
        for w in (self.chk_z_auto, self.spin_z_floor, self.spin_z_ceiling):
            w.blockSignals(True)
        try:
            self.chk_z_auto.setChecked(True)
            self.spin_z_floor.setValue(floor)
            self.spin_z_ceiling.setValue(ceiling)
        finally:
            for w in (self.chk_z_auto, self.spin_z_floor, self.spin_z_ceiling):
                w.blockSignals(False)
        self._sync_axis_enabled()
        self.changed.emit()

    def _sync_axis_enabled(self) -> None:
        for chk, lo, hi in (
            (self.chk_x_auto, self.spin_x_min, self.spin_x_max),
            (self.chk_y_auto, self.spin_y_min, self.spin_y_max),
            (self.chk_z_auto, self.spin_z_floor, self.spin_z_ceiling),
        ):
            manual = not chk.isChecked()
            lo.setEnabled(manual)
            hi.setEnabled(manual)

    # ------------------------------------------------------------------
    def _choose_dir(self) -> None:
        start = self._dir_edit.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", start)
        if path:
            self._dir_edit.setText(path)

    # ------------------------------------------------------------------
    def directory(self) -> str:
        return self._dir_edit.text().strip()

    def export_data(self) -> bool:
        return bool(self._chk_data.isChecked())

    def export_image(self) -> bool:
        return bool(self._chk_image.isChecked())

    def data_format(self) -> str:
        return self._combo_format.currentText()

    # ------------------------------------------------------------------
    def apply_directory(self, path: str) -> None:
        self._dir_edit.setText(str(path or ""))

    def apply_outputs(self, out: BatchOutput) -> None:
        if out is None:
            return
        self._chk_data.setChecked(bool(out.export_data))
        self._chk_image.setChecked(bool(out.export_image))
        idx = self._combo_format.findText(str(out.data_format))
        if idx >= 0:
            self._combo_format.setCurrentIndex(idx)

    def axis_params(self) -> dict:
        return {
            "x_auto": bool(self.chk_x_auto.isChecked()),
            "x_min": float(self.spin_x_min.value()),
            "x_max": float(self.spin_x_max.value()),
            "y_auto": bool(self.chk_y_auto.isChecked()),
            "y_min": float(self.spin_y_min.value()),
            "y_max": float(self.spin_y_max.value()),
            "z_auto": bool(self.chk_z_auto.isChecked()),
            "z_floor": float(self.spin_z_floor.value()),
            "z_ceiling": float(self.spin_z_ceiling.value()),
            "amplitude_mode": (
                "amplitude_db"
                if self.combo_amp_unit.currentText() == "dB"
                else "amplitude"
            ),
        }

    def apply_axis_params(self, params: dict) -> None:
        if not params:
            return
        # Apply combo_amp_unit FIRST under blockSignals so the W2
        # ``_on_amp_unit_changed`` reset handler does NOT fire on
        # programmatic preset loads (§1.5 边界: programmatic setters
        # must round-trip the user's persisted z_floor/z_ceiling/z_auto
        # intact). Apply checkboxes + spins AFTERWARD so the preset's
        # numbers win irrespective of any handler that did slip through.
        if "amplitude_mode" in params:
            raw = str(params.get("amplitude_mode", ""))
            target = "dB" if "db" in raw.lower() else "Linear"
            idx = self.combo_amp_unit.findText(target)
            if idx >= 0:
                self.combo_amp_unit.blockSignals(True)
                try:
                    self.combo_amp_unit.setCurrentIndex(idx)
                finally:
                    self.combo_amp_unit.blockSignals(False)
        for key, widget in (
            ("x_auto", self.chk_x_auto),
            ("y_auto", self.chk_y_auto),
            ("z_auto", self.chk_z_auto),
        ):
            if key in params:
                widget.setChecked(bool(params[key]))
        for key, widget in (
            ("x_min", self.spin_x_min), ("x_max", self.spin_x_max),
            ("y_min", self.spin_y_min), ("y_max", self.spin_y_max),
            ("z_floor", self.spin_z_floor), ("z_ceiling", self.spin_z_ceiling),
        ):
            if key in params:
                try:
                    widget.setValue(float(params[key]))
                except (TypeError, ValueError):
                    pass
        self._sync_axis_enabled()
