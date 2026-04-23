"""Inspector section widgets (Phase 2 incremental).

PersistentTop, TimeContextual, and FFTContextual implemented;
OrderContextual remains a Phase 1 stub — it will be replaced in the
next commit.
"""
from PyQt5.QtCore import pyqtSignal
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class PersistentTop(QWidget):
    """Xaxis / Range / Ticks sections (always visible)."""

    xaxis_apply_requested = pyqtSignal()
    tick_density_changed = pyqtSignal(int, int)
    range_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ------- Xaxis group -------
        g = QGroupBox("横坐标")
        gl = QVBoxLayout(g)
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("来源:"))
        self.combo_xaxis = QComboBox()
        self.combo_xaxis.addItems(['自动(时间)', '指定通道'])
        h1.addWidget(self.combo_xaxis)
        gl.addLayout(h1)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("通道:"))
        self._combo_xaxis_ch = QComboBox()
        self._combo_xaxis_ch.setEnabled(False)
        h2.addWidget(self._combo_xaxis_ch)
        gl.addLayout(h2)
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("标签:"))
        self.edit_xlabel = QLineEdit()
        self.edit_xlabel.setPlaceholderText("Time (s)")
        h3.addWidget(self.edit_xlabel)
        gl.addLayout(h3)
        self.btn_apply_xaxis = QPushButton("应用")
        gl.addWidget(self.btn_apply_xaxis)
        root.addWidget(g)

        # ------- Range group -------
        g = QGroupBox("范围")
        gl = QVBoxLayout(g)
        self.chk_range = QCheckBox("使用选定范围")
        gl.addWidget(self.chk_range)
        h = QHBoxLayout()
        h.addWidget(QLabel("开始:"))
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setDecimals(3)
        self.spin_start.setSuffix(" s")
        self.spin_start.setRange(0, 1e9)
        h.addWidget(self.spin_start)
        gl.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(QLabel("结束:"))
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setDecimals(3)
        self.spin_end.setSuffix(" s")
        self.spin_end.setRange(0, 1e9)
        h.addWidget(self.spin_end)
        gl.addLayout(h)
        root.addWidget(g)

        # ------- Tick density group -------
        g = QGroupBox("刻度")
        fl = QFormLayout(g)
        self.spin_xt = QSpinBox()
        self.spin_xt.setRange(3, 30)
        self.spin_xt.setValue(10)
        fl.addRow("X:", self.spin_xt)
        self.spin_yt = QSpinBox()
        self.spin_yt.setRange(3, 20)
        self.spin_yt.setValue(6)
        fl.addRow("Y:", self.spin_yt)
        root.addWidget(g)

        self._wire()

    def _wire(self):
        self.combo_xaxis.currentIndexChanged.connect(
            lambda i: self._combo_xaxis_ch.setEnabled(i == 1)
        )
        self.btn_apply_xaxis.clicked.connect(self.xaxis_apply_requested)
        self.spin_xt.valueChanged.connect(self._emit_ticks)
        self.spin_yt.valueChanged.connect(self._emit_ticks)
        self.chk_range.toggled.connect(lambda _: self.range_changed.emit())
        self.spin_start.valueChanged.connect(lambda _: self.range_changed.emit())
        self.spin_end.valueChanged.connect(lambda _: self.range_changed.emit())

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
    """Time-domain contextual: plot-mode segmented, cursor segmented, plot button."""

    plot_time_requested = pyqtSignal()
    cursor_mode_changed = pyqtSignal(str)  # 'off' | 'single' | 'dual'
    plot_mode_changed = pyqtSignal(str)    # 'subplot' | 'overlay'

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        g = QGroupBox("绘图模式")
        gl = QHBoxLayout(g)
        self._btn_subplot = QPushButton("Subplot")
        self._btn_overlay = QPushButton("Overlay")
        for b in (self._btn_subplot, self._btn_overlay):
            b.setCheckable(True)
            gl.addWidget(b)
        self._btn_subplot.setChecked(True)
        self._plot_mode = 'subplot'
        self._btn_subplot.clicked.connect(lambda: self.set_plot_mode('subplot'))
        self._btn_overlay.clicked.connect(lambda: self.set_plot_mode('overlay'))
        root.addWidget(g)

        g = QGroupBox("游标")
        gl = QHBoxLayout(g)
        self._cursor_buttons = {}
        for label, key in [('Off', 'off'), ('Single', 'single'), ('Dual', 'dual')]:
            b = QPushButton(label)
            b.setCheckable(True)
            gl.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self.set_cursor_mode(k))
            self._cursor_buttons[key] = b
        self._cursor_mode = 'single'
        self._cursor_buttons['single'].setChecked(True)
        root.addWidget(g)

        self.btn_plot = QPushButton("▶ 绘图")
        root.addWidget(self.btn_plot)
        self.btn_plot.clicked.connect(self.plot_time_requested)
        root.addStretch()

    def set_cursor_mode(self, mode):
        self._cursor_mode = mode
        for k, b in self._cursor_buttons.items():
            b.setChecked(k == mode)
        self.cursor_mode_changed.emit(mode)

    def cursor_mode(self):
        return self._cursor_mode

    def set_plot_mode(self, mode):
        self._plot_mode = mode
        self._btn_subplot.setChecked(mode == 'subplot')
        self._btn_overlay.setChecked(mode == 'overlay')
        self.plot_mode_changed.emit(mode)

    def plot_mode(self):
        return self._plot_mode


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
        self.combo_sig = QComboBox()
        fl.addRow("信号:", self.combo_sig)
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fs_row = QHBoxLayout()
        fs_row.addWidget(self.spin_fs)
        self.btn_rebuild = QPushButton("⏱")
        self.btn_rebuild.setMaximumWidth(30)
        self.btn_rebuild.setToolTip("重建时间轴")
        fs_row.addWidget(self.btn_rebuild)
        fl.addRow("Fs:", fs_row)
        root.addWidget(g)

        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        self.combo_win = QComboBox()
        self.combo_win.addItems(
            ['hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop']
        )
        fl.addRow("窗函数:", self.combo_win)
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(
            ['自动', '512', '1024', '2048', '4096', '8192', '16384']
        )
        fl.addRow("NFFT:", self.combo_nfft)
        self.spin_overlap = QSpinBox()
        self.spin_overlap.setRange(0, 90)
        self.spin_overlap.setValue(50)
        self.spin_overlap.setSuffix(" %")
        fl.addRow("重叠:", self.spin_overlap)
        root.addWidget(g)

        g = QGroupBox("选项")
        gl = QVBoxLayout(g)
        self.chk_autoscale = QCheckBox("自适应频率范围")
        self.chk_autoscale.setChecked(True)
        gl.addWidget(self.chk_autoscale)
        self.chk_remark = QCheckBox("点击标注")
        gl.addWidget(self.chk_remark)
        root.addWidget(g)

        self.btn_fft = QPushButton("▶ 计算 FFT")
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
    order_time_requested = pyqtSignal()
    order_rpm_requested = pyqtSignal()
    order_track_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    signal_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("[order-contextual stub]", self))
