"""UltraView page widgets: library, board grid, cards, tray, focus layer.

Widgets emit typed intents. They do not import MainWindow, mutate BoardState,
or call analysis entry points. Preview records are duck-typed.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from functools import partial
from typing import Any, Mapping, Sequence

from PyQt5 import sip
from PyQt5.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, QRect, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QContextMenuEvent,
    QDrag,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QNativeGestureEvent,
    QPainter,
    QPixmap,
    QWheelEvent,
)
from PyQt5.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
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
    QWIDGETSIZE_MAX,
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

from .chrome import ULTRAVIEW_MUTED
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
    LAYOUT_MOVE,
    LAYOUT_RESIZE,
    LayoutPlan,
    LayoutRejectReason,
    avoidance_preferred_delta,
    candidate_resize,
    export_grid_metrics,
    hit_handle,
    legal_grid_rect,
    plan_layout,
    rect_to_pixels,
    screen_grid_metrics,
)
from .gesture import FreeGridGesture
from .ghost_overlay import GhostOverlay
from .compositor import compose_board, composed_slot_rects
from .viewport import (
    QUALITY_FAST,
    QUALITY_SMOOTH,
    LOD_FULL,
    LOD_NO_FOOTER,
    LOD_TITLE_ONLY,
    lod_visibility,
    ZOOM_DEFAULT,
    scale_grid_metrics,
    zoomed_viewport_size,
)
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
FEEDBACK_OUT_OF_GRID = "不能移出网格"
FEEDBACK_NO_LEGAL_LAYOUT = "当前位置放不下，已保持原布局"
# A blown search budget is *not* "it does not fit": a legal layout may well
# exist, the planner just stopped looking (review 2026-08-15 P1-4).
FEEDBACK_SEARCH_BUDGET = "布局搜索超出预算，已保持原布局 · 可先整理布局再试"
FEEDBACK_REARRANGED = "已重排 {count} 张 · Ctrl+Z 撤销"
FEEDBACK_DISPLACED_OFFSCREEN = "被让位的卡片已移出可视区 · 向下滚动查看"

_PLANNER_LOG = logging.getLogger(__name__)
_PLANNER_LOG_MONO = 0.0
_PLANNER_LOG_INTERVAL_S = 0.5


def _page_of(widget: QWidget):
    current = widget
    while current is not None:
        if current.objectName() == "ultraViewPage":
            return current
        current = current.parentWidget()
    return None


def _union_pixel_rect(rects) -> tuple[float, float, float, float] | None:
    boxes = [tuple(rect) for rect in rects if rect is not None]
    if not boxes:
        return None
    x0 = min(float(rect[0]) for rect in boxes)
    y0 = min(float(rect[1]) for rect in boxes)
    x1 = max(float(rect[0]) + float(rect[2]) for rect in boxes)
    y1 = max(float(rect[1]) + float(rect[3]) for rect in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def _log_plan_result(plan: LayoutPlan) -> None:
    """Release-path diagnostics only; never called from mouse-move."""
    global _PLANNER_LOG_MONO
    import time

    # Giving up on the search is an infrastructure failure, not a user error:
    # it must leave a warning trace and must not be swallowed by the hot-path
    # throttle (review 2026-08-15 P1-4).
    gave_up = plan.reason is LayoutRejectReason.SEARCH_CAP
    now = time.monotonic()
    if not gave_up and now - _PLANNER_LOG_MONO < _PLANNER_LOG_INTERVAL_S:
        return
    _PLANNER_LOG_MONO = now
    log = _PLANNER_LOG.warning if gave_up else _PLANNER_LOG.debug
    log(
        "ultraview plan accepted=%s reason=%s op=%s visits=%s affected=%s",
        plan.accepted,
        None if plan.reason is None else plan.reason.value,
        plan.operation,
        plan.search_visits,
        plan.affected_count(),
    )


def _reject_feedback(reason: LayoutRejectReason | None) -> str:
    """One mapping from reject reason to user copy, for every commit path."""
    if reason is LayoutRejectReason.OUT_OF_BOUNDS:
        return FEEDBACK_OUT_OF_GRID
    if reason is LayoutRejectReason.SEARCH_CAP:
        return FEEDBACK_SEARCH_BUDGET
    return FEEDBACK_NO_LEGAL_LAYOUT


def _clear_page_card_selection(widget: QWidget) -> None:
    page = _page_of(widget)
    if page is not None:
        page.clear_card_selection()


def _forward_native_zoom(widget: QWidget, event) -> bool:
    if not isinstance(event, QNativeGestureEvent):
        return False
    if event.gestureType() != Qt.ZoomNativeGesture:
        return False
    page = _page_of(widget)
    if page is None:
        return False
    return bool(page.handle_pinch(event, widget))


def _forward_zoom_wheel(widget: QWidget, event: QWheelEvent) -> bool:
    if not (event.modifiers() & Qt.ControlModifier):
        return False
    page = _page_of(widget)
    if page is None:
        return False
    return bool(page.handle_zoom_wheel(event, widget))


def _handle_space_key(widget: QWidget, event: QKeyEvent) -> bool:
    if event.key() != Qt.Key_Space or event.isAutoRepeat():
        return False
    if isinstance(QApplication.focusWidget(), QLineEdit):
        return False
    page = _page_of(widget)
    if page is None:
        return False
    page.note_space(event.type() == QEvent.KeyPress)
    return True


def _handle_pan_press(widget: QWidget, event: QMouseEvent) -> bool:
    page = _page_of(widget)
    if page is None:
        return False
    return bool(page.begin_board_pan(event))


def _handle_pan_release(widget: QWidget, event: QMouseEvent) -> bool:
    page = _page_of(widget)
    if page is None:
        return False
    return bool(page.end_board_pan_for_event(event))


def _drop_on_unplaced_tray(widget: QWidget, global_pos: QPoint) -> bool:
    page = _page_of(widget)
    if page is None:
        return False
    # The narrow-rail workspace keeps the complete tray on demand.  During
    # direct free-grid manipulation its rail badge is the stable visible drop
    # target, so moving a card to unplaced does not require opening a large
    # panel first.  Keep the expanded Tray body as the compatible second target.
    tool_rail = getattr(page, "tool_rail", None)
    if callable(tool_rail):
        rail = tool_rail()
        if rail is not None and rail.isVisible() and rail.rect().contains(rail.mapFromGlobal(global_pos)):
            return True
    tray = page.unplaced_tray()
    if tray is None or not tray.isVisible():
        return False
    return tray.rect().contains(tray.mapFromGlobal(global_pos))


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
# Transient dim worn by the cards a drag is currently previewing; the model-level
# ``DIMMED_OPACITY`` above is the persistent one ``restore_dim()`` falls back to.
DRAG_DIM_OPACITY = 0.4
# The library stays a narrow on-canvas overlay.  ``UltraViewPage`` imports the
# default instead of carrying a second geometry literal, so this is the one
# source of truth for the rail overlay's normal width.
LIBRARY_DEFAULT_WIDTH = 360
LIBRARY_MAX_WIDTH = 400
LIBRARY_MODE_GROUPS = "groups"
_LIBRARY_PIN_REST = QColor("#6B7D8E")
_LIBRARY_PIN_ACTIVE = QColor("#3E709C")
TYPE_CHIP_ICON_ONLY_WIDTH = 168
_SECTION_TYPE_ICONS = {
    "time": Icons.mode_time,
    "fft": Icons.mode_fft,
    "fft_time": Icons.mode_fft_time,
    "frf": Icons.mode_frf,
    "order": Icons.mode_order,
}
# View-library geometry. Every value below is an **outer-frame** height, QSS
# stroke included. Qt's `min-height` is content-box, so the matching rule in
# `style.qss` writes `value - border - padding`: 44 for the 46px row (1px
# stroke each side), but 32 for the 32px section head, whose rule turns every
# border off. Mixing the two conventions is what let the hand-written height
# formula drift 51px away from the layout and clip the "time" group.
LIBRARY_OVERLAY_HEIGHT = 560
LIBRARY_OVERLAY_MIN_HEIGHT = 360
LIBRARY_HEAD_HEIGHT = 52
LIBRARY_SEARCH_HEIGHT = 34
LIBRARY_SECTION_GAP = 8
LIBRARY_SECTION_HEAD_HEIGHT = 32
# Two lines (name + checked-channel summary). A deliberate departure from the
# HTML prototype's single 38px row: the second line is the only thing that
# tells default "View 1..N" names apart, so evenness comes from pinning the
# height, not from dropping the information.
LIBRARY_ROW_HEIGHT = 46
# A selected row owns a small shadow.  Rows therefore need an actual air gap
# instead of a sibling border that can show through the selected card's lower
# corner (the recurrent View 1/View 2 line regression).
LIBRARY_SELECTED_ROW_GUTTER = 8
LIBRARY_SECTION_ROW_GAP = LIBRARY_SELECTED_ROW_GUTTER
LIBRARY_ROW_ACTION_SIZE = 23
LIBRARY_ROW_DOT_INSET = 14
TRAY_BODY_MAX_HEIGHT = 220
TRAY_ITEM_MIN_HEIGHT = 40
UNPLACED_OVERLAY_VISIBLE_ROWS = 3
UNPLACED_OVERLAY_WIDTH = 400
UNPLACED_OVERLAY_MIN_HEIGHT = 160


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


def _hairline(parent: QWidget, object_name: str) -> QFrame:
    """1px separator whose color comes from QSS, not from the native frame.

    ``QFrame.HLine`` alone paints a two-tone sunken groove that reads as a
    bevel next to this panel's flat material, so the shape only carries the
    semantics and the styled background carries the ink.
    """
    rule = QFrame(parent)
    rule.setObjectName(object_name)
    rule.setFrameShape(QFrame.HLine)
    rule.setFrameShadow(QFrame.Plain)
    rule.setAttribute(Qt.WA_StyledBackground, True)
    rule.setFixedHeight(1)
    rule.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return rule


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
        self._context = QLabel("拖卡片移动 · 拖边角改尺寸 · 框选 · Ctrl+滚轮缩放", self)
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
    zoom_out_requested = pyqtSignal()
    zoom_in_requested = pyqtSignal()
    zoom_fit_requested = pyqtSignal()
    zoom_reset_requested = pyqtSignal()

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

        self._zoom_out = QToolButton(self)
        self._zoom_out.setObjectName("ultraViewZoomOutButton")
        self._zoom_out.setText("−")
        self._zoom_out.setToolTip("缩小画布")
        self._zoom_out.clicked.connect(self.zoom_out_requested)
        layout.addWidget(self._zoom_out, 0)
        self._zoom_label = QLabel("100%", self)
        self._zoom_label.setObjectName("ultraViewZoomLabel")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setMinimumWidth(42)
        layout.addWidget(self._zoom_label, 0)
        self._zoom_in = QToolButton(self)
        self._zoom_in.setObjectName("ultraViewZoomInButton")
        self._zoom_in.setText("＋")
        self._zoom_in.setToolTip("放大画布")
        self._zoom_in.clicked.connect(self.zoom_in_requested)
        layout.addWidget(self._zoom_in, 0)
        self._zoom_fit = QToolButton(self)
        self._zoom_fit.setObjectName("ultraViewZoomFitButton")
        self._zoom_fit.setText("适应")
        self._zoom_fit.setToolTip("画布适应视口")
        self._zoom_fit.clicked.connect(self.zoom_fit_requested)
        layout.addWidget(self._zoom_fit, 0)
        self._zoom_reset = QToolButton(self)
        self._zoom_reset.setObjectName("ultraViewZoomResetButton")
        self._zoom_reset.setText("100%")
        self._zoom_reset.setToolTip("恢复 100% 缩放")
        self._zoom_reset.clicked.connect(self.zoom_reset_requested)
        layout.addWidget(self._zoom_reset, 0)

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

    def zoom_label(self) -> QLabel:
        return self._zoom_label

    def set_zoom_percent(self, percent: int) -> None:
        self._zoom_label.setText(f"{int(percent)}%")

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
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for filter_id in COMPARE_FILTERS:
            button = QPushButton(COMPARE_FILTER_LABELS_ZH[filter_id], self)
            button.setObjectName("ultraViewCompareButton")
            button.setCheckable(True)
            button.setProperty("filterId", filter_id)
            button.setFocusPolicy(Qt.TabFocus)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._group.addButton(button)
            self._buttons[filter_id] = button
            root.addWidget(button, 0)
        self._buttons[COMPARE_FILTER_ALL].setChecked(True)
        self._group.buttonClicked.connect(self._on_button)
        self._warning = QLabel("", self)
        self._warning.setObjectName("ultraViewAxisWarning")
        self._warning.setWordWrap(True)
        self._warning.hide()
        root.addWidget(self._warning, 0)
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
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(LIBRARY_ROW_HEIGHT)
        self._row = row
        self._press_pos: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(LIBRARY_ROW_DOT_INSET, 5, 8, 5)
        layout.setSpacing(8)
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
        # Channel names read as a list, not as prose: fixed pitch keeps the
        # second line from wobbling row to row. Same recipe as the navigation
        # island's zoom readout, which already ships on Windows.
        meta_font = QFont(self._meta.font())
        meta_font.setStyleHint(QFont.Monospace)
        meta_font.setFixedPitch(True)
        self._meta.setFont(meta_font)
        copy.addWidget(self._name)
        copy.addWidget(self._meta)
        layout.addLayout(copy, 1)
        self._add = QToolButton(self)
        self._add.setObjectName("ultraViewLibraryAdd")
        self._add.setAutoRaise(False)
        self._add.setFixedSize(LIBRARY_ROW_ACTION_SIZE, LIBRARY_ROW_ACTION_SIZE)
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
        selected = bool(on)
        if (self.property("selected") == "true") != selected:
            _set_flag(self, "selected", selected)
        effect = self.graphicsEffect()
        if selected:
            if effect is None:
                shadow = QGraphicsDropShadowEffect(self)
                shadow.setBlurRadius(10)
                shadow.setOffset(0, 2)
                shadow.setColor(QColor(62, 112, 145, 52))
                self.setGraphicsEffect(shadow)
            return
        if effect is not None:
            # QWidget owns its graphics effect.  Clearing it before a rebuild
            # keeps the outgoing row from retaining a shadow wrapper while its
            # section host is queued for deletion.
            self.setGraphicsEffect(None)

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


class _LibrarySectionHeader(QFrame):
    """Paper-card header for one SOURCE_SECTIONS group; no domain color bar."""

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
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(LIBRARY_SECTION_HEAD_HEIGHT)
        self._section = section
        self._count_value = max(0, int(count))
        self._expanded = bool(expanded)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(4)
        self._title = QLabel(SECTION_LABELS_ZH.get(section, section), self)
        self._title.setObjectName("ultraViewLibrarySectionTitle")
        layout.addWidget(self._title, 1)
        self.setToolTip(f"{self._count_value} 个 View")
        self._toggle = QToolButton(self)
        self._toggle.setObjectName("ultraViewLibrarySectionToggle")
        self._toggle.setCheckable(True)
        self._toggle.setAutoRaise(True)
        self._toggle.setFocusPolicy(Qt.TabFocus)
        self._toggle.setFixedSize(22, 22)
        self._toggle.setIconSize(QSize(14, 14))
        # The native triangle is heavier than everything else on this panel;
        # the chevron pair matches the BoardIsland glyph. NoArrow keeps Qt from
        # painting its triangle underneath the icon.
        self._toggle.setArrowType(Qt.NoArrow)
        blocked = self._toggle.blockSignals(True)
        self._toggle.setChecked(expanded)
        self._toggle.blockSignals(blocked)
        self._sync_arrow(expanded)
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle, 0, Qt.AlignVCenter)

    def section(self) -> str:
        return self._section

    def click(self) -> None:
        self._toggle.click()

    def text(self) -> str:
        return f"{SECTION_LABELS_ZH.get(self._section, self._section)}  {self._count_value}"

    def arrowType(self):  # noqa: N802
        """Collapse direction, still projected as a ``Qt.ArrowType``.

        The visual is a chevron icon now, so ``QToolButton.arrowType()`` is
        pinned to ``NoArrow``. This header keeps owning the direction and
        answers with the same vocabulary callers (and the header contract in
        ``tests/ui/test_ultraview_page.py``) already read.
        """
        return Qt.DownArrow if self._expanded else Qt.RightArrow

    def _on_toggled(self, checked: bool) -> None:
        self._sync_arrow(checked)
        self.toggled_section.emit(self._section, checked)

    def _sync_arrow(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._toggle.setIcon(
            Icons.chevron_down(ULTRAVIEW_MUTED)
            if self._expanded
            else Icons.chevron_right(ULTRAVIEW_MUTED)
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.childAt(event.pos()) is not self._toggle:
            self._toggle.click()
        super().mouseReleaseEvent(event)


class ViewLibraryPanel(QFrame):
    add_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    locate_requested = pyqtSignal(str, str)
    drag_started = pyqtSignal(str)
    drag_finished = pyqtSignal()
    pin_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLibrary")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumWidth(280)
        self.setMaximumWidth(LIBRARY_MAX_WIDTH)
        self._rows: list[LibraryRow] = []
        self._selected: tuple[str, str] | None = None
        self._row_widgets: list[LibraryRowWidget] = []
        self._section_frames: dict[str, QFrame] = {}
        self._section_headers: dict[str, _LibrarySectionHeader] = {}
        self._section_rules: dict[str, QFrame] = {}
        self._expanded: dict[str, bool] = {section: True for section in SOURCE_SECTIONS}

        root = QVBoxLayout(self)
        # Root carries no inset: the head band needs to run edge to edge so its
        # rule reads as a real separator. Qt does not clip children to
        # `border-radius`, so each band owns its own padding instead — and the
        # only child that reaches the corner arcs is the head band, which paints
        # nothing.
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head_host = QWidget(self)
        head_host.setObjectName("ultraViewLibraryHead")
        head_host.setFixedHeight(LIBRARY_HEAD_HEIGHT)
        head = QHBoxLayout(head_host)
        head.setContentsMargins(14, 12, 10, 10)
        head.setSpacing(6)
        title = QLabel("View 库", self)
        title.setObjectName("ultraViewLibraryTitle")
        self._count = QLabel("0 个", self)
        self._count.setObjectName("ultraViewLibraryCount")
        # Naming note: this `_pin` is the library overlay's own "keep open"
        # toggle (pinned = don't auto-close on canvas click), unrelated to
        # `PreviewStore.set_pinned_refs` (the residency API for the set of
        # UltraViewRef a Board keeps resident). Same word, different
        # domain — no functional overlap.
        self._pin = QToolButton(self)
        self._pin.setObjectName("ultraViewLibraryPin")
        self._pin.setCheckable(True)
        self._pin.setAutoRaise(True)
        self._pin.setFixedSize(24, 24)
        self._pin.setIconSize(QSize(14, 14))
        self._pin.setFocusPolicy(Qt.TabFocus)
        self._pin.setProperty("role", "icon")
        self._pin.setProperty("chrome", "ultraview")
        self._pin.setProperty("active", "false")
        self._pin.toggled.connect(self._on_pin_toggled)
        head.addWidget(title, 1)
        head.addWidget(self._count, 0, Qt.AlignVCenter)
        head.addWidget(self._pin, 0, Qt.AlignVCenter)
        self._sync_pin(False)
        root.addWidget(head_host)

        # Full width, and that is already 1px short of each edge: Qt's
        # stylesheet insets a styled widget's contents past its own border, so
        # the panel's stroke stays uncovered without an extra margin (measured:
        # contentsRect() is inset by the panel's 1px border on every edge).
        self._head_rule = _hairline(self, "ultraViewLibraryHeadRule")
        root.addWidget(self._head_rule)

        controls = QVBoxLayout()
        controls.setContentsMargins(12, 10, 12, 10)
        controls.setSpacing(8)
        self._search = SearchField("搜索 View、信号或分析类型…", self)
        self._search.setObjectName("ultraViewLibrarySearch")
        self._search.setFixedHeight(LIBRARY_SEARCH_HEIGHT)
        self._search.textChanged.connect(self._rebuild)
        search_wrap = QHBoxLayout()
        search_wrap.setContentsMargins(0, 0, 0, 0)
        search_wrap.addWidget(self._search)
        controls.addLayout(search_wrap)

        root.addLayout(controls)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("ultraViewLibraryScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body = QWidget(self._scroll)
        self._body.setObjectName("ultraViewLibraryBody")
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._body_layout = QVBoxLayout(self._body)
        # The scroll area itself runs full width; the body carries the padding,
        # which puts the vertical scrollbar inside the 12px gutter instead of
        # on top of the group cards' right border.
        self._body_layout.setContentsMargins(12, 10, 12, 12)
        self._body_layout.setSpacing(LIBRARY_SECTION_GAP)
        self._scroll.setWidget(self._body)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(self._scroll, 1)
        # A rebuild creates fresh section frames.  Before Qt's next layout turn
        # their aggregate minimum can momentarily read as the outer margins
        # (22px), which would make QScrollArea squeeze every section instead of
        # turning its scrollbar on.  One owned, coalesced timer measures after
        # that layout turn; reopening the panel must not be the repair path.
        self._body_min_height_timer = QTimer(self)
        self._body_min_height_timer.setSingleShot(True)
        self._body_min_height_timer.timeout.connect(self._sync_body_min_height)
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

    def section_headers(self) -> dict[str, QWidget]:
        return dict(self._section_headers)

    def browse_mode(self) -> str:
        """Return the only remaining browse path for legacy read-only callers."""
        return LIBRARY_MODE_GROUPS

    def is_section_expanded(self, section: str) -> bool:
        return bool(self._expanded.get(section, True))

    def row_widgets(self) -> list[LibraryRowWidget]:
        return list(self._row_widgets)

    def set_rows(self, rows: Sequence[LibraryRow | Mapping[str, Any]]) -> None:
        self._rows = [coerce_library_row(row) for row in rows]
        self._count.setText(f"{len(self._rows)} 个")
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

    def pin_button(self) -> QToolButton:
        return self._pin

    def is_pinned(self) -> bool:
        return bool(self._pin.isChecked())

    def set_pinned(self, pinned: bool) -> None:
        wanted = bool(pinned)
        if self.is_pinned() == wanted and self._pin.property("active") == (
            "true" if wanted else "false"
        ):
            return
        blocked = self._pin.blockSignals(True)
        self._pin.setChecked(wanted)
        self._pin.blockSignals(blocked)
        self._sync_pin(wanted)
        self.pin_toggled.emit(wanted)

    def _on_pin_toggled(self, checked: bool) -> None:
        self._sync_pin(bool(checked))
        self.pin_toggled.emit(bool(checked))

    def _sync_pin(self, pinned: bool) -> None:
        self._pin.setIcon(Icons.ultraview_pin(_LIBRARY_PIN_ACTIVE if pinned else _LIBRARY_PIN_REST))
        value = "true" if pinned else "false"
        if self._pin.property("active") != value:
            self._pin.setProperty("active", value)
            style = self._pin.style()
            if style is not None:
                style.unpolish(self._pin)
                style.polish(self._pin)
            self._pin.update()
        label = "取消钉住 View 库" if pinned else "钉住 View 库，点击画布不关闭"
        self._pin.setToolTip(label)
        self._pin.setAccessibleName(label)

    def _rebuild(self) -> None:
        # Effects are owned by their row widgets.  Clear them before detaching
        # a group host so selection remains an _selected projection, never a
        # lingering QObject/effect owned by a soon-to-die row.
        for row_widget in self._row_widgets:
            row_widget.set_selected(False)
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._row_widgets = []
        self._section_frames = {}
        self._section_headers = {}
        self._section_rules = {}
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
        self._groups_host = QWidget(self._body)
        self._groups_host.setObjectName("ultraViewLibraryGroupsHost")
        groups_layout = QVBoxLayout(self._groups_host)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        groups_layout.setSpacing(LIBRARY_SECTION_GAP)
        for section in SOURCE_SECTIONS:
            frame = QFrame(self._groups_host)
            frame.setObjectName("ultraViewLibrarySection")
            frame.setProperty("section", section)
            frame.setAttribute(Qt.WA_StyledBackground, True)
            section_layout = QVBoxLayout(frame)
            section_layout.setContentsMargins(1, 1, 1, 4)
            section_layout.setSpacing(LIBRARY_SECTION_ROW_GAP)
            expanded = self._expanded.get(section, True)
            header = _LibrarySectionHeader(section, len(by_section[section]), expanded, frame)
            header.toggled_section.connect(self._on_section_toggled)
            section_layout.addWidget(header)
            self._section_headers[section] = header
            rule = _hairline(frame, "ultraViewLibrarySectionRule")
            rule.setVisible(expanded and bool(by_section[section]))
            section_layout.addWidget(rule)
            self._section_rules[section] = rule
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
            groups_layout.addWidget(frame)
        self._body_layout.addWidget(self._groups_host)
        # The scroll body may be taller than its groups.  Keep spare height in
        # an explicit tail stretch rather than letting Qt distribute it into
        # section cards or rows after a rebuild.
        self._body_layout.addStretch(1)
        self._queue_body_min_height_sync()

    def sizeHint(self) -> QSize:  # noqa: N802
        """Fixed size, independent of the list inside.

        Deriving the hint from content made every in-panel action (collapse a
        group or type a character) resize the overlay, and
        ``floating_layout`` centers the panel on its trigger, so the height
        swing became a top-edge jump too. Content scrolls; the frame does not
        move. Capping a content-driven hint would only narrow the jump range.
        """
        return QSize(LIBRARY_DEFAULT_WIDTH, LIBRARY_OVERLAY_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(280, LIBRARY_OVERLAY_MIN_HEIGHT)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_body_min_height()
        self._queue_body_min_height_sync()

    def _measured_body_height(self) -> int:
        """Ask the layout instead of re-deriving what it already knows.

        The hand-written formula this replaces counted content-box constants
        against border-box widgets and forgot the group cards' own margins; it
        answered 528 where the layout needed 579, and QVBoxLayout paid the
        51px difference by squeezing the tallest group until its bottom border
        cut through the last row.
        """
        return self._body_layout.totalMinimumSize().height()

    def _sync_body_min_height(self) -> None:
        self._body.setMinimumHeight(self._measured_body_height())

    def _queue_body_min_height_sync(self) -> None:
        """Measure rebuilt section geometry after Qt has laid out their children."""
        self._body_min_height_timer.start(0)

    def _on_section_toggled(self, section: str, expanded: bool) -> None:
        self._expanded[section] = bool(expanded)
        rows = 0
        for widget in self._row_widgets:
            if widget.row().section == section:
                widget.setVisible(bool(expanded))
                rows += 1
        rule = self._section_rules.get(section)
        if rule is not None:
            rule.setVisible(bool(expanded) and rows > 0)
        self._queue_body_min_height_sync()

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
    sync_requested = pyqtSignal(str, str)
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
        self._raw_image: QImage | None = None
        self._source_pixmap: QPixmap | None = None
        self._scale_buffer: QPixmap | None = None
        self._scale_key: tuple | None = None
        self._raw_cache_key: int | None = None
        self._preview_quality = QUALITY_SMOOTH
        self._lod_level = LOD_FULL
        self._lod_show_title = True
        self._lod_show_source = True
        self._lod_presentation = False

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
        self._type_chip = QToolButton(self._header)
        self._type_chip.setObjectName("ultraViewCardTypeChip")
        self._type_chip.setAutoRaise(False)
        # Purely informational (icon + section label, no clicked handler): it
        # must not steal the press from the card drag gesture underneath it,
        # so it neither takes tab focus nor accepts mouse hit-testing.
        self._type_chip.setFocusPolicy(Qt.NoFocus)
        self._type_chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._type_chip.setCursor(Qt.ArrowCursor)
        self._type_chip.setFixedHeight(22)
        self._type_chip.setIconSize(QSize(12, 12))
        self._type_chip.setProperty("role", "typeChip")
        header.addWidget(self._type_chip, 0, Qt.AlignVCenter)
        self._title = _ElideLabel("", self._header)
        header.addWidget(self._title, 1)
        self._status = QLabel("", self._header)
        self._status.setObjectName("ultraViewCardStatus")
        header.addWidget(self._status, 0)
        self._sync_btn = QToolButton(self._header)
        self._sync_btn.setObjectName("ultraViewCardSyncButton")
        self._sync_btn.setText("同步")
        self._sync_btn.setIcon(Icons.ultraview_sync())
        self._sync_btn.setIconSize(QSize(14, 14))
        self._sync_btn.setToolTip("抓取原 View 当前画面，不重新计算")
        self._sync_btn.setAccessibleName("同步到最新预览")
        self._sync_btn.setCursor(Qt.PointingHandCursor)
        self._sync_btn.setAutoRaise(False)
        self._sync_btn.setFixedHeight(24)
        self._sync_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._sync_btn.clicked.connect(self._emit_sync)
        self._sync_btn.hide()
        header.addWidget(self._sync_btn, 0, Qt.AlignVCenter)
        self._focus_btn = QToolButton(self._header)
        self._focus_btn.setObjectName("ultraViewCardFocusButton")
        self._focus_btn.setIcon(Icons.expand_focus())
        self._focus_btn.setIconSize(QSize(16, 16))
        self._focus_btn.setToolTip("临时放大")
        self._focus_btn.setAccessibleName("临时放大")
        self._focus_btn.setFocusPolicy(Qt.TabFocus)
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

        self.apply_model(model)

    def model(self) -> CardViewModel:
        return self._model

    def slot_id(self) -> str:
        return self._model.slot_id

    def header_height(self) -> int:
        return self._header.height()

    def footer_height(self) -> int:
        return self._footer.height()

    def preview_display_size(self) -> tuple[int, int]:
        size = self._preview_fit_size()
        try:
            dpr = float(self.devicePixelRatioF())
        except RuntimeError:
            dpr = 1.0
        return (
            max(1, int(round(max(1, size.width()) * dpr))),
            max(1, int(round(max(1, size.height()) * dpr))),
        )

    def chrome_height(self) -> int:
        extra = self._orphan_bar.height() if self._orphan_bar.isVisible() else 0
        return self._header.height() + self._footer.height() + extra

    def apply_model(self, model: CardViewModel) -> None:
        self._model = model
        self._lod_show_title = bool(model.show_title)
        self._lod_show_source = bool(model.show_source)
        title = model.title or model.view_id
        self._dot.set_color(model.tab_color)
        self._title.set_full_text(title)
        if model.status == STATUS_MISSING:
            self._status.setText(STATUS_LABELS_ZH[STATUS_MISSING])
        elif model.status == STATUS_STALE:
            self._status.setText(STALE_CARD_COPY)
        elif model.status == STATUS_ORPHANED:
            self._status.setText(ORPHANED_CARD_COPY)
        else:
            self._status.setText("")
        self._status.setProperty("status", model.status)
        section_label = SECTION_LABELS_ZH.get(model.section, model.section)
        self._foot_left.set_full_text(
            f"{section_label} · {_range_text(model.x_range, model.x_unit)}"
        )
        self._foot_source.set_full_text(model.source_summary if model.show_source else "")
        self._sync_type_chip(section_label)
        self._set_image(model)
        _set_flag(self, "selected", model.selected)
        _set_flag(self, "dimmed", model.dimmed)
        _set_flag(self, "orphaned", model.status == STATUS_ORPHANED)
        _set_flag(self, "replacementArmed", model.replacement_armed)
        self.setProperty("status", model.status)
        self._apply_dim(model.dimmed)
        self._apply_lod_visibility()
        _repolish(self)
        _repolish(self._status)
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
        if model.status == STATUS_STALE:
            parts.append("可同步")
        self.setAccessibleName(" ".join(part for part in parts if part))
        self.setToolTip(_full_tooltip(title, model.section, model.source_summary, model.status))

    def set_selected(self, on: bool) -> None:
        wanted = bool(on)
        if bool(self._model.selected) == wanted:
            return
        self.apply_model(replace(self._model, selected=wanted))

    def make_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("ultraViewCardMenu")
        apply_rounded_menu_chrome(menu)
        open_act = menu.addAction("打开原 View")
        open_act.triggered.connect(self._emit_open_source)
        if self._model.status == STATUS_STALE:
            sync_act = menu.addAction("同步到最新")
            sync_act.triggered.connect(self._emit_sync)
        focus_act = menu.addAction("临时放大")
        replace_act = menu.addAction("替换为…")
        unplaced_act = menu.addAction("移到未放置")
        remove_act = menu.addAction("从总览移除")
        copy_act = menu.addAction("复制本卡图像")
        focus_act.triggered.connect(self._emit_focus)
        replace_act.triggered.connect(self._emit_rebind)
        unplaced_act.triggered.connect(self._emit_unplaced)
        remove_act.triggered.connect(self._emit_remove)
        copy_act.triggered.connect(self._emit_copy)
        self._menu = menu
        return menu

    def apply_lod(self, level: str, *, show_title: bool, show_source: bool, presentation: bool = False) -> None:
        self._lod_level = level if level in {LOD_FULL, LOD_NO_FOOTER, LOD_TITLE_ONLY} else LOD_FULL
        self._lod_show_title = bool(show_title)
        self._lod_show_source = bool(show_source)
        self._lod_presentation = bool(presentation)
        self._apply_lod_visibility()

    def _apply_lod_visibility(self) -> None:
        vis = lod_visibility(self._lod_level)
        self.setProperty("lod", self._lod_level)
        title_text = self._model.title or self._model.view_id
        self._title.setVisible(bool(vis.title and self._lod_show_title and title_text))
        self._sync_type_chip(SECTION_LABELS_ZH.get(self._model.section, self._model.section))
        self._type_chip.setVisible(bool(vis.type_chip))
        has_status = bool(self._status.text())
        self._status.setVisible(bool(vis.trust and has_status))
        self._sync_btn.setVisible(bool(vis.trust and self._model.status == STATUS_STALE))
        self._focus_btn.setVisible(bool(vis.body_actions))
        footer = bool(vis.footer and self._lod_show_source)
        self._footer.setVisible(footer)
        self._footer.setFixedHeight(CARD_FOOTER_HEIGHT if footer else 0)
        orphaned = self._model is not None and self._model.status == STATUS_ORPHANED
        self._orphan_bar.setVisible(bool(vis.body_actions and orphaned and not self._lod_presentation))
        self._set_preview_visible(bool(vis.preview))
        _repolish(self)

    def _set_preview_visible(self, visible: bool) -> None:
        if visible:
            self._image.setMinimumHeight(max(8, MIN_CARD_CHROME_HEIGHT // 4))
            self._image.setMaximumHeight(QWIDGETSIZE_MAX)
            self._image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._image.setVisible(True)
            # A raw image can have arrived while the preview was hidden at a
            # lower LOD tier (``_set_image`` skips scaling in that case); fit
            # it now so growing back to a preview-showing tier is never
            # missing its pixmap.
            self._fit_card_image()
            return
        self._image.setVisible(False)
        self._image.setMinimumHeight(0)
        self._image.setMaximumHeight(0)

    def _sync_type_chip(self, section_label: str) -> None:
        label = str(section_label or self._model.section)
        icon_factory = _SECTION_TYPE_ICONS.get(self._model.section)
        if icon_factory is not None:
            self._type_chip.setIcon(icon_factory())
        else:
            self._type_chip.setIcon(Icons.mode_ultraview())
        self._type_chip.setToolTip(label)
        self._type_chip.setAccessibleName(label)
        icon_only = self._header.width() > 0 and self._header.width() < TYPE_CHIP_ICON_ONLY_WIDTH
        if icon_only:
            self._type_chip.setToolButtonStyle(Qt.ToolButtonIconOnly)
            self._type_chip.setText("")
            self._type_chip.setFixedWidth(22)
        else:
            self._type_chip.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self._type_chip.setText(label)
            self._type_chip.setMinimumWidth(0)
            self._type_chip.setMaximumWidth(QWIDGETSIZE_MAX)
            hint = self._type_chip.sizeHint()
            self._type_chip.setFixedWidth(max(22, hint.width() + 8))

    def set_preview_quality(self, quality: str) -> None:
        wanted = QUALITY_FAST if quality == QUALITY_FAST else QUALITY_SMOOTH
        if wanted == self._preview_quality:
            return
        self._preview_quality = wanted
        self._fit_card_image()

    def scale_buffer(self) -> QPixmap | None:
        return self._scale_buffer

    def _set_image(self, model: CardViewModel) -> None:
        image = model.image
        if image is not None and not (callable(getattr(image, "isNull", None)) and image.isNull()):
            raw = image if isinstance(image, QImage) else None
            cache_key = int(raw.cacheKey()) if raw is not None else None
            if (
                raw is not None
                and self._raw_image is not None
                and self._raw_cache_key is not None
                and cache_key == self._raw_cache_key
            ):
                return
            self._raw_image = raw
            self._raw_cache_key = cache_key
            self._source_pixmap = None
            self._scale_buffer = None
            self._scale_key = None
            self._image.setText("")
            # TITLE_ONLY hides the preview label entirely; scaling a pixmap
            # nobody can see is pure waste on the LOD tier that carries the
            # most cards.  ``_set_preview_visible(True)`` re-fits on the way
            # back up so the buffer is never stale, just deferred.
            if lod_visibility(self._lod_level).preview:
                self._fit_card_image()
            return
        self._raw_image = None
        self._raw_cache_key = None
        self._source_pixmap = None
        self._scale_buffer = None
        self._scale_key = None
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
        self._sync_type_chip(SECTION_LABELS_ZH.get(self._model.section, self._model.section))
        if lod_visibility(self._lod_level).preview:
            self._fit_card_image()

    def _preview_fit_size(self) -> QSize:
        """Inner label box after QSS padding, not the outer ``size()``."""
        avail = self._image.contentsRect().size()
        if avail.width() < 2 or avail.height() < 2:
            return self._image.size()
        return avail

    def _fit_card_image(self) -> None:
        if self._raw_image is None:
            return
        raw_w = self._raw_image.width()
        raw_h = self._raw_image.height()
        avail = self._preview_fit_size()
        if avail.width() < 2 or avail.height() < 2:
            return
        cap_w = max(1, min(avail.width(), raw_w))
        cap_h = max(1, min(avail.height(), raw_h))
        key = (
            cap_w,
            cap_h,
            self._preview_quality,
            int(self._raw_image.cacheKey()),
        )
        if self._scale_buffer is not None and self._scale_key == key:
            self._image.setPixmap(self._scale_buffer)
            return
        if self._source_pixmap is None:
            self._source_pixmap = QPixmap.fromImage(self._raw_image)
        transform = (
            Qt.FastTransformation
            if self._preview_quality == QUALITY_FAST
            else Qt.SmoothTransformation
        )
        scaled = self._source_pixmap.scaled(
            cap_w, cap_h, Qt.KeepAspectRatio, transform
        )
        self._scale_buffer = scaled
        self._scale_key = key
        self._image.setPixmap(scaled)

    def restore_dim(self) -> None:
        self._apply_dim(bool(self._model.dimmed))

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

    def _emit_sync(self, _checked: bool = False) -> None:
        if self._model.status != STATUS_STALE:
            return
        self.sync_requested.emit(self._model.section, self._model.view_id)

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

    def event(self, event):  # noqa: N802
        if _forward_native_zoom(self, event):
            return True
        return super().event(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if _forward_zoom_wheel(self, event):
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if _handle_pan_press(self, event):
            event.accept()
            return
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
        page = _page_of(self)
        if page is not None:
            page.handle_card_double_click(self._model.section, self._model.view_id)
            event.accept()
            return
        self.focus_requested.emit(self._model.section, self._model.view_id)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        page = _page_of(self)
        if page is not None and page.is_board_panning():
            page.update_board_pan(event)
            event.accept()
            return
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
        if _handle_pan_release(self, event):
            self._press_pos = None
            event.accept()
            return
        handler = getattr(self.parentWidget(), "handle_card_mouse_release", None)
        if callable(handler):
            handler(self, event)
            self._press_pos = None
            event.accept()
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
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

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
        super().keyReleaseEvent(event)

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
    sync_requested = pyqtSignal(str, str)
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
        self._zoom = ZOOM_DEFAULT
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
        self._raise_overlay()

    def set_viewport_size(self, size: QSize) -> None:
        """Record the scroll viewport. Logical canvas is ``BASE_BOARD_SIZE``.

        Window size used to drive slot aspect; that made every card follow the
        chrome-safe fit rect. Keep the setter so callers and tests still have
        a viewport to query, but geometry comes from the export-sized board.
        """
        if size == self._viewport_size:
            return
        if self._slot_active:
            self.cancel_gesture()
        self._viewport_size = QSize(size)
        self._sync_logical_size()

    def set_zoom(self, zoom: float) -> None:
        value = float(zoom)
        if value == self._zoom:
            return
        self._zoom = value
        self._sync_logical_size()

    def logical_size(self) -> QSize:
        return QSize(self.size())

    def unzoomed_size(self) -> QSize:
        try:
            width, height = logical_board_size(self._layout_id, BASE_BOARD_SIZE)
        except ValueError:
            return QSize(*BASE_BOARD_SIZE)
        return QSize(width, height)

    def content_rect_1x(self) -> tuple[float, float, float, float] | None:
        """Union of occupied template slots at 1×. Empty board returns None."""
        return _union_pixel_rect(
            self.unzoomed_slot_rect(slot_id)
            for slot_id, widget in self._widgets.items()
            if isinstance(widget, UltraViewCard)
        )

    def content_rect(self) -> tuple[float, float, float, float] | None:
        """Union of occupied template cards at the current zoom."""
        return _union_pixel_rect(
            (float(card.x()), float(card.y()), float(card.width()), float(card.height()))
            for card in self.card_widgets()
        )

    def unzoomed_slot_rect(self, slot_id: str) -> tuple[float, float, float, float] | None:
        size = self.unzoomed_size()
        content = (
            BOARD_PADDING,
            BOARD_PADDING,
            max(0, size.width() - 2 * BOARD_PADDING),
            max(0, size.height() - 2 * BOARD_PADDING),
        )
        try:
            rects = slot_rects(self._layout_id, content, self._ratio)
        except ValueError:
            return None
        rect = rects.get(slot_id)
        if rect is None:
            return None
        return (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))

    def clear_projection(self) -> None:
        if not self._widgets:
            return
        for slot_id in list(self._widgets):
            self._discard(slot_id)

    def cancel_gesture(self) -> bool:
        if self._slot_source is None:
            return False
        source = self._slot_source
        active = self._slot_active
        card = self._widgets.get(source)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if isinstance(card, UltraViewCard):
            card.restore_dim()
        self._overlay.clear()
        self._slot_source = None
        self._slot_press = None
        self._slot_active = False
        if active:
            self.drag_finished.emit()
        return True

    def _sync_logical_size(self) -> None:
        unzoomed = self.unzoomed_size()
        width, height = zoomed_viewport_size(
            (unzoomed.width(), unzoomed.height()), self._zoom
        )
        target = QSize(width, height)
        if self.minimumSize() != target:
            self.setMinimumSize(target)
        if self.size() != target:
            self.resize(target)

    def _scaled_slot_rects(self) -> dict[str, tuple[int, int, int, int]]:
        """1× template slots, then uniform zoom. Padding must not be re-laid out."""
        size = self.unzoomed_size()
        content = (
            BOARD_PADDING,
            BOARD_PADDING,
            max(0, size.width() - 2 * BOARD_PADDING),
            max(0, size.height() - 2 * BOARD_PADDING),
        )
        try:
            rects = slot_rects(self._layout_id, content, self._ratio)
        except ValueError:
            return {}
        z = float(self._zoom)
        if abs(z - 1.0) < 1e-12:
            return rects
        return {
            slot_id: (
                int(round(x * z)),
                int(round(y * z)),
                max(0, int(round(width * z))),
                max(0, int(round(height * z))),
            )
            for slot_id, (x, y, width, height) in rects.items()
        }

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
            self._raise_overlay()
            return
        if isinstance(current, UltraViewCard):
            current.apply_model(model)
            return
        self._discard(slot_id)
        card = UltraViewCard(model, self)
        card.open_source_requested.connect(self.open_source_requested)
        card.sync_requested.connect(self.sync_requested)
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
        rects = self._scaled_slot_rects()
        for slot_id, (x, y, width, height) in rects.items():
            widget = self._widgets.get(slot_id)
            if widget is not None:
                widget.setGeometry(x, y, max(0, width), max(0, height))

    def slot_id_at(self, pos: QPoint) -> str | None:
        rects = self._scaled_slot_rects()
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

    def is_gesture_active(self) -> bool:
        return bool(self._slot_active)

    def set_preview_quality(self, quality: str) -> None:
        for card in self.card_widgets():
            card.set_preview_quality(quality)

    def event(self, event):  # noqa: N802
        if _forward_native_zoom(self, event):
            return True
        return super().event(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if _forward_zoom_wheel(self, event):
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if _handle_pan_press(self, event):
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            page = _page_of(self)
            if page is not None:
                page.notify_canvas_click()
            _clear_page_card_selection(self)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        page = _page_of(self)
        if page is not None and page.is_board_panning():
            page.update_board_pan(event)
            event.accept()
            return
        if self._slot_source is not None and (
            event.buttons() & Qt.LeftButton or QWidget.mouseGrabber() is self
        ):
            self._slot_drag_at(event.pos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if _handle_pan_release(self, event):
            event.accept()
            return
        if self._slot_source is not None and event.button() == Qt.LeftButton:
            self._finish_slot_drag(event.pos(), event.globalPos())
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
        super().keyReleaseEvent(event)

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
        self._finish_slot_drag(card.mapTo(self, event.pos()), event.globalPos())

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

    def _finish_slot_drag(self, board_pos: QPoint, global_pos: QPoint | None = None) -> None:
        source = self._slot_source
        active = self._slot_active
        card = self._widgets.get(source) if source else None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if isinstance(card, UltraViewCard):
            card.restore_dim()
        self._overlay.clear()
        self._slot_source = None
        self._slot_press = None
        self._slot_active = False
        if active:
            self.drag_finished.emit()
        if not active or source is None:
            return
        if global_pos is not None and _drop_on_unplaced_tray(self, global_pos):
            if isinstance(card, UltraViewCard):
                model = card.model()
                self.move_to_unplaced_requested.emit(model.section, model.view_id)
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
    autofit_requested = pyqtSignal(str, str)

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
        fit_action = size_menu.addAction("按原图比例")
        fit_action.triggered.connect(self._emit_autofit)
        return menu

    def _emit_preset(self, preset: str, _checked: bool = False) -> None:
        self.preset_requested.emit(self._model.section, self._model.view_id, preset)

    def _emit_autofit(self, _checked: bool = False) -> None:
        self.autofit_requested.emit(self._model.section, self._model.view_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if _handle_pan_press(self, event):
            event.accept()
            return
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
        page = _page_of(self)
        if page is not None and page.is_board_panning():
            page.update_board_pan(event)
            event.accept()
            return
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
        if _handle_pan_release(self, event):
            self._press_pos = None
            event.accept()
            return
        handler = getattr(self.parentWidget(), "handle_card_mouse_release", None)
        if callable(handler):
            handler(self, event)
        self._press_pos = None
        QWidget.mouseReleaseEvent(self, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
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
    autofit_requested = pyqtSignal(str, str)
    open_source_requested = pyqtSignal(str, str)
    sync_requested = pyqtSignal(str, str)
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
        self._zoom = ZOOM_DEFAULT
        self._metrics = screen_grid_metrics([])
        self._base_metrics = self._metrics
        self._gesture = FreeGridGesture()
        self._overlay = GhostOverlay(self)
        self._overlay.hide()
        self._replace = ReplaceHoverController(self)
        self._replace.armed.connect(self._on_replace_armed)
        self._replace.cleared.connect(self._on_replace_cleared)
        self._pending_shift_toggle: UltraViewRef | None = None
        self._layout_revision = 0
        self._gesture_dimmed = False
        # Cards currently wearing the drag dim, owned by the board so the set
        # can shrink mid-gesture; the plan's preview set changes on every move.
        self._dimmed_refs: set[UltraViewRef] = set()

    def set_viewport_size(self, size: QSize) -> None:
        """Record the scroll viewport. Metrics use ``screen_grid_metrics``.

        Column width is the 1600-wide export column, not the window width, so
        card aspect stays put when the user resizes or toggles chrome.
        """
        if size == self._viewport_size:
            return
        if self._gesture.is_active():
            self.cancel_gesture()
        self._viewport_size = QSize(size)
        self._sync_metrics()

    def set_zoom(self, zoom: float) -> None:
        value = float(zoom)
        if value == self._zoom:
            return
        self._zoom = value
        self._sync_metrics()

    def unzoomed_size(self) -> QSize:
        return QSize(self._base_metrics.board_width, self._base_metrics.board_height)

    def content_rect_1x(self) -> tuple[float, float, float, float] | None:
        """Union of placed free-grid cards at 1×. Empty board returns None."""
        return _union_pixel_rect(
            rect_to_pixels(item.rect, self._base_metrics)
            for item in self._placements.values()
        )

    def content_rect(self) -> tuple[float, float, float, float] | None:
        """Union of placed free-grid cards at the current zoom."""
        return _union_pixel_rect(
            rect_to_pixels(item.rect, self._metrics)
            for item in self._placements.values()
        )

    def set_preview_quality(self, quality: str) -> None:
        for card in self._widgets.values():
            card.set_preview_quality(quality)

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
        if cancelled:
            self._relayout()
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
        self._layout_revision += 1
        wanted = set(self._placements)
        for ref in list(self._widgets):
            if ref not in wanted:
                widget = self._widgets.pop(ref)
                self._dimmed_refs.discard(ref)
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
        card.sync_requested.connect(self.sync_requested)
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
        card.autofit_requested.connect(self.autofit_requested)

    def _raise_overlay(self) -> None:
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

    def _sync_metrics(self) -> None:
        self._base_metrics = screen_grid_metrics(list(self._placements.values()))
        self._metrics = scale_grid_metrics(self._base_metrics, self._zoom)
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
                self._gesture.press_resize(
                    ref,
                    placement.rect,
                    handle,
                    board_pos,
                    grab,
                    layout_revision=self._layout_revision,
                )
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
            self._gesture.press_resize(
                ref,
                placement.rect,
                handle,
                board_pos,
                grab,
                layout_revision=self._layout_revision,
            )
        else:
            self._gesture.press(
                ref,
                placement.rect,
                board_pos,
                grab,
                group_origins=group_origins,
                layout_revision=self._layout_revision,
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
        self._finish_gesture(commit=True, global_pos=event.globalPos())

    def _finish_pending_shift_toggle(self) -> bool:
        ref = self._pending_shift_toggle
        self._pending_shift_toggle = None
        if ref is None:
            return False
        self._gesture.toggle_selected(ref)
        self._apply_selection_flags()
        return True

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if _handle_pan_press(self, event):
            event.accept()
            return
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        if self._card_at(event.pos()) is not None:
            super().mousePressEvent(event)
            return
        page = _page_of(self)
        if page is not None:
            page.notify_canvas_click()
        additive = bool(event.modifiers() & Qt.ShiftModifier)
        if not additive:
            page = _page_of(self)
            if page is not None:
                page.clear_card_selection()
            elif self._gesture.selection():
                self._gesture.clear_selection()
                self._apply_selection_flags()
        self._gesture.begin_marquee((event.pos().x(), event.pos().y()), additive)
        self._overlay.set_marquee(self._gesture.marquee_rect())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        page = _page_of(self)
        if page is not None and page.is_board_panning():
            page.update_board_pan(event)
            event.accept()
            return
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
        if _handle_pan_release(self, event):
            event.accept()
            return
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
            self._finish_gesture(commit=True, global_pos=event.globalPos())
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
        if self.handle_selection_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
        super().keyReleaseEvent(event)

    def event(self, event):  # noqa: N802
        if _forward_native_zoom(self, event):
            return True
        return super().event(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if _forward_zoom_wheel(self, event):
            event.accept()
            return
        super().wheelEvent(event)

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
        preview_refs = session.preview_refs()
        members = session.group_origins or {session.ref: session.origin}
        dim_refs = set(members)
        dim_refs.update(preview_refs)
        if not self._gesture_dimmed:
            self.drag_started.emit("layout")
            self._gesture_dimmed = True
        self._sync_gesture_dim(dim_refs)
        ghosts = []
        ghost_rects = session.group_ghost_pixels(self._metrics, board_pos)
        refs = list(preview_refs)
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

    def _sync_gesture_dim(self, wanted: set[UltraViewRef]) -> None:
        """Dim exactly ``wanted`` and undim whatever left the plan.

        The plan's displaced set changes as the pointer moves, so a set computed
        once on the first frame does not match the set restored on release: a
        neighbour that was pushed and then stopped being pushed used to stay at
        40% opacity forever (review 2026-08-15 §4.3 dim 泄漏).
        """
        for ref in self._dimmed_refs - wanted:
            card = self._widgets.get(ref)
            if card is not None:
                card.restore_dim()
        for ref in wanted - self._dimmed_refs:
            card = self._widgets.get(ref)
            if card is None:
                continue
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(DRAG_DIM_OPACITY)
            card.setGraphicsEffect(effect)
        self._dimmed_refs = {ref for ref in wanted if ref in self._widgets}

    def _clear_gesture_dim(self) -> None:
        """Unconditional restore: whatever the board dimmed, the board undims."""
        for ref in self._dimmed_refs:
            card = self._widgets.get(ref)
            if card is not None:
                card.restore_dim()
        self._dimmed_refs = set()

    def _finish_gesture(self, *, commit: bool, global_pos: QPoint | None = None) -> None:
        session = self._gesture.take()
        self._release_mouse_if_grabbed()
        self._gesture_dimmed = False
        if session is None:
            self._clear_gesture_dim()
            return
        members = session.group_origins or {session.ref: session.origin}
        restore_refs = set(members) | set(self._dimmed_refs)
        if session.plan is not None:
            restore_refs.update(ref for ref, _rect in session.plan.preview_rects())
        preview_open = True

        def cleanup_preview() -> None:
            nonlocal preview_open
            if not preview_open:
                return
            preview_open = False
            self._clear_gesture_dim()
            for ref in restore_refs:
                card = self._widgets.get(ref)
                if card is not None:
                    card.restore_dim()
                    card.unsetCursor()
            self._overlay.clear()
            self._sync_selection_handles()
            if session.active:
                self.drag_finished.emit()

        try:
            if not commit or not session.active:
                self._relayout()
                return
            if global_pos is not None and _drop_on_unplaced_tray(self, global_pos):
                for ref in members:
                    self.move_to_unplaced_requested.emit(ref.section, ref.view_id)
                return
            self._commit_session_plan(session)
        finally:
            cleanup_preview()

    def _commit_session_plan(self, session) -> None:
        operation = LAYOUT_RESIZE if session.handle else LAYOUT_MOVE
        incoming = dict(session.group_candidates)
        plan = session.plan
        if session.is_group_move() and plan is None and not session.legal:
            self.feedback_requested.emit(FEEDBACK_OUT_OF_GRID)
            self._relayout()
            return
        if (
            plan is None
            or plan.based_on_layout_revision != self._layout_revision
        ):
            plan = plan_layout(
                tuple(self._placements.values()),
                session.ref,
                session.candidate,
                operation,
                layout_revision=self._layout_revision,
                preferred=avoidance_preferred_delta(session.origin, session.candidate),
                incoming=incoming or None,
            )
        _log_plan_result(plan)
        if not plan.accepted:
            self.feedback_requested.emit(_reject_feedback(plan.reason))
            self._relayout()
            return
        reason = "drag-resize" if session.handle else "drag-move"
        self._emit_plan(plan, reason)

    def _emit_plan(self, plan: LayoutPlan, reason: str) -> bool:
        updates = plan.committed_updates()
        if not updates:
            self._relayout()
            return False
        if len(updates) == 1 and updates[0][0] == plan.mover_ref:
            ref, rect = updates[0]
            self.geometry_requested.emit(
                ref.section,
                ref.view_id,
                rect.column,
                rect.row,
                rect.column_span,
                rect.row_span,
                reason,
            )
        else:
            payload = tuple(
                (
                    ref.section,
                    ref.view_id,
                    rect.column,
                    rect.row,
                    rect.column_span,
                    rect.row_span,
                )
                for ref, rect in sorted(
                    updates, key=lambda item: (item[0].section, item[0].view_id)
                )
            )
            self.group_geometry_requested.emit(payload)
        if plan.affected_count() > 1:
            self.feedback_requested.emit(
                FEEDBACK_REARRANGED.format(count=plan.affected_count())
            )
        self._warn_if_displaced_offscreen(plan)
        return True

    def _visible_board_rect(self) -> QRect:
        """Board-local rect of the scroll viewport, or a null rect when unknown.

        Derived from the scroll host's geometry rather than ``visibleRegion()``
        so it is pure geometry: no dependency on paint/visibility state.
        """
        host = self.parentWidget()
        while host is not None:
            area = host.parentWidget()
            if isinstance(area, QAbstractScrollArea) and area.viewport() is host:
                return QRect(self.mapFrom(host, QPoint(0, 0)), host.size())
            host = area
        return QRect()

    def _warn_if_displaced_offscreen(self, plan: LayoutPlan) -> None:
        """Tell the user when a card was pushed clean out of the visible board.

        Blockers slide along the drag axis (spec D9.3, 2026-08-15 annotation), so
        a displaced card can land below everything the user can see.  Scroll
        follow is not in this batch; an honest hint is.
        """
        visible = self._visible_board_rect()
        if visible.isEmpty():
            return
        gone = [
            item
            for item in plan.displaced_before_after
            if not visible.intersects(QRect(*rect_to_pixels(item.after, self._metrics)))
        ]
        if not gone:
            return
        _PLANNER_LOG.info(
            "ultraview displaced %s card(s) outside the viewport: %s",
            len(gone),
            ", ".join(f"{item.ref.section}/{item.ref.view_id}" for item in gone),
        )
        self.feedback_requested.emit(FEEDBACK_DISPLACED_OFFSCREEN)

    def _request_geometry(self, ref: UltraViewRef, rect: GridRect, reason: str) -> bool:
        placement = self._placements.get(ref)
        if placement is None or rect == placement.rect:
            return False
        operation = (
            LAYOUT_RESIZE if "resize" in reason else LAYOUT_MOVE
        )
        plan = plan_layout(
            tuple(self._placements.values()),
            ref,
            rect,
            operation,
            layout_revision=self._layout_revision,
            preferred=avoidance_preferred_delta(placement.rect, rect),
            incoming={ref: rect},
        )
        _log_plan_result(plan)
        if not plan.accepted:
            self.feedback_requested.emit(_reject_feedback(plan.reason))
            self._relayout()
            return False
        return self._emit_plan(plan, reason)

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
            else GridRect(
                placement.rect.column + int(column_delta),
                placement.rect.row + int(row_delta),
                placement.rect.column_span,
                placement.rect.row_span,
            )
        )
        if not resize:
            self._request_geometry(ref, candidate, "keyboard-move")
            return
        self._request_geometry(ref, candidate, "keyboard-resize")

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

    def event(self, event):  # noqa: N802
        if _forward_native_zoom(self, event):
            return True
        return super().event(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if _forward_zoom_wheel(self, event):
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if _handle_pan_press(self, event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        page = _page_of(self)
        if page is not None and page.is_board_panning():
            page.update_board_pan(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if _handle_pan_release(self, event):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
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

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if _handle_space_key(self, event):
            event.accept()
            return
        super().keyReleaseEvent(event)


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
        self._free_metrics = screen_grid_metrics(placements)
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
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(TRAY_ITEM_MIN_HEIGHT)
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
        remove.setObjectName("ultraViewTrayRemove")
        remove.setText("移除")
        remove.clicked.connect(self._emit_remove)
        for button in (place, self._rebind, remove):
            button.setAutoRaise(False)
            button.setCursor(Qt.PointingHandCursor)
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
        self._overlay_mode = False
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
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body.setMaximumHeight(TRAY_BODY_MAX_HEIGHT)
        self._inner = QWidget(self._body)
        self._inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(10, 8, 10, 10)
        self._inner_layout.setSpacing(6)
        self._body.setWidget(self._inner)
        self._empty = QLabel("缩小布局或移入的卡片会出现在这里", self._inner)
        self._empty.setObjectName("ultraViewTrayEmptyHint")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._inner_layout.addWidget(self._empty)
        self._empty.hide()
        self._body.setVisible(False)
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(self._body, 1)

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
        empty = self._empty
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            widget = item.widget()
            if widget is None or widget is empty:
                continue
            widget.setParent(None)
            widget.deleteLater()
        self._items = []
        if self._inner_layout.indexOf(empty) < 0:
            self._inner_layout.addWidget(empty, 0)
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
            widget.setFocusPolicy(Qt.TabFocus)
            widget.place_requested.connect(self.place_requested)
            widget.remove_requested.connect(self.remove_requested)
            widget.locate_requested.connect(self.locate_requested)
            widget.rebind_arm_requested.connect(self.rebind_arm_requested)
            widget.drag_started.connect(self.drag_started)
            widget.drag_finished.connect(self.drag_finished)
            self._inner_layout.addWidget(widget, 0)
            self._items.append(widget)
        count = len(refs)
        self._title.setText("未放置" if count == 0 else f"未放置 · {count}")
        empty.setVisible(count == 0)
        self._sync_inner_min_height()

    def sizeHint(self) -> QSize:  # noqa: N802
        title_h = max(28, self._title.sizeHint().height()) if self._title.isVisible() else 0
        rows = len(self._items) if self._items else 1
        visible = min(UNPLACED_OVERLAY_VISIBLE_ROWS, max(1, rows))
        margins = self._inner_layout.contentsMargins()
        body_h = (
            margins.top()
            + margins.bottom()
            + visible * TRAY_ITEM_MIN_HEIGHT
            + max(0, visible - 1) * self._inner_layout.spacing()
        )
        return QSize(UNPLACED_OVERLAY_WIDTH, max(UNPLACED_OVERLAY_MIN_HEIGHT, title_h + body_h))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, UNPLACED_OVERLAY_MIN_HEIGHT)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_inner_min_height()

    def _measured_inner_height(self) -> int:
        margins = self._inner_layout.contentsMargins()
        count = len(self._items)
        if count == 0:
            return margins.top() + margins.bottom() + 36
        return (
            margins.top()
            + margins.bottom()
            + count * TRAY_ITEM_MIN_HEIGHT
            + max(0, count - 1) * self._inner_layout.spacing()
        )

    def _sync_inner_min_height(self) -> None:
        self._inner.setMinimumHeight(self._measured_inner_height())

    def set_overlay_mode(self, overlay: bool) -> None:
        """Overlay host always shows the body; the old collapsible title is chrome."""
        self._overlay_mode = bool(overlay)
        self._title.setCheckable(not self._overlay_mode)
        self._title.setVisible(True)
        if self._overlay_mode:
            blocked = self._title.blockSignals(True)
            self._title.setChecked(True)
            self._title.blockSignals(blocked)
            self.set_expanded(True)
            self._body.setMaximumHeight(16777215)
        else:
            self._body.setMaximumHeight(TRAY_BODY_MAX_HEIGHT)

    def focus_first_item(self) -> bool:
        if not self._items:
            if self._empty.isVisible():
                self._empty.setFocus(Qt.OtherFocusReason)
                return True
            return False
        self._items[0].setFocus(Qt.OtherFocusReason)
        return True

    def _on_title(self, checked: bool) -> None:
        if self._overlay_mode:
            blocked = self._title.blockSignals(True)
            self._title.setChecked(True)
            self._title.blockSignals(blocked)
            return
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
        self._sync_badge = QLabel("同步中", panel)
        self._sync_badge.setObjectName("ultraViewFocusSyncing")
        self._sync_badge.setAttribute(Qt.WA_StyledBackground, True)
        self._sync_badge.hide()
        close_btn = QToolButton(panel)
        close_btn.setText("×")
        close_btn.setObjectName("ultraViewFocusClose")
        close_btn.clicked.connect(self.close_layer)
        head.addWidget(self._title, 1)
        head.addWidget(self._sync_badge, 0)
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

    def current_ref(self) -> tuple[str, str] | None:
        if not self._section or not self._view_id:
            return None
        return (self._section, self._view_id)

    def image_host_size(self) -> tuple[int, int]:
        size = self._image_host.size()
        return (max(1, int(size.width())), max(1, int(size.height())))

    def set_syncing(self, syncing: bool) -> None:
        self._sync_badge.setVisible(bool(syncing))
        if syncing:
            self._sync_badge.raise_()

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
        self._section = ""
        self._view_id = ""
        self._sync_badge.hide()
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
