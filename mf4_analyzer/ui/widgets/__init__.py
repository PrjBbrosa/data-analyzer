"""Reusable widgets: StatisticsPanel, MultiFileChannelWidget, Toast."""
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QPropertyAnimation, QRect, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QIcon, QPainter, QPen, QPixmap

from ...ui_kit.icons import Icons, icon_device_pixel_ratio


def _swatch_pixmap(color, size=11, ratio=None):
    """Render the channel color swatch at ``ratio x`` physical resolution and
    tag it with that devicePixelRatio so HiDPI (Retina) screens paint it crisp
    rather than upscaling a 1x bitmap (which produced the jagged edges).

    ``size`` is the logical icon box; the dot fills ``size - 4`` so it reads as
    a compact colour chip aligned with the row text rather than a heavy block.
    """
    if ratio is None:
        ratio = icon_device_pixel_ratio()
    pix = QPixmap(round(size * ratio), round(size * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(QColor(color), 1))
    p.setBrush(QBrush(QColor(color)))
    # Coordinates stay in LOGICAL units; the painter is scaled by the pixmap's
    # devicePixelRatio automatically.
    p.drawRoundedRect(2, 2, size - 4, size - 4, 3, 3)
    p.end()
    return pix


def _swatch_icon(color, size=11):
    return QIcon(_swatch_pixmap(color, size))


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


class _CheckTolerantTree(QTreeWidget):
    """QTreeWidget that widens the *clickable* hit area of the column-0
    checkbox (the indicator stays the same visual size).

    Users kept missing the small indicator box. We grow only the hit band:
    the indicator rect padded by ``HIT_PAD`` px on each side, stretched to
    the full row height. A left-click that lands inside that band toggles
    the row's check state and is consumed, so Qt does not double-toggle it.
    A click on the channel-name / swatch area falls through to the base
    class (selection + the right-click 设为左轴 path are untouched).
    """

    HIT_PAD = 6  # px tolerance added to each side of the indicator rect

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._consume_check_release = False

    def _check_hit_rect(self, item, index):
        """Return the enlarged clickable rect for ``item``'s checkbox, or
        None if the row has no user-checkable column-0 box."""
        if not (item.flags() & Qt.ItemIsUserCheckable):
            return None
        opt = QStyleOptionViewItem()
        opt.initFrom(self)
        opt.rect = self.visualRect(index)
        # The check-indicator subelement rect is only computed when the
        # option advertises a check indicator; without these the style
        # returns a null rect.
        opt.features |= QStyleOptionViewItem.HasCheckIndicator
        opt.checkState = item.checkState(0)
        indicator = self.style().subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, opt, self
        )
        if indicator.isNull() or indicator.width() <= 0:
            # Fallback: some styles still report a degenerate rect under the
            # offscreen platform. Derive the indicator band from the row's
            # left edge + the style's checkbox metric so the tolerance band
            # is still usable.
            metric = self.style().pixelMetric(
                QStyle.PM_IndicatorWidth, opt, self
            )
            if metric <= 0:
                return None
            row = self.visualRect(index)
            left = row.left() + 2
            indicator = QRect(left, row.top(), metric, row.height())
        # Widen left/right by the tolerance; cover the full row height so a
        # click anywhere on the left band (vertically) still counts.
        row = self.visualItemRect(item)
        hit = indicator.adjusted(-self.HIT_PAD, 0, self.HIT_PAD, 0)
        hit.setTop(row.top())
        hit.setBottom(row.bottom())
        return hit

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            item = self.itemAt(pos)
            if item is not None:
                index = self.indexFromItem(item, 0)
                hit = self._check_hit_rect(item, index)
                if hit is not None and hit.contains(pos):
                    new_state = (
                        Qt.Unchecked
                        if item.checkState(0) == Qt.Checked
                        else Qt.Checked
                    )
                    # Route through setCheckState so the existing
                    # itemChanged → _on_item_changed cascade (file→child
                    # propagation, MAX_CHANNELS_WARNING, channels_changed)
                    # runs exactly once. Consume the event pair: returning
                    # here handles the press, and mouseReleaseEvent suppresses
                    # Qt's native indicator release toggle.
                    self._consume_check_release = True
                    item.setCheckState(0, new_state)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._consume_check_release:
            self._consume_check_release = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            item = self.itemAt(pos)
            if item is not None:
                index = self.indexFromItem(item, 0)
                hit = self._check_hit_rect(item, index)
                if hit is not None and hit.contains(pos):
                    new_state = (
                        Qt.Unchecked
                        if item.checkState(0) == Qt.Checked
                        else Qt.Checked
                    )
                    item.setCheckState(0, new_state)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)


