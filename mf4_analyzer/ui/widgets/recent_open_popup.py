"""Presentation-only searchable popup for recent projects and data files.

Projects immutable ``RecentMatch`` rows and exists snapshots. It does not
read QSettings, call ``_open_paths``, or import MainWindow.
"""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.icons import Icons
from ...ui_kit.popup_shell import apply_popup_shell
from ...ui_kit.widgets import SearchField
from ..recent_files import (
    KIND_PROJECT,
    RecentEntry,
    RecentFilesStore,
    RecentMatch,
    format_recent_tooltip,
    match_recent_entries,
)

RECENT_POPUP_MAX_WIDTH = 640
RECENT_POPUP_TARGET_HEIGHT = 700
RECENT_POPUP_ROW_HEIGHT = 40
RECENT_POPUP_SEARCH_HEIGHT = 70
RECENT_POPUP_HEADER_HEIGHT = 32
RECENT_POPUP_FOOTER_HEIGHT = 48
RECENT_NAME_COLUMN_RATIO = 0.46
_SCREEN_MARGIN = 8
_ANCHOR_GAP = 4
_FRAME_GUARD = 1
_SURFACE_RADIUS = 12.0
_FALLBACK_AVAILABLE_GEOMETRY = QRect(0, 0, 1920, 1080)

_SURFACE_BG = QColor("#ffffff")
_SURFACE_BORDER = QColor("#b9cbe0")
_FOOTER_BG = QColor("#fafbfd")
_HEADER_BG = QColor("#f8fafd")
_HEADER_INK = QColor("#687b93")
_HEADER_HINT = QColor("#8a99aa")
_DIVIDER = QColor("#e5ebf2")
_ROW_HOVER = QColor("#f3f7fc")
_ROW_CURRENT = QColor("#edf5ff")
_ACCENT = QColor("#1769e0")
_INK = QColor("#172033")
_INK_MUTED = QColor("#64758b")
_INK_QUIET = QColor("#94a3b8")
_MARK_BG = QColor("#d8e9ff")
_MARK_FG = QColor("#074f9f")
_BADGE_BG = QColor("#eaf3ff")
_BADGE_FG = QColor("#1459a8")
_MISSING_BG = QColor("#f3f5f8")
_MISSING_FG = QColor("#8594a7")
_ICON_FILE_BG = QColor("#f0f4f9")
_ICON_PROJECT_BG = QColor("#eaf3ff")

_COL_NAME = 0
_COL_PATH = 1


