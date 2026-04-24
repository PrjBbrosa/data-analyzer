"""Inspector section widgets (Phase 2).

PersistentTop hosts the always-visible xaxis/range/tick-density controls.
TimeContextual / FFTContextual / OrderContextual host the mode-specific
parameter cards. Public getter/setter names are a contract consumed by
MainWindow's analysis methods — do not rename without updating callers.
"""
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .icons import Icons


def _configure_form(form):
    form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignTop)
    form.setHorizontalSpacing(8)
    form.setVerticalSpacing(8)


def _fit_field(widget):
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return widget


class PersistentTop(QWidget):
    """Xaxis / Range / Ticks sections (always visible)."""

    xaxis_apply_requested = pyqtSignal()
    tick_density_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ------- Xaxis group -------
        g = QGroupBox("横坐标")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.combo_xaxis = QComboBox()
        self.combo_xaxis.addItems(['自动(时间)', '指定通道'])
        fl.addRow("来源:", _fit_field(self.combo_xaxis))
        self._combo_xaxis_ch = QComboBox()
        self._combo_xaxis_ch.setEnabled(False)
        fl.addRow("通道:", _fit_field(self._combo_xaxis_ch))
        self.edit_xlabel = QLineEdit()
        self.edit_xlabel.setPlaceholderText("Time (s)")
        fl.addRow("标签:", _fit_field(self.edit_xlabel))
        self.btn_apply_xaxis = QPushButton("应用")
        self.btn_apply_xaxis.setProperty("role", "primary")
        fl.addRow(self.btn_apply_xaxis)
        root.addWidget(g)

        # ------- Range group -------
        g = QGroupBox("范围")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.chk_range = QCheckBox("使用选定范围")
        fl.addRow(self.chk_range)
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setDecimals(3)
        self.spin_start.setSuffix(" s")
        self.spin_start.setRange(0, 1e9)
        fl.addRow("开始:", _fit_field(self.spin_start))
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setDecimals(3)
        self.spin_end.setSuffix(" s")
        self.spin_end.setRange(0, 1e9)
        fl.addRow("结束:", _fit_field(self.spin_end))
        root.addWidget(g)

        # ------- Tick density group (§6.1 ▸ 刻度) -------
        g = QGroupBox("刻度")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.spin_xt = QSpinBox()
        self.spin_xt.setRange(3, 30)
        self.spin_xt.setValue(10)
        fl.addRow("X:", _fit_field(self.spin_xt))
        self.spin_yt = QSpinBox()
        self.spin_yt.setRange(3, 20)
        self.spin_yt.setValue(6)
        fl.addRow("Y:", _fit_field(self.spin_yt))
        root.addWidget(g)

        self._wire()

    def _wire(self):
        self.combo_xaxis.currentIndexChanged.connect(
            lambda i: self._combo_xaxis_ch.setEnabled(i == 1)
        )
        self.btn_apply_xaxis.clicked.connect(self.xaxis_apply_requested)
        self.spin_xt.valueChanged.connect(self._emit_ticks)
        self.spin_yt.valueChanged.connect(self._emit_ticks)

    def _emit_ticks(self):
        self.tick_density_changed.emit(self.spin_xt.value(), self.spin_yt.value())

    # ---- public getters/setters used by MainWindow ----
    def xaxis_mode(self):
        return 'channel' if self.combo_xaxis.currentIndex() == 1 else 'time'

    def set_xaxis_mode(self, mode):
        self.combo_xaxis.setCurrentIndex(1 if mode == 'channel' else 0)

    def xaxis_channel_data(self):
        """Return (fid, channel) tuple or None."""
        if self.combo_xaxis.currentIndex() != 1:
            return None
        return self._combo_xaxis_ch.currentData()

    def xaxis_label(self):
        return self.edit_xlabel.text().strip()

    def set_xaxis_candidates(self, candidates):
        """candidates: list of (display_text, (fid, ch)) tuples."""
        self._combo_xaxis_ch.clear()
        for text, data in candidates:
            self._combo_xaxis_ch.addItem(text, data)

    def range_enabled(self):
        return self.chk_range.isChecked()

    def range_values(self):
        return (self.spin_start.value(), self.spin_end.value())

    def set_range_from_span(self, xmin, xmax):
        self.spin_start.setValue(xmin)
        self.spin_end.setValue(xmax)
        self.chk_range.setChecked(True)

    def set_range_limits(self, lo, hi):
        for sp in (self.spin_start, self.spin_end):
            sp.setRange(lo, hi)

    def tick_density(self):
        return (self.spin_xt.value(), self.spin_yt.value())


