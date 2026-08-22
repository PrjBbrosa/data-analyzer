"""Own FreeGrid author hit/geometry/editor widget bridge.

``AuthorPaintLayer``, ``BoardTextEditor``, and ``StickyNoteWidget`` remain
QWidget children created by ``FreeGridBoard``. This controller must not parent
a second editor or paint layer, and must not become a second
``BoardInteractionController``: tool, draft, selection, clipboard, format
defaults, and ``editor_active`` stay on the Board-owned session.
"""
from __future__ import annotations

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
from .feedback import AUTHOR_LOCKED, text_for_key
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
        if selected:
            for item in self._author_objects:
                if str(getattr(item, "object_id", "")) not in selected:
                    continue
                box = getattr(item, "box", None)
                if box is not None:
                    boxes.append((box.x, box.y, box.width, box.height))
        origin = self._host.workspace_origin_offset()
        metrics = self._host.metrics()
        self._paint_layer.set_model(
            AuthorLayerModel(
                objects=self._author_objects,
                metrics=metrics,
                origin_offset=origin,
                theme=self._author_theme,
                selection_boxes=tuple(boxes),
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
        additive = bool(event.modifiers() & Qt.ShiftModifier)
        if additive:
            self._host.interaction().toggle(hit.item)
            self._host.apply_selection_flags()
            return
        self._host.interaction().select_only(hit.item)
        self._host.apply_selection_flags()
        if item is not None and bool(getattr(item, "locked", False)):
            self._host.emit_author_feedback(text_for_key(AUTHOR_LOCKED))
            return
        if item is None or not isinstance(item, (StickyObject, TextObject, ShapeObject)):
            return
        self.begin_box_geometry(item, pos, handle=None)

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
        }
        self._host.grab_mouse_for_feedback()

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

    def update_author_geometry(self, pos: QPoint) -> None:
        session = self._geometry_session
        if not session or session.get("origin") is None:
            return
        current = self.pixel_to_board_point(pos)
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
            box = self.resize_author_box(
                (x, y, width, height), str(handle), dx, dy, min_width=min_w, min_height=min_h
            )
        mapped = board_box_to_pixels(
            box,
            self._host.metrics(),
            origin_offset=self._host.workspace_origin_offset(),
        )
        if mapped is not None:
            self._host.ghost_overlay().set_selection_rects(
                (pixel_box(mapped),), handles=True
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

    def finish_author_geometry(self, pos: QPoint) -> None:
        session = self._geometry_session
        if not session or session.get("origin") is None:
            self._geometry_session = None
            self._host.release_mouse_if_grabbed()
            self._host.sync_selection_handles()
            return
        current = self.pixel_to_board_point(pos)
        origin = session["origin"]
        box = session["box"]
        self._geometry_session = None
        self._host.release_mouse_if_grabbed()
        if current is None:
            self._host.sync_selection_handles()
            return
        dx = current[0] - origin[0]
        dy = current[1] - origin[1]
        handle = session.get("handle")
        x, y, width, height = box  # type: ignore[misc]
        min_w = float(session.get("min_width") or STICKY_MIN_WIDTH)
        min_h = float(session.get("min_height") or STICKY_MIN_HEIGHT)
        if session.get("kind") == "resize" and handle:
            next_box = self.resize_author_box(
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

    def keys_at(self, pos: QPoint) -> tuple[AuthorKey, ...]:
        """Reverse-z hit list. The paint layer itself remains mouse-transparent."""
        hits: list[AuthorKey] = []
        origin = self._host.workspace_origin_offset()
        metrics = self._host.metrics()
        probe = pixels_to_board_point(
            (float(pos.x()), float(pos.y())),
            metrics,
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


__all__ = ["FreeGridAuthorController", "FreeGridAuthorHost", "pixel_box"]
