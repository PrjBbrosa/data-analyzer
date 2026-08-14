"""UltraView page widgets: library, board grid, cards, tray, focus layer.

Widgets emit typed intents. They do not import MainWindow, mutate BoardState,
or call analysis entry points. Preview records are duck-typed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import partial
from typing import Any, Mapping, Sequence

from PyQt5 import sip
from PyQt5.QtCore import QByteArray, QMimeData, QObject, QPoint, QRect, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QContextMenuEvent,
    QDrag,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
    COMPARE_FILTER_ALL,
    COMPARE_FILTERS,
    GRID_COLUMNS,
    LAYOUT_MODE_FREE_GRID,
    LAYOUT_SLOTS,
    MAX_GRID_ROWS,
    SECTION_LABELS_ZH,
    SOURCE_SECTIONS,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    ULTRAVIEW_REF_MIME,
    FreeGridPlacement,
    GridRect,
    UltraViewBoardState,
    UltraViewRef,
    parse_ref_payload,
    section_search_haystack,
)
from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome
from mf4_analyzer.ui_kit.widgets import SearchField

from .layouts import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    MIN_CARD_CHROME_HEIGHT,
    content_rect,
    logical_board_size,
    slot_rects,
)
from .free_grid import (
    GridMetrics,
    candidate_move,
    candidate_resize,
    clamp_rect,
    export_grid_metrics,
    grid_metrics,
    hit_handle,
    legal_grid_rect,
    rect_is_available,
    rect_to_pixels,
)
from .gesture import FreeGridGesture
from .ghost_overlay import GhostOverlay
from .compositor import compose_board, composed_slot_rects
from .._helpers import ULTRAVIEW_HINT_BAR_HEIGHT

HANDLE_CURSORS = {
    "n": Qt.SizeVerCursor,
    "s": Qt.SizeVerCursor,
    "e": Qt.SizeHorCursor,
    "w": Qt.SizeHorCursor,
    "nw": Qt.SizeFDiagCursor,
    "se": Qt.SizeFDiagCursor,
    "ne": Qt.SizeBDiagCursor,
    "sw": Qt.SizeBDiagCursor,
}

REPLACE_HOVER_MS = 600


class ReplaceHoverController(QObject):
    """Arm a replacement ring after a sustained hover. No lambda slots."""

    armed = pyqtSignal(str)
    cleared = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: str | None = None
        self._armed: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    def hover(self, key: str | None) -> None:
        if key is None:
            self.clear()
            return
        if key == self._armed:
            return
        if key == self._pending and self._timer.isActive():
            return
        self._armed = None
        self._pending = key
        self.cleared.emit()
        self._timer.start(REPLACE_HOVER_MS)

    def is_armed(self, key: str) -> bool:
        return self._armed == key

    def armed_key(self) -> str | None:
        return self._armed

    def clear(self) -> None:
        self._timer.stop()
        had = self._armed is not None or self._pending is not None
        self._pending = None
        self._armed = None
        if had:
            self.cleared.emit()

    def _on_timeout(self) -> None:
        self._armed = self._pending
        if self._armed is not None:
            self.armed.emit(self._armed)

LAYOUT_LABELS_ZH = {
    "split_horizontal": "左右双图",
    "split_vertical": "上下双图",
    "grid_2x2": "2 × 2",
    "hero_left_4": "左主图 + 3 辅图",
    "hero_top_4": "上主图 + 3 辅图",
    "grid_3x2": "3 × 2",
    "grid_3x3": "3 × 3",
    "grid_4x3": "4 × 3",
}

COMPARE_FILTER_LABELS_ZH = {
    COMPARE_FILTER_ALL: "全部",
    "time": "时间轴",
    "frequency": "频率轴",
    "time_freq": "时频轴",
    "order": "阶次轴",
}

STATUS_LABELS_ZH = {
    "fresh": "最新",
    STATUS_STALE: "源已变化",
    STATUS_MISSING: "尚无可用结果",
    STATUS_ORPHANED: "源已删除",
}

MISSING_CARD_COPY = "尚无可用结果，UltraView 不会后台计算"
STALE_CARD_COPY = "源已变化"
ORPHANED_CARD_COPY = "源 View 已删除"
DIMMED_OPACITY = 0.28
LIBRARY_DEFAULT_WIDTH = 224
TRAY_BODY_MAX_HEIGHT = 108


def _run_ultraview_drag(source: QWidget, mime: QMimeData, action, finished) -> None:
    """Run QDrag without parenting it to a widget that drop handlers may destroy.

    Drop mutations refresh the library/grid/tray while ``exec_`` is still on
    the stack. Parenting the drag to ``source`` and emitting from a deleted
    wrapper both abort via qFatal. A stable window host plus ``sip.isdeleted``
    keeps the nested loop from tearing down its own source.
    """
    host = source.window() if source is not None else None
    if host is None or sip.isdeleted(host):
        host = source
    drag = QDrag(host)
    drag.setMimeData(mime)
    try:
        drag.exec_(action)
    finally:
        try:
            if source is not None and not sip.isdeleted(source):
                finished()
        except RuntimeError:
            # The wrapper can lose its C++ object between the sip check and
            # emit; never let that escape a Qt virtual (qFatal).
            pass


@dataclass(frozen=True)
class LibraryRow:
    section: str
    view_id: str
    name: str = ""
    tab_color: str = ""
    status: str = ""
    on_board: bool = False
    source_summary: str = ""


@dataclass
class CardViewModel:
    slot_id: str
    section: str
    view_id: str
    title: str = ""
    tab_color: str = ""
    status: str = STATUS_MISSING
    source_summary: str = ""
    axis_kind: str | None = None
    x_unit: str = ""
    x_range: tuple[float, float] | None = None
    image: Any = None
    selected: bool = False
    dimmed: bool = False
    replacement_armed: bool = False
    show_title: bool = True
    show_source: bool = True


def coerce_library_row(row: LibraryRow | Mapping[str, Any]) -> LibraryRow:
    if isinstance(row, LibraryRow):
        return row
    return LibraryRow(
        section=str(row.get("section", "")),
        view_id=str(row.get("view_id", "")),
        name=str(row.get("name", "")),
        tab_color=str(row.get("tab_color", "")),
        status=str(row.get("status", "")),
        on_board=bool(row.get("on_board", False)),
        source_summary=str(row.get("source_summary", "")),
    )


def make_ref_mime(section: str, view_id: str) -> QMimeData:
    mime = QMimeData()
    payload = json.dumps(
        {"section": section, "view_id": view_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    mime.setData(ULTRAVIEW_REF_MIME, QByteArray(payload.encode("utf-8")))
    return mime


def extract_ref_strings(mime: QMimeData | None) -> tuple[str, str] | None:
    """Copy ``section`` / ``view_id`` out of ``QMimeData`` immediately.

    Callers must not keep ``mime`` for a queued callback. Invalid payloads
    return ``None``.
    """
    if mime is None or not mime.hasFormat(ULTRAVIEW_REF_MIME):
        return None
    try:
        raw = bytes(mime.data(ULTRAVIEW_REF_MIME)).decode("utf-8")
        payload = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    section = payload.get("section")
    view_id = payload.get("view_id")
    if not isinstance(section, str) or not isinstance(view_id, str):
        return None
    section_copy = str(section)
    view_id_copy = str(view_id)
    if parse_ref_payload({"section": section_copy, "view_id": view_id_copy}) is None:
        return None
    return section_copy, view_id_copy


def preview_image(record: Any) -> QImage | None:
    image = getattr(record, "image", None)
    if image is None:
        return None
    is_null = getattr(image, "isNull", None)
    if callable(is_null) and is_null():
        return None
    return image


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def _set_flag(widget: QWidget, name: str, on: bool) -> None:
    widget.setProperty(name, "true" if on else "false")
    _repolish(widget)


def _elide(label: QLabel, text: str) -> None:
    metrics = label.fontMetrics()
    label.setText(metrics.elidedText(text, Qt.ElideRight, max(0, label.width())))
    label.setToolTip(text if metrics.horizontalAdvance(text) > label.width() else "")


def _range_text(x_range: tuple[float, float] | None, x_unit: str) -> str:
    if x_range is None or len(x_range) != 2:
        return x_unit
    try:
        lo, hi = float(x_range[0]), float(x_range[1])
    except (TypeError, ValueError):
        return x_unit
    unit = f" {x_unit}" if x_unit else ""
    return f"{lo:g}–{hi:g}{unit}"


def _full_tooltip(name: str, section: str, source_summary: str, status: str) -> str:
    section_label = SECTION_LABELS_ZH.get(section, section)
    status_label = STATUS_LABELS_ZH.get(status, status)
    lines = [name or view_fallback(section, ""), f"{section_label} · {source_summary}".strip(" ·")]
    if status_label:
        lines.append(status_label)
    return "\n".join(line for line in lines if line)


def view_fallback(section: str, view_id: str) -> str:
    return view_id or SECTION_LABELS_ZH.get(section, section)


def _accept_ultraview_drag(event) -> bool:
    mime = event.mimeData()
    if mime is not None and mime.hasFormat(ULTRAVIEW_REF_MIME):
        event.acceptProposedAction()
        return True
    event.ignore()
    return False


class _ColorDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#94a3b8")
        self.setFixedSize(8, 8)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_color(self, color: str) -> None:
        self._color = QColor(color) if color else QColor("#94a3b8")
        if not self._color.isValid():
            self._color = QColor("#94a3b8")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())


class _ElideLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        super().setText(text)

    def set_full_text(self, text: str) -> None:
        self._full = text or ""
        self._apply()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        _elide(self, self._full)


class UltraViewHintBar(QFrame):
    """Status-bar hint host. ChartStack can later take this widget."""

    quickref_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartHintBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ULTRAVIEW_HINT_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        # Equal 3px vertical padding keeps a 22px inner slot so the styled
        # ``?`` and 11px copy stay centered and unclipped in a 28px strip.
        layout.setContentsMargins(10, 3, 8, 3)
        layout.setSpacing(4)
        self._quickref = QToolButton(self)
        self._quickref.setObjectName("chartHintQuickrefButton")
        self._quickref.setText("?")
        self._quickref.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._quickref.setAutoRaise(True)
        self._quickref.setCursor(Qt.PointingHandCursor)
        self._quickref.setToolTip("操作速查")
        self._quickref.clicked.connect(self.quickref_requested.emit)
        self._context = QLabel("拖到空槽添加 · 拖到卡片替换 · 双击临时放大", self)
        self._context.setObjectName("chartHintContext")
        self._context.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._context.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._context.setMaximumHeight(ULTRAVIEW_HINT_BAR_HEIGHT - 4)
        self._discovery = QLabel("UltraView 不计算", self)
        self._discovery.setObjectName("chartHintDiscovery")
        self._discovery.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._discovery.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._discovery.setMaximumHeight(ULTRAVIEW_HINT_BAR_HEIGHT - 4)
        layout.addWidget(self._quickref, 0, Qt.AlignVCenter)
        layout.addWidget(self._context, 1, Qt.AlignVCenter)
        layout.addWidget(self._discovery, 0, Qt.AlignVCenter)


class BoardSwitcher(QFrame):
    """Presentation-only multi-Board selector.

    The switcher receives immutable-ish Board DTOs from the Page and emits
    typed intents.  It intentionally never mutates a workspace: that keeps
    project state, confirmation policy, and the 20-Board creation limit in the
    state/coordinator owner rather than in a QWidget callback.
    """

    create_requested = pyqtSignal()
    duplicate_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)
    delete_requested = pyqtSignal(str)
    reorder_requested = pyqtSignal(str, int)
    board_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardSwitcher")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._board_ids: list[str] = []
        self._tab = QTabBar(self)
        self._tab.setObjectName("ultraViewBoardTabs")
        self._tab.setDocumentMode(True)
        self._tab.setUsesScrollButtons(True)
        self._tab.setElideMode(Qt.ElideRight)
        self._tab.setMovable(True)
        self._tab.setExpanding(False)
        self._tab.setTabsClosable(False)
        self._tab.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tab.currentChanged.connect(self._on_current_changed)
        self._tab.tabMoved.connect(self._on_tab_moved)
        self._tab.customContextMenuRequested.connect(self._on_context_menu)
        self._reordering = False
        self._pending_boards: tuple[tuple[Any, ...], str | None] | None = None
        self._flush_boards_timer = QTimer(self)
        self._flush_boards_timer.setSingleShot(True)
        self._flush_boards_timer.timeout.connect(self._end_reordering)

        self._add = QToolButton(self)
        self._add.setObjectName("ultraViewBoardAddButton")
        self._add.setText("+")
        self._add.setToolTip("新建 Board")
        self._add.setAutoRaise(True)
        self._add.clicked.connect(self.create_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 2)
        layout.setSpacing(4)
        layout.addWidget(self._tab, 1)
        layout.addWidget(self._add, 0)

    def tab_bar(self) -> QTabBar:
        return self._tab

    def add_button(self) -> QToolButton:
        return self._add

    def current_board_id(self) -> str | None:
        index = self._tab.currentIndex()
        if 0 <= index < len(self._board_ids):
            return self._board_ids[index]
        return None

    def board_ids(self) -> tuple[str, ...]:
        return tuple(self._board_ids)

    def set_boards(self, boards: Sequence[Any], active_board_id: str | None) -> None:
        """Project the supplied workspace without feeding signals back to it."""
        if self._reordering:
            self._pending_boards = (tuple(boards), active_board_id)
            if not self._flush_boards_timer.isActive():
                self._flush_boards_timer.start(0)
            return
        self._apply_boards(boards, active_board_id)

    def _end_reordering(self) -> None:
        self._reordering = False
        self._flush_pending_boards()

    def _flush_pending_boards(self) -> None:
        pending = self._pending_boards
        self._pending_boards = None
        if pending is None:
            return
        boards, active_board_id = pending
        self._apply_boards(boards, active_board_id)

    def _apply_boards(self, boards: Sequence[Any], active_board_id: str | None) -> None:
        parsed: list[tuple[str, str]] = []
        for index, board in enumerate(boards):
            board_id = str(getattr(board, "board_id", "") or "")
            if not board_id:
                continue
            name = str(getattr(board, "name", "") or f"Board {index + 1}")
            parsed.append((board_id, name))
        prior = self._tab.blockSignals(True)
        try:
            while self._tab.count():
                self._tab.removeTab(0)
            self._board_ids = [board_id for board_id, _name in parsed]
            for board_id, name in parsed:
                tab_index = self._tab.addTab(name)
                self._tab.setTabToolTip(tab_index, name)
                self._tab.setTabData(tab_index, board_id)
            current = self._board_ids.index(active_board_id) if active_board_id in self._board_ids else 0
            self._tab.setCurrentIndex(current if self._board_ids else -1)
        finally:
            self._tab.blockSignals(prior)

    def set_create_enabled(self, enabled: bool, reason: str = "") -> None:
        self._add.setEnabled(bool(enabled))
        self._add.setToolTip(reason or "新建 Board")

    def _board_id_at(self, index: int) -> str | None:
        if 0 <= index < len(self._board_ids):
            return self._board_ids[index]
        return None

    def _on_current_changed(self, index: int) -> None:
        if self._reordering:
            return
        board_id = self._board_id_at(index)
        if board_id is not None:
            self.board_selected.emit(board_id)

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        if not (0 <= from_index < len(self._board_ids) and 0 <= to_index < len(self._board_ids)):
            return
        board_id = self._board_ids.pop(from_index)
        self._board_ids.insert(to_index, board_id)
        self._reordering = True
        try:
            self.reorder_requested.emit(board_id, to_index)
        finally:
            # Leave ``_reordering`` set until the next event-loop turn so a
            # nested ``set_boards`` / ``currentChanged`` cannot tear the bar
            # down while ``tabMoved`` is still on the stack.
            if not self._flush_boards_timer.isActive():
                self._flush_boards_timer.start(0)

    def _on_context_menu(self, pos: QPoint) -> None:
        index = self._tab.tabAt(pos)
        board_id = self._board_id_at(index)
        if board_id is None:
            return
        menu = QMenu(self)
        menu.setObjectName("ultraViewBoardMenu")
        apply_rounded_menu_chrome(menu)
        duplicate = menu.addAction("复制 Board")
        rename = menu.addAction("重命名")
        remove = menu.addAction("删除 Board")
        chosen = menu.exec_(self._tab.mapToGlobal(pos))
        if chosen is duplicate:
            self.duplicate_requested.emit(board_id)
        elif chosen is rename:
            title = self._tab.tabText(index)
            text, accepted = QInputDialog.getText(self, "重命名 Board", "名称", text=title)
            if accepted and text.strip():
                self.rename_requested.emit(board_id, text.strip())
        elif chosen is remove:
            board_name = self._tab.tabText(index)
            answer = QMessageBox.question(
                self,
                "删除 Board",
                f"确定删除“{board_name}”吗？其中的 View 引用不会删除源 View。",
                QMessageBox.Cancel | QMessageBox.Yes,
                QMessageBox.Cancel,
            )
            if answer == QMessageBox.Yes:
                self.delete_requested.emit(board_id)


class BoardToolbar(QFrame):
    layout_changed = pyqtSignal(str)
    ratio_nudge_requested = pyqtSignal(int)
    copy_board_requested = pyqtSignal()
    export_png_requested = pyqtSignal(int)
    show_titles_toggled = pyqtSignal(bool)
    show_sources_toggled = pyqtSignal(bool)
    presentation_toggled = pyqtSignal(bool)
    overview_requested = pyqtSignal()
    board_name_changed = pyqtSignal(str)
    free_grid_toggled = pyqtSignal(bool)
    organize_free_grid_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardToolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._name = QLineEdit(self)
        self._name.setObjectName("ultraViewBoardName")
        self._name.setText("全局对比")
        self._name.setFrame(False)
        self._name.setPlaceholderText("Board 名称")
        self._name.setToolTip("编辑 Board 名称")
        self._name.editingFinished.connect(self._on_name_finished)
        layout.addWidget(self._name, 1)

        self._layout_combo = QComboBox(self)
        self._layout_combo.setObjectName("ultraViewLayoutCombo")
        for layout_id in LAYOUT_SLOTS:
            self._layout_combo.addItem(LAYOUT_LABELS_ZH[layout_id], layout_id)
        self._layout_combo.currentIndexChanged.connect(self._on_layout_index)
        layout.addWidget(self._layout_combo, 0)

        self._free_grid = QToolButton(self)
        self._free_grid.setObjectName("ultraViewFreeGridButton")
        self._free_grid.setText("自由网格")
        self._free_grid.setCheckable(True)
        self._free_grid.setToolTip("切换 12 列受控自由网格")
        self._free_grid.toggled.connect(self._on_free_grid_toggled)
        layout.addWidget(self._free_grid, 0)

        self._organize = QToolButton(self)
        self._organize.setObjectName("ultraViewOrganizeGridButton")
        self._organize.setText("整理")
        self._organize.setToolTip("移除自由网格中的空行")
        self._organize.clicked.connect(self.organize_free_grid_requested)
        self._organize.hide()
        layout.addWidget(self._organize, 0)

        self._copy = QPushButton("复制整板图", self)
        self._copy.setObjectName("ultraViewCopyBoardButton")
        self._copy.clicked.connect(self.copy_board_requested)
        layout.addWidget(self._copy, 0)

        self._export = QToolButton(self)
        self._export.setObjectName("ultraViewExportButton")
        self._export.setText("导出 PNG")
        self._export.setPopupMode(QToolButton.InstantPopup)
        self._export.setToolButtonStyle(Qt.ToolButtonTextOnly)
        export_menu = QMenu(self._export)
        apply_rounded_menu_chrome(export_menu)
        act_1x = export_menu.addAction("导出 PNG 1×")
        act_2x = export_menu.addAction("导出 PNG 2×")
        act_1x.triggered.connect(self._on_export_1x)
        act_2x.triggered.connect(self._on_export_2x)
        self._export.setMenu(export_menu)
        layout.addWidget(self._export, 0)

        self._display = QToolButton(self)
        self._display.setObjectName("ultraViewDisplayButton")
        self._display.setText("显示")
        self._display.setPopupMode(QToolButton.InstantPopup)
        self._display.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._display.setToolTip("显示标题和来源")
        display_menu = QMenu(self._display)
        apply_rounded_menu_chrome(display_menu)
        self._act_titles = display_menu.addAction("显示标题")
        self._act_titles.setCheckable(True)
        self._act_titles.setChecked(True)
        self._act_sources = display_menu.addAction("显示来源")
        self._act_sources.setCheckable(True)
        self._act_sources.setChecked(True)
        self._act_titles.toggled.connect(self.show_titles_toggled)
        self._act_sources.toggled.connect(self.show_sources_toggled)
        self._display.setMenu(display_menu)
        layout.addWidget(self._display, 0)

        self._presentation = QPushButton("演示", self)
        self._presentation.setObjectName("ultraViewPresentationButton")
        self._presentation.setCheckable(True)
        self._presentation.toggled.connect(self.presentation_toggled)
        layout.addWidget(self._presentation, 0)

        self._overview = QPushButton("整板概览", self)
        self._overview.setObjectName("ultraViewBoardOverviewButton")
        self._overview.setToolTip("查看完整 Board；点击卡片可返回阅读位置")
        self._overview.clicked.connect(self.overview_requested)
        layout.addWidget(self._overview, 0)

    def set_board_name(self, name: str) -> None:
        text = name or ""
        if self._name.text() == text:
            return
        blocked = self._name.blockSignals(True)
        self._name.setText(text)
        self._name.blockSignals(blocked)

    def board_name_edit(self) -> QLineEdit:
        return self._name

    def _on_name_finished(self) -> None:
        self.board_name_changed.emit(self._name.text())

    def set_layout_id(self, layout_id: str) -> None:
        index = self._layout_combo.findData(layout_id)
        if index < 0:
            return
        blocked = self._layout_combo.blockSignals(True)
        self._layout_combo.setCurrentIndex(index)
        self._layout_combo.blockSignals(blocked)

    def set_free_grid_enabled(self, enabled: bool) -> None:
        blocked = self._free_grid.blockSignals(True)
        self._free_grid.setChecked(bool(enabled))
        self._free_grid.blockSignals(blocked)
        self._layout_combo.setVisible(not bool(enabled))
        self._organize.setVisible(bool(enabled))

    def _on_free_grid_toggled(self, enabled: bool) -> None:
        if not enabled and self._free_grid.isVisible():
            answer = QMessageBox.question(
                self,
                "切回模板布局",
                "模板会按当前位置顺序重新排列卡片；超出模板容量的卡片会移入未放置区。继续吗？",
                QMessageBox.Cancel | QMessageBox.Yes,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                blocked = self._free_grid.blockSignals(True)
                self._free_grid.setChecked(True)
                self._free_grid.blockSignals(blocked)
                return
        self.free_grid_toggled.emit(bool(enabled))

    def set_presentation_checked(self, on: bool) -> None:
        blocked = self._presentation.blockSignals(True)
        self._presentation.setChecked(on)
        self._presentation.setText("退出演示" if on else "演示")
        self._presentation.blockSignals(blocked)

    def set_show_flags(self, titles: bool, sources: bool) -> None:
        blocked = self._act_titles.blockSignals(True)
        self._act_titles.setChecked(bool(titles))
        self._act_titles.blockSignals(blocked)
        blocked = self._act_sources.blockSignals(True)
        self._act_sources.setChecked(bool(sources))
        self._act_sources.blockSignals(blocked)

    def set_edit_visible(self, visible: bool) -> None:
        for widget in (
            self._layout_combo,
            self._copy,
            self._export,
            self._display,
        ):
            widget.setVisible(visible)

    def _on_layout_index(self, index: int) -> None:
        layout_id = self._layout_combo.itemData(index)
        if isinstance(layout_id, str) and layout_id:
            self.layout_changed.emit(layout_id)

    def _on_export_1x(self, _checked: bool = False) -> None:
        self.export_png_requested.emit(1)

    def _on_export_2x(self, _checked: bool = False) -> None:
        self.export_png_requested.emit(2)


class CompareRail(QFrame):
    compare_filter_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCompareRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for filter_id in COMPARE_FILTERS:
            button = QPushButton(COMPARE_FILTER_LABELS_ZH[filter_id], self)
            button.setObjectName("ultraViewCompareButton")
            button.setCheckable(True)
            button.setProperty("filterId", filter_id)
            button.setFocusPolicy(Qt.TabFocus)
            self._group.addButton(button)
            self._buttons[filter_id] = button
            layout.addWidget(button, 0)
        self._buttons[COMPARE_FILTER_ALL].setChecked(True)
        self._group.buttonClicked.connect(self._on_button)
        self._warning = QLabel("", self)
        self._warning.setObjectName("ultraViewAxisWarning")
        self._warning.setWordWrap(False)
        layout.addWidget(self._warning, 1)
        layout.addStretch(1)
        self._filter_id = COMPARE_FILTER_ALL

    def filter_id(self) -> str:
        return self._filter_id

    def set_filter_id(self, filter_id: str) -> None:
        if filter_id not in self._buttons:
            filter_id = COMPARE_FILTER_ALL
        self._filter_id = filter_id
        button = self._buttons[filter_id]
        blocked = button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(blocked)

    def set_axis_warning(self, text: str) -> None:
        self._warning.setText(text)
        self._warning.setVisible(bool(text))

    def _on_button(self, button: QPushButton) -> None:
        filter_id = str(button.property("filterId") or COMPARE_FILTER_ALL)
        if filter_id == self._filter_id:
            return
        self._filter_id = filter_id
        self.compare_filter_changed.emit(filter_id)


class LibraryRowWidget(QFrame):
    add_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, row: LibraryRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibraryRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(False)
        self._row = row
        self._press_pos: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 4, 4)
        layout.setSpacing(6)
        self._dot = _ColorDot(self)
        self._dot.set_color(row.tab_color)
        layout.addWidget(self._dot, 0, Qt.AlignVCenter)
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(0)
        self._name = _ElideLabel(row.name, self)
        self._name.set_full_text(row.name)
        self._meta = _ElideLabel(row.source_summary, self)
        self._meta.set_full_text(row.source_summary)
        self._meta.setObjectName("ultraViewLibraryMeta")
        copy.addWidget(self._name)
        copy.addWidget(self._meta)
        layout.addLayout(copy, 1)
        self._add = QToolButton(self)
        self._add.setObjectName("ultraViewLibraryAdd")
        self._add.setAutoRaise(False)
        self._add.setFixedSize(18, 18)
        self._add.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._add.clicked.connect(self._on_add)
        layout.addWidget(self._add, 0, Qt.AlignVCenter)
        self.set_row(row)

    def row(self) -> LibraryRow:
        return self._row

    def set_row(self, row: LibraryRow) -> None:
        self._row = row
        self._dot.set_color(row.tab_color)
        self._name.set_full_text(row.name or row.view_id)
        self._meta.set_full_text(row.source_summary)
        self._add.setText("−" if row.on_board else "+")
        self._add.setToolTip("从 Board 移除" if row.on_board else "添加到 Board")
        self._add.setProperty("action", "remove" if row.on_board else "add")
        _repolish(self._add)
        _set_flag(self, "onBoard", row.on_board)
        self.setToolTip(
            _full_tooltip(row.name or row.view_id, row.section, row.source_summary, row.status)
        )
        self.setAccessibleName(
            f"{SECTION_LABELS_ZH.get(row.section, row.section)} {row.name or row.view_id}"
        )

    def set_selected(self, on: bool) -> None:
        _set_flag(self, "selected", on)

    def _on_add(self) -> None:
        row = self._row
        if row.on_board:
            self.remove_requested.emit(row.section, row.view_id)
            return
        self.add_requested.emit(row.section, row.view_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = QPoint(event.pos())
            self.selected.emit(self._row.section, self._row.view_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._press_pos = None
        mime = make_ref_mime(self._row.section, self._row.view_id)
        self.drag_started.emit("library")
        _run_ultraview_drag(
            self, mime, Qt.CopyAction, self.drag_finished.emit
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_pos = None
        super().mouseReleaseEvent(event)


class _LibrarySectionHeader(QToolButton):
    """Chevron + label that toggles one View-library SOURCE_SECTIONS group."""

    toggled_section = pyqtSignal(str, bool)

    def __init__(
        self,
        section: str,
        count: int,
        expanded: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibrarySectionHead")
        self.setProperty("section", section)
        self._section = section
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMaximumHeight(24)
        self.setText(f"{SECTION_LABELS_ZH.get(section, section)}  {count}")
        blocked = self.blockSignals(True)
        self.setChecked(expanded)
        self.blockSignals(blocked)
        self._sync_arrow(expanded)
        self.toggled.connect(self._on_toggled)

    def section(self) -> str:
        return self._section

    def _on_toggled(self, checked: bool) -> None:
        self._sync_arrow(checked)
        self.toggled_section.emit(self._section, checked)

    def _sync_arrow(self, expanded: bool) -> None:
        self.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)


class ViewLibraryPanel(QFrame):
    add_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibrary")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(160)
        self.setMaximumWidth(320)
        self._rows: list[LibraryRow] = []
        self._selected: tuple[str, str] | None = None
        self._row_widgets: list[LibraryRowWidget] = []
        self._section_frames: dict[str, QFrame] = {}
        self._section_headers: dict[str, _LibrarySectionHeader] = {}
        self._expanded: dict[str, bool] = {section: True for section in SOURCE_SECTIONS}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(10, 8, 10, 6)
        title = QLabel("View 库", self)
        title.setObjectName("ultraViewLibraryTitle")
        self._count = QLabel("0", self)
        self._count.setObjectName("ultraViewLibraryCount")
        head.addWidget(title, 1)
        head.addWidget(self._count, 0)
        root.addLayout(head)

        self._search = SearchField("搜索 View…", self)
        self._search.setObjectName("ultraViewLibrarySearch")
        self._search.textChanged.connect(self._rebuild)
        search_wrap = QHBoxLayout()
        search_wrap.setContentsMargins(8, 0, 8, 6)
        search_wrap.addWidget(self._search)
        root.addLayout(search_wrap)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._body = QWidget(self._scroll)
        self._body.setObjectName("ultraViewLibraryBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(6, 0, 6, 8)
        self._body_layout.setSpacing(8)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, 1)
        self._rebuild()

    def search_field(self) -> QLineEdit:
        return self._search

    def selected_ref(self) -> tuple[str, str] | None:
        return self._selected

    def visible_rows(self) -> list[LibraryRow]:
        query = self._search.text().strip().lower()
        rows = []
        for row in self._rows:
            haystack = section_search_haystack(row.section, row.name, row.source_summary)
            if query and query not in haystack:
                continue
            rows.append(row)
        return rows

    def section_widgets(self) -> dict[str, QFrame]:
        return dict(self._section_frames)

    def section_headers(self) -> dict[str, QToolButton]:
        return dict(self._section_headers)

    def is_section_expanded(self, section: str) -> bool:
        return bool(self._expanded.get(section, True))

    def row_widgets(self) -> list[LibraryRowWidget]:
        return list(self._row_widgets)

    def set_rows(self, rows: Sequence[LibraryRow | Mapping[str, Any]]) -> None:
        self._rows = [coerce_library_row(row) for row in rows]
        self._count.setText(str(len(self._rows)))
        self._rebuild()

    def set_on_board(self, membership: set[UltraViewRef]) -> None:
        updated: list[LibraryRow] = []
        for row in self._rows:
            parsed = parse_ref_payload({"section": row.section, "view_id": row.view_id})
            on_board = parsed in membership if parsed is not None else row.on_board
            if on_board != row.on_board:
                row = LibraryRow(
                    section=row.section,
                    view_id=row.view_id,
                    name=row.name,
                    tab_color=row.tab_color,
                    status=row.status,
                    on_board=on_board,
                    source_summary=row.source_summary,
                )
            updated.append(row)
        self._rows = updated
        self._rebuild()

    def set_selected(self, section: str, view_id: str) -> None:
        self._selected = (section, view_id)
        for widget in self._row_widgets:
            row = widget.row()
            widget.set_selected(row.section == section and row.view_id == view_id)

    def focus_search(self) -> None:
        self._search.setFocus(Qt.OtherFocusReason)

    def _rebuild(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._row_widgets = []
        self._section_frames = {}
        self._section_headers = {}
        visible = self.visible_rows()
        by_section: dict[str, list[LibraryRow]] = {section: [] for section in SOURCE_SECTIONS}
        for row in visible:
            if row.section in by_section:
                by_section[row.section].append(row)
        query = self._search.text().strip()
        if query:
            for section, rows in by_section.items():
                if rows:
                    self._expanded[section] = True
        for section in SOURCE_SECTIONS:
            frame = QFrame(self._body)
            frame.setObjectName("ultraViewLibrarySection")
            frame.setProperty("section", section)
            section_layout = QVBoxLayout(frame)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(2)
            expanded = self._expanded.get(section, True)
            header = _LibrarySectionHeader(section, len(by_section[section]), expanded, frame)
            header.toggled_section.connect(self._on_section_toggled)
            section_layout.addWidget(header)
            self._section_headers[section] = header
            for row in by_section[section]:
                row_widget = LibraryRowWidget(row, frame)
                row_widget.add_requested.connect(self.add_requested)
                row_widget.remove_requested.connect(self.remove_requested)
                row_widget.locate_requested.connect(self.locate_requested)
                row_widget.selected.connect(self._on_row_selected)
                row_widget.drag_started.connect(self.drag_started)
                row_widget.drag_finished.connect(self.drag_finished)
                if self._selected == (row.section, row.view_id):
                    row_widget.set_selected(True)
                row_widget.setVisible(expanded)
                section_layout.addWidget(row_widget)
                self._row_widgets.append(row_widget)
            self._section_frames[section] = frame
            self._body_layout.addWidget(frame)
        self._body_layout.addStretch(1)

    def _on_section_toggled(self, section: str, expanded: bool) -> None:
        self._expanded[section] = bool(expanded)
        for widget in self._row_widgets:
            if widget.row().section == section:
                widget.setVisible(bool(expanded))

    def _on_row_selected(self, section: str, view_id: str) -> None:
        self.set_selected(section, view_id)


class EmptySlotWidget(QFrame):
    add_clicked = pyqtSignal(str)
    ref_dropped = pyqtSignal(str, str, str)
    drag_entered = pyqtSignal()

    def __init__(self, slot_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewEmptySlot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.TabFocus)
        self._slot_id = slot_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self._label = QLabel("＋\n添加 View", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setObjectName("ultraViewEmptySlotLabel")
        layout.addWidget(self._label, 1)
        self.setAccessibleName(f"空槽 {slot_id} 添加 View")

    def slot_id(self) -> str:
        return self._slot_id

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.add_clicked.emit(self._slot_id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.add_clicked.emit(self._slot_id)
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            _set_flag(self, "dropActive", True)
            self.drag_entered.emit()
            note = getattr(self.parentWidget(), "note_replace_hover", None)
            if callable(note):
                note(None)
            return
        _set_flag(self, "dropActive", False)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            _set_flag(self, "dropActive", True)
            return
        _set_flag(self, "dropActive", False)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        _set_flag(self, "dropActive", False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        _set_flag(self, "dropActive", False)
        extracted = extract_ref_strings(event.mimeData())
        event.acceptProposedAction()
        if extracted is None:
            return
        section, view_id = extracted
        self.ref_dropped.emit(self._slot_id, section, view_id)


class UltraViewCard(QFrame):
    open_source_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    copy_card_image_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    ref_dropped = pyqtSignal(str, str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, model: CardViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_custom_menu)
        self._model = model
        self._press_pos: QPoint | None = None
        self._menu: QMenu | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget(self)
        self._header.setObjectName("ultraViewCardHeader")
        self._header.setFixedHeight(CARD_HEADER_HEIGHT)
        header = QHBoxLayout(self._header)
        header.setContentsMargins(8, 5, 10, 5)
        header.setSpacing(6)
        self._dot = _ColorDot(self._header)
        header.addWidget(self._dot, 0)
        self._title = _ElideLabel("", self._header)
        header.addWidget(self._title, 1)
        self._status = QLabel("", self._header)
        self._status.setObjectName("ultraViewCardStatus")
        header.addWidget(self._status, 0)
        self._focus_btn = QToolButton(self._header)
        self._focus_btn.setObjectName("ultraViewCardFocusButton")
        self._focus_btn.setIcon(Icons.expand_focus())
        self._focus_btn.setIconSize(QSize(16, 16))
        self._focus_btn.setToolTip("临时放大")
        self._focus_btn.setCursor(Qt.PointingHandCursor)
        self._focus_btn.setAutoRaise(False)
        self._focus_btn.setFixedSize(24, 24)
        self._focus_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._focus_btn.clicked.connect(self._emit_focus)
        header.addWidget(self._focus_btn, 0, Qt.AlignVCenter)
        root.addWidget(self._header, 0)

        self._image = QLabel(self)
        self._image.setObjectName("ultraViewCardImage")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setWordWrap(True)
        self._image.setMinimumHeight(max(8, MIN_CARD_CHROME_HEIGHT // 4))
        self._image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._image, 1)

        self._orphan_bar = QWidget(self)
        self._orphan_bar.setObjectName("ultraViewCardOrphanBar")
        orphan = QHBoxLayout(self._orphan_bar)
        orphan.setContentsMargins(8, 2, 8, 2)
        orphan.setSpacing(6)
        self._rebind_btn = QPushButton("重新绑定", self._orphan_bar)
        self._rebind_btn.setObjectName("ultraViewCardRebindButton")
        self._rebind_btn.clicked.connect(self._emit_rebind)
        self._remove_btn = QPushButton("从总览移除", self._orphan_bar)
        self._remove_btn.setObjectName("ultraViewCardRemoveButton")
        self._remove_btn.clicked.connect(self._emit_remove)
        orphan.addWidget(self._rebind_btn)
        orphan.addWidget(self._remove_btn)
        orphan.addStretch(1)
        root.addWidget(self._orphan_bar, 0)

        self._footer = QWidget(self)
        self._footer.setObjectName("ultraViewCardFooter")
        self._footer.setFixedHeight(CARD_FOOTER_HEIGHT)
        footer = QHBoxLayout(self._footer)
        footer.setContentsMargins(8, 2, 8, 4)
        footer.setSpacing(6)
        self._foot_left = _ElideLabel("", self._footer)
        self._foot_source = _ElideLabel("", self._footer)
        self._foot_source.setObjectName("ultraViewCardSource")
        footer.addWidget(self._foot_left, 1)
        footer.addWidget(self._foot_source, 0)
        root.addWidget(self._footer, 0)

        self._raw_image: QImage | None = None
        self.apply_model(model)

    def model(self) -> CardViewModel:
        return self._model

    def slot_id(self) -> str:
        return self._model.slot_id

    def header_height(self) -> int:
        return self._header.height()

    def footer_height(self) -> int:
        return self._footer.height()

    def chrome_height(self) -> int:
        extra = self._orphan_bar.height() if self._orphan_bar.isVisible() else 0
        return self._header.height() + self._footer.height() + extra

    def apply_model(self, model: CardViewModel) -> None:
        self._model = model
        title = model.title or model.view_id
        self._dot.set_color(model.tab_color)
        self._title.setVisible(bool(model.show_title))
        self._title.set_full_text(title if model.show_title else "")
        if model.status == STATUS_MISSING:
            self._status.setText(STATUS_LABELS_ZH[STATUS_MISSING])
        elif model.status == STATUS_STALE:
            self._status.setText(STALE_CARD_COPY)
        elif model.status == STATUS_ORPHANED:
            self._status.setText(ORPHANED_CARD_COPY)
        else:
            self._status.setText("")
        self._status.setVisible(bool(self._status.text()))
        section_label = SECTION_LABELS_ZH.get(model.section, model.section)
        self._foot_left.set_full_text(
            f"{section_label} · {_range_text(model.x_range, model.x_unit)}"
        )
        self._foot_source.set_full_text(model.source_summary if model.show_source else "")
        self._footer.setVisible(bool(model.show_source))
        if model.show_source:
            self._footer.setFixedHeight(CARD_FOOTER_HEIGHT)
        else:
            self._footer.setFixedHeight(0)
        self._orphan_bar.setVisible(model.status == STATUS_ORPHANED)
        self._set_image(model)
        _set_flag(self, "selected", model.selected)
        _set_flag(self, "dimmed", model.dimmed)
        _set_flag(self, "orphaned", model.status == STATUS_ORPHANED)
        _set_flag(self, "replacementArmed", model.replacement_armed)
        self.setProperty("status", model.status)
        self._apply_dim(model.dimmed)
        _repolish(self)
        parts = [
            section_label,
            title,
            STATUS_LABELS_ZH.get(model.status, model.status),
        ]
        if model.selected:
            parts.append("已选中")
        if model.dimmed:
            parts.append("已弱化")
        if model.replacement_armed:
            parts.append("等待替换")
        if model.status == STATUS_ORPHANED:
            parts.append("源已删除")
        self.setAccessibleName(" ".join(part for part in parts if part))
        self.setToolTip(_full_tooltip(title, model.section, model.source_summary, model.status))

    def make_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("ultraViewCardMenu")
        apply_rounded_menu_chrome(menu)
        open_act = menu.addAction("打开原 View")
        focus_act = menu.addAction("临时放大")
        replace_act = menu.addAction("替换为…")
        unplaced_act = menu.addAction("移到未放置")
        remove_act = menu.addAction("从总览移除")
        copy_act = menu.addAction("复制本卡图像")
        open_act.triggered.connect(self._emit_open_source)
        focus_act.triggered.connect(self._emit_focus)
        replace_act.triggered.connect(self._emit_rebind)
        unplaced_act.triggered.connect(self._emit_unplaced)
        remove_act.triggered.connect(self._emit_remove)
        copy_act.triggered.connect(self._emit_copy)
        self._menu = menu
        return menu

    def _set_image(self, model: CardViewModel) -> None:
        image = model.image
        if image is not None and not (callable(getattr(image, "isNull", None)) and image.isNull()):
            self._raw_image = image if isinstance(image, QImage) else None
            self._image.setText("")
            self._fit_card_image()
            return
        self._raw_image = None
        self._image.setPixmap(QPixmap())
        if model.status == STATUS_MISSING:
            self._image.setText(MISSING_CARD_COPY)
        elif model.status == STATUS_ORPHANED:
            self._image.setText(ORPHANED_CARD_COPY)
        elif model.status == STATUS_STALE:
            self._image.setText(STALE_CARD_COPY)
        else:
            self._image.setText("")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_card_image()

    def _fit_card_image(self) -> None:
        if self._raw_image is None:
            return
        raw_w = self._raw_image.width()
        raw_h = self._raw_image.height()
        avail = self._image.size()
        if avail.width() < 2 or avail.height() < 2:
            return
        cap_w = max(1, min(avail.width(), raw_w))
        cap_h = max(1, min(avail.height(), raw_h))
        pixmap = QPixmap.fromImage(self._raw_image)
        self._image.setPixmap(
            pixmap.scaled(cap_w, cap_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _apply_dim(self, dimmed: bool) -> None:
        if dimmed:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(DIMMED_OPACITY)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)

    def _emit_open_source(self, _checked: bool = False) -> None:
        if self._model.status == STATUS_ORPHANED:
            self.rebind_arm_requested.emit(self._model.section, self._model.view_id)
            return
        self.open_source_requested.emit(self._model.section, self._model.view_id)

    def _emit_focus(self, _checked: bool = False) -> None:
        self.focus_requested.emit(self._model.section, self._model.view_id)

    def _emit_rebind(self, _checked: bool = False) -> None:
        self.rebind_arm_requested.emit(self._model.section, self._model.view_id)

    def _emit_unplaced(self, _checked: bool = False) -> None:
        self.move_to_unplaced_requested.emit(self._model.section, self._model.view_id)

    def _emit_remove(self, _checked: bool = False) -> None:
        self.remove_ref_requested.emit(self._model.section, self._model.view_id)

    def _emit_copy(self, _checked: bool = False) -> None:
        self.copy_card_image_requested.emit(self._model.section, self._model.view_id)

    def _on_custom_menu(self, pos: QPoint) -> None:
        menu = self.make_context_menu()
        menu.popup(self.mapToGlobal(pos))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = QPoint(event.pos())
            self.selected.emit(self._model.section, self._model.view_id)
            handler = getattr(self.parentWidget(), "handle_card_mouse_press", None)
            if callable(handler):
                handler(self, event)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.focus_requested.emit(self._model.section, self._model.view_id)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        parent = self.parentWidget()
        handler = getattr(parent, "handle_card_mouse_move", None)
        armed = getattr(parent, "is_slot_drag_armed", None)
        if callable(handler) and (
            event.buttons() & Qt.LeftButton or (callable(armed) and armed())
        ):
            handler(self, event)
            return
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._press_pos = None
        mime = make_ref_mime(self._model.section, self._model.view_id)
        self.drag_started.emit("card")
        _run_ultraview_drag(
            self, mime, Qt.MoveAction, self.drag_finished.emit
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        handler = getattr(self.parentWidget(), "handle_card_mouse_release", None)
        if callable(handler):
            handler(self, event)
            self._press_pos = None
            event.accept()
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._emit_focus()
            event.accept()
            return
        if key == Qt.Key_Delete:
            self._emit_remove()
            event.accept()
            return
        if key == Qt.Key_Backspace:
            self._emit_unplaced()
            event.accept()
            return
        if key == Qt.Key_O:
            self._emit_open_source()
            event.accept()
            return
        if key == Qt.Key_R:
            self._emit_rebind()
            event.accept()
            return
        if key == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            self._emit_copy()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            _set_flag(self, "dropActive", True)
            note = getattr(self.parentWidget(), "note_replace_hover", None)
            if callable(note):
                note(self._model.slot_id)
            return
        _set_flag(self, "dropActive", False)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            _set_flag(self, "dropActive", True)
            note = getattr(self.parentWidget(), "note_replace_hover", None)
            if callable(note):
                note(self._model.slot_id)
            return
        _set_flag(self, "dropActive", False)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        _set_flag(self, "dropActive", False)
        note = getattr(self.parentWidget(), "note_replace_hover", None)
        if callable(note):
            note(None)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        _set_flag(self, "dropActive", False)
        extracted = extract_ref_strings(event.mimeData())
        event.acceptProposedAction()
        parent = self.parentWidget()
        armed = getattr(parent, "is_replace_armed", None)
        clear = getattr(parent, "clear_replace_hover", None)
        slot_id = self._model.slot_id
        replace_ok = callable(armed) and armed(slot_id)
        if callable(clear):
            clear()
        if extracted is None:
            return
        if not replace_ok:
            return
        section, view_id = extracted
        self.ref_dropped.emit(slot_id, section, view_id)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = self.make_context_menu()
        menu.popup(event.globalPos())
        event.accept()


class BoardGrid(QWidget):
    add_clicked = pyqtSignal(str)
    ref_dropped = pyqtSignal(str, str, str)
    open_source_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    copy_card_image_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()
    slot_swap_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardGrid")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout_id = "hero_left_4"
        self._ratio = 0.67
        self._widgets: dict[str, QWidget] = {}
        self._viewport_size = QSize(0, 0)
        self._overlay = GhostOverlay(self)
        self._overlay.hide()
        self._replace = ReplaceHoverController(self)
        self._replace.armed.connect(self._on_replace_armed)
        self._replace.cleared.connect(self._on_replace_cleared)
        self._slot_source: str | None = None
        self._slot_press: QPoint | None = None
        self._slot_active = False

    def layout_id(self) -> str:
        return self._layout_id

    def slot_widget(self, slot_id: str) -> QWidget | None:
        return self._widgets.get(slot_id)

    def card_widgets(self) -> list[UltraViewCard]:
        return [widget for widget in self._widgets.values() if isinstance(widget, UltraViewCard)]

    def card_for(self, section: str, view_id: str) -> UltraViewCard | None:
        for card in self.card_widgets():
            model = card.model()
            if model.section == section and model.view_id == view_id:
                return card
        return None

    def set_grid(
        self,
        layout_id: str,
        primary_ratio: float,
        models: Mapping[str, CardViewModel | None],
    ) -> None:
        self._layout_id = layout_id
        self._ratio = primary_ratio
        wanted = set(LAYOUT_SLOTS[layout_id])
        for slot_id in list(self._widgets):
            if slot_id not in wanted:
                self._discard(slot_id)
        for slot_id in LAYOUT_SLOTS[layout_id]:
            model = models.get(slot_id)
            self._sync_slot(slot_id, model)
        self._sync_logical_size()
        self._relayout()

    def set_viewport_size(self, size: QSize) -> None:
        """Apply the scroll viewport size without deriving it from this widget.

        Once the Board is wider/taller than the viewport, ``self.size()`` is
        the logical canvas, not the visible window.  Keeping the two inputs
        separate is what makes scrolling and hit testing deterministic.
        """
        if size == self._viewport_size:
            return
        self._viewport_size = QSize(size)
        self._sync_logical_size()

    def logical_size(self) -> QSize:
        return QSize(self.size())

    def _sync_logical_size(self) -> None:
        viewport = self._viewport_size
        if viewport.width() <= 0 or viewport.height() <= 0:
            viewport = self.parentWidget().size() if self.parentWidget() is not None else self.size()
        try:
            width, height = logical_board_size(
                self._layout_id, (viewport.width(), viewport.height())
            )
        except ValueError:
            return
        target = QSize(width, height)
        if self.minimumSize() != target:
            self.setMinimumSize(target)
        if self.size() != target:
            self.resize(target)

    def _discard(self, slot_id: str) -> None:
        widget = self._widgets.pop(slot_id, None)
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()

    def _sync_slot(self, slot_id: str, model: CardViewModel | None) -> None:
        current = self._widgets.get(slot_id)
        if model is None:
            if isinstance(current, EmptySlotWidget):
                return
            self._discard(slot_id)
            empty = EmptySlotWidget(slot_id, self)
            empty.add_clicked.connect(self.add_clicked)
            empty.ref_dropped.connect(self.ref_dropped)
            self._widgets[slot_id] = empty
            empty.show()
            return
        if isinstance(current, UltraViewCard):
            current.apply_model(model)
            return
        self._discard(slot_id)
        card = UltraViewCard(model, self)
        card.open_source_requested.connect(self.open_source_requested)
        card.focus_requested.connect(self.focus_requested)
        card.rebind_arm_requested.connect(self.rebind_arm_requested)
        card.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        card.remove_ref_requested.connect(self.remove_ref_requested)
        card.copy_card_image_requested.connect(self.copy_card_image_requested)
        card.selected.connect(self.selected)
        card.ref_dropped.connect(self.ref_dropped)
        card.drag_started.connect(self.drag_started)
        card.drag_finished.connect(self.drag_finished)
        self._widgets[slot_id] = card
        card.show()
        self._raise_overlay()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()
        self._raise_overlay()

    def _raise_overlay(self) -> None:
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

    def _relayout(self) -> None:
        content = (
            BOARD_PADDING,
            BOARD_PADDING,
            max(0, self.width() - 2 * BOARD_PADDING),
            max(0, self.height() - 2 * BOARD_PADDING),
        )
        try:
            rects = slot_rects(self._layout_id, content, self._ratio)
        except ValueError:
            return
        for slot_id, (x, y, width, height) in rects.items():
            widget = self._widgets.get(slot_id)
            if widget is not None:
                widget.setGeometry(x, y, max(0, width), max(0, height))

    def slot_id_at(self, pos: QPoint) -> str | None:
        content = (
            BOARD_PADDING,
            BOARD_PADDING,
            max(0, self.width() - 2 * BOARD_PADDING),
            max(0, self.height() - 2 * BOARD_PADDING),
        )
        rects = slot_rects(self._layout_id, content, self._ratio)
        px, py = pos.x(), pos.y()
        for slot_id, (x, y, width, height) in rects.items():
            if x <= px <= x + width and y <= py <= y + height:
                return slot_id
        return None

    def note_replace_hover(self, key: str | None) -> None:
        self._replace.hover(key)

    def is_replace_armed(self, key: str) -> bool:
        return self._replace.is_armed(key)

    def clear_replace_hover(self) -> None:
        self._replace.clear()

    def _on_replace_armed(self, key: str) -> None:
        widget = self._widgets.get(key)
        if widget is None:
            return
        geom = widget.geometry()
        self._overlay.set_replace_ring((geom.x(), geom.y(), geom.width(), geom.height()))

    def _on_replace_cleared(self) -> None:
        self._overlay.set_replace_ring(None)

    def is_slot_drag_armed(self) -> bool:
        return self._slot_source is not None

    def handle_card_mouse_press(self, card: UltraViewCard, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._slot_source = card.model().slot_id
        self._slot_press = card.mapTo(self, event.pos())
        self._slot_active = False

    def handle_card_mouse_move(self, card: UltraViewCard, event: QMouseEvent) -> None:
        self._slot_drag_at(card.mapTo(self, event.pos()))

    def handle_card_mouse_release(self, card: UltraViewCard, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._finish_slot_drag(card.mapTo(self, event.pos()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._slot_source is not None and (
            event.buttons() & Qt.LeftButton or QWidget.mouseGrabber() is self
        ):
            self._slot_drag_at(event.pos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._slot_source is not None and event.button() == Qt.LeftButton:
            self._finish_slot_drag(event.pos())
            return
        super().mouseReleaseEvent(event)

    def _slot_drag_at(self, board_pos: QPoint) -> None:
        if self._slot_source is None or self._slot_press is None:
            return
        card = self._widgets.get(self._slot_source)
        if not isinstance(card, UltraViewCard):
            return
        if not self._slot_active:
            if (board_pos - self._slot_press).manhattanLength() < QApplication.startDragDistance():
                return
            self._slot_active = True
            self.drag_started.emit("card")
            if QWidget.mouseGrabber() is None:
                self.grabMouse()
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.4)
            card.setGraphicsEffect(effect)
        target = self.slot_id_at(board_pos)
        geom = card.geometry()
        ghost = (
            geom.x() + board_pos.x() - self._slot_press.x(),
            geom.y() + board_pos.y() - self._slot_press.y(),
            geom.width(),
            geom.height(),
        )
        target_widget = self._widgets.get(target) if target else None
        if target_widget is not None:
            tg = target_widget.geometry()
            highlight = (tg.x(), tg.y(), tg.width(), tg.height())
        else:
            highlight = ghost
        image = getattr(card, "_raw_image", None)
        self._overlay.set_move_preview(
            image,
            ghost,
            highlight,
            legal=target is not None and target != self._slot_source,
        )

    def _finish_slot_drag(self, board_pos: QPoint) -> None:
        source = self._slot_source
        active = self._slot_active
        card = self._widgets.get(source) if source else None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if isinstance(card, UltraViewCard):
            card.setGraphicsEffect(None)
        self._overlay.clear()
        self._slot_source = None
        self._slot_press = None
        self._slot_active = False
        if active:
            self.drag_finished.emit()
        if not active or source is None:
            return
        target = self.slot_id_at(board_pos)
        if target is None or target == source:
            return
        self.slot_swap_requested.emit(source, target)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        extracted = extract_ref_strings(event.mimeData())
        pos = QPoint(event.pos())
        event.acceptProposedAction()
        slot_id = self.slot_id_at(pos)
        widget = self._widgets.get(slot_id) if slot_id is not None else None
        occupied = isinstance(widget, UltraViewCard)
        if occupied and (slot_id is None or not self.is_replace_armed(slot_id)):
            self.clear_replace_hover()
            return
        self.clear_replace_hover()
        if extracted is None or slot_id is None:
            return
        self.ref_dropped.emit(slot_id, extracted[0], extracted[1])


class FreeGridCard(UltraViewCard):
    """A static preview card. Layout moves use the board gesture, not QDrag."""

    layout_key_requested = pyqtSignal(str, str, int, int, bool)
    preset_requested = pyqtSignal(str, str, str)

    def __init__(self, model: CardViewModel, parent: QWidget | None = None) -> None:
        super().__init__(model, parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(False)

    def make_context_menu(self) -> QMenu:
        menu = super().make_context_menu()
        size_menu = menu.addMenu("自由网格尺寸")
        for preset, label in (
            ("small", "小 3 × 2"),
            ("standard", "标准 4 × 3"),
            ("wide", "宽 6 × 3"),
            ("tall", "高 4 × 5"),
            ("large", "大 6 × 6"),
            ("banner", "横幅 12 × 4"),
        ):
            action = size_menu.addAction(label)
            action.triggered.connect(partial(self._emit_preset, preset))
        return menu

    def _emit_preset(self, preset: str, _checked: bool = False) -> None:
        self.preset_requested.emit(self._model.section, self._model.view_id, preset)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            already_selected = bool(self._model.selected)
            shift = bool(event.modifiers() & Qt.ShiftModifier)
            if not shift and not already_selected:
                self.selected.emit(self._model.section, self._model.view_id)
            handler = getattr(self.parentWidget(), "handle_card_mouse_press", None)
            if callable(handler):
                handler(self, event, already_selected)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        parent = self.parentWidget()
        handler = getattr(parent, "handle_card_mouse_move", None)
        gesture = getattr(parent, "gesture", None)
        armed = callable(gesture) and gesture().is_armed()
        if callable(handler) and (event.buttons() & Qt.LeftButton or armed):
            handler(self, event)
            return
        hover = getattr(parent, "handle_card_mouse_hover", None)
        if callable(hover):
            hover(self, event)
        QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        handler = getattr(self.parentWidget(), "handle_card_mouse_release", None)
        if callable(handler):
            handler(self, event)
        self._press_pos = None
        QWidget.mouseReleaseEvent(self, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.AltModifier:
            delta = {
                Qt.Key_Left: (-1, 0),
                Qt.Key_Right: (1, 0),
                Qt.Key_Up: (0, -1),
                Qt.Key_Down: (0, 1),
            }.get(event.key())
            if delta is not None:
                self.layout_key_requested.emit(
                    self._model.section,
                    self._model.view_id,
                    delta[0],
                    delta[1],
                    bool(event.modifiers() & Qt.ShiftModifier),
                )
                event.accept()
                return
        handler = getattr(self.parentWidget(), "handle_selection_key", None)
        if callable(handler) and handler(event):
            event.accept()
            return
        super().keyPressEvent(event)


class FreeGridBoard(QWidget):
    """Controlled 12-column visual projection of persisted free-grid state."""

    ref_dropped = pyqtSignal(str, str)
    geometry_requested = pyqtSignal(str, str, int, int, int, int, str)
    group_geometry_requested = pyqtSignal(object)
    preset_requested = pyqtSignal(str, str, str)
    open_source_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    copy_card_image_requested = pyqtSignal(str, str)
    selected = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()
    feedback_requested = pyqtSignal(str)
    replace_requested = pyqtSignal(str, str, str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewFreeGrid")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._placements: dict[UltraViewRef, FreeGridPlacement] = {}
        self._models: dict[UltraViewRef, CardViewModel] = {}
        self._widgets: dict[UltraViewRef, FreeGridCard] = {}
        self._viewport_size = QSize(0, 0)
        self._metrics = grid_metrics((240, 160), [])
        self._gesture = FreeGridGesture()
        self._overlay = GhostOverlay(self)
        self._overlay.hide()
        self._replace = ReplaceHoverController(self)
        self._replace.armed.connect(self._on_replace_armed)
        self._replace.cleared.connect(self._on_replace_cleared)
        self._pending_shift_toggle: UltraViewRef | None = None

    def set_viewport_size(self, size: QSize) -> None:
        if size == self._viewport_size:
            return
        self._viewport_size = QSize(size)
        self._sync_metrics()

    def metrics(self) -> GridMetrics:
        return self._metrics

    def gesture(self) -> FreeGridGesture:
        return self._gesture

    def ghost_overlay(self) -> GhostOverlay:
        return self._overlay

    def cancel_gesture(self) -> bool:
        cancelled = False
        if self._pending_shift_toggle is not None:
            self._pending_shift_toggle = None
            cancelled = True
        if self._gesture.session() is not None:
            self._finish_gesture(commit=False)
            cancelled = True
        if self._gesture.cancel_marquee():
            self._release_mouse_if_grabbed()
            self._overlay.set_marquee(None)
            self._sync_selection_handles()
            cancelled = True
        return cancelled

    def select_only(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        self._gesture.select_only(ref)
        self._apply_selection_flags()

    def clear_selection(self) -> bool:
        if not self._gesture.selection():
            return False
        self._gesture.clear_selection()
        self._apply_selection_flags()
        return True

    def card_for(self, section: str, view_id: str) -> FreeGridCard | None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        return self._widgets.get(ref) if ref is not None else None

    def card_widgets(self) -> list[FreeGridCard]:
        return list(self._widgets.values())

    def set_free_grid(
        self,
        placements: Sequence[FreeGridPlacement],
        models: Mapping[UltraViewRef, CardViewModel],
    ) -> None:
        self._placements = {item.ref: item for item in placements}
        self._models = dict(models)
        wanted = set(self._placements)
        for ref in list(self._widgets):
            if ref not in wanted:
                widget = self._widgets.pop(ref)
                widget.setParent(None)
                widget.deleteLater()
        for ref, placement in self._placements.items():
            model = self._models.get(ref)
            if model is None:
                continue
            widget = self._widgets.get(ref)
            if widget is None:
                widget = FreeGridCard(model, self)
                self._connect_card(widget)
                self._widgets[ref] = widget
                widget.show()
            else:
                widget.apply_model(model)
            widget.setAccessibleDescription(
                f"第 {placement.rect.row + 1} 行第 {placement.rect.column + 1} 列，"
                f"宽 {placement.rect.column_span} 高 {placement.rect.row_span}"
            )
        self._sync_metrics()
        self._gesture.restrict_selection(self._placements)
        self._raise_overlay()
        self._apply_selection_flags()

    def _connect_card(self, card: FreeGridCard) -> None:
        card.open_source_requested.connect(self.open_source_requested)
        card.focus_requested.connect(self.focus_requested)
        card.rebind_arm_requested.connect(self.rebind_arm_requested)
        card.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        card.remove_ref_requested.connect(self.remove_ref_requested)
        card.copy_card_image_requested.connect(self.copy_card_image_requested)
        card.selected.connect(self.selected)
        card.drag_started.connect(self.drag_started)
        card.drag_finished.connect(self.drag_finished)
        card.layout_key_requested.connect(self._on_layout_key)
        card.preset_requested.connect(self.preset_requested)

    def _raise_overlay(self) -> None:
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

    def _sync_metrics(self) -> None:
        viewport = self._viewport_size
        if viewport.width() <= 0 or viewport.height() <= 0:
            source = self.parentWidget()
            viewport = source.size() if source is not None else self.size()
        self._metrics = grid_metrics(
            (viewport.width(), viewport.height()), list(self._placements.values())
        )
        target = QSize(self._metrics.board_width, self._metrics.board_height)
        if self.minimumSize() != target:
            self.setMinimumSize(target)
        if self.size() != target:
            self.resize(target)
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()
        self._raise_overlay()

    def _relayout(self) -> None:
        if self._gesture.is_active():
            return
        for ref, placement in self._placements.items():
            widget = self._widgets.get(ref)
            if widget is not None:
                widget.setGeometry(*rect_to_pixels(placement.rect, self._metrics))
        self._raise_overlay()
        self._apply_selection_flags()

    def _grid_at(self, pos: QPoint, *, column_span: int = 1, row_span: int = 1) -> tuple[int, int]:
        legal = legal_grid_rect(
            (pos.x(), pos.y()),
            self._metrics,
            column_span=column_span,
            row_span=row_span,
        )
        return legal.column, legal.row

    def _legal_grid_rect(self, rect: GridRect) -> GridRect:
        return clamp_rect(rect)

    def _board_pos(self, card: QWidget, local: QPoint) -> tuple[int, int]:
        mapped = card.mapTo(self, local)
        return mapped.x(), mapped.y()

    def _apply_selection_flags(self) -> None:
        selected = self._gesture.selection()
        for ref, widget in self._widgets.items():
            model = widget.model()
            flag = ref in selected
            if model.selected == flag:
                continue
            updated = replace(model, selected=flag)
            self._models[ref] = updated
            widget.apply_model(updated)
        self._sync_selection_handles()

    def _sync_selection_handles(self) -> None:
        if self._gesture.is_active() or self._gesture.marquee() is not None:
            return
        rects = []
        for ref in self._gesture.selection():
            widget = self._widgets.get(ref)
            if widget is None:
                continue
            geom = widget.geometry()
            rects.append((geom.x(), geom.y(), geom.width(), geom.height()))
        self._overlay.set_selection_rects(rects, handles=len(rects) == 1)

    def handle_card_mouse_press(
        self,
        card: FreeGridCard,
        event: QMouseEvent,
        already_selected: bool = False,
    ) -> None:
        if event.button() != Qt.LeftButton:
            return
        ref = parse_ref_payload(
            {"section": card.model().section, "view_id": card.model().view_id}
        )
        placement = self._placements.get(ref) if ref is not None else None
        if ref is None or placement is None:
            return
        self._pending_shift_toggle = None
        if event.modifiers() & Qt.ShiftModifier:
            handle = None
            if already_selected and len(self._gesture.selection()) == 1:
                handle = hit_handle(
                    (0, 0, card.width(), card.height()),
                    (event.pos().x(), event.pos().y()),
                )
            if handle is not None:
                board_pos = self._board_pos(card, event.pos())
                grab = (event.pos().x(), event.pos().y())
                self._gesture.press_resize(ref, placement.rect, handle, board_pos, grab)
                return
            self._pending_shift_toggle = ref
            return
        if ref not in self._gesture.selection():
            self._gesture.select_only(ref)
            self._apply_selection_flags()
        handle = None
        if already_selected and len(self._gesture.selection()) == 1:
            handle = hit_handle(
                (0, 0, card.width(), card.height()),
                (event.pos().x(), event.pos().y()),
            )
        board_pos = self._board_pos(card, event.pos())
        grab = (event.pos().x(), event.pos().y())
        group_origins = None
        if handle is None:
            group_origins = {
                item: self._placements[item].rect
                for item in self._gesture.selection()
                if item in self._placements
            }
        if handle is not None:
            self._gesture.press_resize(ref, placement.rect, handle, board_pos, grab)
        else:
            self._gesture.press(
                ref, placement.rect, board_pos, grab, group_origins=group_origins
            )

    def handle_card_mouse_hover(self, card: FreeGridCard, event: QMouseEvent) -> None:
        if (
            not card.model().selected
            or len(self._gesture.selection()) != 1
            or self._gesture.is_armed()
        ):
            card.unsetCursor()
            return
        handle = hit_handle(
            (0, 0, card.width(), card.height()),
            (event.pos().x(), event.pos().y()),
        )
        cursor = HANDLE_CURSORS.get(handle) if handle is not None else None
        if cursor is None:
            card.unsetCursor()
        else:
            card.setCursor(cursor)

    def handle_card_mouse_move(self, card: FreeGridCard, event: QMouseEvent) -> None:
        self._update_gesture_at(
            self._board_pos(card, event.pos()),
            keep_aspect=bool(event.modifiers() & Qt.ShiftModifier),
        )

    def handle_card_mouse_release(self, card: FreeGridCard, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._finish_pending_shift_toggle():
            return
        if self._gesture.is_armed():
            self._update_gesture_at(
                self._board_pos(card, event.pos()),
                keep_aspect=bool(event.modifiers() & Qt.ShiftModifier),
            )
        self._finish_gesture(commit=True)

    def _finish_pending_shift_toggle(self) -> bool:
        ref = self._pending_shift_toggle
        self._pending_shift_toggle = None
        if ref is None:
            return False
        self._gesture.toggle_selected(ref)
        self._apply_selection_flags()
        return True

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        if self._card_at(event.pos()) is not None:
            super().mousePressEvent(event)
            return
        additive = bool(event.modifiers() & Qt.ShiftModifier)
        if not additive:
            self._gesture.clear_selection()
            self._apply_selection_flags()
        self._gesture.begin_marquee((event.pos().x(), event.pos().y()), additive)
        self._overlay.set_marquee(self._gesture.marquee_rect())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        grabbed = QWidget.mouseGrabber() is self
        if self._gesture.marquee() is not None and (
            event.buttons() & Qt.LeftButton or grabbed
        ):
            self._gesture.update_marquee((event.pos().x(), event.pos().y()))
            self._overlay.set_marquee(self._gesture.marquee_rect())
            if QWidget.mouseGrabber() is None:
                self.grabMouse()
            return
        if self._gesture.is_armed() and (event.buttons() & Qt.LeftButton or grabbed):
            self._update_gesture_at(
                (event.pos().x(), event.pos().y()),
                keep_aspect=bool(event.modifiers() & Qt.ShiftModifier),
            )
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._gesture.marquee() is not None:
            session = self._gesture.take_marquee()
            self._release_mouse_if_grabbed()
            self._overlay.set_marquee(None)
            if session is not None:
                self._finish_marquee(session)
            self.setFocus(Qt.OtherFocusReason)
            return
        if event.button() == Qt.LeftButton and self._finish_pending_shift_toggle():
            return
        if self._gesture.is_armed() and event.button() == Qt.LeftButton:
            self._update_gesture_at(
                (event.pos().x(), event.pos().y()),
                keep_aspect=bool(event.modifiers() & Qt.ShiftModifier),
            )
            self._finish_gesture(commit=True)
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.handle_selection_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def handle_selection_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key not in (Qt.Key_Delete, Qt.Key_Backspace):
            return False
        refs = [ref for ref in self._gesture.selection() if ref in self._widgets]
        if not refs:
            return False
        for ref in refs:
            if key == Qt.Key_Delete:
                self.remove_ref_requested.emit(ref.section, ref.view_id)
            else:
                self.move_to_unplaced_requested.emit(ref.section, ref.view_id)
        return True

    def _finish_marquee(self, session) -> None:
        x, y, width, height = session.rect()
        if width < 4 and height < 4:
            self._sync_selection_handles()
            return
        box = QRect(x, y, width, height)
        hits = [
            ref
            for ref, widget in self._widgets.items()
            if widget.geometry().intersects(box)
        ]
        if session.additive:
            self._gesture.add_to_selection(hits)
        else:
            self._gesture.set_selection(hits)
        self._apply_selection_flags()

    def _release_mouse_if_grabbed(self) -> None:
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()

    def _update_gesture_at(
        self, board_pos: tuple[int, int], *, keep_aspect: bool = False
    ) -> None:
        session = self._gesture.update(
            board_pos,
            self._metrics,
            tuple(self._placements.values()),
            QApplication.startDragDistance(),
            keep_aspect=keep_aspect,
        )
        if session is None or not session.active:
            return
        if QWidget.mouseGrabber() is None:
            self.grabMouse()
        members = session.group_origins or {session.ref: session.origin}
        started = False
        for ref in members:
            card = self._widgets.get(ref)
            if card is None or card.graphicsEffect() is not None:
                continue
            if not started:
                self.drag_started.emit("layout")
                started = True
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.4)
            card.setGraphicsEffect(effect)
        ghosts = []
        ghost_rects = session.group_ghost_pixels(self._metrics, board_pos)
        refs = list(members)
        if len(ghost_rects) != len(refs):
            refs = [session.ref]
            ghost_rects = (session.ghost_pixels(self._metrics, board_pos),)
        for ref, ghost in zip(refs, ghost_rects):
            card = self._widgets.get(ref)
            image = getattr(card, "_raw_image", None) if card is not None else None
            ghosts.append((image, ghost))
        highlights = session.group_highlight_pixels(self._metrics)
        self._overlay.set_move_previews(
            ghosts,
            highlights,
            legal=session.legal,
            badge=session.badge(),
            handles=session.handle is not None,
        )

    def _finish_gesture(self, *, commit: bool) -> None:
        session = self._gesture.take()
        self._release_mouse_if_grabbed()
        if session is None:
            return
        members = session.group_origins or {session.ref: session.origin}
        for ref in members:
            card = self._widgets.get(ref)
            if card is not None:
                card.setGraphicsEffect(None)
                card.unsetCursor()
        self._overlay.clear()
        self._sync_selection_handles()
        if session.active:
            self.drag_finished.emit()
        if not commit or not session.active:
            return
        if session.is_group_move():
            self._commit_group_move(session)
            return
        candidate = self._legal_grid_rect(session.candidate)
        if not session.legal or not rect_is_available(
            candidate, self._placements.values(), excluding=session.ref
        ):
            self.feedback_requested.emit("目标位置与其他卡片重叠")
            return
        reason = "drag-resize" if session.handle else "drag-move"
        self._request_geometry(session.ref, candidate, reason)

    def _commit_group_move(self, session) -> None:
        if not session.legal:
            self.feedback_requested.emit("目标位置与其他卡片重叠")
            return
        updates = []
        for ref, rect in sorted(
            session.group_candidates.items(),
            key=lambda item: (item[0].section, item[0].view_id),
        ):
            placement = self._placements.get(ref)
            if placement is None:
                return
            candidate = self._legal_grid_rect(rect)
            if candidate != rect:
                self.feedback_requested.emit("目标位置与其他卡片重叠")
                return
            if candidate != placement.rect:
                updates.append(
                    (
                        ref.section,
                        ref.view_id,
                        candidate.column,
                        candidate.row,
                        candidate.column_span,
                        candidate.row_span,
                    )
                )
        if updates:
            self.group_geometry_requested.emit(tuple(updates))

    def _request_geometry(self, ref: UltraViewRef, rect: GridRect, reason: str) -> bool:
        placement = self._placements.get(ref)
        if placement is None or rect == placement.rect:
            return False
        if not rect_is_available(rect, self._placements.values(), excluding=ref):
            self.feedback_requested.emit("目标位置与其他卡片重叠")
            return False
        self.geometry_requested.emit(
            ref.section,
            ref.view_id,
            rect.column,
            rect.row,
            rect.column_span,
            rect.row_span,
            reason,
        )
        return True

    def _on_layout_key(
        self, section: str, view_id: str, column_delta: int, row_delta: int, resize: bool
    ) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        placement = self._placements.get(ref) if ref is not None else None
        if placement is None:
            return
        candidate = (
            candidate_resize(placement.rect, column_delta, row_delta)
            if resize
            else candidate_move(placement.rect, column_delta, row_delta)
        )
        self._request_geometry(
            ref,
            self._legal_grid_rect(candidate),
            "keyboard-resize" if resize else "keyboard-move",
        )

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _accept_ultraview_drag(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if not _accept_ultraview_drag(event):
            return
        event.acceptProposedAction()
        card = self._card_at(event.pos())
        if card is None:
            self._replace.hover(None)
            return
        self._replace.hover(f"{card.model().section}/{card.model().view_id}")

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._replace.clear()
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        ref = extract_ref_strings(event.mimeData())
        card = self._card_at(event.pos())
        event.acceptProposedAction()
        if card is not None:
            key = f"{card.model().section}/{card.model().view_id}"
            if ref is not None and self._replace.is_armed(key):
                self.replace_requested.emit(
                    card.model().section, card.model().view_id, ref[0], ref[1]
                )
            self._replace.clear()
            return
        self._replace.clear()
        if ref is not None:
            self.ref_dropped.emit(*ref)

    def _card_at(self, pos: QPoint) -> FreeGridCard | None:
        for widget in self._widgets.values():
            if widget.geometry().contains(pos):
                return widget
        return None

    def _on_replace_armed(self, key: str) -> None:
        section, _, view_id = key.partition("/")
        card = self.card_for(section, view_id)
        if card is None:
            return
        geom = card.geometry()
        self._overlay.set_replace_ring((geom.x(), geom.y(), geom.width(), geom.height()))

    def _on_replace_cleared(self) -> None:
        self._overlay.set_replace_ring(None)
        self._sync_selection_handles()


class FreeGridMinimap(QFrame):
    """Cheap free-grid navigator; it draws bounds only, never preview pixels."""

    viewport_requested = pyqtSignal(QRect)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewFreeGridMinimap")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(168, 112)
        self._metrics: GridMetrics | None = None
        self._placements: tuple[FreeGridPlacement, ...] = ()
        self._viewport = QRect()

    def set_projection(
        self,
        metrics: GridMetrics,
        placements: Sequence[FreeGridPlacement],
        viewport: QRect,
    ) -> None:
        self._metrics = metrics
        self._placements = tuple(placements)
        self._viewport = QRect(viewport)
        self.update()

    def _scale(self) -> tuple[float, float]:
        if self._metrics is None:
            return 1.0, 1.0
        return (
            max(1, self.width() - 12) / float(max(1, self._metrics.board_width)),
            max(1, self.height() - 12) / float(max(1, self._metrics.board_height)),
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._metrics is None:
            return
        sx, sy = self._scale()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.fillRect(self.rect(), QColor("#ffffff"))
            painter.setPen(QColor("#d7dee8"))
            painter.drawRect(5, 5, self.width() - 10, self.height() - 10)
            painter.setBrush(QColor("#bcd5f5"))
            painter.setPen(QColor("#6da3d9"))
            for item in self._placements:
                x, y, width, height = rect_to_pixels(item.rect, self._metrics)
                painter.drawRect(
                    int(6 + x * sx), int(6 + y * sy),
                    max(1, int(width * sx)), max(1, int(height * sy)),
                )
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor("#1769e0"))
            painter.drawRect(
                int(6 + self._viewport.x() * sx),
                int(6 + self._viewport.y() * sy),
                max(2, int(self._viewport.width() * sx)),
                max(2, int(self._viewport.height() * sy)),
            )
        finally:
            painter.end()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._metrics is None or event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)
        sx, sy = self._scale()
        target = QRect(
            max(0, int((event.pos().x() - 6) / sx - self._viewport.width() / 2)),
            max(0, int((event.pos().y() - 6) / sy - self._viewport.height() / 2)),
            self._viewport.width(),
            self._viewport.height(),
        )
        self.viewport_requested.emit(target)
        event.accept()


class BoardScrollArea(QScrollArea):
    """Scroll host that reports viewport geometry to the logical Board."""

    viewport_resized = pyqtSignal(QSize)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardScrollArea")
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.viewport_resized.emit(self.viewport().size())

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        vertical = self.verticalScrollBar()
        horizontal = self.horizontalScrollBar()
        if event.key() == Qt.Key_Home:
            vertical.setValue(vertical.minimum())
            horizontal.setValue(horizontal.minimum())
            event.accept()
            return
        if event.key() == Qt.Key_End:
            vertical.setValue(vertical.maximum())
            horizontal.setValue(horizontal.maximum())
            event.accept()
            return
        if event.key() == Qt.Key_PageDown:
            vertical.setValue(min(vertical.maximum(), vertical.value() + vertical.pageStep()))
            event.accept()
            return
        if event.key() == Qt.Key_PageUp:
            vertical.setValue(max(vertical.minimum(), vertical.value() - vertical.pageStep()))
            event.accept()
            return
        super().keyPressEvent(event)


class BoardOverview(QFrame):
    """Read-only full-board projection used for P1 global scanning.

    This is intentionally a lightweight QImage composition of existing card
    previews.  It owns no canvas and emits a slot intent on click; the Page
    scrolls the real Board back into view afterwards.
    """

    slot_requested = pyqtSignal(str)
    ref_requested = pyqtSignal(str, str)
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardOverview")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._layout_id = "hero_left_4"
        self._ratio = 0.67
        self._models: dict[str, CardViewModel | None] = {}
        self._board: UltraViewBoardState | None = None
        self._records: dict[UltraViewRef, object] = {}
        self._statuses: dict[UltraViewRef, str] = {}
        self._slot_map: dict[str, tuple[int, int, int, int]] = {}
        self._free_metrics: GridMetrics | None = None
        self._free_rects: dict[str, tuple[int, int, int, int]] = {}
        self._free_refs: dict[str, UltraViewRef] = {}
        self._image = QImage()
        self._content = QRect()
        self._compose_dirty = True
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        bar = QHBoxLayout()
        title = QLabel("整板概览", self)
        title.setObjectName("ultraViewBoardOverviewTitle")
        bar.addWidget(title)
        bar.addStretch(1)
        close = QToolButton(self)
        close.setObjectName("ultraViewBoardOverviewClose")
        close.setText("返回阅读")
        close.clicked.connect(self.close_requested)
        bar.addWidget(close)
        root.addLayout(bar)
        self._preview = QLabel(self)
        self._preview.setObjectName("ultraViewBoardOverviewImage")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        root.addWidget(self._preview, 1)

    def set_board(self, layout_id: str, ratio: float, models: Mapping[str, CardViewModel | None]) -> None:
        self._layout_id = layout_id
        self._ratio = ratio
        self._models = dict(models)
        self._board = None
        self._records = {}
        self._statuses = {}
        self._free_metrics = None
        self._free_rects = {}
        self._free_refs = {}
        self._slot_map = {}
        self._request_compose()

    def set_free_grid(
        self,
        placements: Sequence[FreeGridPlacement],
        models: Mapping[UltraViewRef, CardViewModel],
    ) -> None:
        self._free_metrics = grid_metrics(BASE_BOARD_SIZE, placements)
        self._free_rects = {
            f"grid:{item.ref.section}:{item.ref.view_id}": rect_to_pixels(
                item.rect, self._free_metrics
            )
            for item in placements
        }
        self._free_refs = {
            f"grid:{item.ref.section}:{item.ref.view_id}": item.ref
            for item in placements
        }
        self._models = {
            f"grid:{item.ref.section}:{item.ref.view_id}": models[item.ref]
            for item in placements
            if item.ref in models
        }
        self._board = None
        self._records = {}
        self._statuses = {}
        self._slot_map = dict(self._free_rects)
        self._request_compose()

    def set_projection(
        self,
        board: UltraViewBoardState,
        records: Mapping[UltraViewRef, object],
        statuses: Mapping[UltraViewRef, str],
    ) -> None:
        """Bind the overview to the same compositor the PNG export uses."""
        self._board = board
        self._records = dict(records)
        self._statuses = dict(statuses)
        self._layout_id = board.layout_id
        self._ratio = board.primary_ratio
        if board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self._free_metrics = export_grid_metrics(board.free_grid)
            self._free_refs = {
                f"grid:{item.ref.section}:{item.ref.view_id}": item.ref
                for item in board.free_grid
            }
        else:
            self._free_metrics = None
            self._free_refs = {}
        self._slot_map = composed_slot_rects(board, title=False)
        self._free_rects = dict(self._slot_map) if self._free_metrics is not None else {}
        self._request_compose()

    def _request_compose(self) -> None:
        self._compose_dirty = True
        if self.isVisible():
            self._compose()
            self._compose_dirty = False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._compose_dirty:
            self._compose()
            self._compose_dirty = False

    def slot_id_at(self, pos: QPoint) -> str | None:
        if self._image.isNull() or self._preview.pixmap() is None:
            return None
        pixmap = self._preview.pixmap()
        draw_w, draw_h = pixmap.width(), pixmap.height()
        origin_x = self._preview.x() + (self._preview.width() - draw_w) // 2
        origin_y = self._preview.y() + (self._preview.height() - draw_h) // 2
        if not QRect(origin_x, origin_y, draw_w, draw_h).contains(pos):
            return None
        scale_x = self._image.width() / float(max(1, draw_w))
        scale_y = self._image.height() / float(max(1, draw_h))
        px = int((pos.x() - origin_x) * scale_x)
        py = int((pos.y() - origin_y) * scale_y)
        for slot_id, rect in self._slot_rects().items():
            if QRect(*rect).contains(px, py):
                return slot_id
        return None

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            slot_id = self.slot_id_at(event.pos())
            if slot_id is not None:
                if slot_id.startswith("grid:"):
                    ref = self._free_refs.get(slot_id)
                    if ref is not None:
                        self.ref_requested.emit(ref.section, ref.view_id)
                else:
                    self.slot_requested.emit(slot_id)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            self.close_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_image()

    def _slot_rects(self) -> dict[str, tuple[int, int, int, int]]:
        if self._slot_map:
            return dict(self._slot_map)
        if self._free_metrics is not None:
            return dict(self._free_rects)
        return slot_rects(self._layout_id, content_rect(BASE_BOARD_SIZE), self._ratio)

    def _compose(self) -> None:
        if self._board is not None:
            self._image = compose_board(
                self._board,
                self._records,
                self._statuses,
                scale=1,
                title=False,
            )
            self._slot_map = composed_slot_rects(self._board, title=False)
            self._fit_image()
            return
        if self._free_metrics is not None:
            image_size = (self._free_metrics.board_width, self._free_metrics.board_height)
        else:
            image_size = BASE_BOARD_SIZE
        image = QImage(*image_size, QImage.Format_ARGB32)
        image.fill(QColor("#f5f7fb"))
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            for slot_id, (x, y, width, height) in self._slot_rects().items():
                model = self._models.get(slot_id)
                painter.setPen(QColor("#d7dee8"))
                painter.setBrush(QColor("#ffffff"))
                painter.drawRoundedRect(x, y, width, height, 5, 5)
                if model is None:
                    painter.setPen(QColor("#64748b"))
                    painter.drawText(QRect(x, y, width, height), Qt.AlignCenter, "空槽")
                    continue
                header_h = CARD_HEADER_HEIGHT if model.show_title else 0
                footer_h = CARD_FOOTER_HEIGHT if model.show_source else 0
                painter.setPen(QColor("#1b2430"))
                if header_h:
                    painter.drawText(QRect(x + 8, y, width - 16, header_h), Qt.AlignVCenter | Qt.AlignLeft, model.title or model.view_id)
                raw = model.image if isinstance(model.image, QImage) else None
                image_rect = QRect(x + 4, y + header_h, max(0, width - 8), max(0, height - header_h - footer_h))
                if raw is not None and not raw.isNull():
                    painter.drawImage(image_rect, raw)
                else:
                    painter.setPen(QColor("#64748b"))
                    painter.drawText(image_rect, Qt.AlignCenter, STATUS_LABELS_ZH.get(model.status, "尚无可用结果"))
                if footer_h:
                    painter.fillRect(x + 1, y + height - footer_h, width - 2, footer_h, QColor("#eef2f7"))
                    painter.setPen(QColor("#5b6775"))
                    painter.drawText(QRect(x + 8, y + height - footer_h, width - 16, footer_h), Qt.AlignVCenter | Qt.AlignLeft, model.source_summary)
        finally:
            painter.end()
        self._image = image
        self._fit_image()

    def _fit_image(self) -> None:
        if self._image.isNull():
            self._preview.setPixmap(QPixmap())
            return
        size = self._preview.size()
        if size.width() < 2 or size.height() < 2:
            return
        self._preview.setPixmap(QPixmap.fromImage(self._image).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class TrayItem(QFrame):
    place_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(
        self,
        section: str,
        view_id: str,
        title: str,
        tab_color: str,
        status: str,
        parent: QWidget | None = None,
        *,
        replacement_armed: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewTrayItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._section = section
        self._view_id = view_id
        self._press_pos: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 4)
        layout.setSpacing(6)
        self._dot = _ColorDot(self)
        self._dot.set_color(tab_color)
        layout.addWidget(self._dot, 0)
        self._title = _ElideLabel(title, self)
        self._title.set_full_text(title)
        layout.addWidget(self._title, 1)
        self._status = QLabel(STATUS_LABELS_ZH.get(status, status), self)
        layout.addWidget(self._status, 0)
        place = QToolButton(self)
        place.setObjectName("ultraViewTrayPlace")
        place.setText("放置")
        place.clicked.connect(self._emit_place)
        self._rebind = QToolButton(self)
        self._rebind.setObjectName("ultraViewTrayRebind")
        self._rebind.setText("重新绑定")
        self._rebind.clicked.connect(self._emit_rebind)
        self._rebind.setVisible(status == STATUS_ORPHANED)
        remove = QToolButton(self)
        remove.setText("移除")
        remove.clicked.connect(self._emit_remove)
        layout.addWidget(place, 0)
        layout.addWidget(self._rebind, 0)
        layout.addWidget(remove, 0)
        self.setAccessibleName(f"未放置 {title}")
        self.setProperty("status", status)
        _set_flag(self, "orphaned", status == STATUS_ORPHANED)
        _set_flag(self, "replacementArmed", replacement_armed)

    def ref(self) -> tuple[str, str]:
        return self._section, self._view_id

    def _emit_place(self) -> None:
        self.place_requested.emit(self._section, self._view_id)

    def _emit_rebind(self) -> None:
        self.rebind_arm_requested.emit(self._section, self._view_id)

    def _emit_remove(self) -> None:
        self.remove_requested.emit(self._section, self._view_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = QPoint(event.pos())
            self.locate_requested.emit(self._section, self._view_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._press_pos = None
        mime = make_ref_mime(self._section, self._view_id)
        self.drag_started.emit("tray")
        _run_ultraview_drag(
            self, mime, Qt.MoveAction, self.drag_finished.emit
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press_pos = None
        super().mouseReleaseEvent(event)


class UnplacedTray(QFrame):
    place_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_dropped = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewUnplacedTray")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self._expanded = False
        self._items: list[TrayItem] = []
        self._content_signature: tuple | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._title = QPushButton("未放置", self)
        self._title.setObjectName("ultraViewTrayTitle")
        self._title.setCheckable(True)
        self._title.setChecked(False)
        self._title.clicked.connect(self._on_title)
        root.addWidget(self._title, 0)
        self._body = QScrollArea(self)
        self._body.setObjectName("ultraViewTrayBody")
        self._body.setWidgetResizable(True)
        self._body.setFrameShape(QFrame.NoFrame)
        self._body.setMaximumHeight(TRAY_BODY_MAX_HEIGHT)
        self._inner = QWidget(self._body)
        self._inner_layout = QHBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(8, 6, 8, 8)
        self._inner_layout.setSpacing(8)
        self._inner_layout.addStretch(1)
        self._body.setWidget(self._inner)
        self._body.setVisible(False)
        root.addWidget(self._body, 0)

    def title_bar(self) -> QPushButton:
        return self._title

    def body(self) -> QScrollArea:
        return self._body

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        blocked = self._title.blockSignals(True)
        self._title.setChecked(self._expanded)
        self._title.blockSignals(blocked)
        self._body.setVisible(self._expanded)

    def item_widgets(self) -> list[TrayItem]:
        return list(self._items)

    def set_refs(
        self,
        refs: Sequence[UltraViewRef],
        *,
        titles: Mapping[tuple[str, str], str] | None = None,
        colors: Mapping[tuple[str, str], str] | None = None,
        statuses: Mapping[tuple[str, str], str] | None = None,
        armed: UltraViewRef | None = None,
    ) -> None:
        titles = titles or {}
        colors = colors or {}
        statuses = statuses or {}
        signature = tuple(
            (
                (ref.section, ref.view_id),
                str(titles.get((ref.section, ref.view_id), ref.view_id)),
                str(colors.get((ref.section, ref.view_id), "")),
                str(statuses.get((ref.section, ref.view_id), "")),
                armed == ref,
            )
            for ref in refs
        )
        if signature == self._content_signature:
            return
        self._content_signature = signature
        while self._inner_layout.count() > 1:
            item = self._inner_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._items = []
        for ref in refs:
            key = (ref.section, ref.view_id)
            widget = TrayItem(
                ref.section,
                ref.view_id,
                titles.get(key, ref.view_id),
                colors.get(key, ""),
                statuses.get(key, ""),
                self._inner,
                replacement_armed=armed == ref,
            )
            widget.place_requested.connect(self.place_requested)
            widget.remove_requested.connect(self.remove_requested)
            widget.locate_requested.connect(self.locate_requested)
            widget.rebind_arm_requested.connect(self.rebind_arm_requested)
            widget.drag_started.connect(self.drag_started)
            widget.drag_finished.connect(self.drag_finished)
            self._inner_layout.insertWidget(self._inner_layout.count() - 1, widget)
            self._items.append(widget)
        count = len(refs)
        self._title.setText("未放置" if count == 0 else f"未放置 · {count}")

    def _on_title(self, checked: bool) -> None:
        self.set_expanded(checked)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        _accept_ultraview_drag(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        extracted = extract_ref_strings(event.mimeData())
        event.acceptProposedAction()
        if extracted is None:
            return
        section, view_id = extracted
        self.move_to_unplaced_dropped.emit(section, view_id)


class FocusLayer(QFrame):
    closed = pyqtSignal()
    open_source_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewFocusLayer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()
        self._section = ""
        self._view_id = ""
        self._image: QImage | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        panel = QFrame(self)
        panel.setObjectName("ultraViewFocusPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 8, 8)
        self._title = QLabel("", panel)
        self._title.setObjectName("ultraViewFocusTitle")
        close_btn = QToolButton(panel)
        close_btn.setText("×")
        close_btn.setObjectName("ultraViewFocusClose")
        close_btn.clicked.connect(self.close_layer)
        head.addWidget(self._title, 1)
        head.addWidget(close_btn, 0)
        panel_layout.addLayout(head)
        self._image_host = QLabel(panel)
        self._image_host.setObjectName("ultraViewFocusImage")
        self._image_host.setAlignment(Qt.AlignCenter)
        self._image_host.setMinimumSize(QSize(120, 80))
        self._image_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(self._image_host, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 8, 12, 10)
        note = QLabel("临时查看 · 不改变源 View · 不超过原始像素 100%", panel)
        self._open = QPushButton("打开原 View", panel)
        self._open.setObjectName("ultraViewOpenSourceButton")
        self._open.clicked.connect(self._emit_open)
        foot.addWidget(note, 1)
        foot.addWidget(self._open, 0)
        panel_layout.addLayout(foot)
        root.addWidget(panel, 1)

    def open_source_button(self) -> QPushButton:
        return self._open

    def displayed_pixmap_size(self) -> QSize:
        pixmap = self._image_host.pixmap()
        if pixmap is None or pixmap.isNull():
            return QSize(0, 0)
        return pixmap.size()

    def raw_image_size(self) -> QSize:
        if self._image is None:
            return QSize(0, 0)
        return QSize(self._image.width(), self._image.height())

    def show_ref(
        self,
        section: str,
        view_id: str,
        title: str,
        image: QImage | None,
    ) -> None:
        self._section = section
        self._view_id = view_id
        self._image = image
        self._title.setText(title or view_id)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self._refit()

    def close_layer(self) -> None:
        self.hide()
        self._image = None
        self._image_host.setPixmap(QPixmap())
        self.closed.emit()

    def _emit_open(self) -> None:
        if self._section and self._view_id:
            self.open_source_requested.emit(self._section, self._view_id)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close_layer()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        child = self.childAt(event.pos())
        if child is None or child is self:
            self.close_layer()
            event.accept()
            return
        super().mousePressEvent(event)

    def _refit(self) -> None:
        if self._image is None:
            self._image_host.setPixmap(QPixmap())
            return
        raw_w = self._image.width()
        raw_h = self._image.height()
        avail = self._image_host.size()
        cap_w = max(1, min(avail.width(), raw_w))
        cap_h = max(1, min(avail.height(), raw_h))
        pixmap = QPixmap.fromImage(self._image)
        scaled = pixmap.scaled(cap_w, cap_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image_host.setPixmap(scaled)
