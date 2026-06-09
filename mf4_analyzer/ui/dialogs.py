"""Modal dialogs: ChannelEditor, Export, AxisEdit."""
import numpy as np

from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from matplotlib import colors as mcolors

from ..signal import ChannelMath
from ..ui_kit.widgets.searchable_combo import SearchableComboBox
from ._axis_handle import MplAxisHandle, make_handle
from .widgets.compact_spinbox import CompactDoubleSpinBox


class ChannelEditorDialog(QDialog):
    # Sizing for the narrow "方案 A" single-column layout. The panel target is
    # ~336px overall. ``INPUT_WIDTH`` is now a MINIMUM (floor) for input
    # controls, not a cap: inputs fill the row's available width so long
    # channel names stay visible and no blank gutter is left on the right (see
    # ``_narrow``). Tokens mirror style.qss (input radius 7 / button radius 8 /
    # primary #1769e0).
    export_requested = pyqtSignal(str, list, bool, bool)
    INPUT_WIDTH = 178
    PANEL_WIDTH = 336

    def __init__(self, parent, files, active_fid):
        super().__init__(parent)
        self.setObjectName("ChannelEditorDialog")
        # ``files`` is a dict[fid -> fd] of all loaded files; one file is
        # edited at a time. Switching the top file combo resets the in-flight
        # edit (new/removed) and repopulates every channel combo.
        self._files = dict(files)
        self.current_fid = active_fid if active_fid in self._files else (
            next(iter(self._files)) if self._files else None
        )
        self.fd = self._files.get(self.current_fid)
        self.new_channels = {}
        self.removed_channels = set()
        self.setMinimumWidth(self.PANEL_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- top file selector (stays put, does not scroll) ---
        file_bar = QWidget(self)
        file_bar.setObjectName("channelEditorFileBar")
        fb = QHBoxLayout(file_bar)
        fb.setContentsMargins(12, 10, 12, 8)
        fb.setSpacing(8)
        self._file_bar_layout = fb
        lbl_file = QLabel("文件")
        lbl_file.setMinimumWidth(34)
        fb.addWidget(lbl_file)
        self.combo_file = QComboBox()
        # Fill the file row: a Fixed-width label on the left, the combo
        # expanding to the right edge (no trailing stretch gutter).
        self.combo_file.setMinimumWidth(self.INPUT_WIDTH)
        self.combo_file.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for fid, fd in self._files.items():
            self.combo_file.addItem(self._file_label(fd), fid)
        if self.current_fid is not None:
            idx = self.combo_file.findData(self.current_fid)
            if idx >= 0:
                self.combo_file.setCurrentIndex(idx)
        self.combo_file.currentIndexChanged.connect(self._on_file_changed)
        fb.addWidget(self.combo_file, 1)
        root.addWidget(file_bar)

        # --- scrollable body (operations + delete) ---
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("channelEditorScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("channelEditorBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 6, 12, 10)
        bl.setSpacing(14)

        # 单通道运算
        g = QGroupBox("单通道运算")
        gl = QGridLayout(g)
        gl.setVerticalSpacing(8)
        gl.setHorizontalSpacing(8)
        gl.addWidget(QLabel("源"), 0, 0)
        self.combo_src = SearchableComboBox()
        self._narrow(self.combo_src)
        self.combo_src.currentTextChanged.connect(self.combo_src.setToolTip)
        gl.addWidget(self.combo_src, 0, 1)
        gl.addWidget(QLabel("运算"), 1, 0)
        self.combo_op = QComboBox()
        self.combo_op.addItems(["d/dt", "∫dt", "× 系数", "+ 偏移", "滑动平均", "|x| 绝对值"])
        self._narrow(self.combo_op)
        gl.addWidget(self.combo_op, 1, 1)
        gl.addWidget(QLabel("参数"), 2, 0)
        self.spin_p = CompactDoubleSpinBox()
        self.spin_p.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_p.setRange(-1e12, 1e12)
        self.spin_p.setValue(1)
        self._narrow(self.spin_p)
        gl.addWidget(self.spin_p, 2, 1)
        btn = QPushButton("✚ 创建单通道")
        btn.setObjectName("channelCreateBtn")
        btn.setProperty("role", "create")
        btn.clicked.connect(self._create_single)
        gl.addWidget(btn, 3, 1, Qt.AlignLeft)
        # Stretch the INPUT column (col 1) so controls fill to the right edge;
        # no ghost spacer column. The create button keeps Qt.AlignLeft so it
        # stays compact and left-anchored inside the now-stretched column.
        gl.setColumnStretch(1, 1)
        bl.addWidget(g)

        # 双通道运算
        g2 = QGroupBox("双通道运算 (A ⊕ B)")
        gl2 = QGridLayout(g2)
        gl2.setVerticalSpacing(8)
        gl2.setHorizontalSpacing(8)
        gl2.addWidget(QLabel("通道A"), 0, 0)
        self.combo_a = SearchableComboBox()
        self._narrow(self.combo_a)
        self.combo_a.currentTextChanged.connect(self.combo_a.setToolTip)
        gl2.addWidget(self.combo_a, 0, 1)
        gl2.addWidget(QLabel("运算"), 1, 0)
        self.combo_op2 = QComboBox()
        self.combo_op2.addItems(["A + B", "A - B", "A × B", "A ÷ B", "max(A,B)", "min(A,B)"])
        self._narrow(self.combo_op2)
        gl2.addWidget(self.combo_op2, 1, 1)
        gl2.addWidget(QLabel("通道B"), 2, 0)
        self.combo_b = SearchableComboBox()
        self._narrow(self.combo_b)
        self.combo_b.currentTextChanged.connect(self.combo_b.setToolTip)
        gl2.addWidget(self.combo_b, 2, 1)
        gl2.addWidget(QLabel("名称"), 3, 0)
        self.edit_name2 = QLineEdit()
        self.edit_name2.setPlaceholderText("留空自动生成")
        self._narrow(self.edit_name2)
        gl2.addWidget(self.edit_name2, 3, 1)
        btn2 = QPushButton("✚ 创建双通道")
        btn2.setObjectName("channelCreateBtn")
        btn2.setProperty("role", "create")
        btn2.clicked.connect(self._create_dual)
        gl2.addWidget(btn2, 4, 1, Qt.AlignLeft)
        # Stretch the INPUT column (col 1) so controls fill to the right edge;
        # no ghost spacer column. The create button keeps Qt.AlignLeft.
        gl2.setColumnStretch(1, 1)
        bl.addWidget(g2)

        # 导出（在双通道运算之下、删除之上）
        gx = QGroupBox("导出")
        gxl = QVBoxLayout(gx)
        gxl.setSpacing(8)
        self.list_export = QListWidget()
        self.list_export.setObjectName("channelExportList")
        self.list_export.setMinimumHeight(108)
        self.list_export.setMaximumHeight(120)
        gxl.addWidget(self.list_export)
        self.chk_export_time = QCheckBox("包含时间列")
        self.chk_export_time.setChecked(True)
        self.chk_export_range = QCheckBox("仅导出选定时间范围")
        gxl.addWidget(self.chk_export_time)
        gxl.addWidget(self.chk_export_range)
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setObjectName("channelCreateBtn")
        self.btn_export.setProperty("role", "create")
        self.btn_export.clicked.connect(self._on_export_clicked)
        gxl.addWidget(self.btn_export, 0, Qt.AlignLeft)
        bl.addWidget(gx)

        # 删除通道
        g3 = QGroupBox("删除")
        g3l = QVBoxLayout(g3)
        g3l.setSpacing(8)
        self.list_rm = QListWidget()
        self.list_rm.setObjectName("channelDeleteList")
        self.list_rm.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_rm.setMinimumHeight(108)
        self.list_rm.setMaximumHeight(120)
        g3l.addWidget(self.list_rm)
        btn_rm = QPushButton("🗑 删除选中通道")
        btn_rm.setObjectName("channelDeleteBtn")
        btn_rm.setProperty("role", "danger")
        btn_rm.clicked.connect(self._remove)
        g3l.addWidget(btn_rm, 0, Qt.AlignLeft)
        bl.addWidget(g3)
        bl.addStretch(1)

        self._scroll.setWidget(body)
        root.addWidget(self._scroll, 1)

        # --- footer (stays put): count + 取消/确定 ---
        footer = QWidget(self)
        footer.setObjectName("channelEditorFooter")
        ft = QHBoxLayout(footer)
        ft.setContentsMargins(12, 8, 12, 10)
        ft.setSpacing(10)
        self.lbl = QLabel("新增: 0")
        self.lbl.setObjectName("channelEditorCount")
        ft.addWidget(self.lbl)
        ft.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        ft.addWidget(self.btn_cancel)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setProperty("role", "primary")
        self.btn_ok.clicked.connect(self.accept)
        ft.addWidget(self.btn_ok)
        root.addWidget(footer)

        self._populate_channels()
        QTimer.singleShot(0, self._sync_file_bar_right_edge)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_file_bar_right_edge)

    def _sync_file_bar_right_edge(self):
        if not hasattr(self, "_file_bar_layout"):
            return
        if not hasattr(self, "combo_src") or self.combo_src.width() <= 0:
            return
        target = self.combo_src.mapTo(self, self.combo_src.rect().topLeft()).x()
        target += self.combo_src.width()
        current = self.combo_file.mapTo(self, self.combo_file.rect().topLeft()).x()
        current += self.combo_file.width()
        delta = current - target
        if abs(delta) <= 1:
            return
        left, top, right, bottom = self._file_bar_layout.getContentsMargins()
        self._file_bar_layout.setContentsMargins(
            left,
            top,
            max(0, right + delta),
            bottom,
        )
        self._file_bar_layout.activate()
        if self.layout() is not None:
            self.layout().activate()

    def _file_label(self, fd):
        """File display name: filepath.stem, falling back to filename."""
        fp = getattr(fd, "filepath", None)
        if fp is not None:
            return fp.stem
        name = getattr(fd, "filename", "") or getattr(fd, "short_name", "")
        return name.rsplit(".", 1)[0] if "." in name else name

    def _narrow(self, widget):
        """Let an input control FILL its row's available width.

        Previously this capped controls at ``INPUT_WIDTH`` (178px), which
        left a wide blank gutter on the right and truncated long channel
        names. The semantics are now "fill, with a sane floor": horizontal
        ``Expanding`` so the control grows into the row's slack, plus a
        ``setMinimumWidth`` floor so the control does not collapse when the
        panel is dragged narrow. Vertical policy stays ``Fixed``."""
        widget.setMinimumWidth(self.INPUT_WIDTH)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _on_file_changed(self, _index):
        fid = self.combo_file.currentData()
        if fid is None or fid == self.current_fid:
            return
        # Switching files discards the in-flight edit (one file at a time).
        self.current_fid = fid
        self.fd = self._files.get(fid)
        self.new_channels = {}
        self.removed_channels = set()
        self._populate_channels()

    def _populate_channels(self):
        """Refill source/A/B combos + delete list from the current fd, and
        reset the title and 新增 count. Called at construction and on every
        file switch."""
        chs = self.fd.get_signal_channels() if self.fd is not None else []
        title = self._file_label(self.fd) if self.fd is not None else ""
        self.setWindowTitle(f"通道编辑 - {title}" if title else "通道编辑")
        for combo in (self.combo_src, self.combo_a, self.combo_b):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(chs)
            combo.blockSignals(False)
            # Signals were blocked during refill, so the currentTextChanged →
            # setToolTip wiring did not fire; seed the hover tooltip for the
            # current selection so the full (possibly elided) channel name is
            # visible on hover even when the box width crops it.
            combo.setToolTip(combo.currentText())
        self.list_rm.clear()
        for ch in chs:
            self.list_rm.addItem(ch)
        self.list_export.clear()
        for ch in chs:
            it = QListWidgetItem(ch)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.list_export.addItem(it)
        self.lbl.setText("新增: 0")

    def _on_export_clicked(self):
        if self.current_fid is None:
            return
        channels = [
            self.list_export.item(i).text()
            for i in range(self.list_export.count())
            if self.list_export.item(i).checkState() == Qt.Checked
        ]
        if not channels:
            QMessageBox.information(self, "导出", "请先勾选要导出的通道。")
            return
        self.export_requested.emit(
            self.current_fid, channels,
            self.chk_export_time.isChecked(),
            self.chk_export_range.isChecked(),
        )

    def _create_single(self):
        src = self.combo_src.currentText()
        if src not in self.fd.data.columns: return
        sig = self.fd.data[src].values.astype(float)
        t = self.fd.time_array;
        op = self.combo_op.currentIndex();
        p = self.spin_p.value()
        prefixes = ["d_dt_", "int_", "scaled_", "offset_", "mavg_", "abs_"]
        try:
            if op == 0:
                r = ChannelMath.derivative(t, sig)
            elif op == 1:
                r = ChannelMath.integral(t, sig)
            elif op == 2:
                r = ChannelMath.scale(sig, p)
            elif op == 3:
                r = ChannelMath.offset(sig, p)
            elif op == 4:
                r = ChannelMath.moving_avg(sig, max(int(p), 3))
            elif op == 5:
                r = np.abs(sig)
            else:
                return
            name = f"{prefixes[op]}{src}"
            while name in self.fd.data.columns or name in self.new_channels: name += "_1"
            self.new_channels[name] = (r, self.fd.channel_units.get(src, ''))
            self.lbl.setText(f"新增: {len(self.new_channels)} ({name})")
            self.combo_src.addItem(name);
            self.combo_a.addItem(name);
            self.combo_b.addItem(name)
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _create_dual(self):
        ch_a = self.combo_a.currentText()
        ch_b = self.combo_b.currentText()
        if ch_a not in self.fd.data.columns and ch_a not in self.new_channels: return
        if ch_b not in self.fd.data.columns and ch_b not in self.new_channels: return

        # 获取数据
        if ch_a in self.new_channels:
            sig_a = self.new_channels[ch_a][0]
        else:
            sig_a = self.fd.data[ch_a].values.astype(float)
        if ch_b in self.new_channels:
            sig_b = self.new_channels[ch_b][0]
        else:
            sig_b = self.fd.data[ch_b].values.astype(float)

        if len(sig_a) != len(sig_b):
            QMessageBox.warning(self, "错误", f"通道长度不匹配: {len(sig_a)} vs {len(sig_b)}")
            return

        op = self.combo_op2.currentIndex()
        op_symbols = ["add", "sub", "mul", "div", "max", "min"]
        try:
            if op == 0:
                r = sig_a + sig_b
            elif op == 1:
                r = sig_a - sig_b
            elif op == 2:
                r = sig_a * sig_b
            elif op == 3:
                with np.errstate(divide='ignore', invalid='ignore'):
                    r = np.where(sig_b != 0, sig_a / sig_b, 0)
            elif op == 4:
                r = np.maximum(sig_a, sig_b)
            elif op == 5:
                r = np.minimum(sig_a, sig_b)
            else:
                return

            # 生成名称
            name = self.edit_name2.text().strip()
            if not name:
                name = f"{op_symbols[op]}_{ch_a}_{ch_b}"
            while name in self.fd.data.columns or name in self.new_channels: name += "_1"

            # 合并单位
            unit_a = self.fd.channel_units.get(ch_a, '')
            unit_b = self.fd.channel_units.get(ch_b, '')
            unit = unit_a if unit_a == unit_b else f"{unit_a}/{unit_b}" if op == 3 else ""

            self.new_channels[name] = (r, unit)
            self.lbl.setText(f"新增: {len(self.new_channels)} ({name})")
            self.combo_src.addItem(name);
            self.combo_a.addItem(name);
            self.combo_b.addItem(name)
            self.edit_name2.clear()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _remove(self):
        sel = [i.text() for i in self.list_rm.selectedItems()]
        if sel and QMessageBox.question(self, "确认", f"删除 {len(sel)} 通道?",
                                        QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.removed_channels.update(sel)
            for i in self.list_rm.selectedItems(): self.list_rm.takeItem(self.list_rm.row(i))


class ExportDialog(QDialog):
    def __init__(self, parent, chs):
        super().__init__(parent)
        self.setWindowTitle("导出Excel");
        self.setMinimumSize(280, 300)
        layout = QVBoxLayout(self)
        self.list_ch = QListWidget()
        for ch in chs:
            item = QListWidgetItem(ch);
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable);
            item.setCheckState(Qt.Checked)
            self.list_ch.addItem(item)
        layout.addWidget(self.list_ch)
        self.chk_time = QCheckBox("包含时间列");
        self.chk_time.setChecked(True);
        layout.addWidget(self.chk_time)
        self.chk_range = QCheckBox("仅导出选定范围");
        layout.addWidget(self.chk_range)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept);
        bb.rejected.connect(self.reject);
        layout.addWidget(bb)

    def get_selected(self):
        return [self.list_ch.item(i).text() for i in range(self.list_ch.count()) if
                self.list_ch.item(i).checkState() == Qt.Checked]


