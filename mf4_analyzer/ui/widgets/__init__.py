"""Reusable widgets: StatisticsPanel, MultiFileChannelWidget, Toast."""
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QPropertyAnimation, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QIcon, QPainter, QPen, QPixmap


def _swatch_icon(color, size=14):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(QColor(color), 1))
    p.setBrush(QBrush(QColor(color)))
    p.drawRoundedRect(2, 2, size - 4, size - 4, 3, 3)
    p.end()
    return QIcon(pix)


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
        h = self.tree.header();
        h.setStretchLastSection(False);
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 7): h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree)

    def update_stats(self, stats):
        self.tree.clear()
        for ch, s in stats.items():
            self.tree.addTopLevelItem(QTreeWidgetItem(
                [ch, f"{s['min']:.3g}", f"{s['max']:.3g}", f"{s['mean']:.3g}", f"{s['rms']:.3g}",
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
        self.search.setObjectName("channelSearch")
        self.search.setPlaceholderText("Filter channel...");
        self.search.textChanged.connect(self._filter);
        layout.addWidget(self.search)
        bl = QHBoxLayout()
        for lbl, fn in [("All", self._all), ("None", self._none), ("Inv", self._inv)]:
            b = QPushButton(lbl);
            b.setMaximumWidth(40);
            b.setProperty("role", "tool")
            b.clicked.connect(fn);
            bl.addWidget(b)
        bl.addStretch();
        layout.addLayout(bl)
        self.tree = QTreeWidget();
        self.tree.setObjectName("channelTree")
        self.tree.setHeaderLabels(['Channel', 'Pts']);
        header = self.tree.header()
        # Channel column owns all spare width so long names aren't elided when
        # the dock is widened. Pts column auto-fits its 5-7 digit numbers.
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tree.headerItem().setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)
        self._file_items = {};
        self._colors = {};
        self._files = {};
        self._updating = False

    def add_file(self, fid, fd):
        self._files[fid] = fd
        fi = QTreeWidgetItem([fd.short_name, f"{len(fd.data)}"])
        fi.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
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
            ci.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            ci.setFlags(ci.flags() | Qt.ItemIsUserCheckable);
            ci.setCheckState(0, Qt.Unchecked)
            ci.setData(0, Qt.UserRole, ('channel', fid, ch));
            ci.setIcon(0, _swatch_icon(color))
            ci.setForeground(0, QBrush(QColor('#111827')))
            ci.setForeground(1, QBrush(QColor('#64748b')))
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


class StatsStrip(QFrame):
    """Compact stats line + click-to-expand full table.

    Collapsed: one-liner per channel joined with ' │ '.
    Expanded: full StatisticsPanel with the 6-metric tree.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt5.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout
        self._expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        top = QHBoxLayout()
        self._btn_expand = QToolButton()
        self._btn_expand.setObjectName("statsExpand")
        self._btn_expand.setText(">")
        self._btn_expand.setProperty("role", "tool")
        self._btn_expand.clicked.connect(self.toggle)
        top.addWidget(self._btn_expand)
        self._lbl_summary = QLabel("— 无通道 —")
        top.addWidget(self._lbl_summary, stretch=1)
        lay.addLayout(top)
        self._panel = StatisticsPanel(self)
        self._panel.setVisible(False)
        lay.addWidget(self._panel)

    def toggle(self):
        self._expanded = not self._expanded
        self._btn_expand.setText("v" if self._expanded else ">")
        self._panel.setVisible(self._expanded)

    def update_stats(self, stats):
        if not stats:
            self._lbl_summary.setText("— 无通道 —")
            self._panel.update_stats({})
            return
        parts = []
        for ch, s in stats.items():
            parts.append(
                f"● {ch}: min={s['min']:.3g} max={s['max']:.3g} "
                f"rms={s['rms']:.3g} p2p={s['p2p']:.3g}"
            )
        self._lbl_summary.setText(" │ ".join(parts))
        self._panel.update_stats(stats)


class Toast(QFrame):
    """Floating non-blocking acknowledgement toast.

    One toast at a time per parent: a new message replaces the current one
    instead of stacking, which keeps the bottom edge of the window clean and
    matches user expectation that "the latest action wins". Levels map to
    accent colors (info/success/warning/error) defined in style.qss.
    """

    _HOLD_MS = {'info': 3500, 'success': 3500, 'warning': 5000, 'error': 7000}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(10)
        self._icon = QLabel(self)
        self._icon.setObjectName("toastIcon")
        self._msg = QLabel("", self)
        self._msg.setObjectName("toastText")
        self._msg.setTextFormat(Qt.PlainText)
        lay.addWidget(self._icon)
        lay.addWidget(self._msg)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(180)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self.hide()

    _GLYPHS = {
        'info': '✓',
        'success': '✓',
        'warning': '!',
        'error': '✕',
    }

    def show_message(self, text, level='info'):
        level = level if level in self._HOLD_MS else 'info'
        self.setProperty('level', level)
        self._icon.setProperty('level', level)
        # Re-polish to reapply QSS based on new property value.
        self.style().unpolish(self); self.style().polish(self)
        self._icon.style().unpolish(self._icon); self._icon.style().polish(self._icon)
        self._icon.setText(self._GLYPHS[level])
        self._msg.setText(text)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        # Drop any leftover fade-out → hide connection so this fade-in
        # doesn't get auto-dismissed when it reaches full opacity.
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._hide_timer.start(self._HOLD_MS[level])

    def _fade_out(self):
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.finished.connect(self.hide)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        margin_bottom = 36  # leave room for status bar
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - margin_bottom
        self.move(max(8, x), max(8, y))
