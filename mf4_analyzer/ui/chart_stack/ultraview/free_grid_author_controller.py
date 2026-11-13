"""Own FreeGrid author hit/geometry/editor widget bridge.

``AuthorPaintLayer``, ``BoardTextEditor``, and ``StickyNoteWidget`` remain
QWidget children created by ``FreeGridBoard``. This controller must not parent
a second editor or paint layer, and must not become a second
``BoardInteractionController``: tool, draft, selection, clipboard, format
defaults, and ``editor_active`` stay on the Board-owned session.
"""
from __future__ import annotations

import math
from typing import Protocol, Sequence

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QMouseEvent

from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    ConnectorObject,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
)

from .author_geometry import (
    CORNER_HANDLES,
    board_box_to_pixels,
    board_point_to_pixels,
    connector_handle_points,
    connector_pick_tolerance_px,
    connector_route_points,
    hit_box_handle,
    hit_connector_handle,
    hit_polyline_px,
    pixel_rects_intersect,
    pixels_to_board_point,
    resize_box_candidate,
    snap_board_point,
    stroke_pick_tolerance_px,
)
from .author_layer import AuthorLayerModel, AuthorPaintLayer
from .author_selection import translate_object
from .author_style import DEFAULT_STICKY_PALETTE, DEFAULT_THEME
from .author_tools import (
    HIT_AUTHOR,
    HIT_RESIZE_HANDLE,
    SHAPE_MIN_HEIGHT,
    SHAPE_MIN_WIDTH,
    STICKY_MIN_HEIGHT,
    STICKY_MIN_WIDTH,
    TEXT_MIN_HEIGHT,
    TEXT_MIN_WIDTH,
    TOOL_STICKY,
    AuthorCreateIntent,
    AuthorKey,
    AuthorNudgeIntent,
    AuthorUpdateIntent,
    BoardInteractionController,
    HitTarget,
    ShapeUpdateIntent,
    TextUpdateIntent,
    clamp_author_box,
    new_author_object_id,
    sticky_box_from_points,
)
from .author_widgets import BoardTextEditor, StickyNoteWidget
from .card_widgets import FreeGridCard
from .elastic_workspace import author_content_bounds
from .feedback import AUTHOR_LOCKED, AUTHOR_SNAPPED_ENDPOINT, text_for_key
from .free_grid import GridMetrics
from .viewport_feedback import ViewportFeedbackSurface