class RecentOpenPopup(QFrame):
    """Parented ``Qt.Popup`` listing recent files with search and typed intents."""

    open_requested = pyqtSignal(str)
    clear_requested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("recentOpenPopup")
        apply_popup_shell(self)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.NoFocus)

        self._entries: tuple[RecentEntry, ...] = ()
        self._entry_snapshot: tuple = ()
        self._matches: tuple[RecentMatch, ...] = ()
        self._exists_by_identity: dict[str, bool] = {}
        self._current_identity = ""
        self._hover_row = -1
        self._closed_emitted = False
        self._restore_opener = False
        self._geometry_locked = False
        self._open_emitted = False
        self._home = str(Path.home())
        self._file_icon = Icons.file()
        self._project_icon = Icons.save_disk()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._surface = _RecentOpenSurface(self)
        self._surface.setObjectName("recentOpenSurface")
        surface_lay = QVBoxLayout(self._surface)
        surface_lay.setContentsMargins(
            _FRAME_GUARD, _FRAME_GUARD, _FRAME_GUARD, _FRAME_GUARD
        )
        surface_lay.setSpacing(0)
        root.addWidget(self._surface)

        search_bar = QWidget(self._surface)
        search_bar.setObjectName("recentOpenSearchBar")
        search_bar.setFixedHeight(RECENT_POPUP_SEARCH_HEIGHT)
        search_bar.setAttribute(Qt.WA_StyledBackground, True)
        search_lay = QHBoxLayout(search_bar)
        search_lay.setContentsMargins(16, 14, 16, 14)
        search_lay.setSpacing(12)
        self._search = SearchField(
            "搜索文件名或所在位置，例如 250 lowfri、P166 tlproj",
            search_bar,
        )
        self._search.setObjectName("recentOpenSearch")
        self._search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._count = QLabel(search_bar)
        self._count.setObjectName("recentOpenCount")
        self._count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        search_lay.addWidget(self._search, 1)
        search_lay.addWidget(self._count, 0)
        surface_lay.addWidget(search_bar)

        self._model = _RecentTableModel(self)
        self._table = QTableView(self._surface)
        self._table.setObjectName("recentOpenTable")
        self._table.setModel(self._model)
        self._header = _RecentHeaderView(self._table)
        self._table.setHorizontalHeader(self._header)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(RECENT_POPUP_ROW_HEIGHT)
        self._table.verticalHeader().setMinimumSectionSize(RECENT_POPUP_ROW_HEIGHT)
        self._table.verticalHeader().setMaximumSectionSize(RECENT_POPUP_ROW_HEIGHT)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.setTabKeyNavigation(False)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setAlternatingRowColors(False)
        self._table.setFrameShape(QFrame.NoFrame)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._table.setMouseTracking(True)
        self._table.viewport().setMouseTracking(True)
        self._table.viewport().setAutoFillBackground(False)
        self._table.horizontalHeader().setMinimumSectionSize(80)
        self._table.setItemDelegate(_RecentRowDelegate(self))
        self._table.clicked.connect(self._on_table_clicked)
        surface_lay.addWidget(self._table, 1)

        self._empty = QWidget(self._table.viewport())
        self._empty.setObjectName("recentOpenEmpty")
        empty_lay = QVBoxLayout(self._empty)
        empty_lay.setContentsMargins(24, 24, 24, 24)
        empty_lay.setSpacing(0)
        empty_lay.addStretch(1)
        empty_copy = QWidget(self._empty)
        empty_copy_lay = QVBoxLayout(empty_copy)
        empty_copy_lay.setContentsMargins(0, 0, 0, 0)
        empty_copy_lay.setSpacing(6)
        self._empty_title = QLabel("暂无最近记录", empty_copy)
        self._empty_title.setObjectName("recentOpenEmptyTitle")
        self._empty_title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self._empty_title.setWordWrap(False)
        self._empty_copy = QLabel("打开文件或项目后，会显示在这里。", empty_copy)
        self._empty_copy.setObjectName("recentOpenEmptyCopy")
        self._empty_copy.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self._empty_copy.setWordWrap(False)
        empty_copy_lay.addWidget(self._empty_title)
        empty_copy_lay.addWidget(self._empty_copy)
        empty_lay.addWidget(empty_copy, 0, Qt.AlignHCenter)
        empty_lay.addStretch(1)
        self._empty.hide()

        footer = QWidget(self._surface)
        footer.setObjectName("recentOpenFooter")
        footer.setFixedHeight(RECENT_POPUP_FOOTER_HEIGHT)
        footer.setAttribute(Qt.WA_StyledBackground, True)
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(16, 0, 12, 0)
        footer_lay.setSpacing(16)
        help_label = QLabel("↑ ↓ 选择   Enter 打开   Esc 清空 / 关闭", footer)
        help_label.setObjectName("recentOpenKeyHelp")
        self._clear = QPushButton("清除最近记录", footer)
        self._clear.setObjectName("recentOpenClear")
        self._clear.setCursor(Qt.PointingHandCursor)
        self._clear.setAutoDefault(False)
        self._clear.setDefault(False)
        self._clear.clicked.connect(self._emit_clear)
        footer_lay.addWidget(help_label, 1)
        footer_lay.addWidget(self._clear, 0)
        surface_lay.addWidget(footer)

        self._search.textChanged.connect(self._on_query_changed)
        self._search.returnPressed.connect(self._open_current)
        self._search.escape_requested.connect(self._on_escape_requested)
        self._search.installEventFilter(self)
        self._table.viewport().installEventFilter(self)
        self._table.installEventFilter(self)

        self.setMaximumWidth(RECENT_POPUP_MAX_WIDTH)
        self._update_chrome("")

    def populate(self, entries) -> None:
        entries = tuple(entries or ())
        snapshot = tuple(
            (entry.path, entry.kind, entry.opened_at) for entry in entries
        )
        if snapshot != self._entry_snapshot:
            self._entry_snapshot = snapshot
            self._entries = entries
            self._exists_by_identity = {
                entry.path: RecentFilesStore.exists(entry) for entry in entries
            }
        else:
            self._entries = entries
        self._refilter(self._search.text())

    def reset_for_show(self) -> None:
        self._restore_opener = False
        self._open_emitted = False
        self._hover_row = -1
        if self._search.text():
            self._search.clear()
        else:
            self._refilter("")
        self._select_first_openable()

    def show_at(self, anchor: QWidget) -> None:
        available = self._available_geometry_for(anchor)
        max_w = max(320, available.width() - 2 * _SCREEN_MARGIN)
        max_h = max(220, available.height() - 2 * _SCREEN_MARGIN)
        width = min(RECENT_POPUP_MAX_WIDTH, max_w)
        height = min(RECENT_POPUP_TARGET_HEIGHT, max_h)
        self.setFixedSize(width, height)
        self._sync_column_widths()
        self._sync_empty_geometry()

        anchor_top_left = anchor.mapToGlobal(anchor.rect().topLeft())
        anchor_bottom_left = anchor.mapToGlobal(anchor.rect().bottomLeft())
        left = available.left() + _SCREEN_MARGIN
        right = available.right() - _SCREEN_MARGIN - width + 1
        x = self._clamp(anchor_top_left.x(), left, right)

        top = available.top() + _SCREEN_MARGIN
        bottom = available.bottom() - _SCREEN_MARGIN - height + 1
        below = anchor_bottom_left.y() + _ANCHOR_GAP
        above = anchor_top_left.y() - _ANCHOR_GAP - height
        if below <= bottom:
            y = below
        elif above >= top:
            y = above
        else:
            y = self._clamp(below, top, bottom)
        self._closed_emitted = False
        self._open_emitted = False
        self._geometry_locked = True
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self._sync_column_widths()
        self._sync_empty_geometry()
        self.focus_search(select_all=False)

    def focus_search(self, select_all: bool = False) -> None:
        self._search.setFocus(Qt.ShortcutFocusReason)
        if select_all:
            self._search.selectAll()

    def sizeHint(self) -> QSize:
        return QSize(RECENT_POPUP_MAX_WIDTH, RECENT_POPUP_TARGET_HEIGHT)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._geometry_locked = False
        self._hover_row = -1
        self._emit_closed()

    def closeEvent(self, event):
        super().closeEvent(event)
        self._geometry_locked = False
        self._emit_closed()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_column_widths()
        self._sync_empty_geometry()

    def eventFilter(self, obj, event):
        if obj is self._search and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Up:
                self._move_current(-1)
                return True
            if key == Qt.Key_Down:
                self._move_current(1)
                return True
        if obj in (self._table, self._table.viewport()):
            etype = event.type()
            if etype == QEvent.MouseMove:
                index = self._table.indexAt(
                    self._table.viewport().mapFrom(obj, event.pos())
                    if obj is self._table
                    else event.pos()
                )
                row = index.row() if index.isValid() else -1
                if row != self._hover_row:
                    self._hover_row = row
                    self._table.viewport().update()
            elif etype == QEvent.Leave:
                if self._hover_row != -1:
                    self._hover_row = -1
                    self._table.viewport().update()
        return super().eventFilter(obj, event)

    def _on_query_changed(self, text: str) -> None:
        self._refilter(text)

    def _refilter(self, query: str) -> None:
        self._matches = match_recent_entries(
            self._entries, query, home=self._home,
        )
        self._model.set_rows(self._matches, self._exists_by_identity)
        self._update_chrome(query)
        if self._current_identity:
            for row, match in enumerate(self._matches):
                if (
                    match.entry.path == self._current_identity
                    and self._is_openable(match)
                ):
                    self._select_row(row, scroll=True)
                    return
        self._select_first_openable()

    def _update_chrome(self, query: str) -> None:
        total = len(self._entries)
        visible = len(self._matches)
        stripped = query.strip()
        if stripped:
            self._count.setText(f"{visible} / {total} 条匹配")
            self._header.set_sort_hint("按匹配度排序")
        else:
            self._count.setText(f"{total} 条记录")
            self._header.set_sort_hint("最近优先")
        self._clear.setEnabled(total > 0)
        if total == 0:
            self._empty_title.setText("暂无最近记录")
            self._empty_copy.setText("打开文件或项目后，会显示在这里。")
            self._empty.setVisible(True)
        elif visible == 0:
            self._empty_title.setText("没有匹配项")
            self._empty_copy.setText("试试缩短关键词，或搜索目录名。")
            self._empty.setVisible(True)
        else:
            self._empty.setVisible(False)
        self._empty_title.adjustSize()
        self._empty_copy.adjustSize()
        self._sync_empty_geometry()

    def _sync_empty_geometry(self) -> None:
        viewport = self._table.viewport()
        self._empty.setGeometry(viewport.rect())
        self._empty.raise_()

    def _scrollbar_gutter(self) -> int:
        bar = self._table.verticalScrollBar()
        hinted = bar.sizeHint().width() if bar is not None else 0
        metric = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        return max(8, hinted, metric)

    def _sync_column_widths(self) -> None:
        gutter = self._scrollbar_gutter()
        viewport_w = self._table.viewport().width()
        if viewport_w < 80:
            viewport_w = max(80, self.width() - 2 * _FRAME_GUARD - gutter)
        name_w = max(1, int(round(viewport_w * RECENT_NAME_COLUMN_RATIO)))
        path_w = max(1, viewport_w - name_w)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_NAME, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_PATH, QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_NAME, name_w)
        self._table.setColumnWidth(_COL_PATH, path_w)

    def _openable_rows(self) -> list[int]:
        return [
            row
            for row, match in enumerate(self._matches)
            if self._is_openable(match)
        ]

    def _is_openable(self, match: RecentMatch) -> bool:
        return bool(self._exists_by_identity.get(match.entry.path, False))

    def _select_first_openable(self) -> None:
        rows = self._openable_rows()
        if not rows:
            self._current_identity = ""
            self._table.clearSelection()
            self._table.viewport().update()
            return
        self._select_row(rows[0], scroll=True)

    def _select_row(self, row: int, *, scroll: bool = False) -> None:
        if row < 0 or row >= len(self._matches):
            self._current_identity = ""
            self._table.viewport().update()
            return
        match = self._matches[row]
        self._current_identity = match.entry.path
        index = self._model.index(row, 0)
        if scroll:
            self._table.scrollTo(index, QAbstractItemView.EnsureVisible)
        self._table.viewport().update()
        self._search.setFocus(Qt.OtherFocusReason)

    def _current_row(self) -> int:
        if not self._current_identity:
            return -1
        for row, match in enumerate(self._matches):
            if match.entry.path == self._current_identity:
                return row
        return -1

    def _move_current(self, step: int) -> None:
        rows = self._openable_rows()
        if not rows:
            return
        current = self._current_row()
        try:
            idx = rows.index(current)
        except ValueError:
            idx = 0 if step > 0 else len(rows) - 1
        else:
            idx = (idx + step) % len(rows)
        self._select_row(rows[idx], scroll=True)

    def _on_table_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or index.row() >= len(self._matches):
            return
        match = self._matches[index.row()]
        if not self._is_openable(match):
            return
        self._select_row(index.row())
        self._emit_open(match.entry.path)

    def _open_current(self) -> None:
        row = self._current_row()
        if row < 0:
            return
        match = self._matches[row]
        if not self._is_openable(match):
            return
        self._emit_open(match.entry.path)

    def _emit_open(self, path: str) -> None:
        if self._open_emitted:
            return
        self._open_emitted = True
        self.open_requested.emit(path)
        self.close()

    def _emit_clear(self) -> None:
        if not self._clear.isEnabled():
            return
        self.clear_requested.emit()

    def _on_escape_requested(self) -> None:
        self._restore_opener = True
        self.close()
        parent = self.parent()
        caret = getattr(parent, "btn_open_caret", None) if parent is not None else None
        if caret is not None:
            caret.setFocus(Qt.PopupFocusReason)

    def _emit_closed(self) -> None:
        if self._closed_emitted:
            return
        self._closed_emitted = True
        self.closed.emit()

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        if hi < lo:
            return lo
        return max(lo, min(hi, value))

    @staticmethod
    def _available_geometry_for(anchor: QWidget) -> QRect:
        window = anchor.window() if anchor is not None else None
        handle = window.windowHandle() if window is not None else None
        screen = handle.screen() if handle is not None else None
        if screen is None and anchor is not None:
            screen = QGuiApplication.screenAt(
                anchor.mapToGlobal(anchor.rect().center())
            )
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(_FALLBACK_AVAILABLE_GEOMETRY)
        return screen.availableGeometry()


