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
from ..widgets.pill_switch import PillSwitch, PillSwitchLabel
from ...signal.filters import FilterSpec

_KIND_MAP = {"低通": "low", "高通": "high", "带通": "band", "带阻": "bandstop"}


class FilterPanel(QWidget):
    filter_changed = pyqtSignal()
    # Live display toggles for the already-plotted chart. ``original_visibility_changed``
    # / ``filtered_visibility_changed`` carry the new checked state so the host can
    # call setVisible on the existing curve items WITHOUT a re-plot (秒生效，不重绘).
    original_visibility_changed = pyqtSignal(bool)
    filtered_visibility_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeFilterPanel")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("#timeFilterPanel{background:transparent;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Section title row: bold 「滤波」 label on the left, a pill toggle pinned
        # to the right (same visual as the GPU-render switch). Filtering is OFF
        # by default: a freshly-opened inspector must NOT overlay filtered traces
        # on every time-domain plot — the overlay only appears once the user
        # explicitly turns it on (otherwise routine plots double their traces).
        # The pill replaces the old checkbox so it is harder to flip by a stray
        # click; the title text stays clickable for a larger hit target.
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._enable_switch = PillSwitch(
            self, object_name="filterEnableSwitch", accessible_name="滤波"
        )
        self._enable_switch.setChecked(False)
        self._title_label = PillSwitchLabel(
            "滤波", self._enable_switch, self, object_name="filterEnableLabel"
        )
        self._title_label.setStyleSheet(
            "font-weight:600; color:#1f2d3d; background:transparent;"
        )
        title_row.addWidget(self._title_label, 0)
        title_row.addStretch(1)
        title_row.addWidget(self._enable_switch, 0)
        root.addLayout(title_row)

        # All filter parameters live in one container so a single
        # setEnabled(False) greys out 类型/截止/阶数/显示开关 together when
        # filtering is off (Qt propagates the disabled palette to children).
        self._settings = QWidget(self)
        self._settings.setObjectName("timeFilterSettings")
        self._settings.setAttribute(Qt.WA_TranslucentBackground, True)
        settings_lay = QVBoxLayout(self._settings)
        settings_lay.setContentsMargins(0, 0, 0, 0)
        settings_lay.setSpacing(4)
        root.addWidget(self._settings)

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
        # Keep the three filter editors on one field-column datum.  A short
        # 120px cap makes the cutoff and order controls trail-align while the
        # kind combo fills the field, producing visibly staggered left edges.
        self._single_row = _fit_field(self.spin_cut)
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
        fl.addRow("阶数:", _fit_field(self.combo_order))
        settings_lay.addLayout(fl)

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
        settings_lay.addLayout(row)

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
        # The enable pill re-emits filter_changed (read on the next 「绘图」) AND
        # greys out the settings block when off. Sync the initial (off) state
        # before wiring so no spurious toggled fires during construction.
        self._apply_enabled_state()
        self._enable_switch.toggled.connect(lambda *_: self.filter_changed.emit())
        self._enable_switch.toggled.connect(self._apply_enabled_state)
        # 显示原始/显示滤波后 are LIVE display toggles: they emit a dedicated
        # signal the host wires to setVisible on existing curves (秒生效，不重绘).
        # They intentionally do NOT go through filter_changed (which is read on
        # the next 「绘图」 submit) so unchecking takes effect immediately.
        self.chk_orig.toggled.connect(self.original_visibility_changed.emit)
        self.chk_filt.toggled.connect(self.filtered_visibility_changed.emit)

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
        return self._enable_switch.isChecked()

    def set_enabled(self, on):
        self._enable_switch.setChecked(bool(on))

    def _apply_enabled_state(self, *_):
        """Grey out the whole settings block when filtering is off — the enable
        pill is the only live control until the user turns filtering on."""
        self._settings.setEnabled(self._enable_switch.isChecked())

    def show_original(self):
        return self.chk_orig.isChecked()

    def show_filtered(self):
        return self.chk_filt.isChecked()
