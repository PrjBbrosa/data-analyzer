"""The multi-file channel tree: MultiFileChannelWidget and its private helpers."""
import json
import logging
import sys
from collections import Counter
from collections.abc import Mapping, Sequence

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QDrag,
    QFontMetrics,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
)
from PyQt5.QtCore import (
    Qt,
    QEvent,
    QMimeData,
    QPoint,
    QRect,
    QSettings,
    QSize,
    pyqtSignal,
)

from ...ui_kit.icons import Icons
from ...ui_kit.message_box_buttons import fit_message_box_buttons_to_text
from ...ui_kit.widgets import SearchField
from .. import hints
from ..axis_group_palette import axis_group_color
from ..channel_drag import (
    INTERNAL_CHANNEL_MIME,
    decode_channel_drag,
    encode_channel_drag,
)
from .channel_config_bar import ChannelConfigBar
# ``MultiFileChannelWidget`` resolves these through *this* module's globals, so
# a dev script that swaps the swatch renderer must rebind them here.
from ._swatches import _fmt_rate, _swatch_icon


INTERNAL_FILE_FIDS_MIME = "application/x-tracelab-file-fids"
logger = logging.getLogger(__name__)
_CHANNEL_ORDER_BEFORE = "before"
_CHANNEL_ORDER_AFTER = "after"
RECORD_GROUP_KIND = "record_group"
RECORD_BINDING_KIND = "record_binding"
RECORD_GROUP_TAG = "WinWert 原始记录"
_RECORD_KINDS = (RECORD_GROUP_KIND, RECORD_BINDING_KIND)


def _channel_tip(channel, fd):
    """Full channel name (+ unit) for the row's column-0 tooltip.

    The Channel column stretches but stays narrow at the default dock width,
    so long names are elided. Without a tooltip an elided name was simply
    unreadable — the HEAD files in this domain routinely carry 20+ character
    names whose distinguishing part is a trailing ``_DV`` / ``_PV`` / ``_VT``
    suffix, which is exactly what elision eats.
    """
    unit = ""
    try:
        unit = (getattr(fd, "channel_units", None) or {}).get(channel) or ""
    except Exception:
        unit = ""
    return f"{channel} [{unit}]" if unit else str(channel)


def _zeit_record_indices(fd) -> tuple[int, ...]:
    smeta = getattr(fd, "source_metadata", None) or {}
    raw = smeta.get("zeit_record_indices") or ()
    out = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def grouped_source_raster_label(fd) -> str:
    """Grouped-source raster text. WWT rows include a stable Zeit id."""
    rate = _fmt_rate(getattr(fd, "fs", 0.0) or 0.0)
    smeta = getattr(fd, "source_metadata", None) or {}
    if str(smeta.get("source_kind") or "") != "wwt":
        return rate
    zeit = _zeit_record_indices(fd)
    if not zeit:
        return rate
    if len(zeit) == 1:
        return f"{rate} · Zeit {zeit[0]}"
    if len(zeit) == 2:
        return f"{rate} · Zeit {zeit[0]}/{zeit[1]}"
    return f"{rate} · Zeit {zeit[0]}–{zeit[-1]}"


def grouped_source_raster_tooltip(fd) -> str:
    data = getattr(fd, "data", None)
    n_rows = 0 if data is None else len(data)
    smeta = getattr(fd, "source_metadata", None) or {}
    if str(smeta.get("source_kind") or "") != "wwt":
        return f"{n_rows} 行"
    channels = []
    getter = getattr(fd, "get_signal_channels", None)
    if callable(getter):
        channels = list(getter() or [])
    cmeta = getattr(fd, "channel_metadata", None) or {}
    n_formula = sum(
        1
        for meta in cmeta.values()
        if isinstance(meta, dict) and meta.get("derived")
    )
    zeit = _zeit_record_indices(fd)
    zeit_text = ", ".join(str(i) for i in zeit) if zeit else "—"
    return (
        f"Zeit 记录: {zeit_text}\n"
        f"样本数: {n_rows}\n"
        f"通道数: {len(channels)}\n"
        f"已注入 Pars 公式通道: {n_formula}"
    )


