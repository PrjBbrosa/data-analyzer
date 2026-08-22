"""UltraView page widgets: library, board grid, cards, tray, focus layer.

Widgets emit typed intents. They do not import MainWindow, mutate BoardState,
or call analysis entry points. Preview records are duck-typed.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, replace
from functools import partial
from typing import Any, Callable, Mapping, Sequence

import qtawesome as qta
from PyQt5 import sip
from PyQt5.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, QRect, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QContextMenuEvent,
    QCursor,
    QDrag,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
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
    ULTRAVIEW_PAGE_OBJECT_NAME,
    ULTRAVIEW_REF_MIME,
    FreeGridPlacement,
    GridAnchor,
    GridBounds,
    GridRect,
    BoardBox,
    ConnectorObject,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
    UltraViewBoardState,
    safety_grid_bounds,
    UltraViewRef,
    parse_ref_payload,
    resolve_free_grid_insert_rect,
    section_search_haystack,
)
from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui_kit.menus import add_rounded_submenu, apply_rounded_menu_chrome
from mf4_analyzer.ui_kit.ultraview_style import titanium_color
from mf4_analyzer.ui_kit.widgets import SearchField

from .chrome import ULTRAVIEW_MUTED
from .laser_cursor import (
    LASER_CURSOR_DPR_CHANGE_EVENTS,
    clear_laser_cursor_cache,
    laser_pointer_cursor,
)
from .layouts import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    MIN_CARD_CHROME_HEIGHT,
    content_rect,
    logical_board_size,
    preview_reading_box,
    slot_rects,
)
from .feedback import (
    AUTHOR_LOCKED,
    FEEDBACK_DISPLACED_OFFSCREEN,
    FEEDBACK_NO_LEGAL_LAYOUT,
    FEEDBACK_OUT_OF_GRID,
    FEEDBACK_REARRANGED,
    FEEDBACK_SEARCH_BUDGET,
    format_displace_preview,
    format_rearranged,
    text_for_key,
    text_for_reason,
)
from .free_grid import (
    GridMetrics,
    LAYOUT_MOVE,
    LAYOUT_RESIZE,
    LayoutPlan,
    LayoutRejectReason,
    avoidance_preferred_delta,
    candidate_resize,
    clamp_rect,
    export_grid_metrics,
    hit_handle,
    legal_grid_rect,
    plan_layout,
    rect_to_pixels,
    screen_grid_metrics,
)
from .author_geometry import (
    board_box_to_pixels,
    board_point_to_pixels,
    connector_handle_points,
    hit_box_handle,
    hit_connector,
    hit_connector_handle,
    hit_stroke,
    pixels_to_board_point,
    stroke_hit_record,
)
from .author_layer import AuthorLayerModel, AuthorPaintLayer
from .author_style import DEFAULT_STICKY_PALETTE, DEFAULT_THEME
from .author_tools import (
    HIT_AUTHOR,
    HIT_BLANK,
    HIT_RESIZE_HANDLE,
    SHAPE_MIN_HEIGHT,
    SHAPE_MIN_WIDTH,
    STICKY_MIN_HEIGHT,
    STICKY_MIN_WIDTH,
    TEXT_MIN_HEIGHT,
    TEXT_MIN_WIDTH,
    TOOL_STICKY,
    AuthorCreateIntent,
    AuthorDeleteIntent,
    AuthorKey,
    AuthorUpdateIntent,
    BoardInteractionController,
    CardKey,
    HitTarget,
    ShapeUpdateIntent,
    TextUpdateIntent,
    clamp_author_box,
    new_author_object_id,
    resolve_board_hit,
    sticky_box_from_points,
)
from .author_widgets import BoardTextEditor, StickyNoteWidget
from .elastic_workspace import author_content_bounds
from .gesture import FreeGridGesture
from .ghost_overlay import (
    GhostOverlay,
    PREVIEW_COLLISION_REJECT,
    PREVIEW_DISPLACED_WARNING,
    PREVIEW_MOVER_VALID,
    PREVIEW_SAFETY_WALL,
)
from .viewport_feedback import ViewportFeedbackSurface
from .compositor import compose_board, composed_slot_rects
from .viewport import (
    QUALITY_FAST,
    QUALITY_SMOOTH,
    LOD_FULL,
    LOD_NO_FOOTER,
    LOD_TITLE_ONLY,
    lod_visibility,
    ZOOM_DEFAULT,
    linear_zoom_anchor,
    linear_zoom_point,
    scale_grid_metrics,
    zoomed_viewport_size,
)
from .._helpers import ULTRAVIEW_HINT_BAR_HEIGHT

from .widgets_common import (
    STATUS_LABELS_ZH,
    _accept_ultraview_drag,
    _clear_page_card_selection,
    _drop_on_unplaced_tray,
    _effective_device_pixel_ratio,
    _page_of,
    _set_flag,
    extract_ref_strings,
    make_ref_mime,
    view_fallback,
)
from .card_widgets import (
    DIMMED_OPACITY,
    DRAG_DIM_OPACITY,
    MISSING_CARD_COPY,
    ORPHANED_CARD_COPY,
    REPLACE_HOVER_MS,
    STALE_CARD_COPY,
    TYPE_CHIP_ICON_ONLY_WIDTH,
    CardViewModel,
    FreeGridCard,
    ReplaceHoverController,
    UltraViewCard,
    preview_image,
)
from .library_widgets import (
    LIBRARY_DEFAULT_WIDTH,
    LIBRARY_HEAD_HEIGHT,
    LIBRARY_MAX_WIDTH,
    LIBRARY_MODE_GROUPS,
    LIBRARY_OVERLAY_HEIGHT,
    LIBRARY_OVERLAY_MIN_HEIGHT,
    LIBRARY_ROW_ACTION_SIZE,
    LIBRARY_ROW_DOT_INSET,
    LIBRARY_ROW_HEIGHT,
    LIBRARY_SEARCH_HEIGHT,
    LIBRARY_SECTION_GAP,
    LIBRARY_SECTION_HEAD_HEIGHT,
    LIBRARY_SECTION_ROW_GAP,
    LIBRARY_SELECTED_ROW_GUTTER,
    TRAY_BODY_MAX_HEIGHT,
    TRAY_ITEM_MIN_HEIGHT,
    UNPLACED_OVERLAY_MIN_HEIGHT,
    UNPLACED_OVERLAY_VISIBLE_ROWS,
    UNPLACED_OVERLAY_WIDTH,
    LibraryRow,
    LibraryRowWidget,
    TrayItem,
    UnplacedTray,
    ViewLibraryPanel,
    coerce_library_row,
)

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

_PLANNER_LOG = logging.getLogger(__name__)
_PLANNER_LOG_MONO = 0.0
_PLANNER_LOG_INTERVAL_S = 0.5


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
    return text_for_reason(reason)


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
        self._context = QLabel("拖卡片移动 · 左键框选 · 右键拖动画布 · Ctrl+滚轮缩放", self)
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
    show_card_actions_toggled = pyqtSignal(bool)
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
        self._free_grid.setToolTip("切换自由网格（12 列基准网格）")
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
        self._act_card_actions = display_menu.addAction("常驻显示卡片操作")
        self._act_card_actions.setCheckable(True)
        self._act_card_actions.setChecked(False)
        self._act_titles.toggled.connect(self.show_titles_toggled)
        self._act_sources.toggled.connect(self.show_sources_toggled)
        self._act_card_actions.toggled.connect(self.show_card_actions_toggled)
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
        self._zoom_fit.setToolTip("适应内容：图面填满画布，最高 300%")
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

    def set_show_flags(
        self, titles: bool, sources: bool, card_actions: bool = False
    ) -> None:
        blocked = self._act_titles.blockSignals(True)
        self._act_titles.setChecked(bool(titles))
        self._act_titles.blockSignals(blocked)
        blocked = self._act_sources.blockSignals(True)
        self._act_sources.setChecked(bool(sources))
        self._act_sources.blockSignals(blocked)
        blocked = self._act_card_actions.blockSignals(True)
        self._act_card_actions.setChecked(bool(card_actions))
        self._act_card_actions.blockSignals(blocked)

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
        # Template-only overlay. FreeGrid paints on ViewportFeedbackSurface.
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

    def zoom_anchor_at(self, point: tuple[float, float]) -> tuple[float, float]:
        """Canvas pixel → zoom-independent anchor. Template geometry is linear."""
        return linear_zoom_anchor(point, self._zoom)

    def point_for_zoom_anchor(self, anchor: tuple[float, float]) -> tuple[float, float]:
        """Inverse of :meth:`zoom_anchor_at` at the zoom currently laid out."""
        return linear_zoom_point(anchor, self._zoom)

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

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            page = _page_of(self)
            if page is not None:
                page.notify_canvas_click()
            _clear_page_card_selection(self)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._slot_source is not None and (
            event.buttons() & Qt.LeftButton or QWidget.mouseGrabber() is self
        ):
            self._slot_drag_at(event.pos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._slot_source is not None and event.button() == Qt.LeftButton:
            self._finish_slot_drag(event.pos(), event.globalPos())
            return
        super().mouseReleaseEvent(event)

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


class FreeGridBoard(QWidget):
    """Visual projection of persisted free-grid state.

    ``GridRect`` stays in its canonical logical coordinate system.  The Page
    supplies a session-only ``GridBounds`` workspace extent when it needs
    room around those rects; this widget only maps that extent to local pixels.
    It deliberately owns neither the edge timer nor any viewport event
    forwarding.
    """

    ref_dropped = pyqtSignal(str, str)
    insert_requested = pyqtSignal(str, str, object)
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
    # Lifetime and latest pointer are separate contracts. The bool/object
    # signal remains for existing board-only tests; Page uses the typed pair.
    workspace_gesture_changed = pyqtSignal(bool, object)
    workspace_gesture_active_changed = pyqtSignal(bool, int)
    workspace_pointer_changed = pyqtSignal(int, object)
    author_create_requested = pyqtSignal(object)
    author_update_requested = pyqtSignal(object)
    author_delete_requested = pyqtSignal(object)
    author_edit_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewFreeGrid")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
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
        self._workspace_extent: GridBounds | None = None
        # Author-created objects share the FreeGrid's signed coordinate plane,
        # but their renderer is deliberately a transparent sibling.  Do not
        # make it an event-filter owner: cards, marquee and Page right-pan
        # keep their existing Qt delivery paths.
        self._author_objects: tuple[object, ...] = ()
        self._author_theme = DEFAULT_THEME
        self._author_layer = AuthorPaintLayer(self)
        # Text editing needs a real widget for CJK IME.  It remains hidden
        # until the creation controller starts an edit transaction; painting
        # ordinary TextObject instances stays in AuthorPaintLayer.
        self._author_text_editor = BoardTextEditor(self)
        self._sticky_note = StickyNoteWidget(self)
        self._sticky_note.hide()
        self._sticky_note.text_committed.connect(self._on_sticky_text_committed)
        self._sticky_note.edit_cancelled.connect(self._on_sticky_edit_cancelled)
        self._creation_allowed = False
        self._author_geometry_session: dict[str, object] | None = None
        self._workspace_gesture_active = False
        self._interaction = BoardInteractionController()
        self._gesture = FreeGridGesture(self._interaction)
        self._overlay = ViewportFeedbackSurface(self)
        self._overlay.hide()
        self._latest_pointer_sample: tuple[tuple[int, int], bool, QPoint | None] | None = None
        self._last_pointer_sample: tuple[tuple[int, int], bool, QPoint | None] | None = None
        self._last_consumed_candidate_fingerprint: tuple | None = None
        self._feedback_generation = 0
        self._diag_planner_calls = 0
        self._diag_frame_presents = 0
        self._pointer_coalesce_timer = QTimer(self)
        self._pointer_coalesce_timer.setSingleShot(True)
        self._pointer_coalesce_timer.setInterval(0)
        self._pointer_coalesce_timer.timeout.connect(self._consume_latest_pointer_sample)
        self._ghost_buffers: dict[UltraViewRef, QPixmap] = {}
        self._replace = ReplaceHoverController(self)
        self._replace.armed.connect(self._on_replace_armed)
        self._replace.cleared.connect(self._on_replace_cleared)
        self._pending_shift_toggle: UltraViewRef | None = None
        self._layout_revision = 0
        self._gesture_dimmed = False
        self._gesture_presenting = False
        # This is replaced from ``free_grid_default_span`` when a Board is
        # installed.  Keep the standalone default in schema-5 micro-grid
        # units as well, so test/harness boards never create undersized cards.
        self._default_insert_span = (8, 6)
        self._insert_preview_rect: GridRect | None = None
        self._insert_span_resolver: Callable[[str, str], tuple[int, int] | None] | None = None
        self._insert_drag_ref: tuple[str, str] | None = None
        # Movers currently showing a shell-only placeholder (no drag opacity).
        self._dimmed_refs: set[UltraViewRef] = set()
        self._last_legal_ghosts: tuple[tuple[QImage | QPixmap | None, tuple[int, int, int, int]], ...] = ()
        self._last_legal_highlights: tuple[tuple[int, int, int, int], ...] = ()
        self.destroyed.connect(self._on_workspace_destroyed)

    def set_viewport_size(self, size: QSize) -> None:
        """Record the scroll viewport. Metrics use ``screen_grid_metrics``.

        Column width is the 1600-wide export column, not the window width, so
        card aspect stays put when the user resizes or toggles chrome.
        """
        if size == self._viewport_size:
            return
        self._stop_pointer_coalesce(drop=True)
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

    def set_workspace_extent(self, bounds: GridBounds | None) -> None:
        """Apply a runtime-only workspace origin/size without touching cards.

        ``bounds`` is intentionally not copied into ``UltraViewBoardState``.
        A ``None`` extent preserves the historical base-frame mapping, which
        keeps old callers and exported geometry unchanged.
        """
        wanted = bounds if bounds is not None and not bounds.empty() else None
        if wanted == self._workspace_extent:
            return
        old_origin = self._workspace_origin_offset()
        self._workspace_extent = wanted
        self._sync_metrics()
        self._nudge_live_gesture_for_origin_shift(old_origin)

    def workspace_extent(self) -> GridBounds | None:
        """Return the Page-owned runtime extent; never a persisted payload."""
        return self._workspace_extent

    def unzoomed_size(self) -> QSize:
        return self._workspace_size(self._base_metrics)

    def content_rect_1x(self) -> tuple[float, float, float, float] | None:
        """Union of cards and rendered author content at 1×.

        The live fit path uses this method, so author-only Boards and signed
        negative ink must not fall back to the ordinary empty-card frame.
        """
        return _union_pixel_rect(
            [
                *(
                    rect_to_pixels(
                        item.rect, self._base_metrics, self._workspace_origin_offset()
                    )
                    for item in self._placements.values()
                ),
                *self._author_pixel_rect(self._base_metrics),
            ]
        )

    def content_rect(self) -> tuple[float, float, float, float] | None:
        """Union of cards and rendered author content at the current zoom."""
        return _union_pixel_rect(
            [
                *(
                    rect_to_pixels(item.rect, self._metrics, self._workspace_origin_offset())
                    for item in self._placements.values()
                ),
                *self._author_pixel_rect(self._metrics),
            ]
        )

    def author_paint_layer(self) -> AuthorPaintLayer:
        """Return the transparent paint-only author projection layer."""
        return self._author_layer

    def author_text_editor(self) -> BoardTextEditor:
        """Return the direct-child IME-safe editor owned by this Board."""
        return self._author_text_editor

    def sticky_note_widget(self) -> StickyNoteWidget:
        """Return the sibling Sticky editor; never parented to the paint layer."""
        return self._sticky_note

    def set_creation_allowed(self, allowed: bool) -> None:
        """Page gates Sticky create for presentation / overview / template."""
        self._creation_allowed = bool(allowed)
        if not self._creation_allowed:
            self.hide_author_editor()
            if self._interaction.draft() is not None:
                self._interaction.cancel_draft()
                self._overlay.set_marquee(None)
            clear_laser_cursor_cache()
        self._reapply_pointer_cursor()

    def creation_allowed(self) -> bool:
        return self._creation_allowed

    def interaction(self) -> BoardInteractionController:
        """Single Board interaction owner. Selection/tool/draft live here."""
        return self._interaction

    def set_author_objects(
        self,
        objects: Sequence[object],
        *,
        theme: str = DEFAULT_THEME,
    ) -> None:
        """Project persisted author objects without taking mutation ownership."""
        self._author_objects = tuple(objects)
        self._author_theme = str(theme or DEFAULT_THEME)
        self._interaction.restrict_authors(
            {
                str(getattr(item, "object_id", ""))
                for item in self._author_objects
                if getattr(item, "object_id", None)
            }
        )
        self._sync_author_projection()

    def clear_author_selection(self) -> bool:
        """Clear author keys through the shared controller."""
        if not self._interaction.clear_author_keys():
            return False
        self._sync_author_projection()
        return True

    def author_selection_ids(self) -> frozenset[str]:
        return self._interaction.author_selection_ids()

    def hide_author_editor(self) -> bool:
        """Hide the IME editor without committing. Safe when nothing is editing."""
        hidden = False
        if self._sticky_note.is_editing():
            self._sticky_note.hide_edit()
            hidden = True
        editor = self._author_text_editor
        if editor.is_editing():
            editor.cancel()
            hidden = True
        self._interaction.set_editor_active(False)
        return hidden

    def reset_transient_interaction(self) -> None:
        """Board switch/clear: drop tool/selection/draft/hover; keep coalesce owner."""
        self.hide_author_editor()
        self._interaction.reset_session()
        self._apply_selection_flags()
        self._sync_author_projection()
        clear_laser_cursor_cache()
        self._reapply_pointer_cursor()

    def _author_pixel_rect(
        self, metrics: GridMetrics
    ) -> tuple[tuple[float, float, float, float], ...]:
        bounds = author_content_bounds(self._author_objects)
        if bounds.empty():
            return ()
        mapped = board_box_to_pixels(
            (
                float(bounds.column),
                float(bounds.row),
                float(bounds.column_span),
                float(bounds.row_span),
            ),
            metrics,
            origin_offset=self._workspace_origin_offset(),
        )
        return () if mapped is None else (mapped,)

    def _sync_author_projection(self) -> None:
        boxes = []
        selected = self._interaction.author_selection_ids()
        if selected:
            for item in self._author_objects:
                if str(getattr(item, "object_id", "")) not in selected:
                    continue
                box = getattr(item, "box", None)
                if box is not None:
                    boxes.append((box.x, box.y, box.width, box.height))
        self._author_layer.set_model(
            AuthorLayerModel(
                objects=self._author_objects,
                metrics=self._metrics,
                origin_offset=self._workspace_origin_offset(),
                theme=self._author_theme,
                selection_boxes=tuple(boxes),
            )
        )
        self._author_layer.set_view_geometry(
            self._metrics,
            origin_offset=self._workspace_origin_offset(),
            zoom=self._zoom,
        )
        if self._author_text_editor.is_editing():
            self._author_text_editor.update_board_geometry(
                self._metrics,
                origin_offset=self._workspace_origin_offset(),
            )
        if self._sticky_note.is_editing():
            self._sticky_note.update_board_geometry(
                self._metrics,
                origin_offset=self._workspace_origin_offset(),
            )

    def set_preview_quality(self, quality: str) -> None:
        for card in self._widgets.values():
            card.set_preview_quality(quality)

    def set_default_insert_span(self, span: tuple[int, int]) -> None:
        """Set the board-state preset span used for external-card insertion."""
        try:
            column_span, row_span = int(span[0]), int(span[1])
        except (IndexError, TypeError, ValueError):
            column_span, row_span = 4, 3
        self._default_insert_span = (column_span, row_span)

    def set_insert_span_resolver(
        self,
        resolver: Callable[[str, str], tuple[int, int] | None] | None,
    ) -> None:
        """Board-local callback: (section, view_id) → insert span, or None.

        Used so the insert ghost, drop, and fitted card share one span when
        PreviewStore already has pixels. Layout moves ignore this and keep
        the card's current GridRect.
        """
        self._insert_span_resolver = resolver

    def zoom_anchor_at(self, point: tuple[float, float]) -> tuple[float, float]:
        """Canvas pixel → zoom-independent anchor, in signed workspace cells.

        The free-grid pixel map is ``padding(z) + index * pitch(z)`` with every
        term rounded independently, so it is a stair rather than ``pixel * z``.
        Extrapolating a wheel anchor linearly leaves an error proportional to
        the cell index, and the signed elastic origin pushes that index past
        40.  Anchoring in cells and re-projecting through the metrics actually
        laid out cancels the rounding on both sides.

        Cells are absolute (origin offset folded in) so the anchor survives an
        extent rebase between the two calls.
        """
        unit_x, unit_y = self._zoom_anchor_units()
        padding = self._metrics.exact_padding()
        origin_column, origin_row = self._workspace_origin_offset()
        return (
            origin_column + (float(point[0]) - padding) / unit_x,
            origin_row + (float(point[1]) - padding) / unit_y,
        )

    def point_for_zoom_anchor(self, anchor: tuple[float, float]) -> tuple[float, float]:
        """Inverse of :meth:`zoom_anchor_at` under the metrics now in effect."""
        unit_x, unit_y = self._zoom_anchor_units()
        padding = self._metrics.exact_padding()
        origin_column, origin_row = self._workspace_origin_offset()
        return (
            padding + (float(anchor[0]) - origin_column) * unit_x,
            padding + (float(anchor[1]) - origin_row) * unit_y,
        )

    def _zoom_anchor_units(self) -> tuple[float, float]:
        pitch_x, pitch_y = self._metrics.exact_pitch()
        return (max(1.0, pitch_x), max(1.0, pitch_y))

    def grid_anchor_at(self, pos: QPoint) -> GridAnchor:
        """Map a board-local pixel point to a desired card centre in cells."""
        unit_x, unit_y = self._zoom_anchor_units()
        padding = self._metrics.exact_padding()
        cell_w, cell_h = self._metrics.exact_cell()
        origin_column, origin_row = self._workspace_origin_offset()
        return GridAnchor(
            origin_column + (pos.x() - padding + (unit_x - cell_w) / 2.0) / unit_x,
            origin_row + (pos.y() - padding + (unit_y - cell_h) / 2.0) / unit_y,
        )

    def metrics(self) -> GridMetrics:
        return self._metrics

    def gesture(self) -> FreeGridGesture:
        return self._gesture

    def ghost_overlay(self) -> ViewportFeedbackSurface:
        return self._overlay

    def bind_feedback_surface(self, viewport: QWidget) -> None:
        """Reparent the FreeGrid feedback surface onto the scroll viewport."""
        self._overlay.bind_transform_host(self, viewport)

    def feedback_pipeline_counts(self) -> dict[str, int]:
        overlay = self._overlay
        return {
            "planner": int(self._diag_planner_calls),
            "presents": int(getattr(overlay, "present_count", self._diag_frame_presents)),
            "paints": int(getattr(overlay, "paint_count", 0)),
            "generation": int(getattr(overlay, "generation", self._feedback_generation)),
            "gesture_id": int(getattr(overlay, "gesture_id", 0)),
            "layout_revision": int(self._layout_revision),
        }

    def interaction_facts(self) -> dict[str, bool]:
        """Qt-free flags Page needs without reading private session dicts."""
        gesture = self._gesture
        return {
            "author_geometry_active": self._author_geometry_session is not None,
            "gesture_armed": bool(gesture.is_armed()),
            "gesture_active": bool(gesture.is_active()),
            "marquee_active": gesture.marquee() is not None,
        }

    def workspace_safety_blocked(self) -> bool:
        """True when the live candidate would leave ``safety_grid_bounds()``."""
        session = self._gesture.session()
        if session is None:
            return False
        if session.plan is not None:
            return session.plan.reason is LayoutRejectReason.OUT_OF_BOUNDS
        return (not session.legal) and session.plan is None and session.is_group_move()

    def set_workspace_edge_hint(
        self,
        *,
        continue_sides: Sequence[str] = (),
        copy: str = "",
        viewport_rect: QRect | None = None,
    ) -> None:
        """Page-owned continuation fade. Safety wall is set from the resolver."""
        if self.workspace_safety_blocked():
            continue_sides = ()
            copy = ""
        self._overlay.set_continue_hint(continue_sides, copy, viewport_rect)

    def clear_workspace_edge_hint(self) -> None:
        self._overlay.set_continue_hint()
        if not self.workspace_safety_blocked() and self.cursor().shape() == Qt.ForbiddenCursor:
            self.unsetCursor()

    def reproject_after_viewport_change(self, global_pos: QPoint | None) -> None:
        """Re-resolve the live candidate after a real scroll/extent/origin change.

        Ordinary mouse-move presentation does not come through this entry.
        """
        if global_pos is None:
            return
        local = self.mapFromGlobal(QPoint(global_pos))
        if self._gesture.is_armed():
            keep_aspect = bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)
            self._ingest_pointer_sample(
                self._logical_board_pos((local.x(), local.y())),
                keep_aspect=keep_aspect,
                global_pos=QPoint(global_pos),
            )
            return
        if self._gesture.marquee() is not None:
            self._gesture.update_marquee((local.x(), local.y()))
            self._overlay.set_marquee(self._gesture.marquee_rect())
            self._emit_workspace_gesture(True, QPoint(global_pos))
            return
        if self._workspace_gesture_active:
            card = self._card_at(local)
            if card is None:
                self._replace.hover(None)
                self._show_insert_preview(local)
            else:
                key = f"{card.model().section}/{card.model().view_id}"
                self._replace.hover(key)
                if self._replace.is_armed(key):
                    self._clear_insert_preview()
                else:
                    self._show_insert_preview(local)
            self._emit_workspace_gesture(True, QPoint(global_pos))

    def _nudge_live_gesture_for_origin_shift(
        self, old_origin: tuple[int, int]
    ) -> None:
        """Keep in-flight widgets/marquee aligned when extent grows left/up."""
        if not self._gesture.is_armed() and self._gesture.marquee() is None:
            return
        new_origin = self._workspace_origin_offset()
        if new_origin == old_origin:
            return
        old_x, old_y = self._workspace_origin_pixels(old_origin)
        new_x, new_y = self._workspace_origin_pixels(new_origin)
        dx = old_x - new_x
        dy = old_y - new_y
        if dx == 0 and dy == 0:
            return
        for widget in self._widgets.values():
            widget.move(widget.x() + dx, widget.y() + dy)
        marquee = self._gesture.marquee()
        if marquee is not None:
            marquee.origin = (marquee.origin[0] + dx, marquee.origin[1] + dy)
            marquee.current = (marquee.current[0] + dx, marquee.current[1] + dy)
            self._overlay.set_marquee(self._gesture.marquee_rect())
        self._last_consumed_candidate_fingerprint = None
        self._reproject_live_preview()

    def _workspace_origin_offset(self) -> tuple[int, int]:
        bounds = self._workspace_extent
        if bounds is None:
            return 0, 0
        return bounds.column, bounds.row

    def _workspace_size(self, metrics: GridMetrics) -> QSize:
        """Pixel size of the transient extent at ``metrics`` scale."""
        bounds = self._workspace_extent
        if bounds is None:
            return QSize(metrics.board_width, metrics.board_height)
        columns = max(1, bounds.column_span)
        rows = max(1, bounds.row_span)
        padding = metrics.exact_padding()
        pitch_x, pitch_y = metrics.exact_pitch()
        cell_w, cell_h = metrics.exact_cell()
        width = 2 * padding + (columns - 1) * pitch_x + cell_w
        height = 2 * padding + (rows - 1) * pitch_y + cell_h
        return QSize(int(round(width)), int(round(height)))

    def _workspace_origin_pixels(
        self, origin: tuple[int, int] | None = None
    ) -> tuple[int, int]:
        """Pixel offset between the canonical grid plane and this widget's.

        Rounded once, from the unrounded pitch, so the two translations below
        stay exact inverses of each other. They may sit a pixel off a card that
        ``rect_to_pixels`` placed directly, which only ever moves a translucent
        ghost, never a committed card.
        """
        origin_column, origin_row = (
            self._workspace_origin_offset() if origin is None else origin
        )
        pitch_x, pitch_y = self._metrics.exact_pitch()
        return (
            int(round(origin_column * pitch_x)),
            int(round(origin_row * pitch_y)),
        )

    def _logical_board_pos(self, local: tuple[int, int]) -> tuple[int, int]:
        """Translate workspace-local pixels back to the canonical grid plane."""
        offset_x, offset_y = self._workspace_origin_pixels()
        return (int(local[0]) + offset_x, int(local[1]) + offset_y)

    def _workspace_pixel_rect(self, logical_rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Translate a canonical-grid pixel rect into this widget's local plane."""
        offset_x, offset_y = self._workspace_origin_pixels()
        return (
            int(logical_rect[0]) - offset_x,
            int(logical_rect[1]) - offset_y,
            int(logical_rect[2]),
            int(logical_rect[3]),
        )

    def _emit_workspace_gesture(
        self, active: bool, global_pos: QPoint | None = None
    ) -> None:
        """Publish gesture lifetime and, separately, the latest pointer."""
        wanted = bool(active)
        gesture_id = int(self._gesture.gesture_id() or 0)
        if not wanted:
            if not self._workspace_gesture_active:
                return
            self._workspace_gesture_active = False
            self.workspace_gesture_active_changed.emit(False, gesture_id)
            self.workspace_gesture_changed.emit(False, None)
            return
        started = not self._workspace_gesture_active
        self._workspace_gesture_active = True
        if started:
            if gesture_id <= 0:
                gesture_id = int(self._gesture.gesture_id() or 1)
            self.workspace_gesture_active_changed.emit(True, gesture_id)
            self.workspace_gesture_changed.emit(
                True, QPoint(global_pos) if global_pos else None
            )
        if global_pos is not None:
            self.workspace_pointer_changed.emit(
                gesture_id or int(self._gesture.gesture_id() or 0),
                QPoint(global_pos),
            )

    def _on_workspace_destroyed(self, _object=None) -> None:
        # QObject teardown can arrive after child deletion.  Emitting the
        # lifetime end is safe and lets Page stop an edge timer it owns.
        clear_laser_cursor_cache()
        self._stop_pointer_coalesce(drop=True)
        self.hide_author_editor()
        self._interaction.reset_session()
        if not self._workspace_gesture_active:
            return
        self._workspace_gesture_active = False
        try:
            self.workspace_gesture_active_changed.emit(False, int(self._gesture.gesture_id() or 0))
            self.workspace_gesture_changed.emit(False, None)
        except RuntimeError:
            # Qt may already have torn down this wrapper; no live receiver can
            # remain on it, and Page also cancels on hide/deactivation.
            pass

    def cancel_gesture(self) -> bool:
        self._stop_pointer_coalesce(drop=True)
        cancelled = False
        if self._insert_preview_rect is not None:
            self._clear_insert_preview()
            self._replace.clear()
            cancelled = True
        if self._pending_shift_toggle is not None:
            self._pending_shift_toggle = None
            cancelled = True
        if self._interaction.draft() is not None:
            self._interaction.cancel_draft()
            self._overlay.set_marquee(None)
            self.hide_author_editor()
            cancelled = True
        if self._author_geometry_session is not None:
            self._author_geometry_session = None
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
        self._last_legal_ghosts = ()
        self._last_legal_highlights = ()
        self._last_pointer_sample = None
        self._last_consumed_candidate_fingerprint = None
        self._overlay.clear_edge_hint()
        self._emit_workspace_gesture(False)
        return cancelled

    def sync_selection_projection(self) -> None:
        """Refresh card/author chrome from the shared controller."""
        self._apply_selection_flags()

    def select_only(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        self._interaction.select_only_card(ref)
        self._apply_selection_flags()

    def clear_selection(self) -> bool:
        changed = self._interaction.clear_selection()
        if not changed:
            return False
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
        self._stop_pointer_coalesce(drop=True)
        self._ghost_buffers.clear()
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
        geom = self.rect()
        if self._author_layer.geometry() != geom:
            self._author_layer.setGeometry(geom)
        parent = self._overlay.parentWidget()
        if parent is self and self._overlay.geometry() != geom:
            self._overlay.setGeometry(geom)
        elif parent is not None and parent is not self:
            self._overlay.sync_host_geometry()
        self._author_layer.raise_()
        self._sync_editor_exclusion()
        if parent is self:
            self._overlay._raise_for_stack()
        if self._author_text_editor.is_editing():
            self._author_text_editor.raise_()
        if self._sticky_note.is_editing():
            self._sticky_note.raise_()

    def _sync_editor_exclusion(self) -> None:
        rect = None
        if self._author_text_editor.is_editing():
            rect = self._author_text_editor.geometry()
        elif self._sticky_note.is_editing():
            rect = self._sticky_note.geometry()
        self._overlay.set_editor_exclusion(rect)

    def _sync_metrics(self) -> None:
        self._base_metrics = screen_grid_metrics(list(self._placements.values()))
        self._metrics = scale_grid_metrics(self._base_metrics, self._zoom)
        target = self._workspace_size(self._metrics)
        if self.minimumSize() != target:
            self.setMinimumSize(target)
        if self.size() != target:
            self.resize(target)
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802
        armed = self._gesture.is_armed() or self._gesture.marquee() is not None
        if not armed:
            self._stop_pointer_coalesce(drop=True)
        super().resizeEvent(event)
        if armed:
            if self._author_layer.geometry() != self.rect():
                self._author_layer.setGeometry(self.rect())
            self._raise_overlay()
            self._last_consumed_candidate_fingerprint = None
            self._reproject_live_preview()
            return
        self._relayout()
        self._raise_overlay()

    def _relayout(self) -> None:
        if self._gesture.is_armed() or self._gesture.marquee() is not None:
            return
        self._sync_author_projection()
        for ref, placement in self._placements.items():
            widget = self._widgets.get(ref)
            if widget is not None:
                widget.setGeometry(
                    *rect_to_pixels(
                        placement.rect, self._metrics, self._workspace_origin_offset()
                    )
                )
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

    def _span_for_insert(
        self, section: str | None = None, view_id: str | None = None
    ) -> tuple[int, int]:
        """Fitted insert span when a resolver+ref is available, else default."""
        if section is None or view_id is None:
            if self._insert_drag_ref is not None:
                section, view_id = self._insert_drag_ref
        resolver = self._insert_span_resolver
        if callable(resolver) and section and view_id:
            resolved = resolver(str(section), str(view_id))
            if resolved is not None:
                try:
                    column_span, row_span = int(resolved[0]), int(resolved[1])
                except (IndexError, TypeError, ValueError):
                    column_span, row_span = 0, 0
                if column_span > 0 and row_span > 0:
                    return (column_span, row_span)
        return self._default_insert_span

    def _remember_insert_drag_ref(self, mime: QMimeData | None) -> None:
        extracted = extract_ref_strings(mime)
        if extracted is not None:
            self._insert_drag_ref = extracted

    def _insertion_rect_at(self, pos: QPoint) -> GridRect | None:
        return resolve_free_grid_insert_rect(
            tuple(self._placements.values()),
            span=self._span_for_insert(),
            anchor=self.grid_anchor_at(pos),
        )

    def _show_insert_preview(self, pos: QPoint) -> None:
        rect = self._insertion_rect_at(pos)
        self._insert_preview_rect = rect
        if rect is None:
            self._overlay.set_move_previews((), (), legal=False)
            return
        pixel_rect = rect_to_pixels(
            rect, self._metrics, self._workspace_origin_offset()
        )
        self._overlay.set_move_preview(
            None, pixel_rect, pixel_rect, legal=True, badge=""
        )

    def _clear_insert_preview(self) -> None:
        self._insert_preview_rect = None
        self._overlay.set_move_previews((), (), legal=True)

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
        self._sync_author_projection()

    def _sync_selection_handles(self) -> None:
        if (
            self._gesture.is_armed()
            or self._gesture.is_active()
            or self._gesture.marquee() is not None
        ):
            return
        rects = []
        for ref in self._gesture.selection():
            widget = self._widgets.get(ref)
            if widget is None:
                continue
            geom = widget.geometry()
            rects.append((geom.x(), geom.y(), geom.width(), geom.height()))
        origin = self._workspace_origin_offset()
        for item in self._author_objects:
            object_id = str(getattr(item, "object_id", "") or "")
            if object_id not in self._interaction.author_selection_ids():
                continue
            box = getattr(item, "box", None)
            if box is None:
                continue
            mapped = board_box_to_pixels(
                (box.x, box.y, box.width, box.height),
                self._metrics,
                origin_offset=origin,
            )
            if mapped is not None:
                rects.append(self._pixel_box(mapped))
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
                board_pos = self._logical_board_pos(
                    self._board_pos(card, event.pos())
                )
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
            self._interaction.select_only_card(ref)
        handle = None
        if already_selected and len(self._gesture.selection()) == 1:
            handle = hit_handle(
                (0, 0, card.width(), card.height()),
                (event.pos().x(), event.pos().y()),
            )
        board_pos = self._logical_board_pos(self._board_pos(card, event.pos()))
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
        self._apply_selection_flags()

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
        if not self._gesture.is_armed():
            return
        self._ingest_pointer_sample(
            self._logical_board_pos(self._board_pos(card, event.pos())),
            keep_aspect=bool(event.modifiers() & Qt.ShiftModifier),
            global_pos=event.globalPos(),
        )

    def handle_card_mouse_release(self, card: FreeGridCard, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._finish_pending_shift_toggle():
            return
        if self._gesture.is_armed():
            self._ingest_pointer_sample(
                self._logical_board_pos(self._board_pos(card, event.pos())),
                keep_aspect=bool(event.modifiers() & Qt.ShiftModifier),
                global_pos=event.globalPos(),
            )
            self._flush_pointer_sample()
        self._finish_gesture(commit=True, global_pos=event.globalPos())

    def _finish_pending_shift_toggle(self) -> bool:
        ref = self._pending_shift_toggle
        self._pending_shift_toggle = None
        if ref is None:
            return False
        self._interaction.toggle_card(ref)
        self._apply_selection_flags()
        return True

    def sync_tool_cursor(self) -> None:
        self._sync_tool_cursor()

    def pointer_cursor(self) -> QCursor | None:
        """Cursor projected by Pointer mode onto the scroll viewport."""
        if self._creation_allowed and self._interaction.is_laser_active():
            return laser_pointer_cursor(dpr=_effective_device_pixel_ratio(self))
        return None

    def _reapply_pointer_cursor(self) -> None:
        """Rebuild or unset Laser on this Board and the Page viewport if present."""
        if sip.isdeleted(self):
            return
        page = _page_of(self)
        sync = getattr(page, "_sync_tool_cursor", None) if page is not None else None
        if callable(sync):
            try:
                sync()
                return
            except RuntimeError:
                pass
        self._sync_tool_cursor()

    def event(self, event) -> bool:  # noqa: N802
        if event.type() in LASER_CURSOR_DPR_CHANGE_EVENTS:
            clear_laser_cursor_cache()
            self._reapply_pointer_cursor()
        return super().event(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        clear_laser_cursor_cache()
        self.unsetCursor()
        self._unset_page_viewport_cursor()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._reapply_pointer_cursor()

    def _unset_page_viewport_cursor(self) -> None:
        try:
            page = _page_of(self)
        except RuntimeError:
            return
        getter = getattr(page, "board_scroll_area", None) if page is not None else None
        try:
            area = getter() if callable(getter) else None
        except RuntimeError:
            return
        if area is None:
            return
        try:
            area.viewport().unsetCursor()
        except RuntimeError:
            return

    def _sticky_create_armed(self) -> bool:
        return (
            self._creation_allowed
            and self._interaction.active_tool() == TOOL_STICKY
            and not self._interaction.is_editor_active()
        )

    def _sync_tool_cursor(self) -> None:
        if self._sticky_create_armed():
            self.setCursor(Qt.CrossCursor)
        elif (cursor := self.pointer_cursor()) is not None:
            self.setCursor(cursor)
        else:
            self.unsetCursor()

    def _pixel_to_board_point(self, pos: QPoint) -> tuple[float, float] | None:
        return pixels_to_board_point(
            (float(pos.x()), float(pos.y())),
            self._metrics,
            origin_offset=self._workspace_origin_offset(),
        )

    def _author_item(self, object_id: str):
        for item in self._author_objects:
            if str(getattr(item, "object_id", "") or "") == object_id:
                return item
        return None

    def _draft_pixel_rect(self) -> tuple[int, int, int, int] | None:
        draft = self._interaction.draft()
        if draft is None or draft.origin is None:
            return None
        box = sticky_box_from_points(draft.origin, draft.current)
        mapped = board_box_to_pixels(box, self._metrics, origin_offset=self._workspace_origin_offset())
        if mapped is None:
            return None
        return self._pixel_box(mapped)

    def _pixel_box(
        self, mapped: tuple[float, float, float, float]
    ) -> tuple[int, int, int, int]:
        x, y, width, height = mapped
        return (
            int(round(x)),
            int(round(y)),
            max(1, int(round(width))),
            max(1, int(round(height))),
        )

    def route_card_press(self, card: FreeGridCard, event: QMouseEvent) -> bool:
        """I3: author objects above a card consume the press before card drag."""
        mapped = QPoint(*self._board_pos(card, event.pos()))
        self._close_sticky_editor_if_outside(mapped)
        hit = self.classify_press(mapped, modifiers=event.modifiers())
        if hit.kind == HIT_RESIZE_HANDLE and isinstance(hit.item, AuthorKey):
            self._begin_selected_author_handle(hit, event, mapped)
            return True
        if hit.kind != HIT_AUTHOR:
            return False
        self._handle_author_press(hit, event, mapped)
        return True

    def _close_sticky_editor_if_outside(self, pos: QPoint) -> None:
        if not self._sticky_note.is_editing():
            return
        if self._sticky_note.geometry().contains(pos):
            return
        self._commit_or_cancel_sticky_editor()

    def _commit_or_cancel_sticky_editor(self) -> None:
        if not self._sticky_note.is_editing():
            return
        if not str(self._sticky_note.current_text() or "").strip():
            self._sticky_note.cancel()
            return
        self._sticky_note.commit()

    def _handle_author_press(
        self, hit: HitTarget, event: QMouseEvent, pos: QPoint
    ) -> None:
        if not isinstance(hit.item, AuthorKey):
            return
        item = self._author_item(hit.item.object_id)
        additive = bool(event.modifiers() & Qt.ShiftModifier)
        if additive:
            self._interaction.toggle(hit.item)
            self._apply_selection_flags()
            return
        self._interaction.select_only(hit.item)
        self._apply_selection_flags()
        if item is not None and bool(getattr(item, "locked", False)):
            self.feedback_requested.emit(text_for_key(AUTHOR_LOCKED))
            return
        if item is None or not isinstance(item, (StickyObject, TextObject, ShapeObject)):
            return
        self._begin_box_geometry(item, pos, handle=None)

    def _begin_selected_author_handle(
        self, hit: HitTarget, event: QMouseEvent, pos: QPoint
    ) -> None:
        if not isinstance(hit.item, AuthorKey):
            return
        item = self._author_item(hit.item.object_id)
        if item is None or bool(getattr(item, "locked", False)):
            if item is not None:
                self.feedback_requested.emit(text_for_key(AUTHOR_LOCKED))
            return
        handle = str(hit.handle or "")
        if isinstance(item, ConnectorObject):
            page = _page_of(self)
            starter = getattr(page, "_begin_connector_geometry", None)
            if callable(starter):
                starter((handle, item.object_id), event, pos)
            return
        if isinstance(item, (StickyObject, TextObject, ShapeObject)):
            self._begin_box_geometry(item, pos, handle=handle)

    def _begin_box_geometry(self, item, pos: QPoint, *, handle: str | None) -> None:
        box = getattr(item, "box", None)
        if box is None:
            return
        board_point = self._pixel_to_board_point(pos)
        min_w, min_h = self._author_min_size(item)
        self._author_geometry_session = {
            "object_id": item.object_id,
            "kind": "resize" if handle else "move",
            "handle": handle,
            "origin": board_point,
            "box": (box.x, box.y, box.width, box.height),
            "min_width": min_w,
            "min_height": min_h,
        }
        if QWidget.mouseGrabber() is None:
            self.grabMouse()

    def _author_min_size(self, item) -> tuple[float, float]:
        if isinstance(item, TextObject):
            return TEXT_MIN_WIDTH, TEXT_MIN_HEIGHT
        if isinstance(item, ShapeObject):
            return SHAPE_MIN_WIDTH, SHAPE_MIN_HEIGHT
        return STICKY_MIN_WIDTH, STICKY_MIN_HEIGHT

    def _begin_sticky_draft(self, pos: QPoint) -> None:
        origin = self._pixel_to_board_point(pos)
        if origin is None:
            return
        self._interaction.begin_draft(
            TOOL_STICKY, origin=origin, object_id=new_author_object_id()
        )
        self._overlay.set_marquee(self._draft_pixel_rect())
        self._emit_workspace_gesture(True)

    def _update_sticky_draft(self, pos: QPoint) -> None:
        current = self._pixel_to_board_point(pos)
        self._interaction.update_draft(current)
        rect = self._draft_pixel_rect()
        if rect is not None:
            self._overlay.set_marquee(rect)

    def _finish_sticky_draft(self) -> None:
        draft = self._interaction.draft()
        self._release_mouse_if_grabbed()
        self._overlay.set_marquee(None)
        self._emit_workspace_gesture(False)
        if draft is None or draft.origin is None or draft.object_id is None:
            self._interaction.cancel_draft()
            return
        box = sticky_box_from_points(draft.origin, draft.current)
        item = StickyObject(
            draft.object_id,
            "sticky",
            box=BoardBox(*box),
            text="",
            palette=str(draft.palette or DEFAULT_STICKY_PALETTE),
        )
        self._sticky_note.apply_object(
            item,
            self._metrics,
            origin_offset=self._workspace_origin_offset(),
            theme=self._author_theme,
        )
        self._interaction.set_editor_active(True)
        self._sticky_note.begin_edit()
        self._raise_overlay()

    def _begin_sticky_edit(self, item) -> None:
        if not isinstance(item, StickyObject):
            return
        if bool(getattr(item, "locked", False)):
            self.feedback_requested.emit(text_for_key(AUTHOR_LOCKED))
            return
        self._sticky_note.apply_object(
            item,
            self._metrics,
            origin_offset=self._workspace_origin_offset(),
            theme=self._author_theme,
        )
        self._interaction.set_editor_active(True)
        self._sticky_note.begin_edit()
        self._raise_overlay()

    def _on_sticky_text_committed(self, object_id: str, text: str) -> None:
        draft = self._interaction.draft()
        pending = draft is not None and draft.object_id == object_id
        self._sticky_note.hide_edit()
        self._interaction.set_editor_active(False)
        cleaned = str(text or "")
        if pending:
            if not cleaned.strip():
                self._interaction.cancel_draft()
                self._sync_tool_cursor()
                return
            box = sticky_box_from_points(draft.origin or (0.0, 0.0), draft.current)
            self._interaction.commit_draft()
            self.author_create_requested.emit(
                AuthorCreateIntent(
                    TOOL_STICKY,
                    object_id,
                    box,
                    cleaned,
                    str(draft.palette or DEFAULT_STICKY_PALETTE),
                )
            )
            self._sync_tool_cursor()
            return
        self.author_update_requested.emit(AuthorUpdateIntent(object_id, text=cleaned))

    def _on_sticky_edit_cancelled(self, object_id: str) -> None:
        draft = self._interaction.draft()
        self._interaction.set_editor_active(False)
        if draft is not None and draft.object_id == object_id:
            self._interaction.cancel_draft()
        self._sync_tool_cursor()

    def _update_author_geometry(self, pos: QPoint) -> None:
        session = self._author_geometry_session
        if not session or session.get("origin") is None:
            return
        current = self._pixel_to_board_point(pos)
        if current is None:
            return
        ox, oy = session["origin"]  # type: ignore[misc]
        x, y, width, height = session["box"]  # type: ignore[misc]
        dx = current[0] - ox
        dy = current[1] - oy
        handle = session.get("handle")
        min_w = float(session.get("min_width") or STICKY_MIN_WIDTH)
        min_h = float(session.get("min_height") or STICKY_MIN_HEIGHT)
        if session.get("kind") == "move" or not handle:
            box = clamp_author_box(
                x + dx, y + dy, width, height, min_width=min_w, min_height=min_h
            )
        else:
            box = self._resize_author_box(
                (x, y, width, height), str(handle), dx, dy, min_width=min_w, min_height=min_h
            )
        mapped = board_box_to_pixels(box, self._metrics, origin_offset=self._workspace_origin_offset())
        if mapped is not None:
            self._overlay.set_selection_rects((self._pixel_box(mapped),), handles=True)

    def _resize_author_box(
        self,
        box: tuple[float, float, float, float],
        handle: str,
        dx: float,
        dy: float,
        *,
        min_width: float = STICKY_MIN_WIDTH,
        min_height: float = STICKY_MIN_HEIGHT,
    ) -> tuple[float, float, float, float]:
        x, y, width, height = box
        x2, y2 = x + width, y + height
        if "w" in handle:
            x = x + dx
        if "e" in handle:
            x2 = x2 + dx
        if "n" in handle:
            y = y + dy
        if "s" in handle:
            y2 = y2 + dy
        return clamp_author_box(
            min(x, x2),
            min(y, y2),
            abs(x2 - x),
            abs(y2 - y),
            min_width=min_width,
            min_height=min_height,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        was_editing = self._sticky_note.is_editing() or self._author_text_editor.is_editing()
        self._close_sticky_editor_if_outside(event.pos())
        if was_editing:
            event.accept()
            return
        hit = self.classify_press(
            event.pos(),
            modifiers=event.modifiers(),
            viewport_pan=False,
        )
        if hit.kind == HIT_RESIZE_HANDLE and isinstance(hit.item, AuthorKey):
            page = _page_of(self)
            if page is not None:
                page.notify_canvas_click()
            self._begin_selected_author_handle(hit, event, event.pos())
            event.accept()
            return
        if hit.kind == HIT_AUTHOR:
            page = _page_of(self)
            if page is not None:
                page.notify_canvas_click()
            self._handle_author_press(hit, event, event.pos())
            event.accept()
            return
        if self._card_at(event.pos()) is not None:
            super().mousePressEvent(event)
            return
        page = _page_of(self)
        if page is not None:
            page.notify_canvas_click()
        if self._sticky_create_armed() and hit.kind == HIT_BLANK:
            self._begin_sticky_draft(event.pos())
            event.accept()
            return
        additive = bool(event.modifiers() & Qt.ShiftModifier)
        if not additive:
            if page is not None:
                page.clear_card_selection()
            elif self._interaction.selection():
                self._interaction.clear_selection()
                self._apply_selection_flags()
        self._gesture.begin_marquee((event.pos().x(), event.pos().y()), additive)
        self._overlay.set_marquee(self._gesture.marquee_rect())
        self._emit_workspace_gesture(True, event.globalPos())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        grabbed = QWidget.mouseGrabber() is self
        if self._interaction.draft() is not None and (
            event.buttons() & Qt.LeftButton or grabbed
        ):
            self._update_sticky_draft(event.pos())
            return
        if self._author_geometry_session is not None and (
            event.buttons() & Qt.LeftButton or grabbed
        ):
            self._update_author_geometry(event.pos())
            return
        if self._gesture.marquee() is not None and (
            event.buttons() & Qt.LeftButton or grabbed
        ):
            self._gesture.update_marquee((event.pos().x(), event.pos().y()))
            self._overlay.set_marquee(self._gesture.marquee_rect())
            self._emit_workspace_gesture(True, event.globalPos())
            if QWidget.mouseGrabber() is None:
                self.grabMouse()
            return
        if self._gesture.is_armed() and (event.buttons() & Qt.LeftButton or grabbed):
            self._ingest_pointer_sample(
                self._logical_board_pos((event.pos().x(), event.pos().y())),
                keep_aspect=bool(event.modifiers() & Qt.ShiftModifier),
                global_pos=event.globalPos(),
            )
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._interaction.draft() is not None:
            self._update_sticky_draft(event.pos())
            self._finish_sticky_draft()
            return
        if event.button() == Qt.LeftButton and self._author_geometry_session is not None:
            self._update_author_geometry(event.pos())
            self._finish_author_geometry(event.pos())
            return
        if event.button() == Qt.LeftButton and self._gesture.marquee() is not None:
            session = self._gesture.take_marquee()
            self._release_mouse_if_grabbed()
            self._overlay.set_marquee(None)
            self._emit_workspace_gesture(False)
            if session is not None:
                self._finish_marquee(session)
            self.setFocus(Qt.OtherFocusReason)
            return
        if event.button() == Qt.LeftButton and self._finish_pending_shift_toggle():
            return
        if self._gesture.is_armed() and event.button() == Qt.LeftButton:
            self._ingest_pointer_sample(
                self._logical_board_pos((event.pos().x(), event.pos().y())),
                keep_aspect=bool(event.modifiers() & Qt.ShiftModifier),
                global_pos=event.globalPos(),
            )
            self._flush_pointer_sample()
            self._finish_gesture(commit=True, global_pos=event.globalPos())
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        hit = self.classify_press(event.pos(), modifiers=event.modifiers())
        if hit.kind == HIT_AUTHOR and isinstance(hit.item, AuthorKey):
            item = self._author_item(hit.item.object_id)
            if isinstance(item, StickyObject):
                self._begin_sticky_edit(item)
            else:
                self.author_edit_requested.emit(hit.item.object_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.handle_selection_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def handle_selection_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key not in (Qt.Key_Delete, Qt.Key_Backspace):
            return False
        author_ids = tuple(self._interaction.author_selection_ids())
        if author_ids:
            locked = any(
                bool(getattr(self._author_item(object_id), "locked", False))
                for object_id in author_ids
            )
            if locked:
                self.feedback_requested.emit(text_for_key(AUTHOR_LOCKED))
                return True
            self.author_delete_requested.emit(AuthorDeleteIntent(author_ids))
            return True
        refs = [ref for ref in self._gesture.selection() if ref in self._widgets]
        if not refs:
            return False
        for ref in refs:
            if key == Qt.Key_Delete:
                self.remove_ref_requested.emit(ref.section, ref.view_id)
            else:
                self.move_to_unplaced_requested.emit(ref.section, ref.view_id)
        return True

    def _finish_author_geometry(self, pos: QPoint) -> None:
        session = self._author_geometry_session
        if not session or session.get("origin") is None:
            self._author_geometry_session = None
            self._release_mouse_if_grabbed()
            self._sync_selection_handles()
            return
        current = self._pixel_to_board_point(pos)
        origin = session["origin"]
        box = session["box"]
        self._author_geometry_session = None
        self._release_mouse_if_grabbed()
        if current is None:
            self._sync_selection_handles()
            return
        dx = current[0] - origin[0]
        dy = current[1] - origin[1]
        handle = session.get("handle")
        x, y, width, height = box  # type: ignore[misc]
        min_w = float(session.get("min_width") or STICKY_MIN_WIDTH)
        min_h = float(session.get("min_height") or STICKY_MIN_HEIGHT)
        if session.get("kind") == "resize" and handle:
            next_box = self._resize_author_box(
                (x, y, width, height),
                str(handle),
                dx,
                dy,
                min_width=min_w,
                min_height=min_h,
            )
        else:
            next_box = clamp_author_box(
                x + dx, y + dy, width, height, min_width=min_w, min_height=min_h
            )
        object_id = str(session.get("object_id") or "")
        if next_box != (x, y, width, height) and object_id:
            item = self._author_item(object_id)
            if isinstance(item, TextObject):
                self.author_update_requested.emit(TextUpdateIntent(object_id, box=next_box))
            elif isinstance(item, ShapeObject):
                self.author_update_requested.emit(ShapeUpdateIntent(object_id, box=next_box))
            else:
                self.author_update_requested.emit(AuthorUpdateIntent(object_id, box=next_box))
        self._sync_selection_handles()

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

    def _pointer_sample_tuple(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> tuple[tuple[int, int], bool, QPoint | None]:
        return (
            (int(board_pos[0]), int(board_pos[1])),
            bool(keep_aspect),
            QPoint(global_pos) if global_pos is not None else None,
        )

    def _ingest_pointer_sample(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> None:
        sample = self._pointer_sample_tuple(
            board_pos, keep_aspect=keep_aspect, global_pos=global_pos
        )
        self._latest_pointer_sample = sample
        self._last_pointer_sample = sample
        if global_pos is not None and self._workspace_gesture_active:
            self.workspace_pointer_changed.emit(
                int(self._gesture.gesture_id() or 0),
                QPoint(global_pos),
            )
        session = self._gesture.session()
        if session is None or not session.active:
            # Crossing the drag threshold must paint this frame. Later
            # pointer events overwrite latest_sample and wait for the 0 ms
            # coalescer so one display frame consumes one sample.
            self._flush_pointer_sample()
            return
        if getattr(self, "_gesture_presenting", False):
            self._schedule_pointer_coalesce()
            return
        self._schedule_pointer_coalesce()

    def _queue_pointer_sample(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> None:
        sample = self._pointer_sample_tuple(
            board_pos, keep_aspect=keep_aspect, global_pos=global_pos
        )
        self._latest_pointer_sample = sample
        self._last_pointer_sample = sample
        self._schedule_pointer_coalesce()

    def _schedule_pointer_coalesce(self) -> None:
        timer = getattr(self, "_pointer_coalesce_timer", None)
        if timer is None:
            return
        try:
            if sip.isdeleted(timer):
                return
            if not timer.isActive():
                timer.start()
        except RuntimeError:
            return

    def _stop_pointer_coalesce(self, *, drop: bool) -> None:
        timer = getattr(self, "_pointer_coalesce_timer", None)
        if timer is not None:
            try:
                if not sip.isdeleted(timer):
                    timer.stop()
            except RuntimeError:
                pass
        if drop:
            self._latest_pointer_sample = None

    def _flush_pointer_sample(self) -> None:
        self._stop_pointer_coalesce(drop=False)
        self._consume_latest_pointer_sample()

    def _reproject_live_preview(self) -> None:
        """Re-draw the current sample after zoom/origin/overlay size changes."""
        if not self._gesture.is_active():
            return
        sample = self._latest_pointer_sample or self._last_pointer_sample
        if sample is None:
            return
        self._latest_pointer_sample = sample
        if getattr(self, "_gesture_presenting", False):
            self._schedule_pointer_coalesce()
            return
        self._flush_pointer_sample()

    def _consume_latest_pointer_sample(self) -> None:
        try:
            if sip.isdeleted(self):
                self._latest_pointer_sample = None
                return
        except RuntimeError:
            self._latest_pointer_sample = None
            return
        sample = self._latest_pointer_sample
        self._latest_pointer_sample = None
        if sample is None:
            return
        board_pos, keep_aspect, global_pos = sample
        self._update_gesture_at(
            board_pos, keep_aspect=keep_aspect, global_pos=global_pos
        )

    def _ghost_source_for(self, ref: UltraViewRef) -> QPixmap | QImage | None:
        cached = self._ghost_buffers.get(ref)
        if cached is not None:
            return cached
        card = self._widgets.get(ref)
        if card is None:
            return None
        raw = getattr(card, "_raw_image", None)
        if raw is None:
            return None
        dpr = _effective_device_pixel_ratio(card)
        width = max(1, int(round(max(card.width(), 1) * dpr)))
        height = max(1, int(round(max(card.height(), 1) * dpr)))
        source = getattr(card, "_source_pixmap", None)
        if source is None:
            source = QPixmap.fromImage(raw)
            card._source_pixmap = source
        scaled = source.scaled(
            width, height, Qt.KeepAspectRatio, Qt.FastTransformation
        )
        scaled.setDevicePixelRatio(dpr)
        self._ghost_buffers[ref] = scaled
        return scaled

    def _update_gesture_at(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> None:
        if getattr(self, "_gesture_presenting", False):
            self._latest_pointer_sample = self._pointer_sample_tuple(
                board_pos, keep_aspect=keep_aspect, global_pos=global_pos
            )
            self._last_pointer_sample = self._latest_pointer_sample
            self._schedule_pointer_coalesce()
            return
        session = self._gesture.update(
            board_pos,
            self._metrics,
            tuple(self._placements.values()),
            QApplication.startDragDistance(),
            keep_aspect=keep_aspect,
        )
        if session is None or not session.active:
            return
        fingerprint = self._gesture.candidate_fingerprint()
        if not session.plan_reused:
            self._diag_planner_calls += 1
        if (
            session.plan_reused
            and fingerprint is not None
            and fingerprint == self._last_consumed_candidate_fingerprint
            and self._overlay.is_showing()
        ):
            if global_pos is not None:
                self._emit_workspace_gesture(True, global_pos)
            return
        self._gesture_presenting = True
        try:
            self._present_live_gesture(session, board_pos, global_pos)
            self._last_consumed_candidate_fingerprint = fingerprint
        finally:
            self._gesture_presenting = False
            if self._latest_pointer_sample is not None:
                self._schedule_pointer_coalesce()

    def _present_live_gesture(
        self,
        session,
        board_pos: tuple[int, int],
        global_pos: QPoint | None,
    ) -> None:
        if QWidget.mouseGrabber() is None:
            self.grabMouse()
        first_live = not self._gesture_dimmed
        if first_live:
            self.drag_started.emit("layout")
            self._gesture_dimmed = True
            # Extent/edge-pan refresh must land as a pending sample, not a
            # dropped re-entrant present of the pre-origin coordinates.
            self._emit_workspace_gesture(True, global_pos)
        members = session.group_origins or {session.ref: session.origin}
        refs = list(session.preview_refs())
        for ref in refs:
            self._ghost_source_for(ref)
        ghosts = []
        ghost_rects = tuple(
            self._workspace_pixel_rect(rect)
            for rect in session.group_ghost_pixels(self._metrics, board_pos)
        )
        if len(ghost_rects) != len(refs):
            refs = [session.ref]
            ghost_rects = (
                self._workspace_pixel_rect(
                    session.ghost_pixels(self._metrics, board_pos)
                ),
            )
        mover_refs = set(members)
        displaced_count = 0
        safety = self._session_hits_safety(session)
        for ref, ghost in zip(refs, ghost_rects):
            image = self._ghost_source_for(ref)
            if session.legal:
                if ref in mover_refs:
                    role = PREVIEW_MOVER_VALID
                else:
                    role = PREVIEW_DISPLACED_WARNING
                    displaced_count += 1
            elif safety:
                role = PREVIEW_SAFETY_WALL
            else:
                role = PREVIEW_COLLISION_REJECT
            ghosts.append((image, ghost, role))
        highlights = tuple(
            self._workspace_pixel_rect(rect)
            for rect in session.group_highlight_pixels(self._metrics)
        )
        origin_masks = []
        involved = set(mover_refs)
        if session.plan is not None:
            involved.update(ref for ref, _rect in session.plan.preview_rects())
        for ref in involved:
            card = self._widgets.get(ref)
            if card is None:
                continue
            geom = card.geometry()
            origin_masks.append((geom.x(), geom.y(), geom.width(), geom.height()))
        if session.legal:
            self._last_legal_ghosts = tuple(ghosts)
            self._last_legal_highlights = highlights
        elif safety:
            # Only the mover leaving the safety wall keeps the last legal
            # ghost. A neighbour that cannot be pushed is a collision reject
            # and must keep the attempted red outline.
            ghosts, highlights = self._last_legal_preview(ghosts, highlights)
            displaced_count = sum(
                1
                for item in ghosts
                if len(item) > 2 and item[2] == PREVIEW_DISPLACED_WARNING
            )
        displace_copy = (
            format_displace_preview(displaced_count) if displaced_count else ""
        )
        self._feedback_generation += 1
        self._diag_frame_presents += 1
        self._sync_editor_exclusion()
        self._overlay.set_move_previews(
            ghosts,
            highlights,
            legal=session.legal,
            badge=session.badge(),
            handles=session.handle is not None,
            safety_wall=safety,
            safety_bounds=self._safety_bounds_pixel_rect() if safety else None,
            safety_sides=self._safety_sides_for(session.candidate) if safety else (),
            origin_masks=origin_masks,
            displace_copy=displace_copy,
            gesture_id=int(self._gesture.gesture_id() or 0),
            generation=self._feedback_generation,
            layout_revision=int(session.layout_revision),
            operation="resize" if session.handle is not None else "move",
            candidate_fingerprint=(
                self._workspace_origin_offset(),
                float(self._zoom),
                self._gesture.candidate_fingerprint(),
            ),
        )
        if safety:
            self.setCursor(Qt.ForbiddenCursor)
        elif self.cursor().shape() == Qt.ForbiddenCursor:
            self.unsetCursor()
        if not first_live:
            self._emit_workspace_gesture(True, global_pos)

    def _session_hits_safety(self, session) -> bool:
        """True only when the mover itself crossed the engineering bound.

        Pushing a neighbour out of the board is a collision reject, not a
        safety wall. The old OUT_OF_BOUNDS-for-any-rect test hid the red
        contact edge behind the last legal ghost.
        """
        if session.plan is None:
            return (not session.legal) and session.is_group_move()
        if session.plan.reason is not LayoutRejectReason.OUT_OF_BOUNDS:
            return False
        return clamp_rect(session.candidate) != session.candidate

    def _last_legal_preview(self, ghosts, highlights):
        if self._last_legal_highlights:
            return self._last_legal_ghosts, self._last_legal_highlights
        return ghosts, highlights

    def _safety_bounds_pixel_rect(self) -> QRect:
        bounds = safety_grid_bounds()
        rect = GridRect(
            bounds.column, bounds.row, bounds.column_span, bounds.row_span
        )
        x, y, width, height = rect_to_pixels(
            rect, self._metrics, self._workspace_origin_offset()
        )
        return QRect(x, y, width, height)

    def _safety_sides_for(self, rect: GridRect) -> tuple[str, ...]:
        safety = safety_grid_bounds()
        sides: list[str] = []
        if rect.column < safety.column:
            sides.append("left")
        if rect.column + rect.column_span > safety.column_end:
            sides.append("right")
        if rect.row < safety.row:
            sides.append("top")
        if rect.row + rect.row_span > safety.row_end:
            sides.append("bottom")
        return tuple(sides) or ("left",)

    def _sync_gesture_dim(self, wanted: set[UltraViewRef]) -> None:
        """Restore leftover placeholders. Live drag no longer hides card pixels.

        Origin wash, destination ghosts, and displaced previews all paint on
        the overlay so real cards are not frozen or cleared per frame.
        """
        for ref in self._dimmed_refs - wanted:
            card = self._widgets.get(ref)
            if card is not None:
                card.set_drag_placeholder(False)
        for ref in wanted - self._dimmed_refs:
            card = self._widgets.get(ref)
            if card is None:
                continue
            card.set_drag_placeholder(True)
        self._dimmed_refs = {ref for ref in wanted if ref in self._widgets}

    def _clear_gesture_dim(self) -> None:
        """Unconditional restore: whatever the board hid, the board restores."""
        for ref in self._dimmed_refs:
            card = self._widgets.get(ref)
            if card is not None:
                card.set_drag_placeholder(False)
                card.restore_dim()
        self._dimmed_refs = set()

    def _finish_gesture(self, *, commit: bool, global_pos: QPoint | None = None) -> None:
        self._stop_pointer_coalesce(drop=True)
        gesture_id = int(self._gesture.gesture_id() or 0)
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
            self._ghost_buffers.clear()
            for ref in restore_refs:
                card = self._widgets.get(ref)
                if card is not None:
                    card.set_drag_placeholder(False)
                    card.restore_dim()
                    card.unsetCursor()
            self._overlay.clear(gesture_id or None)
            if self.cursor().shape() == Qt.ForbiddenCursor:
                self.unsetCursor()
            self._sync_selection_handles()
            self._last_legal_ghosts = ()
            self._last_legal_highlights = ()
            self._last_pointer_sample = None
            self._last_consumed_candidate_fingerprint = None
            self._emit_workspace_gesture(False)
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
            self.feedback_requested.emit(format_rearranged(plan.affected_count()))
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
            if not visible.intersects(
                QRect(
                    *rect_to_pixels(
                        item.after, self._metrics, self._workspace_origin_offset()
                    )
                )
            )
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
            self._remember_insert_drag_ref(event.mimeData())
            self._emit_workspace_gesture(True, self.mapToGlobal(event.pos()))

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if not _accept_ultraview_drag(event):
            return
        event.acceptProposedAction()
        self._remember_insert_drag_ref(event.mimeData())
        self._emit_workspace_gesture(True, self.mapToGlobal(event.pos()))
        card = self._card_at(event.pos())
        if card is None:
            self._replace.hover(None)
            self._show_insert_preview(event.pos())
            return
        key = f"{card.model().section}/{card.model().view_id}"
        self._replace.hover(key)
        if self._replace.is_armed(key):
            self._clear_insert_preview()
            return
        self._show_insert_preview(event.pos())

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._insert_drag_ref = None
        self._clear_insert_preview()
        self._replace.clear()
        self._emit_workspace_gesture(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        ref = extract_ref_strings(event.mimeData())
        card = self._card_at(event.pos())
        event.acceptProposedAction()
        self._insert_drag_ref = None
        self._emit_workspace_gesture(False)
        if card is not None:
            key = f"{card.model().section}/{card.model().view_id}"
            if ref is not None and self._replace.is_armed(key):
                self.replace_requested.emit(
                    card.model().section, card.model().view_id, ref[0], ref[1]
                )
                self._clear_insert_preview()
                self._replace.clear()
                return
        anchor = self.grid_anchor_at(event.pos())
        self._clear_insert_preview()
        self._replace.clear()
        if ref is not None:
            self.insert_requested.emit(ref[0], ref[1], anchor)
            # Compatibility for callers that only observe the historical
            # ref-only event.  The production Page consumes ``insert_requested``.
            self.ref_dropped.emit(*ref)

    def _card_at(self, pos: QPoint) -> FreeGridCard | None:
        for widget in self._widgets.values():
            if widget.geometry().contains(pos):
                return widget
        return None

    def classify_press(
        self,
        pos: QPoint,
        *,
        modifiers=Qt.NoModifier,
        viewport_pan: bool = False,
        card: FreeGridCard | None = None,
        already_selected: bool = False,
    ) -> HitTarget:
        """Spec I3 routing skeleton. Author objects stay mouse-transparent."""
        del modifiers
        editor_active = bool(
            self._author_text_editor.is_editing() or self._interaction.is_editor_active()
        )
        handle = None
        handle_item = None
        card_key = None
        author_handle = self._selected_author_handle_at(pos)
        if author_handle is not None:
            handle, handle_item = author_handle
        target = card if card is not None else self._card_at(pos)
        if handle is None and target is not None:
            ref = parse_ref_payload(
                {"section": target.model().section, "view_id": target.model().view_id}
            )
            if ref is not None:
                card_key = CardKey(ref)
                selected = already_selected or ref in self._interaction.card_selection()
                if selected and len(self._interaction.card_selection()) == 1:
                    local = target.mapFrom(self, pos) if card is None else pos
                    handle = hit_handle(
                        (0, 0, target.width(), target.height()),
                        (local.x(), local.y()),
                    )
        elif target is not None:
            ref = parse_ref_payload(
                {"section": target.model().section, "view_id": target.model().view_id}
            )
            if ref is not None:
                card_key = CardKey(ref)
        author_hits = () if handle is not None and handle_item is not None else self._author_keys_at(pos)
        hit = resolve_board_hit(
            editor_active=editor_active,
            viewport_pan=bool(viewport_pan),
            resize_handle=handle,
            handle_item=handle_item,
            author_hits_rev_z=author_hits,
            card=card_key,
        )
        self._interaction.set_hover_target(hit.item)
        return hit

    def _selected_author_handle_at(self, pos: QPoint) -> tuple[str, AuthorKey] | None:
        """I3: selected author handles sit above body hits and cards."""
        ids = self._interaction.author_selection_ids()
        if not ids:
            return None
        origin = self._workspace_origin_offset()
        for item in reversed(self._author_objects):
            object_id = str(getattr(item, "object_id", "") or "")
            if object_id not in ids:
                continue
            if isinstance(item, ConnectorObject):
                handles = connector_handle_points(
                    (item.start.point.x, item.start.point.y),
                    (item.end.point.x, item.end.point.y),
                    route=item.route,
                    elbow_bias=item.elbow_bias,
                )
                mapped = {}
                for name, point in handles.items():
                    pixel = board_point_to_pixels(point, self._metrics, origin_offset=origin)
                    if pixel is not None:
                        mapped[name] = pixel
                hit = hit_connector_handle(mapped, (pos.x(), pos.y()))
                if hit is not None:
                    return (hit, AuthorKey(object_id))
                continue
            box = getattr(item, "box", None)
            if box is None:
                continue
            mapped = board_box_to_pixels(
                (box.x, box.y, box.width, box.height),
                self._metrics,
                origin_offset=origin,
            )
            if mapped is None:
                continue
            handle = hit_box_handle(
                (
                    int(round(mapped[0])),
                    int(round(mapped[1])),
                    int(round(mapped[2])),
                    int(round(mapped[3])),
                ),
                (pos.x(), pos.y()),
            )
            if handle is not None:
                return (handle, AuthorKey(object_id))
        return None

    def _author_keys_at(self, pos: QPoint) -> tuple[AuthorKey, ...]:
        """Reverse-z hit list. The paint layer itself remains mouse-transparent."""
        hits: list[AuthorKey] = []
        origin = self._workspace_origin_offset()
        probe = pixels_to_board_point(
            (float(pos.x()), float(pos.y())),
            self._metrics,
            origin_offset=origin,
        )
        for item in reversed(self._author_objects):
            object_id = str(getattr(item, "object_id", "") or "")
            if not object_id:
                continue
            box = getattr(item, "box", None)
            if box is not None:
                mapped = board_box_to_pixels(
                    (box.x, box.y, box.width, box.height),
                    self._metrics,
                    origin_offset=origin,
                )
                if mapped is None:
                    continue
                x, y, width, height = mapped
                rect = QRect(
                    int(round(x)),
                    int(round(y)),
                    max(1, int(round(width))),
                    max(1, int(round(height))),
                )
                if rect.contains(pos):
                    hits.append(AuthorKey(object_id))
                continue
            if probe is None:
                continue
            if isinstance(item, ConnectorObject):
                if hit_connector(
                    (item.start.point.x, item.start.point.y),
                    (item.end.point.x, item.end.point.y),
                    probe,
                    route=item.route,
                    stroke_width=item.stroke_width,
                    start_head=item.start_head,
                    end_head=item.end_head,
                    elbow_bias=item.elbow_bias,
                ):
                    hits.append(AuthorKey(object_id))
                continue
            if isinstance(item, StrokeObject):
                record = stroke_hit_record(
                    object_id,
                    ((point.x, point.y) for point in item.points),
                    item.width_px_100,
                )
                if record is not None and hit_stroke(record, probe):
                    hits.append(AuthorKey(object_id))
        return tuple(hits)

    def _on_replace_armed(self, key: str) -> None:
        section, _, view_id = key.partition("/")
        card = self.card_for(section, view_id)
        if card is None:
            return
        self._clear_insert_preview()
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
        self._workspace_extent: GridBounds | None = None

    def set_projection(
        self,
        metrics: GridMetrics,
        placements: Sequence[FreeGridPlacement],
        viewport: QRect,
        workspace_extent: GridBounds | None = None,
    ) -> None:
        self._metrics = metrics
        self._placements = tuple(placements)
        self._viewport = QRect(viewport)
        self._workspace_extent = (
            workspace_extent
            if workspace_extent is not None and not workspace_extent.empty()
            else None
        )
        self.update()

    def _origin_offset(self) -> tuple[int, int]:
        bounds = self._workspace_extent
        return (bounds.column, bounds.row) if bounds is not None else (0, 0)

    def _canvas_size(self) -> tuple[int, int]:
        metrics = self._metrics
        if metrics is None or self._workspace_extent is None:
            return (
                metrics.board_width if metrics is not None else 1,
                metrics.board_height if metrics is not None else 1,
            )
        bounds = self._workspace_extent
        columns = max(1, bounds.column_span)
        rows = max(1, bounds.row_span)
        padding = metrics.exact_padding()
        pitch_x, pitch_y = metrics.exact_pitch()
        cell_w, cell_h = metrics.exact_cell()
        return (
            int(round(2 * padding + (columns - 1) * pitch_x + cell_w)),
            int(round(2 * padding + (rows - 1) * pitch_y + cell_h)),
        )

    def _scale(self) -> tuple[float, float]:
        if self._metrics is None:
            return 1.0, 1.0
        canvas_width, canvas_height = self._canvas_size()
        return (
            max(1, self.width() - 12) / float(max(1, canvas_width)),
            max(1, self.height() - 12) / float(max(1, canvas_height)),
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
                x, y, width, height = rect_to_pixels(
                    item.rect, self._metrics, self._origin_offset()
                )
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