class _RecentTableModel(QAbstractTableModel):
    def __init__(self, popup: RecentOpenPopup):
        super().__init__(popup)
        self._popup = popup
        self._rows: tuple[RecentMatch, ...] = ()
        self._exists: dict[str, bool] = {}

    def set_rows(self, rows: tuple[RecentMatch, ...], exists: dict[str, bool]) -> None:
        self.beginResetModel()
        self._rows = rows
        self._exists = exists
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return 2

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal or role != Qt.DisplayRole:
            return None
        if section == _COL_NAME:
            return "文件名"
        if section == _COL_PATH:
            return "所在位置"
        return None

    def flags(self, index):
        if not index.isValid() or index.row() >= len(self._rows):
            return Qt.NoItemFlags
        match = self._rows[index.row()]
        if not self._exists.get(match.entry.path, False):
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        match = self._rows[index.row()]
        missing = not self._exists.get(match.entry.path, False)
        if role in (Qt.DisplayRole, Qt.EditRole):
            if index.column() == _COL_NAME:
                return match.filename
            return match.display_parent
        if role == Qt.ToolTipRole:
            return format_recent_tooltip(match.entry)
        if role == Qt.AccessibleTextRole:
            kind = "项目" if match.entry.kind == KIND_PROJECT else "文件"
            text = f"{kind} {match.filename} {match.entry.path}"
            if missing:
                text += " 未找到，不可打开"
            return text
        if role == Qt.AccessibleDescriptionRole:
            extra = format_recent_tooltip(match.entry)
            if missing:
                return extra + "\n未找到，不可打开"
            return extra
        return None


