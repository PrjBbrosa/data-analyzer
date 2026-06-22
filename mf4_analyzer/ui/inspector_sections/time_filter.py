"""时域滤波控件。FFT 频域滤波参数 + 显示原始/滤波后开关。透明背景。

FFT 频域法天然零相位，故 UI 无「零相位」勾选。容器及所有子控件强制透明背景
（QSS background:transparent + WA_TranslucentBackground + paintEvent 兜底），
避免嵌入到时间范围卡时出现默认灰底。
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox, QCheckBox,
)

from ._helpers import _no_buttons, _fit_field, _pair_field
from ..widgets.compact_spinbox import CompactDoubleSpinBox
from ...signal.filters import FilterSpec

_KIND_MAP = {"低通": "low", "高通": "high", "带通": "band", "带阻": "bandstop"}


class FilterPanel(QWidget):
    filter_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeFilterPanel")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("#timeFilterPanel{background:transparent;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Enable toggle doubles as the section title. Filtering is OFF by
        # default: a freshly-opened inspector must NOT overlay filtered traces
        # on every time-domain plot — the overlay only appears once the user
        # explicitly turns it on (otherwise routine plots double their traces).
        self.chk_enable = QCheckBox("滤波")
        self.chk_enable.setChecked(False)
        self.chk_enable.setStyleSheet(
            "font-weight:600; color:#1f2d3d; background:transparent;"
        )
        root.addWidget(self.chk_enable)

        fl = QFormLayout()
        fl.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fl.setHorizontalSpacing(6)
        fl.setVerticalSpacing(4)
        fl.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._form = fl

        self.combo_kind = QComboBox()
        self.combo_kind.addItems(list(_KIND_MAP))
        fl.addRow("类型:", _fit_field(self.combo_kind))

        # --- single-cutoff row (low / high) ---
        self.spin_cut = _no_buttons(CompactDoubleSpinBox())
        self.spin_cut.setDecimals(1)
        self.spin_cut.setRange(0.0, 1e6)
        self.spin_cut.setSuffix(" Hz")
        self.spin_cut.setValue(100.0)
        self._single_row = _fit_field(self.spin_cut, max_width=120)
        self._single_label = QLabel("截止:")
        fl.addRow(self._single_label, self._single_row)

        # --- dual-cutoff row (band / bandstop) ---
        self.spin_lo = _no_buttons(CompactDoubleSpinBox())
        self.spin_lo.setDecimals(1)
        self.spin_lo.setRange(0.0, 1e6)
        self.spin_lo.setSuffix(" Hz")
        self.spin_lo.setValue(100.0)
        self.spin_hi = _no_buttons(CompactDoubleSpinBox())
        self.spin_hi.setDecimals(1)
        self.spin_hi.setRange(0.0, 1e6)
        self.spin_hi.setSuffix(" Hz")
        self.spin_hi.setValue(2000.0)
        self._band_row = _pair_field(self.spin_lo, "– 上限", self.spin_hi)
        self._band_label = QLabel("下限:")
        fl.addRow(self._band_label, self._band_row)

        self.combo_order = QComboBox()
        self.combo_order.addItems(["2", "4", "6", "8"])
        self.combo_order.setCurrentText("4")
        fl.addRow("阶数:", _fit_field(self.combo_order, max_width=120))
        root.addLayout(fl)

        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(14)
        self.chk_orig = QCheckBox("显示原始")
        self.chk_orig.setChecked(True)
        self.chk_filt = QCheckBox("显示滤波后")
        self.chk_filt.setChecked(True)
        for c in (self.chk_orig, self.chk_filt):
            c.setStyleSheet("background:transparent;")
        row.addWidget(self.chk_orig)
        row.addWidget(self.chk_filt)
        row.addStretch()
        root.addLayout(row)

        # Make every label/field transparent so no default gray surface leaks
        # through when this panel is embedded in the (tinted) time-range card.
        for w in self.findChildren(QLabel):
            existing = w.styleSheet()
            if "background" not in existing:
                w.setStyleSheet(
                    (existing + ";" if existing else "")
                    + "background:transparent;"
                )

        # Initial-state sync BEFORE any toggled signal fires (lesson
        # 2026-04-26-conditional-visibility-init-sync-and-paired-field-children).
        self._sync_rows()
        self.combo_kind.currentTextChanged.connect(self._sync_rows)
        for w in (self.combo_kind, self.combo_order):
            w.currentTextChanged.connect(lambda *_: self.filter_changed.emit())
        for s in (self.spin_cut, self.spin_lo, self.spin_hi):
            s.valueChanged.connect(lambda *_: self.filter_changed.emit())
        for c in (self.chk_enable, self.chk_orig, self.chk_filt):
            c.toggled.connect(lambda *_: self.filter_changed.emit())

    # --- row visibility ------------------------------------------------
    def _is_band(self):
        return _KIND_MAP[self.combo_kind.currentText()] in ("band", "bandstop")

    def _set_row_visible(self, row, label, visible):
        """Toggle a row's wrapper, its label, and the wrapper's direct child
        widgets so per-widget ``isHidden()``/``isVisible()`` stays honest for
        paired-field hosts (lesson: a wrapper-only toggle leaves each inner
        widget's own hidden flag untouched)."""
        row.setVisible(visible)
        label.setVisible(visible)
        for child in row.findChildren(
            QWidget, options=Qt.FindDirectChildrenOnly
        ):
            child.setVisible(visible)

    def _sync_rows(self, *_):
        band = self._is_band()
        self._set_row_visible(self._single_row, self._single_label, not band)
        self._set_row_visible(self._band_row, self._band_label, band)
        self.filter_changed.emit()

    # --- programmatic setters (tests / presets) ------------------------
    def set_kind(self, label):
        self.combo_kind.setCurrentText(label)

    def set_cutoff(self, hz):
        self.spin_cut.setValue(float(hz))

    def set_band(self, lo, hi):
        self.spin_lo.setValue(float(lo))
        self.spin_hi.setValue(float(hi))

    def set_order(self, n):
        self.combo_order.setCurrentText(str(int(n)))

    # --- getters -------------------------------------------------------
    def filter_spec(self):
        kind = _KIND_MAP[self.combo_kind.currentText()]
        order = int(self.combo_order.currentText())
        if kind in ("band", "bandstop"):
            return FilterSpec(
                kind, order=order,
                cutoff_lo=self.spin_lo.value(),
                cutoff_hi=self.spin_hi.value(),
            )
        return FilterSpec(kind, order=order, cutoff=self.spin_cut.value())

    def is_enabled(self):
        return self.chk_enable.isChecked()

    def set_enabled(self, on):
        self.chk_enable.setChecked(bool(on))

    def show_original(self):
        return self.chk_orig.isChecked()

    def show_filtered(self):
        return self.chk_filt.isChecked()
