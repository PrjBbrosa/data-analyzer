"""Reusable widgets: StatisticsPanel, MultiFileChannelWidget, Toast."""
import json
from collections import Counter

from PyQt5.QtWidgets import (
    QAbstractItemView,
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
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStackedLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import (
    Qt,
    QPropertyAnimation,
    QRect,
    QSettings,
    QSize,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QBrush, QFontMetrics, QIcon, QPainter, QPen, QPixmap

from ...ui_kit.icons import Icons, icon_device_pixel_ratio
from .. import hints
from ..axis_group_palette import axis_group_color
from .channel_config_bar import ChannelConfigBar


INTERNAL_FILE_FIDS_MIME = "application/x-tracelab-file-fids"


def _fmt_rate(fs):
    """Format a sample rate in Hz or kHz for display (≥1000 Hz → kHz)."""
    if fs >= 1000:
        return f"{fs / 1000:.1f} kHz"
    return f"{fs:.0f} Hz"


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
            # The stats key may be a composite (data_id, name) identity key
            # (canvas.get_statistics, multi-file same-name decouple); prefer the
            # human-readable display_label for the Channel column when present,
            # else fall back to the key itself (window.py's live strip passes
            # the plain display name as the key with no display_label).
            header = s.get('display_label', ch) if isinstance(s, dict) else ch
            self.tree.addTopLevelItem(QTreeWidgetItem(
                [header, f"{s['min']:.3g}", f"{s['max']:.3g}", f"{s['mean']:.3g}", f"{s['rms']:.3g}",
                 f"{s['std']:.3g}", f"{s['p2p']:.3g}"]))


class _ChannelLeafDelegate(QStyledItemDelegate):
    """Paint channel leaves with one invariant three-column geometry.

    ``QTreeWidgetItem`` delegates checkbox and icon layout to the platform
    style.  On macOS a selected row can therefore shift the native checkbox
    while its decoration icon and column-2 eye keep a different anchor.  A
    channel row is compact enough to own these three visual primitives, so
    paint them once here and leave parent/source rows on the native delegate.
    """

    CHECK_SIZE = 18
    SWATCH_BOX = 16
    EYE_BOX = 18
    LEFT_INSET = 6
    CHECK_TO_SWATCH_GAP = 6
    SWATCH_TO_TEXT_GAP = 4
    CELL_RIGHT_INSET = 7
    SELECTED_BG = QColor("#e8efff")
    TEXT = QColor("#111827")
    MUTED = QColor("#64748b")
    CHECK_BORDER = QColor("#b8c1ce")

    @staticmethod
    def _channel_data(index):
        """Read the identity stored on column zero for any sibling cell."""
        return index.sibling(index.row(), 0).data(Qt.UserRole)

    @classmethod
    def _is_channel(cls, index):
        data = cls._channel_data(index)
        return bool(data and data[0] == "channel")

    def channel_geometry(self, row_rect):
        """Return stable checkbox, swatch and text rects for column 0."""
        check = QRect(
            row_rect.left() + self.LEFT_INSET,
            row_rect.top() + (row_rect.height() - self.CHECK_SIZE) // 2,
            self.CHECK_SIZE,
            self.CHECK_SIZE,
        )
        swatch = QRect(
            check.right() + 1 + self.CHECK_TO_SWATCH_GAP,
            row_rect.top() + (row_rect.height() - self.SWATCH_BOX) // 2,
            self.SWATCH_BOX,
            self.SWATCH_BOX,
        )
        text = QRect(
            swatch.right() + 1 + self.SWATCH_TO_TEXT_GAP,
            row_rect.top(),
            max(0, row_rect.right() - self.CELL_RIGHT_INSET - swatch.right()
                - self.SWATCH_TO_TEXT_GAP),
            row_rect.height(),
        )
        return check, swatch, text

    def eye_geometry(self, row_rect):
        return QRect(
            row_rect.left() + (row_rect.width() - self.EYE_BOX) // 2,
            row_rect.top() + (row_rect.height() - self.EYE_BOX) // 2,
            self.EYE_BOX,
            self.EYE_BOX,
        )

    @staticmethod
    def _is_selected(option):
        return bool(option.state & QStyle.State_Selected)

    def _paint_checkbox(self, painter, rect, checked):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(self.CHECK_BORDER, 1.0))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 1.5, 1.5)
        if checked:
            painter.setPen(QPen(self.TEXT, 2.05, Qt.SolidLine, Qt.RoundCap,
                                Qt.RoundJoin))
            painter.drawLine(
                rect.left() + 4, rect.center().y(),
                rect.left() + 8, rect.bottom() - 4,
            )
            painter.drawLine(
                rect.left() + 8, rect.bottom() - 4,
                rect.right() - 4, rect.top() + 4,
            )
        painter.restore()

    def _paint_text(self, painter, rect, text, color, alignment, option):
        painter.save()
        painter.setFont(option.font)
        painter.setPen(color)
        metrics = QFontMetrics(option.font)
        painter.drawText(
            rect,
            alignment,
            metrics.elidedText(str(text or ""), Qt.ElideRight, rect.width()),
        )
        painter.restore()

    def paint(self, painter, option, index):
        if not self._is_channel(index):
            super().paint(painter, option, index)
            return

        column = index.column()
        selected = self._is_selected(option)
        if selected:
            painter.fillRect(option.rect, self.SELECTED_BG)

        if column == 0:
            check, swatch, text = self.channel_geometry(option.rect)
            self._paint_checkbox(
                painter,
                check,
                index.data(Qt.CheckStateRole) == Qt.Checked,
            )
            icon = index.data(Qt.DecorationRole)
            if isinstance(icon, QIcon) and not icon.isNull():
                icon.paint(painter, swatch, Qt.AlignCenter)
            self._paint_text(
                painter, text, index.data(Qt.DisplayRole), self.TEXT,
                Qt.AlignLeft | Qt.AlignVCenter, option,
            )
            return

        if column == 1:
            self._paint_text(
                painter,
                option.rect.adjusted(0, 0, -self.CELL_RIGHT_INSET, 0),
                index.data(Qt.DisplayRole),
                self.TEXT if selected else self.MUTED,
                Qt.AlignRight | Qt.AlignVCenter,
                option,
            )
            return

        if column == 2:
            icon = index.data(Qt.DecorationRole)
            if isinstance(icon, QIcon) and not icon.isNull():
                icon.paint(painter, self.eye_geometry(option.rect), Qt.AlignCenter)
            return

        super().paint(painter, option, index)


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
        self._owner = None  # set by MultiFileChannelWidget; drawBranches reads it
        self._channel_delegate = _ChannelLeafDelegate(self)
        self.setItemDelegate(self._channel_delegate)

    def _check_hit_rect(self, item, index):
        """Return the enlarged clickable rect for ``item``'s checkbox, or
        None if the row has no user-checkable column-0 box."""
        if not (item.flags() & Qt.ItemIsUserCheckable):
            return None
        data = item.data(0, Qt.UserRole)
        row = self.visualRect(index)
        if data and data[0] == "channel":
            indicator = self._channel_delegate.channel_geometry(row)[0]
            hit = indicator.adjusted(-self.HIT_PAD, 0, self.HIT_PAD, 0)
            hit.setTop(row.top())
            hit.setBottom(row.bottom())
            return hit
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
                    owner = getattr(self, "_owner", None)
                    if not (
                        owner is not None
                        and owner._set_selected_channel_checks(item, new_state)
                    ):
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
                    owner = getattr(self, "_owner", None)
                    if not (
                        owner is not None
                        and owner._set_selected_channel_checks(item, new_state)
                    ):
                        item.setCheckState(0, new_state)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def drawBranches(self, painter, rect, index):
        item = self.itemFromIndex(index)
        data = item.data(0, Qt.UserRole) if item is not None else None
        # 文件/源/采样率行：保留默认展开箭头。
        super().drawBranches(painter, rect, index)
        if not (data and data[0] == 'channel'):
            return
        # On macOS the native tree style leaves an independently painted grey
        # branch/indent gutter beside a selected leaf.  Its checkbox and text
        # do not actually move, but the split background makes the row look as
        # if it has shifted right.  Channel leaves have no expand/collapse
        # glyph, so repaint that gutter with the same selection colour used by
        # the item body before drawing an optional axis-group badge.
        if item.isSelected():
            painter.save()
            painter.fillRect(rect, QColor('#e8efff'))
            painter.restore()
        owner = self._owner
        if owner is None:
            return
        gid = owner.axis_group_for(data[1], data[2])
        if not gid:
            return
        self._paint_group_badge(painter, rect, gid)

    def _paint_group_badge(self, painter, rect, gid):
        """在缩进槽右端（紧贴勾选框前）画组徽标：组色圆角方块 + 白色组号。
        画在 rect 右端，与树深度无关，规避多层缩进导致的错位。"""
        side = 12
        x = rect.right() - side - 2
        y = rect.top() + (rect.height() - side) // 2
        badge = QRect(x, y, side, side)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(axis_group_color(gid))))
        painter.drawRoundedRect(badge, 3, 3)
        painter.setPen(QPen(QColor('#ffffff')))
        f = painter.font()
        f.setPointSizeF(7.5)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(badge, Qt.AlignCenter, str(gid))
        painter.restore()


