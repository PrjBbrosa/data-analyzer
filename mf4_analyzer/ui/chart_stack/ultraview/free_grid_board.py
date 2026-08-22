"""UltraView free-grid board host.

Visual projection of persisted free-grid state. Live move/resize feedback
(latest pointer, 0 ms coalescer, candidate fingerprint, present/clear) lives
on ``FreeGridFeedbackController``. This widget remains the QWidget host for
cards, ``FreeGridGesture``, planner commits, dimming, and ghost sources.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Callable, Mapping, Sequence

from PyQt5 import sip
from PyQt5.QtCore import QMimeData, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QCursor, QImage, QKeyEvent, QMouseEvent, QPixmap
from PyQt5.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QSizePolicy,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import (
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
    UltraViewRef,
    parse_ref_payload,
    resolve_free_grid_insert_rect,
    safety_grid_bounds,
)

from .laser_cursor import (
    LASER_CURSOR_DPR_CHANGE_EVENTS,
    clear_laser_cursor_cache,
    laser_pointer_cursor,
)
from .feedback import (
    AUTHOR_LOCKED,
    FEEDBACK_DISPLACED_OFFSCREEN,
    FEEDBACK_OUT_OF_GRID,
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
from .free_grid_feedback import FreeGridFeedbackController
from .viewport_feedback import ViewportFeedbackSurface
from .viewport import (
    ZOOM_DEFAULT,
    scale_grid_metrics,
)
from .widgets_common import (
    _accept_ultraview_drag,
    _drop_on_unplaced_tray,
    _effective_device_pixel_ratio,
    _page_of,
    _union_pixel_rect,
    extract_ref_strings,
)
from .card_widgets import (
    CardViewModel,
    FreeGridCard,
    ReplaceHoverController,
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
        self._feedback = FreeGridFeedbackController(self, self._overlay, self)
        self._ghost_buffers: dict[UltraViewRef, QPixmap] = {}
        self._replace = ReplaceHoverController(self)
        self._replace.armed.connect(self._on_replace_armed)
        self._replace.cleared.connect(self._on_replace_cleared)
        self._pending_shift_toggle: UltraViewRef | None = None
        self._layout_revision = 0
        self._gesture_dimmed = False
        # This is replaced from ``free_grid_default_span`` when a Board is
        # installed.  Keep the standalone default in schema-5 micro-grid
        # units as well, so test/harness boards never create undersized cards.
        self._default_insert_span = (8, 6)
        self._insert_preview_rect: GridRect | None = None
        self._insert_span_resolver: Callable[[str, str], tuple[int, int] | None] | None = None
        self._insert_drag_ref: tuple[str, str] | None = None
        # Movers currently showing a shell-only placeholder (no drag opacity).
        self._dimmed_refs: set[UltraViewRef] = set()
        self.destroyed.connect(self._on_workspace_destroyed)

    def set_viewport_size(self, size: QSize) -> None:
        """Record the scroll viewport. Metrics use ``screen_grid_metrics``.

        Column width is the 1600-wide export column, not the window width, so
        card aspect stays put when the user resizes or toggles chrome.
        """
        if size == self._viewport_size:
            return
        self._feedback.stop_coalesce(drop=True)
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

    def current_placements(self) -> tuple[FreeGridPlacement, ...]:
        return tuple(self._placements.values())

    def current_zoom(self) -> float:
        return float(self._zoom)

    def workspace_origin_offset(self) -> tuple[int, int]:
        return self._workspace_origin_offset()

    def workspace_pixel_rect(
        self, logical_rect: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        return self._workspace_pixel_rect(logical_rect)

    def is_workspace_gesture_active(self) -> bool:
        return bool(self._workspace_gesture_active)

    def emit_workspace_pointer(self, global_pos: QPoint) -> None:
        self.workspace_pointer_changed.emit(
            int(self._gesture.gesture_id() or 0),
            QPoint(global_pos),
        )

    def emit_workspace_gesture(
        self, active: bool, global_pos: QPoint | None = None
    ) -> None:
        self._emit_workspace_gesture(active, global_pos)

    def note_live_feedback_started(self) -> None:
        self.drag_started.emit("layout")
        self._gesture_dimmed = True

    def is_live_feedback_dimmed(self) -> bool:
        return bool(self._gesture_dimmed)

    def grab_mouse_for_feedback(self) -> None:
        if QWidget.mouseGrabber() is None:
            self.grabMouse()

    def apply_safety_cursor(self, safety: bool) -> None:
        if safety:
            self.setCursor(Qt.ForbiddenCursor)
        elif self.cursor().shape() == Qt.ForbiddenCursor:
            self.unsetCursor()

    def sync_editor_exclusion(self) -> None:
        self._sync_editor_exclusion()

    def session_hits_safety(self, session) -> bool:
        return self._session_hits_safety(session)

    def safety_bounds_pixel_rect(self) -> QRect:
        return self._safety_bounds_pixel_rect()

    def safety_sides_for(self, rect: GridRect) -> tuple[str, ...]:
        return self._safety_sides_for(rect)

    def host_is_deleted(self) -> bool:
        try:
            return bool(sip.isdeleted(self))
        except RuntimeError:
            return True

    def ghost_source_for(self, ref: UltraViewRef) -> QPixmap | QImage | None:
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

    def ghost_overlay(self) -> ViewportFeedbackSurface:
        return self._overlay

    def bind_feedback_surface(self, viewport: QWidget) -> None:
        """Reparent the FreeGrid feedback surface onto the scroll viewport."""
        self._feedback.bind_surface(self, viewport)

    def ingest_pointer_sample(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> None:
        self._feedback.ingest_pointer_sample(
            board_pos, keep_aspect=keep_aspect, global_pos=global_pos
        )

    def feedback_pipeline_counts(self) -> dict[str, int]:
        overlay = self._overlay
        return {
            "planner": int(self._feedback.planner_calls),
            "presents": int(getattr(overlay, "present_count", self._feedback.frame_presents)),
            "paints": int(getattr(overlay, "paint_count", 0)),
            "generation": int(getattr(overlay, "generation", self._feedback.generation)),
            "gesture_id": int(getattr(overlay, "gesture_id", 0)),
            "layout_revision": int(self._layout_revision),
        }

    @property
    def _pointer_coalesce_timer(self):
        return self._feedback.pointer_coalesce_timer

    @property
    def _latest_pointer_sample(self):
        return self._feedback.latest_pointer_sample

    @_latest_pointer_sample.setter
    def _latest_pointer_sample(self, value) -> None:
        self._feedback.latest_pointer_sample = value

    @property
    def _last_pointer_sample(self):
        return self._feedback.last_pointer_sample

    @_last_pointer_sample.setter
    def _last_pointer_sample(self, value) -> None:
        self._feedback.last_pointer_sample = value

    @property
    def _gesture_presenting(self) -> bool:
        return self._feedback.gesture_presenting

    @_gesture_presenting.setter
    def _gesture_presenting(self, value: bool) -> None:
        self._feedback.gesture_presenting = bool(value)

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
        self._feedback.invalidate_candidate_fingerprint()
        self._feedback.reproject_live_preview()

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
        self._feedback.stop_coalesce(drop=True)
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
        self._feedback.stop_coalesce(drop=True)
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
        self._feedback.reset_pointer_state()
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
        self._feedback.stop_coalesce(drop=True)
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
            self._feedback.stop_coalesce(drop=True)
        super().resizeEvent(event)
        if armed:
            if self._author_layer.geometry() != self.rect():
                self._author_layer.setGeometry(self.rect())
            self._raise_overlay()
            self._feedback.invalidate_candidate_fingerprint()
            self._feedback.reproject_live_preview()
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

    def _ingest_pointer_sample(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> None:
        self.ingest_pointer_sample(
            board_pos, keep_aspect=keep_aspect, global_pos=global_pos
        )

    def _flush_pointer_sample(self) -> None:
        self._feedback.flush_pointer_sample()

    def _reproject_live_preview(self) -> None:
        self._feedback.reproject_live_preview()

    def _ghost_source_for(self, ref: UltraViewRef) -> QPixmap | QImage | None:
        return self.ghost_source_for(ref)

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
        self._feedback.stop_coalesce(drop=True)
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
            self._feedback.clear_displayed_frame(gesture_id or None)
            if self.cursor().shape() == Qt.ForbiddenCursor:
                self.unsetCursor()
            self._sync_selection_handles()
            self._feedback.reset_pointer_state()
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
