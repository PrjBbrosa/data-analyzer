"""Standalone UltraView page: View library, board grid, cards, overflow tray.

The page is a view. Coordinator / test harness apply intents by mutating
``UltraViewBoardState`` and calling ``set_board``. This module does not import
MainWindow or analysis compute entry points.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from typing import Any, Mapping, Sequence
import math
import time

from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import (
    QContextMenuEvent,
    QCursor,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QNativeGestureEvent,
    QTabletEvent,
    QWheelEvent,
)
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QShortcut,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome
from mf4_analyzer.ui.ultraview_state import (
    COMPARE_FILTER_ALL,
    STATUS_ORPHANED,
    STATUS_STALE,
    ULTRAVIEW_PAGE_OBJECT_NAME,
    UltraViewBoardState,
    UltraViewRef,
    GridBounds,
    GridAnchor,
    axis_consistency_facts,
    all_refs,
    best_template_for,
    board_to_payload,
    default_board,
    first_empty_slot,
    free_grid_placement_for,
    free_grid_default_span,
    layout_capacity,
    layout_slots,
    AnchorTarget,
    BoardBox,
    BoardPoint,
    ConnectorObject,
    LAYOUT_MODE_FREE_GRID,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
    UnknownAuthorObject,
    LAYOUT_SLOTS,
    MAX_UI_BOARDS,
    membership_set,
    parse_ref_payload,
    placed_ref_set,
    placement_for,
    slot_occupant,
)
from .viewport import (
    BoardViewport,
    two_card_working_frame,
    zoom_percent,
    zoom_to_rect,
)
from .elastic_workspace import (
    EDGE_PAN_BAND_PX,
    content_bounds,
    desired_extent,
    expand_extent,
    safety_grid_bounds,
)
from .floating_layout import RAIL_WIDTH, SAFE_MARGIN
from .feedback import (
    AUTHOR_LOCKED,
    CONTINUE_EXPAND,
    SAFETY_BOUNDS,
    FeedbackThrottle,
    text_for_key,
)
from .viewport_feedback import BoardToViewportTransform
from .free_grid import hit_handle, screen_grid_metrics
from .viewport_router import ViewportGestureRouter
from .viewport_controller import ViewportController
from .board_context_controller import (
    BOARD_MENU_ARRANGE,
    BOARD_MENU_COPY,
    BOARD_MENU_EXPORT,
    BOARD_MENU_FIT,
    BOARD_MENU_OBJECT_NAME,
    BOARD_MENU_OVERVIEW,
    BOARD_MENU_RESET,
    BOARD_MENU_UNDO_ARRANGE,
    BoardContextController,
)
from .author_ui_controller import AuthorUiController, FORMAT_PICKER_KEYS as _FORMAT_PICKER_KEYS
from .author_edits import copy_author_objects
from .author_selection import (
    NUDGE_STEP,
    NUDGE_STEP_SHIFT,
    next_style_changes,
    object_bounds,
    resolve_selection_capabilities,
)
from .author_geometry import (
    board_box_to_pixels,
    board_point_to_pixels,
    box_anchor_point,
    box_center,
    constrain_shift_point,
    connector_handle_points,
    connector_hit_bounds,
    connector_route_points,
    hit_box_handle,
    hit_connection_anchor,
    hit_connector,
    hit_connector_handle,
    lasso_is_usable,
    pixels_to_board_point,
    polyline_center,
    snap_board_point,
    stroke_hit_record,
    strokes_hit_by_segment,
)
from .author_tools import (
    TOOL_SELECT,
    TOOL_STICKY,
    TOOL_TEXT,
    TOOL_SHAPES,
    TOOL_CONNECTOR,
    TOOL_DRAW,
    POINTER_MODE_LASER,
    POINTER_MODE_MOUSE,
    DRAW_ERASER,
    DRAW_LASSO,
    HIT_AUTHOR,
    HIT_BLANK,
    HIT_CARD,
    HIT_RESIZE_HANDLE,
    AuthorAlignIntent,
    AuthorBatchStyleIntent,
    AuthorDeleteIntent,
    AuthorDistributeIntent,
    AuthorDuplicateIntent,
    AuthorKey,
    AuthorLockIntent,
    AuthorNudgeIntent,
    AuthorPasteIntent,
    AuthorUpdateIntent,
    AuthorZOrderIntent,
    CONNECTOR_CLICK_DRAG_THRESHOLD,
    CONNECTOR_HEADS,
    CONNECTOR_LINE_STYLES,
    CONNECTOR_STROKE_WIDTHS,
    CONNECTOR_TYPES,
    SHAPE_CORNER_TYPES,
    SHAPE_LINE_STYLES,
    TEXT_DEFAULT_WIDTH,
    TEXT_MIN_HEIGHT,
    TEXT_MIN_WIDTH,
    ConnectorCreateIntent,
    ConnectorUpdateIntent,
    SelectionDeleteIntent,
    SelectionNudgeIntent,
    ShapeCreateIntent,
    ShapeUpdateIntent,
    StrokeCreateIntent,
    StrokeUpdateIntent,
    TextCreateIntent,
    TextUpdateIntent,
    clamp_author_box,
    connector_style_from_type,
    connector_type_from_style,
    default_shape_corner,
    lasso_selection_keys,
    new_author_object_id,
    normalize_connector_type,
    resize_shape_box,
    resize_text_box,
    shape_box_from_points,
    text_box_from_points,
)
from .author_widgets import is_text_input_widget
from .board_pointer import PointerRouter
from .widgets import (
    LIBRARY_DEFAULT_WIDTH,
    LIBRARY_OVERLAY_MIN_HEIGHT,
    LAYOUT_LABELS_ZH,
    BoardOverview,
    BoardScrollArea,
    BoardSwitcher,
    BoardGrid,
    FreeGridBoard,
    FreeGridCard,
    FreeGridMinimap,
    BoardToolbar,
    CardViewModel,
    CompareRail,
    FocusLayer,
    LibraryRow,
    UltraViewHintBar,
    UnplacedTray,
    UltraViewCard,
    ViewLibraryPanel,
    coerce_library_row,
    preview_image,
)
from .floating_chrome_controller import FloatingChromeController
from .page_projection import (
    LibraryChromeFacts,
    axis_kind_from_record,
    axis_records_from_models,
    card_models_for_slots,
    card_view_model,
    chrome_value,
    color_for,
    replacement_armed_for,
    source_for,
    status_for,
    title_for,
    tray_chrome_maps,
)
from .chrome import (
    BOARD_POPOVER_WIDTH,
    OVERLAY_AUTHOR_CONNECTOR,
    OVERLAY_AUTHOR_DRAW,
    OVERLAY_AUTHOR_FORMAT,
    OVERLAY_AUTHOR_POINTER,
    OVERLAY_AUTHOR_SHAPES,
    OVERLAY_AUTHOR_STICKY,
    PANEL_BOARDS,
    PANEL_FILTER,
    PANEL_LAYOUT,
    PANEL_LIBRARY,
    PANEL_UNPLACED,
    BoardIsland,
    BoardPopover,
    CanvasHost,
    CardContextIsland,
    FormatChoiceFlyout,
    GlobalIsland,
    LayoutPicker,
    NavigationIsland,
    SelectionToolbar,
    ConnectorPopover,
    DrawPopover,
    ShapePopover,
    StatusIsland,
    StickyPopover,
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
    SAFE_MARGIN,
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
_EDGE_HINT_DWELL_S = 0.4


def _qrect(rect: FloatingRect) -> QRect:
    """Map the Qt-free floating-layout rectangle at the Page boundary."""
    return QRect(int(rect.x), int(rect.y), int(rect.width), int(rect.height))


class UltraViewPage(QWidget):
    add_ref_requested = pyqtSignal(str, str)
    replace_slot_requested = pyqtSignal(str, str, str)
    swap_slots_requested = pyqtSignal(str, str)
    place_from_unplaced_requested = pyqtSignal(str, str, str)
    place_free_grid_from_unplaced_requested = pyqtSignal(str, str)
    free_grid_insert_requested = pyqtSignal(str, str, object)
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
    show_card_actions_toggled = pyqtSignal(bool)
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
    auto_arrange_requested = pyqtSignal()
    free_grid_undo_requested = pyqtSignal()
    free_grid_redo_requested = pyqtSignal()
    camera_settled = pyqtSignal()
    author_create_requested = pyqtSignal(object)
    author_update_requested = pyqtSignal(object)
    author_delete_requested = pyqtSignal(object)
    author_batch_requested = pyqtSignal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        visible_author_tools: Sequence[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(ULTRAVIEW_PAGE_OBJECT_NAME)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._board = default_board()
        self._workspace: Any | None = None
        # The action bar is a workspace preference, not Board content.  Keep a
        # page projection so direct ``set_board()`` callers receive the new
        # default even when they do not own an UltraViewWorkspaceState.
        self._show_card_actions = False
        self._previews: dict[UltraViewRef, Any] = {}
        self._statuses: dict[UltraViewRef, str] = {}
        self._ref_exists: dict[UltraViewRef, bool] = {}
        self._replacement_slot: str | None = None
        self._replacement_ref: UltraViewRef | None = None
        self._compare_filter = COMPARE_FILTER_ALL
        self._drag_kind: str | None = None
        self._pending_library_rows: list[LibraryRow] | None = None
        self._board_widgets_dirty = False
        self._projection_batch_depth = 0
        self._projection_dirty = False
        self._presentation = False
        self._floating_chrome: FloatingChromeController | None = None
        self._board_context: BoardContextController | None = None
        self._author_ui: AuthorUiController | None = None
        self._wired_groups: set[str] = set()
        # Floating chrome is transient view state: it is deliberately not
        # serialised with a Board or a project.  A fresh UltraView opens on a
        # continuous canvas; the library is available from the rail on demand.
        self._library_visible = False
        self._active_panel: str | None = None
        self._presentation_panel: str | None = None
        self._deferred_panel_close: str | None = None
        self._prev_unplaced_count: int | None = None
        self._prev_layout_fingerprint: tuple[str, str] | None = None
        self._viewport_ctrl: ViewportController | None = None
        self._rebasing_extent = False
        self._pending_viewport_restore: dict[str, float] | None = None
        # The extent is deliberately page-local session state.  Placements are
        # signed grid coordinates; the working halo, high-water mark and edge
        # timer must never become a project mutation or a viewport payload.
        self._workspace_extent = None
        self._edge_gesture_id = 0
        self._edge_hint_since: float | None = None
        self._edge_copy = ""
        self._feedback_gate = FeedbackThrottle()
        self._monotonic = time.monotonic
        self._diag_reproject_calls = 0
        self._feedback_transform_token = None
        self._feedback_transform_revision = 0

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
        self._interaction = self._free_grid.interaction()
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
        self._grid.installEventFilter(self)
        self._free_grid.installEventFilter(self)
        self._viewport_ctrl = ViewportController(
            board_scroll=self._board_scroll,
            board_stack=self._board_stack,
            board_host=self._board_host,
            grid=self._grid,
            free_grid=self._free_grid,
            active_canvas=self._active_canvas,
            is_free_grid=self._camera_is_free_grid,
            has_board=self._camera_has_board,
            board_id=self._camera_board_id,
            extent_signature=self._extent_signature,
            extent_key=self._camera_extent_key,
            content_fill_rect=self._content_fill_rect,
            fit_origin=self._fit_origin,
            working_frame_center=self._working_frame_center,
            card_rect_1x=self._card_rect_1x,
            refresh_extent=self._camera_refresh_extent,
            apply_lod_chrome=self._apply_lod_chrome,
            set_zoom_percent=self._set_zoom_percent,
            cancel_board_gestures=self.cancel_board_gestures,
            pause_draw=self._interaction.pause_draw_samples,
            resume_draw=self._interaction.resume_draw_samples,
            sync_tool_cursor=self._sync_tool_cursor,
            is_board_canvas_widget=self._is_board_canvas_widget,
            deliver_right_click_menu=self._deliver_right_click_menu,
            camera_settled=self.camera_settled.emit,
            sync_feedback_surface=self._sync_feedback_surface,
            sync_minimap_placement=self._sync_minimap_placement,
            sync_workspace_edge_hint=self._sync_workspace_edge_hint,
            reproject_after_viewport=self._reproject_after_viewport_change,
            on_edge_pan_started=self._on_edge_pan_started,
            on_edge_pan_stopped=self._on_edge_pan_stopped,
            parent=self,
        )
        self._viewport_router = ViewportGestureRouter(
            canvas_host=self._canvas_host,
            viewport=self._viewport_ctrl.viewport(),
            begin_pan=self.begin_board_pan,
            update_pan=self.update_board_pan,
            end_pan=self.end_board_pan_for_event,
            zoom_wheel=self.handle_zoom_wheel,
            pinch=self.handle_pinch,
            note_space=self.note_space,
            text_field_has_focus=self._text_field_has_focus,
            suppress_context_menu=self.suppress_board_context_menu_event,
            is_active=self._viewport_router_is_active,
            parent=self,
        )
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
        self._free_grid.bind_feedback_surface(self._board_scroll.viewport())

        self._tool_rail = ToolRail(
            self._canvas_host, visible_author_tools=visible_author_tools
        )
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

        self._pointer_popover = self._tool_rail.make_pointer_popover(self._canvas_host)
        self._sticky_popover = self._tool_rail.make_sticky_popover(self._canvas_host)
        self._shape_popover = self._tool_rail.make_shape_popover(self._canvas_host)
        self._connector_popover = self._tool_rail.make_connector_popover(self._canvas_host)
        self._draw_popover = self._tool_rail.make_draw_popover(self._canvas_host)
        self._register_author_flyouts()
        self._selection_toolbar = SelectionToolbar(self._canvas_host)
        self._selection_toolbar.hide()
        self._format_picker = FormatChoiceFlyout(self._canvas_host)
        self._pointer_router = PointerRouter(
            free_grid=self._free_grid,
            interaction=self._interaction,
            viewport=self._viewport_ctrl.viewport(),
            board=self._pointer_board,
            filter_host=self,
            emit_create=self.author_create_requested.emit,
            emit_update=self.author_update_requested.emit,
            emit_delete=self.author_delete_requested.emit,
            emit_feedback=self._emit_feedback,
            sync_tool_cursor=self._sync_tool_cursor,
            sync_tool_rail=self._sync_tool_rail_from_controller,
            refresh_author_toolbar=self._refresh_author_toolbar,
            selection_toolbar=self._selection_toolbar,
        )
        self._bind_pointer_router()
        self._author_ui = AuthorUiController(
            interaction=self._interaction,
            canvas_host=self._canvas_host,
            tool_rail=self._tool_rail,
            pointer_popover=self._pointer_popover,
            sticky_popover=self._sticky_popover,
            shape_popover=self._shape_popover,
            connector_popover=self._connector_popover,
            draw_popover=self._draw_popover,
            format_picker=self._format_picker,
            selection_toolbar=self._selection_toolbar,
            navigation_island=self._navigation_island,
            status_island=self._status_island,
            sync_tool_cursor=self._sync_tool_cursor,
            sync_free_grid_cursor=self._free_grid.sync_tool_cursor,
            refresh_author_toolbar=self._refresh_author_toolbar,
            sync_minimap_placement=self._sync_minimap_placement,
            reassert_host_stacking=self._reassert_host_stacking,
            selection_capabilities=self._selection_capabilities,
            selection_bounds=self._selection_bounds_in_host,
            author_item=self._author_item,
            apply_format=self._on_selection_format_requested,
            text_field_has_focus=self._text_field_has_focus,
            creation_allowed=self._free_grid.creation_allowed,
        )
        self._canvas_host.register_overlay(
            OVERLAY_AUTHOR_FORMAT,
            self._format_picker,
            close_on_canvas_click=True,
        )
        self._floating_chrome = FloatingChromeController(
            canvas_host=self._canvas_host,
            board_scroll=self._board_scroll,
            tool_rail=self._tool_rail,
            board_island=self._board_island,
            global_island=self._global_island,
            status_island=self._status_island,
            navigation_island=self._navigation_island,
            overview=self._overview,
            minimap=self._minimap,
            selection_toolbar=self._selection_toolbar,
            empty_board_hint=self._empty_board_hint,
            card_context=self._card_context,
            format_picker=self._format_picker,
            board_popover=self._board_popover,
            author_flyouts=self._author_flyouts(),
            text_editor=self._free_grid.author_text_editor(),
            sticky_editor=self._free_grid.sticky_note_widget(),
            layout_for=self._floating_layout,
            active_panel=self.active_panel,
            board_popover_rect=self._board_popover_rect,
            minimap_should_show=self._minimap_should_show,
            drag_active=self._drag_is_active,
            interaction_facts=self._free_grid.interaction_facts,
            page_geometry_active=self._page_geometry_session_active,
            selection_bounds=self._selection_bounds_in_host,
            selection_capabilities=self._selection_capabilities,
            close_format_picker=self._close_format_picker,
            is_presentation=self.is_presentation_active,
            page_size=self._chrome_page_size,
            draft_active=self._author_draft_active,
            sync_empty_board_cue=self._sync_empty_board_cue,
            sync_feedback_surface=self._sync_feedback_surface,
            position_card_context=self._position_card_context,
        )
        self._more_menu: QMenu | None = None
        self.resolve_insert_span = None
        self.can_undo_auto_arrange = None
        self._board_context = BoardContextController(
            menu_parent=self,
            board_scroll=self._board_scroll,
            board_host=self._board_host,
            free_grid=self._free_grid,
            grid=self._grid,
            card_context=self._card_context,
            is_presentation=self.is_presentation_active,
            overview_visible=self._overview.isVisible,
            focus_visible=self._focus.isVisible,
            drag_active=self._drag_is_active,
            viewport_panning=self.is_board_panning,
            grid_gesture_active=self._grid.is_gesture_active,
            free_grid_gesture_active=self._free_grid_gesture_active,
            layout_mode=self._board_layout_mode,
            free_grid_count=self._board_free_grid_count,
            can_undo_arrange=self._auto_arrange_undo_available,
            close_active_overlay=self._canvas_host.close_active_overlay,
            zoom_fit=self.zoom_fit,
            zoom_reset=self.zoom_reset,
            show_overview=self.show_overview,
            auto_arrange=self.auto_arrange_requested.emit,
            undo_arrange=self.free_grid_undo_requested.emit,
            copy_board=self.copy_board_requested.emit,
            export_png=self.export_png_requested.emit,
            refresh_author_toolbar=self._refresh_author_toolbar,
        )
        self._free_grid.set_insert_span_resolver(self._resolve_insert_span_for_drag)

        self._esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc.setContext(Qt.WidgetWithChildrenShortcut)
        self._grid_undo = QShortcut(QKeySequence.Undo, self)
        self._grid_undo.setContext(Qt.WidgetWithChildrenShortcut)
        self._grid_redo = QShortcut(QKeySequence.Redo, self)
        self._grid_redo.setContext(Qt.WidgetWithChildrenShortcut)
        self._select_tool_shortcut = QShortcut(QKeySequence(Qt.Key_V), self)
        self._select_tool_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._sticky_tool_shortcut = QShortcut(QKeySequence(Qt.Key_N), self)
        self._sticky_tool_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._text_tool_shortcut = QShortcut(QKeySequence(Qt.Key_T), self)
        self._text_tool_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._shape_tool_shortcut = QShortcut(QKeySequence(Qt.Key_S), self)
        self._shape_tool_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._connector_tool_shortcut = QShortcut(QKeySequence(Qt.Key_L), self)
        self._connector_tool_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._draw_tool_shortcut = QShortcut(QKeySequence(Qt.Key_P), self)
        self._draw_tool_shortcut.setContext(Qt.WidgetWithChildrenShortcut)

        self._connect_library()
        self._connect_toolbar()
        self._connect_compare_rail()
        self._connect_switcher()
        self._connect_islands()
        self._connect_canvas_host()
        self._connect_grid()
        self._connect_free_grid()
        self._connect_scroll_minimap()
        self._connect_author_ui()
        self._connect_board_context()
        self._connect_viewport_router()
        self._connect_tray()
        self._connect_shortcuts()
        self.set_board(self._board)
        QTimer.singleShot(0, self._apply_floating_layout)

    def _already_wired(self, group: str) -> bool:
        if group in self._wired_groups:
            return True
        self._wired_groups.add(group)
        return False

    def _connect_library(self) -> None:
        if self._already_wired("library"):
            return
        self._library.add_requested.connect(self.request_add)
        self._library.remove_requested.connect(self.remove_ref_requested)
        self._library.locate_requested.connect(self._on_locate)
        self._library.pin_toggled.connect(self._on_library_pin_toggled)
        self._library.drag_started.connect(self._on_drag_started)
        self._library.drag_finished.connect(self._on_drag_finished)

    def _connect_toolbar(self) -> None:
        if self._already_wired("toolbar"):
            return
        self._toolbar.layout_changed.connect(self.layout_changed)
        self._toolbar.ratio_nudge_requested.connect(self.ratio_nudge_requested)
        self._toolbar.copy_board_requested.connect(self.copy_board_requested)
        self._toolbar.export_png_requested.connect(self.export_png_requested)
        self._toolbar.show_titles_toggled.connect(self.show_titles_toggled)
        self._toolbar.show_sources_toggled.connect(self.show_sources_toggled)
        self._toolbar.show_card_actions_toggled.connect(self.show_card_actions_toggled)
        self._toolbar.presentation_toggled.connect(self._on_presentation_button)
        self._toolbar.overview_requested.connect(self.show_overview)
        self._toolbar.board_name_changed.connect(self.board_name_changed)
        self._toolbar.free_grid_toggled.connect(self.free_grid_toggled)
        self._toolbar.organize_free_grid_requested.connect(self.organize_free_grid_requested)
        self._toolbar.zoom_out_requested.connect(self.zoom_out)
        self._toolbar.zoom_in_requested.connect(self.zoom_in)
        self._toolbar.zoom_fit_requested.connect(self.zoom_fit)
        self._toolbar.zoom_reset_requested.connect(self.zoom_reset)

    def _connect_compare_rail(self) -> None:
        if self._already_wired("compare_rail"):
            return
        self._rail.compare_filter_changed.connect(self._on_compare_filter)

    def _connect_switcher(self) -> None:
        if self._already_wired("switcher"):
            return
        self._switcher.create_requested.connect(self.create_board_requested)
        self._switcher.duplicate_requested.connect(self.duplicate_board_requested)
        self._switcher.rename_requested.connect(self.rename_board_requested)
        self._switcher.delete_requested.connect(self.delete_board_requested)
        self._switcher.reorder_requested.connect(self.reorder_board_requested)
        self._switcher.board_selected.connect(self._on_board_selected)

    def _connect_islands(self) -> None:
        if self._already_wired("islands"):
            return
        self._hint_bar.quickref_requested.connect(self.quickref_requested.emit)
        self._status_island.quickref_requested.connect(self.quickref_requested.emit)
        self._tool_rail.panel_requested.connect(self._toggle_panel)
        self._tool_rail.free_grid_toggled.connect(self._on_free_grid_toggled)
        self._tool_rail.sync_all_requested.connect(self._on_sync_all_requested)
        self._tool_rail.ref_dropped.connect(self._on_tray_drop)
        self._layout_popover.layout_id_chosen.connect(self._on_layout_id_chosen)
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
        if self._floating_chrome is not None:
            self._floating_chrome.connect()

    def _connect_canvas_host(self) -> None:
        if self._already_wired("canvas_host"):
            return
        self._canvas_host.overlay_closed.connect(self._on_overlay_closed)
        self._focus.open_source_requested.connect(self.open_source_requested)

    def _connect_grid(self) -> None:
        if self._already_wired("grid"):
            return
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

    def _connect_free_grid(self) -> None:
        if self._already_wired("free_grid"):
            return
        editor = self._free_grid.author_text_editor()
        editor.text_committed.connect(self._on_text_committed)
        editor.edit_cancelled.connect(self._on_text_cancelled)
        editor.focus_lost.connect(self._on_text_focus_lost)
        editor.limit_reached.connect(self._on_text_limit_reached)
        self._free_grid.insert_requested.connect(self._on_free_grid_insert_requested)
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
        self._free_grid.author_create_requested.connect(self._on_author_create_requested)
        self._free_grid.author_update_requested.connect(self._on_author_update_requested)
        self._free_grid.author_delete_requested.connect(self._on_author_delete_requested)
        self._free_grid.author_edit_requested.connect(self._on_author_edit_requested)
        self._free_grid.replace_requested.connect(self.free_grid_replace_requested)
        workspace_gesture = getattr(self._free_grid, "workspace_gesture_changed", None)
        if workspace_gesture is not None:
            workspace_gesture.connect(self._on_workspace_gesture_changed)
        active_changed = getattr(
            self._free_grid, "workspace_gesture_active_changed", None
        )
        if active_changed is not None:
            active_changed.connect(self._on_workspace_gesture_active_changed)
        pointer_changed = getattr(self._free_grid, "workspace_pointer_changed", None)
        if pointer_changed is not None:
            pointer_changed.connect(self._on_workspace_pointer_changed)
        self._free_grid.destroyed.connect(self._stop_edge_pan)

    def _connect_scroll_minimap(self) -> None:
        if self._already_wired("scroll_minimap"):
            return
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

    def _connect_author_ui(self) -> None:
        if self._already_wired("author_ui"):
            return
        if self._author_ui is not None:
            self._author_ui.connect()
        self._selection_toolbar.more_requested.connect(self._on_selection_more_requested)
        self._select_tool_shortcut.activated.connect(self._on_select_tool_shortcut)
        self._sticky_tool_shortcut.activated.connect(self._on_sticky_tool_shortcut)
        self._text_tool_shortcut.activated.connect(self._on_text_tool_shortcut)
        self._shape_tool_shortcut.activated.connect(self._on_shape_tool_shortcut)
        self._connector_tool_shortcut.activated.connect(self._on_connector_tool_shortcut)
        self._draw_tool_shortcut.activated.connect(self._on_draw_tool_shortcut)

    def _connect_board_context(self) -> None:
        if self._already_wired("board_context"):
            return
        if self._board_context is not None:
            self._board_context.connect()
        self._card_context.open_source_requested.connect(self.open_source_requested)
        self._card_context.sync_requested.connect(self.sync_requested)
        self._card_context.focus_requested.connect(self._on_focus)
        self._card_context.copy_image_requested.connect(self.copy_card_image_requested)
        self._card_context.move_to_unplaced_requested.connect(self.move_to_unplaced_requested)
        self._card_context.more_requested.connect(self._show_card_more_menu)
        self._card_context.rebind_requested.connect(self._on_rebind_arm)
        self._card_context.remove_requested.connect(self.remove_ref_requested)
        self._card_context.fit_requested.connect(self.free_grid_autofit_requested)

    def _connect_viewport_router(self) -> None:
        if self._already_wired("viewport_router"):
            return
        # Single ViewportGestureRouter is constructed in __init__. Install /
        # uninstall stay on showEvent / hideEvent / changeEvent.
        if self._viewport_ctrl is not None:
            self._viewport_ctrl.connect()

    def _connect_tray(self) -> None:
        if self._already_wired("tray"):
            return
        self._tray.place_requested.connect(self._on_tray_place)
        self._tray.remove_requested.connect(self.remove_ref_requested)
        self._tray.locate_requested.connect(self._on_locate)
        self._tray.rebind_arm_requested.connect(self._on_rebind_arm)
        self._tray.move_to_unplaced_dropped.connect(self._on_tray_drop)
        self._tray.drag_started.connect(self._on_drag_started)
        self._tray.drag_finished.connect(self._on_drag_finished)

    def _connect_shortcuts(self) -> None:
        if self._already_wired("shortcuts"):
            return
        self._esc.activated.connect(self._on_escape_shortcut)
        self._grid_undo.activated.connect(self._on_grid_undo_shortcut)
        self._grid_redo.activated.connect(self._on_grid_redo_shortcut)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)

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

    def current_free_grid_insert_anchor(self) -> GridAnchor | None:
        """Return the actual scroll viewport centre in free-grid cell space."""
        if (
            self._board is None
            or self._board.layout_mode != LAYOUT_MODE_FREE_GRID
            or not self.isVisible()
        ):
            return None
        viewport = self._board_scroll.viewport()
        if viewport is None:
            return None
        global_center = viewport.mapToGlobal(viewport.rect().center())
        return self._free_grid.grid_anchor_at(
            self._free_grid.mapFromGlobal(global_center)
        )

    def unplaced_tray(self) -> UnplacedTray:
        return self._tray

    def compare_rail(self) -> CompareRail:
        return self._rail

    def board_toolbar(self) -> BoardToolbar:
        return self._toolbar

    def board_viewport(self) -> BoardViewport:
        return self._viewport_ctrl.viewport()

    @property
    def _viewport(self) -> BoardViewport:
        return self._viewport_ctrl.viewport()

    @property
    def _smooth_timer(self) -> QTimer:
        return self._viewport_ctrl.smooth_timer()

    @property
    def _edge_pan_timer(self) -> QTimer:
        return self._viewport_ctrl.edge_pan_timer()

    @property
    def _edge_pan_active(self) -> bool:
        return self._viewport_ctrl._edge_pan_active

    @_edge_pan_active.setter
    def _edge_pan_active(self, value: bool) -> None:
        self._viewport_ctrl._edge_pan_active = bool(value)

    @property
    def _edge_pan_global_pos(self) -> QPoint | None:
        return self._viewport_ctrl._edge_pan_global_pos

    @_edge_pan_global_pos.setter
    def _edge_pan_global_pos(self, value) -> None:
        self._viewport_ctrl._edge_pan_global_pos = (
            None if value is None else QPoint(value)
        )

    @property
    def _right_gesture_widget(self):
        return self._viewport_ctrl._right_gesture_widget

    @property
    def _filled_card(self) -> tuple[str, str] | None:
        return self._viewport_ctrl.filled_card()

    @property
    def _restoring_viewport(self) -> bool:
        return self._viewport_ctrl.is_restoring()

    @_restoring_viewport.setter
    def _restoring_viewport(self, value: bool) -> None:
        if value:
            self._viewport_ctrl.begin_restore()
        else:
            self._viewport_ctrl.end_restore()

    def _camera_is_free_grid(self) -> bool:
        return self._board.layout_mode == LAYOUT_MODE_FREE_GRID

    def _camera_has_board(self) -> bool:
        return self._board is not None

    def _camera_board_id(self) -> str | None:
        if self._board is None:
            return None
        return str(self._board.board_id)

    def _camera_extent_key(self) -> tuple | None:
        extent = self._workspace_extent
        if extent is None:
            return None
        return (extent.column, extent.row, extent.column_span, extent.row_span)

    def _camera_refresh_extent(self, *args, **kwargs) -> bool:
        return self._refresh_workspace_extent(*args, **kwargs)

    def workspace_extent(self):
        """Return the current free-grid runtime extent, never persisted.

        ``GridBounds`` deliberately stays behind the Qt-free state boundary;
        this narrow inspection seam exists for viewport tests and minimap/
        edge-paint collaborators.  Callers must not mutate it in place.
        """
        return self._workspace_extent

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

    @property
    def _format_picker_key(self) -> str:
        if self._author_ui is None:
            return ""
        return self._author_ui.format_picker_key()

    @_format_picker_key.setter
    def _format_picker_key(self, value: str) -> None:
        if self._author_ui is None:
            return
        self._author_ui.set_format_picker_key(str(value or ""))

    def visible_author_tools(self) -> tuple[str, ...]:
        """Release rail projection. Hidden tools stay implemented, not advertised."""
        return self._tool_rail.visible_author_tools()

    def interaction(self):
        """Board interaction owner. Page selection is a projection of this."""
        return self._interaction

    def pointer_router(self) -> PointerRouter:
        """Author-tool pointer sessions. Page.eventFilter is the only Qt entry."""
        return self._pointer_router

    def _pointer_board(self):
        return self._board

    def _bind_pointer_router(self) -> None:
        router = self._pointer_router
        owned = set(UltraViewPage.__dict__)
        for name in PointerRouter.FORWARDED_METHODS:
            if name in owned:
                continue
            setattr(self, name, getattr(router, name))

    def _pointer_tool_armed(self, tool: str) -> bool:
        return self._pointer_router._pointer_tool_armed(tool)

    @property
    def _editor_kind(self) -> str:
        router = getattr(self, "_pointer_router", None)
        if router is None:
            return ""
        return str(router._editor_kind or "")

    @_editor_kind.setter
    def _editor_kind(self, value: str) -> None:
        router = getattr(self, "_pointer_router", None)
        if router is None:
            return
        router._editor_kind = str(value or "")

    @property
    def _text_limit_notified(self) -> bool:
        router = getattr(self, "_pointer_router", None)
        if router is None:
            return False
        return bool(router._text_limit_notified)

    @_text_limit_notified.setter
    def _text_limit_notified(self, value: bool) -> None:
        router = getattr(self, "_pointer_router", None)
        if router is None:
            return
        router._text_limit_notified = bool(value)

    @property
    def _text_geometry_session(self):
        return self._interaction.geometry_session(TOOL_TEXT)

    @_text_geometry_session.setter
    def _text_geometry_session(self, value) -> None:
        self._interaction.set_geometry_session(TOOL_TEXT, value)

    @property
    def _shape_geometry_session(self):
        return self._interaction.geometry_session(TOOL_SHAPES)

    @_shape_geometry_session.setter
    def _shape_geometry_session(self, value) -> None:
        self._interaction.set_geometry_session(TOOL_SHAPES, value)

    @property
    def _connector_geometry_session(self):
        return self._interaction.geometry_session(TOOL_CONNECTOR)

    @_connector_geometry_session.setter
    def _connector_geometry_session(self, value) -> None:
        self._interaction.set_geometry_session(TOOL_CONNECTOR, value)

    def _drag_is_active(self) -> bool:
        return self._drag_kind is not None

    def _author_draft_active(self) -> bool:
        return self._interaction.draft() is not None

    def _page_geometry_session_active(self) -> bool:
        return (
            self._interaction.geometry_session(TOOL_TEXT) is not None
            or self._interaction.geometry_session(TOOL_SHAPES) is not None
            or self._interaction.geometry_session(TOOL_CONNECTOR) is not None
        )

    def _chrome_page_size(self) -> tuple[int, int]:
        return (self.width(), self.height())

    @property
    def _selected(self) -> UltraViewRef | None:
        return self._interaction.primary_card()

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
        self._display_card_actions = QToolButton(frame)
        self._display_card_actions.setObjectName("ultraViewDisplayCardActionsButton")
        self._display_card_actions.setText("常驻显示卡片操作")
        self._display_card_actions.setCheckable(True)
        self._display_card_actions.setToolTip("取消后，悬停或键盘聚焦卡片时显示操作")
        self._display_card_actions.toggled.connect(self.show_card_actions_toggled)
        layout.addWidget(self._display_titles, 0)
        layout.addWidget(self._display_sources, 0)
        layout.addWidget(self._display_card_actions, 0)
        preference_note = QLabel("适用于当前工程的所有 Board；保存项目后保留。", frame)
        preference_note.setObjectName("ultraViewDisplayPreferenceNote")
        preference_note.setWordWrap(True)
        layout.addWidget(preference_note, 0)
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
        """Chrome-safe parking rect for 1×; full stage during 演示."""
        layout = self._floating_layout()
        if self._presentation:
            return layout.board
        return layout.fit

    def _content_fill_rect(self):
        """适应 target: rail-clear left, stage-safe top and bottom.

        ``fit`` parks 1× below the top islands and above the navigation
        island. 适应 treats the edge chrome as overlays on the dotted
        stage: same left as ``fit`` so the rail keeps a dedicated band,
        but top and bottom both use ``SAFE_MARGIN``. Matching those
        vertical insets keeps the fill centre on the stage centre.
        """
        layout = self._floating_layout()
        if self._presentation:
            return layout.board
        fit = layout.fit
        top = SAFE_MARGIN
        bottom = max(int(fit.bottom), int(layout.board.height) - SAFE_MARGIN)
        return FloatingRect(fit.x, top, fit.width, max(0, bottom - top))

    def _fit_origin(self) -> tuple[float, float]:
        """Chrome-safe parking origin. Fit / 1× / restore park the stack here."""
        fit = self._content_fit_rect()
        return (float(fit.x), float(fit.y))

    def _board_content_origin(self) -> tuple[float, float]:
        """Current board-canvas origin inside the scroll host."""
        return self._viewport_ctrl.board_content_origin()

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
        if self._floating_chrome is None:
            return
        self._floating_chrome.apply()

    def _reassert_host_stacking(self) -> None:
        if self._floating_chrome is None:
            return
        self._floating_chrome.reassert_stacking()

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
        if self._floating_chrome is None:
            return
        self._floating_chrome.position_empty_board_hint()

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
        if self._interaction.active_tool() != TOOL_SELECT:
            self._close_author_flyouts()
            self._interaction.set_active_tool(TOOL_SELECT)
            self._sync_tool_rail_from_controller()
            self._sync_tool_cursor()
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
        if self._author_ui is not None and self._author_ui.handle_overlay_closed(panel_id):
            return
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

    def _rename_board(self, board_id: str, name: str = "") -> None:
        cleaned = str(name or "").strip()
        if cleaned:
            self.rename_board_requested.emit(str(board_id), cleaned)
            return
        target_id = str(board_id or "")
        if not target_id:
            return
        if self._board_popover.isVisible() and target_id in self._board_popover.board_ids():
            self._board_popover.begin_inline_rename(target_id)
            return
        if target_id == str(getattr(self._board, "board_id", "") or ""):
            self._board_island.begin_inline_rename()

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

    def _rename_current_board(self, name: str = "") -> None:
        self._rename_board(self._board.board_id, name)

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
        self._exec_native_menu(menu, origin, trigger=button)

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
        self._reassert_host_stacking()

    def _extent_signature(self, board=None) -> tuple[int, int, int, int]:
        target = self._board if board is None else board
        bounds = content_bounds(target.free_grid, author_objects=target.author_objects)
        return (bounds.column, bounds.row, bounds.column_span, bounds.row_span)

    def _persist_viewport_to_board(self) -> None:
        self._viewport_ctrl.persist()

    def _workspace_cell_pitch(self) -> tuple[float, float]:
        """Return the 1× free-grid pitch without asking a widget for state.

        ``FreeGridBoard.metrics()`` is already zoomed.  The elastic extent
        takes the unzoomed pitch plus the current zoom separately, which keeps
        the halo invariant in screen space rather than accidentally squaring
        the scale.
        """
        metrics = screen_grid_metrics(self._board.free_grid)
        return metrics.exact_pitch()

    def _visible_workspace_bounds(self) -> GridBounds:
        """Current scroll viewport expressed in signed free-grid cells.

        Content alone cannot make a canvas elastic: once a user pans into its
        halo, the content is unchanged while the visible window moves.  Fold
        the visible cell bounds into desired_extent so high-water growth keeps
        following navigation rather than recreating a hidden wall.
        """
        viewport = self._board_scroll.viewport()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return GridBounds(0, 0, 0, 0)
        top_left = self._free_grid.mapFromGlobal(viewport.mapToGlobal(QPoint(0, 0)))
        bottom_right = self._free_grid.mapFromGlobal(
            viewport.mapToGlobal(QPoint(viewport.width(), viewport.height()))
        )
        first = self._free_grid.grid_anchor_at(top_left)
        second = self._free_grid.grid_anchor_at(bottom_right)
        left = math.floor(min(first.column, second.column))
        top = math.floor(min(first.row, second.row))
        right = math.ceil(max(first.column, second.column))
        bottom = math.ceil(max(first.row, second.row))
        return GridBounds.from_edges(left, top, max(left + 1, right), max(top + 1, bottom))

    def _refresh_workspace_extent(
        self,
        *,
        reset: bool = False,
        preserve_visible: bool = True,
    ) -> bool:
        """Grow the free-grid session extent and project it into the canvas.

        The high-water mark is Page-owned runtime geometry: it grows on pan,
        resize, zoom and incoming placements but never writes ``BoardState``.
        A board switch/reset intentionally starts fresh from that board's
        content + viewport halo.

        Always unions the current scroll window so pan-into-halo can grow the
        world. Interactive zoom must not call this helper at all: rebasing the
        signed origin while a scroll transaction is pending costs an extra
        reflow per wheel tick. Halo growth waits for the idle smooth timer.
        """
        if self._board.layout_mode != LAYOUT_MODE_FREE_GRID:
            self._workspace_extent = None
            return False
        viewport = self._board_scroll.viewport()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return False
        content = content_bounds(
            self._board.free_grid, author_objects=self._board.author_objects
        ).union(
            self._visible_workspace_bounds()
        )
        wanted = desired_extent(
            content,
            (float(viewport.width()), float(viewport.height())),
            self._workspace_cell_pitch(),
            zoom=self._viewport.zoom(),
        )
        before = self._workspace_extent
        after = wanted if reset or before is None else expand_extent(before, wanted)
        if after == before:
            return False
        self._workspace_extent = after
        setter = getattr(self._free_grid, "set_workspace_extent", None)
        if callable(setter):
            setter(after)
        if before is not None and preserve_visible:
            # Growing into negative cells rebases the widget-local coordinate
            # plane.  Compensate the scroll bars in the same transaction so a
            # quiet resize/LOD repaint does not make every card visibly jump.
            # _sync_board_stack_geometry publishes the new canvas size before
            # setValue so Qt cannot clamp against yesterday's maximum.
            self._sync_board_stack_geometry(self._free_grid)
            metrics = self._free_grid.metrics()
            # Round the two origins, not the pitch: a rounded pitch times the
            # cell delta is the same quantization error that made zoom jitter,
            # and it would leave the view a few pixels off after every rebase.
            pitch_x, pitch_y = metrics.exact_pitch()
            delta_x = int(round(int(before.column) * pitch_x)) - int(
                round(int(after.column) * pitch_x)
            )
            delta_y = int(round(int(before.row) * pitch_y)) - int(
                round(int(after.row) * pitch_y)
            )
            horizontal = self._board_scroll.horizontalScrollBar()
            vertical = self._board_scroll.verticalScrollBar()
            self._rebasing_extent = True
            try:
                horizontal.setValue(int(horizontal.value() + delta_x))
                vertical.setValue(int(vertical.value() + delta_y))
            finally:
                self._rebasing_extent = False
        return True

    def _working_frame_center(self) -> tuple[float, float]:
        """Pixel centre of the empty-board two-card frame in this extent."""
        metrics = screen_grid_metrics(())
        frame_w, frame_h = two_card_working_frame(metrics)
        extent = self._workspace_extent
        if extent is None:
            return (frame_w / 2.0, frame_h / 2.0)
        pitch_x, pitch_y = metrics.exact_pitch()
        # FreeGridBoard renders signed cells relative to extent.column/row.
        # Keep the visible empty working frame centred on base-frame cells,
        # not on the negative halo's top-left corner.
        return (
            frame_w / 2.0 - float(extent.column) * pitch_x,
            frame_h / 2.0 - float(extent.row) * pitch_y,
        )

    def fit_on_open(self) -> None:
        """Park on 适应 for window open/raise, first visit, and extent rebase.

        Same-session Board switches restore the page-local camera when the
        content extent signature is unchanged. The camera never enters a
        project payload.
        """
        self._viewport_ctrl.fit_on_open()

    def _apply_initial_viewport(self) -> None:
        """First show / empty payload: same camera as a window open."""
        self._viewport_ctrl.apply_initial_viewport()

    def _on_workspace_gesture_changed(self, active: bool, global_pos=None) -> None:
        """Compat lifetime+optional first pointer. Page does not replan here."""
        self._viewport_ctrl.on_workspace_gesture_changed(active, global_pos)

    def _on_workspace_gesture_active_changed(self, active: bool, gesture_id: int) -> None:
        self._viewport_ctrl.on_workspace_gesture_active_changed(active, gesture_id)

    def _on_workspace_pointer_changed(self, gesture_id: int, global_pos=None) -> None:
        self._viewport_ctrl.on_workspace_pointer_changed(gesture_id, global_pos)

    def _now(self) -> float:
        clock = getattr(self, "_monotonic", None)
        return float(clock()) if callable(clock) else time.monotonic()

    def _stop_edge_pan(self, *_args) -> None:
        self._viewport_ctrl.stop_edge_pan()

    def _on_edge_pan_started(self) -> None:
        self._edge_gesture_id += 1
        self._edge_hint_since = None
        self._edge_copy = ""

    def _on_edge_pan_stopped(self) -> None:
        self._edge_hint_since = None
        self._edge_copy = ""
        self._feedback_gate.end_gesture(self._edge_gesture_id)
        self._clear_workspace_edge_hint()

    def _reproject_after_viewport_change(self, global_pos) -> None:
        reproject = getattr(self._free_grid, "reproject_after_viewport_change", None)
        if callable(reproject):
            self._diag_reproject_calls += 1
            reproject(global_pos)

    def _clear_workspace_edge_hint(self) -> None:
        free = getattr(self, "_free_grid", None)
        if free is None:
            return
        try:
            clearer = getattr(free, "clear_workspace_edge_hint", None)
            if callable(clearer):
                clearer()
        except RuntimeError:
            # The board may already be deleted on widget destroyed.
            return

    def _workspace_transform_token(self) -> tuple:
        extent = self._workspace_extent
        extent_key = (
            None
            if extent is None
            else (extent.column, extent.row, extent.column_span, extent.row_span)
        )
        return (
            int(self._board_scroll.horizontalScrollBar().value()),
            int(self._board_scroll.verticalScrollBar().value()),
            extent_key,
            float(self._viewport.zoom()),
        )

    def _sync_feedback_surface(self) -> None:
        free = getattr(self, "_free_grid", None)
        if free is None:
            return
        overlay = getattr(free, "ghost_overlay", None)
        surface = overlay() if callable(overlay) else None
        if surface is None:
            return
        sync = getattr(surface, "sync_host_geometry", None)
        if callable(sync):
            sync()
        apply_transform = getattr(surface, "apply_transform", None)
        if callable(apply_transform):
            viewport = self._board_scroll.viewport()
            origin = free.mapFrom(viewport, QPoint(0, 0))
            token = self._workspace_transform_token()
            if token != self._feedback_transform_token:
                self._feedback_transform_token = token
                self._feedback_transform_revision += 1
            apply_transform(
                BoardToViewportTransform(
                    revision=self._feedback_transform_revision,
                    viewport_in_board=(int(origin.x()), int(origin.y())),
                )
            )
        if self._minimap.isVisible():
            self._minimap.raise_()

    def _edge_pan_tick_for_global(self, global_pos) -> None:
        self._viewport_ctrl.edge_pan_tick_for_global(global_pos)

    def _viewport_rect_in_board(self) -> QRect:
        viewport = self._board_scroll.viewport()
        top_left = self._free_grid.mapFromGlobal(viewport.mapToGlobal(QPoint(0, 0)))
        return QRect(top_left, viewport.size())

    def _continue_sides_at(
        self, local: QPoint, viewport_size: tuple[float, float]
    ) -> tuple[str, ...]:
        x = float(local.x())
        y = float(local.y())
        width, height = viewport_size
        band = float(EDGE_PAN_BAND_PX)
        if x < 0.0 or y < 0.0 or x > width or y > height:
            return ()
        extent = self._workspace_extent
        safety = safety_grid_bounds()
        sides: list[str] = []
        if x < band and (extent is None or extent.column > safety.column):
            sides.append("left")
        if y < band and (extent is None or extent.row > safety.row):
            sides.append("top")
        if x > width - band and (
            extent is None or extent.column_end < safety.column_end
        ):
            sides.append("right")
        if y > height - band and (extent is None or extent.row_end < safety.row_end):
            sides.append("bottom")
        return tuple(sides)

    def _sync_workspace_edge_hint(self, global_pos) -> None:
        setter = getattr(self._free_grid, "set_workspace_edge_hint", None)
        if not callable(setter):
            return
        viewport = self._board_scroll.viewport()
        local = viewport.mapFromGlobal(global_pos)
        safety = bool(getattr(self._free_grid, "workspace_safety_blocked", lambda: False)())
        continue_sides = () if safety else self._continue_sides_at(
            local, (float(viewport.width()), float(viewport.height()))
        )
        copy = ""
        if safety:
            self._edge_hint_since = None
            self._emit_feedback(text_for_key(SAFETY_BOUNDS))
        elif continue_sides:
            now = self._now()
            if self._edge_hint_since is None:
                self._edge_hint_since = now
            if now - self._edge_hint_since >= _EDGE_HINT_DWELL_S:
                if self._feedback_gate.allow_continue_expand(self._edge_gesture_id):
                    self._edge_copy = text_for_key(CONTINUE_EXPAND)
                copy = self._edge_copy
        else:
            self._edge_hint_since = None
        setter(
            continue_sides=continue_sides,
            copy=copy,
            viewport_rect=self._viewport_rect_in_board(),
        )

    def _restore_viewport_from_board(self, board) -> None:
        """Replay the session camera when this Board's extent signature still matches."""
        self._viewport_ctrl.restore_from_board(board)

    def _on_board_scrolled(self, _value: int = 0) -> None:
        if self._restoring_viewport or self._rebasing_extent:
            return
        self._sync_feedback_surface()
        self._viewport_ctrl.persist()

    def set_board_zoom(self, zoom: float, cursor_in_viewport=None) -> None:
        self._viewport_ctrl.set_board_zoom(zoom, cursor_in_viewport)

    def zoom_in(self) -> None:
        self._viewport_ctrl.zoom_in()

    def zoom_out(self) -> None:
        self._viewport_ctrl.zoom_out()

    def zoom_reset(self) -> None:
        self._viewport_ctrl.zoom_reset()

    def zoom_fit(self) -> None:
        self._viewport_ctrl.zoom_fit()

    def _park_zoom(self, zoom: float) -> None:
        self._viewport_ctrl._park_zoom(zoom)

    def _set_zoom_percent(self, percent: int) -> None:
        """Keep the legacy façade and the visible navigation island aligned."""
        self._toolbar.set_zoom_percent(percent)
        self._navigation_island.set_zoom_percent(percent)

    def zoom_to_card(self, section: str, view_id: str, *, animate: bool = True) -> None:
        self._viewport_ctrl.zoom_to_card(section, view_id, animate=animate)

    def _current_center(self) -> tuple[float, float]:
        return self._viewport_ctrl.current_center()

    def _apply_lod_chrome(self) -> None:
        level = self._viewport.lod()
        show_title = bool(self._board.show_titles)
        show_source = bool(self._board.show_sources)
        show_card_actions = self._show_card_actions
        for card in (*self._grid.card_widgets(), *self._free_grid.card_widgets()):
            card.apply_lod(
                level,
                show_title=show_title,
                show_source=show_source,
                show_card_actions=show_card_actions,
                presentation=self._presentation,
            )

    def note_space(self, down: bool) -> None:
        self._viewport_ctrl.note_space(down)

    def begin_board_pan(self, event, widget=None) -> bool:
        return self._viewport_ctrl.begin_board_pan(event, widget)

    def update_board_pan(self, event) -> None:
        self._viewport_ctrl.update_board_pan(event)

    def end_board_pan_for_event(self, event) -> bool:
        return self._viewport_ctrl.end_board_pan_for_event(event)

    def end_board_pan(self) -> None:
        self._viewport_ctrl.end_board_pan()

    def suppress_board_context_menu_event(self, _event) -> bool:
        return self._viewport_ctrl.suppress_board_context_menu_event(_event)

    def _is_board_canvas_widget(self, widget) -> bool:
        current = widget if isinstance(widget, QWidget) else None
        while current is not None:
            if current is self._canvas_stage:
                return True
            if current is self._canvas_host:
                return False
            current = current.parentWidget()
        return False

    def _deliver_right_click_menu(self, event) -> None:
        global_pos = event.globalPos() if hasattr(event, "globalPos") else QCursor.pos()
        widget = QApplication.widgetAt(global_pos)
        if widget is None:
            widget = self._right_gesture_widget
        target = None
        current = widget
        while current is not None:
            if isinstance(current, UltraViewCard):
                target = current
                break
            if current in (
                self._free_grid,
                self._grid,
                self._board_host,
                self._board_scroll.viewport(),
            ):
                target = current
                break
            if current is self._canvas_stage or current is self._canvas_host:
                target = (
                    self._free_grid
                    if self._board.layout_mode == LAYOUT_MODE_FREE_GRID
                    else self._grid
                )
                break
            current = current.parentWidget()
        if target is None:
            return
        pos = target.mapFromGlobal(global_pos)
        QApplication.sendEvent(
            target, QContextMenuEvent(QContextMenuEvent.Mouse, pos, global_pos)
        )

    def cancel_board_gestures(self) -> None:
        self._grid.cancel_gesture()
        self._free_grid.cancel_gesture()

    def handle_zoom_wheel(self, event: QWheelEvent, widget) -> bool:
        return self._viewport_ctrl.handle_zoom_wheel(event, widget)

    def handle_pinch(self, event: QNativeGestureEvent, widget) -> bool:
        return self._viewport_ctrl.handle_pinch(event, widget)

    def _active_canvas(self):
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            return self._free_grid
        return self._grid

    def _zoom_at(self, zoom: float, cursor_in_viewport) -> None:
        self._viewport_ctrl._zoom_at(zoom, cursor_in_viewport)

    def _on_viewport_resized(self, size) -> None:
        layout_size = self._board_layout_viewport_size(size)
        self._grid.set_viewport_size(layout_size)
        self._free_grid.set_viewport_size(layout_size)
        self._refresh_workspace_extent()
        # QStackedWidget keeps the prior canvas size hint.  Once the floating
        # host gives the scroll area its final rect, propagate the active
        # canvas's new logical size back to the stack so first paint shows the
        # cards instead of an empty dotted stage.
        self._sync_board_stack_geometry(self._active_canvas())
        self._sync_feedback_surface()
        self._viewport_ctrl.apply_initial_if_pending()
        self._refresh_card_context()

    def _on_smooth_preview_timeout(self) -> None:
        self._viewport_ctrl._on_smooth_preview_timeout()

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
        self._show_card_actions = bool(getattr(workspace, "show_card_actions", False))
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
        ref = self._interaction.primary_card()
        if ref is None:
            return None
        return ref.section, ref.view_id

    def clear_card_selection(self) -> bool:
        """Hide card-context chrome and clear the single interaction selection.

        Template cards, free-grid rings, and author chrome are projections of
        ``BoardInteractionController``. Library row highlight stays: empty-slot
        place reads it.
        """
        changed = self._free_grid.clear_selection()
        template_cleared = False
        for card in self._grid.card_widgets():
            if card.model().selected:
                card.set_selected(False)
                template_cleared = True
        if not changed and not template_cleared:
            return False
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
            self._close_author_flyouts()
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
        self._sync_authoring_availability()
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
            self._restore_viewport_from_board(self._board)

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
            self._stop_edge_pan()
            # The high-water mark belongs to the active board session, not a
            # project payload and not the next Board's initial view.
            self._workspace_extent = None
            self._free_grid.cancel_gesture()
            self._free_grid.reset_transient_interaction()
            self._clear_draw_draft_paint()
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
        self._free_grid.set_default_insert_span(free_grid_default_span(board))
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
        self._toolbar.set_show_flags(
            board.show_titles, board.show_sources, self._show_card_actions
        )
        self._board_island.set_current_board(board.board_id, board.name)
        blocked = self._display_titles.blockSignals(True)
        self._display_titles.setChecked(bool(board.show_titles))
        self._display_titles.blockSignals(blocked)
        blocked = self._display_sources.blockSignals(True)
        self._display_sources.setChecked(bool(board.show_sources))
        self._display_sources.blockSignals(blocked)
        blocked = self._display_card_actions.blockSignals(True)
        self._display_card_actions.setChecked(self._show_card_actions)
        self._display_card_actions.blockSignals(blocked)
        self._tool_rail.set_badge(PANEL_UNPLACED, n_unplaced)
        self._sync_layout_popover()
        self._sync_authoring_availability()
        if self._drag_kind is not None:
            # Drop handlers mutate the board inside QDrag.exec_(). Rebuilding
            # library/grid/tray here would deleteLater the drag source before
            # mouseMoveEvent returns, which aborts via qFatal.
            self._board_widgets_dirty = True
            if switching:
                self._pending_viewport_restore = {}
            self._sync_empty_board_cue()
            return
        self._library.set_on_board(membership_set(board))
        if switching and self._projection_batch_depth:
            self._pending_viewport_restore = {}
            self._refresh_projection()
        elif switching:
            self._restoring_viewport = True
            try:
                self._refresh_projection()
            finally:
                self._restoring_viewport = False
            self._restore_viewport_from_board(board)
        else:
            self._refresh_projection()
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            if self._refresh_workspace_extent():
                self._sync_board_stack_geometry(self._free_grid)
        self._set_zoom_percent(zoom_percent(self._viewport.zoom()))
        self._apply_floating_layout()

    def _open_unplaced_after_layout_overflow(self) -> None:
        if self._presentation or not self._board.unplaced:
            return
        self._open_panel(PANEL_UNPLACED)
        self._tray.focus_first_item()

    def show_overview(self) -> None:
        """Show a scaled, read-only full Board projection without capture."""
        self._close_author_flyouts()
        self._refresh_projection()
        self._overview.setGeometry(self._board_scroll.geometry())
        self._overview.raise_()
        self._overview.show()
        self._overview.setFocus(Qt.OtherFocusReason)
        self._sync_authoring_availability()
        self._sync_empty_board_cue()

    def hide_overview(self) -> None:
        if self._overview.isVisible():
            self._overview.hide()
            self._sync_authoring_availability()
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
        self._close_author_flyouts()
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
        self.set_compare_filter(COMPARE_FILTER_ALL)
        self._library.set_pinned(False)
        if self._focus.isVisible():
            self._focus.close_layer()
        self._close_active_panel()
        if self._author_ui is not None:
            self._author_ui.reset()
        if self._board_context is not None:
            self._board_context.reset()
        self.clear_card_selection()
        self.clear_replacement_arm()
        self._viewport_ctrl.reset()
        if self._floating_chrome is not None:
            self._floating_chrome.reset()
        if self._presentation:
            self.set_presentation_active(False)
            if emit_presentation:
                self.presentation_toggled.emit(False)
        self.fit_on_open()

    def shutdown(self) -> None:
        """Stop owned timers and disconnect controller slots. Safe if never connected."""
        if self._viewport_router is not None:
            self._viewport_router.uninstall()
        if self._viewport_ctrl is not None:
            self._viewport_ctrl.shutdown()
        if self._author_ui is not None:
            self._author_ui.shutdown()
        if self._board_context is not None:
            self._board_context.shutdown()
        if self._floating_chrome is not None:
            self._floating_chrome.shutdown()

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
        return is_text_input_widget(QApplication.focusWidget())

    def _viewport_router_is_active(self) -> bool:
        """Limit QApplication gesture routing to a shown Board host.

        ``activeWindow()`` is not part of this predicate. Offscreen tests and
        leftover parentless widgets (capture fakes) can remain the session's
        active window after they should have gone away; a real foreign window
        already causes ``WindowDeactivate`` to uninstall the filter.
        """
        return bool(self.isVisible() and self._canvas_host.isVisible())

    def _on_app_focus_changed(self, _old, now) -> None:
        in_edit = is_text_input_widget(now)
        for shortcut in (
            self._esc,
            self._grid_undo,
            self._grid_redo,
            self._select_tool_shortcut,
            self._sticky_tool_shortcut,
            getattr(self, "_text_tool_shortcut", None),
            getattr(self, "_shape_tool_shortcut", None),
            getattr(self, "_connector_tool_shortcut", None),
            getattr(self, "_draw_tool_shortcut", None),
        ):
            if shortcut is not None:
                shortcut.setEnabled(not in_edit)
        if in_edit:
            self.note_space(False)
        # ``now is None`` also fires for transient, non-deactivation reasons
        # (a popup hiding/destroying mid-interaction) and would cancel an
        # in-progress drag out from under the user.  Real window deactivation
        # is already covered by changeEvent(WindowDeactivate) and hideEvent,
        # both of which call _cancel_board_gestures() themselves.

    def handle_escape(self) -> bool:
        if self._free_grid.sticky_note_widget().is_editing():
            self._free_grid.sticky_note_widget().cancel()
            return True
        if (
            self._free_grid.author_text_editor().is_editing()
            or self._interaction.is_editor_active()
        ):
            self._free_grid.hide_author_editor()
            return True
        if self._interaction.draft() is not None:
            tool = self._interaction.draft().tool
            self._interaction.cancel_draft()
            if tool == TOOL_SHAPES:
                self._clear_shape_draft_paint()
            if tool == TOOL_CONNECTOR:
                self._clear_connector_draft_paint()
            if tool == TOOL_DRAW:
                self._clear_draw_draft_paint()
            self._sync_tool_rail_from_controller()
            self._sync_tool_cursor()
            return True
        if self._viewport.is_panning():
            self.end_board_pan()
            return True
        if self._grid.cancel_gesture():
            return True
        if self._free_grid.cancel_gesture():
            return True
        if any(flyout.isVisible() for flyout in self._author_flyouts()):
            self._close_author_flyouts()
            return True
        if self._format_picker.isVisible() or self._format_picker_key:
            self._close_format_picker()
            return True
        if self._interaction.active_tool() != TOOL_SELECT:
            self._interaction.set_active_tool(TOOL_SELECT)
            self._sync_tool_rail_from_controller()
            self._free_grid.sync_tool_cursor()
            return True
        if self.clear_card_selection():
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
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._stop_edge_pan()
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
        elif self._is_board_context_menu_event(watched, event):
            return self._handle_board_context_menu(watched, event)
        elif getattr(self, "_free_grid", None) is not None and (
            watched is self._free_grid or isinstance(watched, FreeGridCard)
        ):
            router = getattr(self, "_pointer_router", None)
            if router is not None and router.handle_board_event(watched, event):
                if event.type() in (QEvent.MouseButtonRelease, QEvent.TabletRelease):
                    QTimer.singleShot(0, self._refresh_author_toolbar)
                return True
            if event.type() == QEvent.KeyPress and self._handle_board_selection_key(event):
                return True
            if event.type() == QEvent.MouseButtonRelease:
                QTimer.singleShot(0, self._refresh_author_toolbar)
        return super().eventFilter(watched, event)

    def _is_board_context_menu_event(self, watched, event) -> bool:
        if self._board_context is None:
            return False
        return self._board_context.is_board_context_menu_event(watched, event)

    def _board_context_menu_blocked(self) -> bool:
        return self._board_context.board_context_menu_blocked()

    def _is_blank_board_context_hit(self, watched, event) -> bool:
        return self._board_context.is_blank_board_context_hit(watched, event)

    def _handle_board_context_menu(self, watched, event) -> bool:
        return self._board_context.handle_board_context_menu(watched, event)

    def make_board_context_menu(self) -> QMenu:
        return self._board_context.make_board_context_menu()

    def _board_layout_mode(self) -> str:
        return self._board.layout_mode

    def _board_free_grid_count(self) -> int:
        return len(self._board.free_grid)

    def _free_grid_gesture_active(self) -> bool:
        return self._free_grid.gesture().is_active()

    def _auto_arrange_undo_available(self) -> bool:
        resolver = getattr(self, "can_undo_auto_arrange", None)
        return bool(callable(resolver) and resolver())

    def _popup_board_context_menu(self, global_pos: QPoint) -> None:
        self._board_context.popup_board_context_menu(global_pos)

    def _exec_native_menu(self, menu, global_pos: QPoint, *, trigger=None) -> None:
        self._canvas_host.close_active_overlay(restore_focus=False)
        if trigger is not None:
            menu.aboutToHide.connect(partial(self._restore_menu_trigger, trigger))
        menu.popup(global_pos)

    def _restore_menu_trigger(self, trigger) -> None:
        if trigger is None:
            return
        try:
            visible = trigger.isVisible() and trigger.isEnabled()
        except RuntimeError:
            return
        if visible:
            trigger.setFocus(Qt.OtherFocusReason)

    def _close_board_context_menu(self) -> None:
        self._board_context.close_board_context_menu()

    def _on_board_context_menu_hidden(self) -> None:
        self._board_context._on_board_context_menu_hidden()

    def _on_board_menu_zoom_fit(self, _checked: bool = False) -> None:
        self._board_context._on_board_menu_zoom_fit(_checked)

    def _on_board_menu_zoom_reset(self, _checked: bool = False) -> None:
        self._board_context._on_board_menu_zoom_reset(_checked)

    def _on_board_menu_overview(self, _checked: bool = False) -> None:
        self._board_context._on_board_menu_overview(_checked)

    def _on_board_menu_auto_arrange(self, _checked: bool = False) -> None:
        self._board_context._on_board_menu_auto_arrange(_checked)

    def _on_board_menu_undo_arrange(self, _checked: bool = False) -> None:
        self._board_context._on_board_menu_undo_arrange(_checked)

    def _on_board_menu_copy(self, _checked: bool = False) -> None:
        self._board_context._on_board_menu_copy(_checked)

    def _on_board_menu_export(self, _checked: bool = False) -> None:
        self._board_context._on_board_menu_export(_checked)

    def _cancel_board_gestures(self) -> None:
        self._commit_or_cancel_text_editor()
        self._text_geometry_session = None
        self._shape_geometry_session = None
        self._connector_geometry_session = None
        if self._interaction.draft() is not None and self._interaction.draft().tool == TOOL_SHAPES:
            self._interaction.cancel_draft()
            self._clear_shape_draft_paint()
        if self._interaction.draft() is not None and self._interaction.draft().tool == TOOL_CONNECTOR:
            self._interaction.cancel_draft()
            self._clear_connector_draft_paint()
        if self._interaction.draft() is not None and self._interaction.draft().tool == TOOL_DRAW:
            self._interaction.cancel_draft()
            self._clear_draw_draft_paint()
        self._viewport_ctrl.cancel()
        if self._grid.is_gesture_active():
            self._grid.cancel_gesture()
        if self._free_grid.gesture().is_active():
            self._free_grid.cancel_gesture()

    def event(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.WindowDeactivate:
            self._commit_or_cancel_text_editor()
            self._text_geometry_session = None
            self._shape_geometry_session = None
            self._connector_geometry_session = None
            if self._interaction.draft() is not None and self._interaction.draft().tool == TOOL_SHAPES:
                self._interaction.cancel_draft()
                self._clear_shape_draft_paint()
            if self._interaction.draft() is not None and self._interaction.draft().tool == TOOL_CONNECTOR:
                self._interaction.cancel_draft()
                self._clear_connector_draft_paint()
            if self._interaction.draft() is not None and self._interaction.draft().tool == TOOL_DRAW:
                self._interaction.cancel_draft()
                self._clear_draw_draft_paint()
        return super().event(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowDeactivate:
            self._viewport_router.uninstall()
            self._viewport_ctrl.hide()
            self._cancel_board_gestures()
        elif event.type() == QEvent.WindowActivate:
            self._viewport_router.install()
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._viewport_router.install()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._viewport_router.uninstall()
        self._viewport_ctrl.hide()
        self._cancel_board_gestures()
        super().hideEvent(event)

    def _on_drag_started(self, kind: str) -> None:
        self._drag_kind = kind
        if kind == "card":
            self._card_context.hide()

    def _resolve_insert_span_for_drag(
        self, section: str, view_id: str
    ) -> tuple[int, int] | None:
        resolver = getattr(self, "resolve_insert_span", None)
        if not callable(resolver):
            return None
        return resolver(section, view_id)

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
            self._restore_viewport_from_board(self._board)

    def _emit_feedback(self, message: str) -> None:
        if message == text_for_key(SAFETY_BOUNDS):
            if not self._feedback_gate.allow_hard_reject(SAFETY_BOUNDS, self._now()):
                return
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
            anchor = self.current_free_grid_insert_anchor()
            if anchor is not None:
                self.free_grid_insert_requested.emit(section, view_id, anchor)
            else:
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

    def _on_free_grid_insert_requested(
        self, section: str, view_id: str, anchor: GridAnchor
    ) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        if ref in self._board.unplaced:
            self.free_grid_insert_requested.emit(section, view_id, anchor)
        elif ref not in membership_set(self._board):
            self.free_grid_insert_requested.emit(section, view_id, anchor)
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
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            anchor = self.current_free_grid_insert_anchor()
            if anchor is not None:
                self.free_grid_insert_requested.emit(section, view_id, anchor)
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
        self._interaction.select_only_card(ref)
        self._library.set_selected(ref.section, ref.view_id)
        if ref in self._board.unplaced:
            self._open_panel(PANEL_UNPLACED)
            self._tray.focus_first_item()
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self._free_grid.sync_selection_projection()
        self._refresh_projection()
        self.selection_changed.emit(ref.section, ref.view_id)

    def _author_flyouts(self):
        return (
            self._pointer_popover,
            self._sticky_popover,
            self._shape_popover,
            self._connector_popover,
            self._draw_popover,
        )

    def _register_author_flyouts(self) -> None:
        for overlay_id, widget, tool in (
            (OVERLAY_AUTHOR_POINTER, self._pointer_popover, TOOL_SELECT),
            (OVERLAY_AUTHOR_STICKY, self._sticky_popover, TOOL_STICKY),
            (OVERLAY_AUTHOR_SHAPES, self._shape_popover, TOOL_SHAPES),
            (OVERLAY_AUTHOR_DRAW, self._draw_popover, TOOL_DRAW),
            (OVERLAY_AUTHOR_CONNECTOR, self._connector_popover, TOOL_CONNECTOR),
        ):
            self._canvas_host.register_overlay(
                overlay_id,
                widget,
                trigger=self._tool_rail.tool_button(tool),
                close_on_canvas_click=True,
            )

    def _author_flyout_safe_rect(self) -> QRect:
        return self._author_ui.author_flyout_safe_rect()

    def _author_flyout_rect(self, button: QWidget | None, size: QSize) -> QRect:
        return self._author_ui.author_flyout_rect(button, size)

    def _open_author_flyout(self, overlay_id: str, flyout, button: QWidget | None) -> None:
        self._author_ui.open_author_flyout(overlay_id, flyout, button)

    def _close_author_flyouts(self, keep=None) -> None:
        if self._author_ui is None:
            return
        self._author_ui.close_author_flyouts(keep=keep)

    def _show_tool_flyout(self, tool: str) -> None:
        self._author_ui.show_tool_flyout(tool)

    def _toggle_tool_flyout(self, tool: str) -> None:
        self._author_ui.toggle_tool_flyout(tool)

    def _on_author_tool_requested(self, tool: str) -> None:
        self._author_ui.on_author_tool_requested(tool)

    def _on_pointer_menu_requested(self) -> None:
        self._author_ui.on_pointer_menu_requested()

    def _on_pointer_mode_requested(self, mode: str) -> None:
        self._author_ui.on_pointer_mode_requested(mode)

    def _apply_pointer_mode(self, mode: str) -> None:
        self._author_ui.apply_pointer_mode(mode)

    def _show_pointer_popover(self) -> None:
        self._author_ui.show_pointer_popover()

    def pointer_popover(self):
        return self._pointer_popover

    def _on_author_tool_pinned(self, tool: str, pinned: bool) -> None:
        self._author_ui.on_author_tool_pinned(tool, pinned)

    def _on_sticky_palette_selected(self, token: str) -> None:
        self._author_ui.on_sticky_palette_selected(token)

    def _on_sticky_stack_requested(self, token: str) -> None:
        self._author_ui.on_sticky_stack_requested(token)

    def _show_sticky_popover(self) -> None:
        self._author_ui.show_sticky_popover()

    def sticky_popover(self) -> StickyPopover:
        return self._sticky_popover

    def shape_popover(self) -> ShapePopover:
        return self._shape_popover

    def connector_popover(self) -> ConnectorPopover:
        return self._connector_popover

    def draw_popover(self) -> DrawPopover:
        return self._draw_popover

    def selection_toolbar(self) -> SelectionToolbar:
        return self._selection_toolbar

    def _on_sticky_pin_requested(self, pinned: bool) -> None:
        self._author_ui.on_sticky_pin_requested(pinned)

    def _on_shape_selected(self, shape: str) -> None:
        self._author_ui.on_shape_selected(shape)

    def _on_shape_pin_requested(self, pinned: bool) -> None:
        self._author_ui.on_shape_pin_requested(pinned)

    def _show_shape_popover(self) -> None:
        self._author_ui.show_shape_popover()

    def _sync_tool_rail_from_controller(self) -> None:
        if self._author_ui is None:
            return
        self._author_ui.sync_tool_rail_from_controller()

    def _on_select_tool_shortcut(self) -> None:
        self._author_ui.on_select_tool_shortcut()

    def _on_sticky_tool_shortcut(self) -> None:
        self._author_ui.on_sticky_tool_shortcut()

    def _on_text_tool_shortcut(self) -> None:
        self._author_ui.on_text_tool_shortcut()

    def _on_shape_tool_shortcut(self) -> None:
        self._author_ui.on_shape_tool_shortcut()

    def _on_connector_selected(self, kind: str) -> None:
        self._author_ui.on_connector_selected(kind)

    def _on_connector_pin_requested(self, pinned: bool) -> None:
        self._author_ui.on_connector_pin_requested(pinned)

    def _show_connector_popover(self) -> None:
        self._author_ui.show_connector_popover()

    def _on_connector_tool_shortcut(self) -> None:
        self._author_ui.on_connector_tool_shortcut()

    def _on_draw_tool_selected(self, tool: str, preset_index: int) -> None:
        self._author_ui.on_draw_tool_selected(tool, preset_index)

    def _show_draw_popover(self) -> None:
        self._author_ui.show_draw_popover()

    def _relayout_draw_popover(self) -> None:
        self._author_ui.relayout_draw_popover()

    def _on_draw_tool_shortcut(self) -> None:
        self._author_ui.on_draw_tool_shortcut()

    def _sync_tool_cursor(self) -> None:
        self._free_grid.sync_tool_cursor()
        if not self._viewport.is_panning() and not self._viewport.space_down():
            cursor = self._free_grid.pointer_cursor()
            viewport = self._board_scroll.viewport()
            if cursor is None:
                viewport.unsetCursor()
            else:
                viewport.setCursor(cursor)
        if (
            self._draw_create_armed()
            and not self._viewport.is_panning()
            and not self._viewport.space_down()
        ):
            self._free_grid.setCursor(Qt.CrossCursor)

    def _on_author_edit_requested(self, object_id: str) -> None:
        item = self._author_item(object_id)
        if isinstance(item, TextObject):
            self._begin_text_edit(item, replace=False)
            return
        if isinstance(item, ShapeObject):
            self._begin_shape_label_edit(item, replace=False)
            return
        if isinstance(item, ConnectorObject):
            self._begin_connector_label_edit(item)

    def _on_selection_more_requested(self) -> None:
        toolbar = self._selection_toolbar
        caps = self._selection_capabilities()
        menu = QMenu(self)
        apply_rounded_menu_chrome(menu)
        self._more_menu = menu
        if caps.can_delete:
            action = menu.addAction("删除")
            action.triggered.connect(partial(self._on_more_action, "delete"))
        if caps.can_z_order:
            for key, label in (
                ("z_front", "置于顶层"),
                ("z_back", "置于底层"),
                ("z_forward", "上移一层"),
                ("z_backward", "下移一层"),
            ):
                action = menu.addAction(label)
                action.triggered.connect(partial(self._on_more_action, key))
        overflow_labels = {
            "align_left": "左齐",
            "align_center": "水平居中",
            "align_right": "右齐",
            "align_top": "顶齐",
            "align_middle": "垂直居中",
            "align_bottom": "底齐",
            "distribute_h": "水平分布",
            "distribute_v": "垂直分布",
            "copy_image": "复制图",
            "sync": "同步",
            "fit": "Card Fit",
            "font_size": "字号",
            "list_style": "列表",
            "text_palette": "文字颜色",
            "fill_palette": "底色",
            "link": "链接",
            "lock": "锁定",
            "text": "文字",
            "label": "标签",
            "shape": "方形",
        }
        for key in toolbar.overflow_keys():
            if key in {"delete", "z_front", "z_back", "z_forward", "z_backward"}:
                continue
            label = overflow_labels.get(key)
            if label is None:
                control = next((item for item in caps.controls if item.key == key), None)
                label = control.label if control is not None else key
            action = menu.addAction(str(label))
            action.triggered.connect(partial(self._on_more_action, key))
        if menu.actions():
            button = toolbar.more_button()
            self._exec_native_menu(
                menu,
                button.mapToGlobal(QPoint(0, button.height())),
                trigger=button,
            )

    def _on_more_action(self, key: str, _checked: bool = False) -> None:
        self._on_selection_format_requested(key, True)

    def format_picker(self) -> FormatChoiceFlyout:
        return self._format_picker

    def _close_format_picker(self) -> None:
        if self._author_ui is None:
            return
        self._author_ui.close_format_picker()

    def _format_picker_rect(self, button: QWidget, size: QSize) -> QRect:
        return self._author_ui.format_picker_rect(button, size)

    def _on_format_choice_selected(self, value: object) -> None:
        self._author_ui.on_format_choice_selected(value)

    def _popup_format_picker(self, key: str) -> None:
        self._author_ui.popup_format_picker(key)

    def _on_selection_format_requested(self, key: str, value: object) -> None:
        caps = self._selection_capabilities()
        if key in _FORMAT_PICKER_KEYS and value is True:
            self._popup_format_picker(key)
            return
        if key == "open":
            if len(caps.card_refs) == 1:
                ref = caps.card_refs[0]
                self.open_source_requested.emit(ref.section, ref.view_id)
            return
        if key == "sync":
            for ref in caps.card_refs:
                self.sync_requested.emit(ref.section, ref.view_id)
            return
        if key == "focus":
            if len(caps.card_refs) == 1:
                ref = caps.card_refs[0]
                self._on_focus(ref.section, ref.view_id)
            return
        if key == "fit":
            if len(caps.card_refs) == 1:
                ref = caps.card_refs[0]
                self.free_grid_autofit_requested.emit(ref.section, ref.view_id)
            return
        if key == "copy_image":
            if len(caps.card_refs) == 1:
                ref = caps.card_refs[0]
                self.copy_card_image_requested.emit(ref.section, ref.view_id)
            return
        if key == "z_forward":
            self.author_batch_requested.emit(AuthorZOrderIntent(caps.author_ids, "forward"))
            return
        if key == "z_backward":
            self.author_batch_requested.emit(AuthorZOrderIntent(caps.author_ids, "backward"))
            return
        if key == "duplicate":
            self._duplicate_selection()
            return
        if key.startswith("align_"):
            alignment = key[len("align_") :]
            self.author_batch_requested.emit(AuthorAlignIntent(caps.author_ids, alignment))
            return
        if key == "distribute_h":
            self.author_batch_requested.emit(
                AuthorDistributeIntent(caps.author_ids, "horizontal")
            )
            return
        if key == "distribute_v":
            self.author_batch_requested.emit(
                AuthorDistributeIntent(caps.author_ids, "vertical")
            )
            return
        if key == "z_front":
            self.author_batch_requested.emit(AuthorZOrderIntent(caps.author_ids, "front"))
            return
        if key == "z_back":
            self.author_batch_requested.emit(AuthorZOrderIntent(caps.author_ids, "back"))
            return
        if key == "delete":
            self._delete_selection()
            return
        if key == "lock" and (
            len(caps.author_ids) != 1 or caps.kind in {"mixed", "card_author", "sticky", "stroke"}
        ):
            target = True if caps.lock_state is not True else False
            self.author_batch_requested.emit(
                AuthorLockIntent(caps.author_ids, locked=target)
            )
            QTimer.singleShot(0, self._refresh_author_toolbar)
            return
        if len(caps.author_ids) > 1 and key not in {"text", "label", "open", "sync", "fit"}:
            self.author_batch_requested.emit(
                AuthorBatchStyleIntent(caps.author_ids, key, value)
            )
            QTimer.singleShot(0, self._refresh_author_toolbar)
            return
        if caps.kind == "shape" or self._selection_toolbar.kind() == "shape":
            self._on_shape_format_requested(key, value)
            return
        if caps.kind == "connector" or self._selection_toolbar.kind() == "connector":
            self._on_connector_format_requested(key, value)
            return
        if caps.kind == "sticky":
            self._on_sticky_format_requested(key, value)
            return
        if caps.kind == "stroke":
            self._on_stroke_format_requested(key, value)
            return
        if caps.kind != "text" and self._selection_toolbar.kind() != "text":
            return
        editor = self._free_grid.author_text_editor()
        object_id = editor.object_id() if editor.is_editing() else ""
        if not object_id:
            ids = self._interaction.author_selection_ids()
            if len(ids) != 1:
                return
            object_id = next(iter(ids))
        item = self._author_item(object_id)
        current = item if isinstance(item, TextObject) else None
        if current is None and editor.is_editing():
            fmt = self._interaction.text_format()
            current = TextObject(
                object_id,
                "text",
                box=BoardBox(0.0, 0.0, TEXT_DEFAULT_WIDTH, 1.0),
                text=editor.current_text(),
                font_role=fmt.font_role,
                font_size=fmt.font_size,
                bold=fmt.bold,
                italic=fmt.italic,
                underline=fmt.underline,
                align=fmt.align,
                list_style=fmt.list_style,
                text_palette=fmt.text_palette,
                fill_palette=fmt.fill_palette,
                opacity=fmt.opacity,
                link=fmt.link,
            )
        if current is None:
            return
        changes = next_style_changes(current, key, value)
        if not changes:
            return
        self._interaction.set_text_format(**{
            field: getattr(current, field) if field not in changes else changes[field]
            for field in (
                "font_role",
                "font_size",
                "bold",
                "italic",
                "underline",
                "align",
                "list_style",
                "text_palette",
                "fill_palette",
                "opacity",
                "link",
            )
        })
        if editor.is_editing() and editor.object_id() == object_id:
            live = _replace_text_style(current, changes)
            editor.apply_live_style(live)
            if self._interaction.draft() is not None:
                return
        self.author_update_requested.emit(TextUpdateIntent(object_id, **changes))

    def _on_sticky_format_requested(self, key: str, value: object) -> None:
        ids = tuple(self._interaction.author_selection_ids())
        item = self._author_item(ids[0]) if len(ids) == 1 else None
        if not isinstance(item, StickyObject):
            return
        changes = next_style_changes(item, key, value)
        if not changes:
            return
        payload = {}
        if "palette" in changes:
            payload["palette"] = changes["palette"]
        if "shape" in changes:
            payload["shape"] = changes["shape"]
        if "font_size" in changes:
            payload["font_size"] = changes["font_size"]
        if "locked" in changes:
            payload["locked"] = changes["locked"]
        if payload:
            self.author_update_requested.emit(AuthorUpdateIntent(item.object_id, **payload))
            QTimer.singleShot(0, self._refresh_author_toolbar)

    def _on_stroke_format_requested(self, key: str, value: object) -> None:
        ids = tuple(self._interaction.author_selection_ids())
        item = self._author_item(ids[0]) if len(ids) == 1 else None
        if not isinstance(item, StrokeObject):
            return
        changes = next_style_changes(item, key, value)
        if not changes:
            return
        self.author_update_requested.emit(StrokeUpdateIntent(item.object_id, **changes))
        QTimer.singleShot(0, self._refresh_author_toolbar)

    def _editable_author_ids(self) -> tuple[str, ...]:
        caps = self._selection_capabilities()
        skipped = set(caps.skipped_unknown) | set(caps.skipped_locked)
        return tuple(object_id for object_id in caps.author_ids if object_id not in skipped)

    def _duplicate_selection(self) -> None:
        if self._board_shortcuts_blocked():
            return
        ids = self._editable_author_ids()
        if not ids:
            return
        self.author_batch_requested.emit(AuthorDuplicateIntent(ids))

    def _copy_selection(self) -> None:
        if self._board_shortcuts_blocked():
            return
        caps = self._selection_capabilities()
        payload = copy_author_objects(self._board, caps.author_ids)
        self._interaction.set_clipboard(payload)

    def _paste_selection(self) -> None:
        if self._board_shortcuts_blocked():
            return
        payload = self._interaction.clipboard()
        if payload is None or not payload.objects:
            return
        self.author_batch_requested.emit(AuthorPasteIntent(payload))

    def _delete_selection(self) -> None:
        if self._board_shortcuts_blocked():
            return
        caps = self._selection_capabilities()
        author_ids = self._editable_author_ids()
        if caps.card_refs and (author_ids or caps.author_ids):
            self.author_batch_requested.emit(
                SelectionDeleteIntent(author_ids, caps.card_refs)
            )
            return
        if author_ids:
            locked = bool(caps.skipped_locked) and not author_ids
            if locked or (caps.skipped_locked and not author_ids):
                self._emit_feedback(text_for_key(AUTHOR_LOCKED))
                return
            self.author_delete_requested.emit(AuthorDeleteIntent(author_ids))
            return
        for ref in caps.card_refs:
            self.remove_ref_requested.emit(ref.section, ref.view_id)

    def _nudge_selection(self, dx: float, dy: float) -> None:
        if self._board_shortcuts_blocked():
            return
        caps = self._selection_capabilities()
        author_ids = self._editable_author_ids()
        if caps.card_refs:
            self.author_batch_requested.emit(
                SelectionNudgeIntent(author_ids, caps.card_refs, dx, dy)
            )
            return
        if author_ids:
            self.author_batch_requested.emit(AuthorNudgeIntent(author_ids, dx, dy))

    def _board_shortcuts_blocked(self) -> bool:
        if self._text_field_has_focus() or self._interaction.is_editor_active():
            return True
        if self._free_grid.author_text_editor().is_editing():
            return True
        if self._free_grid.sticky_note_widget().is_editing():
            return True
        return False

    def _handle_board_selection_key(self, event) -> bool:
        if self._board_shortcuts_blocked():
            return False
        key = event.key()
        modifiers = event.modifiers()
        ctrl = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))
        if ctrl and key == Qt.Key_D:
            self._duplicate_selection()
            return True
        if ctrl and key == Qt.Key_C:
            self._copy_selection()
            return True
        if ctrl and key == Qt.Key_V:
            self._paste_selection()
            return True
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            caps = self._selection_capabilities()
            if caps.card_refs and caps.author_ids:
                self._delete_selection()
                return True
            return False
        arrows = {
            Qt.Key_Left: (-1.0, 0.0),
            Qt.Key_Right: (1.0, 0.0),
            Qt.Key_Up: (0.0, -1.0),
            Qt.Key_Down: (0.0, 1.0),
        }
        delta = arrows.get(key)
        if delta is None or ctrl:
            return False
        caps = self._selection_capabilities()
        if not caps.author_ids:
            return False
        step = NUDGE_STEP_SHIFT if modifiers & Qt.ShiftModifier else NUDGE_STEP
        self._nudge_selection(delta[0] * step, delta[1] * step)
        return True

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._handle_board_selection_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_author_create_requested(self, intent) -> None:
        self._sync_tool_rail_from_controller()
        self.author_create_requested.emit(intent)

    def _on_author_update_requested(self, intent) -> None:
        self.author_update_requested.emit(intent)

    def _on_author_delete_requested(self, intent) -> None:
        self.author_delete_requested.emit(intent)

    def select_ref(self, ref: UltraViewRef) -> None:
        """Select a Board reference for coordinator-driven locate actions."""
        self._select_ref(ref)

    def _status_for(self, ref: UltraViewRef) -> str:
        explicit = self._statuses[ref] if ref in self._statuses else None
        return status_for(explicit, self._ref_exists.get(ref, True), self._previews.get(ref))

    def _library_row_for(self, ref: UltraViewRef):
        for row in self._library.row_widgets():
            item = row.row()
            if item.section == ref.section and item.view_id == ref.view_id:
                return item
        return None

    def _chrome_facts_for(self, ref: UltraViewRef) -> LibraryChromeFacts | None:
        item = self._library_row_for(ref)
        if item is None:
            return None
        return LibraryChromeFacts(
            section=item.section,
            view_id=item.view_id,
            name=item.name,
            tab_color=item.tab_color,
            source_summary=item.source_summary,
        )

    def _library_chrome_map(self) -> dict[tuple[str, str], LibraryChromeFacts]:
        facts: dict[tuple[str, str], LibraryChromeFacts] = {}
        for row in self._library.row_widgets():
            item = row.row()
            key = (item.section, item.view_id)
            if key in facts:
                continue
            facts[key] = LibraryChromeFacts(
                section=item.section,
                view_id=item.view_id,
                name=item.name,
                tab_color=item.tab_color,
                source_summary=item.source_summary,
            )
        return facts

    def _chrome_value(
        self,
        ref: UltraViewRef,
        *,
        lib_attr: str,
        record_attr: str,
        default: str = "",
    ) -> str:
        live = self._ref_exists.get(ref, True)
        chrome = self._chrome_facts_for(ref)
        record = self._previews.get(ref)
        lib_val = str(getattr(chrome, lib_attr, "") or "") if chrome is not None else ""
        rec_val = (
            str(getattr(record, record_attr, "") or "") if record is not None else ""
        )
        return chrome_value(live, lib_val, rec_val, default)

    def _title_for(self, ref: UltraViewRef) -> str:
        return title_for(
            ref,
            self._ref_exists.get(ref, True),
            self._chrome_facts_for(ref),
            self._previews.get(ref),
        )

    def _color_for(self, ref: UltraViewRef) -> str:
        return color_for(
            ref,
            self._ref_exists.get(ref, True),
            self._chrome_facts_for(ref),
            self._previews.get(ref),
        )

    def _source_for(self, ref: UltraViewRef) -> str:
        return source_for(
            ref,
            self._ref_exists.get(ref, True),
            self._chrome_facts_for(ref),
            self._previews.get(ref),
        )

    def _axis_for(self, ref: UltraViewRef) -> str | None:
        return axis_kind_from_record(self._previews.get(ref))

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
        self._free_grid.set_author_objects(())
        self._minimap.hide()
        self._board_stack.setCurrentWidget(self._grid)
        chrome_by_key = self._library_chrome_map()
        slot_refs = {
            slot_id: slot_occupant(self._board, slot_id)
            for slot_id in layout_slots(self._board.layout_id)
        }
        models = card_models_for_slots(
            slot_refs,
            chrome_by_key=chrome_by_key,
            records=self._previews,
            statuses=self._statuses,
            exists=self._ref_exists,
            selected=self._interaction.card_selection(),
            compare_filter=self._compare_filter,
            replacement_ref=self._replacement_ref,
            replacement_slot=self._replacement_slot,
            show_title=bool(self._board.show_titles),
            show_source=bool(self._board.show_sources),
            show_card_actions=self._show_card_actions,
        )
        axis_records = axis_records_from_models(models.values())
        self._grid.set_grid(self._board.layout_id, self._board.primary_ratio, models)
        self._sync_board_stack_geometry(self._grid)
        self._apply_lod_chrome()
        self._sync_overview()
        titles, colors, statuses = tray_chrome_maps(
            self._board.unplaced,
            chrome_by_key=chrome_by_key,
            records=self._previews,
            statuses=self._statuses,
            exists=self._ref_exists,
        )
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

    def _sync_authoring_availability(self) -> None:
        """Gate creation chrome; unfinished tools stay hidden on the release rail."""
        if not self._tool_rail.visible_author_tools():
            self._disable_authoring("创作工具尚未启用")
            return
        if self._presentation:
            self._disable_authoring("演示模式中不能创建")
            return
        if self._overview.isVisible():
            self._disable_authoring("整板概览中不能创建")
            return
        if self._board.layout_mode != LAYOUT_MODE_FREE_GRID:
            self._disable_authoring("创作工具仅在自由网格中可用")
            return
        self._tool_rail.set_creation_enabled(True)
        self._free_grid.set_creation_allowed(True)

    def _disable_authoring(self, reason: str) -> None:
        self._tool_rail.set_creation_enabled(False, reason)
        self._free_grid.set_creation_allowed(False)

    def _refresh_card_context(self) -> None:
        """Card actions now live on each card; the floating island stays hidden."""
        if self._board_context is None:
            return
        self._board_context.refresh_card_context()

    def _refresh_author_toolbar(self) -> None:
        if self._floating_chrome is None:
            return
        self._floating_chrome.refresh_author_toolbar()

    def _selection_bounds_in_host(self) -> QRect | None:
        caps = self._selection_capabilities()
        union: QRect | None = None

        def _add(rect: QRect) -> None:
            nonlocal union
            union = rect if union is None else union.united(rect)

        for ref in caps.card_refs:
            card = self._free_grid.card_for(ref.section, ref.view_id)
            if card is None:
                continue
            top_left = card.mapTo(self._canvas_host, QPoint(0, 0))
            _add(QRect(top_left, card.size()))
        origin = self._free_grid.author_paint_layer().model().origin_offset
        metrics = self._free_grid.metrics()
        for object_id in caps.author_ids:
            item = self._author_item(object_id)
            bounds = object_bounds(item)
            if bounds is None:
                continue
            mapped = board_box_to_pixels(bounds, metrics, origin_offset=origin)
            if mapped is None:
                continue
            x, y, width, height = mapped
            top_left = self._free_grid.mapTo(
                self._canvas_host, QPoint(int(round(x)), int(round(y)))
            )
            _add(
                QRect(
                    top_left,
                    QSize(max(1, int(round(width))), max(1, int(round(height)))),
                )
            )
        return union

    def _selection_capabilities(self):
        editor = self._free_grid.author_text_editor()
        editor_kind = ""
        editor_id = ""
        if editor.is_editing():
            editor_kind = str(self._editor_kind or "text")
            editor_id = editor.object_id()
        axis_kinds = {
            ref: kind
            for ref in self._interaction.card_selection()
            if (kind := self._axis_for(ref))
        }
        return resolve_selection_capabilities(
            self._board,
            self._interaction.selection(),
            editor_kind=editor_kind,
            editor_object_id=editor_id,
            axis_kinds=axis_kinds,
            show_card_fit=self._board.layout_mode == LAYOUT_MODE_FREE_GRID,
        )

    def _card_model(self, ref: UltraViewRef, *, slot_id: str) -> CardViewModel:
        return card_view_model(
            slot_id=slot_id,
            ref=ref,
            live=self._ref_exists.get(ref, True),
            chrome=self._chrome_facts_for(ref),
            record=self._previews.get(ref),
            explicit_status=self._statuses[ref] if ref in self._statuses else None,
            selected=ref in self._interaction.card_selection(),
            compare_filter=self._compare_filter,
            replacement_armed=replacement_armed_for(
                ref, slot_id, self._replacement_ref, self._replacement_slot
            ),
            show_title=bool(self._board.show_titles),
            show_source=bool(self._board.show_sources),
            show_card_actions=self._show_card_actions,
        )

    def _refresh_free_grid_projection(self) -> None:
        chrome_by_key = self._library_chrome_map()
        slot_refs = {
            f"grid:{item.ref.section}:{item.ref.view_id}": item.ref
            for item in self._board.free_grid
        }
        slot_models = card_models_for_slots(
            slot_refs,
            chrome_by_key=chrome_by_key,
            records=self._previews,
            statuses=self._statuses,
            exists=self._ref_exists,
            selected=self._interaction.card_selection(),
            compare_filter=self._compare_filter,
            replacement_ref=self._replacement_ref,
            replacement_slot=self._replacement_slot,
            show_title=bool(self._board.show_titles),
            show_source=bool(self._board.show_sources),
            show_card_actions=self._show_card_actions,
        )
        models: dict[UltraViewRef, CardViewModel] = {}
        for item in self._board.free_grid:
            model = slot_models[f"grid:{item.ref.section}:{item.ref.view_id}"]
            if model is None:
                continue
            models[item.ref] = model
        self._board_stack.setCurrentWidget(self._free_grid)
        self._free_grid.set_free_grid(self._board.free_grid, models)
        self._free_grid.set_author_objects(self._board.author_objects)
        self._install_card_connector_filters()
        # Selection/preview refreshes run through this projection too.  Do
        # not rebase the runtime coordinate plane for those view-only events;
        # board mutation, resize, zoom and edge-pan own extent growth.
        if self._workspace_extent is None:
            self._refresh_workspace_extent()
        self._sync_board_stack_geometry(self._free_grid)
        self._apply_lod_chrome()
        titles, colors, statuses = tray_chrome_maps(
            self._board.unplaced,
            chrome_by_key=chrome_by_key,
            records=self._previews,
            statuses=self._statuses,
            exists=self._ref_exists,
        )
        axis_records = axis_records_from_models(models.values())
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
        """Lay out the canvas so ``desired_scroll`` is a valid scrollbar value."""
        return self._viewport_ctrl.place_canvas_for_scroll(canvas, desired_scroll)

    def _sync_board_stack_geometry(self, canvas: QWidget) -> None:
        """Keep the scroll host sized to the current logical canvas.

        QStackedWidget's size hint is the maximum of both canvas modes.  The
        Board scroll contract instead needs the active canvas's exact logical
        size, or a 12-card template stops producing scroll bars after a mode
        switch.  Preserve the current stack origin (including zoom pad); Fit
        and restore park explicitly before calling ``_place_canvas_for_scroll``.
        """
        self._viewport_ctrl.sync_board_stack_geometry(canvas)

    def _minimap_should_show(self) -> bool:
        if self._board.layout_mode != LAYOUT_MODE_FREE_GRID:
            return False
        # Runtime halo intentionally creates pan slack even on an empty
        # Board.  It is not user content and must not by itself summon a
        # minimap/navigation affordance.
        if not self._board.free_grid:
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

    def _minimap_geometry_gesture_active(self) -> bool:
        if self._floating_chrome is None:
            return False
        return self._floating_chrome.minimap_geometry_gesture_active()

    def _sync_minimap_placement(self, floating=None) -> None:
        if self._floating_chrome is None:
            return
        self._floating_chrome.sync_minimap_placement(floating)

    def _position_minimap(self, floating=None) -> None:
        self._sync_minimap_placement(floating)

    def _refresh_minimap(self, *_args) -> None:
        if self._floating_chrome is None:
            return
        if not self._minimap_should_show():
            self._floating_chrome.hide_minimap()
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
            workspace_extent=self._workspace_extent,
        )
        self._floating_chrome.sync_minimap_placement()

    def _on_minimap_viewport(self, rect: QRect) -> None:
        self._viewport_ctrl.apply_minimap_viewport(rect)


def _replace_text_style(item: TextObject, changes: dict[str, object]) -> TextObject:
    fields = {
        "font_role": item.font_role,
        "font_size": item.font_size,
        "bold": item.bold,
        "italic": item.italic,
        "underline": item.underline,
        "align": item.align,
        "list_style": item.list_style,
        "text_palette": item.text_palette,
        "fill_palette": item.fill_palette,
        "opacity": item.opacity,
        "link": item.link,
        "locked": item.locked,
        "text": item.text,
        "box": item.box,
    }
    fields.update(changes)
    return TextObject(item.object_id, "text", **fields)