class _RecentHeaderView(QHeaderView):
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setObjectName("recentOpenHeader")
        self.setFixedHeight(RECENT_POPUP_HEADER_HEIGHT)
        self.setSectionsClickable(False)
        self.setSectionsMovable(False)
        self.setHighlightSections(False)
        self.setSortIndicatorShown(False)
        self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setStretchLastSection(False)
        self._sort_hint = "最近优先"

    def set_sort_hint(self, text: str) -> None:
        if text == self._sort_hint:
            return
        self._sort_hint = text
        self.update()

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        painter.fillRect(rect, _HEADER_BG)
        font = QFont(painter.font())
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(_HEADER_INK)
        text_rect = rect.adjusted(12 if logicalIndex == _COL_NAME else 10, 0, -8, 0)
        if logicalIndex == _COL_NAME:
            painter.drawText(
                text_rect, Qt.AlignVCenter | Qt.AlignLeft, "文件名",
            )
            hint_font = QFont(font)
            hint_font.setBold(False)
            painter.setFont(hint_font)
            painter.setPen(_HEADER_HINT)
            painter.drawText(
                text_rect.adjusted(0, 0, -10, 0),
                Qt.AlignVCenter | Qt.AlignRight,
                self._sort_hint,
            )
            painter.setPen(QPen(_DIVIDER, 1))
            x = rect.right()
            painter.drawLine(x, rect.top(), x, rect.bottom())
        else:
            painter.drawText(
                text_rect, Qt.AlignVCenter | Qt.AlignLeft, "所在位置",
            )
        painter.setPen(QPen(QColor("#e8edf4"), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.restore()


class _RecentRowDelegate(QStyledItemDelegate):
    def __init__(self, popup: RecentOpenPopup):
        super().__init__(popup)
        self._popup = popup

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), RECENT_POPUP_ROW_HEIGHT)

    def paint(self, painter, option, index):
        popup = self._popup
        row = index.row()
        if row < 0 or row >= len(popup._matches):
            return
        match = popup._matches[row]
        missing = not popup._is_openable(match)
        current = match.entry.path == popup._current_identity and not missing
        hovered = row == popup._hover_row and not missing
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect
        if current:
            painter.fillRect(rect, _ROW_CURRENT)
        elif hovered:
            painter.fillRect(rect, _ROW_HOVER)
        else:
            painter.fillRect(rect, _SURFACE_BG)
        if current and index.column() == _COL_NAME:
            bar = QRect(rect.left(), rect.top() + 7, 3, rect.height() - 14)
            painter.fillRect(bar, _ACCENT)
        if index.column() == _COL_NAME:
            self._paint_name(painter, rect, match, missing)
            painter.setPen(QPen(_DIVIDER, 1))
            x = rect.right()
            painter.drawLine(x, rect.top(), x, rect.bottom())
        else:
            self._paint_path(painter, rect, match, missing)
        painter.restore()

    def _paint_name(self, painter, rect, match, missing):
        popup = self._popup
        icon_box = QRect(rect.left() + 8, rect.center().y() - 11, 22, 22)
        is_project = match.entry.kind == KIND_PROJECT
        painter.setPen(Qt.NoPen)
        painter.setBrush(_ICON_PROJECT_BG if is_project else _ICON_FILE_BG)
        painter.drawRoundedRect(QRectF(icon_box), 6, 6)
        icon = popup._project_icon if is_project else popup._file_icon
        icon.paint(painter, icon_box.adjusted(3, 3, -3, -3))

        badge_w = 0
        if is_project:
            badge_w = 34
        text_left = icon_box.right() + 8
        text_right = rect.right() - 8 - (badge_w + 6 if badge_w else 0)
        text_rect = QRect(text_left, rect.top(), max(8, text_right - text_left), rect.height())
        color = _INK_QUIET if missing else _INK
        self._draw_elided(
            painter,
            text_rect,
            match.filename,
            match.name_spans,
            color,
            Qt.ElideMiddle,
            bold=True,
            pixel=13,
        )
        if is_project:
            badge = QRect(rect.right() - 8 - 32, rect.center().y() - 10, 32, 20)
            painter.setPen(Qt.NoPen)
            painter.setBrush(_MISSING_BG if missing else _BADGE_BG)
            painter.drawRoundedRect(QRectF(badge), 5, 5)
            painter.setPen(_MISSING_FG if missing else _BADGE_FG)
            font = QFont(painter.font())
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(badge, Qt.AlignCenter, "项目")

    def _paint_path(self, painter, rect, match, missing):
        text_left = rect.left() + 10
        if missing:
            badge = QRect(rect.right() - 8 - 44, rect.center().y() - 10, 44, 20)
            painter.setPen(Qt.NoPen)
            painter.setBrush(_MISSING_BG)
            painter.drawRoundedRect(QRectF(badge), 5, 5)
            painter.setPen(_MISSING_FG)
            font = QFont(painter.font())
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(badge, Qt.AlignCenter, "未找到")
            text_right = badge.left() - 8
        else:
            text_right = rect.right() - 8
        text_rect = QRect(text_left, rect.top(), max(8, text_right - text_left), rect.height())
        color = _INK_QUIET if missing else _INK_MUTED
        self._draw_elided(
            painter,
            text_rect,
            match.display_parent,
            () if missing else match.path_spans,
            color,
            Qt.ElideMiddle,
            bold=False,
            pixel=12,
        )

    def _draw_elided(
        self,
        painter,
        rect,
        text,
        spans,
        color,
        elide_mode,
        *,
        bold,
        pixel,
    ):
        font = QFont(painter.font())
        font.setPixelSize(pixel)
        font.setBold(bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        elided = fm.elidedText(text, elide_mode, rect.width())
        if elided != text or not spans:
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
            return
        x = rect.left()
        marked = set()
        for start, end in spans:
            for index in range(max(0, start), min(len(text), end)):
                marked.add(index)
        run_start = 0
        while run_start < len(text):
            is_mark = run_start in marked
            run_end = run_start + 1
            while run_end < len(text) and (run_end in marked) == is_mark:
                run_end += 1
            chunk = text[run_start:run_end]
            width = fm.horizontalAdvance(chunk)
            chunk_rect = QRect(x, rect.top(), width, rect.height())
            if is_mark:
                painter.fillRect(
                    QRect(x, rect.center().y() - fm.height() // 2 + 1, width, fm.height() - 2),
                    _MARK_BG,
                )
                painter.setPen(_MARK_FG)
            else:
                painter.setPen(color)
            painter.drawText(chunk_rect, Qt.AlignVCenter | Qt.AlignLeft, chunk)
            x += width
            run_start = run_end


class _RecentOpenSurface(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, _SURFACE_RADIUS, _SURFACE_RADIUS)
        painter.fillPath(path, _SURFACE_BG)
        footer = self.findChild(QWidget, "recentOpenFooter")
        if footer is not None:
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(QRectF(footer.geometry()), _FOOTER_BG)
            painter.restore()
        header = self.findChild(QWidget, "recentOpenSearchBar")
        if header is not None:
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(QRectF(header.geometry()), _SURFACE_BG)
            painter.restore()
        painter.setPen(QPen(_SURFACE_BORDER, 1))
        painter.drawPath(path)
        painter.end()
