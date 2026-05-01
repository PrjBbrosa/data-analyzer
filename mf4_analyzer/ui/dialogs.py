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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from matplotlib import colors as mcolors

from ..signal import ChannelMath
from .widgets.compact_spinbox import CompactDoubleSpinBox
from .widgets.searchable_combo import SearchableComboBox


class ChannelEditorDialog(QDialog):
    def __init__(self, parent, fd):
        super().__init__(parent)
        self.setWindowTitle(f"通道编辑 - {fd.filename}")
        self.setMinimumSize(500, 420)
        self.fd = fd
        self.new_channels = {};
        self.removed_channels = set()
        layout = QVBoxLayout(self)
        chs = fd.get_signal_channels()

        # 单通道运算
        g = QGroupBox("单通道运算");
        gl = QGridLayout(g)
        gl.addWidget(QLabel("源:"), 0, 0)
        self.combo_src = SearchableComboBox();
        self.combo_src.addItems(chs);
        gl.addWidget(self.combo_src, 0, 1)
        gl.addWidget(QLabel("运算:"), 1, 0)
        self.combo_op = QComboBox();
        self.combo_op.addItems(["d/dt", "∫dt", "× 系数", "+ 偏移", "滑动平均", "|x| 绝对值"]);
        gl.addWidget(self.combo_op, 1, 1)
        gl.addWidget(QLabel("参数:"), 2, 0)
        self.spin_p = CompactDoubleSpinBox();
        self.spin_p.setButtonSymbols(QAbstractSpinBox.NoButtons);
        self.spin_p.setRange(-1e12, 1e12);
        self.spin_p.setValue(1);
        gl.addWidget(self.spin_p, 2, 1)
        btn = QPushButton("✚ 创建");
        btn.clicked.connect(self._create_single);
        gl.addWidget(btn, 3, 0, 1, 2)
        layout.addWidget(g)

        # 双通道运算
        g2 = QGroupBox("双通道运算 (A ⊕ B)");
        gl2 = QGridLayout(g2)
        gl2.addWidget(QLabel("通道A:"), 0, 0)
        self.combo_a = SearchableComboBox();
        self.combo_a.addItems(chs);
        gl2.addWidget(self.combo_a, 0, 1)
        gl2.addWidget(QLabel("运算:"), 1, 0)
        self.combo_op2 = QComboBox();
        self.combo_op2.addItems(["A + B", "A - B", "A × B", "A ÷ B", "max(A,B)", "min(A,B)"]);
        gl2.addWidget(self.combo_op2, 1, 1)
        gl2.addWidget(QLabel("通道B:"), 2, 0)
        self.combo_b = SearchableComboBox();
        self.combo_b.addItems(chs);
        gl2.addWidget(self.combo_b, 2, 1)
        gl2.addWidget(QLabel("新名称:"), 3, 0)
        self.edit_name2 = QLineEdit();
        self.edit_name2.setPlaceholderText("留空自动生成");
        gl2.addWidget(self.edit_name2, 3, 1)
        btn2 = QPushButton("✚ 创建");
        btn2.clicked.connect(self._create_dual);
        gl2.addWidget(btn2, 4, 0, 1, 2)
        layout.addWidget(g2)

        # 删除通道
        g3 = QGroupBox("删除");
        g3l = QVBoxLayout(g3)
        self.list_rm = QListWidget();
        self.list_rm.setSelectionMode(QListWidget.ExtendedSelection);
        self.list_rm.setMaximumHeight(70)
        for ch in chs: self.list_rm.addItem(ch)
        g3l.addWidget(self.list_rm)
        btn_rm = QPushButton("🗑 删除");
        btn_rm.clicked.connect(self._remove);
        g3l.addWidget(btn_rm)
        layout.addWidget(g3)

        self.lbl = QLabel(f"新增: 0");
        layout.addWidget(self.lbl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept);
        bb.rejected.connect(self.reject);
        layout.addWidget(bb)

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

    def __init__(self, parent, ax):
        super().__init__(parent)
        self.ax = ax
        self._lines = self._editable_lines()
        self._mappables = self._editable_mappables()
        self.setObjectName("ChartOptionsDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("图表选项")
        self.setMinimumWidth(430)
        self._applied = False
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
        title = self.ax.get_title() or self.ax.get_label() or "当前图"
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
        xlo, xhi = self.ax.get_xlim()
        ylo, yhi = self.ax.get_ylim()
        grid_lines = list(self.ax.xaxis.get_gridlines()) + list(self.ax.yaxis.get_gridlines())
        grid_visible = any(line.get_visible() for line in grid_lines)
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
            "title": self.ax.get_title(),
            "x_min": float(xlo),
            "x_max": float(xhi),
            "x_label": self.ax.get_xlabel(),
            "x_scale": self.SCALE_TO_TEXT.get(self.ax.get_xscale(), self.ax.get_xscale()),
            "x_auto": False,
            "y_min": float(ylo),
            "y_max": float(yhi),
            "y_label": self.ax.get_ylabel(),
            "y_scale": self.SCALE_TO_TEXT.get(self.ax.get_yscale(), self.ax.get_yscale()),
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
        ax = self.ax
        ax.set_title(self.edit_title.text())
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
        ax.grid(self.chk_grid.isChecked())
        if self.chk_legend.isChecked():
            handles, labels = ax.get_legend_handles_labels()
            pairs = [(h, l) for h, l in zip(handles, labels) if l and not l.startswith("_")]
            if pairs:
                handles, labels = zip(*pairs)
                ax.legend(handles, labels)
        self._apply_appearance()
        if ax.figure.canvas is not None:
            ax.figure.canvas.draw_idle()
        self._applied = True

    def was_applied(self):
        return self._applied

    def _apply_axis(self, *, axis, auto, vmin, vmax, label, scale_text):
        scale = self.TEXT_TO_SCALE.get(scale_text, "linear")
        if axis == "x":
            self.ax.set_xscale(scale)
            if auto:
                self.ax.autoscale(axis="x")
            else:
                self.ax.set_xlim(float(vmin), float(vmax))
            self.ax.set_xlabel(label)
        else:
            self.ax.set_yscale(scale)
            if auto:
                self.ax.autoscale(axis="y")
            else:
                self.ax.set_ylim(float(vmin), float(vmax))
            self.ax.set_ylabel(label)

    def _editable_lines(self):
        return [line for line in self.ax.get_lines() if line.get_visible()]

    def _editable_mappables(self):
        found = []
        for obj in list(self.ax.images) + list(self.ax.collections):
            if hasattr(obj, "set_cmap") and hasattr(obj, "set_clim"):
                found.append(obj)
        return found

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

    def _accept_with_apply(self):
        self.apply_changes()
        self.accept()