class TimeContextual(QWidget):
    """Time-domain contextual: just the manual replot button.

    Plot-mode and cursor-mode controls have been relocated to the chart
    card toolbar (see chart_stack.TimeChartCard).
    """

    plot_time_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        self.btn_plot = QPushButton("绘图")
        self.btn_plot.setIcon(Icons.plot())
        self.btn_plot.setIconSize(QSize(16, 16))
        self.btn_plot.setProperty("role", "primary")
        root.addWidget(self.btn_plot)
        self.btn_plot.clicked.connect(self.plot_time_requested)
        root.addStretch()


class FFTContextual(QWidget):
    """FFT contextual: signal/Fs/params/options + compute button."""

    fft_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    remark_toggled = pyqtSignal(bool)
    signal_changed = pyqtSignal(object)  # emits (fid, ch) or None

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        g = QGroupBox("分析信号")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.combo_sig = QComboBox()
        fl.addRow("信号:", _fit_field(self.combo_sig))
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fs_row = QHBoxLayout()
        fs_row.addWidget(_fit_field(self.spin_fs))
        self.btn_rebuild = QPushButton("")
        self.btn_rebuild.setIcon(Icons.rebuild_time())
        self.btn_rebuild.setIconSize(QSize(16, 16))
        self.btn_rebuild.setMaximumWidth(30)
        self.btn_rebuild.setProperty("role", "tool")
        self.btn_rebuild.setToolTip("重建时间轴")
        fs_row.addWidget(self.btn_rebuild)
        fl.addRow("Fs:", fs_row)
        root.addWidget(g)

        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.combo_win = QComboBox()
        self.combo_win.addItems(
            ['hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop']
        )
        fl.addRow("窗函数:", _fit_field(self.combo_win))
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(
            ['自动', '512', '1024', '2048', '4096', '8192', '16384']
        )
        fl.addRow("NFFT:", _fit_field(self.combo_nfft))
        self.spin_overlap = QSpinBox()
        self.spin_overlap.setRange(0, 90)
        self.spin_overlap.setValue(50)
        self.spin_overlap.setSuffix(" %")
        fl.addRow("重叠:", _fit_field(self.spin_overlap))
        root.addWidget(g)

        g = QGroupBox("选项")
        gl = QVBoxLayout(g)
        self.chk_autoscale = QCheckBox("自适应频率范围")
        self.chk_autoscale.setChecked(True)
        gl.addWidget(self.chk_autoscale)
        self.chk_remark = QCheckBox("点击标注")
        gl.addWidget(self.chk_remark)
        root.addWidget(g)

        self.btn_fft = QPushButton("计算 FFT")
        self.btn_fft.setIcon(Icons.mode_fft())
        self.btn_fft.setIconSize(QSize(16, 16))
        self.btn_fft.setProperty("role", "primary")
        root.addWidget(self.btn_fft)
        root.addStretch()

        self.btn_fft.clicked.connect(self.fft_requested)
        self.btn_rebuild.clicked.connect(
            lambda: self.rebuild_time_requested.emit(self.btn_rebuild)
        )
        self.chk_remark.toggled.connect(self.remark_toggled)
        # §6.3 Fs rule: spin_fs reflects selected signal's source file Fs.
        # MainWindow will call set_fs via the signal_changed relay.

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    def set_signal_candidates(self, candidates):
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        for text, data in candidates:
            self.combo_sig.addItem(text, data)
        self.combo_sig.blockSignals(False)
        try:
            self.combo_sig.currentIndexChanged.disconnect(self._on_sig_index_changed)
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)
        self._on_sig_index_changed()  # emit for newly-populated default

    def current_signal(self):
        return self.combo_sig.currentData()

    def get_params(self):
        nfft_text = self.combo_nfft.currentText()
        return dict(
            window=self.combo_win.currentText(),
            nfft=None if nfft_text == '自动' else int(nfft_text),
            overlap=self.spin_overlap.value() / 100.0,
            autoscale=self.chk_autoscale.isChecked(),
            remark=self.chk_remark.isChecked(),
        )

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(fs)
        self.spin_fs.blockSignals(False)