class MultiFileChannelWidget(QWidget):
    channels_changed = pyqtSignal()
    visibility_changed = pyqtSignal(str, str, bool)
    # Emitted when the user picks 设为左轴 in a channel's right-click menu.
    # (fid, channel) — MainWindow makes that channel the overlay left axis.
    primary_channel_requested = pyqtSignal(str, str)
    channel_context_menu_requested = pyqtSignal()
    # Emitted when 编辑通道 (moved here from the top toolbar) is clicked.
    channel_editor_requested = pyqtSignal()
    # Emitted when overlay shared-axis groups change (merge/split).
    axis_groups_changed = pyqtSignal()
    files_attach_requested = pyqtSignal(object)
    files_detach_requested = pyqtSignal(object, str)
    MAX_CHANNELS_WARNING = 8  # 超过此数量时警告

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("channelCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self);
        layout.setContentsMargins(8, 8, 8, 8);
        layout.setSpacing(6)
        self.search = QLineEdit();
        self.search.setObjectName("channelSearch")
        self.search.setPlaceholderText("Filter channel...");
        self.search.textChanged.connect(self._filter);
        layout.addWidget(self.search)
        bl = QHBoxLayout()
        self.btn_all = QPushButton("全选")
        self.btn_all.setMaximumWidth(48)
        self.btn_all.setProperty("role", "tool")
        self.btn_all.clicked.connect(self._all)
        bl.addWidget(self.btn_all)
        self.btn_none = QPushButton("全不")
        self.btn_none.setMaximumWidth(48)
        self.btn_none.setProperty("role", "tool")
        self.btn_none.clicked.connect(self._none)
        bl.addWidget(self.btn_none)
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
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree._owner = self  # _CheckTolerantTree.drawBranches reads group state
        self.tree.setIndentation(16)  # 收窄默认~20；并复用为共轴徽标槽（Task 3）
        self.tree.setHeaderLabels(['Channel', 'Pts', '显示']);
        header = self.tree.header()
        # Channel column owns all spare width so long names aren't elided when
        # the dock is widened. Pts column auto-fits its 5-7 digit numbers.
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.resizeSection(2, 42)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tree.headerItem().setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        self.tree.headerItem().setTextAlignment(2, Qt.AlignCenter)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMouseTracking(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemEntered.connect(self._on_item_entered)
        self.tree.viewportEntered.connect(self._clear_detach_hover)
        # Right-click a channel row → 设为左轴 (overlay primary axis).
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree_stack_host = QWidget(self)
        self._tree_stack = QStackedLayout(self._tree_stack_host)
        self._tree_stack.setContentsMargins(0, 0, 0, 0)
        self._tree_stack.addWidget(self.tree)
        self.empty_state = QLabel(
            "当前 View 尚未加入文件\n从上方拖入文件，或开启自动加入",
            self._tree_stack_host,
        )
        self.empty_state.setObjectName("channelEmptyState")
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setWordWrap(True)
        self._tree_stack.addWidget(self.empty_state)
        layout.addWidget(self._tree_stack_host)
        self.config_bar = ChannelConfigBar(self)
        layout.addWidget(self.config_bar)
        self._file_items = {}   # fid -> QTreeWidgetItem (flat mode: top-level; nested mode: raster node)
        self._colors = {}
        self._files = {}
        self._attached_file_ids = []
        self._updating = False
        self._hover_detach_item = None
        self.setProperty("dropActive", False)
        # NEW: for nested (HEAD .hdf) mode
        self._source_items = {}  # filepath_str -> QTreeWidgetItem (top-level file node)
        self._raster_items = {}  # fid -> QTreeWidgetItem (raster subgroup node)
        self._axis_groups = {}      # (fid, ch) -> group_id:int
        self._axis_group_seq = 0
        # Per-TimeDomain-View projection. The persisted owner is ViewState;
        # this set is the live channel-tree copy for the currently focused View.
        self._hidden_channels = set()
        self.axis_groups_changed.connect(self.tree.viewport().update)
        self._sync_empty_state()

    def add_file(self, fid, fd):
        self._files[fid] = fd
        label_suffix = getattr(fd, 'label_suffix', '')

        if label_suffix:
            # NESTED MODE: source file node → raster subgroup → channel leaves
            fp = getattr(fd, 'filepath', None)
            fp_str = str(fp) if fp is not None else fid
            file_label = fp.stem if fp is not None else fp_str

            # Get or create file-level source node
            if fp_str not in self._source_items:
                source_item = QTreeWidgetItem([file_label, ""])
                if fp is not None:
                    source_item.setToolTip(0, fp.name)
                source_item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                source_item.setFlags(source_item.flags() | Qt.ItemIsUserCheckable)
                source_item.setCheckState(0, Qt.Unchecked)
                source_item.setData(0, Qt.UserRole, ('source', fp_str))
                source_item.setExpanded(True)
                font = source_item.font(0)
                font.setBold(True)
                source_item.setFont(0, font)
                self.tree.addTopLevelItem(source_item)
                self._source_items[fp_str] = source_item
            else:
                source_item = self._source_items[fp_str]

            # Create raster subgroup node
            n_rows = len(fd.data)
            raster_item = QTreeWidgetItem([_fmt_rate(fd.fs), str(n_rows)])
            raster_item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            raster_item.setFlags(raster_item.flags() | Qt.ItemIsUserCheckable)
            raster_item.setCheckState(0, Qt.Unchecked)
            raster_item.setData(0, Qt.UserRole, ('raster', fid))
            raster_item.setExpanded(True)
            raster_item.setToolTip(0, f"{n_rows} 行")
            font2 = raster_item.font(0)
            font2.setBold(True)
            raster_item.setFont(0, font2)
            source_item.addChild(raster_item)
            self._raster_items[fid] = raster_item

            # Add channel leaves under raster node
            palette = fd.get_color_palette()
            for i, ch in enumerate(fd.get_signal_channels()):
                color = palette[i % len(palette)]
                self._colors[(fid, ch)] = color
                ci = QTreeWidgetItem([ch, str(n_rows)])
                ci.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                ci.setTextAlignment(2, Qt.AlignCenter)
                ci.setFlags(ci.flags() | Qt.ItemIsUserCheckable)
                ci.setCheckState(0, Qt.Unchecked)
                ci.setData(0, Qt.UserRole, ('channel', fid, ch))
                ci.setIcon(0, _swatch_icon(color))
                ci.setForeground(0, QBrush(QColor('#111827')))
                ci.setForeground(1, QBrush(QColor('#64748b')))
                raster_item.addChild(ci)

            # Also store raster_item in _file_items for backwards-compat APIs
            self._file_items[fid] = raster_item

        else:
            # FLAT MODE: existing 2-level behavior (unchanged)
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
            fi.setData(0, Qt.UserRole, ('file', fid))
            fi.setExpanded(True)
            font = fi.font(0)
            font.setBold(True)
            fi.setFont(0, font)
            palette = fd.get_color_palette()
            for i, ch in enumerate(fd.get_signal_channels()):
                color = palette[i % len(palette)]
                self._colors[(fid, ch)] = color
                ci = QTreeWidgetItem([ch, str(len(fd.data))])
                ci.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                ci.setTextAlignment(2, Qt.AlignCenter)
                ci.setFlags(ci.flags() | Qt.ItemIsUserCheckable)
                ci.setCheckState(0, Qt.Unchecked)
                ci.setData(0, Qt.UserRole, ('channel', fid, ch))
                ci.setIcon(0, _swatch_icon(color))
                ci.setForeground(0, QBrush(QColor('#111827')))
                ci.setForeground(1, QBrush(QColor('#64748b')))
                fi.addChild(ci)
            self.tree.addTopLevelItem(fi)
            self._file_items[fid] = fi

        self._apply_filters()
        self._refresh_visibility_icons()
        self._update_edit_enabled()

    def get_attached_file_ids(self):
        return list(self._attached_file_ids)

    def set_attached_file_ids(self, fids):
        known = self._files
        self._attached_file_ids = [
            fid
            for fid in dict.fromkeys(str(value) for value in (fids or ()))
            if fid in known
        ]
        self._clear_detach_hover()
        self._apply_filters()
        self._sync_empty_state()

    def _file_fids_from_mime(self, mime):
        if mime is None or not mime.hasFormat(INTERNAL_FILE_FIDS_MIME):
            return ()
        try:
            payload = json.loads(
                bytes(mime.data(INTERNAL_FILE_FIDS_MIME)).decode("utf-8")
            )
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, list):
            return ()
        known = self._files
        return tuple(
            fid
            for fid in dict.fromkeys(
                value for value in payload if isinstance(value, str)
            )
            if fid in known
        )

    def dragEnterEvent(self, event):
        if self._file_fids_from_mime(event.mimeData()):
            self._set_drop_active(True)
            event.acceptProposedAction()
            return
        self._set_drop_active(False)
        event.ignore()

    def dragMoveEvent(self, event):
        if self._file_fids_from_mime(event.mimeData()):
            self._set_drop_active(True)
            event.acceptProposedAction()
            return
        self._set_drop_active(False)
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drop_active(False)
        event.accept()

    def dropEvent(self, event):
        self._set_drop_active(False)
        fids = self._file_fids_from_mime(event.mimeData())
        if not fids:
            event.ignore()
            return
        self.files_attach_requested.emit(fids)
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def _set_drop_active(self, active):
        self.setProperty("dropActive", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)

    def _sync_empty_state(self):
        has_attached = bool(self._attached_file_ids)
        self._tree_stack.setCurrentWidget(self.tree if has_attached else self.empty_state)
        for widget in (
            self.search,
            self.btn_all,
            self.btn_none,
            self.btn_selected_only,
            self.btn_edit,
        ):
            widget.setEnabled(has_attached)
        self._update_config_context()

    def _update_config_context(self):
        self.config_bar.set_context(
            has_checked=bool(self.get_checked_channels()),
            has_attached=bool(self._attached_file_ids),
        )

    def _is_item_attached(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return False
        attached = set(self._attached_file_ids)
        if data[0] in ('file', 'raster'):
            return str(data[1]) in attached
        if data[0] == 'channel':
            return str(data[1]) in attached
        if data[0] == 'source':
            return any(
                self._is_item_attached(item.child(idx))
                for idx in range(item.childCount())
            )
        return False

    def _fids_for_node(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return ()
        if data[0] in ('file', 'raster'):
            fids = (str(data[1]),)
        elif data[0] == 'source':
            fids = tuple(
                str(item.child(idx).data(0, Qt.UserRole)[1])
                for idx in range(item.childCount())
                if item.child(idx).data(0, Qt.UserRole)
                and item.child(idx).data(0, Qt.UserRole)[0] == 'raster'
            )
        else:
            return ()
        attached = set(self._attached_file_ids)
        return tuple(fid for fid in fids if fid in attached)

    def _on_item_entered(self, item, _column):
        if item is self._hover_detach_item:
            return
        self._clear_detach_hover()
        if not self._fids_for_node(item):
            return
        self._hover_detach_item = item
        item.setIcon(2, Icons.close_file())
        item.setToolTip(2, "从当前 View 移除")

    def _clear_detach_hover(self):
        item = self._hover_detach_item
        self._hover_detach_item = None
        if item is not None:
            item.setIcon(2, QIcon())
            item.setToolTip(2, "")

    def _update_edit_enabled(self):
        """编辑通道 is only meaningful with an attached file."""
        self.btn_edit.setEnabled(bool(self._attached_file_ids))

    def _iter_channel_items(self):
        def _walk(item):
            data = item.data(0, Qt.UserRole)
            if data and data[0] == 'channel':
                yield item
            for idx in range(item.childCount()):
                yield from _walk(item.child(idx))

        for idx in range(self.tree.topLevelItemCount()):
            yield from _walk(self.tree.topLevelItem(idx))

    def _channel_item_for(self, fid, channel):
        for item in self._iter_channel_items():
            data = item.data(0, Qt.UserRole)
            if data[1] == fid and data[2] == channel:
                return item
        return None

    def _sync_visibility_icon(self, item):
        data = item.data(0, Qt.UserRole)
        if not (data and data[0] == 'channel'):
            return
        key = (data[1], data[2])
        checked = item.checkState(0) == Qt.Checked
        previous = self._updating
        self._updating = True
        try:
            if not checked:
                item.setIcon(2, QIcon())
                item.setToolTip(2, '')
            elif key in self._hidden_channels:
                item.setIcon(2, Icons.eye_closed())
                item.setToolTip(2, '点击显示此通道（仅影响时域图）')
            else:
                item.setIcon(2, Icons.eye_open())
                item.setToolTip(2, '点击隐藏此通道（仅影响时域图）')
        finally:
            self._updating = previous

    def _refresh_visibility_icons(self):
        for item in self._iter_channel_items():
            self._sync_visibility_icon(item)

    def get_hidden_channels(self):
        return [
            (fid, channel)
            for fid, channel, _color in self.get_checked_channels()
            if (fid, channel) in self._hidden_channels
        ]

    def set_hidden_channels(self, hidden):
        checked = {
            (fid, channel)
            for fid, channel, _color in self.get_checked_channels()
        }
        wanted = set()
        for entry in hidden or []:
            try:
                fid, channel = entry[:2]
            except (TypeError, ValueError):
                continue
            key = (fid, channel)
            if key in checked:
                wanted.add(key)
        self._hidden_channels = wanted
        self._refresh_visibility_icons()

    def get_visible_checked_channels(self):
        return [
            row for row in self.get_checked_channels()
            if (row[0], row[1]) not in self._hidden_channels
        ]

    def set_channel_visible(self, fid, channel, visible, *, emit=True):
        item = self._channel_item_for(fid, channel)
        if item is None or item.checkState(0) != Qt.Checked:
            return False
        key = (fid, channel)
        flag = bool(visible)
        was_visible = key not in self._hidden_channels
        if flag:
            self._hidden_channels.discard(key)
        else:
            self._hidden_channels.add(key)
        self._sync_visibility_icon(item)
        changed = was_visible != flag
        if changed and emit:
            self.visibility_changed.emit(str(fid), str(channel), flag)
        return changed

    def set_time_visibility_available(self, available):
        self.tree.setColumnHidden(2, not bool(available))

    def _on_item_clicked(self, item, column):
        if column != 2:
            return
        data = item.data(0, Qt.UserRole)
        fids = self._fids_for_node(item)
        if fids:
            self.files_detach_requested.emit(fids, item.text(0))
            return
        if not (data and data[0] == 'channel'):
            return
        if item.checkState(0) != Qt.Checked:
            return
        key = (data[1], data[2])
        self.set_channel_visible(
            data[1], data[2], key in self._hidden_channels,
        )

    def _on_item_changed(self, item, col):
        # Column 2 also changes when the parent detach hover icon is painted.
        # Only column 0 owns checkbox membership; treating icon writes as
        # checkbox edits would recursively clear a whole grouped source.
        if self._updating or col != 0:
            return
        data = item.data(0, Qt.UserRole)

        def _discard_hidden_descendants(node):
            node_data = node.data(0, Qt.UserRole)
            if node_data and node_data[0] == 'channel':
                self._hidden_channels.discard((node_data[1], node_data[2]))
            for child_idx in range(node.childCount()):
                _discard_hidden_descendants(node.child(child_idx))

        if data and data[0] in ('file', 'source', 'raster'):
            checked = item.checkState(0) == Qt.Checked

            # Count all descendant channel leaves
            def _count_channels(node):
                total = 0
                for i in range(node.childCount()):
                    child = node.child(i)
                    cd = child.data(0, Qt.UserRole)
                    if cd and cd[0] == 'channel':
                        total += int(self._is_item_attached(child))
                    elif self._is_item_attached(child):
                        total += _count_channels(child)
                return total

            if checked:
                n_channels = _count_channels(item)
                if n_channels > self.MAX_CHANNELS_WARNING:
                    reply = QMessageBox.question(
                        self.tree, "确认",
                        f"该节点有 {n_channels} 个通道，全部勾选可能导致卡顿。\n确定要全选吗？",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        self._updating = True
                        item.setCheckState(0, Qt.Unchecked)
                        self._updating = False
                        return

            # Recursively set all descendant nodes
            def _set_all(node, state):
                for i in range(node.childCount()):
                    child = node.child(i)
                    if not self._is_item_attached(child):
                        continue
                    child.setCheckState(0, state)
                    _set_all(child, state)

            state = Qt.Checked if checked else Qt.Unchecked
            self._updating = True
            _set_all(item, state)
            self._updating = False
            _discard_hidden_descendants(item)
        elif data and data[0] == 'channel':
            # Checkbox membership changes always reset the display state: a
            # newly checked channel opens its eye; an unchecked channel cannot
            # retain an unreachable hidden marker.
            self._hidden_channels.discard((data[1], data[2]))

        self._refresh_visibility_icons()
        self._apply_filters()
        self._update_config_context()
        self.channels_changed.emit()

    def _on_context_menu(self, pos):
        """Right-click menu on a channel row: 设为左轴，以及（多选时）合并/拆分
        共轴组。文件行与空白处忽略。"""
        item = self.tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != 'channel':
            return
        _kind, fid, ch = data
        # 收集当前 Ctrl/Shift 多选中的通道键；若右键的行不在选区内，则只针对该行。
        sel_keys = []
        for it in self.tree.selectedItems():
            d = it.data(0, Qt.UserRole)
            if d and d[0] == 'channel':
                sel_keys.append((d[1], d[2]))
        if (fid, ch) not in sel_keys:
            sel_keys = [(fid, ch)]
        can_merge, can_split = self._axis_group_menu_plan(sel_keys)

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
        act_merge = menu.addAction("合并为共轴") if can_merge else None
        act_split = menu.addAction("拆分共轴组") if can_split else None
        if act_merge is not None:
            # The axis-group menu is actually opening with the 合并为共轴 item
            # present (multi-select) — retire the coaxis.merge discovery hint so
            # the footer stops rotating it. Shared default QSettings, the same
            # discovered set the chart-card hint system reads (see presets.py).
            hints.mark_discovered(QSettings(), "coaxis.merge")
        chosen = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_primary:
            self.primary_channel_requested.emit(fid, ch)
        elif act_merge is not None and chosen is act_merge:
            self.merge_axis_group(sel_keys)
        elif act_split is not None and chosen is act_split:
            self.split_axis_group(sel_keys)

    def remove_file(self, fid, *, emit=True):
        # Clean up colors and files dict
        for k in [k for k in self._colors if k[0] == fid]:
            del self._colors[k]
        if fid in self._files:
            del self._files[fid]
        for k in [k for k in self._axis_groups if k[0] == fid]:
            del self._axis_groups[k]
        self._hidden_channels = {
            key for key in self._hidden_channels if key[0] != fid
        }
        self._attached_file_ids = [
            attached for attached in self._attached_file_ids if attached != fid
        ]
        self._prune_axis_groups()

        # Check if nested (raster) or flat
        if fid in self._raster_items:
            raster_item = self._raster_items.pop(fid)
            parent = raster_item.parent()
            if parent is not None:
                parent.removeChild(raster_item)
                # If the source node has no more raster children, remove it
                if parent.childCount() == 0:
                    pdata = parent.data(0, Qt.UserRole)
                    if pdata and pdata[0] == 'source':
                        fp_str = pdata[1]
                        self._source_items.pop(fp_str, None)
                        idx = self.tree.indexOfTopLevelItem(parent)
                        if idx >= 0:
                            self.tree.takeTopLevelItem(idx)
            # Also clean up _file_items (which pointed to raster_item)
            self._file_items.pop(fid, None)
        elif fid in self._file_items:
            # Flat mode
            fi = self._file_items.pop(fid)
            idx = self.tree.indexOfTopLevelItem(fi)
            if idx >= 0:
                self.tree.takeTopLevelItem(idx)

        self._update_edit_enabled()
        self._apply_filters()
        self._sync_empty_state()
        if emit:
            self.channels_changed.emit()

    def get_checked_channels(self):
        result = []
        attached = set(self._attached_file_ids)
        for item in self._iter_channel_items():
            data = item.data(0, Qt.UserRole)
            if (
                str(data[1]) in attached
                and item.checkState(0) == Qt.Checked
            ):
                fid, ch = data[1], data[2]
                result.append((fid, ch, self._colors.get((fid, ch), '#1f77b4')))
        return result

    # ---- overlay shared-axis groups -------------------------------------
    def axis_group_for(self, fid, ch):
        return self._axis_groups.get((str(fid), str(ch)))

    def _new_axis_group_id(self):
        self._axis_group_seq += 1
        return self._axis_group_seq

    def merge_axis_group(self, keys):
        """Put ``keys`` (iterable of (fid, ch)) on one shared axis.

        If any key already belongs to a group, fold everything into the
        smallest such group id; else allocate a fresh id. Returns the group
        id, or None when fewer than 2 keys are given."""
        keys = [(str(f), str(c)) for (f, c) in keys]
        if len(keys) < 2:
            return None
        existing = sorted({self._axis_groups[k] for k in keys if k in self._axis_groups})
        gid = existing[0] if existing else self._new_axis_group_id()
        fold = set(existing[1:])
        if fold:
            for k, g in list(self._axis_groups.items()):
                if g in fold:
                    self._axis_groups[k] = gid
        for k in keys:
            self._axis_groups[k] = gid
        self._prune_axis_groups()
        self.axis_groups_changed.emit()
        return gid

    def split_axis_group(self, keys):
        """Remove ``keys`` from their groups; dissolve any group left < 2."""
        changed = False
        for (f, c) in keys:
            k = (str(f), str(c))
            if k in self._axis_groups:
                del self._axis_groups[k]
                changed = True
        if changed:
            self._prune_axis_groups()
            self.axis_groups_changed.emit()

    def _prune_axis_groups(self):
        counts = Counter(self._axis_groups.values())
        for k, g in list(self._axis_groups.items()):
            if counts[g] < 2:
                del self._axis_groups[k]
        self._renumber_axis_groups()

    def _renumber_axis_groups(self):
        """Keep group badges compact after split/delete operations."""
        live = sorted(set(self._axis_groups.values()))
        mapping = {old: idx + 1 for idx, old in enumerate(live)}
        if mapping:
            for k, g in list(self._axis_groups.items()):
                self._axis_groups[k] = mapping[g]
            self._axis_group_seq = max(mapping.values())
        else:
            self._axis_group_seq = 0

    @staticmethod
    def _effective_groups(axis_groups, checked_keys):
        """Restrict groups to checked channels and drop singleton groups."""
        eff = {k: g for k, g in axis_groups.items() if k in checked_keys}
        counts = Counter(eff.values())
        return {k: g for k, g in eff.items() if counts[g] >= 2}

    def checked_axis_groups(self):
        checked = {(f, c) for (f, c, _color) in self.get_checked_channels()}
        return self._effective_groups(self._axis_groups, checked)

    def _axis_group_menu_plan(self, sel_keys):
        """(can_merge, can_split) for the right-click menu (Task 2)."""
        sel = [(str(f), str(c)) for (f, c) in sel_keys]
        can_merge = len(sel) >= 2
        can_split = any(k in self._axis_groups for k in sel)
        return can_merge, can_split

    def _confirm_selected_channel_checks(self, count, state):
        checking = state == Qt.Checked
        box = QMessageBox(self.tree)
        box.setWindowTitle('批量操作确认')
        box.setIcon(QMessageBox.Question)
        if checking:
            box.setText(f'当前选中了 {count} 个通道，是否将它们全部勾选并显示？')
            confirm_text = '全部勾选并显示'
        else:
            box.setText(
                f'当前选中了 {count} 个通道，'
                '是否将它们全部取消勾选并从当前视图移除？'
            )
            confirm_text = '全部取消勾选'
        confirm = box.addButton(confirm_text, QMessageBox.AcceptRole)
        cancel = box.addButton('取消操作', QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        return box.clickedButton() is confirm

    def _set_selected_channel_checks(self, clicked_item, state):
        """Batch-toggle selected channel rows when their checkbox is clicked."""
        data = clicked_item.data(0, Qt.UserRole)
        if not (data and data[0] == 'channel' and clicked_item.isSelected()):
            return False
        items = []
        seen = set()
        for item in self.tree.selectedItems():
            d = item.data(0, Qt.UserRole)
            if not (d and d[0] == 'channel'):
                continue
            key = (d[1], d[2])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
        if clicked_item not in items:
            items.append(clicked_item)
        if len(items) < 2:
            return False
        if not self._confirm_selected_channel_checks(len(items), state):
            # The custom checkbox hit path must still consume the click. False
            # here would fall through to Qt's native toggle and mutate the
            # clicked row after the user explicitly cancelled the batch.
            return True

        self._updating = True
        try:
            for item in items:
                item.setCheckState(0, state)
                data = item.data(0, Qt.UserRole)
                self._hidden_channels.discard((data[1], data[2]))
        finally:
            self._updating = False
        self._refresh_visibility_icons()
        self._apply_filters()
        self.channels_changed.emit()
        return True

    def set_checked_channels(self, checked):
        """Batch-restore checked channels without emitting channels_changed."""
        attached = set(self._attached_file_ids)
        wanted = set()
        for entry in checked or []:
            try:
                fid, ch = entry[:2]
            except (TypeError, ValueError):
                continue
            if str(fid) in attached:
                wanted.add((fid, ch))

        # Preserve hidden state only for channels that remain checked. Newly
        # checked rows therefore default to visible; removed rows cannot leave
        # stale hidden references behind.
        self._hidden_channels.intersection_update(wanted)

        self._updating = True
        try:
            def _set_in_subtree(item):
                data = item.data(0, Qt.UserRole)
                if data and data[0] == 'channel':
                    is_checked = (data[1], data[2]) in wanted
                    item.setCheckState(0, Qt.Checked if is_checked else Qt.Unchecked)
                else:
                    for i in range(item.childCount()):
                        _set_in_subtree(item.child(i))
                    # Update container check state based on descendants
                    if item.childCount() > 0:
                        all_ch = True
                        any_ch = False

                        def _check_leaves(node):
                            nonlocal all_ch, any_ch
                            for i in range(node.childCount()):
                                c = node.child(i)
                                if not self._is_item_attached(c):
                                    continue
                                cd = c.data(0, Qt.UserRole)
                                if cd and cd[0] == 'channel':
                                    st = c.checkState(0) == Qt.Checked
                                    all_ch = all_ch and st
                                    any_ch = any_ch or st
                                else:
                                    _check_leaves(c)

                        all_ch = True
                        any_ch = False
                        _check_leaves(item)
                        item.setCheckState(0, Qt.Checked if all_ch else Qt.Unchecked)

            for i in range(self.tree.topLevelItemCount()):
                _set_in_subtree(self.tree.topLevelItem(i))
        finally:
            self._updating = False
        self._refresh_visibility_icons()
        self._apply_filters()
        self._update_config_context()

    def get_channel_colors(self):
        return dict(self._colors)

    def set_channel_colors(self, colors):
        # Rebuild valid_keys from all channel leaves in tree
        valid_keys = set()

        def _collect_keys(item):
            data = item.data(0, Qt.UserRole)
            if data and data[0] == 'channel':
                valid_keys.add((data[1], data[2]))
            for i in range(item.childCount()):
                _collect_keys(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            _collect_keys(self.tree.topLevelItem(i))

        self._colors = {k: v for k, v in self._colors.items() if k in valid_keys}
        for key, hex_color in (colors or {}).items():
            try:
                fid, ch = key
            except (TypeError, ValueError):
                continue
            if (fid, ch) not in valid_keys:
                continue
            self._colors[(fid, ch)] = hex_color

        # Update icons in tree. ``setIcon`` mutates item data, so QTreeWidget
        # fires ``itemChanged`` — which ``_on_item_changed`` turns into a
        # ``channels_changed`` emit (a full time-domain replot). A color swatch
        # is display-only and must never trigger a replot, so gate the icon
        # writes behind ``_updating`` (the same guard the check-state cascade
        # uses); save/restore keeps any nested caller's flag intact.
        def _update_icons(item):
            data = item.data(0, Qt.UserRole)
            if data and data[0] == 'channel':
                key = (data[1], data[2])
                if key in self._colors:
                    item.setIcon(0, _swatch_icon(self._colors[key]))
            for i in range(item.childCount()):
                _update_icons(item.child(i))

        prev_updating = self._updating
        self._updating = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                _update_icons(self.tree.topLevelItem(i))
        finally:
            self._updating = prev_updating

    def get_file_data(self, fid):
        return self._files.get(fid)

    def check_first_channel(self, fid):
        if str(fid) not in set(self._attached_file_ids):
            return
        if fid in self._raster_items:
            ri = self._raster_items[fid]
            if ri.childCount() > 0:
                self._updating = True
                ri.child(0).setCheckState(0, Qt.Checked)
                self._updating = False
                data = ri.child(0).data(0, Qt.UserRole)
                self._hidden_channels.discard((data[1], data[2]))
                self._refresh_visibility_icons()
                self._apply_filters()
                self.channels_changed.emit()
        elif fid in self._file_items:
            fi = self._file_items[fid]
            if fi.childCount() > 0:
                self._updating = True
                fi.child(0).setCheckState(0, Qt.Checked)
                self._updating = False
                data = fi.child(0).data(0, Qt.UserRole)
                self._hidden_channels.discard((data[1], data[2]))
                self._refresh_visibility_icons()
                self._apply_filters()
                self.channels_changed.emit()

    def _filter(self, txt):
        self._apply_filters()

    def _apply_filters(self, _checked=None):
        t = self.search.text().strip().lower()
        show_checked_only = self.btn_selected_only.isChecked()
        filtering = bool(t) or show_checked_only

        def _apply_to_node(item):
            data = item.data(0, Qt.UserRole)
            if data and data[0] == 'channel':
                if not self._is_item_attached(item):
                    item.setHidden(True)
                    return False
                matches_text = not t or t in item.text(0).lower()
                matches_checked = not show_checked_only or item.checkState(0) == Qt.Checked
                visible = matches_text and matches_checked
                item.setHidden(not visible)
                return visible
            else:
                if data and data[0] in ('file', 'raster') and not self._is_item_attached(item):
                    item.setHidden(True)
                    for idx in range(item.childCount()):
                        _apply_to_node(item.child(idx))
                    return False
                # Container node: visible if any child is visible
                visible_children = 0
                for i in range(item.childCount()):
                    if _apply_to_node(item.child(i)):
                        visible_children += 1
                attached = self._is_item_attached(item)
                hide = not attached or (visible_children == 0 and filtering)
                item.setHidden(hide)
                if filtering and visible_children > 0:
                    item.setExpanded(True)
                return visible_children > 0

        for i in range(self.tree.topLevelItemCount()):
            _apply_to_node(self.tree.topLevelItem(i))

    def _all(self):
        # Count total visible channel leaves across the whole tree
        def _count_visible_channels(item):
            data = item.data(0, Qt.UserRole)
            if data and data[0] == 'channel':
                return 0 if item.isHidden() or not self._is_item_attached(item) else 1
            total = 0
            for i in range(item.childCount()):
                total += _count_visible_channels(item.child(i))
            return total

        total = sum(
            _count_visible_channels(self.tree.topLevelItem(i))
            for i in range(self.tree.topLevelItemCount())
        )

        if total > self.MAX_CHANNELS_WARNING:
            reply = QMessageBox.question(
                self.tree, "确认",
                f"共有 {total} 个通道，全部勾选可能导致卡顿。\n确定要全选吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self._updating = True

        def _check_visible(item):
            data = item.data(0, Qt.UserRole)
            if data and data[0] == 'channel':
                if not item.isHidden() and self._is_item_attached(item):
                    item.setCheckState(0, Qt.Checked)
                    data = item.data(0, Qt.UserRole)
                    self._hidden_channels.discard((data[1], data[2]))
            else:
                for i in range(item.childCount()):
                    _check_visible(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            _check_visible(self.tree.topLevelItem(i))
        self._updating = False
        self._refresh_visibility_icons()
        self._apply_filters()
        self._update_config_context()
        self.channels_changed.emit()

    def _none(self):
        self._updating = True
        self._hidden_channels.clear()

        def _uncheck_all(item):
            if self._is_item_attached(item):
                item.setCheckState(0, Qt.Unchecked)
            for i in range(item.childCount()):
                _uncheck_all(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            _uncheck_all(self.tree.topLevelItem(i))
        self._updating = False
        self._refresh_visibility_icons()
        self._apply_filters()
        self._update_config_context()
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
