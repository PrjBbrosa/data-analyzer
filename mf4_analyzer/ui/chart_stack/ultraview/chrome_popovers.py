"""Board list and layout-picker popovers for UltraView chrome.

``_InlineNameEditor`` stays in ``chrome_common`` (shared with BoardIsland).
Author flyouts remain in ``author_chrome``.
"""
from __future__ import annotations

from collections.abc import Mapping

import qtawesome as qta
from PyQt5.QtCore import QEvent, QRect, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.icons import icon_device_pixel_ratio
from mf4_analyzer.ui.ultraview_state import LAYOUT_SLOTS

from .chrome_common import (
    UV_BRAND,
    UV_CANVAS_DEEP,
    UV_DANGER,
    UV_INK,
    UV_LINE,
    UV_MUTED,
    UV_PAPER,
    UV_WASH,
    _InlineNameEditor,
)


BOARD_POPOVER_WIDTH = 260
BOARD_ROW_HEIGHT = 36
_BOARD_CURRENT_ROLE = Qt.UserRole + 1
_BOARD_ACTION_WIDTH = 24
_BOARD_POPOVER_MARGIN = 8
_BOARD_POPOVER_GAP = 6
_BOARD_CREATE_HEIGHT = 28
_BOARD_LIST_BOTTOM_PAD = 6

def board_popover_height(rows: int) -> int:
    """Exact popover height for ``rows`` Board lines plus the create row."""
    count = max(1, int(rows))
    list_h = count * BOARD_ROW_HEIGHT + max(0, count - 1) + _BOARD_LIST_BOTTOM_PAD
    return _BOARD_POPOVER_MARGIN * 2 + list_h + _BOARD_POPOVER_GAP + _BOARD_CREATE_HEIGHT

_LAYOUT_THUMB_SIZE = QSize(88, 54)
_LAYOUT_THUMB_CELL = QSize(168, 118)
_HERO_LAYOUT_IDS = frozenset({"hero_left_4", "hero_top_4"})

_LAYOUT_THUMB_SCHEMES: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "split_horizontal": ((0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 0.5, 1.0)),
    "split_vertical": ((0.0, 0.0, 1.0, 0.5), (0.0, 0.5, 1.0, 0.5)),
    "grid_2x2": (
        (0.0, 0.0, 0.5, 0.5),
        (0.5, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5),
    ),
    "hero_left_4": (
        (0.0, 0.0, 0.62, 1.0),
        (0.62, 0.0, 0.38, 0.33),
        (0.62, 0.33, 0.38, 0.33),
        (0.62, 0.66, 0.38, 0.34),
    ),
    "hero_top_4": (
        (0.0, 0.0, 1.0, 0.58),
        (0.0, 0.58, 0.33, 0.42),
        (0.33, 0.58, 0.34, 0.42),
        (0.67, 0.58, 0.33, 0.42),
    ),
    "grid_3x2": tuple(
        (col / 3.0, row / 2.0, 1.0 / 3.0, 0.5) for row in range(2) for col in range(3)
    ),
    "grid_3x3": tuple(
        (col / 3.0, row / 3.0, 1.0 / 3.0, 1.0 / 3.0) for row in range(3) for col in range(3)
    ),
    "grid_4x3": tuple(
        (col / 4.0, row / 3.0, 0.25, 1.0 / 3.0) for row in range(3) for col in range(4)
    ),
    "free_grid": tuple(
        (col / 4.0, row / 3.0, 0.25, 1.0 / 3.0) for row in range(3) for col in range(4)
    ),
}