class _ChannelLeafDelegate(QStyledItemDelegate):
    """Paint channel leaves with one invariant three-column geometry.

    ``QTreeWidgetItem`` delegates checkbox and icon layout to the platform
    style.  On macOS a selected checkable row can therefore shift the native
    checkbox / QSS-padded ``option.rect`` while its decoration and Pts cell
    keep a different anchor.  Every role (time / fft_sources /
    analysis_candidates) paints from the view's ``visualRect`` with fixed
    insets so selection never changes the box, text, or Pts right edge.
    """

    CHECK_SIZE = 18
    SWATCH_BOX = 16
    EYE_BOX = 18
    LEFT_INSET = 6
    CHECK_TO_SWATCH_GAP = 6
    SWATCH_TO_TEXT_GAP = 4
    PARENT_TEXT_GAP = 9
    CELL_RIGHT_INSET = 7
    PTS_LEFT_INSET = 4
    SELECTED_BG = QColor("#b7d3f2")
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

    @classmethod
    def _is_record_binding(cls, index):
        data = cls._channel_data(index)
        return bool(data and data[0] == RECORD_BINDING_KIND)

    @classmethod
    def _is_record_group(cls, index):
        data = cls._channel_data(index)
        return bool(data and data[0] == RECORD_GROUP_KIND)

    def initStyleOption(self, option, index):
        """Drop native check/decoration slots; we paint both ourselves."""
        super().initStyleOption(option, index)
        data = self._channel_data(index)
        if data and data[0] in (
            "channel", "file", "source", "raster",
            RECORD_GROUP_KIND, RECORD_BINDING_KIND,
        ):
            option.features &= ~QStyleOptionViewItem.HasCheckIndicator
            option.features &= ~QStyleOptionViewItem.HasDecoration
            option.icon = QIcon()

    def _stable_cell_rect(self, option, index):
        """Content band for custom painting.

        Prefer ``option.rect`` (the rect the view asked us to paint). After
        clearing HasCheckIndicator and horizontal QSS padding it stays
        selection-stable, and it stays out of the branch gutter — using
        ``visualRect`` alone could place a top-level file checkbox under the
        expander on macOS so the box looked "gone".
        """
        opt = QRect(option.rect)
        if opt.isValid() and opt.width() > 0 and opt.height() > 0:
            return opt
        widget = option.widget or self.parent()
        if widget is not None and hasattr(widget, "visualRect"):
            rect = widget.visualRect(index)
            if rect.isValid() and rect.width() > 0 and rect.height() > 0:
                return QRect(rect)
        return opt

    @staticmethod
    def _row_shows_checkbox(index):
        """Match parent/channel chrome: only UserCheckable rows get a box."""
        return bool(index.flags() & Qt.ItemIsUserCheckable)

    def channel_geometry(self, row_rect, *, with_checkbox=True):
        """Return stable checkbox/swatch/text rects for column 0."""
        if with_checkbox:
            check = QRect(
                row_rect.left() + self.LEFT_INSET,
                row_rect.top() + (row_rect.height() - self.CHECK_SIZE) // 2,
                self.CHECK_SIZE,
                self.CHECK_SIZE,
            )
            swatch_left = check.right() + 1 + self.CHECK_TO_SWATCH_GAP
        else:
            check = QRect()
            swatch_left = row_rect.left() + self.LEFT_INSET
        swatch = QRect(
            swatch_left,
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

    def parent_geometry(self, row_rect):
        """Return stable checkbox/text rects for file/source/raster rows.

        The native macOS item delegate applies a different decoration inset
        while a parent row is selected.  Keeping the checkbox in the same
        indentation slot as its unselected siblings also keeps the click band
        predictable for nested source/raster trees.
        """
        check = QRect(
            row_rect.left() + self.LEFT_INSET,
            row_rect.top() + (row_rect.height() - self.CHECK_SIZE) // 2,
            self.CHECK_SIZE,
            self.CHECK_SIZE,
        )
        text = QRect(
            check.right() + 1 + self.PARENT_TEXT_GAP,
            row_rect.top(),
            max(0, row_rect.right() - self.CELL_RIGHT_INSET
                - check.right() - self.PARENT_TEXT_GAP),
            row_rect.height(),
        )
        return check, text

    def pts_geometry(self, row_rect):
        """Right-aligned Pts band with a selection-invariant right inset."""
        return row_rect.adjusted(
            self.PTS_LEFT_INSET, 0, -self.CELL_RIGHT_INSET, 0,
        )

    def column_action_geometry(self, row_rect):
        """Center a row action inside the fixed display column."""
        return QRect(
            row_rect.left() + (row_rect.width() - self.EYE_BOX) // 2,
            row_rect.top() + (row_rect.height() - self.EYE_BOX) // 2,
            self.EYE_BOX,
            self.EYE_BOX,
        )

    def eye_geometry(self, row_rect):
        return self.column_action_geometry(row_rect)

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

    def _item_paint_option(self, option, index, cell_rect):
        """Keep item-level font/metrics while locking geometry to ``cell_rect``."""
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.rect = QRect(cell_rect)
        styled.state = option.state
        return styled

    def _fill_selected(self, painter, option, cell_rect):
        if not self._is_selected(option):
            return
        painter.fillRect(cell_rect, self.SELECTED_BG)
        if option.rect != cell_rect:
            painter.fillRect(option.rect, self.SELECTED_BG)

    def _paint_checkable_parent(self, painter, option, index, cell_rect):
        """Paint a file/source/raster cell without platform inset drift."""
        styled = self._item_paint_option(option, index, cell_rect)
        self._fill_selected(painter, option, cell_rect)
        check, text = self.parent_geometry(cell_rect)
        self._paint_checkbox(
            painter,
            check,
            index.data(Qt.CheckStateRole) == Qt.Checked,
        )
        self._paint_text(
            painter,
            text,
            index.data(Qt.DisplayRole),
            self.TEXT,
            Qt.AlignLeft | Qt.AlignVCenter,
            styled,
            elide=Qt.ElideMiddle,
        )

    def _paint_plain_parent(self, painter, option, index, cell_rect):
        """Non-checkable file/source/raster label with the same left inset."""
        styled = self._item_paint_option(option, index, cell_rect)
        self._fill_selected(painter, option, cell_rect)
        text = QRect(
            cell_rect.left() + self.LEFT_INSET,
            cell_rect.top(),
            max(0, cell_rect.width() - self.LEFT_INSET - self.CELL_RIGHT_INSET),
            cell_rect.height(),
        )
        self._paint_text(
            painter,
            text,
            index.data(Qt.DisplayRole),
            self.TEXT,
            Qt.AlignLeft | Qt.AlignVCenter,
            styled,
            elide=Qt.ElideMiddle,
        )

    def _paint_pts(self, painter, option, index, cell_rect):
        styled = self._item_paint_option(option, index, cell_rect)
        self._fill_selected(painter, option, cell_rect)
        self._paint_text(
            painter,
            self.pts_geometry(cell_rect),
            index.data(Qt.DisplayRole),
            self.TEXT if self._is_selected(option) else self.MUTED,
            Qt.AlignRight | Qt.AlignVCenter,
            styled,
        )

    def _paint_text(self, painter, rect, text, color, alignment, option,
                    elide=Qt.ElideRight):
        painter.save()
        painter.setFont(option.font)
        painter.setPen(color)
        metrics = QFontMetrics(option.font)
        painter.drawText(
            rect,
            alignment,
            metrics.elidedText(str(text or ""), elide, rect.width()),
        )
        painter.restore()

    def paint(self, painter, option, index):
        cell = self._stable_cell_rect(option, index)
        data = self._channel_data(index)
        column = index.column()

        # Pts is role-agnostic: every row type uses the same right edge so
        # selection / projection switches cannot nudge the numbers sideways.
        if column == 1:
            self._paint_pts(painter, option, index, cell)
            return

        if self._is_record_group(index):
            if column == 0:
                self._paint_plain_parent(painter, option, index, cell)
            elif column == 2:
                self._fill_selected(painter, option, cell)
            else:
                super().paint(painter, option, index)
            return

        if self._is_record_binding(index):
            styled = self._item_paint_option(option, index, cell)
            self._fill_selected(painter, option, cell)
            if column == 0:
                _check, swatch, text = self.channel_geometry(
                    cell, with_checkbox=False,
                )
                icon = index.data(Qt.DecorationRole)
                if isinstance(icon, QIcon) and not icon.isNull():
                    icon.paint(painter, swatch, Qt.AlignCenter)
                self._paint_text(
                    painter, text, index.data(Qt.DisplayRole), self.TEXT,
                    Qt.AlignLeft | Qt.AlignVCenter, styled,
                    elide=Qt.ElideMiddle,
                )
            elif column == 2:
                icon = index.data(Qt.DecorationRole)
                if isinstance(icon, QIcon) and not icon.isNull():
                    icon.paint(painter, self.eye_geometry(cell), Qt.AlignCenter)
            else:
                super().paint(painter, option, index)
            return

        if not self._is_channel(index):
            if (
                column == 0
                and data
                and data[0] in ("file", "source", "raster")
            ):
                if self._row_shows_checkbox(index):
                    self._paint_checkable_parent(painter, option, index, cell)
                else:
                    self._paint_plain_parent(painter, option, index, cell)
                return
            icon = index.data(Qt.DecorationRole)
            if (column == 2 and isinstance(icon, QIcon)
                    and not icon.isNull()):
                # File/raster detach used to follow the native decoration
                # inset, then later CE_ItemViewItem so the red x sat on the
                # same centerline as channel eyes. That style fill also
                # applied ::item:selected's per-cell radius, turning the
                # display column into a detached pill. Paint the same
                # rectangular selected fill as the other columns, then the
                # icon on the shared action geometry.
                self._fill_selected(painter, option, cell)
                icon.paint(
                    painter,
                    self.column_action_geometry(cell),
                    Qt.AlignCenter,
                )
                return
            super().paint(painter, option, index)
            return

        styled = self._item_paint_option(option, index, cell)
        self._fill_selected(painter, option, cell)

        if column == 0:
            show_check = self._row_shows_checkbox(index)
            check, swatch, text = self.channel_geometry(
                cell, with_checkbox=show_check,
            )
            if show_check:
                self._paint_checkbox(
                    painter,
                    check,
                    index.data(Qt.CheckStateRole) == Qt.Checked,
                )
            icon = index.data(Qt.DecorationRole)
            if isinstance(icon, QIcon) and not icon.isNull():
                icon.paint(painter, swatch, Qt.AlignCenter)
            # Elide the middle, not the tail: measurement channels in this
            # domain differ only by a trailing suffix (Com_Motor_Torque_DV vs
            # _PV vs _VT), so ElideRight collapses distinct channels into
            # identical-looking rows. Keeping both ends readable is what makes
            # a narrow column still usable; the tooltip carries the full name.
            self._paint_text(
                painter, text, index.data(Qt.DisplayRole), self.TEXT,
                Qt.AlignLeft | Qt.AlignVCenter, styled,
                elide=Qt.ElideMiddle,
            )
            return

        if column == 2:
            icon = index.data(Qt.DecorationRole)
            if isinstance(icon, QIcon) and not icon.isNull():
                icon.paint(painter, self.eye_geometry(cell), Qt.AlignCenter)
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
        self._drag_press_pos = None
        self._drag_channel = None
        self._drag_file_press_pos = None
        self._drag_file_anchor_fid = None
        self._channel_delegate = _ChannelLeafDelegate(self)
        # Darwin-only: selected-row tint washes out Fusion's branch glyph, so
        # drawBranches overpaints a dark chevron in the branch slot. Kept as a
        # platform gate (not a QStyle handle) — QMacStyle.PE_IndicatorBranch
        # can Abort under restricted offscreen hosts.
        self._repaint_selected_expander = sys.platform == "darwin"
        self.setItemDelegate(self._channel_delegate)

    def _check_hit_rect(self, item, index):
        """Return the enlarged clickable rect for ``item``'s checkbox, or
        None if the row has no user-checkable column-0 box."""
        if not (item.flags() & Qt.ItemIsUserCheckable):
            return None
        data = item.data(0, Qt.UserRole)
        if data and data[0] in _RECORD_KINDS:
            return None
        row = self.visualRect(index)
        if data and data[0] == "channel":
            indicator = self._channel_delegate.channel_geometry(row)[0]
            hit = indicator.adjusted(-self.HIT_PAD, 0, self.HIT_PAD, 0)
            hit.setTop(row.top())
            hit.setBottom(row.bottom())
            return hit
        if data and data[0] in ("file", "source", "raster"):
            indicator = self._channel_delegate.parent_geometry(row)[0]
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
            self._clear_channel_drag_candidate()
            self._clear_file_drag_candidate()
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
                if self._is_channel_body_press(item, pos):
                    data = item.data(0, Qt.UserRole)
                    self._drag_press_pos = QPoint(pos)
                    self._drag_channel = (str(data[1]), str(data[2]))
                elif self._is_file_body_press(item, pos):
                    anchor_fid = self._file_anchor_for_item(item)
                    if anchor_fid is not None:
                        self._drag_file_press_pos = QPoint(pos)
                        self._drag_file_anchor_fid = anchor_fid
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._consume_check_release:
            self._consume_check_release = False
            self._clear_channel_drag_candidate()
            self._clear_file_drag_candidate()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._clear_channel_drag_candidate()
            self._clear_file_drag_candidate()
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        """Keep a left-button row drag from extending the tree selection."""
        if event.buttons() & Qt.LeftButton:
            if self._maybe_start_channel_drag(event):
                event.accept()
                return
            if self._maybe_start_file_drag(event):
                event.accept()
                return
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _clear_channel_drag_candidate(self):
        self._drag_press_pos = None
        self._drag_channel = None

    def _clear_file_drag_candidate(self):
        self._drag_file_press_pos = None
        self._drag_file_anchor_fid = None

    def _is_channel_body_press(self, item, pos):
        if item is None or self.columnAt(pos.x()) != 0:
            return False
        data = item.data(0, Qt.UserRole)
        return bool(data and data[0] == "channel")

    def _file_anchor_for_item(self, item):
        """Return one logical-source id for a draggable top-level file node."""
        if item is None or item.parent() is not None:
            return None
        data = item.data(0, Qt.UserRole)
        if not data:
            return None
        if data[0] == "file":
            return str(data[1])
        if data[0] != "source":
            return None
        for index in range(item.childCount()):
            child_data = item.child(index).data(0, Qt.UserRole)
            if child_data and child_data[0] == "raster":
                return str(child_data[1])
        return None

    def _is_file_body_press(self, item, pos):
        if item is None or self.columnAt(pos.x()) != 0:
            return False
        if self._file_anchor_for_item(item) is None:
            return False
        index = self.indexFromItem(item, 0)
        checkbox = self._check_hit_rect(item, index)
        # The expander lives left of the checkbox. Starting only after the
        # enlarged checkbox band keeps expand/collapse and selection gestures
        # independent from the file-order drag source.
        return checkbox is not None and pos.x() > checkbox.right()

    def _maybe_start_channel_drag(self, event):
        if self._drag_channel is None or self._drag_press_pos is None:
            return False
        if (
            (event.pos() - self._drag_press_pos).manhattanLength()
            < QApplication.startDragDistance()
        ):
            return False
        fid, channel = self._drag_channel
        self._clear_channel_drag_candidate()
        owner = getattr(self, "_owner", None)
        if owner is None:
            return False
        owner._start_channel_drag(fid, channel)
        return True

    def _maybe_start_file_drag(self, event):
        if self._drag_file_anchor_fid is None or self._drag_file_press_pos is None:
            return False
        if (
            (event.pos() - self._drag_file_press_pos).manhattanLength()
            < QApplication.startDragDistance()
        ):
            return False
        anchor_fid = self._drag_file_anchor_fid
        self._clear_file_drag_candidate()
        owner = getattr(self, "_owner", None)
        if owner is None or not owner._tree_file_reorder_allowed():
            return False
        owner._start_tree_file_drag(anchor_fid)
        return True

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
        super().drawBranches(painter, rect, index)
        selected = item is not None and item.isSelected()
        is_parent = bool(
            data and data[0] in ('file', 'source', 'raster', RECORD_GROUP_KIND)
        )
        is_channel = bool(data and data[0] == 'channel')
        is_record_binding = bool(data and data[0] == RECORD_BINDING_KIND)
        # Flatten the branch slot to the same rectangular selected fill as
        # the item body. Channel leaves have no expander, so always overwrite
        # the native grey gutter. Darwin selected parents also overwrite:
        # QSS ::branch:selected radius (and the native disclosure chrome)
        # otherwise leaves a circular highlight whose square slot corners
        # show through. Non-Darwin parents keep the native glyph, so they
        # must not be filled over.
        if selected and (
            is_channel
            or is_record_binding
            or (is_parent and self._repaint_selected_expander)
        ):
            painter.fillRect(rect, _ChannelLeafDelegate.SELECTED_BG)
        if (
            is_parent
            and item.childCount() > 0
            and selected
            and self._repaint_selected_expander
        ):
            self._paint_selected_expander(painter, rect, item.isExpanded())
        if not is_channel:
            return
        owner = self._owner
        if owner is None:
            return
        gid = owner.axis_group_for(data[1], data[2])
        if not gid:
            return
        self._paint_group_badge(painter, rect, gid)

    def _paint_selected_expander(self, painter, rect, expanded):
        """Repaint a dark chevron so the selected tint does not swallow it.

        Historically this called ``QMacStyle.drawPrimitive(PE_IndicatorBranch)``.
        That native primitive can ``Abort`` under restricted offscreen hosts
        (sandbox / missing Cocoa) once the selected branch fill is styled, so
        the glyph is drawn as a plain vector instead. Geometry still tracks the
        16px right-edge branch slot Qt uses for the unselected row.
        """
        draw_rect = QRect(rect)
        target_center_x = rect.right() - 8
        draw_rect.translate(target_center_x - rect.center().x(), 0)
        cx = draw_rect.center().x()
        cy = draw_rect.center().y()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#334155"))
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if expanded:
            # Downward chevron (open).
            points = QPolygon([
                QPoint(cx - 4, cy - 1),
                QPoint(cx, cy + 3),
                QPoint(cx + 4, cy - 1),
            ])
        else:
            # Rightward chevron (collapsed).
            points = QPolygon([
                QPoint(cx - 1, cy - 4),
                QPoint(cx + 3, cy),
                QPoint(cx - 1, cy + 4),
            ])
        painter.drawPolyline(points)
        painter.restore()

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
    channel_order_requested = pyqtSignal(str, str, str, str)
    # Tree-root reorder intent. FileNavigator expands either fid to its
    # physical card block before forwarding the existing file_order_requested
    # signal to the workspace order owner.
    file_tree_order_requested = pyqtSignal(str, str, str)
    # Presentation-only: record-only WinWert curves under the owner source.
    # Payload is (view_id, binding_id, visible). Does not write ViewState.
    record_curve_visibility_toggled = pyqtSignal(str, str, bool)
    MAX_CHANNELS_WARNING = 8  # 超过此数量时警告

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("channelCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self);
        # Bottom 2: lift the 28px save/apply row so it shares the 30px View
        # rail band instead of sitting on the navigator floor.
        layout.setContentsMargins(8, 8, 8, 2);
        layout.setSpacing(6)
        self.search = SearchField("搜索通道…");
        self.search.setObjectName("channelSearch")
        self.search.textChanged.connect(self._filter);
        layout.addWidget(self.search)
        bl = QHBoxLayout()
        self.btn_all = QPushButton("全选")
        self.btn_all.setMaximumWidth(48)
        self.btn_all.setProperty("role", "quiet")
        self.btn_all.clicked.connect(self._all)
        bl.addWidget(self.btn_all)
        self.btn_none = QPushButton("全不")
        self.btn_none.setMaximumWidth(48)
        self.btn_none.setProperty("role", "quiet")
        self.btn_none.clicked.connect(self._none)
        bl.addWidget(self.btn_none)
        self.btn_selected_only = QPushButton("已选")
        self.btn_selected_only.setMaximumWidth(48)
        self.btn_selected_only.setProperty("role", "quiet")
        self.btn_selected_only.setCheckable(True)
        self.btn_selected_only.toggled.connect(self._apply_filters)
        bl.addWidget(self.btn_selected_only)
        bl.addStretch();
        # 编辑通道 lives on this row (right-aligned) instead of the top toolbar,
        # so the channel actions sit next to the channel tree they affect.
        self.btn_edit = QPushButton("编辑通道")
        self.btn_edit.setIcon(Icons.edit_channels())
        self.btn_edit.setIconSize(QSize(16, 16))
        self.btn_edit.setProperty("role", "quiet")
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
        # the dock is widened. Pts stays Fixed: ResizeToContents remeasured on
        # selection under macOS QSS and made the numbers jump sideways.
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.resizeSection(1, self._pts_section_width())
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
        self._empty_section_label = "时域"
        self._empty_view_name = "View 1"
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
        # ViewState-owned axis memberships restored for the focused Time View.
        # Unlike user-created groups, a WWT group may have one Navigator
        # channel plus an exceptional record-only binding, so it must not go
        # through the ordinary singleton-pruning model above.
        self._restored_axis_group_projection = {}
        # Per-TimeDomain-View projection. The persisted owner is ViewState;
        # this set is the live channel-tree copy for the currently focused View.
        self._hidden_channels = set()
        # Active-View record-only presentation. Identity is
        # (view_id, binding_id, owner_fid, record_index); never display name.
        self._record_view_id = None
        self._record_group_items = {}
        self._record_binding_items = {}
        self._record_visible = {}
        self._record_presentations = {}
        self._dropped_record_rows = ()
        # The action column is shared by every product mode: file/raster rows
        # use it to leave the focused View.  Only channel-eye toggles are
        # time-domain-specific.
        self._time_channel_visibility_available = True
        self._projection_role = "time"
        self._channel_checks_editable = True
        # Cache of the (role, checks_editable, visibility_available) tuple
        # last fully replayed to chrome/icons by ``set_projection_role``.
        # ``None`` forces the first call to always do the full replay.
        self._projection_chrome_signature = None
        self.axis_groups_changed.connect(self.tree.viewport().update)
        self.tree.viewport().setAcceptDrops(True)
        self.tree.viewport().setAccessibleName("通道树排序")
        self.tree.viewport().installEventFilter(self)
        self._channel_insert_line = QFrame(self.tree.viewport())
        self._channel_insert_line.setObjectName("channelInsertLine")
        self._channel_insert_line.setAccessibleName("通道插入位置")
        self._channel_insert_line.setFixedHeight(2)
        self._channel_insert_line.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._channel_insert_line.hide()
        self._file_tree_insert_line = QFrame(self.tree.viewport())
        self._file_tree_insert_line.setObjectName("fileTreeInsertLine")
        self._file_tree_insert_line.setAccessibleName("文件插入位置")
        self._file_tree_insert_line.setFixedHeight(2)
        self._file_tree_insert_line.setAttribute(
            Qt.WA_TransparentForMouseEvents, True
        )
        self._file_tree_insert_line.hide()
        self._sync_empty_state()
        self._sync_projection_chrome()

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
            raster_item = QTreeWidgetItem([grouped_source_raster_label(fd), str(n_rows)])
            raster_item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            raster_item.setFlags(raster_item.flags() | Qt.ItemIsUserCheckable)
            raster_item.setCheckState(0, Qt.Unchecked)
            raster_item.setData(0, Qt.UserRole, ('raster', fid))
            raster_item.setExpanded(True)
            raster_item.setToolTip(0, grouped_source_raster_tooltip(fd))
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
                ci.setToolTip(0, _channel_tip(ch, fd))
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
                ci.setToolTip(0, _channel_tip(ch, fd))
                ci.setForeground(0, QBrush(QColor('#111827')))
                ci.setForeground(1, QBrush(QColor('#64748b')))
                fi.addChild(ci)
            self.tree.addTopLevelItem(fi)
            self._file_items[fid] = fi

        self._apply_filters()
        self._refresh_visibility_icons()
        self._update_edit_enabled()
        # Newly built rows always start checkable; re-apply role chrome so
        # analysis_candidates stays non-checkable after add/refresh.
        self._sync_projection_chrome()

    def project_file_order(self, ordered_fids):
        """Move existing top-level file/source nodes to match workspace order."""
        desired = []
        seen = set()
        for fid in ordered_fids or ():
            fid = str(fid)
            item = None
            if fid in self._raster_items:
                raster = self._raster_items[fid]
                item = raster.parent() or raster
            elif fid in self._file_items:
                item = self._file_items[fid]
                parent = item.parent()
                if parent is not None:
                    item = parent
            if item is None:
                continue
            key = id(item)
            if key in seen:
                continue
            seen.add(key)
            desired.append(item)
        leftovers = []
        for idx in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(idx)
            if id(item) in seen:
                continue
            seen.add(id(item))
            leftovers.append(item)
        desired.extend(leftovers)
        current = [
            self.tree.topLevelItem(idx)
            for idx in range(self.tree.topLevelItemCount())
        ]
        if current == desired:
            return
        taken = []
        while self.tree.topLevelItemCount():
            taken.append(self.tree.takeTopLevelItem(0))
        by_id = {id(item): item for item in taken}
        for item in desired:
            real = by_id.get(id(item))
            if real is not None:
                self.tree.addTopLevelItem(real)

    def project_channel_order(self, fid, ordered_channels):
        """Move existing channel leaves under one fid/raster parent."""
        parent = self._file_items.get(str(fid))
        if parent is None:
            return
        by_name = {}
        current = []
        record_items = []
        idx = 0
        while idx < parent.childCount():
            child = parent.child(idx)
            data = child.data(0, Qt.UserRole)
            if data and data[0] == "channel":
                by_name[str(data[2])] = child
                current.append(child)
            elif data and data[0] in _RECORD_KINDS:
                record_items.append(child)
            idx += 1
        if not current:
            return
        desired = []
        seen = set()
        for name in ordered_channels or ():
            name = str(name)
            item = by_name.get(name)
            if item is None or name in seen:
                continue
            seen.add(name)
            desired.append(item)
        for item in current:
            name = str(item.data(0, Qt.UserRole)[2])
            if name in seen:
                continue
            seen.add(name)
            desired.append(item)
        if desired == current:
            return
        selected = {id(item) for item in self.tree.selectedItems()}
        current_item = self.tree.currentItem()
        expanded = parent.isExpanded()
        for item in current:
            parent.removeChild(item)
        for item in desired:
            parent.addChild(item)
        for item in record_items:
            parent.removeChild(item)
            parent.addChild(item)
        parent.setExpanded(expanded)
        for item in desired:
            item.setSelected(id(item) in selected)
        if current_item is not None:
            self.tree.setCurrentItem(current_item)
        self._refresh_visibility_icons()
        self._apply_filters()

    def refresh_file(self, fid, fd, channel_order=None):
        """Rebuild one file's channel rows without detaching it from a View.

        ``remove_file`` has intentionally destructive lifecycle semantics: it
        removes a source from the current View and discards its display state.
        Channel editing changes the universe of rows for an existing source,
        so it must use this narrower path instead.
        """
        fid = str(fid)
        if fid not in self._files:
            self.add_file(fid, fd)
            if channel_order:
                self.project_channel_order(fid, channel_order)
            return

        checked = list(self.get_checked_channels())
        hidden = list(self.get_hidden_channels())
        colors = dict(self._colors)
        axis_groups = dict(self._axis_groups)
        tree_state = self._file_tree_state(fid)

        self._clear_detach_hover()
        self._remove_file_tree_item(fid)
        self.add_file(fid, fd)

        # ``add_file`` supplies defaults for new rows.  Restore only the
        # surviving rows' user choices, leaving new channels visible/default.
        self.set_channel_colors(colors)
        self.set_checked_channels(checked)
        self.set_hidden_channels(hidden)
        self._restore_axis_groups(axis_groups)
        self._restore_file_tree_state(tree_state)
        if channel_order:
            self.project_channel_order(fid, channel_order)

    def _file_tree_state(self, fid):
        """Capture selection/expansion for the visual subtree of one file."""
        root = self._file_items.get(fid)
        if root is None:
            return (), (), None, None
        items = [root]
        parent = root.parent()
        if parent is not None:
            items.append(parent)

        def _walk(item):
            for idx in range(item.childCount()):
                child = item.child(idx)
                items.append(child)
                _walk(child)

        _walk(root)
        selected = tuple(
            tuple(item.data(0, Qt.UserRole))
            for item in self.tree.selectedItems()
            if item in items and item.data(0, Qt.UserRole)
        )
        expanded = tuple(
            (tuple(item.data(0, Qt.UserRole)), item.isExpanded())
            for item in items
            if item.data(0, Qt.UserRole)
        )
        current = self.tree.currentItem()
        current_data = (
            tuple(current.data(0, Qt.UserRole))
            if current in items and current is not None
            and current.data(0, Qt.UserRole)
            else None
        )
        placement = None
        if parent is not None and parent.data(0, Qt.UserRole):
            placement = (
                tuple(root.data(0, Qt.UserRole)),
                tuple(parent.data(0, Qt.UserRole)),
                parent.indexOfChild(root),
            )
        return selected, expanded, current_data, placement

    def _restore_file_tree_state(self, tree_state):
        selected, expanded, current_data, placement = tree_state
        if placement is not None:
            root_data, parent_data, previous_index = placement
            root = self._tree_item_for_data(root_data)
            parent = self._tree_item_for_data(parent_data)
            if root is not None and parent is not None and root.parent() is parent:
                current_index = parent.indexOfChild(root)
                target_index = min(max(0, previous_index), parent.childCount() - 1)
                if current_index != target_index:
                    parent.takeChild(current_index)
                    parent.insertChild(target_index, root)
        for data in selected:
            item = self._tree_item_for_data(data)
            if item is not None:
                item.setSelected(True)
        if current_data is not None:
            item = self._tree_item_for_data(current_data)
            if item is not None:
                self.tree.setCurrentItem(item)
        # Selecting a child may make Qt expand its ancestors.  Apply the saved
        # expansion state last so a collapsed file remains collapsed.
        for data, is_expanded in expanded:
            item = self._tree_item_for_data(data)
            if item is not None:
                item.setExpanded(is_expanded)

    def _tree_item_for_data(self, wanted):
        def _find(item):
            data = item.data(0, Qt.UserRole)
            if data and tuple(data) == tuple(wanted):
                return item
            for idx in range(item.childCount()):
                found = _find(item.child(idx))
                if found is not None:
                    return found
            return None

        for idx in range(self.tree.topLevelItemCount()):
            found = _find(self.tree.topLevelItem(idx))
            if found is not None:
                return found
        return None

    def _restore_axis_groups(self, previous):
        valid_keys = {
            (data[1], data[2])
            for item in self._iter_channel_items()
            for data in (item.data(0, Qt.UserRole),)
        }
        self._axis_groups = {
            key: group for key, group in previous.items() if key in valid_keys
        }
        self._prune_axis_groups()
        if self._axis_groups != previous:
            self.axis_groups_changed.emit()

    def _remove_file_tree_item(self, fid):
        """Remove only the QTreeWidget nodes; keep all logical View state."""
        self._clear_record_items_for_fid(fid)
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
            self._file_items.pop(fid, None)
        elif fid in self._file_items:
            fi = self._file_items.pop(fid)
            idx = self.tree.indexOfTopLevelItem(fi)
            if idx >= 0:
                self.tree.takeTopLevelItem(idx)

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

    def eventFilter(self, watched, event):
        if watched is self.tree.viewport():
            etype = event.type()
            if etype == QEvent.DragLeave:
                self._clear_channel_insert_line()
                self._clear_file_tree_insert_line()
                self._set_drop_active(False)
                event.accept()
                return True
            if etype in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
                mime = event.mimeData()
                if mime is not None and mime.hasFormat(INTERNAL_CHANNEL_MIME):
                    if etype == QEvent.DragEnter:
                        self._handle_channel_drag_enter(event)
                    elif etype == QEvent.DragMove:
                        self._handle_channel_drag_move(event)
                    else:
                        self._handle_channel_drop(event)
                    return True
                if mime is not None and mime.hasFormat(INTERNAL_FILE_FIDS_MIME):
                    if etype == QEvent.DragEnter:
                        handled = self._handle_tree_file_drag_enter(event)
                    elif etype == QEvent.DragMove:
                        handled = self._handle_tree_file_drag_move(event)
                    else:
                        handled = self._handle_tree_file_drop(event)
                    if handled:
                        return True
                if etype == QEvent.DragEnter:
                    self.dragEnterEvent(event)
                elif etype == QEvent.DragMove:
                    self.dragMoveEvent(event)
                else:
                    self.dropEvent(event)
                return True
        return super().eventFilter(watched, event)

    def _start_channel_drag(self, fid, channel):
        mime = QMimeData()
        mime.setData(INTERNAL_CHANNEL_MIME, encode_channel_drag(fid, channel))
        host = self.window() or self
        drag = QDrag(host)
        drag.setMimeData(mime)
        drag.setPixmap(self._channel_drag_pixmap(fid, channel))
        drag.exec_(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)

    def _start_tree_file_drag(self, anchor_fid):
        """Start a file-card-compatible drag from a top-level tree node."""
        mime = QMimeData()
        mime.setData(
            INTERNAL_FILE_FIDS_MIME,
            json.dumps([str(anchor_fid)]).encode("utf-8"),
        )
        host = self.window() or self
        drag = QDrag(host)
        drag.setMimeData(mime)
        drag.exec_(Qt.CopyAction | Qt.MoveAction, Qt.MoveAction)

    def _channel_drag_pixmap(self, fid, channel):
        fd = self._files.get(fid)
        source = ""
        if fd is not None:
            fp = getattr(fd, "filepath", None)
            if fp is not None:
                source = fp.stem
            else:
                source = (
                    getattr(fd, "short_name", "")
                    or getattr(fd, "filename", "")
                    or str(fid)
                )
        label = f"{channel}  ·  {source}" if source else str(channel)
        color = QColor(self._colors.get((fid, channel), "#1f77b4"))
        pixmap = QPixmap(240, 28)
        pixmap.fill(QColor("#f8fafc"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(8, 8, 12, 12)
        painter.setPen(QColor("#111827"))
        text_rect = QRect(26, 0, 206, 28)
        painter.drawText(
            text_rect,
            Qt.AlignVCenter | Qt.AlignLeft,
            painter.fontMetrics().elidedText(label, Qt.ElideMiddle, 206),
        )
        painter.end()
        return pixmap

    def _channel_drag_payload(self, mime):
        if mime is None or not mime.hasFormat(INTERNAL_CHANNEL_MIME):
            return None
        decoded = decode_channel_drag(bytes(mime.data(INTERNAL_CHANNEL_MIME)))
        if decoded is None:
            return None
        fid, channel = decoded
        if self._channel_item_for(fid, channel) is None:
            return None
        return fid, channel

    def _channel_reorder_allowed(self):
        return (
            not self.search.text().strip()
            and self._projection_role == "time"
        )

    def _channel_drop_target(self, event, source_fid, source_channel):
        item = self.tree.itemAt(event.pos())
        if item is None:
            return None, None, False
        data = item.data(0, Qt.UserRole)
        if not (data and data[0] == "channel"):
            return None, None, False
        target_fid = str(data[1])
        target_channel = str(data[2])
        source_item = self._channel_item_for(source_fid, source_channel)
        same_parent = (
            source_item is not None
            and item.parent() is source_item.parent()
            and target_fid == str(source_fid)
        )
        geo = self.tree.visualItemRect(item)
        placement = (
            _CHANNEL_ORDER_BEFORE
            if event.pos().y() < geo.center().y()
            else _CHANNEL_ORDER_AFTER
        )
        return target_channel, placement, same_parent

    def _channel_order_is_noop(self, source_item, target_item, placement):
        parent = source_item.parent() if source_item is not None else None
        if parent is None or target_item is None or target_item.parent() is not parent:
            return True
        if source_item is target_item:
            return True
        source_at = parent.indexOfChild(source_item)
        target_at = parent.indexOfChild(target_item)
        if placement == _CHANNEL_ORDER_BEFORE:
            return source_at == target_at - 1
        if placement == _CHANNEL_ORDER_AFTER:
            return source_at == target_at + 1
        return True

    def _show_channel_insert_line(self, item, placement):
        geo = self.tree.visualItemRect(item)
        y = geo.top() if placement == _CHANNEL_ORDER_BEFORE else geo.bottom() - 1
        viewport = self.tree.viewport()
        width = max(8, viewport.width() - 8)
        self._channel_insert_line.setGeometry(4, max(0, y - 1), width, 2)
        self._channel_insert_line.show()
        self._channel_insert_line.raise_()

    def _clear_channel_insert_line(self):
        self._channel_insert_line.hide()

    def _handle_channel_drag_enter(self, event):
        try:
            payload = self._channel_drag_payload(event.mimeData())
            if payload is None or not self._channel_reorder_allowed():
                self._clear_channel_insert_line()
                event.ignore()
                return
            event.setDropAction(Qt.MoveAction)
            event.accept()
        except Exception:
            logger.exception("channel tree drag enter failed")
            self._clear_channel_insert_line()
            event.ignore()

    def _handle_channel_drag_move(self, event):
        try:
            payload = self._channel_drag_payload(event.mimeData())
            if payload is None or not self._channel_reorder_allowed():
                self._clear_channel_insert_line()
                event.ignore()
                return
            source_fid, source_channel = payload
            target_channel, placement, same_parent = self._channel_drop_target(
                event, source_fid, source_channel
            )
            if not same_parent or target_channel is None:
                self._clear_channel_insert_line()
                event.ignore()
                return
            source_item = self._channel_item_for(source_fid, source_channel)
            target_item = self._channel_item_for(source_fid, target_channel)
            if self._channel_order_is_noop(source_item, target_item, placement):
                self._clear_channel_insert_line()
            else:
                self._show_channel_insert_line(target_item, placement)
            event.setDropAction(Qt.MoveAction)
            event.accept()
        except Exception:
            logger.exception("channel tree drag move failed")
            self._clear_channel_insert_line()
            event.ignore()

    def _handle_channel_drop(self, event):
        self._clear_channel_insert_line()
        try:
            payload = self._channel_drag_payload(event.mimeData())
            if payload is None or not self._channel_reorder_allowed():
                event.ignore()
                return
            source_fid, source_channel = payload
            target_channel, placement, same_parent = self._channel_drop_target(
                event, source_fid, source_channel
            )
            if not same_parent or target_channel is None:
                event.ignore()
                return
            source_item = self._channel_item_for(source_fid, source_channel)
            target_item = self._channel_item_for(source_fid, target_channel)
            event.setDropAction(Qt.MoveAction)
            event.accept()
            if self._channel_order_is_noop(source_item, target_item, placement):
                return
            self.channel_order_requested.emit(
                source_fid, source_channel, target_channel, placement
            )
        except Exception:
            logger.exception("channel tree drop failed")
            event.ignore()

    def _tree_file_reorder_allowed(self):
        return (
            not self.search.text().strip()
            and self._projection_role == "time"
        )

    def _tree_file_root_for_fid(self, fid):
        item = self._file_items.get(str(fid))
        if item is None:
            return None
        while item.parent() is not None:
            item = item.parent()
        data = item.data(0, Qt.UserRole)
        if data and data[0] in ("file", "source"):
            return item
        return None

    def _tree_file_anchor_for_item(self, item):
        return self.tree._file_anchor_for_item(item)

    def _tree_file_drag_anchor(self, mime):
        """Validate that a file drag represents exactly one physical root."""
        fids = self._file_fids_from_mime(mime)
        if not fids:
            return None
        root = None
        for fid in fids:
            candidate = self._tree_file_root_for_fid(fid)
            if candidate is None:
                return None
            if root is None:
                root = candidate
            elif candidate is not root:
                return None
        if root is None or not self._is_item_attached(root):
            return None
        return self._tree_file_anchor_for_item(root)

    def _tree_file_drop_target(self, event):
        item = self.tree.itemAt(event.pos())
        anchor_fid = self._tree_file_anchor_for_item(item)
        if (
            anchor_fid is None
            or item is None
            or not self._is_item_attached(item)
        ):
            return None, None, None
        geo = self.tree.visualItemRect(item)
        placement = (
            _CHANNEL_ORDER_BEFORE
            if event.pos().y() < geo.center().y()
            else _CHANNEL_ORDER_AFTER
        )
        return anchor_fid, placement, item

    def _tree_file_order_is_noop(self, source_fid, target_item, placement):
        source_item = self._tree_file_root_for_fid(source_fid)
        if source_item is None or target_item is None or source_item is target_item:
            return True
        source_at = self.tree.indexOfTopLevelItem(source_item)
        target_at = self.tree.indexOfTopLevelItem(target_item)
        if source_at < 0 or target_at < 0:
            return True
        if placement == _CHANNEL_ORDER_BEFORE:
            return source_at == target_at - 1
        if placement == _CHANNEL_ORDER_AFTER:
            return source_at == target_at + 1
        return True

    def _show_file_tree_insert_line(self, item, placement):
        geo = self.tree.visualItemRect(item)
        y = geo.top() if placement == _CHANNEL_ORDER_BEFORE else geo.bottom() - 1
        viewport = self.tree.viewport()
        width = max(8, viewport.width() - 8)
        self._file_tree_insert_line.setGeometry(4, max(0, y - 1), width, 2)
        self._file_tree_insert_line.show()
        self._file_tree_insert_line.raise_()

    def _clear_file_tree_insert_line(self):
        self._file_tree_insert_line.hide()

    def _handle_tree_file_drag_enter(self, event):
        anchor_fid = self._tree_file_drag_anchor(event.mimeData())
        if anchor_fid is None or not self._tree_file_reorder_allowed():
            self._clear_file_tree_insert_line()
            return False
        self._set_drop_active(False)
        event.setDropAction(Qt.MoveAction)
        event.accept()
        return True

    def _handle_tree_file_drag_move(self, event):
        anchor_fid = self._tree_file_drag_anchor(event.mimeData())
        target_fid, placement, target_item = self._tree_file_drop_target(event)
        if (
            anchor_fid is None
            or target_fid is None
            or not self._tree_file_reorder_allowed()
        ):
            self._clear_file_tree_insert_line()
            return False
        self._set_drop_active(False)
        if self._tree_file_order_is_noop(anchor_fid, target_item, placement):
            self._clear_file_tree_insert_line()
        else:
            self._show_file_tree_insert_line(target_item, placement)
        event.setDropAction(Qt.MoveAction)
        event.accept()
        return True

    def _handle_tree_file_drop(self, event):
        self._clear_file_tree_insert_line()
        anchor_fid = self._tree_file_drag_anchor(event.mimeData())
        target_fid, placement, target_item = self._tree_file_drop_target(event)
        if (
            anchor_fid is None
            or target_fid is None
            or not self._tree_file_reorder_allowed()
        ):
            return False
        self._set_drop_active(False)
        event.setDropAction(Qt.MoveAction)
        event.accept()
        if self._tree_file_order_is_noop(anchor_fid, target_item, placement):
            return True
        self.file_tree_order_requested.emit(anchor_fid, target_fid, placement)
        return True

    def _set_drop_active(self, active):
        self.setProperty("dropActive", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)

    def _sync_empty_state(self):
        has_attached = bool(self._attached_file_ids)
        self._tree_stack.setCurrentWidget(self.tree if has_attached else self.empty_state)
        if not has_attached:
            section = getattr(self, "_empty_section_label", "时域")
            view_name = getattr(self, "_empty_view_name", "View")
            if self._projection_role == "time":
                self.empty_state.setText(
                    f"当前“{section} · {view_name}”尚未加入文件\n"
                    "从上方拖入文件，或开启自动加入"
                )
            else:
                self.empty_state.setText(
                    f"当前“{section} · {view_name}”尚未加入文件\n"
                    "从上方拖入；或在链接菜单启用「切换分析时填充空 View」"
                )
        editable = self._channel_checks_editable
        for widget in (
            self.search,
            self.btn_edit,
        ):
            widget.setEnabled(has_attached)
        for widget in (self.btn_all, self.btn_none, self.btn_selected_only):
            widget.setEnabled(has_attached and editable)
        self._update_config_context()
        self._sync_projection_chrome()

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
        if data[0] == RECORD_GROUP_KIND:
            return str(data[2]) in attached
        if data[0] == RECORD_BINDING_KIND:
            return str(data[3]) in attached
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
        if data[0] in _RECORD_KINDS:
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
            if data and data[0] in _RECORD_KINDS:
                return
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
        if data and data[0] == RECORD_BINDING_KIND:
            key = (data[1], data[2], data[3], data[4])
            name = (self._record_presentations.get(key) or {}).get("name") or data[2]
            previous = self._updating
            self._updating = True
            try:
                if not self._time_channel_visibility_available:
                    item.setIcon(2, QIcon())
                    item.setToolTip(2, "")
                    item.setData(2, Qt.AccessibleTextRole, "")
                elif self._record_visible.get(key, True):
                    item.setIcon(2, Icons.eye_open())
                    item.setToolTip(2, "点击隐藏此记录（仅影响当前 View）")
                    item.setData(
                        2,
                        Qt.AccessibleTextRole,
                        f"显示/隐藏 WinWert 原始记录：{name}",
                    )
                else:
                    item.setIcon(2, Icons.eye_closed())
                    item.setToolTip(2, "点击显示此记录（仅影响当前 View）")
                    item.setData(
                        2,
                        Qt.AccessibleTextRole,
                        f"显示/隐藏 WinWert 原始记录：{name}",
                    )
            finally:
                self._updating = previous
            return
        if not (data and data[0] == 'channel'):
            return
        key = (data[1], data[2])
        checked = item.checkState(0) == Qt.Checked
        previous = self._updating
        self._updating = True
        try:
            if not self._time_channel_visibility_available or not checked:
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
        self._refresh_record_visibility_icons()

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
        """Compatibility shim: eye toggles only while the time projection is active.

        Prefer ``set_projection_role``. File/raster removal shares column 2 and
        remains available in every role.
        """
        self._time_channel_visibility_available = bool(available)
        if available and self._projection_role != "time":
            self._projection_role = "time"
            self._channel_checks_editable = True
        elif not available and self._projection_role == "time":
            # Legacy callers only flipped the eye; keep role but disable eye.
            pass
        self._refresh_visibility_icons()
        self._sync_projection_chrome()
        # This shim mutates the same tri-state that ``set_projection_role``
        # short-circuits on, but bypasses that method entirely. Keep the
        # cached signature coherent so a later ``set_projection_role`` call
        # that happens to land back on an already-cached tuple doesn't skip
        # a replay this shim actually still owes the tree.
        self._projection_chrome_signature = (
            self._projection_role,
            self._channel_checks_editable,
            self._time_channel_visibility_available,
        )

    def _pts_section_width(self):
        """Wide enough for 7-digit point counts plus the delegate's insets."""
        fm = self.tree.fontMetrics()
        return max(
            52,
            fm.horizontalAdvance("0000000")
            + _ChannelLeafDelegate.PTS_LEFT_INSET
            + _ChannelLeafDelegate.CELL_RIGHT_INSET
            + 8,
        )

    def projection_role(self):
        return self._projection_role

    def set_projection_role(self, role):
        """Present the channel tree for the active mode context.

        Roles:
        - ``time``: checkbox + eye + detach; channel-config apply row shown
        - ``fft_sources``: checkbox = focused FFT pane sources; no eye; detach ok
        - ``analysis_candidates``: checkboxes non-editable; no eye; detach ok
        """
        allowed = {"time", "fft_sources", "analysis_candidates"}
        role = str(role or "time")
        if role not in allowed:
            role = "time"
        self._projection_role = role
        self._time_channel_visibility_available = role == "time"
        self._channel_checks_editable = role != "analysis_candidates"
        signature = (
            self._projection_role,
            self._channel_checks_editable,
            self._time_channel_visibility_available,
        )
        if signature == self._projection_chrome_signature:
            # Mode/View switches call this at high frequency and usually land
            # on the role that is already active (attachment-projection p95
            # regressed 2.98ms -> 8.19ms from replaying the icon walk + a
            # whole-tree setFlags/header pass on every no-op call). Nothing
            # observable changed, so chrome/icons/empty-state are already
            # correct -- skip the replay. Row rebuilds (``add_file``) call
            # ``_sync_projection_chrome()`` directly and are unaffected by
            # this cache. ``_attached_file_ids``/label changes elsewhere
            # (``set_attached_file_ids`` / ``set_empty_state_context``) call
            # ``_sync_empty_state()`` themselves, so skipping it here does
            # not leave empty-state text/button-enablement stale.
            return
        self._projection_chrome_signature = signature
        self._refresh_visibility_icons()
        self._sync_projection_chrome()
        self._sync_empty_state()

    def set_empty_state_context(self, *, section_label=None, view_name=None):
        if section_label is not None:
            self._empty_section_label = str(section_label)
        if view_name is not None:
            self._empty_view_name = str(view_name)
        self._sync_empty_state()

    def _iter_tree_items(self):
        def _walk(node):
            yield node
            for i in range(node.childCount()):
                yield from _walk(node.child(i))

        for i in range(self.tree.topLevelItemCount()):
            yield from _walk(self.tree.topLevelItem(i))

    def _sync_projection_chrome(self):
        # Channel-config apply/save is a Time View feature.
        is_time = self._projection_role == "time"
        self.config_bar.setVisible(is_time)
        self.config_bar.setEnabled(is_time)
        # Bulk check helpers are meaningless for read-only candidate trees.
        editable = self._channel_checks_editable
        for widget in (self.btn_all, self.btn_none, self.btn_selected_only):
            widget.setEnabled(editable and bool(self._attached_file_ids))
        header = self.tree.headerItem()
        if header is not None:
            header.setText(
                2,
                {
                    "time": "显示",
                    "fft_sources": "来源",
                    "analysis_candidates": "移出",
                }.get(self._projection_role, "显示"),
            )
        # analysis_candidates must not present checkboxes; time / fft_sources
        # re-enable them so role switches reverse cleanly after a rebuild.
        self._updating = True
        try:
            for item in self._iter_tree_items():
                data = item.data(0, Qt.UserRole)
                if not data or data[0] in _RECORD_KINDS:
                    continue
                if data[0] not in ("channel", "file", "source", "raster"):
                    continue
                flags = item.flags()
                if editable:
                    item.setFlags(flags | Qt.ItemIsUserCheckable)
                else:
                    item.setFlags(flags & ~Qt.ItemIsUserCheckable)
        finally:
            self._updating = False

    def _on_item_clicked(self, item, column):
        if column != 2:
            return
        data = item.data(0, Qt.UserRole)
        fids = self._fids_for_node(item)
        if fids:
            self.files_detach_requested.emit(fids, item.text(0))
            return
        if data and data[0] == RECORD_BINDING_KIND:
            if not self._time_channel_visibility_available:
                return
            key = (data[1], data[2], data[3], data[4])
            new_visible = not self._record_visible.get(key, True)
            self._record_visible[key] = new_visible
            self._sync_visibility_icon(item)
            self.record_curve_visibility_toggled.emit(
                str(data[1]), str(data[2]), bool(new_visible),
            )
            return
        if not self._time_channel_visibility_available:
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
        if not self._channel_checks_editable:
            # analysis_candidates: force unchecked and do not emit.
            self._updating = True
            try:
                item.setCheckState(0, Qt.Unchecked)

                def _clear(node):
                    node.setCheckState(0, Qt.Unchecked)
                    for i in range(node.childCount()):
                        _clear(node.child(i))

                if item.data(0, Qt.UserRole) and item.data(0, Qt.UserRole)[0] in (
                    "file", "source", "raster",
                ):
                    for i in range(item.childCount()):
                        _clear(item.child(i))
            finally:
                self._updating = False
            return
        data = item.data(0, Qt.UserRole)
        if data and data[0] in _RECORD_KINDS:
            return

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
                    if cd and cd[0] in _RECORD_KINDS:
                        continue
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
                    cd = child.data(0, Qt.UserRole)
                    if cd and cd[0] in _RECORD_KINDS:
                        continue
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
        if not data or data[0] in _RECORD_KINDS or data[0] != 'channel':
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
        self._restored_axis_group_projection = {
            key: group
            for key, group in self._restored_axis_group_projection.items()
            if key[0] != str(fid)
        }
        self._hidden_channels = {
            key for key in self._hidden_channels if key[0] != fid
        }
        self._attached_file_ids = [
            attached for attached in self._attached_file_ids if attached != fid
        ]
        self._prune_axis_groups()

        self._remove_file_tree_item(fid)

        self._update_edit_enabled()
        self._apply_filters()
        self._sync_empty_state()
        if emit:
            self.channels_changed.emit()

    def set_record_curve_rows(self, view_id, rows: Sequence[Mapping[str, object]] | None = None):
        """Project active-View record-only rows under their owner sources.

        Incremental: match on ``(view_id, binding_id, owner_fid, record_index)``.
        Does not rebuild the file tree or emit ``record_curve_visibility_toggled``.
        Rows whose ``owner_fid`` is missing or not in the tree are dropped.
        """
        if view_id is None or not rows:
            self._clear_all_record_items()
            self._record_view_id = None
            self._dropped_record_rows = ()
            return

        view_id = str(view_id)
        parsed = []
        dropped = []
        for row in rows:
            coerced = self._coerce_record_row(row)
            if coerced is None:
                dropped.append(self._dropped_row_fact(row, reason="invalid"))
                continue
            parent = self._record_owner_parent(coerced["owner_fid"])
            if parent is None:
                dropped.append(self._dropped_row_fact(coerced, reason="missing_owner"))
                continue
            parsed.append((coerced, parent))

        wanted = {
            (view_id, row["binding_id"], row["owner_fid"], row["record_index"])
            for row, _parent in parsed
        }

        previous = self._updating
        self._updating = True
        try:
            for key in list(self._record_binding_items):
                if key not in wanted:
                    self._remove_record_binding_item(key)
            for group_key in list(self._record_group_items):
                if group_key[0] != view_id or group_key[1] not in {
                    row["owner_fid"] for row, _parent in parsed
                }:
                    self._remove_record_group_item(group_key)

            by_owner = {}
            seen_owners = []
            for row, parent in parsed:
                fid = row["owner_fid"]
                if fid not in by_owner:
                    by_owner[fid] = []
                    seen_owners.append((fid, parent))
                by_owner[fid].append(row)

            for owner_fid, parent in seen_owners:
                group = self._ensure_record_group(view_id, owner_fid, parent)
                bindings = by_owner[owner_fid]
                group.setText(0, f"{RECORD_GROUP_TAG} ({len(bindings)})")
                group.setToolTip(0, RECORD_GROUP_TAG)
                group.setExpanded(True)
                for index, row in enumerate(bindings):
                    key = (
                        view_id,
                        row["binding_id"],
                        row["owner_fid"],
                        row["record_index"],
                    )
                    item = self._record_binding_items.get(key)
                    if item is None:
                        item = self._make_record_binding_item(view_id, row)
                        group.insertChild(index, item)
                        self._record_binding_items[key] = item
                    else:
                        if item.parent() is not group:
                            old_parent = item.parent()
                            if old_parent is not None:
                                old_parent.removeChild(item)
                            group.insertChild(index, item)
                        elif group.indexOfChild(item) != index:
                            group.takeChild(group.indexOfChild(item))
                            group.insertChild(index, item)
                    self._apply_record_binding_presentation(item, view_id, row)
                for leftover in range(group.childCount() - 1, len(bindings) - 1, -1):
                    extra = group.child(leftover)
                    extra_data = extra.data(0, Qt.UserRole) if extra is not None else None
                    if extra_data and extra_data[0] == RECORD_BINDING_KIND:
                        extra_key = (
                            extra_data[1], extra_data[2], extra_data[3], extra_data[4],
                        )
                        if extra_key not in wanted:
                            self._remove_record_binding_item(extra_key)

            for group_key, group in list(self._record_group_items.items()):
                if group.childCount() == 0:
                    self._remove_record_group_item(group_key)
        finally:
            self._updating = previous

        self._record_view_id = view_id
        self._dropped_record_rows = tuple(dropped)
        self._refresh_record_visibility_icons()
        self._apply_filters()

    def clear_record_curve_rows(self):
        self.set_record_curve_rows(None, ())

    def _coerce_record_row(self, row):
        if not isinstance(row, Mapping):
            return None
        binding_id = str(row.get("binding_id") or "").strip()
        owner_fid = str(row.get("owner_fid") or "").strip()
        if not binding_id or not owner_fid:
            return None
        try:
            record_index = int(row.get("record_index"))
        except (TypeError, ValueError):
            return None
        color = str(row.get("color") or "#64748b")
        parsed = QColor(color)
        if not parsed.isValid():
            color = "#64748b"
        return {
            "binding_id": binding_id,
            "owner_fid": owner_fid,
            "record_index": record_index,
            "name": str(row.get("name") or ""),
            "unit": str(row.get("unit") or ""),
            "color": color,
            "visible": bool(row.get("visible", True)),
        }

    @staticmethod
    def _dropped_row_fact(row, *, reason):
        if isinstance(row, Mapping):
            return {
                "binding_id": str(row.get("binding_id") or ""),
                "owner_fid": str(row.get("owner_fid") or ""),
                "record_index": row.get("record_index"),
                "reason": reason,
            }
        return {"reason": reason}

    def _record_owner_parent(self, owner_fid):
        fid = str(owner_fid)
        if fid in self._raster_items:
            return self._raster_items[fid]
        return self._file_items.get(fid)

    def _record_item_flags(self):
        return (
            Qt.ItemIsEnabled
            | Qt.ItemIsSelectable
        ) & ~Qt.ItemIsUserCheckable & ~Qt.ItemIsDragEnabled

    def _ensure_record_group(self, view_id, owner_fid, parent):
        key = (str(view_id), str(owner_fid))
        group = self._record_group_items.get(key)
        if group is not None and group.parent() is parent:
            return group
        if group is not None:
            old_parent = group.parent()
            if old_parent is not None:
                old_parent.removeChild(group)
        group = QTreeWidgetItem(["", ""])
        group.setFlags(self._record_item_flags())
        group.setData(0, Qt.UserRole, (RECORD_GROUP_KIND, str(view_id), str(owner_fid)))
        font = group.font(0)
        font.setBold(True)
        group.setFont(0, font)
        parent.addChild(group)
        self._record_group_items[key] = group
        return group

    def _make_record_binding_item(self, view_id, row):
        item = QTreeWidgetItem(["", ""])
        item.setFlags(self._record_item_flags())
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        item.setTextAlignment(2, Qt.AlignCenter)
        item.setData(
            0,
            Qt.UserRole,
            (
                RECORD_BINDING_KIND,
                str(view_id),
                row["binding_id"],
                row["owner_fid"],
                row["record_index"],
            ),
        )
        item.setForeground(0, QBrush(QColor("#111827")))
        return item

    def _apply_record_binding_presentation(self, item, view_id, row):
        name = row["name"] or row["binding_id"]
        unit = row["unit"]
        text = f"{name} [{unit}]" if unit else name
        item.setText(0, text)
        item.setIcon(0, _swatch_icon(row["color"]))
        item.setToolTip(
            0,
            (
                f"{text}\n"
                f"WinWert record {row['record_index']}\n"
                f"所属 View: {view_id}\n"
                "仅控制当前 View"
            ),
        )
        key = (
            str(view_id),
            row["binding_id"],
            row["owner_fid"],
            row["record_index"],
        )
        self._record_visible[key] = bool(row["visible"])
        self._record_presentations[key] = {
            "name": name,
            "unit": unit,
            "color": row["color"],
        }
        self._sync_visibility_icon(item)

    def _remove_record_binding_item(self, key):
        item = self._record_binding_items.pop(key, None)
        self._record_visible.pop(key, None)
        self._record_presentations.pop(key, None)
        if item is None:
            return
        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)

    def _remove_record_group_item(self, key):
        group = self._record_group_items.pop(key, None)
        if group is None:
            return
        for index in range(group.childCount() - 1, -1, -1):
            child = group.child(index)
            data = child.data(0, Qt.UserRole) if child is not None else None
            if data and data[0] == RECORD_BINDING_KIND:
                child_key = (data[1], data[2], data[3], data[4])
                self._record_binding_items.pop(child_key, None)
                self._record_visible.pop(child_key, None)
                self._record_presentations.pop(child_key, None)
        parent = group.parent()
        if parent is not None:
            parent.removeChild(group)

    def _clear_all_record_items(self):
        previous = self._updating
        self._updating = True
        try:
            for key in list(self._record_group_items):
                self._remove_record_group_item(key)
        finally:
            self._updating = previous
        self._record_group_items.clear()
        self._record_binding_items.clear()
        self._record_visible.clear()
        self._record_presentations.clear()
        self._record_view_id = None

    def _clear_record_items_for_fid(self, fid):
        fid = str(fid)
        previous = self._updating
        self._updating = True
        try:
            for key in [k for k in self._record_group_items if k[1] == fid]:
                self._remove_record_group_item(key)
            for key in [k for k in self._record_binding_items if k[2] == fid]:
                self._remove_record_binding_item(key)
        finally:
            self._updating = previous

    def _refresh_record_visibility_icons(self):
        for item in self._record_binding_items.values():
            self._sync_visibility_icon(item)

    def _record_search_haystack(self, item):
        data = item.data(0, Qt.UserRole)
        parts = [item.text(0) or "", item.toolTip(0) or "", RECORD_GROUP_TAG]
        if data and data[0] == RECORD_BINDING_KIND:
            key = (data[1], data[2], data[3], data[4])
            pres = self._record_presentations.get(key) or {}
            parts.extend([pres.get("name") or "", pres.get("unit") or ""])
        return " ".join(parts).lower()

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
        key = (str(fid), str(ch))
        return self._axis_groups.get(
            key, self._restored_axis_group_projection.get(key)
        )

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

        # A ViewState-projected group is the persistent owner for imported
        # WWT channels.  Promoting it into the generic session-only model
        # would make a subsequent capture lose the edit (capture deliberately
        # serializes this projection, not ``_axis_groups``).  Keep the entire
        # merged component in that View-owned map instead, including any
        # ordinary session group that joins an imported member.
        persisted = self._restored_axis_group_projection
        persisted_ids = {
            persisted[key] for key in keys if key in persisted
        }
        if persisted_ids:
            gid = next(persisted[key] for key in keys if key in persisted)
            persistent_keys = {
                key for key, group in persisted.items()
                if group in persisted_ids
            }
            session_ids = {
                self._axis_groups[key] for key in keys
                if key in self._axis_groups
            }
            for key, group in self._axis_groups.items():
                if group in session_ids:
                    persistent_keys.add(key)
            persistent_keys.update(keys)

            updated = dict(persisted)
            for key in persistent_keys:
                updated[key] = gid
                self._axis_groups.pop(key, None)
            self._prune_axis_groups()
            self.set_restored_axis_group_projection(updated)
            self.axis_groups_changed.emit()
            return gid

        existing = sorted({self._axis_groups[k] for k in keys if k in self._axis_groups})
        gid = existing[0] if existing else self._new_axis_group_id()
        fold = set(existing[1:])
        if fold:
            for k, g in list(self._axis_groups.items()):
                if g in fold:
                    self._axis_groups[k] = gid
        for k in keys:
            self._restored_axis_group_projection.pop(k, None)
            self._axis_groups[k] = gid
        self._prune_axis_groups()
        self.axis_groups_changed.emit()
        return gid

    def split_axis_group(self, keys):
        """Remove ``keys`` from their groups; dissolve any group left < 2."""
        changed = False
        persisted = dict(self._restored_axis_group_projection)
        for (f, c) in keys:
            k = (str(f), str(c))
            if k in self._axis_groups:
                del self._axis_groups[k]
                changed = True
            if k in persisted:
                del persisted[k]
                changed = True
        if changed:
            self._prune_axis_groups()
            self.set_restored_axis_group_projection(persisted)
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
        effective = {
            key: group
            for key, group in self._restored_axis_group_projection.items()
            if key in checked
        }
        # Explicit ordinary Canvas edits win over the imported initial seed.
        effective.update(self._effective_groups(self._axis_groups, checked))
        return effective

    def set_restored_axis_group_projection(self, raw_groups) -> None:
        """Set the focused View's persistent axis-group membership.

        The persisted JSON map uses composite ``[fid, channel]`` keys and an
        opaque axis id.  ``_axis_groups`` is intentionally reserved for
        non-imported, session-level grouping; a persistent View member must
        not also live there.  A View may retain one normal Navigator row when
        its other shared-axis member is an exceptional record-only binding.
        """
        projected = {}
        if isinstance(raw_groups, Mapping):
            for raw_key, raw_group in raw_groups.items():
                if isinstance(raw_key, str):
                    try:
                        key = json.loads(raw_key)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                else:
                    key = raw_key
                try:
                    fid, channel = key
                except (TypeError, ValueError):
                    continue
                group = str(raw_group or "").strip()
                if not group:
                    continue
                projected[(str(fid), str(channel))] = group
        if projected == self._restored_axis_group_projection:
            return
        self._restored_axis_group_projection = projected
        for key in projected:
            self._axis_groups.pop(key, None)
        self._prune_axis_groups()
        # This setter projects persisted/imported View state.  It is not an
        # interactive merge/split intent, so publishing ``axis_groups_changed``
        # would re-enter MainWindow's user-edit path while the rest of the View
        # controls are still being restored.  Repaint the badge presentation
        # directly; real merge/split operations continue to emit the signal.
        self.tree.viewport().update()

    def restored_axis_group_projection(self):
        """Return the focused View's persisted-ready composite-key map."""
        return {
            json.dumps([fid, channel], ensure_ascii=False, separators=(",", ":")): group
            for (fid, channel), group in self._restored_axis_group_projection.items()
        }

    def _axis_group_menu_plan(self, sel_keys):
        """(can_merge, can_split) for the right-click menu (Task 2)."""
        sel = [(str(f), str(c)) for (f, c) in sel_keys]
        can_merge = len(sel) >= 2
        can_split = any(
            k in self._axis_groups or k in self._restored_axis_group_projection
            for k in sel
        )
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
        fit_message_box_buttons_to_text(box)
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
                if data and data[0] in _RECORD_KINDS:
                    return
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
                                if cd and cd[0] in _RECORD_KINDS:
                                    continue
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
        parent = self._raster_items.get(fid) or self._file_items.get(fid)
        if parent is None:
            return
        first = None
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, Qt.UserRole)
            if data and data[0] == "channel":
                first = child
                break
        if first is None:
            return
        self._updating = True
        first.setCheckState(0, Qt.Checked)
        self._updating = False
        data = first.data(0, Qt.UserRole)
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
            if data and data[0] == RECORD_BINDING_KIND:
                if not self._is_item_attached(item):
                    item.setHidden(True)
                    return False
                if show_checked_only:
                    item.setHidden(True)
                    return False
                matches_text = not t or t in self._record_search_haystack(item)
                item.setHidden(not matches_text)
                return matches_text
            if data and data[0] == RECORD_GROUP_KIND:
                if not self._is_item_attached(item):
                    item.setHidden(True)
                    for idx in range(item.childCount()):
                        _apply_to_node(item.child(idx))
                    return False
                visible_children = 0
                for i in range(item.childCount()):
                    if _apply_to_node(item.child(i)):
                        visible_children += 1
                matches_tag = (
                    not t
                    or t in (item.text(0) or "").lower()
                    or t in RECORD_GROUP_TAG.lower()
                )
                if not filtering:
                    item.setHidden(False)
                    return True
                visible = visible_children > 0 or (
                    bool(t) and matches_tag and not show_checked_only
                )
                item.setHidden(not visible)
                if visible and filtering:
                    item.setExpanded(True)
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
            if data and data[0] in _RECORD_KINDS:
                return 0
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
            if data and data[0] in _RECORD_KINDS:
                return
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
            data = item.data(0, Qt.UserRole)
            if data and data[0] in _RECORD_KINDS:
                return
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
