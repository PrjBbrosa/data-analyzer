"""MainWindow: top-level QMainWindow assembling the application UI."""
import numpy as np
import pandas as pd
from pathlib import Path
from collections import OrderedDict

from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QTimer

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.ticker import MaxNLocator

from ..io import DataLoader, FileData, HAS_ASAMMDF
from ..signal import FFTAnalyzer, OrderAnalyzer
from .canvases import TimeDomainCanvas, PlotCanvas
from .dialogs import ChannelEditorDialog, ExportDialog
from .widgets import StatisticsPanel, MultiFileChannelWidget
from .axis_lock_toolbar import AxisLockBar
from .icons import Icons


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MF4/CSV/Excel 数据分析工具 v5.0 - 多文件支持")
        self.setGeometry(100, 100, 1450, 850);
        self.setMinimumSize(900, 600)
        self.files = OrderedDict();
        self._fc = 0;
        self._active = None
        self._init_ui();
        self._connect()

    def _init_ui(self):
        from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget
        from PyQt5.QtCore import Qt

        from .chart_stack import ChartStack
        from .file_navigator import FileNavigator
        from .inspector import Inspector
        from .toolbar import Toolbar

        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toolbar = Toolbar(self)
        root.addWidget(self.toolbar)

        splitter = QSplitter(Qt.Horizontal, self)
        self.navigator = FileNavigator(self)
        self.chart_stack = ChartStack(self)
        self.inspector = Inspector(self)
        splitter.addWidget(self.navigator)
        splitter.addWidget(self.chart_stack)
        splitter.addWidget(self.inspector)
        splitter.setSizes([220, 920, 260])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        self.navigator.setMinimumWidth(180)
        self.chart_stack.setMinimumWidth(400)
        self.inspector.setMinimumWidth(220)
        root.addWidget(splitter, stretch=1)

        # Compatibility aliases so legacy methods that still reference old
        # widget names compile and run in Phase 1. Each alias is removed in
        # the Phase 2 task that rewrites its consumer method.
        self.canvas_time = self.chart_stack.canvas_time
        self.canvas_fft = self.chart_stack.canvas_fft
        self.canvas_order = self.chart_stack.canvas_order
        self.channel_list = self.navigator.channel_list
        # Phase-1 placeholder shims for widgets that Phase 2 will kill:
        # plot_time / do_fft / do_order_* still read .spin_start / .spin_end /
        # .spin_fs / .combo_sig / .combo_rpm / .spin_xt / .spin_yt / .chk_range
        # / .chk_fft_autoscale etc. Alias them to the Inspector's real widgets
        # once Inspector has them (Phase 2). Until Phase 2 lands, the old
        # widget objects are kept alive as **hidden off-screen children** of
        # MainWindow so existing methods don't AttributeError.
        from PyQt5.QtWidgets import (
            QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QSpinBox, QTabWidget,
        )
        self._legacy_hidden = QWidget(self)
        self._legacy_hidden.setVisible(False)
        self.btn_load = self.toolbar.btn_add
        self.btn_close = self.toolbar.btn_edit   # unused in Phase 1; wired off
        self.btn_close_all = self.toolbar.btn_export  # unused; wired off
        self.btn_plot = self.toolbar.btn_mode_time  # unused in Phase 1
        self.combo_mode = QComboBox(self._legacy_hidden); self.combo_mode.addItems(['Subplot', 'Overlay'])
        self.chk_cursor = QCheckBox(self._legacy_hidden)
        self.chk_dual = QCheckBox(self._legacy_hidden)
        self.btn_reset = self.toolbar.btn_cursor_reset
        self.btn_edit = self.toolbar.btn_edit
        self.btn_export = self.toolbar.btn_export
        self.combo_xaxis = QComboBox(self._legacy_hidden); self.combo_xaxis.addItems(['自动(时间)', '指定通道'])
        self.combo_xaxis_ch = QComboBox(self._legacy_hidden)
        self.edit_xlabel = QLabel("", self._legacy_hidden)
        self.btn_apply_xaxis = QLabel("", self._legacy_hidden)
        self.chk_range = QCheckBox(self._legacy_hidden)
        self.spin_start = QDoubleSpinBox(self._legacy_hidden); self.spin_start.setRange(0, 1e9)
        self.spin_end = QDoubleSpinBox(self._legacy_hidden); self.spin_end.setRange(0, 1e9)
        self.spin_xt = QSpinBox(self._legacy_hidden); self.spin_xt.setRange(3, 30); self.spin_xt.setValue(10)
        self.spin_yt = QSpinBox(self._legacy_hidden); self.spin_yt.setRange(3, 20); self.spin_yt.setValue(6)
        self.combo_sig = QComboBox(self._legacy_hidden)
        self.combo_rpm = QComboBox(self._legacy_hidden); self.combo_rpm.addItem("None", None)
        self.spin_fs = QDoubleSpinBox(self._legacy_hidden); self.spin_fs.setRange(1, 1e6); self.spin_fs.setValue(1000)
        self.btn_rebuild_time = QLabel("", self._legacy_hidden)
        self.spin_rf = QDoubleSpinBox(self._legacy_hidden); self.spin_rf.setRange(0.0001, 10000); self.spin_rf.setValue(1)
        self.combo_win = QComboBox(self._legacy_hidden); self.combo_win.addItems(['hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop'])
        self.combo_nfft = QComboBox(self._legacy_hidden); self.combo_nfft.addItems(['自动', '512', '1024', '2048', '4096', '8192', '16384'])
        self.spin_overlap = QSpinBox(self._legacy_hidden); self.spin_overlap.setRange(0, 90); self.spin_overlap.setValue(50)
        self.btn_fft = QLabel("", self._legacy_hidden)
        self.chk_fft_remark = QCheckBox(self._legacy_hidden)
        self.chk_fft_autoscale = QCheckBox(self._legacy_hidden); self.chk_fft_autoscale.setChecked(True)
        self.spin_mo = QSpinBox(self._legacy_hidden); self.spin_mo.setRange(1, 100); self.spin_mo.setValue(20)
        self.spin_order_res = QDoubleSpinBox(self._legacy_hidden); self.spin_order_res.setRange(0.01, 1.0); self.spin_order_res.setValue(0.1)
        self.combo_order_nfft = QComboBox(self._legacy_hidden); self.combo_order_nfft.addItems(['512', '1024', '2048', '4096', '8192']); self.combo_order_nfft.setCurrentText('1024')
        self.spin_time_res = QDoubleSpinBox(self._legacy_hidden); self.spin_time_res.setRange(0.01, 1.0); self.spin_time_res.setValue(0.05)
        self.spin_rpm_res = QSpinBox(self._legacy_hidden); self.spin_rpm_res.setRange(1, 100); self.spin_rpm_res.setValue(10)
        self.spin_to = QDoubleSpinBox(self._legacy_hidden); self.spin_to.setRange(0.5, 100); self.spin_to.setValue(1)
        self.btn_ot = QLabel("", self._legacy_hidden)
        self.btn_or = QLabel("", self._legacy_hidden)
        self.btn_ok = QLabel("", self._legacy_hidden)
        self.lbl_order_progress = QLabel("", self._legacy_hidden)
        # Existing QLabels used in plot_time's status updates
        self.lbl_info = QLabel("", self._legacy_hidden)
        self.lbl_cursor = QLabel("", self._legacy_hidden)
        self.lbl_dual = QLabel("", self._legacy_hidden)
        # StatisticsPanel legacy alias — the real strip lives on ChartStack
        from .widgets import StatisticsPanel
        self.stats = StatisticsPanel(self._legacy_hidden)
        # old tabs object — only ever .setCurrentIndex(n) is called; create a real hidden one
        self.tabs = QTabWidget(self._legacy_hidden)
        for _ in range(3):
            self.tabs.addTab(QWidget(), "")

        from PyQt5.QtWidgets import QStatusBar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")

    def _connect(self):
        # --- New-module wiring ---
        self.toolbar.file_add_requested.connect(self.load_files)
        self.toolbar.channel_editor_requested.connect(self.open_editor)
        self.toolbar.export_requested.connect(self.export_excel)
        self.toolbar.mode_changed.connect(self._on_mode_changed)
        self.toolbar.cursor_reset_requested.connect(self._reset_cursors)
        self.toolbar.axis_lock_requested.connect(self._show_axis_lock_popover)

        self.navigator.channels_changed.connect(self._ch_changed)
        self.navigator.file_activated.connect(self._on_file_activated)
        self.navigator.file_close_requested.connect(self._on_file_close_requested)
        self.navigator.close_all_requested.connect(self._on_close_all_requested)

        # Canvas cursor signals are owned by ChartStack; MainWindow doesn't
        # need to subscribe (ChartStack updates the pill itself).

        # Inspector signals wire up in Phase 2 when real sections land. In
        # Phase 1, these are no-ops but must exist so Task 2.x edits are
        # minimal additions rather than rewrites.
        self.inspector.plot_time_requested.connect(self.plot_time)
        self.inspector.fft_requested.connect(self.do_fft)
        self.inspector.order_time_requested.connect(self.do_order_time)
        self.inspector.order_rpm_requested.connect(self.do_order_rpm)
        self.inspector.order_track_requested.connect(self.do_order_track)
        self.inspector.xaxis_apply_requested.connect(self._apply_xaxis)
        self.inspector.rebuild_time_requested.connect(self._show_rebuild_popover)
        self.inspector.tick_density_changed.connect(self._update_all_tick_density_pair)
        self.inspector.remark_toggled.connect(self.canvas_fft.set_remark_enabled)
        self.inspector.cursor_mode_changed.connect(self._on_cursor_mode_changed)
        self.inspector.plot_mode_changed.connect(self._on_plot_mode_changed)
        self.inspector.signal_changed.connect(self._on_inspector_signal_changed)

        # Custom X axis state (unchanged)
        self._custom_xlabel = None
        self._custom_xaxis_fid = None
        self._custom_xaxis_ch = None
        self._plot_mode = 'subplot'
        self._axis_lock_widget = None

    def _on_mode_changed(self, mode):
        self.chart_stack.set_mode(mode)
        self.inspector.set_mode(mode)
        self.toolbar.set_enabled_for_mode(mode, has_file=bool(self.files))
        # §6.2 auto re-plot on entering time mode with checked channels
        if mode == 'time' and self.files and self.navigator.get_checked_channels():
            self.plot_time()

    def _on_cursor_mode_changed(self, mode):
        self.canvas_time.set_cursor_visible(mode != 'off')
        self.canvas_time.set_dual_cursor_mode(mode == 'dual')

    def _on_plot_mode_changed(self, mode):
        self._plot_mode = mode
        self.plot_time()

    def _update_all_tick_density_pair(self, xt, yt):
        self.canvas_time.set_tick_density(xt, yt)
        from matplotlib.ticker import MaxNLocator
        for ax in self.canvas_fft.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
        self.canvas_fft.draw_idle()
        for ax in self.canvas_order.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
        self.canvas_order.draw_idle()

    def _show_axis_lock_popover(self, anchor):
        # Phase 1 placeholder — Phase 3 replaces with drawers/axis_lock_popover.py.
        # Canvas is the single source of truth for axis-lock state (§12.1).
        cur = self.canvas_time._axis_lock or 'none'
        next_state = {'none': 'x', 'x': 'y', 'y': 'none'}[cur]
        self.canvas_time.set_axis_lock(next_state)
        self.statusBar.showMessage(f"轴锁: {next_state}")

    def _show_rebuild_popover(self, anchor, mode='fft'):
        # Phase 1 placeholder — Phase 3 replaces.
        # `mode` identifies which Inspector section emitted (needed for signal→file resolution).
        self.rebuild_time_axis()

    def _on_inspector_signal_changed(self, mode, data):
        """Fs auto-sync per §6.3: spin_fs reflects selected signal's source file Fs."""
        if not data:
            return
        fid, _ch = data
        if fid not in self.files:
            return
        fs = self.files[fid].fs
        if mode == 'fft':
            self.inspector.fft_ctx.set_fs(fs)
        elif mode == 'order':
            self.inspector.order_ctx.set_fs(fs)

    def _on_file_activated(self, fid):
        self._active = fid
        self._update_info()

    def _on_file_close_requested(self, fid):
        self._close(fid)

    def _on_close_all_requested(self):
        # Navigator already confirmed; skip the second confirm here
        self._close_all_confirmed()

    def _close_all_confirmed(self):
        for fid in list(self.files.keys()):
            del self.files[fid]
            self.navigator.remove_file(fid)
        self._active = None
        self._update_info()
        self._reset_plot_state(scope='all')
        self.statusBar.showMessage("已关闭全部")

    def _on_xaxis_mode_changed(self, idx):
        """横坐标模式切换"""
        use_channel = (idx == 1)
        self.combo_xaxis_ch.setEnabled(use_channel)
        if use_channel:
            # 填充可用通道
            self.combo_xaxis_ch.clear()
            for fid, fd in self.files.items():
                px = f"[{fd.short_name}] "
                for ch in fd.channels:
                    self.combo_xaxis_ch.addItem(px + ch, (fid, ch))

    def _apply_xaxis(self):
        """应用横坐标设置"""
        mode = self.combo_xaxis.currentIndex()
        if mode == 0:
            # 自动(时间)
            self._custom_xlabel = self.edit_xlabel.text().strip() or None
            self._custom_xaxis_fid = None
            self._custom_xaxis_ch = None
        else:
            # 指定通道
            idx = self.combo_xaxis_ch.currentIndex()
            if idx < 0:
                QMessageBox.warning(self, "提示", "请选择横坐标通道")
                return
            data = self.combo_xaxis_ch.itemData(idx)
            if data:
                self._custom_xaxis_fid, self._custom_xaxis_ch = data
            self._custom_xlabel = self.edit_xlabel.text().strip() or self._custom_xaxis_ch

        # 重新绘图
        self.plot_time()
        self.statusBar.showMessage(f"横坐标已更新: {self._custom_xlabel or 'Time (s)'}")

    def _update_all_tick_density(self):
        """更新所有图表的刻度密度"""
        xt, yt = self.spin_xt.value(), self.spin_yt.value()
        self.canvas_time.set_tick_density(xt, yt)
        # FFT图
        for ax in self.canvas_fft.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
        self.canvas_fft.draw_idle()
        # Order图
        for ax in self.canvas_order.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
        self.canvas_order.draw_idle()

    def rebuild_time_axis(self):
        """根据当前Fs重建活动文件的时间轴"""
        if not self._active or self._active not in self.files:
            QMessageBox.warning(self, "提示", "请先选择一个文件")
            return

        fd = self.files[self._active]
        fs = self.spin_fs.value()
        old_max = fd.time_array[-1] if len(fd.time_array) > 0 else 0

        fd.rebuild_time_axis(fs)
        new_max = fd.time_array[-1] if len(fd.time_array) > 0 else 0

        # 更新范围控件
        self.spin_start.setRange(0, new_max)
        self.spin_end.setRange(0, new_max)
        self.spin_end.setValue(new_max)

        # 重新绘图
        self.plot_time()

        self.statusBar.showMessage(f"时间轴已重建: {fd.short_name} | Fs={fs}Hz | 时长: {old_max:.1f}s → {new_max:.3f}s")

    def _dual_changed(self, st):
        en = (st == Qt.Checked);
        self.canvas_time.set_dual_cursor_mode(en);
        self.lbl_dual.setVisible(en)
        if en and not self.chk_cursor.isChecked(): self.chk_cursor.setChecked(True)

    def _reset_cursors(self):
        self.canvas_time._ax = self.canvas_time._bx = None;
        self.canvas_time._placing = 'A'
        self.canvas_time._refresh = True;
        self.canvas_time.draw_idle()
        self.lbl_dual.setText("");
        self.lbl_cursor.setText("游标已重置")

    def load_files(self):
        fps, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "All (*.mf4 *.csv *.xlsx *.xls)")
        for fp in fps: self._load_one(fp)

    def _load_one(self, fp):
        try:
            self.statusBar.showMessage(f"加载: {fp}");
            QApplication.processEvents()
            p = Path(fp);
            ext = p.suffix.lower()
            if ext == '.mf4':
                if not HAS_ASAMMDF: QMessageBox.critical(self, "错误", "asammdf 未安装"); return
                data, chs, units = DataLoader.load_mf4(fp)
            elif ext in ('.xlsx', '.xls'):
                data, chs, units = DataLoader.load_excel(fp)
            else:
                data, chs, units = DataLoader.load_csv(fp)
            fid = f"f{self._fc}";
            self._fc += 1
            fd = FileData(fp, data, chs, units, len(self.files));
            self.files[fid] = fd
            self.navigator.add_file(fid, fd)
            self._update_combos()
            if fd.time_array is not None and len(fd.time_array):
                self.spin_start.setRange(0, max(self.spin_end.maximum(), fd.time_array[-1]))
                self.spin_end.setRange(0, max(self.spin_end.maximum(), fd.time_array[-1]))
                if len(self.files) == 1: self.spin_end.setValue(fd.time_array[-1])
            self.channel_list.check_first_channel(fid)
            QTimer.singleShot(100, self.plot_time)
            self._update_info()
            self.statusBar.showMessage(f"✅ 已加载: {p.name} ({len(data)} 行) | 共 {len(self.files)} 文件")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def close_active(self):
        if self._active: self._close(self._active)

    def _close(self, fid):
        if fid not in self.files: return
        del self.files[fid]
        self.navigator.remove_file(fid)
        self._active = self.navigator._active_fid  # navigator picks fallback
        self._update_info()
        self._reset_plot_state(scope='file')
        self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")

    def close_all(self):
        """Legacy entry; navigator's kebab path is canonical. Not bound to UI."""
        self._close_all_confirmed()

    def _update_info(self):
        if not self.files: self.lbl_info.setText("未加载文件"); return
        self.lbl_info.setText("\n".join(
            [f"{'▶' if fid == self._active else '  '} {fd.short_name}: {len(fd.data)}" for fid, fd in
             self.files.items()]))

    def _reset_plot_state(self, scope='file'):
        """Wipe plot-related state after a file close. scope in {'file', 'all'}.
        Kept scope-parameterised for future divergence; today both paths share code."""
        self.canvas_time.full_reset()
        self.canvas_fft.full_reset()
        self.canvas_order.full_reset()
        self.axis_lock.reset()
        self.stats.update_stats({})
        self.lbl_cursor.setText("")
        self.lbl_dual.setText("")
        self.lbl_dual.setVisible(False)
        self.chk_cursor.blockSignals(True); self.chk_cursor.setChecked(False); self.chk_cursor.blockSignals(False)
        self.chk_dual.blockSignals(True); self.chk_dual.setChecked(False); self.chk_dual.blockSignals(False)

        # Invalidate custom X axis pointer if the source file is gone
        if self._custom_xaxis_fid is not None and self._custom_xaxis_fid not in self.files:
            self._custom_xaxis_fid = None
            self._custom_xaxis_ch = None
            self._custom_xlabel = None
            self.combo_xaxis.blockSignals(True)
            self.combo_xaxis.setCurrentIndex(0)
            self.combo_xaxis.blockSignals(False)
            self.combo_xaxis_ch.setEnabled(False)

        self.combo_xaxis_ch.clear()
        self._update_combos()  # rebuilds combo_sig/combo_rpm from current self.files

        if not self.files:
            self.spin_start.blockSignals(True); self.spin_start.setValue(0); self.spin_start.blockSignals(False)
            self.spin_end.blockSignals(True); self.spin_end.setValue(0); self.spin_end.blockSignals(False)
            self.spin_fs.blockSignals(True); self.spin_fs.setValue(1000); self.spin_fs.blockSignals(False)
        else:
            max_t = max((fd.time_array[-1] for fd in self.files.values() if len(fd.time_array) > 0), default=0)
            if self.spin_end.value() > max_t: self.spin_end.setValue(max_t)
            if self.spin_start.value() > max_t: self.spin_start.setValue(0)
            if self._active in self.files:
                self.spin_fs.blockSignals(True); self.spin_fs.setValue(self.files[self._active].fs); self.spin_fs.blockSignals(False)

        # re-fill combo_xaxis_ch if still in channel mode
        if self.combo_xaxis.currentIndex() == 1:
            self._on_xaxis_mode_changed(1)
            if self._custom_xaxis_fid is not None and self._custom_xaxis_ch is not None:
                target = (self._custom_xaxis_fid, self._custom_xaxis_ch)
                for i in range(self.combo_xaxis_ch.count()):
                    if self.combo_xaxis_ch.itemData(i) == target:
                        self.combo_xaxis_ch.blockSignals(True)
                        self.combo_xaxis_ch.setCurrentIndex(i)
                        self.combo_xaxis_ch.blockSignals(False)
                        break

        self.plot_time()  # re-renders remaining channels or clears if empty

    def _update_combos(self):
        self.combo_sig.clear();
        self.combo_rpm.clear();
        self.combo_rpm.addItem("None", None)
        for fid, fd in self.files.items():
            px = f"[{fd.short_name}] "
            for ch in fd.get_signal_channels():
                self.combo_sig.addItem(px + ch, (fid, ch));
                self.combo_rpm.addItem(px + ch, (fid, ch))

    def _ch_changed(self):
        if self.files and self.tabs.currentIndex() == 0: self.plot_time()

    def _on_span(self, xmin, xmax):
        self.spin_start.setValue(xmin);
        self.spin_end.setValue(xmax);
        self.chk_range.setChecked(True)
        st = self.canvas_time.get_statistics(time_range=(xmin, xmax))
        if st: self.stats.update_stats(st)

    def plot_time(self):
        if not self.files: self.canvas_time.clear(); self.canvas_time.draw(); self.stats.update_stats({}); return
        checked = self.channel_list.get_checked_channels()
        if not checked: self.canvas_time.clear(); self.canvas_time.draw(); self.stats.update_stats({}); return

        mode = 'subplot' if self.combo_mode.currentIndex() == 0 else 'overlay'
        if mode == 'overlay' and len(checked) > 5:
            ans = QMessageBox.question(
                self, "确认",
                f"overlay 下 {len(checked)} 个通道会产生 {len(checked)} 根 Y 轴，右侧可能拥挤。继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return

        # 获取自定义横坐标数据
        custom_x = None
        if self._custom_xaxis_fid and self._custom_xaxis_ch:
            if self._custom_xaxis_fid in self.files:
                xfd = self.files[self._custom_xaxis_fid]
                if self._custom_xaxis_ch in xfd.data.columns:
                    custom_x = xfd.data[self._custom_xaxis_ch].values.copy()

        data = [];
        st = {}
        for fid, ch, color in checked:
            fd = self.channel_list.get_file_data(fid)
            if fd is None or ch not in fd.data.columns: continue

            # 使用自定义横坐标或默认时间轴
            if custom_x is not None and len(custom_x) == len(fd.data):
                t = custom_x.copy()
            else:
                t = fd.time_array.copy()

            sig = fd.data[ch].values.copy()
            unit = fd.channel_units.get(ch, '');
            name = fd.get_prefixed_channel(ch)
            if self.chk_range.isChecked(): m = (t >= self.spin_start.value()) & (t <= self.spin_end.value()); t, sig = \
            t[m], sig[m]
            if len(sig) == 0: continue
            data.append((name, True, t, sig, color, unit))
            st[name] = {'min': np.min(sig), 'max': np.max(sig), 'mean': np.mean(sig), 'rms': np.sqrt(np.mean(sig ** 2)),
                        'std': np.std(sig), 'p2p': np.ptp(sig), 'unit': unit}
        if not data: self.canvas_time.clear(); self.canvas_time.draw(); self.stats.update_stats({}); return

        xlabel = self._custom_xlabel or 'Time (s)'
        self.canvas_time.plot_channels(data, mode, xlabel=xlabel)
        self.canvas_time.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
        self.canvas_time.enable_span_selector(self._on_span);
        self.stats.update_stats(st);
        self.tabs.setCurrentIndex(0)
        self.statusBar.showMessage(f"绘制: {len(checked)} 通道, {len(set(fid for fid, _, _ in checked))} 文件")

    def open_editor(self):
        if not self.files or not self._active or self._active not in self.files: QMessageBox.warning(self, "提示",
                                                                                                     "请先加载文件"); return
        fd = self.files[self._active];
        dlg = ChannelEditorDialog(self, fd)
        if dlg.exec_() == QDialog.Accepted:
            for name, (arr, unit) in dlg.new_channels.items(): fd.data[name] = arr; fd.channels.append(name);
            fd.channel_units[name] = unit
            for name in dlg.removed_channels:
                if name in fd.data.columns: fd.data = fd.data.drop(columns=[name])
                if name in fd.channels: fd.channels.remove(name)
                fd.channel_units.pop(name, None)
            self.channel_list.remove_file(self._active);
            self.channel_list.add_file(self._active, fd);
            self._update_combos()
            self.statusBar.showMessage(f"编辑: +{len(dlg.new_channels)} -{len(dlg.removed_channels)}");
            self.plot_time()

    def export_excel(self):
        if not self.files or not self._active: QMessageBox.warning(self, "提示", "请先加载文件"); return
        fd = self.files[self._active];
        chs = fd.get_signal_channels()
        if not chs: return
        dlg = ExportDialog(self, chs)
        if dlg.exec_() == QDialog.Accepted:
            sel = dlg.get_selected()
            if not sel: return
            fp, _ = QFileDialog.getSaveFileName(self, "保存", "", "Excel (*.xlsx)")
            if not fp: return
            try:
                df = pd.DataFrame()
                if dlg.chk_time.isChecked() and fd.time_array is not None: df['Time'] = fd.time_array
                for ch in sel:
                    if ch in fd.data.columns: df[ch] = fd.data[ch].values
                if dlg.chk_range.isChecked() and fd.time_array is not None:
                    m = (fd.time_array >= self.spin_start.value()) & (fd.time_array <= self.spin_end.value());
                    df = df.loc[m].reset_index(drop=True)
                df.to_excel(fp, index=False, engine='openpyxl')
                QMessageBox.information(self, "成功", f"导出: {len(df)} 行 × {len(df.columns)} 列")
            except Exception as e:
                QMessageBox.critical(self, "错误", str(e))

    def _get_sig(self):
        idx = self.combo_sig.currentIndex()
        if idx < 0: return None, None, None
        d = self.combo_sig.itemData(idx)
        if not d: return None, None, None
        fid, ch = d
        if fid not in self.files: return None, None, None
        fd = self.files[fid]
        if ch not in fd.data.columns: return None, None, None
        return fd.time_array, fd.data[ch].values, fd.fs

    def _get_rpm(self, n):
        idx = self.combo_rpm.currentIndex()
        if idx <= 0: QMessageBox.warning(self, "提示", "请选择转速信号"); return None
        d = self.combo_rpm.itemData(idx)
        if not d: return None
        fid, ch = d
        if fid not in self.files: return None
        fd = self.files[fid]
        if ch not in fd.data.columns: return None
        rpm = fd.data[ch].values.copy() * self.spin_rf.value()
        if self.chk_range.isChecked() and fd.time_array is not None:
            m = (fd.time_array >= self.spin_start.value()) & (fd.time_array <= self.spin_end.value());
            rpm = rpm[m]
        if len(rpm) != n: QMessageBox.warning(self, "提示", f"长度不匹配 ({n} vs {len(rpm)})"); return None
        return rpm

    @staticmethod
    def _fft_auto_xlim(freq, amp):
        """自适应计算FFT频率范围，取整到 1/2/5/10/20/50/100... 序列"""
        if len(freq) < 2 or len(amp) < 2:
            return freq[-1] if len(freq) else 100
        # 找到包含99%能量的频率
        cumulative = np.cumsum(amp ** 2)
        total = cumulative[-1]
        if total < 1e-20:
            return freq[-1]
        # 99%能量截止
        idx_99 = np.searchsorted(cumulative, total * 0.99)
        f_cutoff = freq[min(idx_99, len(freq) - 1)]
        # 给一些余量 (1.2x)
        f_cutoff *= 1.2
        # 取整到好看的数值序列: 1, 2, 5, 10, 20, 50, 100, 200, 500 ...
        nice_vals = []
        for exp in range(-1, 7):
            for m in [1, 2, 5]:
                nice_vals.append(m * 10 ** exp)
        nice_vals.sort()
        for nv in nice_vals:
            if nv >= f_cutoff:
                return nv
        return freq[-1]

    def do_fft(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 10: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.chk_range.isChecked() and t is not None:
            m = (t >= self.spin_start.value()) & (t <= self.spin_end.value());
            sig = sig[m]
        fs = self.spin_fs.value();
        win = self.combo_win.currentText()

        # 获取NFFT
        nfft_text = self.combo_nfft.currentText()
        nfft = None if nfft_text == '自动' else int(nfft_text)
        overlap = self.spin_overlap.value() / 100.0

        try:
            self.statusBar.showMessage('计算FFT...');
            QApplication.processEvents()

            if nfft and overlap > 0:
                # 使用平均FFT (Welch方法)
                freq, amp, psd = FFTAnalyzer.compute_averaged_fft(sig, fs, win, nfft, overlap)
            else:
                freq, amp = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
                _, psd = FFTAnalyzer.compute_psd(sig, fs, win, nfft)

            self.canvas_fft.clear()

            # 自适应频率范围计算
            if self.chk_fft_autoscale.isChecked():
                x_max = self._fft_auto_xlim(freq, amp)
            else:
                x_max = fs / 2

            psd_db = 10 * np.log10(psd + 1e-12)

            ax1 = self.canvas_fft.fig.add_subplot(2, 1, 1)
            ax1.plot(freq, amp, '#1f77b4', lw=0.8);
            ax1.set_xlabel('Frequency (Hz)');
            ax1.set_ylabel('幅值')
            ax1.set_title(f'FFT - {self.combo_sig.currentText()} (窗:{win}, NFFT:{nfft or "auto"})');
            ax1.grid(True, alpha=0.25, ls='--');
            ax1.set_xlim(0, x_max)
            ax2 = self.canvas_fft.fig.add_subplot(2, 1, 2)
            ax2.plot(freq, psd_db, '#d62728', lw=0.8);
            ax2.set_xlabel('Frequency (Hz)');
            ax2.set_ylabel('PSD (dB)')
            ax2.set_title('功率谱密度');
            ax2.grid(True, alpha=0.25, ls='--');
            ax2.set_xlim(0, x_max)

            # 存储曲线数据用于remark吸附
            self.canvas_fft.store_line_data(0, freq, amp)
            self.canvas_fft.store_line_data(1, freq, psd_db)

            self.canvas_fft.fig.tight_layout()
            self.canvas_fft.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
            self.canvas_fft.draw();
            self.tabs.setCurrentIndex(1)
            pi = np.argmax(amp[1:]) + 1;
            self.statusBar.showMessage(f'FFT峰值: {freq[pi]:.2f} Hz ({amp[pi]:.4f})')
        except Exception as e:
            QMessageBox.critical(self, 'FFT错误', str(e))

    def _order_progress(self, current, total):
        """Order分析进度回调"""
        pct = int(current / total * 100) if total > 0 else 0
        self.lbl_order_progress.setText(f"{pct}%")
        QApplication.processEvents()

    def do_order_time(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.chk_range.isChecked() and t is not None:
            m = (t >= self.spin_start.value()) & (t <= self.spin_end.value());
            t, sig = t[m], sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.spin_fs.value()

        # 获取参数
        nfft = int(self.combo_order_nfft.currentText())
        order_res = self.spin_order_res.value()
        time_res = self.spin_time_res.value()
        max_ord = self.spin_mo.value()

        try:
            self.statusBar.showMessage('计算时间-阶次谱...');
            self.lbl_order_progress.setText("0%")
            QApplication.processEvents()

            tb, ords, om = OrderAnalyzer.compute_order_spectrum_time_based(
                sig, rpm, t, fs, max_ord, order_res, time_res, nfft, self._order_progress
            )

            self.canvas_order.clear();
            ax = self.canvas_order.fig.add_subplot(1, 1, 1)
            im = ax.pcolormesh(tb, ords, om.T, shading='gouraud', cmap='jet')
            ax.set_xlabel('Time (s)');
            ax.set_ylabel('Order')
            ax.set_title(f'时间-阶次谱 - {self.combo_sig.currentText()} (分辨率:{order_res})')
            self.canvas_order.fig.colorbar(im, ax=ax, label='RMS')
            self.canvas_order.fig.tight_layout()
            self.canvas_order.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
            self.canvas_order.draw();
            self.tabs.setCurrentIndex(2)
            self.lbl_order_progress.setText("")
            self.statusBar.showMessage(f'完成 | {len(tb)} 时间点 × {len(ords)} 阶次')
        except Exception as e:
            self.lbl_order_progress.setText("")
            QMessageBox.critical(self, '错误', str(e))

    def do_order_rpm(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.chk_range.isChecked() and t is not None:
            m = (t >= self.spin_start.value()) & (t <= self.spin_end.value());
            sig = sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.spin_fs.value()

        # 获取参数
        nfft = int(self.combo_order_nfft.currentText())
        order_res = self.spin_order_res.value()
        rpm_res = self.spin_rpm_res.value()
        max_ord = self.spin_mo.value()

        try:
            self.statusBar.showMessage('计算转速-阶次谱...');
            self.lbl_order_progress.setText("0%")
            QApplication.processEvents()

            ords, rb, om = OrderAnalyzer.compute_order_spectrum(
                sig, rpm, fs, max_ord, rpm_res, order_res, nfft, self._order_progress
            )

            self.canvas_order.clear();
            ax = self.canvas_order.fig.add_subplot(1, 1, 1)
            im = ax.pcolormesh(ords, rb, om, shading='gouraud', cmap='jet')
            ax.set_xlabel('Order');
            ax.set_ylabel('RPM')
            ax.set_title(f'转速-阶次谱 - {self.combo_sig.currentText()} (阶次分辨率:{order_res}, RPM分辨率:{rpm_res})')
            self.canvas_order.fig.colorbar(im, ax=ax, label='Amplitude')
            self.canvas_order.fig.tight_layout()
            self.canvas_order.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
            self.canvas_order.draw();
            self.tabs.setCurrentIndex(2)
            self.lbl_order_progress.setText("")
            self.statusBar.showMessage(f'转速-阶次谱完成 | {len(rb)} RPM × {len(ords)} 阶次')
        except Exception as e:
            self.lbl_order_progress.setText("")
            QMessageBox.critical(self, '错误', str(e))

    def do_order_track(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.chk_range.isChecked() and t is not None:
            m = (t >= self.spin_start.value()) & (t <= self.spin_end.value());
            sig = sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.spin_fs.value();
        to = self.spin_to.value()
        nfft = int(self.combo_order_nfft.currentText())

        try:
            self.statusBar.showMessage(f'跟踪阶次 {to}...');
            QApplication.processEvents()
            rt, oa = OrderAnalyzer.extract_order_track(sig, rpm, fs, to, nfft)
            self.canvas_order.clear()
            ax1 = self.canvas_order.fig.add_subplot(2, 1, 1)
            ax1.plot(rt, oa, '#1f77b4', lw=1);
            ax1.set_xlabel('RPM');
            ax1.set_ylabel('幅值')
            ax1.set_title(f'阶次 {to} 跟踪 - {self.combo_sig.currentText()}');
            ax1.grid(True, alpha=0.25, ls='--')
            ax2 = self.canvas_order.fig.add_subplot(2, 1, 2)
            ax2.plot(rpm, '#2ca02c', lw=0.5);
            ax2.set_xlabel('Sample');
            ax2.set_ylabel('RPM')
            ax2.set_title('转速曲线');
            ax2.grid(True, alpha=0.25, ls='--')
            self.canvas_order.fig.tight_layout()
            self.canvas_order.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
            self.canvas_order.draw();
            self.tabs.setCurrentIndex(2)
            self.statusBar.showMessage(f'阶次 {to} 跟踪完成')
        except Exception as e:
            QMessageBox.critical(self, '错误', str(e))
