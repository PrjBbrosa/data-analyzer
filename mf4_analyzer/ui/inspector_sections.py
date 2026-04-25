"""Inspector section widgets (Phase 2).

PersistentTop hosts the always-visible xaxis/range/tick-density controls.
TimeContextual / FFTContextual / OrderContextual host the mode-specific
parameter cards. Public getter/setter names are a contract consumed by
MainWindow's analysis methods — do not rename without updating callers.
"""
import json

from PyQt5.QtCore import QSettings, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .icons import Icons


_PRESET_ORG = "MF4Analyzer"
_PRESET_APP = "DataAnalyzer"


def _preset_settings():
    return QSettings(_PRESET_ORG, _PRESET_APP)


class PresetBar(QWidget):
    """Three-slot preset bar: load / save row, persisted via QSettings.

    Storage format (JSON per slot)::

        {"name": "<user-provided name>", "params": {...}}

    Legacy slots written by an earlier build store the params dict at the
    top level (no ``name``/``params`` envelope); :meth:`_read` upgrades them
    on first read so subsequent rename / save round-trips work uniformly.

    The owning contextual supplies ``collect_fn`` (returns a JSON-serializable
    params dict) and ``apply_fn`` (restore params from such a dict). The bar
    emits ``acknowledged(level, msg)`` so the host can surface a toast.

    Renaming / clearing are reachable via right-click on the load button.
    """

    SLOTS = (1, 2, 3)
    NAME_MAX_LEN = 12
    acknowledged = pyqtSignal(str, str)  # level, message

    def __init__(self, kind, collect_fn, apply_fn, parent=None):
        super().__init__(parent)
        self._kind = kind  # 'fft' or 'order'
        self._collect = collect_fn
        self._apply = apply_fn

        gl = QGridLayout(self)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setHorizontalSpacing(6)
        gl.setVerticalSpacing(4)
        self._load_btns = {}
        self._save_btns = {}
        for i, n in enumerate(self.SLOTS):
            ld = QPushButton(self._default_name(n), self)
            ld.setProperty("role", "preset-load")
            ld.setProperty("filled", "false")
            ld.setContextMenuPolicy(Qt.CustomContextMenu)
            ld.clicked.connect(lambda _=False, slot=n: self._load(slot))
            ld.customContextMenuRequested.connect(
                lambda pos, slot=n: self._show_menu(slot, pos)
            )
            sv = QPushButton(f"存为 {n}", self)
            sv.setProperty("role", "preset-save")
            sv.setToolTip(f"把当前参数保存到「{self._default_name(n)}」槽位")
            sv.clicked.connect(lambda _=False, slot=n: self._save(slot))
            gl.addWidget(ld, 0, i)
            gl.addWidget(sv, 1, i)
            self._load_btns[n] = ld
            self._save_btns[n] = sv
        self._refresh_states()

    # ---- naming helpers ----
    @staticmethod
    def _default_name(slot):
        return f"配置 {slot}"

    # ---- persistence helpers ----
    def _key(self, slot):
        return f"{self._kind}/preset/{slot}"

    def _read(self, slot):
        """Return ``(name, params)`` or ``None`` for an empty slot.

        Tolerates the legacy flat-dict format by treating the whole payload
        as ``params`` and synthesising a default name.
        """
        raw = _preset_settings().value(self._key(slot), "")
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(obj, dict):
            return None
        if 'params' in obj and isinstance(obj['params'], dict):
            name = obj.get('name') or self._default_name(slot)
            return str(name), obj['params']
        # legacy flat dict — entire payload is params
        return self._default_name(slot), obj

    def _write(self, slot, name, params):
        payload = {"name": name, "params": params}
        _preset_settings().setValue(self._key(slot), json.dumps(payload))

    def _delete(self, slot):
        _preset_settings().remove(self._key(slot))

    def _refresh_states(self):
        for n in self.SLOTS:
            entry = self._read(n)
            btn = self._load_btns[n]
            if entry is None:
                btn.setText(self._default_name(n))
                btn.setEnabled(False)
                btn.setProperty("filled", "false")
                btn.setToolTip(
                    "（空槽位 — 用下方“存为”按钮保存当前参数；"
                    "保存后可右键重命名 / 清空）"
                )
            else:
                name, params = entry
                btn.setText(name)
                btn.setEnabled(True)
                btn.setProperty("filled", "true")
                btn.setToolTip(self._format_summary(name, params))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _format_summary(self, name, params):
        if not isinstance(params, dict):
            return name
        items = []
        for k, v in params.items():
            if isinstance(v, float):
                items.append(f"{k}={v:g}")
            elif isinstance(v, bool):
                items.append(f"{k}={'是' if v else '否'}")
            else:
                items.append(f"{k}={v}")
        return f"{name}\n{', '.join(items)}\n（右键可重命名 / 清空）"

    # ---- actions ----
    def _save(self, slot):
        try:
            params = self._collect()
        except Exception as e:  # pragma: no cover — defensive
            self.acknowledged.emit("error", f"保存失败: {e}")
            return
        existing = self._read(slot)
        name = existing[0] if existing else self._default_name(slot)
        self._write(slot, name, params)
        self._refresh_states()
        self.acknowledged.emit("success", f"已保存到「{name}」")

    def _load(self, slot):
        entry = self._read(slot)
        if entry is None:
            self.acknowledged.emit("warning", f"「{self._default_name(slot)}」是空的")
            return
        name, params = entry
        try:
            self._apply(params)
        except Exception as e:
            self.acknowledged.emit("error", f"加载失败: {e}")
            return
        self.acknowledged.emit("success", f"已加载「{name}」")

    def _rename(self, slot):
        entry = self._read(slot)
        if entry is None:
            # Should never reach here — menu disables rename on empty slots —
            # but guard anyway.
            self.acknowledged.emit("warning", "请先保存参数再重命名")
            return
        current, params = entry
        new_name, ok = QInputDialog.getText(
            self,
            "重命名配置",
            f"为槽位 {slot} 输入名称（最长 {self.NAME_MAX_LEN} 字符）：",
            QLineEdit.Normal,
            current,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            self.acknowledged.emit("warning", "名称不能为空")
            return
        if len(new_name) > self.NAME_MAX_LEN:
            new_name = new_name[: self.NAME_MAX_LEN]
        self._write(slot, new_name, params)
        self._refresh_states()
        self.acknowledged.emit("success", f"已重命名为「{new_name}」")

    def _clear(self, slot):
        entry = self._read(slot)
        if entry is None:
            return
        name = entry[0]
        ans = QMessageBox.question(
            self,
            "清空配置",
            f"确定清空「{name}」？该操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._delete(slot)
        self._refresh_states()
        self.acknowledged.emit("info", f"已清空「{name}」")

    def _show_menu(self, slot, pos):
        btn = self._load_btns[slot]
        menu = QMenu(self)
        act_rename = menu.addAction("重命名…")
        act_clear = menu.addAction("清空")
        entry = self._read(slot)
        # Both actions need a saved preset to operate on.
        act_rename.setEnabled(entry is not None)
        act_clear.setEnabled(entry is not None)
        chosen = menu.exec_(btn.mapToGlobal(pos))
        if chosen is act_rename:
            self._rename(slot)
        elif chosen is act_clear:
            self._clear(slot)


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
        root.setSpacing(10)

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
        root.setSpacing(10)

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
        self.setObjectName("fftContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

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

        g = QGroupBox("预设配置")
        gl = QVBoxLayout(g)
        gl.setSpacing(4)
        self.preset_bar = PresetBar(
            'fft', self._collect_preset, self._apply_preset, parent=self,
        )
        gl.addWidget(self.preset_bar)
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

    def _collect_preset(self):
        return dict(
            window=self.combo_win.currentText(),
            nfft=self.combo_nfft.currentText(),
            overlap=self.spin_overlap.value(),
            autoscale=self.chk_autoscale.isChecked(),
            remark=self.chk_remark.isChecked(),
        )

    def _apply_preset(self, d):
        if 'window' in d:
            i = self.combo_win.findText(str(d['window']))
            if i >= 0:
                self.combo_win.setCurrentIndex(i)
        if 'nfft' in d:
            i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'overlap' in d:
            self.spin_overlap.setValue(int(d['overlap']))
        if 'autoscale' in d:
            self.chk_autoscale.setChecked(bool(d['autoscale']))
        if 'remark' in d:
            self.chk_remark.setChecked(bool(d['remark']))

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
        self.setObjectName("orderContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

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

        g = QGroupBox("预设配置")
        gl = QVBoxLayout(g)
        gl.setSpacing(4)
        self.preset_bar = PresetBar(
            'order', self._collect_preset, self._apply_preset, parent=self,
        )
        gl.addWidget(self.preset_bar)
        root.addWidget(g)

        self.lbl_progress = QLabel("")
        root.addWidget(self.lbl_progress)
        root.addStretch()

        self.btn_ot.clicked.connect(self.order_time_requested)
        self.btn_or.clicked.connect(self.order_rpm_requested)
        self.btn_ok.clicked.connect(self.order_track_requested)

    def _collect_preset(self):
        return dict(
            rpm_factor=self.spin_rf.value(),
            max_order=self.spin_mo.value(),
            order_res=self.spin_order_res.value(),
            time_res=self.spin_time_res.value(),
            rpm_res=self.spin_rpm_res.value(),
            nfft=self.combo_nfft.currentText(),
            target_order=self.spin_to.value(),
        )

    def _apply_preset(self, d):
        if 'rpm_factor' in d:
            self.spin_rf.setValue(float(d['rpm_factor']))
        if 'max_order' in d:
            self.spin_mo.setValue(int(d['max_order']))
        if 'order_res' in d:
            self.spin_order_res.setValue(float(d['order_res']))
        if 'time_res' in d:
            self.spin_time_res.setValue(float(d['time_res']))
        if 'rpm_res' in d:
            self.spin_rpm_res.setValue(int(d['rpm_res']))
        if 'nfft' in d:
            i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'target_order' in d:
            self.spin_to.setValue(float(d['target_order']))

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
