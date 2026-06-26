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

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ....batch import BatchOutput
from ...inspector_sections._helpers import _make_axis_settings_group
from ..._axis_defaults import z_range_for


_GENERIC_DB_Z_RANGE = (-80.0, 0.0)
_ORDER_TIME_DB_Z_RANGE = (-50.0, -10.0)
_ORDER_TIME_METHOD = "order_time"
_BATCH_AXIS_LABEL_W = 72

_AXIS_CONTEXTS = {
    "time": {
        "x_label": "时间 (X):",
        "x_unit": "s",
        "x_summary": "全时段",
        "y_label": "幅值 (Y):",
        "y_unit": "",
        "y_summary": "自动范围",
    },
    "fft": {
        "x_label": "频率 (X):",
        "x_unit": "Hz",
        "x_summary": "自动范围",
        "y_label": "幅值 (Y):",
        "y_unit": "",
        "y_summary": "自动范围",
    },
    "fft_time": {
        "x_label": "时间 (X):",
        "x_unit": "s",
        "x_summary": "全时段",
        "y_label": "频率 (Y):",
        "y_unit": "Hz",
        "y_summary": "0 → Nyquist",
    },
    "order_time": {
        "x_label": "时间 (X):",
        "x_unit": "s",
        "x_summary": "全时段",
        "y_label": "阶次 (Y):",
        "y_unit": "",
        "y_summary": "0 → 最大阶次",
    },
}


class OutputPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchOutputPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
QWidget#BatchOutputPanel {
    background-color: #ffffff;
}
""")

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

        axis_group = _make_axis_settings_group(
            self,
            x_label="时间 (X):", x_unit="s",
            x_default_min=0.0, x_default_max=0.0,
            y_label="范围 (Y):", y_unit="",
            y_default_min=0.0, y_default_max=0.0,
            z_default_floor=_GENERIC_DB_Z_RANGE[0],
            z_default_ceiling=_GENERIC_DB_Z_RANGE[1],
            z_default_auto=True,
            x_default_auto=True,
            y_default_auto=True,
            x_auto_summary="全时段",
            y_auto_summary="自动范围",
            z_auto_summary="自动色阶",
        )
        self._widen_axis_label_column(axis_group)
        self._flatten_axis_group_chrome(axis_group)
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
        for chk in (self.chk_x_auto, self.chk_y_auto, self.chk_z_auto):
            chk.toggled.connect(lambda *_: self.changed.emit())
        for spin in (
            self.spin_x_min, self.spin_x_max,
            self.spin_y_min, self.spin_y_max,
            self.spin_z_floor, self.spin_z_ceiling,
        ):
            spin.valueChanged.connect(lambda *_: self.changed.emit())
        self._apply_method_axis_context("fft")
        self._sync_axis_enabled()

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

    def apply_method_defaults(self, method: str) -> None:
        """Apply method-specific output defaults without clobbering edits."""
        self._apply_method_axis_context(method)
        if not self._is_method_default_z_state():
            return
        if method == _ORDER_TIME_METHOD:
            z_auto = False
            z_floor, z_ceiling = _ORDER_TIME_DB_Z_RANGE
        else:
            z_auto = True
            z_floor, z_ceiling = _GENERIC_DB_Z_RANGE
        for w in (self.chk_z_auto, self.spin_z_floor, self.spin_z_ceiling):
            w.blockSignals(True)
        try:
            self.chk_z_auto.setChecked(z_auto)
            self.spin_z_floor.setValue(z_floor)
            self.spin_z_ceiling.setValue(z_ceiling)
        finally:
            for w in (self.chk_z_auto, self.spin_z_floor, self.spin_z_ceiling):
                w.blockSignals(False)
        self._sync_axis_enabled()
        self.changed.emit()

    def _apply_method_axis_context(self, method: str) -> None:
        context = _AXIS_CONTEXTS.get(str(method), _AXIS_CONTEXTS["fft"])
        for axis, suffix_key in (("x", "x_unit"), ("y", "y_unit")):
            suffix = context[suffix_key]
            text = f" {suffix}" if suffix else ""
            for spin_key in ("spin_min", "spin_max"):
                self._axis_row_parts[axis][spin_key].setSuffix(text)
        self._axis_row_parts["x"]["label"].setText(context["x_label"])
        self._axis_row_parts["x"]["summary"].setText(context["x_summary"])
        self._axis_row_parts["y"]["label"].setText(context["y_label"])
        self._axis_row_parts["y"]["summary"].setText(context["y_summary"])

    def _widen_axis_label_column(self, axis_group: QWidget) -> None:
        for parts in self._axis_row_parts.values():
            parts["label"].setMinimumWidth(_BATCH_AXIS_LABEL_W)
            parts["label"].setMaximumWidth(_BATCH_AXIS_LABEL_W)

        header = axis_group.findChild(QWidget, "axisHeaderRow")
        header_layout = header.layout() if header is not None else None
        spacer_item = header_layout.itemAt(0) if header_layout is not None else None
        if spacer_item is not None and spacer_item.spacerItem() is not None:
            spacer_item.spacerItem().changeSize(
                _BATCH_AXIS_LABEL_W,
                0,
                QSizePolicy.Fixed,
                QSizePolicy.Minimum,
            )
            header_layout.invalidate()

    def _flatten_axis_group_chrome(self, axis_group: QWidget) -> None:
        axis_group.setStyleSheet("""
