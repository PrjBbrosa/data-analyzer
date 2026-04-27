"""Modal dialogs: ChannelEditor, Export, AxisEdit."""
import numpy as np

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from PyQt5.QtCore import Qt

from ..signal import ChannelMath
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
        self.spin_p = QDoubleSpinBox();
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

        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-1e15, 1e15)
        self.spin_min.setDecimals(4)
        self.spin_min.setValue(lo)
        layout.addRow("最小值:", self.spin_min)

        self.spin_max = QDoubleSpinBox()
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
