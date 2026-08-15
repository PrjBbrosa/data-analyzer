"""Standalone UltraView page: View library, board grid, cards, overflow tray.

The page is a view. Coordinator / test harness apply intents by mutating
``UltraViewBoardState`` and calling ``set_board``. This module does not import
MainWindow or analysis compute entry points.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Mapping, Sequence
import math

from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, QTimer, QVariantAnimation, Qt, pyqtSignal
from PyQt5.QtGui import QCursor, QKeySequence, QMouseEvent, QNativeGestureEvent, QWheelEvent
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QShortcut,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
    COMPARE_FILTER_ALL,
    STATUS_ORPHANED,
    STATUS_STALE,
    ULTRAVIEW_PAGE_OBJECT_NAME,
    UltraViewBoardState,
    UltraViewRef,
    axis_consistency_facts,
    all_refs,
    best_template_for,
    board_to_payload,
    card_matches_compare_filter,
    default_board,
    derive_preview_status,
    first_empty_slot,
    free_grid_placement_for,
    layout_capacity,
    layout_slots,
    LAYOUT_MODE_FREE_GRID,
    LAYOUT_SLOTS,
    MAX_UI_BOARDS,
    membership_set,
    parse_ref_payload,
    placed_ref_set,
    placement_for,
    slot_occupant,
)
from .viewport import (
    QUALITY_FAST,
    QUALITY_SMOOTH,
    SMOOTH_DELAY_MS,
    ZOOM_BUTTON_STEP,
    BoardViewport,
    center_from_scroll,
    clamp_zoom,
    fit_zoom,
    scroll_for_center,
    wheel_zoom_factor,
    zoom_at,
    zoom_percent,
    zoom_to_rect,
    FIT_CONTENT_MARGIN,
)
from .widgets import (
    LIBRARY_DEFAULT_WIDTH,
    LIBRARY_OVERLAY_MIN_HEIGHT,
    LAYOUT_LABELS_ZH,
    BoardOverview,
    BoardScrollArea,
    BoardSwitcher,
    BoardGrid,
    FreeGridBoard,
    FreeGridMinimap,
    BoardToolbar,
    CardViewModel,
    CompareRail,
    FocusLayer,
    LibraryRow,
    UltraViewHintBar,
    UnplacedTray,
    ViewLibraryPanel,
    coerce_library_row,
    preview_image,
)
from .chrome import (
    BOARD_POPOVER_WIDTH,
    PANEL_BOARDS,
    PANEL_FILTER,
    PANEL_LAYOUT,
    PANEL_LIBRARY,
    PANEL_UNPLACED,
    BoardIsland,
    BoardPopover,
    CanvasHost,
    CardContextIsland,
    GlobalIsland,
    LayoutPicker,
    NavigationIsland,
    StatusIsland,
    ToolRail,
    board_popover_height,
)
from .floating_layout import (
    BOARD_ISLAND_MAX_WIDTH,
    DEFAULT_MINIMAP_SIZE,
    DEFAULT_NAVIGATION_ISLAND_SIZE,
    GLOBAL_ISLAND_WIDTH,
    ISLAND_HEIGHT,
    OVERLAY_ANCHOR_GLOBAL,
    OVERLAY_ANCHOR_RAIL,
    OVERLAY_GAP,
    RAIL_CONTENT_HEIGHT,
    RAIL_WIDTH,
    STATUS_ISLAND_WIDTH,
    Rect as FloatingRect,
    calculate_floating_layout,
    place_card_context,
)

_FEEDBACK_BOARD_FULL = "Board 已满：换布局或先移除"
_FEEDBACK_NO_SELECTION = "先打开 View 库并选择一个 View"
_FEEDBACK_NO_STALE = "没有需要更新的预览"
_RAIL_PANELS = frozenset({PANEL_LIBRARY, PANEL_LAYOUT, PANEL_FILTER, PANEL_UNPLACED})
_GLOBAL_PANELS = frozenset({"display", "export"})


def _qrect(rect: FloatingRect) -> QRect:
    """Map the Qt-free floating-layout rectangle at the Page boundary."""
    return QRect(int(rect.x), int(rect.y), int(rect.width), int(rect.height))


def _event_point(value) -> QPoint | None:
    if value is None:
        return None
    if isinstance(value, QPoint):
        return value
    if hasattr(value, "toPoint"):
        return value.toPoint()
    return QPoint(int(value.x()), int(value.y()))


def _event_global_point(event) -> QPoint:
    if hasattr(event, "globalPosition"):
        point = _event_point(event.globalPosition())
        if point is not None:
            return point
    if hasattr(event, "globalPos"):
        point = _event_point(event.globalPos())
        if point is not None:
            return point
    if hasattr(event, "screenPos"):
        point = _event_point(event.screenPos())
        if point is not None:
            return point
    return QPoint(0, 0)


def _event_local_point(event) -> QPoint | None:
    if hasattr(event, "position"):
        point = _event_point(event.position())
        if point is not None:
            return point
    if hasattr(event, "pos"):
        return _event_point(event.pos())
    if hasattr(event, "localPos"):
        return _event_point(event.localPos())
    return None


def _is_origin_point(point: QPoint | None) -> bool:
    return point is None or (int(point.x()) == 0 and int(point.y()) == 0)


def _event_global_xy(event) -> tuple[float, float]:
    point = _event_global_point(event)
    return (float(point.x()), float(point.y()))


class UltraViewPage(QWidget):
    add_ref_requested = pyqtSignal(str, str)
    replace_slot_requested = pyqtSignal(str, str, str)
    swap_slots_requested = pyqtSignal(str, str)
    place_from_unplaced_requested = pyqtSignal(str, str, str)
    place_free_grid_from_unplaced_requested = pyqtSignal(str, str)
    free_grid_replace_requested = pyqtSignal(str, str, str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    open_source_requested = pyqtSignal(str, str)
    sync_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    rebind_arm_requested = pyqtSignal(str, str)
    layout_changed = pyqtSignal(str)
    ratio_nudge_requested = pyqtSignal(int)
    copy_board_requested = pyqtSignal()
    copy_card_image_requested = pyqtSignal(str, str)
    export_png_requested = pyqtSignal(int)
    presentation_toggled = pyqtSignal(bool)
    show_titles_toggled = pyqtSignal(bool)
    show_sources_toggled = pyqtSignal(bool)
    rebind_ref_requested = pyqtSignal(str, str, str, str)
    locate_ref_requested = pyqtSignal(str, str)
    compare_filter_changed = pyqtSignal(str)
    quickref_requested = pyqtSignal()
    selection_changed = pyqtSignal(str, str)
    board_name_changed = pyqtSignal(str)
    feedback_requested = pyqtSignal(str)
    create_board_requested = pyqtSignal()
    duplicate_board_requested = pyqtSignal(str)
    rename_board_requested = pyqtSignal(str, str)
    delete_board_requested = pyqtSignal(str)
    reorder_board_requested = pyqtSignal(str, int)
    select_board_requested = pyqtSignal(str)
    free_grid_toggled = pyqtSignal(bool)
    free_grid_geometry_requested = pyqtSignal(str, str, int, int, int, int, str)
    free_grid_group_geometry_requested = pyqtSignal(object)
    free_grid_preset_requested = pyqtSignal(str, str, str)
    free_grid_autofit_requested = pyqtSignal(str, str)
    organize_free_grid_requested = pyqtSignal()
    free_grid_undo_requested = pyqtSignal()
    free_grid_redo_requested = pyqtSignal()
    viewport_changed = pyqtSignal(str, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(ULTRAVIEW_PAGE_OBJECT_NAME)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._board = default_board()
        self._workspace: Any | None = None
        self._previews: dict[UltraViewRef, Any] = {}
        self._statuses: dict[UltraViewRef, str] = {}
        self._ref_exists: dict[UltraViewRef, bool] = {}
        self._selected: UltraViewRef | None = None
        self._replacement_slot: str | None = None
        self._replacement_ref: UltraViewRef | None = None
        self._compare_filter = COMPARE_FILTER_ALL
        self._drag_kind: str | None = None
        self._pending_library_rows: list[LibraryRow] | None = None
        self._board_widgets_dirty = False
        self._projection_batch_depth = 0
        self._projection_dirty = False
        self._presentation = False
        # Floating chrome is transient view state: it is deliberately not
        # serialised with a Board or a project.  A fresh UltraView opens on a
        # continuous canvas; the library is available from the rail on demand.
        self._library_visible = False
        self._active_panel: str | None = None
        self._presentation_panel: str | None = None
        self._deferred_panel_close: str | None = None
        self._prev_unplaced_count: int | None = None
        self._prev_layout_fingerprint: tuple[str, str] | None = None
        self._viewport = BoardViewport()
        self._restoring_viewport = False
        self._pending_viewport_restore: dict[str, float] | None = None
        self._pending_fit = True
        self._smooth_timer = QTimer(self)
        self._smooth_timer.setObjectName("ultraViewSmoothPreviewTimer")
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(SMOOTH_DELAY_MS)
        self._smooth_timer.timeout.connect(self._on_smooth_preview_timeout)
        self._zoom_anim = QVariantAnimation(self)
        self._zoom_anim.setObjectName("ultraViewZoomToCardAnimation")
        self._zoom_anim.setDuration(180)
        self._zoom_anim.valueChanged.connect(self._on_zoom_anim_tick)
        self._anim_start_zoom = 1.0
        self._anim_end_zoom = 1.0
        self._anim_start_center = (0.0, 0.0)
        self._anim_end_center = (0.0, 0.0)
        self._filled_card: tuple[str, str] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # The stage fills the independent UltraView tool window.  The scroll
        # host sits inside it at a rect supplied by ``floating_layout``;
        # islands and popovers are sibling overlays, never layout neighbours
        # which could steal a row/column from the Board.
        self._canvas_host = CanvasHost(self)
        self._canvas_host.installEventFilter(self)
        self._canvas_stage = QFrame(self._canvas_host)
        self._canvas_stage.setObjectName("ultraViewCanvasStage")
        self._canvas_stage.setAttribute(Qt.WA_StyledBackground, True)
        self._board_column = self._canvas_stage  # compatibility-only internal alias
        self._grid = BoardGrid(self._canvas_stage)
        self._free_grid = FreeGridBoard(self._canvas_stage)
        self._board_host = QWidget(self._canvas_stage)
        self._board_host.setObjectName("ultraViewBoardHost")
        self._board_host.setAttribute(Qt.WA_StyledBackground, True)
        self._board_stack = QStackedWidget(self._board_host)
        self._board_stack.setObjectName("ultraViewBoardCanvasStack")
        self._board_stack.addWidget(self._grid)
        self._board_stack.addWidget(self._free_grid)
        self._board_scroll = BoardScrollArea(self._canvas_stage)
        self._board_scroll.setWidget(self._board_host)
        self._board_host.installEventFilter(self)
        self._board_scroll.viewport().installEventFilter(self)
        self._canvas_host.set_canvas_widget(self._canvas_stage)
        root.addWidget(self._canvas_host, 1)

        # Old widgets stay alive as presentation façades for integrations and
        # focused tests.  Only their *entry placement* changes; signals still
        # route through the existing Page/coordinator contracts.
        self._library = ViewLibraryPanel(self._canvas_host)
        self._switcher = BoardSwitcher(self._canvas_host)
        self._toolbar = BoardToolbar(self._canvas_host)
        self._rail = CompareRail(self._canvas_host)
        self._tray = UnplacedTray(self._canvas_host)
        self._hint_bar = UltraViewHintBar(self._canvas_host)
        self._switcher.hide()
        self._toolbar.hide()
        self._hint_bar.hide()

        self._overview = BoardOverview(self._canvas_host)
        self._overview.hide()
        self._minimap = FreeGridMinimap(self._board_scroll.viewport())
        self._minimap.hide()

        self._tool_rail = ToolRail(self._canvas_host)
        self._empty_board_hint = QLabel("从左侧 View 库添加对比", self._canvas_host)
        self._empty_board_hint.setObjectName("ultraViewEmptyBoardHint")
        self._empty_board_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._empty_board_hint.setAttribute(Qt.WA_StyledBackground, True)
        self._empty_board_hint.hide()
        self._board_island = BoardIsland(self._canvas_host)
        self._global_island = GlobalIsland(self._canvas_host)
        self._navigation_island = NavigationIsland(self._canvas_host)
        self._status_island = StatusIsland(self._canvas_host)
        self._card_context = CardContextIsland(self._canvas_host)
        self._layout_popover = LayoutPicker(LAYOUT_LABELS_ZH, self._canvas_host)
        self._layout_popover.layout_id_chosen.connect(self._on_layout_id_chosen)
        self._board_popover = BoardPopover(self._canvas_host)
        self._display_popover = self._build_display_popover(self._canvas_host)
        self._export_popover = self._build_export_popover(self._canvas_host)

        self._canvas_host.register_overlay(
            PANEL_LIBRARY,
            self._library,
            trigger=self._tool_rail.panel_button(PANEL_LIBRARY),
        )
        self._canvas_host.register_overlay(
            PANEL_LAYOUT,
            self._layout_popover,
            trigger=self._tool_rail.panel_button(PANEL_LAYOUT),
        )
        self._canvas_host.register_overlay(
            PANEL_FILTER,
            self._rail,
            trigger=self._tool_rail.panel_button(PANEL_FILTER),
        )
        self._canvas_host.register_overlay(
            PANEL_UNPLACED,
            self._tray,
            trigger=self._tool_rail.panel_button(PANEL_UNPLACED),
        )
        self._canvas_host.register_overlay(
            "display",
            self._display_popover,
            trigger=self._global_island.display_button(),
        )
        self._canvas_host.register_overlay(
            "export",
            self._export_popover,
            trigger=self._global_island.export_button(),
        )
        self._canvas_host.register_overlay(
            PANEL_BOARDS,
            self._board_popover,
            trigger=self._board_island.menu_button(),
        )

        self._focus = FocusLayer(self)
        self._focus.hide()

        self._hint_bar.quickref_requested.connect(self.quickref_requested.emit)
        self._status_island.quickref_requested.connect(self.quickref_requested.emit)
        self._tool_rail.panel_requested.connect(self._toggle_panel)
        self._tool_rail.free_grid_toggled.connect(self._on_free_grid_toggled)
        self._tool_rail.sync_all_requested.connect(self._on_sync_all_requested)
        self._tool_rail.ref_dropped.connect(self._on_tray_drop)
        self._canvas_host.overlay_closed.connect(self._on_overlay_closed)
        self._board_island.board_menu_requested.connect(self._show_board_menu)
        self._board_island.create_requested.connect(self.create_board_requested)
        self._board_island.rename_requested.connect(self._rename_current_board)
        self._board_popover.board_selected.connect(self._on_board_selected)
        self._board_popover.duplicate_requested.connect(self.duplicate_board_requested)
        self._board_popover.delete_requested.connect(self._confirm_delete_board)
        self._board_popover.boards_reordered.connect(self._on_boards_reordered)
        self._board_popover.create_requested.connect(self.create_board_requested)
        self._board_popover.rename_requested.connect(self._rename_board)
        self._global_island.display_requested.connect(self._on_display_panel_requested)
        self._global_island.export_requested.connect(self._on_export_panel_requested)
        self._global_island.presentation_toggled.connect(self._on_presentation_button)
        self._navigation_island.overview_requested.connect(self.show_overview)
        self._navigation_island.zoom_out_requested.connect(self.zoom_out)
        self._navigation_island.zoom_in_requested.connect(self.zoom_in)
        self._navigation_island.zoom_fit_requested.connect(self.zoom_fit)
        self._navigation_island.zoom_reset_requested.connect(self.zoom_reset)
        self._card_context.open_source_requested.connect(self.open_source_requested)
        self._card_context.sync_requested.connect(self.sync_requested)
        self._card_context.focus_requested.connect(self._on_focus)
        self._card_context.copy_image_requested.connect(self.copy_card_image_requested)
        self._card_context.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        self._card_context.more_requested.connect(self._show_card_more_menu)
        self._card_context.rebind_requested.connect(self._on_rebind_arm)
        self._card_context.remove_requested.connect(self.remove_ref_requested)
        self._card_context.fit_requested.connect(self.free_grid_autofit_requested)

        self._library.add_requested.connect(self.request_add)
        self._library.remove_requested.connect(self.remove_ref_requested)
        self._library.locate_requested.connect(self._on_locate)
        self._library.pin_toggled.connect(self._on_library_pin_toggled)
        self._library.drag_started.connect(self._on_drag_started)
        self._library.drag_finished.connect(self._on_drag_finished)

        self._toolbar.layout_changed.connect(self.layout_changed)
        self._toolbar.ratio_nudge_requested.connect(self.ratio_nudge_requested)
        self._toolbar.copy_board_requested.connect(self.copy_board_requested)
        self._toolbar.export_png_requested.connect(self.export_png_requested)
        self._toolbar.show_titles_toggled.connect(self.show_titles_toggled)
        self._toolbar.show_sources_toggled.connect(self.show_sources_toggled)
        self._toolbar.presentation_toggled.connect(self._on_presentation_button)
        self._toolbar.overview_requested.connect(self.show_overview)
        self._toolbar.board_name_changed.connect(self.board_name_changed)
        self._toolbar.free_grid_toggled.connect(self.free_grid_toggled)
        self._toolbar.organize_free_grid_requested.connect(self.organize_free_grid_requested)
        self._toolbar.zoom_out_requested.connect(self.zoom_out)
        self._toolbar.zoom_in_requested.connect(self.zoom_in)
        self._toolbar.zoom_fit_requested.connect(self.zoom_fit)
        self._toolbar.zoom_reset_requested.connect(self.zoom_reset)

        self._rail.compare_filter_changed.connect(self._on_compare_filter)

        self._switcher.create_requested.connect(self.create_board_requested)
        self._switcher.duplicate_requested.connect(self.duplicate_board_requested)
        self._switcher.rename_requested.connect(self.rename_board_requested)
        self._switcher.delete_requested.connect(self.delete_board_requested)
        self._switcher.reorder_requested.connect(self.reorder_board_requested)
        self._switcher.board_selected.connect(self._on_board_selected)
        self._board_scroll.viewport_resized.connect(self._on_viewport_resized)
        self._board_scroll.viewport_resized.connect(self._refresh_minimap)
        self._board_scroll.horizontalScrollBar().valueChanged.connect(self._refresh_minimap)
        self._board_scroll.verticalScrollBar().valueChanged.connect(self._refresh_minimap)
        self._board_scroll.horizontalScrollBar().rangeChanged.connect(self._refresh_minimap)
        self._board_scroll.verticalScrollBar().rangeChanged.connect(self._refresh_minimap)
        self._board_scroll.horizontalScrollBar().valueChanged.connect(self._on_board_scrolled)
        self._board_scroll.verticalScrollBar().valueChanged.connect(self._on_board_scrolled)
        self._overview.slot_requested.connect(self._on_overview_slot)
        self._overview.ref_requested.connect(self._on_overview_ref)
        self._overview.close_requested.connect(self.hide_overview)
        self._minimap.viewport_requested.connect(self._on_minimap_viewport)

        self._grid.add_clicked.connect(self._on_empty_slot)
        self._grid.ref_dropped.connect(self._on_ref_dropped)
        self._grid.open_source_requested.connect(self.open_source_requested)
        self._grid.sync_requested.connect(self.sync_requested)
        self._grid.focus_requested.connect(self._on_focus)
        self._grid.rebind_arm_requested.connect(self._on_rebind_arm)
        self._grid.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        self._grid.remove_ref_requested.connect(self.remove_ref_requested)
        self._grid.copy_card_image_requested.connect(self.copy_card_image_requested)
        self._grid.selected.connect(self._on_card_selected)
        self._grid.drag_started.connect(self._on_drag_started)
        self._grid.drag_finished.connect(self._on_drag_finished)
        self._grid.slot_swap_requested.connect(self.swap_slots_requested)

        self._free_grid.ref_dropped.connect(self._on_free_grid_ref_dropped)
        self._free_grid.geometry_requested.connect(self.free_grid_geometry_requested)
        self._free_grid.group_geometry_requested.connect(
            self.free_grid_group_geometry_requested
        )
        self._free_grid.preset_requested.connect(self.free_grid_preset_requested)
        self._free_grid.autofit_requested.connect(self.free_grid_autofit_requested)
        self._free_grid.open_source_requested.connect(self.open_source_requested)
        self._free_grid.sync_requested.connect(self.sync_requested)
        self._free_grid.focus_requested.connect(self._on_focus)
        self._free_grid.rebind_arm_requested.connect(self._on_rebind_arm)
        self._free_grid.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        self._free_grid.remove_ref_requested.connect(self.remove_ref_requested)
        self._free_grid.copy_card_image_requested.connect(self.copy_card_image_requested)
        self._free_grid.selected.connect(self._on_card_selected)
        self._free_grid.drag_started.connect(self._on_drag_started)
        self._free_grid.drag_finished.connect(self._on_drag_finished)
        self._free_grid.feedback_requested.connect(self._emit_feedback)
        self._free_grid.replace_requested.connect(self.free_grid_replace_requested)

        self._tray.place_requested.connect(self._on_tray_place)
        self._tray.remove_requested.connect(self.remove_ref_requested)
        self._tray.locate_requested.connect(self._on_locate)
        self._tray.rebind_arm_requested.connect(self._on_rebind_arm)
        self._tray.move_to_unplaced_dropped.connect(self._on_tray_drop)
        self._tray.drag_started.connect(self._on_drag_started)
        self._tray.drag_finished.connect(self._on_drag_finished)

        self._focus.open_source_requested.connect(self.open_source_requested)
        self._esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc.setContext(Qt.WidgetWithChildrenShortcut)
        self._esc.activated.connect(self._on_escape_shortcut)
        self._grid_undo = QShortcut(QKeySequence.Undo, self)
        self._grid_undo.setContext(Qt.WidgetWithChildrenShortcut)
        self._grid_undo.activated.connect(self._on_grid_undo_shortcut)
        self._grid_redo = QShortcut(QKeySequence.Redo, self)
        self._grid_redo.setContext(Qt.WidgetWithChildrenShortcut)
        self._grid_redo.activated.connect(self._on_grid_redo_shortcut)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)
        self.set_board(self._board)
        QTimer.singleShot(0, self._apply_floating_layout)

    def board_switcher(self) -> BoardSwitcher:
        return self._switcher

    def board_scroll_area(self) -> BoardScrollArea:
        return self._board_scroll

    def board_overview(self) -> BoardOverview:
        return self._overview

    def free_grid_minimap(self) -> FreeGridMinimap:
        return self._minimap

    def hint_bar(self) -> QWidget:
        return self._hint_bar

    def library_panel(self) -> ViewLibraryPanel:
        return self._library

    def board_grid(self) -> BoardGrid:
        return self._grid

    def unplaced_tray(self) -> UnplacedTray:
        return self._tray

    def compare_rail(self) -> CompareRail:
        return self._rail

    def board_toolbar(self) -> BoardToolbar:
        return self._toolbar

    def board_viewport(self) -> BoardViewport:
        return self._viewport

    def board_zoom(self) -> float:
        return self._viewport.zoom()

    def preview_quality(self) -> str:
        return self._viewport.quality()

    def smooth_preview_timer(self) -> QTimer:
        return self._smooth_timer

    def is_board_panning(self) -> bool:
        return self._viewport.is_panning()

    @contextmanager
    def projection_batch(self):
        """Coalesce card projection and library rows across coordinator pushes."""
        self._projection_batch_depth += 1
        try:
            yield
        finally:
            self._projection_batch_depth -= 1
            if self._projection_batch_depth == 0:
                self._flush_projection_batch()

    def canvas_host(self) -> CanvasHost:
        """Expose the floating host for focused geometry/interaction probes."""
        return self._canvas_host

    def tool_rail(self) -> ToolRail:
        return self._tool_rail

    def board_island(self) -> BoardIsland:
        return self._board_island

    def board_popover(self) -> BoardPopover:
        return self._board_popover

    def global_island(self) -> GlobalIsland:
        return self._global_island

    def navigation_island(self) -> NavigationIsland:
        return self._navigation_island

    def status_island(self) -> StatusIsland:
        return self._status_island

    def card_context_island(self) -> CardContextIsland:
        return self._card_context

    def active_panel(self) -> str | None:
        return self._active_panel

    def _build_popover(self, parent: QWidget, object_name: str, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame(parent)
        frame.setObjectName(object_name)
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setFocusPolicy(Qt.StrongFocus)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        heading = QLabel(title, frame)
        heading.setObjectName(f"{object_name}Title")
        heading.setProperty("role", "popoverTitle")
        layout.addWidget(heading, 0)
        return frame, layout

    def _on_layout_id_chosen(self, layout_id: str) -> None:
        wanted = str(layout_id or "")
        if not wanted:
            return
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            if not self._confirm_leave_free_grid(wanted):
                self._sync_layout_popover()
                return
        if wanted != self._board.layout_id or self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self.layout_changed.emit(wanted)

    def _confirm_leave_free_grid(self, layout_id: str) -> bool:
        count = len(self._board.free_grid)
        wanted = str(layout_id or "")
        if wanted not in LAYOUT_SLOTS:
            wanted = best_template_for(count)
        capacity = layout_capacity(wanted)
        if count <= capacity:
            return True
        label = LAYOUT_LABELS_ZH.get(wanted, wanted)
        overflow = count - capacity
        answer = QMessageBox.question(
            self,
            "切回模板布局",
            f"将切换到「{label}」（{capacity} 槽）。超出容量的 {overflow} 张卡片会移入未放置区。继续吗？",
            QMessageBox.Cancel | QMessageBox.Yes,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Yes

    def _on_free_grid_toggled(self, enabled: bool) -> None:
        if not enabled and self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            layout_id = best_template_for(len(self._board.free_grid))
            if not self._confirm_leave_free_grid(layout_id):
                self._tool_rail.set_free_grid_enabled(True)
                return
        self.free_grid_toggled.emit(bool(enabled))

    def _stale_refs(self) -> list[UltraViewRef]:
        return [
            ref for ref in all_refs(self._board)
            if self._status_for(ref) == STATUS_STALE
        ]

    def _stale_ref_count(self) -> int:
        return len(self._stale_refs())

    def _on_sync_all_requested(self) -> None:
        stale = self._stale_refs()
        if not stale:
            self._emit_feedback(_FEEDBACK_NO_STALE)
            return
        for ref in stale:
            self.sync_requested.emit(ref.section, ref.view_id)

    def _sync_layout_popover(self) -> None:
        is_free_grid = self._board.layout_mode == LAYOUT_MODE_FREE_GRID
        if hasattr(self, "_layout_popover"):
            self._layout_popover.set_current(
                self._board.layout_id,
                free_grid=is_free_grid,
                view_count=len(all_refs(self._board)),
            )
        if hasattr(self, "_tool_rail"):
            self._tool_rail.set_free_grid_enabled(is_free_grid)

    def _build_display_popover(self, parent: QWidget) -> QFrame:
        frame, layout = self._build_popover(parent, "ultraViewDisplayPopover", "显示")
        self._display_titles = QToolButton(frame)
        self._display_titles.setObjectName("ultraViewDisplayTitlesButton")
        self._display_titles.setText("显示卡片标题")
        self._display_titles.setCheckable(True)
        self._display_titles.setToolTip("切换卡片标题")
        self._display_titles.toggled.connect(self.show_titles_toggled)
        self._display_sources = QToolButton(frame)
        self._display_sources.setObjectName("ultraViewDisplaySourcesButton")
        self._display_sources.setText("显示来源文件")
        self._display_sources.setCheckable(True)
        self._display_sources.setToolTip("切换来源文件")
        self._display_sources.toggled.connect(self.show_sources_toggled)
        layout.addWidget(self._display_titles, 0)
        layout.addWidget(self._display_sources, 0)
        note = QLabel("预览状态始终可见", frame)
        note.setObjectName("ultraViewDisplayTrustNote")
        note.setToolTip("过期、缺失和孤儿 View 是可信度信息，不提供隐藏开关")
        layout.addWidget(note, 0)
        return frame

    def _build_export_popover(self, parent: QWidget) -> QFrame:
        frame, layout = self._build_popover(parent, "ultraViewExportPopover", "导出")
        copy = QPushButton("复制整板图", frame)
        copy.setObjectName("ultraViewExportCopyBoardButton")
        copy.clicked.connect(self.copy_board_requested)
        png_1x = QPushButton("导出 PNG 1×", frame)
        png_1x.setObjectName("ultraViewExportPng1xButton")
        png_1x.clicked.connect(self._on_export_1x)
        png_2x = QPushButton("导出 PNG 2×", frame)
        png_2x.setObjectName("ultraViewExportPng2xButton")
        png_2x.clicked.connect(self._on_export_2x)
        layout.addWidget(copy, 0)
        layout.addWidget(png_1x, 0)
        layout.addWidget(png_2x, 0)
        return frame

    def _on_export_1x(self) -> None:
        self.export_png_requested.emit(1)

    def _on_export_2x(self) -> None:
        self.export_png_requested.emit(2)

    def _on_display_panel_requested(self) -> None:
        self._toggle_panel("display")

    def _on_export_panel_requested(self) -> None:
        self._toggle_panel("export")

    def _overlay_size(self, panel_id: str) -> tuple[int, int]:
        minima = {
            PANEL_LIBRARY: (LIBRARY_DEFAULT_WIDTH, LIBRARY_OVERLAY_MIN_HEIGHT),
            PANEL_LAYOUT: (360, 240),
            PANEL_FILTER: (160, 160),
            PANEL_UNPLACED: (360, 160),
            PANEL_BOARDS: (BOARD_POPOVER_WIDTH, board_popover_height(1)),
            "display": (200, 80),
            "export": (200, 80),
        }
        min_width, min_height = minima.get(panel_id, (200, 80))
        widget = self._canvas_host.overlay(panel_id) if hasattr(self, "_canvas_host") else None
        if widget is None:
            return (min_width, min_height)
        hint = widget.sizeHint()
        min_hint = widget.minimumSizeHint()
        width = max(min_width, hint.width(), min_hint.width())
        height = max(min_height, hint.height(), min_hint.height())
        host_h = int(self._canvas_host.height())
        if panel_id == PANEL_BOARDS:
            cap_h = max(min_height, int(host_h * 0.6)) if host_h > 0 else 320
            return (BOARD_POPOVER_WIDTH, min(height, cap_h))
        cap_h = max(min_height, host_h - 96) if host_h > 0 else 640
        return (min(width, 520), min(height, cap_h))

    def _chrome_sizes(self) -> dict[str, tuple[int, int]]:
        def _hint(widget, fallback: tuple[int, int]) -> tuple[int, int]:
            hint = widget.sizeHint()
            width = hint.width() if hint.width() > 0 else fallback[0]
            height = hint.height() if hint.height() > 0 else fallback[1]
            return (width, height)

        return {
            "board_island": _hint(
                self._board_island, (BOARD_ISLAND_MAX_WIDTH, ISLAND_HEIGHT)
            ),
            "global_island": _hint(
                self._global_island, (GLOBAL_ISLAND_WIDTH, ISLAND_HEIGHT)
            ),
            "status_island": _hint(
                self._status_island, (STATUS_ISLAND_WIDTH, ISLAND_HEIGHT)
            ),
            "navigation_island": _hint(
                self._navigation_island, DEFAULT_NAVIGATION_ISLAND_SIZE
            ),
            "rail": _hint(self._tool_rail, (RAIL_WIDTH, RAIL_CONTENT_HEIGHT)),
        }

    def _content_fit_rect(self):
        """Chrome-safe parking rect for 1× / 适应; full stage during 演示."""
        layout = self._floating_layout()
        if self._presentation:
            return layout.board
        return layout.fit

    def _fit_origin(self) -> tuple[float, float]:
        """Chrome-safe parking origin. Fit / 1× / restore park the stack here."""
        fit = self._content_fit_rect()
        return (float(fit.x), float(fit.y))

    def _board_content_origin(self) -> tuple[float, float]:
        """Current board-canvas origin inside the scroll host.

        After a cursor-anchored zoom this may include left/top pad so a
        negative desired scroll stays representable.  Scroll math must use
        this value, not ``_fit_origin``: recentering onto fit after
        compensation is what pinned zoom to the chrome-safe corner.
        """
        if self._board_stack.width() <= 0 or self._board_stack.height() <= 0:
            return self._fit_origin()
        return (float(self._board_stack.x()), float(self._board_stack.y()))

    def _board_layout_viewport_size(self, size=None):
        """Viewport used for card layout: the chrome-safe fit rect, not the full-bleed scroll host."""
        del size
        fit = self._content_fit_rect()
        return QSize(max(1, int(fit.width)), max(1, int(fit.height)))

    def _panel_trigger_rect(self) -> FloatingRect | None:
        """Stage-relative rect of the rail button that opened the active panel.

        Only rail panels have a rail trigger; global panels anchor under
        GlobalIsland instead and never consult this.
        """
        panel_id = self._active_panel
        if panel_id is None or panel_id not in _RAIL_PANELS:
            return None
        button = self._tool_rail.panel_button(panel_id)
        if button is None or not button.isVisible():
            return None
        point = button.mapTo(self._canvas_host, QPoint(0, 0))
        return FloatingRect(point.x(), point.y(), button.width(), button.height())

    def _floating_layout(self, *, overlay_open: bool | None = None):
        panel = self._active_panel
        if overlay_open is None:
            layout_open = panel not in (None, PANEL_BOARDS)
        else:
            layout_open = bool(overlay_open)
        sizes = self._chrome_sizes()
        return calculate_floating_layout(
            (self._canvas_host.width(), self._canvas_host.height()),
            overlay_open=layout_open,
            overlay_size=self._overlay_size(panel or PANEL_LIBRARY),
            overlay_anchor=(
                OVERLAY_ANCHOR_GLOBAL
                if panel in _GLOBAL_PANELS
                else OVERLAY_ANCHOR_RAIL
            ),
            minimap_size=DEFAULT_MINIMAP_SIZE if self._minimap_should_show() else None,
            board_island_size=sizes["board_island"],
            global_island_size=sizes["global_island"],
            status_island_size=sizes["status_island"],
            navigation_island_size=sizes["navigation_island"],
            rail_size=sizes["rail"],
            trigger_rect=self._panel_trigger_rect(),
        )

    def _apply_floating_layout(self) -> None:
        """Place the scroll viewport and all fixed chrome without reflow."""
        if not hasattr(self, "_canvas_host"):
            return
        layout = self._floating_layout()
        self._board_scroll.setGeometry(_qrect(layout.board))
        self._tool_rail.setGeometry(_qrect(layout.rail))
        self._board_island.setGeometry(_qrect(layout.board_island))
        self._global_island.setGeometry(_qrect(layout.global_island))
        self._status_island.setGeometry(_qrect(layout.status_island))
        self._navigation_island.setGeometry(_qrect(layout.navigation_island))
        for island in (
            self._tool_rail,
            self._board_island,
            self._global_island,
            self._status_island,
            self._navigation_island,
        ):
            island.raise_()
        self._sync_empty_board_cue()
        if self._active_panel == PANEL_BOARDS:
            self._canvas_host.set_overlay_geometry(PANEL_BOARDS, self._board_popover_rect())
            overlay = self._canvas_host.overlay(PANEL_BOARDS)
            if overlay is not None:
                overlay.raise_()
            self._board_popover.relayout()
        elif self._active_panel is not None and layout.overlay is not None:
            self._canvas_host.set_overlay_geometry(self._active_panel, _qrect(layout.overlay))
            overlay = self._canvas_host.overlay(self._active_panel)
            if overlay is not None:
                overlay.raise_()
        if self._overview.isVisible():
            self._overview.setGeometry(self._board_scroll.geometry())
            self._overview.raise_()
            self._navigation_island.raise_()
            self._card_context.hide()
        self._position_minimap(layout)
        if not self._overview.isVisible():
            self._position_card_context()

    def _toggle_panel(self, panel_id: str) -> None:
        if self._active_panel == panel_id:
            self._close_active_panel(restore_focus=False)
            self._sync_panel_triggers()
            return
        if not self._open_panel(panel_id):
            self._sync_panel_triggers()

    def _sync_panel_triggers(self) -> None:
        self._tool_rail.set_active_panel(self._active_panel if self._active_panel in _RAIL_PANELS else None)
        self._global_island.set_active_panel(self._active_panel if self._active_panel in _GLOBAL_PANELS else None)
        self._board_island.set_menu_open(self._active_panel == PANEL_BOARDS)
        self._sync_empty_board_cue()

    def _sync_empty_board_cue(self) -> None:
        """Empty canvas: solid View 库 CTA plus a sentence beside the rail."""
        empty = not placed_ref_set(self._board)
        self._tool_rail.set_empty_board(empty)
        hint = getattr(self, "_empty_board_hint", None)
        if hint is None:
            return
        show = (
            empty
            and not self._presentation
            and self._active_panel != PANEL_LIBRARY
            and not self._overview.isVisible()
            and self._tool_rail.isVisible()
        )
        hint.setVisible(show)
        if show:
            self._position_empty_board_hint()

    def _position_empty_board_hint(self) -> None:
        button = self._tool_rail.panel_button(PANEL_LIBRARY)
        hint = self._empty_board_hint
        if button is None:
            return
        hint.adjustSize()
        center = button.mapTo(self._canvas_host, button.rect().center())
        x = self._tool_rail.geometry().right() + 14
        y = center.y() - hint.height() // 2
        hint.move(x, max(0, y))
        hint.raise_()

    def _board_popover_rect(self) -> QRect:
        island = self._board_island.geometry()
        width, height = self._overlay_size(PANEL_BOARDS)
        host = self._canvas_host.contentsRect()
        x = island.x()
        y = island.y() + island.height() + OVERLAY_GAP
        if y + height > host.bottom():
            y = max(host.y(), island.y() - OVERLAY_GAP - height)
        return QRect(x, y, width, height)

    def _open_panel(self, panel_id: str) -> bool:
        if self._presentation or self._canvas_host.overlay(panel_id) is None:
            return False
        if self._drag_kind is not None and self._active_panel is not None and panel_id != self._active_panel:
            self._deferred_panel_close = self._active_panel
            return False
        self._active_panel = panel_id
        if panel_id == PANEL_BOARDS:
            self._refresh_board_popover()
            rect = self._board_popover_rect()
            opened = self._canvas_host.open_overlay(panel_id, rect, focus=True)
            if not opened:
                self._active_panel = None
                return False
            self._sync_panel_triggers()
            self._apply_floating_layout()
            self._board_popover.list_widget().setFocus(Qt.OtherFocusReason)
            return True
        layout = self._floating_layout(overlay_open=True)
        if layout.overlay is None:
            self._active_panel = None
            return False
        if panel_id == PANEL_UNPLACED:
            self._tray.set_overlay_mode(True)
        opened = self._canvas_host.open_overlay(
            panel_id,
            _qrect(layout.overlay),
            focus=panel_id == PANEL_LIBRARY,
        )
        if not opened:
            self._active_panel = None
            return False
        self._library_visible = panel_id == PANEL_LIBRARY
        self._sync_panel_triggers()
        self._apply_floating_layout()
        if panel_id == PANEL_LIBRARY:
            self._library.focus_search()
        elif panel_id == PANEL_UNPLACED:
            self._tray.focus_first_item()
        return True

    def _close_active_panel(self, *, restore_focus: bool = True) -> bool:
        panel_id = self._active_panel
        if panel_id is not None and self._drag_kind is not None:
            self._deferred_panel_close = panel_id
            return False
        closed = self._canvas_host.close_active_overlay(restore_focus=restore_focus)
        if panel_id == PANEL_UNPLACED:
            self._tray.set_overlay_mode(False)
        return closed

    def _on_overlay_closed(self, panel_id: str) -> None:
        if panel_id == PANEL_LIBRARY:
            self._library_visible = False
        if panel_id == PANEL_UNPLACED:
            self._tray.set_overlay_mode(False)
        if self._active_panel == panel_id:
            self._active_panel = None
        self._sync_panel_triggers()
        self._apply_floating_layout()

    def _on_library_pin_toggled(self, pinned: bool) -> None:
        self._canvas_host.set_overlay_close_on_canvas(PANEL_LIBRARY, close=not pinned)

    def _show_board_menu(self) -> None:
        self._toggle_panel(PANEL_BOARDS)

    def _refresh_board_popover(self) -> None:
        boards = tuple(getattr(self._workspace, "boards", ()) or ()) if self._workspace is not None else (self._board,)
        active_id = str(
            getattr(self._workspace, "active_board_id", "") or getattr(self._board, "board_id", "") or ""
        )
        self._board_popover.set_boards(boards, active_id)
        at_cap = len(boards) >= MAX_UI_BOARDS
        self._board_popover.set_create_enabled(
            not at_cap,
            "最多创建 20 个 Board" if at_cap else "",
        )
        if self._active_panel == PANEL_BOARDS:
            self._apply_floating_layout()

    def _on_boards_reordered(self, board_id: str, new_index: int) -> None:
        self.reorder_board_requested.emit(str(board_id), int(new_index))

    def _rename_board(self, board_id: str) -> None:
        boards = tuple(getattr(self._workspace, "boards", ()) or ()) if self._workspace is not None else (self._board,)
        target = next((item for item in boards if str(getattr(item, "board_id", "")) == board_id), self._board)
        text, accepted = QInputDialog.getText(self, "重命名 Board", "名称", text=str(getattr(target, "name", "") or ""))
        if accepted and text.strip():
            self.rename_board_requested.emit(board_id, text.strip())

    def _confirm_delete_board(self, board_id: str) -> None:
        boards = tuple(getattr(self._workspace, "boards", ()) or ()) if self._workspace is not None else (self._board,)
        target = next((item for item in boards if str(getattr(item, "board_id", "")) == board_id), self._board)
        name = str(getattr(target, "name", "") or "Board")
        answer = QMessageBox.question(
            self,
            "删除 Board",
            f"确定删除“{name}”吗？其中的 View 引用不会删除源 View。",
            QMessageBox.Cancel | QMessageBox.Yes,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Yes:
            self.delete_board_requested.emit(board_id)

    def _rename_current_board(self) -> None:
        self._rename_board(self._board.board_id)

    def _show_card_more_menu(self, section: str, view_id: str) -> None:
        card = self.card_widget(section, view_id)
        if card is None:
            return
        menu = card.make_context_menu()
        button = card.action_button("more")
        if button is not None:
            origin = button.mapToGlobal(QPoint(0, button.height()))
        else:
            origin = card.mapToGlobal(QPoint(card.width(), 0))
        menu.exec_(origin)

    def _position_card_context(self) -> None:
        if self._presentation or self._overview.isVisible() or self._selected is None or not self._card_context.isVisible():
            return
        card = self.card_widget(self._selected.section, self._selected.view_id)
        if card is None or not card.isVisible():
            self._card_context.clear_ref()
            return
        point = card.mapTo(self._canvas_host, QPoint(0, 0))
        card_rect = FloatingRect(point.x(), point.y(), card.width(), card.height())
        layout = self._floating_layout()
        placed = place_card_context(
            (self._canvas_host.width(), self._canvas_host.height()),
            card_rect,
            size=(max(136, self._card_context.sizeHint().width()), 40),
            avoid=(
                layout.board_island,
                layout.global_island,
                layout.navigation_island,
                layout.status_island,
                layout.rail,
            ),
        )
        self._card_context.setGeometry(_qrect(placed.rect))
        self._card_context.raise_()

    def _persist_viewport_to_board(self) -> None:
        if self._restoring_viewport or self._board is None:
            return
        center = self._current_center()
        self._viewport.set_center(center)
        payload = {
            "zoom": float(self._viewport.zoom()),
            "center_x": float(center[0]),
            "center_y": float(center[1]),
        }
        self.viewport_changed.emit(str(self._board.board_id), payload)

    def _restore_viewport_from_board(self, board, payload: Mapping[str, Any] | None = None) -> None:
        source = payload if payload is not None else getattr(board, "viewport", None)
        if not isinstance(source, Mapping) or "zoom" not in source:
            self._pending_fit = True
            viewport = self._board_scroll.viewport()
            if viewport.width() > 1 and viewport.height() > 1:
                self._pending_fit = False
                self.zoom_fit()
            return
        self._pending_fit = False
        self._restoring_viewport = True
        try:
            self._viewport.restore_payload(source)
            zoom = self._viewport.zoom()
            # ``restore_payload`` already applied the viewport zoom.  Keep
            # that behavior while broadcasting it to both render surfaces.
            self._broadcast_zoom(zoom, viewport=False)
            origin = self._fit_origin()
            self._board_stack.move(int(round(origin[0])), int(round(origin[1])))
            viewport = self._board_scroll.viewport()
            scroll = scroll_for_center(
                self._viewport.center(),
                (float(viewport.width()), float(viewport.height())),
                zoom,
            )
            applied = self._place_canvas_for_scroll(
                self._active_canvas(),
                (scroll[0] + origin[0], scroll[1] + origin[1]),
            )
            self._board_scroll.horizontalScrollBar().setValue(int(round(applied[0])))
            self._board_scroll.verticalScrollBar().setValue(int(round(applied[1])))
            self._set_zoom_percent(zoom_percent(zoom))
            self._apply_lod_chrome()
        finally:
            self._restoring_viewport = False
        self._persist_viewport_to_board()

    def _on_board_scrolled(self, _value: int = 0) -> None:
        self._persist_viewport_to_board()

    def set_board_zoom(self, zoom: float, cursor_in_viewport=None) -> None:
        viewport = self._board_scroll.viewport()
        if cursor_in_viewport is None:
            cursor_in_viewport = (viewport.width() / 2.0, viewport.height() / 2.0)
        self._zoom_at(zoom, cursor_in_viewport)

    def zoom_in(self) -> None:
        self.set_board_zoom(self._viewport.zoom() + ZOOM_BUTTON_STEP)

    def zoom_out(self) -> None:
        self.set_board_zoom(self._viewport.zoom() - ZOOM_BUTTON_STEP)

    def zoom_reset(self) -> None:
        self.set_board_zoom(1.0)

    def zoom_fit(self) -> None:
        self._filled_card = None
        canvas = self._active_canvas()
        fit = self._content_fit_rect()
        content = canvas.content_rect_1x()
        if content is None:
            size = canvas.unzoomed_size()
            self._park_zoom(
                fit_zoom(
                    (size.width(), size.height()),
                    (float(fit.width), float(fit.height)),
                )
            )
            return
        # Fit the placed-content box into the chrome-safe rect. zoom_to_card
        # uses the raw viewport so a double-click can bleed under the toolbar;
        # 适应 must keep cards inside the floating-chrome safe zone.
        zoom, center = zoom_to_rect(
            content, (float(fit.width), float(fit.height)), margin=FIT_CONTENT_MARGIN
        )
        self._apply_zoom_and_center(
            zoom, center, viewport_size=(float(fit.width), float(fit.height))
        )

    def _park_zoom(self, zoom: float) -> None:
        """Zoom and leave the board in the chrome-safe fit rect."""
        self.cancel_board_gestures()
        self._filled_card = None
        self._apply_preview_quality(QUALITY_FAST)
        after = clamp_zoom(zoom)
        self._broadcast_zoom(after)
        origin = self._fit_origin()
        self._board_stack.move(int(round(origin[0])), int(round(origin[1])))
        applied = self._place_canvas_for_scroll(self._active_canvas(), (0.0, 0.0))
        self._board_scroll.horizontalScrollBar().setValue(int(round(applied[0])))
        self._board_scroll.verticalScrollBar().setValue(int(round(applied[1])))
        self._set_zoom_percent(zoom_percent(after))
        self._apply_lod_chrome()
        self._restart_smooth_timer()
        self._persist_viewport_to_board()

    def _set_zoom_percent(self, percent: int) -> None:
        """Keep the legacy façade and the visible navigation island aligned."""
        self._toolbar.set_zoom_percent(percent)
        self._navigation_island.set_zoom_percent(percent)

    def _broadcast_zoom(self, zoom: float, *, viewport: bool = True) -> None:
        """Keep the viewport model and both Board render surfaces in sync."""
        if viewport:
            self._viewport.set_zoom(zoom)
        self._grid.set_zoom(zoom)
        self._free_grid.set_zoom(zoom)

    def zoom_to_card(self, section: str, view_id: str, *, animate: bool = True) -> None:
        rect_1x = self._card_rect_1x(section, view_id)
        if rect_1x is None:
            return
        self._filled_card = (str(section), str(view_id))
        viewport = self._board_scroll.viewport()
        zoom, center = zoom_to_rect(
            rect_1x, (float(viewport.width()), float(viewport.height()))
        )
        if animate:
            self._animate_viewport(zoom, center)
            return
        self._apply_zoom_and_center(zoom, center)

    def _current_center(self) -> tuple[float, float]:
        viewport = self._board_scroll.viewport()
        origin = self._board_content_origin()
        return center_from_scroll(
            (
                float(self._board_scroll.horizontalScrollBar().value()) - origin[0],
                float(self._board_scroll.verticalScrollBar().value()) - origin[1],
            ),
            (float(viewport.width()), float(viewport.height())),
            self._viewport.zoom(),
        )

    def _animate_viewport(self, zoom: float, center: tuple[float, float]) -> None:
        self._anim_start_zoom = self._viewport.zoom()
        self._anim_end_zoom = clamp_zoom(zoom)
        self._anim_start_center = self._current_center()
        self._anim_end_center = (float(center[0]), float(center[1]))
        self._zoom_anim.stop()
        self._zoom_anim.setStartValue(0.0)
        self._zoom_anim.setEndValue(1.0)
        self._zoom_anim.start()

    def _on_zoom_anim_tick(self, value) -> None:
        t = float(value)
        zoom = self._anim_start_zoom + (self._anim_end_zoom - self._anim_start_zoom) * t
        center = (
            self._anim_start_center[0]
            + (self._anim_end_center[0] - self._anim_start_center[0]) * t,
            self._anim_start_center[1]
            + (self._anim_end_center[1] - self._anim_start_center[1]) * t,
        )
        self._apply_zoom_and_center(zoom, center)

    def _apply_zoom_and_center(
        self,
        zoom: float,
        center: tuple[float, float],
        *,
        viewport_size: tuple[float, float] | None = None,
    ) -> None:
        self.cancel_board_gestures()
        self._apply_preview_quality(QUALITY_FAST)
        after = clamp_zoom(zoom)
        self._broadcast_zoom(after)
        self._viewport.set_center(center)
        origin = self._fit_origin()
        self._board_stack.move(int(round(origin[0])), int(round(origin[1])))
        if viewport_size is None:
            viewport = self._board_scroll.viewport()
            view = (float(viewport.width()), float(viewport.height()))
            scroll = scroll_for_center(center, view, after)
            desired = (scroll[0] + origin[0], scroll[1] + origin[1])
        else:
            view = (float(viewport_size[0]), float(viewport_size[1]))
            live = self._active_canvas().content_rect()
            if live is not None:
                # Canvas is already at ``after``; use live pixels so metric
                # rounding cannot drift the visual center off the safe zone.
                cx = live[0] + live[2] / 2.0
                cy = live[1] + live[3] / 2.0
                desired = (cx - view[0] / 2.0, cy - view[1] / 2.0)
            else:
                desired = scroll_for_center(center, view, after)
        applied = self._place_canvas_for_scroll(self._active_canvas(), desired)
        self._board_scroll.horizontalScrollBar().setValue(int(round(applied[0])))
        self._board_scroll.verticalScrollBar().setValue(int(round(applied[1])))
        self._set_zoom_percent(zoom_percent(after))
        self._apply_lod_chrome()
        self._restart_smooth_timer()
        self._persist_viewport_to_board()

    def _apply_lod_chrome(self) -> None:
        level = self._viewport.lod()
        show_title = bool(self._board.show_titles)
        show_source = bool(self._board.show_sources)
        for card in (*self._grid.card_widgets(), *self._free_grid.card_widgets()):
            card.apply_lod(
                level,
                show_title=show_title,
                show_source=show_source,
                presentation=self._presentation,
            )

    def note_space(self, down: bool) -> None:
        self._viewport.set_space_down(down)
        if down:
            self._board_scroll.viewport().setCursor(Qt.OpenHandCursor)
        elif not self._viewport.is_panning():
            self._board_scroll.viewport().unsetCursor()

    def begin_board_pan(self, event) -> bool:
        button = event.button()
        if button != Qt.MiddleButton and not (
            button == Qt.LeftButton and self._viewport.space_down()
        ):
            return False
        self.cancel_board_gestures()
        global_pos = _event_global_xy(event)
        self._viewport.begin_pan(global_pos, int(button))
        self._board_scroll.viewport().setCursor(Qt.ClosedHandCursor)
        self._apply_preview_quality(QUALITY_FAST)
        self._restart_smooth_timer()
        return True

    def update_board_pan(self, event) -> None:
        if not self._viewport.is_panning():
            return
        dx, dy = self._viewport.update_pan(_event_global_xy(event))
        horizontal = self._board_scroll.horizontalScrollBar()
        vertical = self._board_scroll.verticalScrollBar()
        horizontal.setValue(int(horizontal.value() + dx))
        vertical.setValue(int(vertical.value() + dy))
        self._restart_smooth_timer()

    def end_board_pan_for_event(self, event) -> bool:
        if not self._viewport.end_pan(int(event.button())):
            return False
        self._after_end_board_pan()
        return True

    def end_board_pan(self) -> None:
        if not self._viewport.end_pan(None):
            return
        self._after_end_board_pan()

    def _after_end_board_pan(self) -> None:
        if self._viewport.space_down():
            self._board_scroll.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self._board_scroll.viewport().unsetCursor()
        self._persist_viewport_to_board()
        self._restart_smooth_timer()

    def cancel_board_gestures(self) -> None:
        self._grid.cancel_gesture()
        self._free_grid.cancel_gesture()

    def handle_zoom_wheel(self, event: QWheelEvent, widget) -> bool:
        factor = wheel_zoom_factor(event.angleDelta().y(), event.pixelDelta().y())
        if factor == 1.0:
            return False
        cursor = self._cursor_in_scroll_viewport(event, widget)
        self._zoom_at(self._viewport.zoom() * factor, cursor)
        return True

    def handle_pinch(self, event: QNativeGestureEvent, widget) -> bool:
        if event.gestureType() != Qt.ZoomNativeGesture:
            return False
        cursor = self._cursor_in_scroll_viewport(event, widget)
        self._zoom_at(self._viewport.zoom() * (1.0 + float(event.value())), cursor)
        return True

    def _active_canvas(self):
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            return self._free_grid
        return self._grid

    def _zoom_at(self, zoom: float, cursor_in_viewport) -> None:
        self.cancel_board_gestures()
        self._filled_card = None
        self._apply_preview_quality(QUALITY_FAST)
        before = self._viewport.zoom()
        after = clamp_zoom(zoom)
        cursor = (float(cursor_in_viewport[0]), float(cursor_in_viewport[1]))
        scroll = (
            float(self._board_scroll.horizontalScrollBar().value()),
            float(self._board_scroll.verticalScrollBar().value()),
        )
        origin = self._board_content_origin()
        new_scroll = zoom_at(before, after, cursor, scroll, origin)
        self._broadcast_zoom(after)
        applied = self._place_canvas_for_scroll(self._active_canvas(), new_scroll)
        self._board_scroll.horizontalScrollBar().setValue(int(round(applied[0])))
        self._board_scroll.verticalScrollBar().setValue(int(round(applied[1])))
        self._set_zoom_percent(zoom_percent(after))
        self._apply_lod_chrome()
        self._restart_smooth_timer()
        self._persist_viewport_to_board()

    def _cursor_in_scroll_viewport(self, event, widget) -> tuple[float, float]:
        """Pick a viewport-local zoom anchor; never trust a degenerate (0, 0).

        Cocoa pinch/wheel often reports ``globalPosition() == (0, 0)`` *and*
        ``position() == (0, 0)``. Mapping that through the receiver lands on
        the widget origin, ``QScrollBar.setValue`` clamps to 0, and the board
        grows from the top-left. Prefer a non-zero global point, then a
        non-zero local point via ``widget.mapToGlobal`` (never
        ``viewport.mapFrom(descendant, …)``), then ``QCursor.pos()``.
        """
        viewport = self._board_scroll.viewport()
        view_rect = viewport.rect()

        def _if_inside(global_pos: QPoint) -> tuple[float, float] | None:
            mapped = viewport.mapFromGlobal(global_pos)
            if view_rect.contains(mapped):
                return (float(mapped.x()), float(mapped.y()))
            return None

        global_pos = _event_global_point(event)
        if not _is_origin_point(global_pos):
            found = _if_inside(global_pos)
            if found is not None:
                return found
        local = _event_local_point(event)
        if local is not None and widget is not None and not _is_origin_point(local):
            found = _if_inside(widget.mapToGlobal(local))
            if found is not None:
                return found
        found = _if_inside(QCursor.pos())
        if found is not None:
            return found
        return (viewport.width() / 2.0, viewport.height() / 2.0)

    def _apply_preview_quality(self, quality: str) -> None:
        self._viewport.set_quality(quality)
        self._grid.set_preview_quality(quality)
        self._free_grid.set_preview_quality(quality)

    def _restart_smooth_timer(self) -> None:
        self._smooth_timer.start(SMOOTH_DELAY_MS)

    def _on_viewport_resized(self, size) -> None:
        layout_size = self._board_layout_viewport_size(size)
        self._grid.set_viewport_size(layout_size)
        self._free_grid.set_viewport_size(layout_size)
        # QStackedWidget keeps the prior canvas size hint.  Once the floating
        # host gives the scroll area its final rect, propagate the active
        # canvas's new logical size back to the stack so first paint shows the
        # cards instead of an empty dotted stage.
        self._sync_board_stack_geometry(self._active_canvas())
        if self._pending_fit and self._board_scroll.viewport().width() > 1:
            self._pending_fit = False
            self.zoom_fit()
        self._refresh_card_context()

    def _on_smooth_preview_timeout(self) -> None:
        self._apply_preview_quality(QUALITY_SMOOTH)

    def focus_layer(self) -> FocusLayer:
        return self._focus

    def board(self) -> UltraViewBoardState:
        return self._board

    def set_workspace(self, workspace: Any) -> None:
        """Project a workspace through the active Board without owning it.

        The state owner is intentionally duck-typed here while P1 state code
        remains Qt-free.  This avoids a cycle and keeps the old ``set_board``
        test harness/API valid.
        """
        boards = tuple(getattr(workspace, "boards", ()) or ())
        active_id = str(getattr(workspace, "active_board_id", "") or "")
        self._workspace = workspace
        if self._switcher.isVisible():
            self._switcher.set_boards(boards, active_id)
            self._switcher.set_create_enabled(
                len(boards) < MAX_UI_BOARDS,
                "最多创建 20 个 Board" if len(boards) >= MAX_UI_BOARDS else "",
            )
        self._board_island.set_create_enabled(
            len(boards) < MAX_UI_BOARDS,
            "最多创建 20 个 Board" if len(boards) >= MAX_UI_BOARDS else "",
        )
        self._refresh_board_popover()
        active = next((board for board in boards if getattr(board, "board_id", None) == active_id), None)
        if active is None and boards:
            active = boards[0]
        if active is not None:
            self.set_board(active)

    def board_payload(self) -> dict[str, Any]:
        return board_to_payload(self._board)

    def compare_filter(self) -> str:
        return self._compare_filter

    def set_compare_filter(self, filter_id: str) -> None:
        wanted = str(filter_id or COMPARE_FILTER_ALL)
        self._compare_filter = wanted
        self._rail.set_filter_id(wanted)
        self._tool_rail.set_filter_active(wanted != COMPARE_FILTER_ALL)
        self._refresh_projection()

    def show_focus(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        record = self._previews.get(ref) if ref is not None else None
        title = getattr(record, "title", "") if record is not None else view_id
        image = preview_image(record)
        self._focus.setGeometry(self.rect())
        self._focus.show_ref(section, view_id, title or view_id, image)

    def set_focus_syncing(self, syncing: bool) -> None:
        self._focus.set_syncing(bool(syncing))

    def handle_card_double_click(self, section: str, view_id: str) -> None:
        """Layered double-click: fill the card, then open temporary inspect."""
        target = (str(section), str(view_id))
        if self._focus.isVisible():
            current = self._focus.current_ref()
            if current == target:
                return
            self._on_focus(section, view_id)
            return
        filled = self._card_fills_viewport(section, view_id) or self._filled_card == target
        armed = self._replacement_ref is not None or self._replacement_slot
        if filled and not armed:
            self._on_focus(section, view_id)
            return
        if filled and armed:
            return
        self.zoom_to_card(section, view_id)

    def _card_rect_1x(self, section: str, view_id: str):
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            card = self._free_grid.card_for(section, view_id)
            if card is None:
                return None
            current = max(self._viewport.zoom(), 1e-6)
            geom = card.geometry()
            return (
                geom.x() / current,
                geom.y() / current,
                geom.width() / current,
                geom.height() / current,
            )
        card = self._grid.card_for(section, view_id)
        if card is None:
            return None
        return self._grid.unzoomed_slot_rect(card.model().slot_id)

    def _card_fills_viewport(self, section: str, view_id: str) -> bool:
        rect_1x = self._card_rect_1x(section, view_id)
        if rect_1x is None:
            return False
        viewport = self._board_scroll.viewport()
        zoom, center = zoom_to_rect(
            rect_1x, (float(viewport.width()), float(viewport.height()))
        )
        current = self._current_center()
        return (
            abs(self._viewport.zoom() - zoom) <= 0.02
            and abs(current[0] - center[0]) <= 8.0
            and abs(current[1] - center[1]) <= 8.0
        )

    def replacement_slot(self) -> str | None:
        return self._replacement_slot

    def replacement_ref(self) -> tuple[str, str] | None:
        if self._replacement_ref is None:
            return None
        return self._replacement_ref.section, self._replacement_ref.view_id

    def selected_ref(self) -> tuple[str, str] | None:
        if self._selected is None:
            return None
        return self._selected.section, self._selected.view_id

    def clear_card_selection(self) -> bool:
        """Hide card-context chrome and drop every owner of View selection.

        Free-grid rings live on the gesture; the 5-icon island follows
        ``_selected``. Clearing only one owner leaves the other visible.
        Library row highlight stays: empty-slot place reads it.
        """
        grid_cleared = self._free_grid.clear_selection()
        had = self._selected is not None
        if not had and not grid_cleared:
            return False
        self._selected = None
        for card in self._grid.card_widgets():
            card.set_selected(False)
        self._refresh_card_context()
        return True

    def is_library_visible(self) -> bool:
        return self._library_visible

    def notify_canvas_click(self) -> None:
        """Blank-canvas press: close unpinned overlays, honoring drag deferral.

        CanvasHost.close_from_canvas_click() respects pin but not the
        library-drag deferral in ``_close_active_panel``; a drop press
        must not dismiss the library until ``_on_drag_finished``.
        """
        key = self._active_panel
        if key is not None and not self._canvas_host.overlay_closes_on_canvas(key):
            return
        self._close_active_panel(restore_focus=False)

    def is_presentation_active(self) -> bool:
        return self._presentation

    def card_widget(self, section: str, view_id: str):
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            return self._free_grid.card_for(section, view_id)
        return self._grid.card_for(section, view_id)

    def card_display_sizes(self) -> dict[UltraViewRef, tuple[int, int]]:
        sizes: dict[UltraViewRef, tuple[int, int]] = {}
        for card in self._active_canvas().card_widgets():
            model = card.model()
            sizes[UltraViewRef(model.section, model.view_id)] = card.preview_display_size()
        if self._focus.isVisible():
            current = self._focus.current_ref()
            if current is not None:
                ref = parse_ref_payload(
                    {"section": current[0], "view_id": current[1]}
                )
                if ref is not None:
                    sizes[ref] = self._focus.image_host_size()
        return sizes

    def slot_widget(self, slot_id: str):
        return self._grid.slot_widget(slot_id)

    def set_library_visible(self, visible: bool) -> None:
        if visible:
            self._open_panel(PANEL_LIBRARY)
            return
        if self._active_panel == PANEL_LIBRARY:
            self._close_active_panel()
        else:
            self._library_visible = False
            self._library.hide()

    def set_presentation_active(self, active: bool) -> None:
        wanted = bool(active)
        if self._presentation == wanted:
            return
        self._presentation = wanted
        self.setProperty("presentation", "true" if self._presentation else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._toolbar.set_presentation_checked(self._presentation)
        self._global_island.set_presentation_checked(self._presentation)
        self._toolbar.set_edit_visible(not self._presentation)
        if self._presentation:
            self._presentation_panel = self._active_panel
            self._canvas_host.close_active_overlay(restore_focus=False)
            self._library_visible = False
            self._board_island.hide()
            self._tool_rail.hide()
            self._status_island.hide()
            self._navigation_island.hide()
            self._card_context.hide()
            self._global_island.set_edit_visible(False)
            self._global_island.show()
            self._tray.body().setVisible(False)
            if (
                self._board.layout_mode == LAYOUT_MODE_FREE_GRID
                or len(layout_slots(self._board.layout_id)) >= 9
            ):
                self.show_overview()
        else:
            self.hide_overview()
            self._board_island.show()
            self._tool_rail.show()
            self._status_island.show()
            self._navigation_island.show()
            self._global_island.set_edit_visible(True)
            self._tray.body().setVisible(self._tray.is_expanded())
            restore_panel = self._presentation_panel
            self._presentation_panel = None
            if restore_panel is not None:
                self._open_panel(restore_panel)
            self._refresh_card_context()
        layout_size = self._board_layout_viewport_size()
        self._grid.set_viewport_size(layout_size)
        self._free_grid.set_viewport_size(layout_size)
        self._apply_lod_chrome()
        self._apply_floating_layout()

    def set_library_rows(self, rows: Sequence[LibraryRow | Mapping[str, Any]]) -> None:
        coerced = [coerce_library_row(row) for row in rows]
        if self._drag_kind is not None or self._projection_batch_depth:
            self._pending_library_rows = coerced
            return
        self._apply_library_rows(coerced)

    def _apply_library_rows(self, rows: Sequence[LibraryRow]) -> None:
        self._library.set_rows(rows)
        self._library.set_on_board(membership_set(self._board))

    def _flush_projection_batch(self) -> None:
        """Apply one deferred projection, unless a drag owns widget lifetime."""
        if self._projection_batch_depth:
            return
        if self._drag_kind is not None:
            if self._projection_dirty:
                self._board_widgets_dirty = True
            return
        pending_rows = self._pending_library_rows
        self._pending_library_rows = None
        if pending_rows is not None:
            self._apply_library_rows(pending_rows)
        dirty = self._projection_dirty
        self._projection_dirty = False
        pending_viewport = self._pending_viewport_restore
        self._pending_viewport_restore = None
        if dirty:
            if pending_viewport is not None:
                self._restoring_viewport = True
                try:
                    self._refresh_projection()
                finally:
                    self._restoring_viewport = False
            else:
                self._refresh_projection()
        if pending_viewport is not None:
            self._restore_viewport_from_board(
                self._board, payload=pending_viewport
            )

    def set_preview(self, ref: UltraViewRef | Mapping[str, Any], record_like: Any) -> None:
        parsed = ref if isinstance(ref, UltraViewRef) else parse_ref_payload(ref)
        if parsed is None:
            return
        if self._previews.get(parsed) is record_like:
            return
        self._previews[parsed] = record_like
        self._refresh_projection()

    def set_ref_status(
        self,
        ref: UltraViewRef | Mapping[str, Any],
        status: str,
        ref_exists: bool,
    ) -> None:
        parsed = ref if isinstance(ref, UltraViewRef) else parse_ref_payload(ref)
        if parsed is None:
            return
        status_s = str(status)
        exists_b = bool(ref_exists)
        if (
            self._statuses.get(parsed) == status_s
            and self._ref_exists.get(parsed) == exists_b
        ):
            return
        self._statuses[parsed] = status_s
        self._ref_exists[parsed] = exists_b
        self._refresh_projection()

    def apply_preview_and_status(
        self,
        ref: UltraViewRef | Mapping[str, Any],
        record_like: Any,
        status: str,
        ref_exists: bool,
    ) -> None:
        """Apply preview record and status in one projection (UVL-A08).

        Tests that call ``set_preview`` / ``set_ref_status`` still refresh
        synchronously so they can read ``card_widget`` without pumping
        events. Coordinator idle/publish uses this combined entry so the
        pair does not rebuild the board twice.
        """
        parsed = ref if isinstance(ref, UltraViewRef) else parse_ref_payload(ref)
        if parsed is None:
            return
        changed = False
        if record_like is not None and self._previews.get(parsed) is not record_like:
            self._previews[parsed] = record_like
            changed = True
        status_s = str(status)
        exists_b = bool(ref_exists)
        if (
            self._statuses.get(parsed) != status_s
            or self._ref_exists.get(parsed) != exists_b
        ):
            self._statuses[parsed] = status_s
            self._ref_exists[parsed] = exists_b
            changed = True
        if changed:
            self._refresh_projection()

    def clear_runtime_caches(self) -> None:
        """Drop page-local preview shadows so they cannot outlive the store."""
        self._previews.clear()
        self._statuses.clear()
        self._ref_exists.clear()
        self._refresh_projection()

    def _prune_runtime_caches(self) -> None:
        keep = membership_set(self._board)
        self._previews = {ref: value for ref, value in self._previews.items() if ref in keep}
        self._statuses = {ref: value for ref, value in self._statuses.items() if ref in keep}
        self._ref_exists = {ref: value for ref, value in self._ref_exists.items() if ref in keep}

    def set_board(self, board: UltraViewBoardState) -> None:
        keep_overview = (
            self._overview.isVisible()
            and self._board.board_id == board.board_id
        )
        switching = board.board_id != self._board.board_id
        if switching:
            self._persist_viewport_to_board()
        incoming_viewport = dict(getattr(board, "viewport", None) or {})
        if not keep_overview:
            self.hide_overview()
        if self._workspace is None and self._switcher.isVisible():
            self._switcher.set_boards((board,), board.board_id)
        layout_viewport = self._board_layout_viewport_size()
        self._grid.set_viewport_size(layout_viewport)
        self._free_grid.set_viewport_size(layout_viewport)
        prev = self._prev_unplaced_count
        previous_fingerprint = self._prev_layout_fingerprint
        self._board = board
        self._prune_runtime_caches()
        n_unplaced = len(board.unplaced)
        fingerprint = (str(board.layout_id), str(board.layout_mode))
        overflow_from_layout_shrink = (
            not switching
            and prev is not None
            and n_unplaced > prev
            and previous_fingerprint is not None
            and previous_fingerprint != fingerprint
        )
        if overflow_from_layout_shrink:
            self._tray.set_expanded(True)
            QTimer.singleShot(0, self._open_unplaced_after_layout_overflow)
        self._prev_unplaced_count = n_unplaced
        self._prev_layout_fingerprint = fingerprint
        if self._replacement_ref is not None and self._replacement_ref not in membership_set(board):
            self._replacement_ref = None
            self._replacement_slot = None
        elif self._replacement_slot and self._replacement_slot not in layout_slots(board.layout_id):
            self._replacement_slot = None
        self._toolbar.set_board_name(board.name)
        self._toolbar.set_layout_id(board.layout_id)
        self._toolbar.set_free_grid_enabled(board.layout_mode == LAYOUT_MODE_FREE_GRID)
        self._toolbar.set_show_flags(board.show_titles, board.show_sources)
        self._board_island.set_current_board(board.board_id, board.name)
        blocked = self._display_titles.blockSignals(True)
        self._display_titles.setChecked(bool(board.show_titles))
        self._display_titles.blockSignals(blocked)
        blocked = self._display_sources.blockSignals(True)
        self._display_sources.setChecked(bool(board.show_sources))
        self._display_sources.blockSignals(blocked)
        self._tool_rail.set_badge(PANEL_UNPLACED, n_unplaced)
        self._sync_layout_popover()
        if self._drag_kind is not None:
            # Drop handlers mutate the board inside QDrag.exec_(). Rebuilding
            # library/grid/tray here would deleteLater the drag source before
            # mouseMoveEvent returns, which aborts via qFatal.
            self._board_widgets_dirty = True
            if switching:
                self._pending_viewport_restore = incoming_viewport
            self._sync_empty_board_cue()
            return
        self._library.set_on_board(membership_set(board))
        if switching and self._projection_batch_depth:
            self._pending_viewport_restore = incoming_viewport
            self._refresh_projection()
        elif switching:
            self._restoring_viewport = True
            try:
                self._refresh_projection()
            finally:
                self._restoring_viewport = False
            self._restore_viewport_from_board(board, payload=incoming_viewport)
        else:
            self._refresh_projection()
        self._set_zoom_percent(zoom_percent(self._viewport.zoom()))
        self._apply_floating_layout()

    def _open_unplaced_after_layout_overflow(self) -> None:
        if self._presentation or not self._board.unplaced:
            return
        self._open_panel(PANEL_UNPLACED)
        self._tray.focus_first_item()

    def show_overview(self) -> None:
        """Show a scaled, read-only full Board projection without capture."""
        self._refresh_projection()
        self._overview.setGeometry(self._board_scroll.geometry())
        self._overview.raise_()
        self._overview.show()
        self._overview.setFocus(Qt.OtherFocusReason)
        self._sync_empty_board_cue()

    def hide_overview(self) -> None:
        if self._overview.isVisible():
            self._overview.hide()
            self._sync_empty_board_cue()

    def _on_overview_slot(self, slot_id: str) -> None:
        self.hide_overview()
        widget = self._grid.slot_widget(slot_id)
        if widget is not None:
            self._board_scroll.ensureWidgetVisible(widget, 24, 24)
            widget.setFocus(Qt.OtherFocusReason)

    def _on_overview_ref(self, section: str, view_id: str) -> None:
        self.hide_overview()
        widget = self._free_grid.card_for(section, view_id)
        if widget is not None:
            self._board_scroll.ensureWidgetVisible(widget, 24, 24)
            widget.setFocus(Qt.OtherFocusReason)

    def _on_board_selected(self, board_id: str) -> None:
        self._close_active_panel(restore_focus=False)
        self._card_context.clear_ref()
        self.reset_sheet_session(emit_presentation=False)
        self.select_board_requested.emit(board_id)

    def request_add(self, section: str, view_id: str) -> None:
        self._emit_add(section, view_id)

    def arm_replacement(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None or self._board is None:
            return
        if ref not in membership_set(self._board):
            return
        placement = placement_for(self._board, ref)
        self._replacement_ref = ref
        self._replacement_slot = None if placement is None else placement.slot_id
        self._open_library_for_pick()
        self.rebind_arm_requested.emit(section, view_id)
        self._refresh_projection()

    def clear_replacement_arm(self) -> None:
        if self._replacement_slot is None and self._replacement_ref is None:
            return
        self._replacement_slot = None
        self._replacement_ref = None
        self._refresh_projection()

    def reset_sheet_session(self, *, emit_presentation: bool = True) -> None:
        """Leave focus / replacement / presentation before the tool window closes."""
        if self._focus.isVisible():
            self._focus.close_layer()
        self._close_active_panel()
        self.clear_card_selection()
        self.clear_replacement_arm()
        if self._presentation:
            self.set_presentation_active(False)
            if emit_presentation:
                self.presentation_toggled.emit(False)

    def _on_escape_shortcut(self) -> None:
        if self._text_field_has_focus():
            return
        self.handle_escape()

    def _on_grid_undo_shortcut(self) -> None:
        if self._text_field_has_focus():
            return
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID and not self._focus.isVisible():
            self.free_grid_undo_requested.emit()

    def _on_grid_redo_shortcut(self) -> None:
        if self._text_field_has_focus():
            return
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID and not self._focus.isVisible():
            self.free_grid_redo_requested.emit()

    def _text_field_has_focus(self) -> bool:
        return isinstance(QApplication.focusWidget(), QLineEdit)

    def _on_app_focus_changed(self, _old, now) -> None:
        in_edit = isinstance(now, QLineEdit)
        self._esc.setEnabled(not in_edit)
        self._grid_undo.setEnabled(not in_edit)
        self._grid_redo.setEnabled(not in_edit)
        if in_edit:
            self.note_space(False)
        # ``now is None`` also fires for transient, non-deactivation reasons
        # (a popup hiding/destroying mid-interaction) and would cancel an
        # in-progress drag out from under the user.  Real window deactivation
        # is already covered by changeEvent(WindowDeactivate) and hideEvent,
        # both of which call _cancel_board_gestures() themselves.

    def handle_escape(self) -> bool:
        if self._viewport.is_panning():
            self.end_board_pan()
            return True
        if self._grid.cancel_gesture():
            return True
        if self._free_grid.cancel_gesture():
            return True
        if self._focus.isVisible():
            self._focus.close_layer()
            return True
        if self._overview.isVisible():
            self.hide_overview()
            return True
        if self._active_panel is not None:
            self._close_active_panel()
            return True
        if self._replacement_slot is not None or self._replacement_ref is not None:
            self.clear_replacement_arm()
            return True
        if self._presentation:
            self.set_presentation_active(False)
            self.presentation_toggled.emit(False)
            return True
        popup = QApplication.activePopupWidget()
        if isinstance(popup, QMenu) and popup.isVisible():
            popup.close()
            return True
        if self.clear_card_selection():
            return True
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802
        if self._grid.is_gesture_active():
            self._grid.cancel_gesture()
        if self._free_grid.gesture().is_active():
            self._free_grid.cancel_gesture()
        super().resizeEvent(event)
        self._focus.setGeometry(self.rect())
        self._apply_floating_layout()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._canvas_host and event.type() == QEvent.Resize:
            # The host receives its final geometry after the Page layout pass;
            # defer one turn so we never size the scroll viewport from stale
            # 0x0/previous dimensions during a tool-window resize.
            QTimer.singleShot(0, self._apply_floating_layout)
        elif (
            getattr(self, "_board_scroll", None) is not None
            and watched is self._board_scroll.viewport()
            and event.type() == QEvent.MouseButtonPress
            and self._active_panel is not None
        ):
            self._close_active_panel(restore_focus=False)
        elif (
            getattr(self, "_board_host", None) is not None
            and watched is self._board_host
            and event.type() == QEvent.MouseButtonPress
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.LeftButton
        ):
            self.clear_card_selection()
        return super().eventFilter(watched, event)

    def _cancel_board_gestures(self) -> None:
        if self._viewport.is_panning():
            self.end_board_pan()
        if self._grid.is_gesture_active():
            self._grid.cancel_gesture()
        if self._free_grid.gesture().is_active():
            self._free_grid.cancel_gesture()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowDeactivate:
            self.note_space(False)
            self._cancel_board_gestures()
        super().changeEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.note_space(False)
        self._cancel_board_gestures()
        super().hideEvent(event)

    def _on_drag_started(self, kind: str) -> None:
        self._drag_kind = kind
        if kind == "card":
            self._card_context.hide()

    def _on_drag_finished(self) -> None:
        self._drag_kind = None
        self._flush_deferred_drag_refresh()
        if self._deferred_panel_close is not None:
            self._deferred_panel_close = None
            self._close_active_panel()
        self._refresh_card_context()

    def _flush_deferred_drag_refresh(self) -> None:
        pending_rows = self._pending_library_rows
        self._pending_library_rows = None
        dirty = self._board_widgets_dirty or self._projection_dirty
        self._board_widgets_dirty = False
        self._projection_dirty = False
        pending_viewport = self._pending_viewport_restore
        self._pending_viewport_restore = None
        if pending_rows is not None:
            self._apply_library_rows(pending_rows)
        elif dirty:
            self._library.set_on_board(membership_set(self._board))
        if dirty:
            if pending_viewport is not None:
                self._restoring_viewport = True
                try:
                    self._refresh_projection()
                finally:
                    self._restoring_viewport = False
            else:
                self._refresh_projection()
        if pending_viewport is not None:
            self._restore_viewport_from_board(self._board, payload=pending_viewport)

    def _emit_feedback(self, message: str) -> None:
        self.feedback_requested.emit(message)

    def _open_library_for_pick(self) -> None:
        if self._presentation:
            return
        self._open_panel(PANEL_LIBRARY)
        self._library.focus_search()

    def _on_toolbar_add(self) -> None:
        selected = self._library.selected_ref()
        if selected is None:
            self._open_library_for_pick()
            self._emit_feedback(_FEEDBACK_NO_SELECTION)
            return
        self._emit_add(selected[0], selected[1])

    def _on_empty_slot(self, slot_id: str) -> None:
        self.clear_card_selection()
        selected = self._library.selected_ref()
        if selected is None:
            self._open_library_for_pick()
            self._emit_feedback(_FEEDBACK_NO_SELECTION)
            return
        if self._replacement_ref is not None or self._replacement_slot:
            # UVL-A01: armed completion still wins over empty-slot place.
            # Tray-armed refs have no slot; bind the clicked empty slot as
            # the replace target. A board-armed slot is left unchanged so
            # the click does not retarget a different occupant.
            if self._replacement_slot is None:
                self._replacement_slot = slot_id
            self._finish_armed_replacement(selected[0], selected[1])
            return
        self.replace_slot_requested.emit(slot_id, selected[0], selected[1])

    def _on_locate(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            self._select_ref(ref)
        self.locate_ref_requested.emit(section, view_id)

    def _on_card_selected(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            self._select_ref(ref)

    def _on_focus(self, section: str, view_id: str) -> None:
        self.show_focus(section, view_id)
        self.focus_requested.emit(section, view_id)

    def _on_rebind_arm(self, section: str, view_id: str) -> None:
        self.arm_replacement(section, view_id)

    def _on_presentation_button(self, checked: bool) -> None:
        self.set_presentation_active(checked)
        self.presentation_toggled.emit(checked)

    def _on_compare_filter(self, filter_id: str) -> None:
        self._compare_filter = filter_id
        self._tool_rail.set_filter_active(filter_id != COMPARE_FILTER_ALL)
        self.compare_filter_changed.emit(filter_id)
        self._refresh_projection()

    def _on_tray_place(self, section: str, view_id: str) -> None:
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self.place_free_grid_from_unplaced_requested.emit(section, view_id)
            return
        slot = first_empty_slot(self._board)
        if slot is None:
            self._emit_feedback(_FEEDBACK_BOARD_FULL)
            return
        self.place_from_unplaced_requested.emit(slot, section, view_id)

    def _on_tray_drop(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        if placement_for(self._board, ref) is not None or free_grid_placement_for(self._board, ref) is not None:
            self.move_to_unplaced_requested.emit(section, view_id)

    def _on_free_grid_ref_dropped(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        if ref in self._board.unplaced:
            self.place_free_grid_from_unplaced_requested.emit(section, view_id)
        elif ref not in membership_set(self._board):
            self.add_ref_requested.emit(section, view_id)
        else:
            self._on_locate(section, view_id)

    def _on_ref_dropped(self, slot_id: str, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        kind = self._drag_kind
        armed = self._replacement_ref is not None or self._replacement_slot
        if armed and kind in ("card", "tray"):
            # UVL-A03: card swap / tray place are board mutations, not a
            # library completion of the armed replacement. Drop the arm
            # first, then continue the normal swap/place flow.
            self.clear_replacement_arm()
        elif armed:
            if ref in membership_set(self._board) and kind == "library":
                self._on_locate(section, view_id)
                return
            if ref not in membership_set(self._board) or kind in (None, "library"):
                if ref in membership_set(self._board):
                    self._on_locate(section, view_id)
                    return
                self._finish_armed_replacement(section, view_id)
                return
        in_tray = ref in self._board.unplaced
        placed = placement_for(self._board, ref)
        if kind == "library" or (kind is None and placed is None and not in_tray):
            if ref in membership_set(self._board):
                self._on_locate(section, view_id)
                return
            occupant = slot_occupant(self._board, slot_id)
            if occupant is None:
                self.add_ref_requested.emit(section, view_id)
            else:
                self.replace_slot_requested.emit(slot_id, section, view_id)
            return
        if kind == "tray" or (kind is None and in_tray):
            self.place_from_unplaced_requested.emit(slot_id, section, view_id)
            return
        if placed is not None:
            if placed.slot_id == slot_id:
                self._select_ref(ref)
                return
            self.swap_slots_requested.emit(placed.slot_id, slot_id)
            return
        if in_tray:
            self.place_from_unplaced_requested.emit(slot_id, section, view_id)
            return
        occupant = slot_occupant(self._board, slot_id)
        if occupant is None:
            self.add_ref_requested.emit(section, view_id)
        else:
            self.replace_slot_requested.emit(slot_id, section, view_id)

    def _emit_add(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        if ref in membership_set(self._board):
            self._on_locate(section, view_id)
            return
        if self._replacement_ref is not None or self._replacement_slot:
            self._finish_armed_replacement(section, view_id)
            return
        self.add_ref_requested.emit(section, view_id)

    def _finish_armed_replacement(self, section: str, view_id: str) -> None:
        old = self._replacement_ref
        slot = self._replacement_slot
        self.clear_replacement_arm()
        if old is not None and self._status_for(old) == STATUS_ORPHANED:
            self.rebind_ref_requested.emit(
                old.section, old.view_id, section, view_id
            )
            return
        if slot:
            self.replace_slot_requested.emit(slot, section, view_id)

    def _select_ref(self, ref: UltraViewRef) -> None:
        self._selected = ref
        self._library.set_selected(ref.section, ref.view_id)
        if ref in self._board.unplaced:
            self._open_panel(PANEL_UNPLACED)
            self._tray.focus_first_item()
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self._free_grid.select_only(ref.section, ref.view_id)
        self._refresh_projection()
        self.selection_changed.emit(ref.section, ref.view_id)

    def select_ref(self, ref: UltraViewRef) -> None:
        """Select a Board reference for coordinator-driven locate actions."""
        self._select_ref(ref)

    def _status_for(self, ref: UltraViewRef) -> str:
        if ref in self._statuses:
            return self._statuses[ref]
        exists = self._ref_exists.get(ref, True)
        record = self._previews.get(ref)
        image_valid = preview_image(record) is not None
        captured = getattr(record, "captured_digest", None) if record is not None else None
        return derive_preview_status(exists, image_valid, captured, None)

    def _library_row_for(self, ref: UltraViewRef):
        for row in self._library.row_widgets():
            item = row.row()
            if item.section == ref.section and item.view_id == ref.view_id:
                return item
        return None

    def _chrome_value(
        self,
        ref: UltraViewRef,
        *,
        lib_attr: str,
        record_attr: str,
        default: str = "",
    ) -> str:
        live = self._ref_exists.get(ref, True)
        lib = self._library_row_for(ref)
        record = self._previews.get(ref)
        lib_val = str(getattr(lib, lib_attr, "") or "") if lib is not None else ""
        rec_val = (
            str(getattr(record, record_attr, "") or "") if record is not None else ""
        )
        if live:
            return lib_val or rec_val or default
        return rec_val or lib_val or default

    def _title_for(self, ref: UltraViewRef) -> str:
        return self._chrome_value(
            ref, lib_attr="name", record_attr="title", default=ref.view_id
        )

    def _color_for(self, ref: UltraViewRef) -> str:
        return self._chrome_value(ref, lib_attr="tab_color", record_attr="tab_color")

    def _source_for(self, ref: UltraViewRef) -> str:
        return self._chrome_value(
            ref, lib_attr="source_summary", record_attr="source_summary"
        )

    def _axis_for(self, ref: UltraViewRef) -> str | None:
        record = self._previews.get(ref)
        if record is None:
            return None
        kind = getattr(record, "axis_kind", None)
        return str(kind) if kind else None

    def _sync_overview(self) -> None:
        records = {}
        statuses = {}
        for ref in membership_set(self._board):
            records[ref] = self._previews.get(ref)
            statuses[ref] = self._status_for(ref)
        self._overview.set_projection(self._board, records, statuses)

    def _refresh_projection(self) -> None:
        if self._projection_batch_depth:
            self._projection_dirty = True
            return
        if self._drag_kind is not None:
            self._board_widgets_dirty = True
            return
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self._grid.clear_projection()
            self._refresh_free_grid_projection()
            return
        if self._free_grid.card_widgets():
            self._free_grid.set_free_grid([], {})
        self._minimap.hide()
        self._board_stack.setCurrentWidget(self._grid)
        models: dict[str, CardViewModel | None] = {}
        axis_records = []
        for slot_id in layout_slots(self._board.layout_id):
            ref = slot_occupant(self._board, slot_id)
            if ref is None:
                models[slot_id] = None
                continue
            record = self._previews.get(ref)
            status = self._status_for(ref)
            axis_kind = self._axis_for(ref)
            x_unit = str(getattr(record, "x_unit", "") or "") if record is not None else ""
            raw_range = getattr(record, "x_range", None) if record is not None else None
            x_range = None
            if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
                try:
                    x_range = (float(raw_range[0]), float(raw_range[1]))
                except (TypeError, ValueError):
                    x_range = None
            if axis_kind:
                axis_records.append(
                    {"axis_kind": axis_kind, "x_unit": x_unit, "x_range": x_range}
                )
            models[slot_id] = CardViewModel(
                slot_id=slot_id,
                section=ref.section,
                view_id=ref.view_id,
                title=self._title_for(ref),
                tab_color=self._color_for(ref),
                status=status,
                source_summary=self._source_for(ref),
                axis_kind=axis_kind,
                x_unit=x_unit,
                x_range=x_range,
                image=preview_image(record),
                selected=self._selected == ref,
                dimmed=not card_matches_compare_filter(axis_kind, self._compare_filter),
                replacement_armed=(
                    self._replacement_ref == ref
                    or self._replacement_slot == slot_id
                ),
                show_title=bool(self._board.show_titles),
                show_source=bool(self._board.show_sources),
            )
        self._grid.set_grid(self._board.layout_id, self._board.primary_ratio, models)
        self._sync_board_stack_geometry(self._grid)
        self._apply_lod_chrome()
        self._sync_overview()
        titles = {}
        colors = {}
        statuses = {}
        for ref in self._board.unplaced:
            key = (ref.section, ref.view_id)
            titles[key] = self._title_for(ref)
            colors[key] = self._color_for(ref)
            statuses[key] = self._status_for(ref)
        self._tray.set_refs(
            self._board.unplaced,
            titles=titles,
            colors=colors,
            statuses=statuses,
            armed=self._replacement_ref,
        )
        facts = axis_consistency_facts(axis_records)
        warnings = []
        if facts.unit_inconsistent_kinds:
            warnings.append("量纲不一致")
        if facts.range_inconsistent_kinds:
            warnings.append("X 范围不一致")
        self._rail.set_axis_warning(" · ".join(warnings))
        self._sync_transient_chrome(warnings)
        self._focus.setGeometry(self.rect())

    def _sync_transient_chrome(self, warnings: Sequence[str]) -> None:
        self._tool_rail.set_badge(PANEL_UNPLACED, len(self._board.unplaced))
        self._tool_rail.set_stale_count(self._stale_ref_count())
        self._tool_rail.set_filter_active(self._compare_filter != COMPARE_FILTER_ALL)
        self._tool_rail.set_filter_warning(bool(warnings))
        warning_text = " · ".join(warnings)
        if warning_text:
            self._status_island.set_status(f"只读预览 · 不计算 · {warning_text}", level="warning")
        else:
            self._status_island.set_status("只读预览 · 不计算")
        self._refresh_card_context()

    def _refresh_card_context(self) -> None:
        """Card actions now live on each card; the floating island stays hidden."""
        self._card_context.clear_ref()

    def _card_model(self, ref: UltraViewRef, *, slot_id: str) -> CardViewModel:
        record = self._previews.get(ref)
        status = self._status_for(ref)
        axis_kind = self._axis_for(ref)
        x_unit = str(getattr(record, "x_unit", "") or "") if record is not None else ""
        raw_range = getattr(record, "x_range", None) if record is not None else None
        x_range = None
        if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
            try:
                x_range = (float(raw_range[0]), float(raw_range[1]))
            except (TypeError, ValueError):
                x_range = None
        return CardViewModel(
            slot_id=slot_id,
            section=ref.section,
            view_id=ref.view_id,
            title=self._title_for(ref),
            tab_color=self._color_for(ref),
            status=status,
            source_summary=self._source_for(ref),
            axis_kind=axis_kind,
            x_unit=x_unit,
            x_range=x_range,
            image=preview_image(record),
            selected=self._selected == ref,
            dimmed=not card_matches_compare_filter(axis_kind, self._compare_filter),
            replacement_armed=self._replacement_ref == ref,
            show_title=bool(self._board.show_titles),
            show_source=bool(self._board.show_sources),
        )

    def _refresh_free_grid_projection(self) -> None:
        models = {
            item.ref: self._card_model(item.ref, slot_id=f"grid:{item.ref.section}:{item.ref.view_id}")
            for item in self._board.free_grid
        }
        self._board_stack.setCurrentWidget(self._free_grid)
        self._free_grid.set_free_grid(self._board.free_grid, models)
        self._sync_board_stack_geometry(self._free_grid)
        self._apply_lod_chrome()
        titles = {}
        colors = {}
        statuses = {}
        axis_records = []
        for item in self._board.free_grid:
            ref = item.ref
            model = models[ref]
            if model.axis_kind:
                axis_records.append({"axis_kind": model.axis_kind, "x_unit": model.x_unit, "x_range": model.x_range})
        for ref in self._board.unplaced:
            key = (ref.section, ref.view_id)
            titles[key] = self._title_for(ref)
            colors[key] = self._color_for(ref)
            statuses[key] = self._status_for(ref)
        self._tray.set_refs(self._board.unplaced, titles=titles, colors=colors, statuses=statuses, armed=self._replacement_ref)
        facts = axis_consistency_facts(axis_records)
        warnings = []
        if facts.unit_inconsistent_kinds:
            warnings.append("量纲不一致")
        if facts.range_inconsistent_kinds:
            warnings.append("X 范围不一致")
        self._rail.set_axis_warning(" · ".join(warnings))
        self._sync_transient_chrome(warnings)
        self._sync_overview()
        self._focus.setGeometry(self.rect())

    def _place_canvas_for_scroll(
        self, canvas: QWidget, desired_scroll: tuple[float, float]
    ) -> tuple[float, float]:
        """Lay out the canvas so ``desired_scroll`` is a valid scrollbar value.

        Negative desired scroll becomes left/top pad on the stack; a desired
        value past the current max grows the host.  Must run after the canvas
        has the new zoom, and must not be followed by a fit-center pass.
        When the board still fits the viewport this is what keeps the cursor
        anchor from collapsing onto the chrome-safe corner (the top-left of
        ``fit``, which sits right of the rail — the "zooms toward the
        top-right" report).
        """
        target = canvas.size()
        if target.width() <= 0 or target.height() <= 0:
            target = canvas.minimumSize()
        origin_x, origin_y = self._board_content_origin()
        viewport = self._board_scroll.viewport().size()
        view_w = max(1, viewport.width())
        view_h = max(1, viewport.height())
        canvas_w = max(1, int(target.width()))
        canvas_h = max(1, int(target.height()))
        desired_x, desired_y = float(desired_scroll[0]), float(desired_scroll[1])
        pad_x = max(0.0, -desired_x)
        pad_y = max(0.0, -desired_y)
        stack_x = int(round(origin_x + pad_x))
        stack_y = int(round(origin_y + pad_y))
        applied_x = desired_x + pad_x
        applied_y = desired_y + pad_y
        host_w = max(stack_x + canvas_w, view_w, int(math.ceil(applied_x + view_w)))
        host_h = max(stack_y + canvas_h, view_h, int(math.ceil(applied_y + view_h)))
        self._board_stack.setMinimumSize(target)
        self._board_stack.resize(target)
        self._board_stack.move(stack_x, stack_y)
        self._board_host.setMinimumSize(host_w, host_h)
        self._board_host.resize(host_w, host_h)
        return (applied_x, applied_y)

    def _sync_board_stack_geometry(self, canvas: QWidget) -> None:
        """Keep the scroll host sized to the current logical canvas.

        QStackedWidget's size hint is the maximum of both canvas modes.  The
        Board scroll contract instead needs the active canvas's exact logical
        size, or a 12-card template stops producing scroll bars after a mode
        switch.  Preserve the current stack origin (including zoom pad); Fit
        and restore park explicitly before calling ``_place_canvas_for_scroll``.
        """
        scroll = (
            float(self._board_scroll.horizontalScrollBar().value()),
            float(self._board_scroll.verticalScrollBar().value()),
        )
        self._place_canvas_for_scroll(canvas, scroll)

    def _minimap_should_show(self) -> bool:
        if self._board.layout_mode != LAYOUT_MODE_FREE_GRID:
            return False
        if self._presentation or self._overview.isVisible():
            return False
        if self._active_panel is not None:
            return False
        horizontal = self._board_scroll.horizontalScrollBar()
        vertical = self._board_scroll.verticalScrollBar()
        return int(horizontal.maximum()) > int(horizontal.minimum()) or int(
            vertical.maximum()
        ) > int(vertical.minimum())

    def _position_minimap(self, floating=None) -> None:
        if not self._minimap.isVisible():
            return
        layout = floating if floating is not None else self._floating_layout()
        if layout.minimap is None:
            self._minimap.hide()
            return
        viewport = self._board_scroll.viewport()
        global_point = self._canvas_host.mapToGlobal(QPoint(layout.minimap.x, layout.minimap.y))
        local_point = viewport.mapFromGlobal(global_point)
        self._minimap.move(local_point)
        self._minimap.raise_()

    def _refresh_minimap(self, *_args) -> None:
        if not self._minimap_should_show():
            self._minimap.hide()
            return
        viewport = self._board_scroll.viewport()
        origin = self._board_content_origin()
        self._minimap.set_projection(
            self._free_grid.metrics(),
            self._board.free_grid,
            QRect(
                int(round(self._board_scroll.horizontalScrollBar().value() - origin[0])),
                int(round(self._board_scroll.verticalScrollBar().value() - origin[1])),
                viewport.width(),
                viewport.height(),
            ),
        )
        self._minimap.show()
        self._position_minimap()

    def _on_minimap_viewport(self, rect: QRect) -> None:
        origin = self._board_content_origin()
        horizontal = self._board_scroll.horizontalScrollBar()
        vertical = self._board_scroll.verticalScrollBar()
        horizontal.setValue(
            min(horizontal.maximum(), max(horizontal.minimum(), int(round(rect.x() + origin[0]))))
        )
        vertical.setValue(
            min(vertical.maximum(), max(vertical.minimum(), int(round(rect.y() + origin[1]))))
        )