class MultiFileChannelWidget(QWidget):
    channels_changed = pyqtSignal()
    # Emitted when the user picks 设为左轴 in a channel's right-click menu.
    # (fid, channel) — MainWindow makes that channel the overlay left axis.
    primary_channel_requested = pyqtSignal(str, str)
    channel_context_menu_requested = pyqtSignal()
    # Emitted when 编辑通道 (moved here from the top toolbar) is clicked.
    channel_editor_requested = pyqtSignal()
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
        for lbl, fn in [("全选", self._all), ("全不", self._none)]:
            b = QPushButton(lbl);
            b.setMaximumWidth(48);
            b.setProperty("role", "tool")
            b.clicked.connect(fn);
            bl.addWidget(b)
        self.btn_selected_only = QPushButton("已选")
        self.btn_selected_only.setMaximumWidth(48)
        self.btn_selected_only.setProperty("role", "tool")
        self.btn_selected_only.setCheckable(True)
        self.btn_selected_only.toggled.connect(self._apply_filters)
        bl.addWidget(self.btn_selected_only)
        bl.addStretch();
        # 编辑通道 lives on this row (right-aligned) instead of the top toolbar,
        # so the channel actions sit next to the channel tree they affect.
        self.btn_edit = QPushButton("编辑通道")
        self.btn_edit.setIcon(Icons.edit_channels())
        self.btn_edit.setIconSize(QSize(16, 16))
        self.btn_edit.setProperty("role", "tool")
        self.btn_edit.setEnabled(False)  # enabled once a file is loaded
        self.btn_edit.clicked.connect(self.channel_editor_requested)
        bl.addWidget(self.btn_edit)
        layout.addLayout(bl)
        self.tree = _CheckTolerantTree();
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
        # Right-click a channel row → 设为左轴 (overlay primary axis).
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree)
        self._file_items = {};
        self._colors = {};
        self._files = {};
        self._updating = False

    def add_file(self, fid, fd):
        self._files[fid] = fd
        fp = getattr(fd, "filepath", None)
        if fp is not None:
            file_label = fp.stem
            file_tip = fp.name
        else:
            file_tip = getattr(fd, "filename", "") or getattr(fd, "short_name", "")
            file_label = file_tip.rsplit(".", 1)[0] if "." in file_tip else file_tip
        fi = QTreeWidgetItem([file_label, f"{len(fd.data)}"])
        if file_tip:
            fi.setToolTip(0, file_tip)
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
        self._apply_filters()
        self._update_edit_enabled()

    def _update_edit_enabled(self):
        """编辑通道 is only meaningful with at least one file loaded."""
        self.btn_edit.setEnabled(bool(self._files))

    def _on_item_changed(self, item, col):
        if self._updating: return
        data = item.data(0, Qt.UserRole)
        if data and data[0] == 'file':
            # 文件级复选框被点击
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
        self._apply_filters()
        self.channels_changed.emit()

    def _on_context_menu(self, pos):
        """Show a per-channel right-click menu with 设为左轴 (set as the
        overlay primary/left-axis channel). The menu only appears on a
        channel row; file rows and empty space are ignored."""
        item = self.tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != 'channel':
            return
        _kind, fid, ch = data
        self.channel_context_menu_requested.emit()
        menu = QMenu(self.tree)
        menu.setObjectName("channelContextMenu")
        menu.setWindowFlags(
            menu.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        act_primary = menu.addAction("设为左轴")
        chosen = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if chosen is act_primary:
            self.primary_channel_requested.emit(fid, ch)

    def remove_file(self, fid):
        if fid in self._file_items:
            i = self._file_items.pop(fid);
            idx = self.tree.indexOfTopLevelItem(i)
            if idx >= 0: self.tree.takeTopLevelItem(idx)
        for k in [k for k in self._colors if k[0] == fid]: del self._colors[k]
        if fid in self._files: del self._files[fid]
        self._update_edit_enabled()
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

    def set_checked_channels(self, checked):
        """Batch-restore checked channels without emitting channels_changed."""
        wanted = set()
        for entry in checked or []:
            try:
                fid, ch = entry[:2]
            except (TypeError, ValueError):
                continue
            wanted.add((fid, ch))

        self._updating = True
        try:
            for fid, fi in self._file_items.items():
                all_checked = fi.childCount() > 0
                for i in range(fi.childCount()):
                    ci = fi.child(i)
                    data = ci.data(0, Qt.UserRole)
                    is_checked = bool(
                        data
                        and data[0] == 'channel'
                        and (data[1], data[2]) in wanted
                    )
                    ci.setCheckState(0, Qt.Checked if is_checked else Qt.Unchecked)
                    all_checked = all_checked and is_checked
                fi.setCheckState(0, Qt.Checked if all_checked else Qt.Unchecked)
        finally:
            self._updating = False
        self._apply_filters()

    def get_channel_colors(self):
        return dict(self._colors)

    def set_channel_colors(self, colors):
        valid_keys = set()
        for fi in self._file_items.values():
            for i in range(fi.childCount()):
                data = fi.child(i).data(0, Qt.UserRole)
                if data and data[0] == 'channel':
                    valid_keys.add((data[1], data[2]))
        self._colors = {
            key: color for key, color in self._colors.items() if key in valid_keys
        }

        for key, hex_color in (colors or {}).items():
            try:
                fid, ch = key
            except (TypeError, ValueError):
                continue
            if (fid, ch) not in valid_keys:
                continue
            self._colors[(fid, ch)] = hex_color

        for fi in self._file_items.values():
            for i in range(fi.childCount()):
                ci = fi.child(i)
                data = ci.data(0, Qt.UserRole)
                if not data or data[0] != 'channel':
                    continue
                key = (data[1], data[2])
                if key in self._colors:
                    ci.setIcon(0, _swatch_icon(self._colors[key]))

    def get_file_data(self, fid):
        return self._files.get(fid)

    def check_first_channel(self, fid):
        if fid in self._file_items:
            fi = self._file_items[fid]
            if fi.childCount() > 0:
                self._updating = True
                fi.child(0).setCheckState(0, Qt.Checked)
                self._updating = False
                self._apply_filters()
                self.channels_changed.emit()

    def _filter(self, txt):
        self._apply_filters()

    def _apply_filters(self, _checked=None):
        t = self.search.text().strip().lower()
        show_checked_only = self.btn_selected_only.isChecked()
        filtering = bool(t) or show_checked_only
        for fid, fi in self._file_items.items():
            v = 0
            for i in range(fi.childCount()):
                ci = fi.child(i);
                matches_text = not t or t in ci.text(0).lower()
                matches_checked = (
                    not show_checked_only
                    or ci.checkState(0) == Qt.Checked
                )
                m = matches_text and matches_checked
                ci.setHidden(not m);
                v += m
            fi.setHidden(v == 0 and filtering)
            if filtering and v > 0:
                fi.setExpanded(True)

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
        self._apply_filters()
        self.channels_changed.emit()

    def _none(self):
        self._updating = True
        for fi in self._file_items.values():
            fi.setCheckState(0, Qt.Unchecked)
            for i in range(fi.childCount()): fi.child(i).setCheckState(0, Qt.Unchecked)
        self._updating = False;
        self._apply_filters()
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
