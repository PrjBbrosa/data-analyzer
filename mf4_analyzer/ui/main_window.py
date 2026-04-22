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
        cw = QWidget();
        self.setCentralWidget(cw)
        ml = QHBoxLayout(cw);
        ml.setContentsMargins(5, 5, 5, 5)
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(self._left());
        sp.addWidget(self._right());
        sp.setSizes([320, 1080])
        ml.addWidget(sp)
        self.statusBar = QStatusBar();
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready - 支持同时打开多个文件进行对比分析")

    def _left(self):
        scroll = QScrollArea();
        scroll.setWidgetResizable(True);
        scroll.setMinimumWidth(290);
        scroll.setMaximumWidth(400)
        p = QWidget();
        lay = QVBoxLayout(p);
        lay.setSpacing(5)

        g = QGroupBox("📂 文件管理");
        gl = QVBoxLayout(g)
        br = QHBoxLayout()
        self.btn_load = QPushButton("➕ 添加");
        self.btn_load.setStyleSheet("font-weight:bold;background:#2196F3;color:white;");
        br.addWidget(self.btn_load)
        self.btn_close = QPushButton("✖ 关闭");
        self.btn_close.setStyleSheet("background:#f44336;color:white;");
        br.addWidget(self.btn_close)
        self.btn_close_all = QPushButton("全部");
        self.btn_close_all.setMaximumWidth(50);
        br.addWidget(self.btn_close_all)
        gl.addLayout(br)
        self.file_tabs = QTabWidget();
        self.file_tabs.setTabsClosable(True);
        self.file_tabs.setMaximumHeight(80);
        gl.addWidget(self.file_tabs)
        self.lbl_info = QLabel("未加载文件");
        self.lbl_info.setStyleSheet("color:#666;font-size:9px;");
        gl.addWidget(self.lbl_info)
        lay.addWidget(g)

        g = QGroupBox("通道选择");
        gl = QVBoxLayout(g)
        self.channel_list = MultiFileChannelWidget()
        self.channel_list.setMinimumHeight(280)  # 确保能显示6-10个通道
        gl.addWidget(self.channel_list)
        ml2 = QHBoxLayout();
        ml2.addWidget(QLabel("模式:"))
        self.combo_mode = QComboBox();
        self.combo_mode.addItems(['Subplot', 'Overlay']);
        ml2.addWidget(self.combo_mode);
        gl.addLayout(ml2)
        self.btn_plot = QPushButton("📈 绘图");
        self.btn_plot.setStyleSheet("font-weight:bold;");
        gl.addWidget(self.btn_plot)
        ch = QHBoxLayout()
        self.chk_cursor = QCheckBox("游标");
        ch.addWidget(self.chk_cursor)
        self.chk_dual = QCheckBox("双游标");
        ch.addWidget(self.chk_dual)
        self.btn_reset = QPushButton("重置");
        self.btn_reset.setMaximumWidth(45);
        ch.addWidget(self.btn_reset);
        ch.addStretch();
        gl.addLayout(ch)
        bh = QHBoxLayout()
        self.btn_edit = QPushButton("🔧 编辑");
        self.btn_edit.setStyleSheet("background:#FF9800;color:white;");
        bh.addWidget(self.btn_edit)
        self.btn_export = QPushButton("📥 导出");
        self.btn_export.setStyleSheet("background:#4CAF50;color:white;");
        bh.addWidget(self.btn_export)
        gl.addLayout(bh);
        lay.addWidget(g)


        # 横坐标设置
        g = QGroupBox("横坐标");
        gl3 = QVBoxLayout(g)
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("来源:"))
        self.combo_xaxis = QComboBox();
        self.combo_xaxis.addItems(['自动(时间)', '指定通道']);
        h1.addWidget(self.combo_xaxis)
        gl3.addLayout(h1)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("通道:"))
        self.combo_xaxis_ch = QComboBox();
        self.combo_xaxis_ch.setEnabled(False);
        h2.addWidget(self.combo_xaxis_ch)
        gl3.addLayout(h2)
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("标签:"))
        self.edit_xlabel = QLineEdit();
        self.edit_xlabel.setPlaceholderText("Time (s)");
        self.edit_xlabel.setMaximumWidth(100);
        h3.addWidget(self.edit_xlabel)
        gl3.addLayout(h3)
        self.btn_apply_xaxis = QPushButton("应用");
        self.btn_apply_xaxis.setMaximumWidth(60);
        gl3.addWidget(self.btn_apply_xaxis)
        lay.addWidget(g)


        g = QGroupBox("范围");
        gl2 = QVBoxLayout(g)
        self.chk_range = QCheckBox("使用选定范围");
        gl2.addWidget(self.chk_range)
        h1 = QHBoxLayout();
        h1.addWidget(QLabel("开始:"))
        self.spin_start = QDoubleSpinBox();
        self.spin_start.setDecimals(3);
        self.spin_start.setSuffix(" s");
        h1.addWidget(self.spin_start);
        gl2.addLayout(h1)
        h2 = QHBoxLayout();
        h2.addWidget(QLabel("结束:"))
        self.spin_end = QDoubleSpinBox();
        self.spin_end.setDecimals(3);
        self.spin_end.setSuffix(" s");
        h2.addWidget(self.spin_end);
        gl2.addLayout(h2)
        lay.addWidget(g)

        g = QGroupBox("刻度");
        fl = QFormLayout(g)
        self.spin_xt = QSpinBox();
        self.spin_xt.setRange(3, 30);
        self.spin_xt.setValue(10);
        fl.addRow("X:", self.spin_xt)
        self.spin_yt = QSpinBox();
        self.spin_yt.setRange(3, 20);
        self.spin_yt.setValue(6);
        fl.addRow("Y:", self.spin_yt)
        lay.addWidget(g)


        g = QGroupBox("分析信号");
        fl = QFormLayout(g)
        self.combo_sig = QComboBox();
        fl.addRow("信号:", self.combo_sig)
        self.combo_rpm = QComboBox();
        fl.addRow("转速:", self.combo_rpm)
        self.spin_fs = QDoubleSpinBox();
        self.spin_fs.setRange(1, 1e6);
        self.spin_fs.setValue(1000);
        self.spin_fs.setSuffix(" Hz");
        fl.addRow("Fs:", self.spin_fs)
        # 时间轴重建按钮
        self.btn_rebuild_time = QPushButton("🔄 重建时间轴");
        self.btn_rebuild_time.setToolTip("根据Fs重新生成当前文件的时间轴")
        fl.addRow(self.btn_rebuild_time)
        h = QHBoxLayout();
        h.addWidget(QLabel("RPM系数:"))
        self.spin_rf = QDoubleSpinBox();
        self.spin_rf.setRange(0.0001, 10000);
        self.spin_rf.setValue(1);
        self.spin_rf.setDecimals(4);
        h.addWidget(self.spin_rf);
        fl.addRow(h)
        lay.addWidget(g)

        lay.addStretch();
        scroll.setWidget(p);
        return scroll

    def _right(self):
        p = QWidget();
        lay = QVBoxLayout(p);
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()

        tt = QWidget();
        tl = QVBoxLayout(tt);
        tl.setContentsMargins(2, 2, 2, 2)
        self.canvas_time = TimeDomainCanvas(self);
        self.toolbar_time = NavigationToolbar(self.canvas_time, self)
        self.lbl_cursor = QLabel("");
        self.lbl_cursor.setStyleSheet("background:#1e1e1e;color:#0f0;padding:2px;font-family:monospace;font-size:15px;")
        self.lbl_dual = QLabel("");
        self.lbl_dual.setStyleSheet(
            "background:#0d1117;color:#58a6ff;padding:2px;font-family:monospace;font-size:15px;");
        self.lbl_dual.setWordWrap(True);
        self.lbl_dual.setVisible(False)
        tl.addWidget(self.toolbar_time);
        tl.addWidget(self.lbl_cursor);
        tl.addWidget(self.lbl_dual);
        tl.addWidget(self.canvas_time, stretch=1)
        self.stats = StatisticsPanel();
        tl.addWidget(self.stats)
        self.tabs.addTab(tt, "📈 时域")

        ft = QWidget();
        fl = QVBoxLayout(ft);
        fl.setContentsMargins(2, 2, 2, 2)
        fc = QHBoxLayout()
        fc.addWidget(QLabel("窗函数:"))
        self.combo_win = QComboBox();
        self.combo_win.addItems(['hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop']);
        fc.addWidget(self.combo_win)
        fc.addWidget(QLabel("FFT点数:"))
        self.combo_nfft = QComboBox();
        self.combo_nfft.addItems(['自动', '512', '1024', '2048', '4096', '8192', '16384']);
        fc.addWidget(self.combo_nfft)
        fc.addWidget(QLabel("重叠:"))
        self.spin_overlap = QSpinBox();
        self.spin_overlap.setRange(0, 90);
        self.spin_overlap.setValue(50);
        self.spin_overlap.setSuffix("%");
        fc.addWidget(self.spin_overlap)
        self.btn_fft = QPushButton("▶ FFT");
        self.btn_fft.setStyleSheet("font-weight:bold;");
        fc.addWidget(self.btn_fft)
        self.chk_fft_remark = QCheckBox("标注")
        self.chk_fft_remark.setToolTip("左键点击曲线添加标注，右键删除标注")
        fc.addWidget(self.chk_fft_remark)
        self.chk_fft_autoscale = QCheckBox("自适应")
        self.chk_fft_autoscale.setToolTip("自动匹配有效频率范围")
        self.chk_fft_autoscale.setChecked(True)
        fc.addWidget(self.chk_fft_autoscale)
        fc.addStretch();
        fl.addLayout(fc)
        self.canvas_fft = PlotCanvas(self);
        self.toolbar_fft = NavigationToolbar(self.canvas_fft, self)
        fl.addWidget(self.toolbar_fft);
        fl.addWidget(self.canvas_fft, stretch=1)
        self.tabs.addTab(ft, "📊 FFT")

        ot = QWidget();
        ol = QVBoxLayout(ot);
        ol.setContentsMargins(2, 2, 2, 2)
        # 第一行参数
        oc1 = QHBoxLayout()
        oc1.addWidget(QLabel("最大阶次:"))
        self.spin_mo = QSpinBox();
        self.spin_mo.setRange(1, 100);
        self.spin_mo.setValue(20);
        oc1.addWidget(self.spin_mo)
        oc1.addWidget(QLabel("阶次分辨率:"))
        self.spin_order_res = QDoubleSpinBox();
        self.spin_order_res.setRange(0.01, 1.0);
        self.spin_order_res.setValue(0.1);
        self.spin_order_res.setSingleStep(0.05);
        oc1.addWidget(self.spin_order_res)
        oc1.addWidget(QLabel("目标阶次:"))
        self.spin_to = QDoubleSpinBox();
        self.spin_to.setRange(0.5, 100);
        self.spin_to.setValue(1);
        oc1.addWidget(self.spin_to)
        oc1.addStretch();
        ol.addLayout(oc1)
        # 第二行参数
        oc2 = QHBoxLayout()
        oc2.addWidget(QLabel("FFT点数:"))
        self.combo_order_nfft = QComboBox();
        self.combo_order_nfft.addItems(['512', '1024', '2048', '4096', '8192']);
        self.combo_order_nfft.setCurrentText('1024');
        oc2.addWidget(self.combo_order_nfft)
        oc2.addWidget(QLabel("时间分辨率:"))
        self.spin_time_res = QDoubleSpinBox();
        self.spin_time_res.setRange(0.01, 1.0);
        self.spin_time_res.setValue(0.05);
        self.spin_time_res.setSingleStep(0.01);
        self.spin_time_res.setSuffix("s");
        oc2.addWidget(self.spin_time_res)
        oc2.addWidget(QLabel("RPM分辨率:"))
        self.spin_rpm_res = QSpinBox();
        self.spin_rpm_res.setRange(1, 100);
        self.spin_rpm_res.setValue(10);
        self.spin_rpm_res.setSuffix(" rpm");
        oc2.addWidget(self.spin_rpm_res)
        oc2.addStretch();
        ol.addLayout(oc2)
        # 按钮行
        ob = QHBoxLayout()
        self.btn_ot = QPushButton("▶ 时间-阶次");
        self.btn_ot.setStyleSheet("font-weight:bold;");
        ob.addWidget(self.btn_ot)
        self.btn_or = QPushButton("▶ 转速-阶次");
        ob.addWidget(self.btn_or)
        self.btn_ok = QPushButton("▶ 阶次跟踪");
        ob.addWidget(self.btn_ok)
        self.lbl_order_progress = QLabel("");
        self.lbl_order_progress.setStyleSheet("color:#888;");
        ob.addWidget(self.lbl_order_progress)
        ob.addStretch();
        ol.addLayout(ob)
        self.canvas_order = PlotCanvas(self);
        self.toolbar_order = NavigationToolbar(self.canvas_order, self)
        ol.addWidget(self.toolbar_order);
        ol.addWidget(self.canvas_order, stretch=1)
        self.tabs.addTab(ot, "🔄 阶次")

        lay.addWidget(self.tabs);
        return p

    def _connect(self):
        self.btn_load.clicked.connect(self.load_files)
        self.btn_close.clicked.connect(self.close_active)
        self.btn_close_all.clicked.connect(self.close_all)
        self.file_tabs.currentChanged.connect(self._tab_changed)
        self.file_tabs.tabCloseRequested.connect(self._tab_close)
        self.btn_plot.clicked.connect(self.plot_time)
        self.btn_fft.clicked.connect(self.do_fft)
        self.btn_ot.clicked.connect(self.do_order_time)
        self.btn_or.clicked.connect(self.do_order_rpm)
        self.btn_ok.clicked.connect(self.do_order_track)
        self.channel_list.channels_changed.connect(self._ch_changed)
        self.chk_cursor.stateChanged.connect(lambda st: self.canvas_time.set_cursor_visible(st == Qt.Checked))
        self.canvas_time.cursor_info.connect(self.lbl_cursor.setText)
        self.canvas_time.dual_cursor_info.connect(self.lbl_dual.setText)
        self.spin_xt.valueChanged.connect(self._update_all_tick_density)
        self.spin_yt.valueChanged.connect(self._update_all_tick_density)
        self.chk_dual.stateChanged.connect(self._dual_changed)
        self.btn_edit.clicked.connect(self.open_editor)
        self.btn_export.clicked.connect(self.export_excel)
        self.btn_reset.clicked.connect(self._reset_cursors)
        self.btn_rebuild_time.clicked.connect(self.rebuild_time_axis)
        self.chk_fft_remark.stateChanged.connect(
            lambda st: self.canvas_fft.set_remark_enabled(st == Qt.Checked))
        # 横坐标设置
        self.combo_xaxis.currentIndexChanged.connect(self._on_xaxis_mode_changed)
        self.btn_apply_xaxis.clicked.connect(self._apply_xaxis)
        self._custom_xlabel = None  # 自定义X轴标签
        self._custom_xaxis_fid = None  # 自定义X轴来源文件
        self._custom_xaxis_ch = None  # 自定义X轴来源通道

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
            self._add_tab(fid, fd);
            self.channel_list.add_file(fid, fd);
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

    def _add_tab(self, fid, fd):
        tw = QWidget();
        tw.setProperty("file_id", fid)  # 存储file_id到widget属性
        lay = QVBoxLayout(tw);
        lay.setContentsMargins(3, 3, 3, 3)
        lbl = QLabel(f"📄 {fd.filename}\n{len(fd.data)} 行\nFs: {fd.fs:.1f} Hz");
        lbl.setStyleSheet("font-size:9px;color:#555;");
        lay.addWidget(lbl);
        lay.addStretch()
        idx = self.file_tabs.addTab(tw, fd.short_name[:10]);
        self.file_tabs.setTabToolTip(idx, str(fd.filepath))
        self.file_tabs.setCurrentIndex(idx);
        self._active = fid

    def _get_tab_fid(self, idx):
        """获取指定tab的file_id"""
        if idx < 0: return None
        w = self.file_tabs.widget(idx)
        return w.property("file_id") if w else None

    def _tab_changed(self, idx):
        fid = self._get_tab_fid(idx)
        if fid:
            self._active = fid;
            self._update_info()
            if fid in self.files: self.spin_fs.setValue(self.files[fid].fs)

    def _tab_close(self, idx):
        fid = self._get_tab_fid(idx)
        if fid: self._close(fid)

    def close_active(self):
        if self._active: self._close(self._active)

    def _close(self, fid):
        if fid not in self.files: return
        del self.files[fid];
        self.channel_list.remove_file(fid)
        for i in range(self.file_tabs.count()):
            if self._get_tab_fid(i) == fid: self.file_tabs.removeTab(i); break
        self._active = list(self.files.keys())[0] if self.files else None
        self._update_info();
        self._update_combos();
        self.plot_time()
        self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")

    def close_all(self):
        if not self.files: return
        if QMessageBox.question(self, "确认", f"关闭全部 {len(self.files)} 文件?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        for fid in list(self.files.keys()): self._close(fid)
        self.canvas_time.clear();
        self.canvas_time.draw();
        self.stats.update_stats({})

    def _update_info(self):
        if not self.files: self.lbl_info.setText("未加载文件"); return
        self.lbl_info.setText("\n".join(
            [f"{'▶' if fid == self._active else '  '} {fd.short_name}: {len(fd.data)}" for fid, fd in
             self.files.items()]))

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

        mode = 'subplot' if self.combo_mode.currentIndex() == 0 else 'overlay'
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