def pixel_box(
    mapped: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    x, y, width, height = mapped
    return (
        int(round(x)),
        int(round(y)),
        max(1, int(round(width))),
        max(1, int(round(height))),
    )


class FreeGridAuthorHost(Protocol):
    """Explicit Board ports. The controller never reads host private fields."""

    def interaction(self) -> BoardInteractionController: ...

    def metrics(self) -> GridMetrics: ...

    def workspace_origin_offset(self) -> tuple[int, int]: ...

    def current_zoom(self) -> float: ...

    def creation_allowed(self) -> bool: ...

    def classify_press(
        self,
        pos: QPoint,
        *,
        modifiers=Qt.NoModifier,
        viewport_pan: bool = False,
        card: FreeGridCard | None = None,
        already_selected: bool = False,
    ) -> HitTarget: ...

    def map_card_to_board(
        self, card: FreeGridCard, local: QPoint
    ) -> tuple[int, int]: ...

    def apply_selection_flags(self) -> None: ...

    def sync_selection_handles(self) -> None: ...

    def sync_tool_cursor(self) -> None: ...

    def raise_overlay(self) -> None: ...

    def ghost_overlay(self) -> ViewportFeedbackSurface: ...

    def emit_workspace_gesture(
        self, active: bool, global_pos: QPoint | None = None
    ) -> None: ...

    def grab_mouse_for_feedback(self) -> None: ...

    def release_mouse_if_grabbed(self) -> None: ...

    def emit_author_feedback(self, text: str) -> None: ...

    def emit_author_create(self, intent: object) -> None: ...

    def emit_author_update(self, intent: object) -> None: ...

    def emit_author_edit(self, object_id: str) -> None: ...

    def begin_connector_geometry(
        self,
        handle: str,
        object_id: str,
        event: QMouseEvent,
        pos: QPoint,
    ) -> None: ...


class FreeGridAuthorController:
    """One owner for author hit, live box geometry, and editor widget bridge."""

    def __init__(
        self,
        host: FreeGridAuthorHost,
        paint_layer: AuthorPaintLayer,
        text_editor: BoardTextEditor,
        sticky_note: StickyNoteWidget,
    ) -> None:
        self._host = host
        self._paint_layer = paint_layer
        self._text_editor = text_editor
        self._sticky_note = sticky_note
        self._author_objects: tuple[object, ...] = ()
        self._author_theme = DEFAULT_THEME
        self._geometry_session: dict[str, object] | None = None
        self._sticky_note.text_committed.connect(self._on_sticky_text_committed)
        self._sticky_note.edit_cancelled.connect(self._on_sticky_edit_cancelled)
        self._host.interaction().set_author_marquee_resolver(self.author_keys_intersecting)

    def projected_objects(self) -> tuple[object, ...]:
        return self._author_objects

    def set_projected_objects(self, value: Sequence[object]) -> None:
        self._author_objects = tuple(value)

    def projected_theme(self) -> str:
        return self._author_theme

    def set_projected_theme(self, value: str) -> None:
        self._author_theme = str(value or DEFAULT_THEME)

    @property
    def geometry_session(self) -> dict[str, object] | None:
        return self._geometry_session

    @geometry_session.setter
    def geometry_session(self, value: dict[str, object] | None) -> None:
        self._geometry_session = value

    def set_author_objects(
        self,
        objects: Sequence[object],
        *,
        theme: str = DEFAULT_THEME,
    ) -> None:
        """Project persisted author objects without taking mutation ownership."""
        self._author_objects = tuple(objects)
        self._author_theme = str(theme or DEFAULT_THEME)
        self._host.interaction().restrict_authors(
            {
                str(getattr(item, "object_id", ""))
                for item in self._author_objects
                if getattr(item, "object_id", None)
            }
        )
        self.sync_projection()

    def clear_author_selection(self) -> bool:
        """Clear author keys through the shared session owner."""
        if not self._host.interaction().clear_author_keys():
            return False
        self.sync_projection()
        return True

    def author_selection_ids(self) -> frozenset[str]:
        return self._host.interaction().author_selection_ids()

    def hide_author_editor(self) -> bool:
        """Hide the IME editor without committing. Safe when nothing is editing."""
        hidden = False
        if self._sticky_note.is_editing():
            self._sticky_note.hide_edit()
            hidden = True
        editor = self._text_editor
        if editor.is_editing():
            editor.cancel()
            hidden = True
        self._host.interaction().set_editor_active(False)
        return hidden

    def is_editor_open(self) -> bool:
        return bool(self._sticky_note.is_editing() or self._text_editor.is_editing())

    def is_draft_active(self) -> bool:
        return self._host.interaction().draft() is not None

    def has_geometry_session(self) -> bool:
        return self._geometry_session is not None

    def cancel_geometry_session(self) -> bool:
        if self._geometry_session is None:
            return False
        self._geometry_session = None
        self._paint_layer.set_geometry_overrides(())
        unlock = getattr(self._host, "unlock_resize_cursor", None)
        if callable(unlock):
            unlock()
        return True

    def cancel_draft_preview(self) -> bool:
        if self._host.interaction().draft() is None:
            return False
        self._host.interaction().cancel_draft()
        self._host.ghost_overlay().set_marquee(None)
        self.hide_author_editor()
        return True

    def reset_transient(self) -> None:
        """Board switch/clear: hide editors and drop the geometry session."""
        self.hide_author_editor()
        self._geometry_session = None
        self._paint_layer.set_geometry_overrides(())

    def projected_selection_rects(self) -> list[tuple[int, int, int, int]]:
        """Pixel rects of selected author boxes. Overlay present stays on Board."""
        rects: list[tuple[int, int, int, int]] = []
        origin = self._host.workspace_origin_offset()
        selected = self._host.interaction().author_selection_ids()
        metrics = self._host.metrics()
        for item in self._author_objects:
            object_id = str(getattr(item, "object_id", "") or "")
            if object_id not in selected:
                continue
            box = getattr(item, "box", None)
            if box is None:
                continue
            mapped = board_box_to_pixels(
                (box.x, box.y, box.width, box.height),
                metrics,
                origin_offset=origin,
            )
            if mapped is not None:
                rects.append(pixel_box(mapped))
        return rects

    def pixel_rects(
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
            origin_offset=self._host.workspace_origin_offset(),
        )
        return () if mapped is None else (mapped,)

    def sync_projection(self) -> None:
        boxes = []
        selected = self._host.interaction().author_selection_ids()
        overrides = {
            str(object_id): geometry
            for object_id, geometry in self._live_geometry_overrides()
        }
        if selected:
            for item in self._author_objects:
                object_id = str(getattr(item, "object_id", ""))
                if object_id not in selected:
                    continue
                geometry = overrides.get(object_id)
                if geometry is not None and geometry[0] == "box":
                    boxes.append(geometry[1])
                    continue
                box = getattr(item, "box", None)
                if box is not None and geometry is None:
                    boxes.append((box.x, box.y, box.width, box.height))
        origin = self._host.workspace_origin_offset()
        metrics = self._host.metrics()
        editor_object_id = (
            self._text_editor.object_id() if self._text_editor.is_editing() else ""
        )
        self._paint_layer.set_model(
            AuthorLayerModel(
                objects=self._author_objects,
                metrics=metrics,
                origin_offset=origin,
                theme=self._author_theme,
                hidden_text_object_ids=frozenset(
                    (editor_object_id,) if editor_object_id else ()
                ),
                selection_boxes=tuple(boxes),
                geometry_overrides=tuple(overrides.items()),
                text_handle_boxes=self._text_handle_boxes(overrides),
            )
        )
        self._paint_layer.set_view_geometry(
            metrics,
            origin_offset=origin,
            zoom=self._host.current_zoom(),
        )
        if self._text_editor.is_editing():
            self._text_editor.update_board_geometry(
                metrics,
                origin_offset=origin,
            )
        if self._sticky_note.is_editing():
            self._sticky_note.update_board_geometry(
                metrics,
                origin_offset=origin,
            )

    def sticky_create_armed(self) -> bool:
        interaction = self._host.interaction()
        return (
            self._host.creation_allowed()
            and interaction.active_tool() == TOOL_STICKY
            and not interaction.is_editor_active()
        )

    def pixel_to_board_point(self, pos: QPoint) -> tuple[float, float] | None:
        return pixels_to_board_point(
            (float(pos.x()), float(pos.y())),
            self._host.metrics(),
            origin_offset=self._host.workspace_origin_offset(),
        )

    def author_item(self, object_id: str):
        for item in self._author_objects:
            if str(getattr(item, "object_id", "") or "") == object_id:
                return item
        return None

    def draft_pixel_rect(self) -> tuple[int, int, int, int] | None:
        draft = self._host.interaction().draft()
        if draft is None or draft.origin is None:
            return None
        box = sticky_box_from_points(draft.origin, draft.current)
        mapped = board_box_to_pixels(
            box,
            self._host.metrics(),
            origin_offset=self._host.workspace_origin_offset(),
        )
        if mapped is None:
            return None
        return pixel_box(mapped)

    def route_card_press(self, card: FreeGridCard, event: QMouseEvent) -> bool:
        """I3: author objects above a card consume the press before card drag."""
        mapped = QPoint(*self._host.map_card_to_board(card, event.pos()))
        self.close_sticky_editor_if_outside(mapped)
        hit = self._host.classify_press(mapped, modifiers=event.modifiers())
        if hit.kind == HIT_RESIZE_HANDLE and isinstance(hit.item, AuthorKey):
            self.begin_selected_author_handle(hit, event, mapped)
            return True
        if hit.kind != HIT_AUTHOR:
            return False
        self.handle_author_press(hit, event, mapped)
        return True

    def close_sticky_editor_if_outside(self, pos: QPoint) -> None:
        if not self._sticky_note.is_editing():
            return
        if self._sticky_note.geometry().contains(pos):
            return
        self.commit_or_cancel_sticky_editor()

    def commit_or_cancel_sticky_editor(self) -> None:
        if not self._sticky_note.is_editing():
            return
        if not str(self._sticky_note.current_text() or "").strip():
            self._sticky_note.cancel()
            return
        self._sticky_note.commit()

    def handle_author_press(
        self, hit: HitTarget, event: QMouseEvent, pos: QPoint
    ) -> None:
        if not isinstance(hit.item, AuthorKey):
            return
        item = self.author_item(hit.item.object_id)
        interaction = self._host.interaction()
        additive = bool(event.modifiers() & Qt.ShiftModifier)
        if additive:
            interaction.toggle(hit.item)
            self._host.apply_selection_flags()
            return
        if item is not None and bool(getattr(item, "locked", False)):
            interaction.select_only(hit.item)
            self._host.apply_selection_flags()
            self._host.emit_author_feedback(text_for_key(AUTHOR_LOCKED))
            return
        if _connector_has_snapped_end(item):
            if hit.item not in interaction.selection():
                interaction.select_only(hit.item)
            self._host.apply_selection_flags()
            self._host.emit_author_feedback(text_for_key(AUTHOR_SNAPPED_ENDPOINT))
            return
        if item is None:
            interaction.select_only(hit.item)
            self._host.apply_selection_flags()
            return
        if hit.item in interaction.selection():
            members = self._movable_selected_objects()
        else:
            interaction.select_only(hit.item)
            members = (item,)
        self._host.apply_selection_flags()
        self._begin_group_move(members, pos)

    def begin_selected_author_handle(
        self, hit: HitTarget, event: QMouseEvent, pos: QPoint
    ) -> None:
        if not isinstance(hit.item, AuthorKey):
            return
        item = self.author_item(hit.item.object_id)
        if item is None or bool(getattr(item, "locked", False)):
            if item is not None:
                self._host.emit_author_feedback(text_for_key(AUTHOR_LOCKED))
            return
        handle = str(hit.handle or "")
        if isinstance(item, ConnectorObject):
            self._host.begin_connector_geometry(handle, item.object_id, event, pos)
            return
        if isinstance(item, (StickyObject, TextObject, ShapeObject)):
            self.begin_box_geometry(item, pos, handle=handle)

    def begin_box_geometry(self, item, pos: QPoint, *, handle: str | None) -> None:
        box = getattr(item, "box", None)
        if box is None:
            return
        board_point = self.pixel_to_board_point(pos)
        min_w, min_h = self.author_min_size(item)
        self._geometry_session = {
            "object_id": item.object_id,
            "kind": "resize" if handle else "move",
            "handle": handle,
            "origin": board_point,
            "box": (box.x, box.y, box.width, box.height),
            "min_width": min_w,
            "min_height": min_h,
            "square_snap": isinstance(item, StickyObject) and str(handle or "") in CORNER_HANDLES,
            "square_snapped": False,
            "preview_box": (box.x, box.y, box.width, box.height),
        }
        self._host.grab_mouse_for_feedback()
        lock = getattr(self._host, "lock_resize_cursor", None)
        if callable(lock) and handle:
            lock(str(handle))

    def author_min_size(self, item) -> tuple[float, float]:
        if isinstance(item, TextObject):
            return TEXT_MIN_WIDTH, TEXT_MIN_HEIGHT
        if isinstance(item, ShapeObject):
            return SHAPE_MIN_WIDTH, SHAPE_MIN_HEIGHT
        return STICKY_MIN_WIDTH, STICKY_MIN_HEIGHT

    def begin_sticky_draft(self, pos: QPoint) -> None:
        origin = self.pixel_to_board_point(pos)
        if origin is None:
            return
        self._host.interaction().begin_draft(
            TOOL_STICKY, origin=origin, object_id=new_author_object_id()
        )
        self._host.ghost_overlay().set_marquee(self.draft_pixel_rect())
        self._host.emit_workspace_gesture(True)

    def update_sticky_draft(self, pos: QPoint) -> None:
        current = self.pixel_to_board_point(pos)
        self._host.interaction().update_draft(current)
        rect = self.draft_pixel_rect()
        if rect is not None:
            self._host.ghost_overlay().set_marquee(rect)

    def finish_sticky_draft(self) -> None:
        draft = self._host.interaction().draft()
        self._host.release_mouse_if_grabbed()
        self._host.ghost_overlay().set_marquee(None)
        self._host.emit_workspace_gesture(False)
        if draft is None or draft.origin is None or draft.object_id is None:
            self._host.interaction().cancel_draft()
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
            self._host.metrics(),
            origin_offset=self._host.workspace_origin_offset(),
            theme=self._author_theme,
        )
        self._host.interaction().set_editor_active(True)
        self._sticky_note.begin_edit()
        self._host.raise_overlay()

    def begin_sticky_edit(self, item) -> None:
        if not isinstance(item, StickyObject):
            return
        if bool(getattr(item, "locked", False)):
            self._host.emit_author_feedback(text_for_key(AUTHOR_LOCKED))
            return
        self._sticky_note.apply_object(
            item,
            self._host.metrics(),
            origin_offset=self._host.workspace_origin_offset(),
            theme=self._author_theme,
        )
        self._host.interaction().set_editor_active(True)
        self._sticky_note.begin_edit()
        self._host.raise_overlay()

    def _on_sticky_text_committed(self, object_id: str, text: str) -> None:
        draft = self._host.interaction().draft()
        pending = draft is not None and draft.object_id == object_id
        self._sticky_note.hide_edit()
        self._host.interaction().set_editor_active(False)
        cleaned = str(text or "")
        if pending:
            if not cleaned.strip():
                self._host.interaction().cancel_draft()
                self._host.sync_tool_cursor()
                return
            box = sticky_box_from_points(draft.origin or (0.0, 0.0), draft.current)
            self._host.interaction().commit_draft()
            self._host.emit_author_create(
                AuthorCreateIntent(
                    TOOL_STICKY,
                    object_id,
                    box,
                    cleaned,
                    str(draft.palette or DEFAULT_STICKY_PALETTE),
                )
            )
            self._host.sync_tool_cursor()
            return
        self._host.emit_author_update(AuthorUpdateIntent(object_id, text=cleaned))

    def _on_sticky_edit_cancelled(self, object_id: str) -> None:
        draft = self._host.interaction().draft()
        self._host.interaction().set_editor_active(False)
        if draft is not None and draft.object_id == object_id:
            self._host.interaction().cancel_draft()
        self._host.sync_tool_cursor()

    def update_author_geometry(self, pos: QPoint, *, modifiers: int = 0) -> None:
        session = self._geometry_session
        if not session or session.get("origin") is None:
            return
        if session.get("kind") == "group-move":
            self._update_group_move(session, pos)
            return
        box = self._candidate_from_session(session, pos, modifiers=modifiers)
        if box is None:
            return
        session["preview_box"] = box
        mapped = board_box_to_pixels(
            box,
            self._host.metrics(),
            origin_offset=self._host.workspace_origin_offset(),
        )
        if mapped is not None:
            self._host.ghost_overlay().set_selection_rects(
                (pixel_box(mapped),), handles=True
            )

    def _pitch(self) -> tuple[float, float]:
        try:
            pitch = self._host.metrics().exact_pitch()
            return float(pitch[0]), float(pitch[1])
        except (AttributeError, TypeError, ValueError):
            return (1.0, 1.0)

    def _bypass_square_snap(self, modifiers: int) -> bool:
        return bool(int(modifiers) & int(Qt.ControlModifier))

    def _candidate_from_session(
        self,
        session: dict[str, object],
        pos: QPoint,
        *,
        modifiers: int = 0,
    ) -> tuple[float, float, float, float] | None:
        current = self.pixel_to_board_point(pos)
        if current is None:
            return None
        ox, oy = session["origin"]  # type: ignore[misc]
        x, y, width, height = session["box"]  # type: ignore[misc]
        dx = current[0] - ox
        dy = current[1] - oy
        handle = session.get("handle")
        min_w = float(session.get("min_width") or STICKY_MIN_WIDTH)
        min_h = float(session.get("min_height") or STICKY_MIN_HEIGHT)
        if session.get("kind") == "move" or not handle:
            return clamp_author_box(
                x + dx, y + dy, width, height, min_width=min_w, min_height=min_h
            )
        pitch_x, pitch_y = self._pitch()
        candidate, snapped = resize_box_candidate(
            (x, y, width, height),
            str(handle),
            dx,
            dy,
            pitch_x=pitch_x,
            pitch_y=pitch_y,
            square_snap=bool(session.get("square_snap")),
            snapped=bool(session.get("square_snapped")),
            bypass=self._bypass_square_snap(modifiers),
        )
        session["square_snapped"] = snapped
        return clamp_author_box(
            candidate[0],
            candidate[1],
            candidate[2],
            candidate[3],
            min_width=min_w,
            min_height=min_h,
        )

    def resize_author_box(
        self,
        box: tuple[float, float, float, float],
        handle: str,
        dx: float,
        dy: float,
        *,
        min_width: float = STICKY_MIN_WIDTH,
        min_height: float = STICKY_MIN_HEIGHT,
        square_snap: bool = False,
        snapped: bool = False,
        bypass: bool = False,
        pitch_x: float | None = None,
        pitch_y: float | None = None,
    ) -> tuple[float, float, float, float]:
        if pitch_x is None or pitch_y is None:
            pitch_x, pitch_y = self._pitch()
        candidate, _snapped = resize_box_candidate(
            box,
            handle,
            dx,
            dy,
            pitch_x=float(pitch_x),
            pitch_y=float(pitch_y),
            square_snap=square_snap,
            snapped=snapped,
            bypass=bypass,
        )
        return clamp_author_box(
            candidate[0],
            candidate[1],
            candidate[2],
            candidate[3],
            min_width=min_width,
            min_height=min_height,
        )

    def finish_author_geometry(self, pos: QPoint, *, modifiers: int = 0) -> None:
        session = self._geometry_session
        if not session or session.get("origin") is None:
            self._geometry_session = None
            self._paint_layer.set_geometry_overrides(())
            self._host.release_mouse_if_grabbed()
            unlock = getattr(self._host, "unlock_resize_cursor", None)
            if callable(unlock):
                unlock()
            self._host.sync_selection_handles()
            return
        if session.get("kind") == "group-move":
            self._finish_group_move(session)
            return
        next_box = self._candidate_from_session(session, pos, modifiers=modifiers)
        preview = session.get("preview_box")
        if next_box is None and isinstance(preview, tuple) and len(preview) == 4:
            next_box = preview  # type: ignore[assignment]
        origin_box = session["box"]
        object_id = str(session.get("object_id") or "")
        self._geometry_session = None
        self._host.release_mouse_if_grabbed()
        unlock = getattr(self._host, "unlock_resize_cursor", None)
        if callable(unlock):
            unlock()
        if next_box is None:
            self._host.sync_selection_handles()
            return
        x, y, width, height = origin_box  # type: ignore[misc]
        if next_box != (x, y, width, height) and object_id:
            item = self.author_item(object_id)
            if isinstance(item, TextObject):
                self._host.emit_author_update(TextUpdateIntent(object_id, box=next_box))
            elif isinstance(item, ShapeObject):
                self._host.emit_author_update(ShapeUpdateIntent(object_id, box=next_box))
            else:
                self._host.emit_author_update(AuthorUpdateIntent(object_id, box=next_box))
        self._host.sync_selection_handles()

    def selected_handle_at(self, pos: QPoint) -> tuple[str, AuthorKey] | None:
        """I3: selected author handles sit above body hits and cards."""
        ids = self._host.interaction().author_selection_ids()
        if not ids:
            return None
        origin = self._host.workspace_origin_offset()
        metrics = self._host.metrics()
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
                    pixel = board_point_to_pixels(point, metrics, origin_offset=origin)
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
                metrics,
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

    def author_keys_intersecting(
        self, rect: tuple[int, int, int, int]
    ) -> tuple[AuthorKey, ...]:
        """Free objects whose pixel bounds intersect ``rect``.

        The rule matches card marquee: ``QRect.intersects``, not containment.
        Selection itself is written by the gesture that owns ``_selection``.
        """
        hits: list[AuthorKey] = []
        for item in self._author_objects:
            object_id = str(getattr(item, "object_id", "") or "")
            bounds = self._item_pixel_rect(item)
            if not object_id or bounds is None:
                continue
            if pixel_rects_intersect(bounds, rect):
                hits.append(AuthorKey(object_id))
        return tuple(hits)

    def keys_at(self, pos: QPoint) -> tuple[AuthorKey, ...]:
        """Reverse-z hit list. The paint layer itself remains mouse-transparent."""
        hits: list[AuthorKey] = []
        origin = self._host.workspace_origin_offset()
        metrics = self._host.metrics()
        probe_px = (float(pos.x()), float(pos.y()))
        for item in reversed(self._author_objects):
            object_id = str(getattr(item, "object_id", "") or "")
            if not object_id:
                continue
            box = getattr(item, "box", None)
            if box is not None:
                mapped = board_box_to_pixels(
                    (box.x, box.y, box.width, box.height),
                    metrics,
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
            if isinstance(item, ConnectorObject):
                pixels = _route_pixels(item, metrics, origin)
                if hit_polyline_px(pixels, probe_px, connector_pick_tolerance_px()):
                    hits.append(AuthorKey(object_id))
                continue
            if isinstance(item, StrokeObject):
                pixels = _point_pixels(item.points, metrics, origin)
                if hit_polyline_px(
                    pixels, probe_px, stroke_pick_tolerance_px(item.width_px_100)
                ):
                    hits.append(AuthorKey(object_id))
        return tuple(hits)

    def _movable_selected_objects(self) -> tuple[object, ...]:
        selected = self._host.interaction().author_selection_ids()
        members = []
        for item in self._author_objects:
            object_id = str(getattr(item, "object_id", "") or "")
            if object_id not in selected:
                continue
            if bool(getattr(item, "locked", False)):
                continue
            if _connector_has_snapped_end(item):
                continue
            members.append(item)
        return tuple(members)

    def _begin_group_move(self, members: tuple[object, ...], pos: QPoint) -> None:
        if not members:
            return
        self._geometry_session = {
            "kind": "group-move",
            "origin": self.pixel_to_board_point(pos),
            "members": members,
            "overrides": (),
            "snapped_delta": (0.0, 0.0),
        }
        self._host.grab_mouse_for_feedback()
        self._update_group_move(self._geometry_session, pos)

    def _update_group_move(self, session: dict[str, object], pos: QPoint) -> None:
        current = self.pixel_to_board_point(pos)
        origin = session.get("origin")
        members = session.get("members")
        if current is None or not isinstance(origin, tuple) or not isinstance(members, tuple):
            return
        dx = float(current[0]) - float(origin[0])
        dy = float(current[1]) - float(origin[1])
        snapped = snap_board_point((dx, dy)) or (0.0, 0.0)
        session["snapped_delta"] = snapped
        overrides = []
        drop_rects = []
        for item in members:
            object_id = str(getattr(item, "object_id", "") or "")
            if not object_id:
                continue
            overrides.append((object_id, _geometry_tuple(translate_object(item, dx, dy))))
            drop = self._item_pixel_rect(translate_object(item, snapped[0], snapped[1]))
            if drop is not None:
                drop_rects.append(drop)
        session["overrides"] = tuple(overrides)
        self.sync_projection()
        self._host.ghost_overlay().set_selection_rects(tuple(drop_rects), handles=False)

    def _finish_group_move(self, session: dict[str, object]) -> None:
        snapped = session.get("snapped_delta") or (0.0, 0.0)
        members = session.get("members") or ()
        ids = tuple(
            str(getattr(item, "object_id", "") or "")
            for item in members
            if str(getattr(item, "object_id", "") or "")
        )
        sx, sy = float(snapped[0]), float(snapped[1])
        self._geometry_session = None
        self._paint_layer.set_geometry_overrides(())
        self._host.release_mouse_if_grabbed()
        unlock = getattr(self._host, "unlock_resize_cursor", None)
        if callable(unlock):
            unlock()
        if ids and (sx != 0.0 or sy != 0.0):
            self._host.emit_author_update(AuthorNudgeIntent(ids, sx, sy))
        self.sync_projection()
        self._host.sync_selection_handles()

    def _live_geometry_overrides(self) -> tuple[tuple[str, tuple], ...]:
        session = self._geometry_session
        if not session or session.get("kind") != "group-move":
            return ()
        overrides = session.get("overrides") or ()
        return tuple(overrides)

    def _text_handle_boxes(self, overrides: dict[str, tuple]) -> tuple[tuple, ...]:
        selected = self._host.interaction().author_selection_ids()
        boxes = []
        for item in self._author_objects:
            if not isinstance(item, TextObject):
                continue
            object_id = str(getattr(item, "object_id", "") or "")
            if object_id not in selected:
                continue
            geometry = overrides.get(object_id)
            if geometry is not None and geometry[0] == "box":
                boxes.append(geometry[1])
                continue
            box = getattr(item, "box", None)
            if box is not None:
                boxes.append((box.x, box.y, box.width, box.height))
        return tuple(boxes)

    def _item_pixel_rect(self, item) -> tuple[int, int, int, int] | None:
        origin = self._host.workspace_origin_offset()
        metrics = self._host.metrics()
        box = getattr(item, "box", None)
        if box is not None:
            mapped = board_box_to_pixels(
                (box.x, box.y, box.width, box.height),
                metrics,
                origin_offset=origin,
            )
            return None if mapped is None else pixel_box(mapped)
        if isinstance(item, ConnectorObject):
            return _pixel_bounds(_route_pixels(item, metrics, origin))
        if isinstance(item, StrokeObject):
            return _pixel_bounds(_point_pixels(item.points, metrics, origin))
        return None


def _connector_has_snapped_end(item) -> bool:
    """A connector end is snapped when it carries an anchor target."""
    if not isinstance(item, ConnectorObject):
        return False
    return item.start.target is not None or item.end.target is not None


def _geometry_tuple(item) -> tuple:
    """Preview geometry tag for one translated object."""
    box = getattr(item, "box", None)
    if box is not None:
        return ("box", (box.x, box.y, box.width, box.height))
    if isinstance(item, StrokeObject):
        return ("points", tuple((point.x, point.y) for point in item.points))
    if isinstance(item, ConnectorObject):
        return (
            "connector",
            (item.start.point.x, item.start.point.y),
            (item.end.point.x, item.end.point.y),
        )
    return ()


def _point_pixels(points, metrics, origin) -> tuple[tuple[float, float], ...]:
    pixels = []
    for point in points:
        pixel = board_point_to_pixels(
            (float(point.x), float(point.y)), metrics, origin_offset=origin
        )
        if pixel is not None:
            pixels.append(pixel)
    return tuple(pixels)


def _route_pixels(item: ConnectorObject, metrics, origin) -> tuple[tuple[float, float], ...]:
    route = connector_route_points(
        (item.start.point.x, item.start.point.y),
        (item.end.point.x, item.end.point.y),
        route=item.route,
        elbow_bias=item.elbow_bias,
    )
    pixels = []
    for point in route:
        pixel = board_point_to_pixels(point, metrics, origin_offset=origin)
        if pixel is not None:
            pixels.append(pixel)
    return tuple(pixels)


def _pixel_bounds(pixels: tuple[tuple[float, float], ...]) -> tuple[int, int, int, int] | None:
    if not pixels:
        return None
    xs = [point[0] for point in pixels]
    ys = [point[1] for point in pixels]
    left = int(math.floor(min(xs)))
    top = int(math.floor(min(ys)))
    right = int(math.ceil(max(xs)))
    bottom = int(math.ceil(max(ys)))
    return (left, top, max(1, right - left), max(1, bottom - top))


__all__ = ["FreeGridAuthorController", "FreeGridAuthorHost", "pixel_box"]