QGroupBox#axisSettingsGroup {
    margin-top: 6px;
    padding: 18px 0 8px 0;
    border: none;
    border-radius: 0;
    background-color: #ffffff;
}
QGroupBox#axisSettingsGroup::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0;
    right: 0;
    padding: 2px 0 6px 0;
    color: #111827;
    font-size: 12px;
    font-weight: 600;
    background-color: transparent;
    border-bottom: 1px solid #dfe5ee;
}
QGroupBox#axisSettingsGroup QWidget#axisRow,
QGroupBox#axisSettingsGroup QWidget#axisRowLine,
QGroupBox#axisSettingsGroup QWidget#axisAutoCell,
QGroupBox#axisSettingsGroup QWidget#axisRangeHost,
QGroupBox#axisSettingsGroup QWidget#axisRangeSummaryPage,
QGroupBox#axisSettingsGroup QWidget#axisManualRangePage,
QGroupBox#axisSettingsGroup QWidget#axisUnitLine,
QGroupBox#axisSettingsGroup QWidget#axisHeaderRow,
QGroupBox#axisSettingsGroup QWidget#axisHeaderRange {
    border: none;
    background-color: transparent;
}
QGroupBox#axisSettingsGroup QLabel[axisHeader="true"] {
    color: #97a1b2;
    font-size: 11px;
    font-weight: 500;
    background-color: transparent;
}
""")

    def _is_method_default_z_state(self) -> bool:
        if self.combo_amp_unit.currentText() != "dB":
            return False
        current = (
            bool(self.chk_z_auto.isChecked()),
            float(self.spin_z_floor.value()),
            float(self.spin_z_ceiling.value()),
        )
        method_defaults = (
            (True, *_GENERIC_DB_Z_RANGE),
            (False, *_ORDER_TIME_DB_Z_RANGE),
        )
        return any(
            current[0] is default[0]
            and abs(current[1] - default[1]) < 1e-9
            and abs(current[2] - default[2]) < 1e-9
            for default in method_defaults
        )

    def _sync_axis_enabled(self) -> None:
        for key in ("x", "y", "z"):
            parts = self._axis_row_parts[key]
            auto = parts["checkbox"].isChecked()
            parts["stack"].setCurrentWidget(
                parts["summary_page"] if auto else parts["manual_page"]
            )
            parts["summary_page"].setVisible(auto)
            parts["manual_page"].setVisible(not auto)
            parts["summary"].setVisible(auto)
            for w in (parts["spin_min"], parts["arrow"], parts["spin_max"]):
                w.setVisible(not auto)
                w.setEnabled(not auto)

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