def layout_thumbnail_icon(layout_id: str) -> QIcon:
    """Paint a paper-card preview: inset canvas, gutters, weighted hero slot."""
    logical_w, logical_h = _LAYOUT_THUMB_SIZE.width(), _LAYOUT_THUMB_SIZE.height()
    dpr = icon_device_pixel_ratio()
    pixmap = QPixmap(max(1, int(round(logical_w * dpr))), max(1, int(round(logical_h * dpr))))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(UV_LINE)
    painter.setBrush(UV_PAPER)
    painter.drawRoundedRect(QRectF(0.5, 0.5, logical_w - 1.0, logical_h - 1.0), 7, 7)
    inset = QRectF(5.0, 5.0, logical_w - 10.0, logical_h - 10.0)
    painter.setPen(Qt.NoPen)
    painter.setBrush(UV_CANVAS_DEEP)
    painter.drawRoundedRect(inset, 4, 4)
    cells = _LAYOUT_THUMB_SCHEMES.get(str(layout_id), _LAYOUT_THUMB_SCHEMES["grid_2x2"])
    gutter = 2.4
    hero = str(layout_id) in _HERO_LAYOUT_IDS
    slot_line = QColor(UV_BRAND.red(), UV_BRAND.green(), UV_BRAND.blue(), 55)
    aux_fill = QColor("#E2EAEC")
    hero_fill = QColor("#C9DBDE")
    for index, (left, top, width, height) in enumerate(cells):
        x = inset.x() + left * inset.width() + gutter
        y = inset.y() + top * inset.height() + gutter
        w = max(2.0, width * inset.width() - gutter * 2.0)
        h = max(2.0, height * inset.height() - gutter * 2.0)
        painter.setBrush(hero_fill if hero and index == 0 else aux_fill)
        painter.setPen(slot_line)
        painter.drawRoundedRect(QRectF(x, y, w, h), 2.2, 2.2)
    painter.end()
    return QIcon(pixmap)

class _BoardListDelegate(QStyledItemDelegate):
    """Draw check + name + copy/delete without stealing InternalMove."""

    duplicate_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hovered_row = -1
        # Duplicating a Board preserves its layout/reference collection; it is
        # not an image-copy operation.  Use one normalised Font Awesome family
        # for both compact row actions so their optical boxes match.
        self._copy_icon = qta.icon("fa5s.clone", color=UV_MUTED)
        self._delete_icon = qta.icon("fa5s.trash-alt", color=UV_DANGER)

    def set_hovered_row(self, row: int) -> None:
        self._hovered_row = int(row)

    def hovered_row(self) -> int:
        return self._hovered_row

    def paint(self, painter, option, index) -> None:  # noqa: N802
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect.adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = index.row() == self._hovered_row
        current = bool(index.data(_BOARD_CURRENT_ROLE))
        if selected:
            painter.setPen(UV_BRAND)
            painter.setBrush(UV_WASH)
            painter.drawRoundedRect(QRectF(rect), 6, 6)
        elif hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#F7FAFC"))
            painter.drawRoundedRect(QRectF(rect), 6, 6)
        check_rect = QRect(rect.left() + 4, rect.top(), 16, rect.height())
        painter.setPen(UV_BRAND if current else Qt.transparent)
        painter.drawText(check_rect, Qt.AlignCenter, "✓" if current else "")
        copy_rect, delete_rect = self.action_rects(option.rect)
        name_rect = self.name_rect(option.rect)
        metrics = option.fontMetrics
        name = metrics.elidedText(str(index.data(Qt.DisplayRole) or ""), Qt.ElideRight, name_rect.width())
        painter.setPen(UV_INK)
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, name)
        self._paint_icon(painter, self._copy_icon, copy_rect)
        self._paint_icon(painter, self._delete_icon, delete_rect)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        del option, index
        return QSize(BOARD_POPOVER_WIDTH - 16, BOARD_ROW_HEIGHT)

    @staticmethod
    def _paint_icon(painter, icon: QIcon, slot: QRect) -> None:
        box = QRect(0, 0, 18, 18)
        box.moveCenter(slot.center())
        icon.paint(painter, box, Qt.AlignCenter)

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        del model
        if event.type() != QEvent.MouseButtonRelease or event.button() != Qt.LeftButton:
            return False
        board_id = str(index.data(Qt.UserRole) or "")
        if not board_id:
            return False
        copy_rect, delete_rect = self.action_rects(option.rect)
        if copy_rect.contains(event.pos()):
            self.duplicate_requested.emit(board_id)
            return True
        if delete_rect.contains(event.pos()):
            self.delete_requested.emit(board_id)
            return True
        return False

    @staticmethod
    def action_rects(item_rect: QRect) -> tuple[QRect, QRect]:
        delete_rect = QRect(
            item_rect.right() - _BOARD_ACTION_WIDTH - 4,
            item_rect.top(),
            _BOARD_ACTION_WIDTH,
            item_rect.height(),
        )
        copy_rect = QRect(
            delete_rect.left() - _BOARD_ACTION_WIDTH,
            item_rect.top(),
            _BOARD_ACTION_WIDTH,
            item_rect.height(),
        )
        return copy_rect, delete_rect

    @staticmethod
    def name_rect(item_rect: QRect) -> QRect:
        rect = item_rect.adjusted(4, 2, -4, -2)
        check_right = rect.left() + 4 + 16
        copy_rect, _delete_rect = _BoardListDelegate.action_rects(item_rect)
        return QRect(
            check_right + 4,
            rect.top(),
            max(0, copy_rect.left() - 4 - check_right - 4),
            rect.height(),
        )