class AxisEditDialog(QDialog):
    """双击坐标轴弹出的编辑对话框"""
    def __init__(self, parent, ax, axis='x'):
        super().__init__(parent)
        self.ax = ax
        self.axis = axis
        self.setWindowTitle(f"{'X' if axis == 'x' else 'Y'}轴设置")
        self.setMinimumWidth(280)
        layout = QFormLayout(self)

        if axis == 'x':
            lo, hi = ax.get_xlim()
            label = ax.get_xlabel()
        else:
            lo, hi = ax.get_ylim()
            label = ax.get_ylabel()

        self.spin_min = CompactDoubleSpinBox()
        self.spin_min.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_min.setRange(-1e15, 1e15)
        self.spin_min.setDecimals(4)
        self.spin_min.setValue(lo)
        layout.addRow("最小值:", self.spin_min)

        self.spin_max = CompactDoubleSpinBox()
        self.spin_max.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_max.setRange(-1e15, 1e15)
        self.spin_max.setDecimals(4)
        self.spin_max.setValue(hi)
        layout.addRow("最大值:", self.spin_max)

        self.edit_label = QLineEdit(label)
        layout.addRow("标签:", self.edit_label)

        self.chk_auto = QCheckBox("自动范围")
        layout.addRow(self.chk_auto)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_values(self):
        return self.spin_min.value(), self.spin_max.value(), self.edit_label.text(), self.chk_auto.isChecked()