class OrderContextual(QWidget):
    """Order-analysis contextual: source/params/3 compute btns + tracking sub-group."""

    order_time_requested = pyqtSignal()
    order_rpm_requested = pyqtSignal()
    order_track_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)  # anchor widget
    signal_changed = pyqtSignal(object)  # (fid, ch) tuple or None

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        g = QGroupBox("信号源")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.combo_sig = QComboBox()
        fl.addRow("信号:", _fit_field(self.combo_sig))
        self.combo_rpm = QComboBox()
        fl.addRow("转速:", _fit_field(self.combo_rpm))
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fs_row = QHBoxLayout()
        fs_row.addWidget(_fit_field(self.spin_fs))
        self.btn_rebuild = QPushButton("")
        self.btn_rebuild.setIcon(Icons.rebuild_time())
        self.btn_rebuild.setIconSize(QSize(16, 16))
        self.btn_rebuild.setMaximumWidth(30)
        self.btn_rebuild.setProperty("role", "tool")
        self.btn_rebuild.setToolTip("重建时间轴")
        self.btn_rebuild.clicked.connect(
            lambda: self.rebuild_time_requested.emit(self.btn_rebuild)
        )
        fs_row.addWidget(self.btn_rebuild)
        fl.addRow("Fs:", fs_row)
        self.spin_rf = QDoubleSpinBox()
        self.spin_rf.setRange(0.0001, 10000)
        self.spin_rf.setDecimals(4)
        self.spin_rf.setValue(1)
        fl.addRow("RPM系数:", _fit_field(self.spin_rf))
        root.addWidget(g)

        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.spin_mo = QSpinBox()
        self.spin_mo.setRange(1, 100)
        self.spin_mo.setValue(20)
        fl.addRow("最大阶次:", _fit_field(self.spin_mo))
        self.spin_order_res = QDoubleSpinBox()
        self.spin_order_res.setRange(0.01, 1.0)
        self.spin_order_res.setValue(0.1)
        self.spin_order_res.setSingleStep(0.05)
        fl.addRow("阶次分辨率:", _fit_field(self.spin_order_res))
        self.spin_time_res = QDoubleSpinBox()
        self.spin_time_res.setRange(0.01, 1.0)
        self.spin_time_res.setValue(0.05)
        self.spin_time_res.setSuffix(" s")
        fl.addRow("时间分辨率:", _fit_field(self.spin_time_res))
        self.spin_rpm_res = QSpinBox()
        self.spin_rpm_res.setRange(1, 100)
        self.spin_rpm_res.setValue(10)
        self.spin_rpm_res.setSuffix(" rpm")
        fl.addRow("RPM分辨率:", _fit_field(self.spin_rpm_res))
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(['512', '1024', '2048', '4096', '8192'])
        self.combo_nfft.setCurrentText('1024')
        fl.addRow("FFT点数:", _fit_field(self.combo_nfft))
        root.addWidget(g)

        two_btns = QHBoxLayout()
        self.btn_ot = QPushButton("时间-阶次")
        self.btn_ot.setProperty("role", "primary")
        self.btn_or = QPushButton("转速-阶次")
        self.btn_or.setProperty("role", "primary")
        two_btns.addWidget(self.btn_ot)
        two_btns.addWidget(self.btn_or)
        root.addLayout(two_btns)

        g = QGroupBox("阶次跟踪")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.spin_to = QDoubleSpinBox()
        self.spin_to.setRange(0.5, 100)
        self.spin_to.setValue(1)
        fl.addRow("目标阶次:", _fit_field(self.spin_to))
        self.btn_ok = QPushButton("阶次跟踪")
        self.btn_ok.setProperty("role", "primary")
        fl.addRow(self.btn_ok)
        root.addWidget(g)

        self.lbl_progress = QLabel("")
        root.addWidget(self.lbl_progress)
        root.addStretch()

        self.btn_ot.clicked.connect(self.order_time_requested)
        self.btn_or.clicked.connect(self.order_rpm_requested)
        self.btn_ok.clicked.connect(self.order_track_requested)

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    def set_signal_candidates(self, candidates):
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        for text, data in candidates:
            self.combo_sig.addItem(text, data)
        self.combo_sig.blockSignals(False)
        try:
            self.combo_sig.currentIndexChanged.disconnect(self._on_sig_index_changed)
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)
        self._on_sig_index_changed()

    def set_rpm_candidates(self, candidates):
        self.combo_rpm.clear()
        self.combo_rpm.addItem("None", None)
        for text, data in candidates:
            self.combo_rpm.addItem(text, data)

    def current_signal(self):
        return self.combo_sig.currentData()

    def current_rpm(self):
        return self.combo_rpm.currentData()

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(fs)
        self.spin_fs.blockSignals(False)

    def rpm_factor(self):
        return self.spin_rf.value()

    def get_params(self):
        return dict(
            max_order=self.spin_mo.value(),
            order_res=self.spin_order_res.value(),
            time_res=self.spin_time_res.value(),
            rpm_res=self.spin_rpm_res.value(),
            nfft=int(self.combo_nfft.currentText()),
        )

    def target_order(self):
        return self.spin_to.value()

    def set_progress(self, text):
        self.lbl_progress.setText(text)