class _BoardList(QListWidget):
    """QListWidget whose Delete key never removes a Board row."""

    reordered = pyqtSignal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_id = ""
        self.setObjectName("ultraViewBoardList")
        self.setFrameShape(QFrame.NoFrame)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSizeAdjustPolicy(QAbstractItemView.AdjustToContents)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setDropIndicatorShown(True)
        self.setSpacing(1)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(BOARD_POPOVER_WIDTH - 12, self._content_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(BOARD_POPOVER_WIDTH - 12, BOARD_ROW_HEIGHT)

    def content_height(self) -> int:
        return self._content_height()

    def _content_height(self) -> int:
        rows = max(1, self.count())
        return rows * BOARD_ROW_HEIGHT + max(0, rows - 1) * self.spacing() + _BOARD_LIST_BOTTOM_PAD

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        item = self.currentItem()
        self._drag_id = str(item.data(Qt.UserRole) or "") if item is not None else ""
        super().startDrag(supported_actions)

    def dropEvent(self, event) -> None:  # noqa: N802
        super().dropEvent(event)
        board_id = self._drag_id
        self._drag_id = ""
        if not board_id:
            return
        for index in range(self.count()):
            item = self.item(index)
            if item is not None and str(item.data(Qt.UserRole) or "") == board_id:
                self.reordered.emit(board_id, index)
                return

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            event.accept()
            return
        super().keyPressEvent(event)


class BoardPopover(QFrame):
    """Single-layer Board list: click to switch, drag to reorder, copy/delete on the row.

    Page owns workspace mutation, confirmation, and the 20-Board cap.  This
    widget only projects the current list and emits typed intents.
    """

    board_selected = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    boards_reordered = pyqtSignal(str, int)
    create_requested = pyqtSignal()
    rename_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardPopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._reordering = False
        self._pending_boards: tuple[tuple[object, ...], str | None] | None = None
        self._rename_editor: _InlineNameEditor | None = None
        self._rename_board_id = ""
        self._pending_rename_id = ""
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._end_reordering)
        root = QVBoxLayout(self)
        root.setContentsMargins(
            _BOARD_POPOVER_MARGIN,
            _BOARD_POPOVER_MARGIN,
            _BOARD_POPOVER_MARGIN,
            _BOARD_POPOVER_MARGIN,
        )
        root.setSpacing(_BOARD_POPOVER_GAP)
        self._list = _BoardList(self)
        self._delegate = _BoardListDelegate(self._list)
        self._list.setItemDelegate(self._delegate)
        self._delegate.duplicate_requested.connect(self.duplicate_requested)
        self._delegate.delete_requested.connect(self.delete_requested)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.reordered.connect(self._on_reordered)
        self._list.installEventFilter(self)
        self._list.viewport().installEventFilter(self)
        self._list.verticalScrollBar().valueChanged.connect(self._sync_rename_editor_geometry)
        root.addWidget(self._list, 0)
        self._create = QToolButton(self)
        self._create.setObjectName("ultraViewBoardPopoverCreate")
        self._create.setText("＋ 新建 Board")
        self._create.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._create.setCursor(Qt.PointingHandCursor)
        self._create.setFocusPolicy(Qt.TabFocus)
        self._create.setFixedHeight(_BOARD_CREATE_HEIGHT)
        self._create.setToolTip("新建 Board")
        self._create.setAccessibleName("新建 Board")
        self._create.clicked.connect(self.create_requested)
        root.addWidget(self._create, 0)

    def list_widget(self) -> QListWidget:
        return self._list

    def create_button(self) -> QToolButton:
        return self._create

    def board_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is None:
                continue
            board_id = str(item.data(Qt.UserRole) or "")
            if board_id:
                ids.append(board_id)
        return tuple(ids)

    def current_board_id(self) -> str:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is not None and bool(item.data(_BOARD_CURRENT_ROLE)):
                return str(item.data(Qt.UserRole) or "")
        return ""

    def action_rects_for(self, board_id: str) -> tuple[QRect, QRect]:
        """Viewport-local copy/delete hit rects for tests."""
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is None or str(item.data(Qt.UserRole) or "") != board_id:
                continue
            rect = self._list.visualItemRect(item)
            return _BoardListDelegate.action_rects(rect)
        return QRect(), QRect()

    def name_rect_for(self, board_id: str) -> QRect:
        """Viewport-local name hit rect for tests."""
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is None or str(item.data(Qt.UserRole) or "") != board_id:
                continue
            return _BoardListDelegate.name_rect(self._list.visualItemRect(item))
        return QRect()

    def begin_inline_rename(self, board_id: str = "") -> None:
        """Overlay a line edit on the row name; commit emits ``rename_requested``."""
        target = str(board_id or self._selected_board_id() or "")
        if not target:
            return
        if self._rename_editor is not None:
            if self._rename_board_id == target:
                self._rename_editor.setFocus(Qt.OtherFocusReason)
                self._rename_editor.selectAll()
                return
            self._close_inline_rename()
        item = self._item_for(target)
        if item is None:
            return
        self._list.setCurrentItem(item)
        rect = _BoardListDelegate.name_rect(self._list.visualItemRect(item))
        if not rect.isValid() or rect.width() < 8:
            return
        editor = _InlineNameEditor(self._list.viewport())
        editor.setObjectName("ultraViewBoardRowRename")
        editor.setFont(self._list.font())
        editor.setText(item.text())
        editor.setGeometry(rect)
        editor.committed.connect(self._on_inline_rename_committed)
        editor.cancelled.connect(self._on_inline_rename_cancelled)
        self._rename_editor = editor
        self._rename_board_id = target
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.OtherFocusReason)
        editor.selectAll()

    def _flush_pending_inline_rename(self) -> None:
        board_id = self._pending_rename_id
        self._pending_rename_id = ""
        if board_id:
            self.begin_inline_rename(board_id)

    def apply_internal_move(self, board_id: str, new_index: int) -> None:
        """Reorder as InternalMove would, then emit the same intent."""
        ids = list(self.board_ids())
        if board_id not in ids:
            return
        old = ids.index(board_id)
        target = max(0, min(int(new_index), len(ids) - 1))
        if old == target:
            return
        item = self._list.takeItem(old)
        if item is None:
            return
        self._list.insertItem(target, item)
        self._list.setCurrentItem(item)
        self._on_reordered(board_id, target)

    def set_boards(self, boards, active_board_id: str | None) -> None:
        if self._reordering:
            self._pending_boards = (tuple(boards), active_board_id)
            if not self._flush_timer.isActive():
                self._flush_timer.start(0)
            return
        self._apply_boards(boards, active_board_id)

    def set_create_enabled(self, enabled: bool, reason: str = "") -> None:
        self._create.setEnabled(bool(enabled))
        self._create.setToolTip(str(reason or "新建 Board"))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(BOARD_POPOVER_WIDTH, board_popover_height(self._list.count()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(BOARD_POPOVER_WIDTH, board_popover_height(1))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_list_to_contents()

    def relayout(self) -> None:
        """Recompute list height after the overlay geometry changes."""
        self._fit_list_to_contents()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._list and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_F2:
                board_id = self._selected_board_id()
                if board_id:
                    self.begin_inline_rename(board_id)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                board_id = self._selected_board_id()
                if board_id:
                    self.board_selected.emit(board_id)
                return True
        if watched is self._list.viewport():
            if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                item = self._list.itemAt(event.pos())
                if item is not None:
                    item_rect = self._list.visualItemRect(item)
                    copy_rect, delete_rect = _BoardListDelegate.action_rects(item_rect)
                    if copy_rect.contains(event.pos()) or delete_rect.contains(event.pos()):
                        return True
                    if _BoardListDelegate.name_rect(item_rect).contains(event.pos()):
                        board_id = str(item.data(Qt.UserRole) or "")
                        if board_id:
                            self._pending_rename_id = board_id
                            QTimer.singleShot(0, self._flush_pending_inline_rename)
                        return True
            if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                if event.button() == Qt.LeftButton:
                    item = self._list.itemAt(event.pos())
                    if item is not None:
                        copy_rect, delete_rect = _BoardListDelegate.action_rects(
                            self._list.visualItemRect(item)
                        )
                        if copy_rect.contains(event.pos()) or delete_rect.contains(event.pos()):
                            if event.type() == QEvent.MouseButtonRelease:
                                board_id = str(item.data(Qt.UserRole) or "")
                                if board_id and copy_rect.contains(event.pos()):
                                    self.duplicate_requested.emit(board_id)
                                elif board_id:
                                    self.delete_requested.emit(board_id)
                            return True
            if event.type() == QEvent.MouseMove:
                row = self._list.indexAt(event.pos()).row()
                if row != self._delegate.hovered_row():
                    self._delegate.set_hovered_row(row)
                    self._list.viewport().update()
                item = self._list.itemAt(event.pos())
                if item is not None:
                    copy_rect, delete_rect = _BoardListDelegate.action_rects(
                        self._list.visualItemRect(item)
                    )
                    if copy_rect.contains(event.pos()):
                        self._list.setToolTip("复制 Board")
                    elif delete_rect.contains(event.pos()):
                        self._list.setToolTip("删除 Board")
                    else:
                        self._list.setToolTip(item.toolTip())
            if event.type() == QEvent.Leave:
                if self._delegate.hovered_row() != -1:
                    self._delegate.set_hovered_row(-1)
                    self._list.viewport().update()
        return super().eventFilter(watched, event)

    def _list_content_height(self) -> int:
        return self._list.content_height()

    def _fit_list_to_contents(self) -> None:
        content = self._list_content_height()
        layout = self.layout()
        if layout is None:
            return
        margins = layout.contentsMargins()
        available = (
            self.height()
            - margins.top()
            - margins.bottom()
            - layout.spacing()
            - self._create.height()
        )
        if available <= 0:
            target = content
        else:
            target = max(BOARD_ROW_HEIGHT, min(content, available))
        if self._list.height() != target:
            self._list.setFixedHeight(target)
        if content <= target + 4:
            self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._list.verticalScrollBar().setValue(0)
            if self._list.height() != content and available >= content:
                self._list.setFixedHeight(content)
        else:
            self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def _selected_board_id(self) -> str:
        item = self._list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        board_id = str(item.data(Qt.UserRole) or "")
        if not board_id:
            return
        # Stay open on the already-current Board so a name double-click can
        # enter inline rename. Canvas click / Esc still close the overlay.
        if board_id == self.current_board_id():
            return
        self.board_selected.emit(board_id)

    def _item_for(self, board_id: str) -> QListWidgetItem | None:
        target = str(board_id or "")
        if not target:
            return None
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is not None and str(item.data(Qt.UserRole) or "") == target:
                return item
        return None

    def _on_inline_rename_committed(self, text: str) -> None:
        board_id = self._rename_board_id
        self._close_inline_rename()
        cleaned = str(text or "").strip()
        if cleaned and board_id:
            self.rename_requested.emit(board_id, cleaned)

    def _on_inline_rename_cancelled(self) -> None:
        self._close_inline_rename()

    def _close_inline_rename(self) -> None:
        self._pending_rename_id = ""
        editor = self._rename_editor
        self._rename_editor = None
        self._rename_board_id = ""
        if editor is None:
            return
        editor.discard()
        editor.hide()
        editor.deleteLater()

    def _sync_rename_editor_geometry(self, _value: int = 0) -> None:
        editor = self._rename_editor
        if editor is None:
            return
        item = self._item_for(self._rename_board_id)
        if item is None:
            self._close_inline_rename()
            return
        editor.setGeometry(_BoardListDelegate.name_rect(self._list.visualItemRect(item)))

    def _on_reordered(self, board_id: str, new_index: int) -> None:
        self._reordering = True
        self.boards_reordered.emit(str(board_id), int(new_index))
        if not self._flush_timer.isActive():
            self._flush_timer.start(0)

    def _end_reordering(self) -> None:
        self._reordering = False
        pending = self._pending_boards
        self._pending_boards = None
        if pending is not None:
            boards, active_id = pending
            self._apply_boards(boards, active_id)

    def _apply_boards(self, boards, active_board_id: str | None) -> None:
        self._close_inline_rename()
        parsed: list[tuple[str, str]] = []
        for index, board in enumerate(boards or ()):
            board_id = str(getattr(board, "board_id", "") or "")
            if not board_id:
                continue
            name = str(getattr(board, "name", "") or f"Board {index + 1}")
            parsed.append((board_id, name))
        blocked = self._list.blockSignals(True)
        self._list.clear()
        active = str(active_board_id or "")
        current_item: QListWidgetItem | None = None
        for board_id, name in parsed:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, board_id)
            item.setData(_BOARD_CURRENT_ROLE, board_id == active)
            item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsDragEnabled
                | Qt.ItemIsDropEnabled
            )
            item.setToolTip(name)
            self._list.addItem(item)
            if board_id == active:
                current_item = item
        if current_item is not None:
            self._list.setCurrentItem(current_item)
        self._list.blockSignals(blocked)
        intended = self._list_content_height()
        self._list.setFixedHeight(intended)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.verticalScrollBar().setValue(0)
        self.setMaximumHeight(board_popover_height(max(1, len(parsed))))
        self.updateGeometry()
        self._fit_list_to_contents()

