"""Standalone UltraView page: View library, board grid, cards, overflow tray.

The page is a view. Coordinator / test harness apply intents by mutating
``UltraViewBoardState`` and calling ``set_board``. This module does not import
MainWindow or analysis compute entry points.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from PyQt5.QtCore import QPoint, QRect, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence, QNativeGestureEvent, QWheelEvent
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QLineEdit,
    QMenu,
    QShortcut,
    QStackedWidget,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
    COMPARE_FILTER_ALL,
    STATUS_ORPHANED,
    UltraViewBoardState,
    UltraViewRef,
    axis_consistency_facts,
    board_to_payload,
    card_matches_compare_filter,
    default_board,
    derive_preview_status,
    first_empty_slot,
    free_grid_placement_for,
    layout_slots,
    LAYOUT_MODE_FREE_GRID,
    MAX_UI_BOARDS,
    membership_set,
    parse_ref_payload,
    placement_for,
    slot_occupant,
)

from .viewport import (
    QUALITY_FAST,
    QUALITY_SMOOTH,
    SMOOTH_DELAY_MS,
    ZOOM_BUTTON_STEP,
    BoardViewport,
    clamp_zoom,
    fit_zoom,
    wheel_zoom_factor,
    zoom_at_cursor,
    zoom_percent,
)
from .widgets import (
    LIBRARY_DEFAULT_WIDTH,
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

_FEEDBACK_BOARD_FULL = "Board 已满：换布局或先移除"
_FEEDBACK_NO_SELECTION = "先在左侧 View 库选择一个 View"


def _event_global_point(event) -> QPoint:
    if hasattr(event, "globalPosition"):
        value = event.globalPosition()
        return value.toPoint() if hasattr(value, "toPoint") else QPoint(int(value.x()), int(value.y()))
    if hasattr(event, "globalPos"):
        return event.globalPos()
    if hasattr(event, "screenPos"):
        value = event.screenPos()
        return value.toPoint() if hasattr(value, "toPoint") else QPoint(int(value.x()), int(value.y()))
    return QPoint(0, 0)


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
    organize_free_grid_requested = pyqtSignal()
    free_grid_undo_requested = pyqtSignal()
    free_grid_redo_requested = pyqtSignal()
    viewport_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewPage")
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
        self._presentation = False
        self._library_visible = True
        self._prev_unplaced_count: int | None = None
        self._viewport = BoardViewport()
        self._smooth_timer = QTimer(self)
        self._smooth_timer.setObjectName("ultraViewSmoothPreviewTimer")
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(SMOOTH_DELAY_MS)
        self._smooth_timer.timeout.connect(self._on_smooth_preview_timeout)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.setObjectName("ultraViewSplitter")
        self._library = ViewLibraryPanel(self._splitter)
        self._board_column = QFrame(self._splitter)
        self._board_column.setObjectName("ultraViewBoardColumn")
        self._board_column.setAttribute(Qt.WA_StyledBackground, True)
        column = QVBoxLayout(self._board_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self._switcher = BoardSwitcher(self._board_column)
        self._toolbar = BoardToolbar(self._board_column)
        self._rail = CompareRail(self._board_column)
        self._grid = BoardGrid(self._board_column)
        self._free_grid = FreeGridBoard(self._board_column)
        self._board_stack = QStackedWidget(self._board_column)
        self._board_stack.setObjectName("ultraViewBoardCanvasStack")
        self._board_stack.addWidget(self._grid)
        self._board_stack.addWidget(self._free_grid)
        self._board_scroll = BoardScrollArea(self._board_column)
        self._board_scroll.setWidget(self._board_stack)
        self._tray = UnplacedTray(self._board_column)
        self._overview = BoardOverview(self._board_column)
        self._overview.hide()
        self._minimap = FreeGridMinimap(self._board_scroll.viewport())
        self._minimap.hide()
        column.addWidget(self._switcher, 0)
        column.addWidget(self._toolbar, 0)
        column.addWidget(self._rail, 0)
        column.addWidget(self._board_scroll, 1)
        column.addWidget(self._tray, 0)
        self._splitter.addWidget(self._library)
        self._splitter.addWidget(self._board_column)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([LIBRARY_DEFAULT_WIDTH, 1200])
        root.addWidget(self._splitter, 1)

        self._hint_bar = UltraViewHintBar(self)
        self._hint_bar.quickref_requested.connect(self.quickref_requested.emit)
        root.addWidget(self._hint_bar, 0)

        self._focus = FocusLayer(self)
        self._focus.hide()

        self._library.add_requested.connect(self.request_add)
        self._library.remove_requested.connect(self.remove_ref_requested)
        self._library.locate_requested.connect(self._on_locate)
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
        self._board_scroll.viewport_resized.connect(self._grid.set_viewport_size)
        self._board_scroll.viewport_resized.connect(self._free_grid.set_viewport_size)
        self._board_scroll.viewport_resized.connect(self._refresh_minimap)
        self._board_scroll.horizontalScrollBar().valueChanged.connect(self._refresh_minimap)
        self._board_scroll.verticalScrollBar().valueChanged.connect(self._refresh_minimap)
        self._overview.slot_requested.connect(self._on_overview_slot)
        self._overview.ref_requested.connect(self._on_overview_ref)
        self._overview.close_requested.connect(self.hide_overview)
        self._minimap.viewport_requested.connect(self._on_minimap_viewport)

        self._grid.add_clicked.connect(self._on_empty_slot)
        self._grid.ref_dropped.connect(self._on_ref_dropped)
        self._grid.open_source_requested.connect(self.open_source_requested)
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
        self._free_grid.open_source_requested.connect(self.open_source_requested)
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
        self.set_board(self._board)

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
        viewport = self._board_scroll.viewport()
        canvas = self._active_canvas()
        size = canvas.unzoomed_size()
        self.set_board_zoom(fit_zoom((size.width(), size.height()), (viewport.width(), viewport.height())))

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
        global_pos = _event_global_xy(event)
        self._viewport.begin_pan(global_pos)
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

    def end_board_pan(self) -> None:
        self._viewport.end_pan()
        if self._viewport.space_down():
            self._board_scroll.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self._board_scroll.viewport().unsetCursor()
        self._restart_smooth_timer()

    def handle_zoom_wheel(self, event: QWheelEvent, widget) -> bool:
        delta = event.angleDelta().y()
        factor = wheel_zoom_factor(delta)
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
        before = self._viewport.zoom()
        after = clamp_zoom(zoom)
        cursor = (float(cursor_in_viewport[0]), float(cursor_in_viewport[1]))
        scroll = (
            float(self._board_scroll.horizontalScrollBar().value()),
            float(self._board_scroll.verticalScrollBar().value()),
        )
        new_scroll = zoom_at_cursor(before, after, cursor, scroll)
        self._viewport.set_zoom(after)
        self._grid.set_zoom(after)
        self._free_grid.set_zoom(after)
        self._sync_board_stack_geometry(self._active_canvas())
        self._board_scroll.horizontalScrollBar().setValue(int(round(new_scroll[0])))
        self._board_scroll.verticalScrollBar().setValue(int(round(new_scroll[1])))
        self._toolbar.set_zoom_percent(zoom_percent(after))
        self._apply_preview_quality(QUALITY_FAST)
        self._restart_smooth_timer()
        self.viewport_changed.emit()

    def _cursor_in_scroll_viewport(self, event, widget) -> tuple[float, float]:
        viewport = self._board_scroll.viewport()
        global_pos = _event_global_point(event)
        local = viewport.mapFromGlobal(global_pos)
        return (float(local.x()), float(local.y()))

    def _apply_preview_quality(self, quality: str) -> None:
        self._viewport.set_quality(quality)
        self._grid.set_preview_quality(quality)
        self._free_grid.set_preview_quality(quality)

    def _restart_smooth_timer(self) -> None:
        self._smooth_timer.start(SMOOTH_DELAY_MS)

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
        self._switcher.set_boards(boards, active_id)
        self._switcher.set_create_enabled(
            len(boards) < MAX_UI_BOARDS,
            "最多创建 20 个 Board" if len(boards) >= MAX_UI_BOARDS else "",
        )
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
        self._refresh_projection()

    def show_focus(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        record = self._previews.get(ref) if ref is not None else None
        title = getattr(record, "title", "") if record is not None else view_id
        image = preview_image(record)
        self._focus.setGeometry(self.rect())
        self._focus.show_ref(section, view_id, title or view_id, image)

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

    def is_library_visible(self) -> bool:
        return self._library_visible

    def is_presentation_active(self) -> bool:
        return self._presentation

    def card_widget(self, section: str, view_id: str):
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            return self._free_grid.card_for(section, view_id)
        return self._grid.card_for(section, view_id)

    def slot_widget(self, slot_id: str):
        return self._grid.slot_widget(slot_id)

    def set_library_visible(self, visible: bool) -> None:
        self._library_visible = bool(visible)
        self._library.setVisible(self._library_visible and not self._presentation)

    def set_presentation_active(self, active: bool) -> None:
        self._presentation = bool(active)
        self._toolbar.set_presentation_checked(self._presentation)
        self._library.setVisible(self._library_visible and not self._presentation)
        self._toolbar.set_edit_visible(not self._presentation)
        self._rail.setVisible(not self._presentation)
        self._tray.title_bar().setVisible(True)
        if self._presentation:
            self._tray.body().setVisible(False)
            if (
                self._board.layout_mode == LAYOUT_MODE_FREE_GRID
                or len(layout_slots(self._board.layout_id)) >= 9
            ):
                self.show_overview()
        else:
            self.hide_overview()
            self._tray.body().setVisible(self._tray.is_expanded())

    def set_library_rows(self, rows: Sequence[LibraryRow | Mapping[str, Any]]) -> None:
        coerced = [coerce_library_row(row) for row in rows]
        if self._drag_kind is not None:
            self._pending_library_rows = coerced
            return
        self._apply_library_rows(coerced)

    def _apply_library_rows(self, rows: Sequence[LibraryRow]) -> None:
        self._library.set_rows(rows)
        self._library.set_on_board(membership_set(self._board))

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
        if not keep_overview:
            self.hide_overview()
        if self._workspace is None:
            self._switcher.set_boards((board,), board.board_id)
        self._grid.set_viewport_size(self._board_scroll.viewport().size())
        self._free_grid.set_viewport_size(self._board_scroll.viewport().size())
        prev = self._prev_unplaced_count
        self._board = board
        self._prune_runtime_caches()
        n_unplaced = len(board.unplaced)
        if n_unplaced > 0 and (prev is None or prev == 0):
            self._tray.set_expanded(True)
        self._prev_unplaced_count = n_unplaced
        if self._replacement_ref is not None and self._replacement_ref not in membership_set(board):
            self._replacement_ref = None
            self._replacement_slot = None
        elif self._replacement_slot and self._replacement_slot not in layout_slots(board.layout_id):
            self._replacement_slot = None
        self._toolbar.set_board_name(board.name)
        self._toolbar.set_layout_id(board.layout_id)
        self._toolbar.set_free_grid_enabled(board.layout_mode == LAYOUT_MODE_FREE_GRID)
        self._toolbar.set_show_flags(board.show_titles, board.show_sources)
        if self._drag_kind is not None:
            # Drop handlers mutate the board inside QDrag.exec_(). Rebuilding
            # library/grid/tray here would deleteLater the drag source before
            # mouseMoveEvent returns, which aborts via qFatal.
            self._board_widgets_dirty = True
            return
        self._library.set_on_board(membership_set(board))
        self._refresh_projection()
        self._toolbar.set_zoom_percent(zoom_percent(self._viewport.zoom()))

    def show_overview(self) -> None:
        """Show a scaled, read-only full Board projection without capture."""
        self._refresh_projection()
        self._overview.setGeometry(self._board_scroll.geometry())
        self._overview.raise_()
        self._overview.show()
        self._overview.setFocus(Qt.OtherFocusReason)

    def hide_overview(self) -> None:
        if self._overview.isVisible():
            self._overview.hide()

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
        self._library.focus_search()
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
        self.clear_replacement_arm()
        if self._presentation:
            self.set_presentation_active(False)
            if emit_presentation:
                self.presentation_toggled.emit(False)

    def _on_escape_shortcut(self) -> None:
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

    def handle_escape(self) -> bool:
        if self._viewport.is_panning():
            self.end_board_pan()
            return True
        if self._free_grid.cancel_gesture():
            return True
        if self._focus.isVisible():
            self._focus.close_layer()
            return True
        if self._overview.isVisible():
            self.hide_overview()
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
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID and self._free_grid.clear_selection():
            return True
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._focus.setGeometry(self.rect())
        if self._overview.isVisible():
            self._overview.setGeometry(self._board_scroll.geometry())
        self._position_minimap()

    def _on_drag_started(self, kind: str) -> None:
        self._drag_kind = kind

    def _on_drag_finished(self) -> None:
        self._drag_kind = None
        self._flush_deferred_drag_refresh()

    def _flush_deferred_drag_refresh(self) -> None:
        pending = self._pending_library_rows
        self._pending_library_rows = None
        dirty = self._board_widgets_dirty
        self._board_widgets_dirty = False
        if pending is not None:
            self._apply_library_rows(pending)
        elif dirty:
            self._library.set_on_board(membership_set(self._board))
        if dirty:
            self._refresh_projection()

    def _emit_feedback(self, message: str) -> None:
        self.feedback_requested.emit(message)

    def _on_toolbar_add(self) -> None:
        selected = self._library.selected_ref()
        if selected is None:
            self._library.focus_search()
            self._emit_feedback(_FEEDBACK_NO_SELECTION)
            return
        self._emit_add(selected[0], selected[1])

    def _on_empty_slot(self, slot_id: str) -> None:
        selected = self._library.selected_ref()
        if selected is None:
            self._library.focus_search()
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
        self.focus_requested.emit(section, view_id)
        self.show_focus(section, view_id)

    def _on_rebind_arm(self, section: str, view_id: str) -> None:
        self.arm_replacement(section, view_id)

    def _on_presentation_button(self, checked: bool) -> None:
        self.set_presentation_active(checked)
        self.presentation_toggled.emit(checked)

    def _on_compare_filter(self, filter_id: str) -> None:
        self._compare_filter = filter_id
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
            self._tray.set_expanded(True)
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self._free_grid.select_only(ref.section, ref.view_id)
        self._refresh_projection()
        self.selection_changed.emit(ref.section, ref.view_id)

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
        if self._drag_kind is not None:
            self._board_widgets_dirty = True
            return
        if self._board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self._refresh_free_grid_projection()
            return
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
        self._focus.setGeometry(self.rect())

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
        self._sync_overview()
        self._minimap.show()
        self._refresh_minimap()
        self._focus.setGeometry(self.rect())

    def _sync_board_stack_geometry(self, canvas: QWidget) -> None:
        """Keep the scroll host sized to the current logical canvas.

        QStackedWidget's size hint is the maximum of both canvas modes.  The
        Board scroll contract instead needs the active canvas's exact logical
        size, or a 12-card template stops producing scroll bars after a mode
        switch.
        """
        target = canvas.size()
        if target.width() <= 0 or target.height() <= 0:
            target = canvas.minimumSize()
        self._board_stack.setMinimumSize(target)
        self._board_stack.resize(target)

    def _position_minimap(self) -> None:
        if not self._minimap.isVisible():
            return
        viewport = self._board_scroll.viewport()
        self._minimap.move(
            max(6, viewport.width() - self._minimap.width() - 12),
            max(6, viewport.height() - self._minimap.height() - 12),
        )
        self._minimap.raise_()

    def _refresh_minimap(self, *_args) -> None:
        if self._board.layout_mode != LAYOUT_MODE_FREE_GRID:
            self._minimap.hide()
            return
        viewport = self._board_scroll.viewport()
        self._minimap.set_projection(
            self._free_grid.metrics(),
            self._board.free_grid,
            QRect(
                self._board_scroll.horizontalScrollBar().value(),
                self._board_scroll.verticalScrollBar().value(),
                viewport.width(),
                viewport.height(),
            ),
        )
        self._position_minimap()

    def _on_minimap_viewport(self, rect: QRect) -> None:
        horizontal = self._board_scroll.horizontalScrollBar()
        vertical = self._board_scroll.verticalScrollBar()
        horizontal.setValue(min(horizontal.maximum(), max(horizontal.minimum(), rect.x())))
        vertical.setValue(min(vertical.maximum(), max(vertical.minimum(), rect.y())))
