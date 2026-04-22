"""Reusable widgets: StatisticsPanel and MultiFileChannelWidget."""
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush


class StatisticsPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken);
        self.setMaximumHeight(110)
        layout = QVBoxLayout(self);
        layout.setContentsMargins(4, 2, 4, 2)
        self.tree = QTreeWidget();
        self.tree.setHeaderLabels(['Channel', 'Min', 'Max', 'Mean', 'RMS', 'Std', 'P-P'])
        self.tree.setAlternatingRowColors(True);
        self.tree.setRootIsDecorated(False);
        self.tree.setStyleSheet("font-size:15px;")
        h = self.tree.header();
        h.setStretchLastSection(False);
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 7): h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree)

    def update_stats(self, stats):
        self.tree.clear()
        for ch, s in stats.items():
            self.tree.addTopLevelItem(QTreeWidgetItem(
                [ch[:26], f"{s['min']:.3g}", f"{s['max']:.3g}", f"{s['mean']:.3g}", f"{s['rms']:.3g}",
                 f"{s['std']:.3g}", f"{s['p2p']:.3g}"]))


class MultiFileChannelWidget(QWidget):
    channels_changed = pyqtSignal()
    MAX_CHANNELS_WARNING = 8  # 超过此数量时警告

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self);
        layout.setContentsMargins(0, 0, 0, 0);
        layout.setSpacing(2)
        self.search = QLineEdit();
        self.search.setPlaceholderText("🔍 Filter...");
        self.search.textChanged.connect(self._filter);
        layout.addWidget(self.search)
        bl = QHBoxLayout()
        for lbl, fn in [("All", self._all), ("None", self._none), ("Inv", self._inv)]:
            b = QPushButton(lbl);
            b.setMaximumWidth(40);
            b.clicked.connect(fn);
            bl.addWidget(b)
        bl.addStretch();
        layout.addLayout(bl)
        self.tree = QTreeWidget();
        self.tree.setHeaderLabels(['Channel', 'Pts']);
        self.tree.setColumnWidth(0, 165)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)
        self._file_items = {};
        self._colors = {};
        self._files = {};
        self._updating = False

    def add_file(self, fid, fd):
        self._files[fid] = fd
        fi = QTreeWidgetItem([f"📁 {fd.short_name}", f"{len(fd.data)}"])
        # 不使用AutoTristate，手动控制文件级勾选
        fi.setFlags(fi.flags() | Qt.ItemIsUserCheckable)
        fi.setCheckState(0, Qt.Unchecked)
        fi.setData(0, Qt.UserRole, ('file', fid));
        fi.setExpanded(True)
        font = fi.font(0);
        font.setBold(True);
        fi.setFont(0, font)
        palette = fd.get_color_palette()
        for i, ch in enumerate(fd.get_signal_channels()):
            color = palette[i % len(palette)];
            self._colors[(fid, ch)] = color
            ci = QTreeWidgetItem([ch, str(len(fd.data))])
            ci.setFlags(ci.flags() | Qt.ItemIsUserCheckable);
            ci.setCheckState(0, Qt.Unchecked)
            ci.setData(0, Qt.UserRole, ('channel', fid, ch));
            ci.setForeground(0, QBrush(QColor(color)))
            fi.addChild(ci)
        self.tree.addTopLevelItem(fi);
        self._file_items[fid] = fi

    def _on_item_changed(self, item, col):
        if self._updating: return
        data = item.data(0, Qt.UserRole)
        if data and data[0] == 'file':
            # 文件级复选框被点击
            fid = data[1]
            checked = item.checkState(0) == Qt.Checked
            if checked:
                # 统计该文件下有多少通道
                n_channels = item.childCount()
                if n_channels > self.MAX_CHANNELS_WARNING:
                    reply = QMessageBox.question(
                        self.tree, "确认",
                        f"该文件有 {n_channels} 个通道，全部勾选可能导致卡顿。\n确定要全选吗？",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        self._updating = True
                        item.setCheckState(0, Qt.Unchecked)
                        self._updating = False
                        return
                # 勾选所有子通道
                self._updating = True
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, Qt.Checked)
                self._updating = False
            else:
                # 取消所有子通道
                self._updating = True
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, Qt.Unchecked)
                self._updating = False
        self.channels_changed.emit()

    def remove_file(self, fid):
        if fid in self._file_items:
            i = self._file_items.pop(fid);
            idx = self.tree.indexOfTopLevelItem(i)
            if idx >= 0: self.tree.takeTopLevelItem(idx)
        for k in [k for k in self._colors if k[0] == fid]: del self._colors[k]
        if fid in self._files: del self._files[fid]
        self.channels_changed.emit()

    def get_checked_channels(self):
        r = []
        for fid, fi in self._file_items.items():
            for i in range(fi.childCount()):
                ci = fi.child(i)
                if ci.checkState(0) == Qt.Checked:
                    d = ci.data(0, Qt.UserRole)
                    if d and d[0] == 'channel': r.append((d[1], d[2], self._colors.get((d[1], d[2]), '#1f77b4')))
        return r

    def get_file_data(self, fid):
        return self._files.get(fid)

    def check_first_channel(self, fid):
        if fid in self._file_items:
            fi = self._file_items[fid]
            if fi.childCount() > 0: self._updating = True; fi.child(0).setCheckState(0,
                                                                                     Qt.Checked); self._updating = False; self.channels_changed.emit()

    def _filter(self, txt):
        t = txt.lower()
        for fid, fi in self._file_items.items():
            v = 0
            for i in range(fi.childCount()):
                ci = fi.child(i);
                m = t in ci.text(0).lower();
                ci.setHidden(not m);
                v += m
            fi.setHidden(v == 0 and len(t) > 0)

    def _all(self):
        # 统计总共要勾选多少通道
        total = sum(fi.childCount() for fi in self._file_items.values())
        if total > self.MAX_CHANNELS_WARNING:
            reply = QMessageBox.question(
                self.tree, "确认",
                f"共有 {total} 个通道，全部勾选可能导致卡顿。\n确定要全选吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self._updating = True
        for fi in self._file_items.values():
            for i in range(fi.childCount()):
                if not fi.child(i).isHidden(): fi.child(i).setCheckState(0, Qt.Checked)
        self._updating = False;
        self.channels_changed.emit()

    def _none(self):
        self._updating = True
        for fi in self._file_items.values():
            fi.setCheckState(0, Qt.Unchecked)
            for i in range(fi.childCount()): fi.child(i).setCheckState(0, Qt.Unchecked)
        self._updating = False;
        self.channels_changed.emit()

    def _inv(self):
        self._updating = True
        for fi in self._file_items.values():
            for i in range(fi.childCount()):
                ci = fi.child(i)
                if not ci.isHidden(): ci.setCheckState(0,
                                                       Qt.Unchecked if ci.checkState(0) == Qt.Checked else Qt.Checked)
        self._updating = False;
        self.channels_changed.emit()