class LayoutPicker(QFrame):
    """Eight template previews; Page owns confirmation and free-grid history."""

    layout_id_chosen = pyqtSignal(str)

    def __init__(
        self,
        labels: Mapping[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLayoutPopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._labels = dict(labels)
        self._buttons: dict[str, QToolButton] = {}
        self._view_count = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)
        heading = QLabel("布局", self)
        heading.setObjectName("ultraViewLayoutPopoverTitle")
        heading.setProperty("role", "popoverTitle")
        root.addWidget(heading, 0)
        self._intro = QLabel(self)
        self._intro.setObjectName("ultraViewLayoutPopoverIntro")
        self._intro.setWordWrap(True)
        self._intro.setText("选择模板 · 当前 0 个 View；自由网格可由左侧独立开关进入")
        root.addWidget(self._intro, 0)
        grid_host = QWidget(self)
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (layout_id, label) in enumerate(self._labels.items()):
            button = QToolButton(self)
            button.setObjectName(f"ultraViewLayoutThumb_{layout_id}")
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(layout_thumbnail_icon(layout_id))
            button.setIconSize(_LAYOUT_THUMB_SIZE)
            button.setToolTip(str(label))
            button.setAccessibleName(str(label))
            button.setProperty("layoutId", layout_id)
            button.setProperty("role", "layoutThumb")
            button.setMinimumSize(_LAYOUT_THUMB_CELL)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            button.clicked.connect(self._on_thumb_clicked)
            self._apply_thumb_caption(button, layout_id, current=False)
            self._group.addButton(button)
            self._buttons[layout_id] = button
            grid.addWidget(button, index // 2, index % 2)
        scroll = QScrollArea(self)
        scroll.setObjectName("ultraViewLayoutPopoverScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        scroll.setWidget(grid_host)
        self._scroll = scroll
        root.addWidget(scroll, 1)

    def thumb_button(self, layout_id: str) -> QToolButton | None:
        return self._buttons.get(str(layout_id))

    def intro_label(self) -> QLabel:
        return self._intro

    def _scrollbar_extent(self) -> int:
        return max(0, int(self.style().pixelMetric(QStyle.PM_ScrollBarExtent)))

    def sizeHint(self) -> QSize:  # noqa: N802
        cell_w, cell_h = _LAYOUT_THUMB_CELL.width(), _LAYOUT_THUMB_CELL.height()
        # 12 outer + two cells + gap + 8 content-to-viewport + scrollbar + 12 outer
        width = 12 + cell_w * 2 + 8 + 8 + self._scrollbar_extent() + 12
        return QSize(width, 10 + 22 + 8 + 36 + 8 + cell_h * 4 + 8 * 3 + 12)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        cell_w = _LAYOUT_THUMB_CELL.width()
        width = 12 + cell_w * 2 + 8 + 8 + self._scrollbar_extent() + 12
        return QSize(width, 160)

    def set_current(self, layout_id: str, *, free_grid: bool, view_count: int | None = None) -> None:
        if view_count is not None:
            try:
                self._view_count = max(0, int(view_count))
            except (TypeError, ValueError):
                self._view_count = 0
        is_free_grid = bool(free_grid)
        self._group.setExclusive(not is_free_grid)
        if is_free_grid:
            self._intro.setText("当前为自由网格；选择任一模板即可切回")
        else:
            self._intro.setText(
                f"选择模板 · 当前 {self._view_count} 个 View；自由网格可由左侧独立开关进入"
            )
        for candidate, button in self._buttons.items():
            checked = not is_free_grid and candidate == layout_id
            blocked = button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(blocked)
            self._apply_thumb_caption(button, candidate, current=checked)

    def _capacity_label(self, layout_id: str) -> str:
        slots = LAYOUT_SLOTS.get(str(layout_id), ())
        return f"{len(slots)} 格" if slots else ""

    def _apply_thumb_caption(self, button: QToolButton, layout_id: str, *, current: bool) -> None:
        label = str(self._labels.get(layout_id, layout_id))
        suffix = "当前" if current else self._capacity_label(layout_id)
        button.setText(f"{label}\n{suffix}" if suffix else label)

    def _on_thumb_clicked(self) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton):
            return
        layout_id = str(button.property("layoutId") or "")
        if layout_id:
            self.layout_id_chosen.emit(layout_id)