class ChartOptionsDialog(QDialog):
    """Inspector-styled lightweight chart options dialog for one axes."""

    SCALE_TO_TEXT = {
        "linear": "线性",
        "log": "对数",
    }
    TEXT_TO_SCALE = {v: k for k, v in SCALE_TO_TEXT.items()}

    def __init__(self, parent, axis_or_handle):
        super().__init__(parent)
        # Constructor accepts either a raw matplotlib ``Axes`` or an
        # already-wrapped ``AxisHandle`` (design §5.3 / Plan Task 3
        # Step 3). Existing call-sites in ``_axis_interaction`` and the
        # whole ``tests/ui/test_dialogs.py`` suite pass raw Axes, so the
        # wrap-on-demand branch keeps them working without an edit.
        self.handle = make_handle(axis_or_handle)
        # Backward-compat alias: code paths that still need the raw
        # matplotlib ``Axes`` during the migration window (legend
        # handles, gridline visibility introspection, line-axes/spines/
        # tick color sync at lines 750-793) read it through ``self.ax``.
        # ``MplAxisHandle`` exposes the underlying Axes via ``.axes``;
        # for ``PgAxisHandle`` this will be ``None`` once T5 lands and
        # the legacy code paths will already be gone by then.
        self.ax = getattr(self.handle, "axes", None)
        self._lines = self._editable_lines()
        self._mappables = self._editable_mappables()
        self.setObjectName("ChartOptionsDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("图表选项")
        self.setMinimumWidth(430)
        self._applied = False
        self._invalid_axes: list[str] = []
        self._initial = self._read_axes()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(3)
        title = QLabel("图表选项", self)
        title.setObjectName("chartOptionsTitle")
        subtitle = QLabel(self._target_summary(), self)
        subtitle.setObjectName("chartOptionsSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("chartOptionsTabs")
        self.tabs.addTab(self._axes_tab(), "坐标轴")
        self.tabs.addTab(self._appearance_tab(), "图形")
        self.tabs.addTab(self._legend_tab(), "图例")
        root.addWidget(self.tabs)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.addStretch(1)
        self.btn_reset = QPushButton("重置", self)
        self.btn_cancel = QPushButton("取消", self)
        self.btn_apply = QPushButton("应用", self)
        self.btn_ok = QPushButton("确定", self)
        self.btn_apply.setProperty("role", "primary")
        self.btn_ok.setProperty("role", "primary")
        for btn in (self.btn_reset, self.btn_cancel, self.btn_apply, self.btn_ok):
            actions.addWidget(btn)
        root.addLayout(actions)

        self.btn_reset.clicked.connect(self.reset_fields)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self.apply_changes)
        self.btn_ok.clicked.connect(self._accept_with_apply)
        self.chk_x_auto.toggled.connect(self._sync_auto_fields)
        self.chk_y_auto.toggled.connect(self._sync_auto_fields)
        self.chk_color_auto.toggled.connect(self._sync_auto_fields)
        self.combo_curve.currentIndexChanged.connect(self._sync_curve_color)
        self.btn_curve_color.clicked.connect(self._choose_curve_color)
        self.reset_fields()

    def _target_summary(self):
        # ``get_label`` is a matplotlib-only Artist accessor (not in the
        # ``AxisHandle`` protocol, design §5.3). Read it via the
        # migration-temporary escape hatch when present, so pyqtgraph
        # handles eventually fall through cleanly to the "当前图" default.
        title = self.handle.get_title()
        if not title and self.ax is not None:
            title = self.ax.get_label()
        title = title or "当前图"
        return f"目标：{title}"

    def _axes_tab(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        lay.addWidget(self._basic_group())
        lay.addWidget(self._axis_group("X 轴", "x"))
        lay.addWidget(self._axis_group("Y 轴", "y"))
        lay.addStretch(1)
        return page

    def _appearance_tab(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)
        lay.addWidget(self._curve_group())
        lay.addWidget(self._mappable_group())
        lay.addStretch(1)
        return page

    def _legend_tab(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)
        group = self._group_frame("图例")
        form = QVBoxLayout(group)
        form.setContentsMargins(10, 8, 10, 10)
        form.setSpacing(8)
        title = QLabel("图例", group)
        title.setObjectName("chartOptionsGroupTitle")
        form.addWidget(title)
        self.chk_legend = QCheckBox("重新生成自动图例", group)
        form.addWidget(self.chk_legend)
        lay.addWidget(group)
        lay.addStretch(1)
        return page

    def _basic_group(self):
        group = self._group_frame("基础信息")
        box = QVBoxLayout(group)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        title = QLabel("基础信息", group)
        title.setObjectName("chartOptionsGroupTitle")
        box.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self.edit_title = QLineEdit(group)
        form.addRow("标题", self.edit_title)
        box.addLayout(form)
        self.chk_grid = QCheckBox("显示网格线", group)
        box.addWidget(self.chk_grid)
        return group

    def _axis_group(self, group_title, axis):
        group = self._group_frame(group_title)
        box = QVBoxLayout(group)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        title = QLabel(group_title, group)
        title.setObjectName("chartOptionsGroupTitle")
        box.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        spin_min = self._spin(group)
        spin_max = self._spin(group)
        edit_label = QLineEdit(group)
        combo_scale = QComboBox(group)
        combo_scale.addItems(["线性", "对数"])
        chk_auto = QCheckBox("自动范围", group)

        form.addRow("最小值", spin_min)
        form.addRow("最大值", spin_max)
        form.addRow("标签", edit_label)
        form.addRow("刻度", combo_scale)
        box.addLayout(form)
        box.addWidget(chk_auto)

        setattr(self, f"spin_{axis}_min", spin_min)
        setattr(self, f"spin_{axis}_max", spin_max)
        setattr(self, f"edit_{axis}_label", edit_label)
        setattr(self, f"combo_{axis}_scale", combo_scale)
        setattr(self, f"chk_{axis}_auto", chk_auto)
        return group

    def _curve_group(self):
        group = self._group_frame("曲线")
        box = QVBoxLayout(group)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        title = QLabel("曲线", group)
        title.setObjectName("chartOptionsGroupTitle")
        box.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.combo_curve = QComboBox(group)
        for i, line in enumerate(self._lines):
            label = line.get_label()
            if not label or label.startswith("_"):
                label = f"曲线 {i + 1}"
            self.combo_curve.addItem(label)
        if not self._lines:
            self.combo_curve.addItem("无可编辑曲线")
            self.combo_curve.setEnabled(False)

        self.edit_curve_color = QLineEdit(group)
        self.edit_curve_color.setPlaceholderText("#1769e0")
        self.btn_curve_color = QPushButton("选择", group)
        color_row = QWidget(group)
        color_lay = QHBoxLayout(color_row)
        color_lay.setContentsMargins(0, 0, 0, 0)
        color_lay.setSpacing(6)
        color_lay.addWidget(self.edit_curve_color, stretch=1)
        color_lay.addWidget(self.btn_curve_color)
        if not self._lines:
            self.edit_curve_color.setEnabled(False)
            self.btn_curve_color.setEnabled(False)

        form.addRow("对象", self.combo_curve)
        form.addRow("颜色", color_row)
        box.addLayout(form)
        return group

    def _mappable_group(self):
        group = self._group_frame("色图与色阶")
        box = QVBoxLayout(group)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        title = QLabel("色图与色阶", group)
        title.setObjectName("chartOptionsGroupTitle")
        box.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.combo_cmap = QComboBox(group)
        self.combo_cmap.addItems([
            "turbo", "viridis", "plasma", "inferno", "magma",
            "cividis", "jet", "gray",
        ])
        self.chk_color_auto = QCheckBox("自动色阶范围", group)
        self.spin_color_min = self._spin(group)
        self.spin_color_max = self._spin(group)

        form.addRow("色图", self.combo_cmap)
        form.addRow("最小值", self.spin_color_min)
        form.addRow("最大值", self.spin_color_max)
        box.addLayout(form)
        box.addWidget(self.chk_color_auto)

        if not self._mappables:
            self.combo_cmap.setEnabled(False)
            self.chk_color_auto.setEnabled(False)
            self.spin_color_min.setEnabled(False)
            self.spin_color_max.setEnabled(False)
        return group

    def _group_frame(self, _title):
        frame = QFrame(self)
        frame.setObjectName("chartOptionsGroup")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        return frame

    def _spin(self, parent):
        spin = CompactDoubleSpinBox(parent)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setRange(-1e15, 1e15)
        spin.setDecimals(6)
        return spin

    def _read_axes(self):
        xlo, xhi = self.handle.get_xlim()
        ylo, yhi = self.handle.get_ylim()
        try:
            grid_visible = bool(self.handle.is_grid_enabled())
        except AttributeError:
            grid_visible = False
        try:
            x_scale_raw = self.handle.get_xscale()
        except AttributeError:
            x_scale_raw = "linear"
        try:
            y_scale_raw = self.handle.get_yscale()
        except AttributeError:
            y_scale_raw = "linear"
        # Matplotlib fallback for older/custom handles that do not yet
        # expose the full state surface.
        if self.ax is not None and not hasattr(self.handle, "is_grid_enabled"):
            grid_lines = list(self.ax.xaxis.get_gridlines()) + list(self.ax.yaxis.get_gridlines())
            grid_visible = any(line.get_visible() for line in grid_lines)
        if self.ax is not None and not hasattr(self.handle, "get_xscale"):
            x_scale_raw = self.ax.get_xscale()
        if self.ax is not None and not hasattr(self.handle, "get_yscale"):
            y_scale_raw = self.ax.get_yscale()
        line = self._current_line()
        line_color = self._line_color_text(line) if line is not None else ""
        mappable = self._current_mappable()
        if mappable is not None:
            cmap = mappable.get_cmap().name
            cmin, cmax = mappable.get_clim()
        else:
            cmap = "turbo"
            cmin, cmax = 0.0, 1.0
        return {
            "title": self.handle.get_title(),
            "x_min": float(xlo),
            "x_max": float(xhi),
            "x_label": self.handle.get_xlabel(),
            "x_scale": self.SCALE_TO_TEXT.get(x_scale_raw, x_scale_raw),
            "x_auto": False,
            "y_min": float(ylo),
            "y_max": float(yhi),
            "y_label": self.handle.get_ylabel(),
            "y_scale": self.SCALE_TO_TEXT.get(y_scale_raw, y_scale_raw),
            "y_auto": False,
            "grid": grid_visible,
            "legend": False,
            "curve_index": 0,
            "curve_color": line_color,
            "cmap": cmap,
            "color_min": float(cmin),
            "color_max": float(cmax),
            "color_auto": False,
        }

    def reset_fields(self):
        d = self._initial
        self.edit_title.setText(d["title"])
        self.spin_x_min.setValue(d["x_min"])
        self.spin_x_max.setValue(d["x_max"])
        self.edit_x_label.setText(d["x_label"])
        self.combo_x_scale.setCurrentText(d["x_scale"])
        self.chk_x_auto.setChecked(d["x_auto"])
        self.spin_y_min.setValue(d["y_min"])
        self.spin_y_max.setValue(d["y_max"])
        self.edit_y_label.setText(d["y_label"])
        self.combo_y_scale.setCurrentText(d["y_scale"])
        self.chk_y_auto.setChecked(d["y_auto"])
        self.chk_grid.setChecked(d["grid"])
        self.chk_legend.setChecked(d["legend"])
        self.combo_curve.setCurrentIndex(d["curve_index"] if self._lines else 0)
        self.edit_curve_color.setText(d["curve_color"])
        self._set_combo_text(self.combo_cmap, d["cmap"])
        self.spin_color_min.setValue(d["color_min"])
        self.spin_color_max.setValue(d["color_max"])
        self.chk_color_auto.setChecked(d["color_auto"])
        self._sync_auto_fields()

    def apply_changes(self):
        # Reset per-apply error collector; repeated clicks must not carry
        # invalid-axis state from a previous attempt.
        self._invalid_axes = []
        self.handle.set_title(self.edit_title.text())
        self._apply_axis(
            axis="x",
            auto=self.chk_x_auto.isChecked(),
            vmin=self.spin_x_min.value(),
            vmax=self.spin_x_max.value(),
            label=self.edit_x_label.text(),
            scale_text=self.combo_x_scale.currentText(),
        )
        self._apply_axis(
            axis="y",
            auto=self.chk_y_auto.isChecked(),
            vmin=self.spin_y_min.value(),
            vmax=self.spin_y_max.value(),
            label=self.edit_y_label.text(),
            scale_text=self.combo_y_scale.currentText(),
        )
        self.handle.grid(self.chk_grid.isChecked())
        if self.chk_legend.isChecked() and hasattr(self.handle, "rebuild_legend"):
            self.handle.rebuild_legend()
        elif self.chk_legend.isChecked() and self.ax is not None:
            handles, labels = self.ax.get_legend_handles_labels()
            pairs = [(h, l) for h, l in zip(handles, labels) if l and not l.startswith("_")]
            if pairs:
                handles, labels = zip(*pairs)
                self.ax.legend(handles, labels)
        self._apply_appearance()
        self.handle.request_redraw()
        if self._invalid_axes:
            # Log scale + non-positive range: scale switch and label/legend
            # changes still landed (user may want them), but the manual range
            # was rejected and the axis fell back to autoscale. Surface that
            # to the user; do NOT mark _applied so the OK path can refuse to
            # close.
            QMessageBox.warning(
                self,
                "范围非法",
                "对数刻度下 X/Y 范围必须 > 0",
            )
            self._applied = False
            return
        self._applied = True

    def was_applied(self):
        return self._applied

    def _apply_axis(self, *, axis, auto, vmin, vmax, label, scale_text):
        scale = self.TEXT_TO_SCALE.get(scale_text, "linear")
        if axis == "x":
            setter_scale = self.handle.set_xscale
            setter_lim = self.handle.set_xlim
            setter_label = self.handle.set_xlabel
        else:
            setter_scale = self.handle.set_yscale
            setter_lim = self.handle.set_ylim
            setter_label = self.handle.set_ylabel

        setter_scale(scale)
        if auto:
            self.handle.autoscale(axis=axis)
        else:
            if scale == "log" and (float(vmin) <= 0 or float(vmax) <= 0):
                # Defer hard error to the apply() aggregator: collect axis,
                # fall back to autoscale so the chart stays in a usable state
                # rather than silently keeping a stale (or matplotlib-clamped)
                # range.
                self._invalid_axes.append(axis)
                self.handle.autoscale(axis=axis)
            else:
                setter_lim(float(vmin), float(vmax))
        setter_label(label)

    def _editable_lines(self):
        # ``handle.get_lines()`` already filters out invisible lines and
        # returns ``LineHandle`` wrappers. Renderer-agnostic by design
        # §5.3 — works for both ``MplAxisHandle`` and the future
        # ``PgAxisHandle``.
        return list(self.handle.get_lines())

    def _editable_mappables(self):
        # ``handle.get_mappables()`` returns the same set the legacy
        # ``ax.images + ax.collections`` walk produced. For TimeDomain
        # this is empty (design §5.3), which correctly disables the
        # ColorMap/ColorScale group below.
        return list(self.handle.get_mappables())

    def _current_line(self):
        if not self._lines:
            return None
        idx = max(0, min(self.combo_curve.currentIndex(), len(self._lines) - 1)) \
            if hasattr(self, "combo_curve") else 0
        return self._lines[idx]

    def _current_mappable(self):
        return self._mappables[0] if self._mappables else None

    def _line_color_text(self, line):
        try:
            return mcolors.to_hex(line.get_color())
        except ValueError:
            return str(line.get_color())

    def _set_combo_text(self, combo, text):
        if combo.findText(text) < 0:
            combo.addItem(text)
        combo.setCurrentText(text)

    def _sync_curve_color(self):
        line = self._current_line()
        if line is not None:
            self.edit_curve_color.setText(self._line_color_text(line))

    def _sync_auto_fields(self):
        for axis in ("x", "y"):
            auto = getattr(self, f"chk_{axis}_auto").isChecked()
            getattr(self, f"spin_{axis}_min").setEnabled(not auto)
            getattr(self, f"spin_{axis}_max").setEnabled(not auto)
        color_enabled = bool(self._mappables) and not self.chk_color_auto.isChecked()
        self.spin_color_min.setEnabled(color_enabled)
        self.spin_color_max.setEnabled(color_enabled)

    def _choose_curve_color(self):
        initial = self.edit_curve_color.text().strip()
        initial_color = (
            QColor(mcolors.to_hex(initial))
            if mcolors.is_color_like(initial)
            else QColor("#1769e0")
        )
        color = QColorDialog.getColor(
            initial_color,
            self,
            "选择颜色",
        )
        if color.isValid():
            self.edit_curve_color.setText(color.name())

    def _apply_appearance(self):
        line = self._current_line()
        color = self.edit_curve_color.text().strip()
        if line is not None and color and mcolors.is_color_like(color):
            line.set_color(color)
            self._sync_curve_axis_color(line, color)

        mappable = self._current_mappable()
        if mappable is None:
            return
        mappable.set_cmap(self.combo_cmap.currentText())
        if self.chk_color_auto.isChecked():
            arr = mappable.get_array()
            if arr is not None:
                data = np.asarray(arr, dtype=float)
                finite = data[np.isfinite(data)]
                if finite.size:
                    mappable.set_clim(float(np.min(finite)), float(np.max(finite)))
        else:
            mappable.set_clim(
                float(self.spin_color_min.value()),
                float(self.spin_color_max.value()),
            )

    def _sync_curve_axis_color(self, line, color):
        sync = getattr(self.handle, "sync_line_axis_color", None)
        if callable(sync):
            sync(line, color)

        # ``line`` is a ``LineHandle`` wrapper now; unwrap back to the
        # matplotlib ``Line2D`` for the canvas/inside-label sync paths
        # that still need the raw artist during the migration window.
        raw_line = getattr(line, "line", line)
        ax = getattr(raw_line, "axes", None) or self.ax
        if ax is None:
            return

        canvas = getattr(ax.figure, "canvas", None)
        channel_name = self._channel_name_for_line(canvas, raw_line)
        if channel_name is None:
            return

        channel_data = getattr(canvas, "channel_data", None)
        if isinstance(channel_data, dict) and channel_name in channel_data:
            t, sig, _old_color, unit = channel_data[channel_name]
            channel_data[channel_name] = (t, sig, color, unit)

        for artist in getattr(canvas, "_inside_channel_label_artists", []):
            if artist.get_gid() != channel_name:
                continue
            artist.set_color(color)
            patch = artist.get_bbox_patch()
            if patch is not None:
                patch.set_edgecolor(color)

    def _axis_side_for_line(self, ax):
        canvas = getattr(ax.figure, "canvas", None)
        axes_list = getattr(canvas, "axes_list", [])
        if getattr(canvas, "_overlay_mode", False) and axes_list and ax is not axes_list[0]:
            return 'right'
        label_pos = getattr(ax.yaxis, "get_label_position", lambda: "left")()
        tick_pos = getattr(ax.yaxis, "get_ticks_position", lambda: "left")()
        if label_pos == 'right' or tick_pos == 'right':
            return 'right'
        return 'left'

    def _channel_name_for_line(self, canvas, line):
        if canvas is None:
            return None
        for name, (_ax, channel_line) in getattr(canvas, "_channel_lines", {}).items():
            if channel_line is line:
                return name
        return None

    def _accept_with_apply(self):
        self.apply_changes()
        # If apply rejected (e.g. log + non-positive range), keep the dialog
        # open so the user can correct the input.
        if self._invalid_axes:
            return
        self.accept()
