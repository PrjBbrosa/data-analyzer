"""Own UltraView camera apply. Zoom math stays in ``viewport.py``.

Page remains the composition root: it forwards public zoom/pan methods,
keeps ``ViewportGestureRouter``, and supplies extent / chrome / minimap
callbacks. This module must not reimplement ``zoom_at`` / fit / anchor
formulas.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
import math

from PyQt5.QtCore import QObject, QPoint, QRect, QTimer, QVariantAnimation, Qt
from PyQt5.QtGui import QCursor, QNativeGestureEvent, QWheelEvent
from PyQt5.QtWidgets import QApplication, QStackedWidget, QWidget

from .board_aux_widgets import BoardScrollArea
from .elastic_workspace import edge_pan_velocity
from .free_grid import screen_grid_metrics
from .free_grid_board import FreeGridBoard
from .template_board import BoardGrid
from .viewport import (
    QUALITY_FAST,
    QUALITY_SMOOTH,
    SMOOTH_DELAY_MS,
    ZOOM_BUTTON_STEP,
    BoardViewport,
    board_fit_zoom,
    canvas_point_under,
    center_from_scroll,
    clamp_zoom,
    scroll_for_anchor,
    scroll_for_center,
    two_card_working_frame,
    wheel_zoom_factor,
    zoom_percent,
    zoom_to_rect,
)


def _disconnect(signal, slot) -> None:
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        return


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


class ViewportController(QObject):
    """Single owner of BoardViewport, zoom/pan apply, edge-pan timer, settle."""

    def __init__(
        self,
        *,
        board_scroll: BoardScrollArea,
        board_stack: QStackedWidget,
        board_host: QWidget,
        grid: BoardGrid,
        free_grid: FreeGridBoard,
        active_canvas: Callable[[], QWidget],
        is_free_grid: Callable[[], bool],
        has_board: Callable[[], bool],
        board_id: Callable[[], str | None],
        extent_signature: Callable[..., tuple[int, int, int, int]],
        extent_key: Callable[[], tuple | None],
        content_fill_rect: Callable[[], Any],
        fit_origin: Callable[[], tuple[float, float]],
        working_frame_center: Callable[[], tuple[float, float]],
        card_rect_1x: Callable[[str, str], Any],
        refresh_extent: Callable[..., bool],
        apply_lod_chrome: Callable[[], None],
        set_zoom_percent: Callable[[int], None],
        cancel_board_gestures: Callable[[], None],
        pause_draw: Callable[[], None],
        resume_draw: Callable[[], None],
        sync_tool_cursor: Callable[[], None],
        is_board_canvas_widget: Callable[[object], bool],
        deliver_right_click_menu: Callable[[object], None],
        camera_settled: Callable[[], None],
        sync_feedback_surface: Callable[[], None],
        sync_minimap_placement: Callable[[], None],
        sync_workspace_edge_hint: Callable[[object], None],
        reproject_after_viewport: Callable[[object], None],
        on_edge_pan_started: Callable[[], None],
        on_edge_pan_stopped: Callable[[], None],
        dismiss_author_transients: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._board_scroll = board_scroll
        self._board_stack = board_stack
        self._board_host = board_host
        self._grid = grid
        self._free_grid = free_grid
        self._active_canvas = active_canvas
        self._is_free_grid = is_free_grid
        self._has_board = has_board
        self._board_id = board_id
        self._extent_signature = extent_signature
        self._extent_key = extent_key
        self._content_fill_rect = content_fill_rect
        self._fit_origin = fit_origin
        self._working_frame_center = working_frame_center
        self._card_rect_1x = card_rect_1x
        self._refresh_extent = refresh_extent
        self._apply_lod_chrome = apply_lod_chrome
        self._set_zoom_percent = set_zoom_percent
        self._cancel_board_gestures = cancel_board_gestures
        self._pause_draw = pause_draw
        self._resume_draw = resume_draw
        self._sync_tool_cursor = sync_tool_cursor
        self._is_board_canvas_widget = is_board_canvas_widget
        self._deliver_right_click_menu = deliver_right_click_menu
        self._camera_settled = camera_settled
        self._sync_feedback_surface = sync_feedback_surface
        self._sync_minimap_placement = sync_minimap_placement
        self._sync_workspace_edge_hint = sync_workspace_edge_hint
        self._reproject_after_viewport = reproject_after_viewport
        self._on_edge_pan_started = on_edge_pan_started
        self._on_edge_pan_stopped = on_edge_pan_stopped
        self._dismiss_author_transients = dismiss_author_transients

        self._viewport = BoardViewport()
        self._session_camera: dict[
            str,
            tuple[float, tuple[float, float], tuple[int, int, int, int], tuple[float, float]],
        ] = {}
        self._restoring_viewport = False
        self._pending_fit = True
        self._filled_card: tuple[str, str] | None = None
        self._ignore_next_context_menu = False
        self._right_gesture_widget: QWidget | None = None

        self._edge_pan_timer = QTimer(self)
        self._edge_pan_timer.setObjectName("ultraViewWorkspaceEdgePanTimer")
        self._edge_pan_timer.setInterval(16)
        self._edge_pan_active = False
        self._edge_pan_reentrant = False
        self._edge_pan_global_pos: QPoint | None = None
        self._edge_gesture_token = 0

        self._smooth_timer = QTimer(self)
        self._smooth_timer.setObjectName("ultraViewSmoothPreviewTimer")
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(SMOOTH_DELAY_MS)
        self._zoom_anim = QVariantAnimation(self)
        self._zoom_anim.setObjectName("ultraViewZoomToCardAnimation")
        self._zoom_anim.setDuration(180)
        self._anim_start_zoom = 1.0
        self._anim_end_zoom = 1.0
        self._anim_start_center = (0.0, 0.0)
        self._anim_end_center = (0.0, 0.0)
        self._connected = False
        self._slots: list[tuple[Any, Any]] = []
        self.connect()

    def connect(self) -> None:
        if self._connected:
            return
        pairs = (
            (self._edge_pan_timer.timeout, self._on_edge_pan_tick),
            (self._smooth_timer.timeout, self._on_smooth_preview_timeout),
            (self._zoom_anim.valueChanged, self._on_zoom_anim_tick),
        )
        for signal, slot in pairs:
            signal.connect(slot)
            self._slots.append((signal, slot))
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        for signal, slot in self._slots:
            _disconnect(signal, slot)
        self._slots.clear()
        self._connected = False

    def shutdown(self) -> None:
        self.hide()
        self.disconnect()

    def viewport(self) -> BoardViewport:
        return self._viewport

    def smooth_timer(self) -> QTimer:
        return self._smooth_timer

    def edge_pan_timer(self) -> QTimer:
        return self._edge_pan_timer

    @property
    def edge_pan_active(self) -> bool:
        return self._edge_pan_active

    @edge_pan_active.setter
    def edge_pan_active(self, value: bool) -> None:
        self._edge_pan_active = bool(value)

    @property
    def edge_pan_global_pos(self) -> QPoint | None:
        return self._edge_pan_global_pos

    @edge_pan_global_pos.setter
    def edge_pan_global_pos(self, value) -> None:
        self._edge_pan_global_pos = None if value is None else QPoint(value)

    @property
    def right_gesture_widget(self) -> QWidget | None:
        return self._right_gesture_widget

    def park_zoom(self, zoom: float) -> None:
        """Zoom and leave the board in the chrome-safe fit rect."""
        self._park_zoom(zoom)

    def zoom_at(self, zoom: float, cursor_in_viewport) -> None:
        self._zoom_at(zoom, cursor_in_viewport)

    def on_smooth_preview_timeout(self) -> None:
        self._on_smooth_preview_timeout()

    def filled_card(self) -> tuple[str, str] | None:
        return self._filled_card

    def is_restoring(self) -> bool:
        return self._restoring_viewport

    def begin_restore(self) -> None:
        self._restoring_viewport = True

    def end_restore(self) -> None:
        self._restoring_viewport = False

    def hide(self) -> None:
        self.stop_edge_pan()
        self._stop_anim_and_smooth()
        self.note_space(False)

    def reset(self) -> None:
        self.stop_edge_pan()
        self._stop_anim_and_smooth()
        self._session_camera.clear()
        self._filled_card = None
        self._pending_fit = True

    def cancel(self) -> None:
        self.stop_edge_pan()
        self._stop_anim_and_smooth()
        if self._viewport.is_panning():
            self.end_board_pan()

    def persist(self) -> None:
        if self._restoring_viewport or not self._has_board():
            return
        board_id = self._board_id()
        if board_id is None:
            return
        center = self.current_center()
        origin = self.board_content_origin()
        self._viewport.set_center(center)
        self._session_camera[str(board_id)] = (
            float(self._viewport.zoom()),
            (float(center[0]), float(center[1])),
            self._extent_signature(),
            (float(origin[0]), float(origin[1])),
        )
        self._camera_settled()

    def fit_on_open(self) -> None:
        """Park on 适应 for window open/raise, first visit, and extent rebase."""
        fill = self._content_fill_rect()
        if fill.width <= 1 or fill.height <= 1:
            self._pending_fit = True
            return
        self._pending_fit = False
        self.zoom_fit()

    def apply_initial_viewport(self) -> None:
        """First show / empty payload: same camera as a window open."""
        self.fit_on_open()

    def apply_initial_if_pending(self) -> None:
        if self._pending_fit and self._board_scroll.viewport().width() > 1:
            self._pending_fit = False
            self.apply_initial_viewport()

    def restore_from_board(self, board) -> None:
        """Replay the session camera when this Board's extent signature still matches."""
        camera = self._session_camera.get(str(board.board_id))
        signature = self._extent_signature(board)
        if camera is None or camera[2] != signature:
            self.fit_on_open()
            return
        zoom, center, _saved, *rest = camera
        origin = rest[0] if rest else self.board_content_origin()
        if self._is_free_grid():
            self._refresh_extent(reset=True, preserve_visible=False)
        self._restoring_viewport = True
        try:
            self._apply_zoom_and_center(zoom, center, viewport_origin=origin)
        finally:
            self._restoring_viewport = False

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
        # 100% is a scale reset, not a parking/fit command.  Preserve the
        # world point currently at the viewport centre so users do not get
        # teleported back to the base-frame origin on a wide monitor.
        self._filled_card = None
        self._apply_zoom_and_center(1.0, self.current_center())

    def zoom_fit(self) -> None:
        self._filled_card = None
        canvas = self._active_canvas()
        fill = self._content_fill_rect()
        content = canvas.content_rect_1x()
        if content is None:
            if self._is_free_grid():
                self._refresh_extent()
                frame = two_card_working_frame(screen_grid_metrics(()))
                self._apply_zoom_and_center(
                    board_fit_zoom(frame, (float(fill.width), float(fill.height))),
                    self._working_frame_center(),
                    viewport_size=(float(fill.width), float(fill.height)),
                )
                return
            size = canvas.unzoomed_size()
            self._park_zoom(
                board_fit_zoom(
                    (size.width(), size.height()),
                    (float(fill.width), float(fill.height)),
                )
            )
            return
        # Fit the placed-content box into the fill rect. zoom_to_card
        # uses the raw viewport so a double-click can bleed under the toolbar;
        # 适应 keeps the rail-clear left of ``fit`` and uses the stage-safe
        # top and bottom so the cluster fills the dotted canvas.
        zoom = board_fit_zoom(
            (float(content[2]), float(content[3])),
            (float(fill.width), float(fill.height)),
        )
        center = (float(content[0]) + float(content[2]) / 2.0,
                  float(content[1]) + float(content[3]) / 2.0)
        self._apply_zoom_and_center(
            zoom, center, viewport_size=(float(fill.width), float(fill.height))
        )

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

    def note_space(self, down: bool) -> None:
        self._viewport.set_space_down(down)
        if down:
            self._pause_draw()
            self._board_scroll.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self._resume_draw()
            if not self._viewport.is_panning():
                self._board_scroll.viewport().unsetCursor()
                self._sync_tool_cursor()

    def begin_board_pan(self, event, widget=None) -> bool:
        button = event.button()
        is_right = button == Qt.RightButton
        if button != Qt.MiddleButton and not (
            button == Qt.LeftButton and self._viewport.space_down()
        ) and not is_right:
            return False
        if widget is None and hasattr(event, "globalPos"):
            widget = QApplication.widgetAt(event.globalPos())
        if is_right and not self._is_board_canvas_widget(widget):
            return False
        if not is_right:
            self._cancel_board_gestures()
            self._pause_draw()
        global_pos = _event_global_xy(event)
        self._viewport.begin_pan(global_pos, int(button), deferred=is_right)
        self._right_gesture_widget = widget if is_right else None
        if not is_right:
            self._board_scroll.viewport().setCursor(Qt.ClosedHandCursor)
            self._apply_preview_quality(QUALITY_FAST)
            self._restart_smooth_timer()
        return True

    def update_board_pan(self, event) -> None:
        if not self._viewport.is_panning():
            return
        threshold = 0.0
        if self._viewport.pan_button() == int(Qt.RightButton):
            threshold = float(QApplication.startDragDistance())
        was_committed = self._viewport.pan_committed()
        dx, dy = self._viewport.update_pan(_event_global_xy(event), threshold=threshold)
        if self._viewport.pan_committed() and not was_committed:
            self._cancel_board_gestures()
            self._pause_draw()
            self._board_scroll.viewport().setCursor(Qt.ClosedHandCursor)
            self._apply_preview_quality(QUALITY_FAST)
        if dx == 0.0 and dy == 0.0:
            return
        horizontal = self._board_scroll.horizontalScrollBar()
        vertical = self._board_scroll.verticalScrollBar()
        horizontal.setValue(int(horizontal.value() + dx))
        vertical.setValue(int(vertical.value() + dy))
        self._restart_smooth_timer()

    def end_board_pan_for_event(self, event) -> bool:
        pan_button = self._viewport.pan_button()
        committed = self._viewport.pan_committed()
        if not self._viewport.end_pan(int(event.button())):
            return False
        self._after_end_board_pan()
        if pan_button == int(Qt.RightButton):
            if not committed:
                self._deliver_right_click_menu(event)
            self._arm_context_menu_suppress()
        self._right_gesture_widget = None
        return True

    def end_board_pan(self) -> None:
        if self._viewport.pan_button() == int(Qt.RightButton):
            self._arm_context_menu_suppress()
        if not self._viewport.end_pan(None):
            self._right_gesture_widget = None
            return
        self._right_gesture_widget = None
        self._after_end_board_pan()

    def suppress_board_context_menu_event(self, _event) -> bool:
        if self._ignore_next_context_menu:
            self._ignore_next_context_menu = False
            return True
        return bool(self._viewport.is_panning())

    def apply_minimap_viewport(self, rect: QRect) -> None:
        origin = self.board_content_origin()
        horizontal = self._board_scroll.horizontalScrollBar()
        vertical = self._board_scroll.verticalScrollBar()
        horizontal.setValue(
            min(horizontal.maximum(), max(horizontal.minimum(), int(round(rect.x() + origin[0]))))
        )
        vertical.setValue(
            min(vertical.maximum(), max(vertical.minimum(), int(round(rect.y() + origin[1]))))
        )

    def board_content_origin(self) -> tuple[float, float]:
        """Current board-canvas origin inside the scroll host.

        After a cursor-anchored zoom this may include left/top pad so a
        negative desired scroll stays representable.  Scroll math must use
        this value, not ``fit`` origin: recentering onto fit after
        compensation is what pinned zoom to the chrome-safe corner.
        """
        if self._board_stack.width() <= 0 or self._board_stack.height() <= 0:
            return self._fit_origin()
        return (float(self._board_stack.x()), float(self._board_stack.y()))

    def current_center(self) -> tuple[float, float]:
        viewport = self._board_scroll.viewport()
        origin = self.board_content_origin()
        return center_from_scroll(
            (
                float(self._board_scroll.horizontalScrollBar().value()) - origin[0],
                float(self._board_scroll.verticalScrollBar().value()) - origin[1],
            ),
            (float(viewport.width()), float(viewport.height())),
            self._viewport.zoom(),
        )

    def place_canvas_for_scroll(
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
        origin_x, origin_y = self.board_content_origin()
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

    def sync_board_stack_geometry(self, canvas: QWidget) -> None:
        """Keep the scroll host sized to the current logical canvas."""
        scroll = (
            float(self._board_scroll.horizontalScrollBar().value()),
            float(self._board_scroll.verticalScrollBar().value()),
        )
        self.place_canvas_for_scroll(canvas, scroll)

    def on_workspace_gesture_changed(self, active: bool, global_pos=None) -> None:
        """Compat lifetime+optional first pointer. Page does not replan here."""
        if not bool(active):
            self.on_workspace_gesture_active_changed(False, self._edge_gesture_token)
            return
        if global_pos is not None:
            self._edge_pan_global_pos = QPoint(global_pos)
        self.on_workspace_gesture_active_changed(True, self._edge_gesture_token)
        if global_pos is not None:
            self.on_workspace_pointer_changed(self._edge_gesture_token, global_pos)

    def on_workspace_gesture_active_changed(self, active: bool, gesture_id: int) -> None:
        wanted = bool(active)
        self._edge_gesture_token = int(gesture_id or 0)
        if not wanted:
            self.stop_edge_pan()
            self._sync_minimap_placement()
            return
        if not self._edge_pan_active:
            self._on_edge_pan_started()
        self._edge_pan_active = True
        self._refresh_extent()
        self._sync_feedback_surface()
        self._sync_edge_timer_for_pointer()
        self._sync_minimap_placement()

    def on_workspace_pointer_changed(self, gesture_id: int, global_pos=None) -> None:
        if not self._edge_pan_active:
            return
        if int(gesture_id or 0) not in (0, int(self._edge_gesture_token)):
            return
        if global_pos is not None:
            self._edge_pan_global_pos = QPoint(global_pos)
        self._sync_edge_timer_for_pointer()

    def stop_edge_pan(self, *_args) -> None:
        self._edge_pan_active = False
        if self._edge_pan_timer.isActive():
            self._edge_pan_timer.stop()
        self._edge_pan_global_pos = None
        self._on_edge_pan_stopped()

    def edge_pan_tick_for_global(self, global_pos) -> None:
        if global_pos is None or self._edge_pan_reentrant:
            return
        self._edge_pan_reentrant = True
        try:
            self._edge_pan_tick_for_global_unlocked(global_pos)
        finally:
            self._edge_pan_reentrant = False

    def _stop_anim_and_smooth(self) -> None:
        self._zoom_anim.stop()
        if self._smooth_timer.isActive():
            self._smooth_timer.stop()

    def _dismiss_transients_for_zoom(self) -> None:
        dismiss = self._dismiss_author_transients
        if callable(dismiss):
            dismiss()

    def _park_zoom(self, zoom: float) -> None:
        """Zoom and leave the board in the chrome-safe fit rect."""
        self._cancel_board_gestures()
        self._filled_card = None
        self._dismiss_transients_for_zoom()
        self._apply_preview_quality(QUALITY_FAST)
        after = clamp_zoom(zoom)
        self._broadcast_zoom(after)
        origin = self._fit_origin()
        self._board_stack.move(int(round(origin[0])), int(round(origin[1])))
        applied = self.place_canvas_for_scroll(self._active_canvas(), (0.0, 0.0))
        self._board_scroll.horizontalScrollBar().setValue(int(round(applied[0])))
        self._board_scroll.verticalScrollBar().setValue(int(round(applied[1])))
        self._set_zoom_percent(zoom_percent(after))
        self._apply_lod_chrome()
        self._restart_smooth_timer()
        self.persist()

    def _broadcast_zoom(self, zoom: float, *, viewport: bool = True) -> None:
        """Keep the viewport model and both Board render surfaces in sync.

        Do not refresh workspace extent here. The caller still has a pending
        scroll transaction computed against the current origin; rebasing
        first is what made cards flicker while zooming.
        """
        if viewport:
            self._viewport.set_zoom(zoom)
        self._grid.set_zoom(zoom)
        self._free_grid.set_zoom(zoom)

    def _settle_workspace_after_zoom(self) -> None:
        """Grow halo after the gesture has stopped, keeping the view still."""
        self._refresh_extent(preserve_visible=True)

    def _animate_viewport(self, zoom: float, center: tuple[float, float]) -> None:
        self._anim_start_zoom = self._viewport.zoom()
        self._anim_end_zoom = clamp_zoom(zoom)
        self._anim_start_center = self.current_center()
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
        viewport_origin: tuple[float, float] | None = None,
    ) -> None:
        self._cancel_board_gestures()
        self._dismiss_transients_for_zoom()
        self._apply_preview_quality(QUALITY_FAST)
        after = clamp_zoom(zoom)
        self._broadcast_zoom(after)
        self._viewport.set_center(center)
        # zoom_fit passes the fill size; its origin must match that rect.
        # Parking ``fit`` sits below the top islands. Using it here would
        # leave the visual centre low after raising fill.y, and would also
        # rewrite session-camera scrollbars by that island gap on restore.
        if viewport_origin is not None:
            origin = (float(viewport_origin[0]), float(viewport_origin[1]))
        elif viewport_size is not None:
            fill = self._content_fill_rect()
            origin = (float(fill.x), float(fill.y))
        else:
            origin = self.board_content_origin()
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
        applied = self.place_canvas_for_scroll(self._active_canvas(), desired)
        self._board_scroll.horizontalScrollBar().setValue(int(round(applied[0])))
        self._board_scroll.verticalScrollBar().setValue(int(round(applied[1])))
        self._set_zoom_percent(zoom_percent(after))
        self._apply_lod_chrome()
        self._restart_smooth_timer()
        self.persist()

    def _zoom_at(self, zoom: float, cursor_in_viewport) -> None:
        self._cancel_board_gestures()
        self._filled_card = None
        self._dismiss_transients_for_zoom()
        self._apply_preview_quality(QUALITY_FAST)
        after = clamp_zoom(zoom)
        cursor = (float(cursor_in_viewport[0]), float(cursor_in_viewport[1]))
        scroll = (
            float(self._board_scroll.horizontalScrollBar().value()),
            float(self._board_scroll.verticalScrollBar().value()),
        )
        origin = self.board_content_origin()
        canvas = self._active_canvas()
        # Anchor through the canvas's own coordinate system instead of
        # extrapolating ``logical * zoom``.  The free-grid pixel map rounds
        # every metric before multiplying by a cell index, so a linear
        # prediction carries an error proportional to that index -- and the
        # signed elastic origin drives the index past 40, which is what made
        # each wheel notch shove the board tens of pixels sideways.
        anchor = canvas.zoom_anchor_at(canvas_point_under(cursor, scroll, origin))
        self._broadcast_zoom(after)
        new_scroll = scroll_for_anchor(
            canvas.point_for_zoom_anchor(anchor), cursor, origin
        )
        applied = self.place_canvas_for_scroll(canvas, new_scroll)
        self._board_scroll.horizontalScrollBar().setValue(int(round(applied[0])))
        self._board_scroll.verticalScrollBar().setValue(int(round(applied[1])))
        self._set_zoom_percent(zoom_percent(after))
        self._apply_lod_chrome()
        self._restart_smooth_timer()
        self.persist()

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

    def _on_smooth_preview_timeout(self) -> None:
        self._apply_preview_quality(QUALITY_SMOOTH)
        self._settle_workspace_after_zoom()

    def _arm_context_menu_suppress(self) -> None:
        self._ignore_next_context_menu = True
        QTimer.singleShot(0, self._expire_context_menu_suppress)

    def _expire_context_menu_suppress(self) -> None:
        self._ignore_next_context_menu = False

    def _after_end_board_pan(self) -> None:
        if self._viewport.space_down():
            self._board_scroll.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self._board_scroll.viewport().unsetCursor()
            self._resume_draw()
            self._sync_tool_cursor()
        self.persist()
        self._restart_smooth_timer()

    def _on_edge_pan_tick(self) -> None:
        if not self._edge_pan_active or not self._is_free_grid():
            self.stop_edge_pan()
            return
        self.edge_pan_tick_for_global(self._edge_pan_global_pos)

    def _pointer_edge_velocity(self, global_pos) -> tuple[float, float]:
        if global_pos is None:
            return (0.0, 0.0)
        viewport = self._board_scroll.viewport()
        local = viewport.mapFromGlobal(global_pos)
        return edge_pan_velocity(
            (float(local.x()), float(local.y())),
            (float(viewport.width()), float(viewport.height())),
        )

    def _sync_edge_timer_for_pointer(self) -> None:
        pos = self._edge_pan_global_pos
        if pos is None or not self._edge_pan_active:
            if self._edge_pan_timer.isActive():
                self._edge_pan_timer.stop()
            return
        velocity = self._pointer_edge_velocity(pos)
        self._sync_workspace_edge_hint(pos)
        if velocity == (0.0, 0.0):
            if self._edge_pan_timer.isActive():
                self._edge_pan_timer.stop()
            return
        if not self._edge_pan_timer.isActive():
            self._edge_pan_timer.start()

    def _transform_token(self) -> tuple:
        return (
            int(self._board_scroll.horizontalScrollBar().value()),
            int(self._board_scroll.verticalScrollBar().value()),
            self._extent_key(),
            float(self._viewport.zoom()),
        )

    def _edge_pan_tick_for_global_unlocked(self, global_pos) -> None:
        velocity = self._pointer_edge_velocity(global_pos)
        if velocity == (0.0, 0.0):
            if self._edge_pan_timer.isActive():
                self._edge_pan_timer.stop()
            self._sync_workspace_edge_hint(global_pos)
            self._sync_feedback_surface()
            return
        old_token = self._transform_token()
        changed = self._refresh_extent()
        if changed:
            self.sync_board_stack_geometry(self._free_grid)
        horizontal = self._board_scroll.horizontalScrollBar()
        vertical = self._board_scroll.verticalScrollBar()
        horizontal.setValue(int(round(horizontal.value() + velocity[0])))
        vertical.setValue(int(round(vertical.value() + velocity[1])))
        self._restart_smooth_timer()
        if self._transform_token() == old_token:
            self._sync_workspace_edge_hint(global_pos)
            self._sync_feedback_surface()
            return
        self._reproject_after_viewport(global_pos)
        self._sync_workspace_edge_hint(global_pos)
        self._sync_feedback_surface()
