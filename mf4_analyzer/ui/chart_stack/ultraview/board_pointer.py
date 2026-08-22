"""Pointer routing for UltraView author tools.

Page remains the Qt host and signal emitter. ``PointerRouter`` owns draft and
geometry pointer sessions so UltraViewPage stays a composition root. Mouse and
Laser share this dispatch; only the cursor provider differs.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PyQt5.QtCore import QEvent, QPoint, QTimer, Qt
from PyQt5.QtGui import QKeyEvent, QMouseEvent, QTabletEvent
from PyQt5.QtWidgets import QApplication, QWidget

from mf4_analyzer.ui.ultraview_state import (
    AnchorTarget,
    BoardBox,
    ConnectorObject,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
    UnknownAuthorObject,
)
from .author_edits import copy_author_objects
from .author_selection import next_style_changes
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
    BoardItemKey,
    CardKey,
    AuthorNudgeIntent,
    AuthorPasteIntent,
    AuthorUpdateIntent,
    AuthorZOrderIntent,
    CLOSED_SHAPE_TYPES,
    CONNECTOR_CLICK_DRAG_THRESHOLD,
    CONNECTOR_HEADS,
    CONNECTOR_LINE_STYLES,
    CONNECTOR_STROKE_PALETTES,
    CONNECTOR_STROKE_WIDTHS,
    CONNECTOR_TYPES,
    SHAPE_CORNER_TYPES,
    SHAPE_CORNERS,
    SHAPE_FILL_PALETTES,
    SHAPE_LINE_STYLES,
    SHAPE_STROKE_PALETTES,
    SHAPE_STROKE_WIDTHS,
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
    is_draw_ink_subtool,
    lasso_selection_keys,
    new_author_object_id,
    normalize_connector_type,
    resolve_board_hit,
    resize_shape_box,
    resize_text_box,
    shape_box_from_points,
    text_box_from_points,
)
from .author_widgets import is_text_input_widget
from .feedback import AUTHOR_LOCKED, text_for_key
from .free_grid import hit_handle
from .widgets import FreeGridCard


class _EmitPort:
    """Signal-shaped emit callback so session methods keep ``.emit(...)``."""

    __slots__ = ("emit",)

    def __init__(self, emit: Callable[..., None]) -> None:
        self.emit = emit


@dataclass(frozen=True)
class PointerHitFacts:
    """Structured kwargs for ``resolve_board_hit``. Not a second priority table."""

    editor_active: bool = False
    viewport_pan: bool = False
    resize_handle: str | None = None
    handle_item: BoardItemKey | None = None
    author_hits_rev_z: Sequence[AuthorKey] = ()
    card: CardKey | None = None

    def resolve(self):
        return resolve_board_hit(
            editor_active=self.editor_active,
            viewport_pan=self.viewport_pan,
            resize_handle=self.resize_handle,
            handle_item=self.handle_item,
            author_hits_rev_z=self.author_hits_rev_z,
            card=self.card,
        )


class PointerRouter:
    """Draft and geometry pointer sessions for the four author tools.

    Constructed with the live ``FreeGridBoard`` and the same
    ``BoardInteractionController`` instance Page already owns. Does not
    install a QApplication event filter; Page.eventFilter delegates here.
    """

    def __init__(
        self,
        *,
        free_grid,
        interaction,
        viewport,
        board: Callable[[], object],
        filter_host: QWidget,
        emit_create: Callable[..., None],
        emit_update: Callable[..., None],
        emit_delete: Callable[..., None],
        emit_feedback: Callable[[str], None],
        sync_tool_cursor: Callable[[], None],
        sync_tool_rail: Callable[[], None],
        refresh_author_toolbar: Callable[[], None],
        selection_toolbar,
    ) -> None:
        self._free_grid = free_grid
        self._interaction = interaction
        self._viewport = viewport
        self._board_of = board
        self._filter_host = filter_host
        self.author_create_requested = _EmitPort(emit_create)
        self.author_update_requested = _EmitPort(emit_update)
        self.author_delete_requested = _EmitPort(emit_delete)
        self._emit_feedback = emit_feedback
        self._sync_tool_cursor = sync_tool_cursor
        self._sync_tool_rail_from_controller = sync_tool_rail
        self._refresh_author_toolbar = refresh_author_toolbar
        self._selection_toolbar = selection_toolbar
        self._filtered_cards: set[int] = set()
        self._editor_kind = ""
        self._text_limit_notified = False

    @property
    def _board(self):
        return self._board_of()

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

    def handle_board_event(self, watched, event) -> bool:
        """Dispatch an armed author-tool event. Mouse and Laser share this path."""
        if watched is not self._free_grid and not isinstance(watched, FreeGridCard):
            return False
        if self._pointer_tool_armed(TOOL_DRAW):
            if self._handle_draw_board_event(watched, event):
                return True
        if self._pointer_tool_armed(TOOL_CONNECTOR):
            if self._handle_connector_board_event(watched, event):
                return True
        if watched is self._free_grid:
            if self._pointer_tool_armed(TOOL_TEXT):
                if self._handle_text_board_event(event):
                    return True
            if self._pointer_tool_armed(TOOL_SHAPES):
                if self._handle_shape_board_event(event):
                    return True
        return False

    def _text_create_armed(self) -> bool:
        return (
            self._free_grid.creation_allowed()
            and self._interaction.active_tool() == TOOL_TEXT
            and not self._interaction.is_editor_active()
            and not self._free_grid.author_text_editor().is_editing()
        )

    def _pointer_tool_armed(self, tool: str) -> bool:
        """H2: Page only intercepts when the matching tool is armed or in session."""
        if self._interaction.active_tool() == tool:
            return True
        draft = self._interaction.draft()
        if draft is not None and draft.tool == tool:
            return True
        if tool == TOOL_TEXT and self._text_geometry_session is not None:
            return True
        if tool == TOOL_SHAPES and self._shape_geometry_session is not None:
            return True
        if tool == TOOL_CONNECTOR and self._connector_geometry_session is not None:
            return True
        return False

    def _board_point_from_pos(self, pos: QPoint):
        return pixels_to_board_point(
            (float(pos.x()), float(pos.y())),
            self._free_grid.metrics(),
            origin_offset=self._free_grid.author_paint_layer().model().origin_offset,
        )

    def _draw_create_armed(self) -> bool:
        return (
            self._free_grid.creation_allowed()
            and self._interaction.active_tool() == TOOL_DRAW
            and not self._interaction.is_editor_active()
            and not self._free_grid.author_text_editor().is_editing()
        )

    def _draw_dpr(self) -> float:
        try:
            ratio = float(self._free_grid.devicePixelRatioF())
        except (AttributeError, TypeError, ValueError):
            ratio = 1.0
        return ratio if ratio > 0.0 else 1.0

    def _clear_draw_draft_paint(self) -> None:
        self._free_grid.author_paint_layer().clear_live_stroke()

    def _paint_draw_sample(self, point, *, append: bool) -> None:
        style = self._interaction.draw_style()
        draft = self._interaction.draft()
        tool = draft.subtool if draft is not None else style.tool
        palette = draft.palette if draft is not None else style.palette
        width = draft.width_px_100 if draft is not None else style.width_px_100
        role = "overlay" if not is_draw_ink_subtool(tool) else "ink"
        layer = self._free_grid.author_paint_layer()
        if append:
            layer.append_live_stroke_point(
                point, tool=tool, palette=palette, width_px=width, role=role
            )
            return
        layer.set_live_stroke(
            (point,), tool=tool, palette=palette, width_px=width, role=role
        )

    def _handle_draw_board_event(self, watched, event) -> bool:
        types = {
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseMove,
            QEvent.TabletPress,
            QEvent.TabletRelease,
            QEvent.TabletMove,
        }
        if event.type() not in types:
            return False
        if self._viewport.is_panning():
            if self._interaction.draft() is not None and self._interaction.draft().tool == TOOL_DRAW:
                self._interaction.pause_draw_samples()
                return False
            return False
        pos = self._event_board_pos(watched, event)
        if event.type() in (QEvent.MouseButtonPress, QEvent.TabletPress):
            is_tablet = isinstance(event, QTabletEvent)
            button = event.button() if hasattr(event, "button") else Qt.NoButton
            if not is_tablet and button != Qt.LeftButton:
                return False
            if self._draw_create_armed():
                additive = bool(event.modifiers() & Qt.ShiftModifier) if hasattr(
                    event, "modifiers"
                ) else False
                self._begin_draw_draft(pos, additive=additive)
                return True
            return False
        if event.type() in (QEvent.MouseButtonRelease, QEvent.TabletRelease):
            draft = self._interaction.draft()
            if draft is not None and draft.tool == TOOL_DRAW:
                self._finish_draw_draft(pos)
                return True
            return False
        if event.type() in (QEvent.MouseMove, QEvent.TabletMove):
            draft = self._interaction.draft()
            if draft is not None and draft.tool == TOOL_DRAW:
                if self._viewport.space_down():
                    self._interaction.pause_draw_samples()
                    return True
                self._update_draw_draft(pos)
                return True
            return False
        return False

    def _begin_draw_draft(self, pos: QPoint, *, additive: bool = False) -> None:
        origin = self._board_point_from_pos(pos)
        if origin is None:
            return
        self._interaction.begin_draft(
            TOOL_DRAW, origin=origin, object_id=new_author_object_id()
        )
        draft = self._interaction.draft()
        if draft is None or not draft.points:
            return
        draft.additive = bool(additive)
        if draft.subtool == DRAW_ERASER:
            records = []
            for item in self._board.author_objects:
                if not isinstance(item, StrokeObject) or item.locked:
                    continue
                record = stroke_hit_record(
                    item.object_id,
                    ((point.x, point.y) for point in item.points),
                    item.width_px_100,
                )
                if record is not None:
                    records.append(record)
            self._interaction.arm_eraser_index(records)
            self._note_eraser_segment(draft.points[0], draft.points[0])
        self._paint_draw_sample(draft.points[0], append=False)
        self._free_grid.grabMouse()

    def _update_draw_draft(self, pos: QPoint) -> None:
        current = self._board_point_from_pos(pos)
        draft = self._interaction.draft()
        if draft is None or draft.tool != TOOL_DRAW:
            return
        before = len(draft.points)
        last = draft.points[-1] if draft.points else None
        code = self._interaction.append_draw_sample(
            current, self._free_grid.metrics(), dpr=self._draw_dpr()
        )
        draft = self._interaction.draft()
        if draft is not None and len(draft.points) > before:
            if draft.subtool == DRAW_ERASER and last is not None:
                self._note_eraser_segment(last, draft.points[-1])
            self._paint_draw_sample(draft.points[-1], append=True)
        if code == "stroke_sample_limit":
            self._finish_draw_draft(pos)
            self._emit_feedback("笔画点数已达上限，已结束当前笔画")

    def _note_eraser_segment(self, start, end) -> None:
        draft = self._interaction.draft()
        if draft is None or draft.subtool != DRAW_ERASER:
            return
        self._interaction.note_eraser_hits(
            strokes_hit_by_segment(draft.hit_index, start, end)
        )

    def _finish_draw_draft(self, pos: QPoint) -> None:
        self._release_text_mouse()
        draft = self._interaction.draft()
        self._clear_draw_draft_paint()
        if draft is None or draft.tool != TOOL_DRAW:
            self._interaction.cancel_draft()
            self._sync_tool_cursor()
            return
        current = self._board_point_from_pos(pos)
        last = draft.points[-1] if draft.points else None
        if current is not None:
            before = len(draft.points)
            self._interaction.append_draw_sample(
                current, self._free_grid.metrics(), dpr=self._draw_dpr()
            )
            draft = self._interaction.draft() or draft
            if (
                draft.subtool == DRAW_ERASER
                and last is not None
                and len(draft.points) > before
            ):
                self._note_eraser_segment(last, draft.points[-1])
        if draft.subtool == DRAW_LASSO:
            self._finish_lasso_draft(draft)
            return
        if draft.subtool == DRAW_ERASER:
            self._finish_eraser_draft(draft)
            return
        if draft.object_id is None:
            self._interaction.cancel_draft()
            self._sync_tool_cursor()
            return
        points = self._interaction.persist_draft_stroke(
            self._free_grid.metrics(), dpr=self._draw_dpr()
        )
        style = self._interaction.draw_style()
        object_id = draft.object_id
        self._interaction.commit_draft()
        if len(points) < 2:
            self._sync_tool_rail_from_controller()
            self._sync_tool_cursor()
            return
        self.author_create_requested.emit(
            StrokeCreateIntent(
                object_id=object_id,
                points=points,
                tool=draft.subtool or style.tool,
                palette=draft.palette or style.palette,
                width_px_100=draft.width_px_100 or style.width_px_100,
            )
        )
        self._sync_tool_rail_from_controller()
        self._sync_tool_cursor()

    def _finish_eraser_draft(self, draft) -> None:
        deleted = tuple(draft.erased_ids)
        self._interaction.commit_draft()
        if deleted:
            self.author_delete_requested.emit(AuthorDeleteIntent(deleted))
        self._sync_tool_rail_from_controller()
        self._sync_tool_cursor()

    def _finish_lasso_draft(self, draft) -> None:
        if lasso_is_usable(draft.points):
            keys = lasso_selection_keys(
                path=tuple(draft.points),
                author_centers=self._lasso_author_centers(),
                card_centers=self._lasso_card_centers(),
            )
            self._interaction.finish_lasso_selection(keys, additive=bool(draft.additive))
        else:
            self._interaction.commit_draft()
            self._interaction.set_active_tool(TOOL_SELECT)
        self._free_grid.sync_selection_projection()
        self._sync_tool_rail_from_controller()
        self._sync_tool_cursor()

    def _lasso_author_centers(self) -> tuple[tuple[str, tuple[float, float]], ...]:
        centers = []
        for item in self._board.author_objects:
            object_id = str(getattr(item, "object_id", "") or "")
            if not object_id:
                continue
            center = self._author_item_center(item)
            if center is not None:
                centers.append((object_id, center))
        return tuple(centers)

    def _lasso_card_centers(self) -> tuple[tuple[object, tuple[float, float]], ...]:
        centers = []
        for placement in self._board.free_grid:
            rect = placement.rect
            center = (
                float(rect.column) + float(rect.column_span) / 2.0,
                float(rect.row) + float(rect.row_span) / 2.0,
            )
            centers.append((placement.ref, center))
        return tuple(centers)

    def _author_item_center(self, item) -> tuple[float, float] | None:
        box = getattr(item, "box", None)
        if box is not None:
            return box_center((box.x, box.y, box.width, box.height))
        points = getattr(item, "points", None)
        if points:
            return polyline_center((point.x, point.y) for point in points)
        start = getattr(item, "start", None)
        end = getattr(item, "end", None)
        if start is None or end is None:
            return None
        first = getattr(start, "point", start)
        last = getattr(end, "point", end)
        return polyline_center(((first.x, first.y), (last.x, last.y)))

    def _author_item(self, object_id: str):
        wanted = str(object_id or "")
        for item in self._board.author_objects:
            if getattr(item, "object_id", "") == wanted:
                return item
            if isinstance(item, UnknownAuthorObject) and str(item.raw.get("id") or "") == wanted:
                return item
        return None

    def _release_text_mouse(self) -> None:
        if QWidget.mouseGrabber() is self._free_grid:
            self._free_grid.releaseMouse()

    def _handle_text_board_event(self, event) -> bool:
        editor = self._free_grid.author_text_editor()
        if isinstance(event, QMouseEvent) and event.button() == Qt.LeftButton:
            if event.type() == QEvent.MouseButtonPress:
                if editor.is_editing() and not editor.geometry().contains(event.pos()):
                    self._commit_or_cancel_text_editor()
                    return True
                hit = self._free_grid.classify_press(
                    event.pos(), modifiers=event.modifiers()
                )
                if hit.kind == HIT_AUTHOR and isinstance(hit.item, AuthorKey):
                    item = self._author_item(hit.item.object_id)
                    if isinstance(item, TextObject):
                        self._handle_text_author_press(hit, event)
                        return True
                if self._text_create_armed() and hit.kind == HIT_BLANK:
                    self._begin_text_draft(event.pos())
                    return True
                return False
            if event.type() == QEvent.MouseButtonDblClick:
                hit = self._free_grid.classify_press(
                    event.pos(), modifiers=event.modifiers()
                )
                if hit.kind == HIT_AUTHOR and isinstance(hit.item, AuthorKey):
                    item = self._author_item(hit.item.object_id)
                    if isinstance(item, TextObject):
                        self._begin_text_edit(item, replace=False)
                        return True
                return False
            if event.type() == QEvent.MouseButtonRelease:
                if self._interaction.draft() is not None and (
                    self._interaction.draft().tool == TOOL_TEXT
                ):
                    self._finish_text_draft(event.pos())
                    return True
                if self._text_geometry_session is not None:
                    self._finish_text_geometry(event.pos())
                    return True
                return False
        if event.type() == QEvent.MouseMove and isinstance(event, QMouseEvent):
            draft = self._interaction.draft()
            if draft is not None and draft.tool == TOOL_TEXT:
                self._update_text_draft(event.pos())
                return True
            if self._text_geometry_session is not None:
                self._update_text_geometry(event.pos())
                return True
            return False
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            return self._handle_text_type_to_edit(event)
        return False

    def _handle_text_author_press(self, hit, event: QMouseEvent) -> None:
        item = self._author_item(hit.item.object_id)
        if not isinstance(item, TextObject):
            return
        additive = bool(event.modifiers() & Qt.ShiftModifier)
        if additive:
            self._interaction.toggle(hit.item)
            self._free_grid.sync_selection_projection()
            self._refresh_author_toolbar()
            return
        self._interaction.select_only(hit.item)
        self._free_grid.sync_selection_projection()
        self._refresh_author_toolbar()
        if item.locked:
            self._emit_feedback(text_for_key(AUTHOR_LOCKED))
            return
        mapped = board_box_to_pixels(
            (item.box.x, item.box.y, item.box.width, item.box.height),
            self._free_grid.metrics(),
            origin_offset=self._free_grid.author_paint_layer().model().origin_offset,
        )
        handle = None
        if mapped is not None:
            handle = hit_handle(
                (int(mapped[0]), int(mapped[1]), int(mapped[2]), int(mapped[3])),
                (event.pos().x(), event.pos().y()),
            )
        self._text_geometry_session = {
            "object_id": item.object_id,
            "kind": "resize" if handle else "move",
            "handle": handle,
            "origin": self._board_point_from_pos(event.pos()),
            "box": (item.box.x, item.box.y, item.box.width, item.box.height),
        }

    def _begin_text_draft(self, pos: QPoint) -> None:
        origin = self._board_point_from_pos(pos)
        if origin is None:
            return
        self._interaction.begin_draft(
            TOOL_TEXT, origin=origin, object_id=new_author_object_id()
        )
        self._free_grid.grabMouse()

    def _update_text_draft(self, pos: QPoint) -> None:
        self._interaction.update_draft(self._board_point_from_pos(pos))

    def _finish_text_draft(self, pos: QPoint) -> None:
        self._release_text_mouse()
        draft = self._interaction.draft()
        if draft is None or draft.origin is None or draft.object_id is None:
            self._interaction.cancel_draft()
            return
        self._interaction.update_draft(self._board_point_from_pos(pos))
        current = self._interaction.draft()
        box = text_box_from_points(draft.origin, None if current is None else current.current)
        fmt = self._interaction.text_format()
        style = TextObject(
            draft.object_id,
            "text",
            box=BoardBox(*box),
            text="",
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
        self._begin_text_edit(style, replace=False)
        self._refresh_author_toolbar()

    def _update_text_geometry(self, pos: QPoint) -> None:
        session = self._text_geometry_session
        if not session or session.get("origin") is None:
            return
        current = self._board_point_from_pos(pos)
        if current is None:
            return
        origin = session["origin"]
        dx = current[0] - origin[0]
        dy = current[1] - origin[1]
        box = session["box"]
        handle = session.get("handle")
        if session.get("kind") == "resize" and handle:
            resize_text_box(box, str(handle), dx, dy)
        else:
            clamp_author_box(
                box[0] + dx,
                box[1] + dy,
                box[2],
                box[3],
                min_width=TEXT_MIN_WIDTH,
                min_height=TEXT_MIN_HEIGHT,
            )

    def _finish_text_geometry(self, pos: QPoint) -> None:
        session = self._text_geometry_session
        self._text_geometry_session = None
        self._release_text_mouse()
        if not session or session.get("origin") is None:
            return
        current = self._board_point_from_pos(pos)
        if current is None:
            return
        origin = session["origin"]
        dx = current[0] - origin[0]
        dy = current[1] - origin[1]
        box = session["box"]
        handle = session.get("handle")
        if session.get("kind") == "resize" and handle:
            next_box = resize_text_box(box, str(handle), dx, dy)
        else:
            next_box = clamp_author_box(
                box[0] + dx,
                box[1] + dy,
                box[2],
                box[3],
                min_width=TEXT_MIN_WIDTH,
                min_height=TEXT_MIN_HEIGHT,
            )
        object_id = str(session.get("object_id") or "")
        if object_id and next_box != box:
            self.author_update_requested.emit(TextUpdateIntent(object_id, box=next_box))

    def _handle_text_type_to_edit(self, event: QKeyEvent) -> bool:
        if self._free_grid.author_text_editor().is_editing():
            return False
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Escape):
            return False
        ids = self._interaction.author_selection_ids()
        if len(ids) != 1:
            return False
        item = self._author_item(next(iter(ids)))
        if not isinstance(item, TextObject) or item.locked:
            return False
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers():
            self._begin_text_edit(item, replace=False)
            return True
        typed = event.text()
        blocked = Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier
        if typed and typed.isprintable() and not (event.modifiers() & blocked):
            self._begin_text_edit(item, replace=True)
            self._free_grid.author_text_editor().setPlainText(typed)
            return True
        return False

    def _begin_text_edit(self, item: TextObject, *, replace: bool) -> None:
        if bool(getattr(item, "locked", False)):
            self._emit_feedback(text_for_key(AUTHOR_LOCKED))
            return
        self._text_geometry_session = None
        self._text_limit_notified = False
        self._free_grid.author_text_editor().begin_edit(
            object_id=item.object_id,
            box=item.box,
            text="" if replace else item.text,
            metrics=self._free_grid.metrics(),
            origin_offset=self._free_grid.author_paint_layer().model().origin_offset,
            style=item,
        )
        self._editor_kind = "text"
        self._interaction.set_editor_active(True)
        self._interaction.select_only_author(item.object_id)
        self._free_grid.sync_selection_projection()

    def _commit_or_cancel_text_editor(self) -> None:
        editor = self._free_grid.author_text_editor()
        if not editor.is_editing():
            return
        if self._editor_kind in {"shape", "connector"}:
            editor.commit()
            return
        if not str(editor.current_text() or "").strip():
            editor.cancel()
            return
        editor.commit()

    def _on_text_committed(self, object_id: str, text: str) -> None:
        kind = self._editor_kind
        self._editor_kind = ""
        self._interaction.set_editor_active(False)
        self._text_limit_notified = False
        cleaned = str(text or "")
        if kind == "shape":
            self.author_update_requested.emit(ShapeUpdateIntent(object_id, text=cleaned))
            return
        if kind == "connector":
            self.author_update_requested.emit(ConnectorUpdateIntent(object_id, text=cleaned))
            return
        draft = self._interaction.draft()
        pending = draft is not None and draft.object_id == object_id
        if pending:
            if not cleaned.strip():
                self._interaction.cancel_draft()
                self._sync_tool_rail_from_controller()
                self._free_grid.sync_tool_cursor()
                return
            box = text_box_from_points(draft.origin or (0.0, 0.0), draft.current)
            fmt = self._interaction.text_format()
            self._interaction.commit_draft()
            self.author_create_requested.emit(
                TextCreateIntent(
                    object_id=object_id,
                    box=box,
                    text=cleaned,
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
            )
            self._sync_tool_rail_from_controller()
            self._free_grid.sync_tool_cursor()
            return
        self.author_update_requested.emit(TextUpdateIntent(object_id, text=cleaned))

    def _on_text_cancelled(self, object_id: str) -> None:
        self._editor_kind = ""
        self._interaction.set_editor_active(False)
        self._text_limit_notified = False
        draft = self._interaction.draft()
        if draft is not None and draft.object_id == object_id:
            self._interaction.cancel_draft()
        self._sync_tool_rail_from_controller()
        self._free_grid.sync_tool_cursor()

    def _on_text_focus_lost(self) -> None:
        editor = self._free_grid.author_text_editor()
        if not editor.is_editing():
            return
        now = QApplication.focusWidget()
        if is_text_input_widget(now):
            return
        toolbar = getattr(self, "_selection_toolbar", None)
        if toolbar is not None and now is not None and (
            now is toolbar or toolbar.isAncestorOf(now)
        ):
            return
        self._commit_or_cancel_text_editor()

    def _on_text_limit_reached(self) -> None:
        if self._text_limit_notified:
            return
        self._text_limit_notified = True
        self._emit_feedback("文字已达 6000 字上限")

    def _shape_create_armed(self) -> bool:
        return (
            self._free_grid.creation_allowed()
            and self._interaction.active_tool() == TOOL_SHAPES
            and not self._interaction.is_editor_active()
            and not self._free_grid.author_text_editor().is_editing()
        )

    def _shape_modifiers(self, event) -> tuple[bool, bool, bool]:
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.NoModifier
        keep_aspect = bool(modifiers & Qt.ShiftModifier)
        from_center = bool(modifiers & Qt.AltModifier)
        snap = not bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))
        return keep_aspect, from_center, snap

    def _clear_shape_draft_paint(self) -> None:
        self._free_grid.author_paint_layer().set_draft_shape(None, None)

    def _paint_shape_draft(self, box: tuple[float, float, float, float], shape: str) -> None:
        self._free_grid.author_paint_layer().set_draft_shape(shape, box)

    def _handle_shape_board_event(self, event) -> bool:
        editor = self._free_grid.author_text_editor()
        if isinstance(event, QMouseEvent) and event.button() == Qt.LeftButton:
            if event.type() == QEvent.MouseButtonPress:
                if editor.is_editing() and not editor.geometry().contains(event.pos()):
                    self._commit_or_cancel_text_editor()
                    return True
                hit = self._free_grid.classify_press(
                    event.pos(), modifiers=event.modifiers()
                )
                if hit.kind == HIT_AUTHOR and isinstance(hit.item, AuthorKey):
                    item = self._author_item(hit.item.object_id)
                    if isinstance(item, ShapeObject):
                        self._handle_shape_author_press(hit, event)
                        return True
                if self._shape_create_armed() and hit.kind == HIT_BLANK:
                    self._begin_shape_draft(event)
                    return True
                return False
            if event.type() == QEvent.MouseButtonDblClick:
                hit = self._free_grid.classify_press(
                    event.pos(), modifiers=event.modifiers()
                )
                if hit.kind == HIT_AUTHOR and isinstance(hit.item, AuthorKey):
                    item = self._author_item(hit.item.object_id)
                    if isinstance(item, ShapeObject):
                        self._begin_shape_label_edit(item, replace=False)
                        return True
                return False
            if event.type() == QEvent.MouseButtonRelease:
                if self._interaction.draft() is not None and (
                    self._interaction.draft().tool == TOOL_SHAPES
                ):
                    self._finish_shape_draft(event)
                    return True
                if self._shape_geometry_session is not None:
                    self._finish_shape_geometry(event)
                    return True
                return False
        if event.type() == QEvent.MouseMove and isinstance(event, QMouseEvent):
            draft = self._interaction.draft()
            if draft is not None and draft.tool == TOOL_SHAPES:
                self._update_shape_draft(event)
                return True
            if self._shape_geometry_session is not None:
                self._update_shape_geometry(event)
                return True
            return False
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            return self._handle_shape_type_to_edit(event)
        return False

    def _handle_shape_author_press(self, hit, event: QMouseEvent) -> None:
        item = self._author_item(hit.item.object_id)
        if not isinstance(item, ShapeObject):
            return
        additive = bool(event.modifiers() & Qt.ShiftModifier)
        if additive:
            self._interaction.toggle(hit.item)
            self._free_grid.sync_selection_projection()
            self._refresh_author_toolbar()
            return
        self._interaction.select_only(hit.item)
        self._free_grid.sync_selection_projection()
        self._refresh_author_toolbar()
        if item.locked:
            self._emit_feedback(text_for_key(AUTHOR_LOCKED))
            return
        mapped = board_box_to_pixels(
            (item.box.x, item.box.y, item.box.width, item.box.height),
            self._free_grid.metrics(),
            origin_offset=self._free_grid.author_paint_layer().model().origin_offset,
        )
        handle = None
        if mapped is not None:
            handle = hit_box_handle(
                (int(mapped[0]), int(mapped[1]), int(mapped[2]), int(mapped[3])),
                (event.pos().x(), event.pos().y()),
            )
        self._shape_geometry_session = {
            "object_id": item.object_id,
            "kind": "resize" if handle else "move",
            "handle": handle or "move",
            "origin": self._board_point_from_pos(event.pos()),
            "box": (item.box.x, item.box.y, item.box.width, item.box.height),
        }
        self._free_grid.grabMouse()

    def _begin_shape_draft(self, event: QMouseEvent) -> None:
        origin = self._board_point_from_pos(event.pos())
        if origin is None:
            return
        self._interaction.begin_draft(
            TOOL_SHAPES, origin=origin, object_id=new_author_object_id()
        )
        keep_aspect, from_center, snap = self._shape_modifiers(event)
        box = shape_box_from_points(
            origin, None, keep_aspect=keep_aspect, from_center=from_center, snap=snap
        )
        self._paint_shape_draft(box, self._interaction.last_shape())
        self._free_grid.grabMouse()

    def _update_shape_draft(self, event: QMouseEvent) -> None:
        current = self._board_point_from_pos(event.pos())
        self._interaction.update_draft(current)
        draft = self._interaction.draft()
        if draft is None or draft.origin is None:
            return
        keep_aspect, from_center, snap = self._shape_modifiers(event)
        box = shape_box_from_points(
            draft.origin,
            current,
            keep_aspect=keep_aspect,
            from_center=from_center,
            snap=snap,
        )
        self._paint_shape_draft(box, draft.shape or self._interaction.last_shape())

    def _finish_shape_draft(self, event: QMouseEvent) -> None:
        self._release_text_mouse()
        draft = self._interaction.draft()
        self._clear_shape_draft_paint()
        if draft is None or draft.origin is None or draft.object_id is None:
            self._interaction.cancel_draft()
            return
        current = self._board_point_from_pos(event.pos())
        keep_aspect, from_center, snap = self._shape_modifiers(event)
        box = shape_box_from_points(
            draft.origin,
            current,
            keep_aspect=keep_aspect,
            from_center=from_center,
            snap=snap,
        )
        shape = draft.shape or self._interaction.last_shape()
        fmt = self._interaction.shape_format()
        corner = fmt.corner_radius
        if corner is None:
            corner = default_shape_corner(shape)
        self._interaction.commit_draft()
        self.author_create_requested.emit(
            ShapeCreateIntent(
                object_id=draft.object_id,
                box=box,
                shape=shape,
                text="",
                fill_palette=fmt.fill_palette,
                stroke_palette=fmt.stroke_palette,
                stroke_width=fmt.stroke_width,
                line_style=fmt.line_style,
                corner_radius=corner,
            )
        )
        self._interaction.select_only_author(draft.object_id)
        self._sync_tool_rail_from_controller()
        self._free_grid.sync_tool_cursor()
        self._refresh_author_toolbar()

    def _next_shape_box(self, event: QMouseEvent, session: dict) -> tuple[float, float, float, float] | None:
        if session.get("origin") is None:
            return None
        current = self._board_point_from_pos(event.pos())
        if current is None:
            return None
        origin = session["origin"]
        dx = current[0] - origin[0]
        dy = current[1] - origin[1]
        box = session["box"]
        keep_aspect, from_center, snap = self._shape_modifiers(event)
        handle = str(session.get("handle") or "move")
        return resize_shape_box(
            box,
            handle,
            dx,
            dy,
            keep_aspect=keep_aspect,
            from_center=from_center,
            snap=snap,
        )

    def _update_shape_geometry(self, event: QMouseEvent) -> None:
        session = self._shape_geometry_session
        if not session:
            return
        next_box = self._next_shape_box(event, session)
        if next_box is None:
            return
        item = self._author_item(str(session.get("object_id") or ""))
        shape = item.shape if isinstance(item, ShapeObject) else self._interaction.last_shape()
        self._paint_shape_draft(next_box, shape)

    def _finish_shape_geometry(self, event: QMouseEvent) -> None:
        session = self._shape_geometry_session
        self._shape_geometry_session = None
        self._release_text_mouse()
        self._clear_shape_draft_paint()
        if not session:
            return
        next_box = self._next_shape_box(event, session)
        if next_box is None:
            return
        object_id = str(session.get("object_id") or "")
        box = session.get("box")
        if object_id and next_box != box:
            self.author_update_requested.emit(ShapeUpdateIntent(object_id, box=next_box))

    def _handle_shape_type_to_edit(self, event: QKeyEvent) -> bool:
        if self._free_grid.author_text_editor().is_editing():
            return False
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Escape):
            return False
        ids = self._interaction.author_selection_ids()
        if len(ids) != 1:
            return False
        item = self._author_item(next(iter(ids)))
        if not isinstance(item, ShapeObject) or item.locked:
            return False
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers():
            self._begin_shape_label_edit(item, replace=False)
            return True
        typed = event.text()
        blocked = Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier
        if typed and typed.isprintable() and not (event.modifiers() & blocked):
            self._begin_shape_label_edit(item, replace=True)
            self._free_grid.author_text_editor().setPlainText(typed)
            return True
        return False

    def _begin_shape_label_edit(self, item: ShapeObject, *, replace: bool) -> None:
        if bool(getattr(item, "locked", False)):
            self._emit_feedback(text_for_key(AUTHOR_LOCKED))
            return
        self._shape_geometry_session = None
        self._text_limit_notified = False
        self._editor_kind = "shape"
        self._free_grid.author_text_editor().begin_edit(
            object_id=item.object_id,
            box=item.box,
            text="" if replace else item.text,
            metrics=self._free_grid.metrics(),
            origin_offset=self._free_grid.author_paint_layer().model().origin_offset,
        )
        self._interaction.set_editor_active(True)
        self._interaction.select_only_author(item.object_id)
        self._free_grid.sync_selection_projection()

    def _on_shape_format_requested(self, key: str, value: object) -> None:
        ids = tuple(self._interaction.author_selection_ids())
        items = [
            item
            for item in (self._author_item(object_id) for object_id in ids)
            if isinstance(item, ShapeObject)
        ]
        if not items:
            return
        if key == "text":
            if len(items) == 1:
                self._begin_shape_label_edit(items[0], replace=False)
            return
        changes = next_style_changes(items[0], key, value)
        if not changes:
            return
        remembered = {
            field: getattr(items[0], field)
            for field in (
                "shape",
                "fill_palette",
                "stroke_palette",
                "stroke_width",
                "line_style",
                "corner_radius",
            )
        }
        if changes.get("clear_fill"):
            remembered["fill_palette"] = None
        for field, next_value in changes.items():
            if field in remembered:
                remembered[field] = next_value
        self._interaction.set_shape_format(**remembered)
        for item in items:
            payload = dict(changes)
            if "shape" in payload and "corner_radius" not in payload:
                next_shape = str(payload["shape"])
                if next_shape not in SHAPE_CORNER_TYPES:
                    payload["corner_radius"] = 0
            self.author_update_requested.emit(ShapeUpdateIntent(item.object_id, **payload))
        QTimer.singleShot(0, self._refresh_author_toolbar)

    def _connector_create_armed(self) -> bool:
        return (
            self._free_grid.creation_allowed()
            and self._interaction.active_tool() == TOOL_CONNECTOR
            and not self._interaction.is_editor_active()
            and not self._free_grid.author_text_editor().is_editing()
        )

    def _connector_snap_enabled(self, event) -> bool:
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.NoModifier
        return not bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))

    def _connector_shift(self, event) -> bool:
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.NoModifier
        return bool(modifiers & Qt.ShiftModifier)

    def _clear_connector_draft_paint(self) -> None:
        self._free_grid.author_paint_layer().set_guides()

    def _paint_connector_draft(self, start, end, *, route: str = "straight") -> None:
        points = connector_route_points(start, end, route)
        self._free_grid.author_paint_layer().set_guides(draft_points=points)

    def _event_board_pos(self, watched, event) -> QPoint:
        pos = event.pos()
        if watched is self._free_grid or watched is None:
            return pos
        return watched.mapTo(self._free_grid, pos)

    def _map_point(self, pos: QPoint, *, snap: bool) -> tuple[float, float] | None:
        point = self._board_point_from_pos(pos)
        if point is None:
            return None
        if not snap:
            return point
        snapped = snap_board_point(point)
        return snapped if snapped is not None else point

    def _handle_connector_board_event(self, watched, event) -> bool:
        if event.type() not in {
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick,
            QEvent.MouseMove,
        }:
            return False
        pos = self._event_board_pos(watched, event)
        editor = self._free_grid.author_text_editor()
        if isinstance(event, QMouseEvent) and event.button() == Qt.LeftButton:
            if event.type() == QEvent.MouseButtonPress:
                if editor.is_editing() and not editor.geometry().contains(pos):
                    self._commit_or_cancel_text_editor()
                    return True
                draft = self._interaction.draft()
                if (
                    draft is not None
                    and draft.tool == TOOL_CONNECTOR
                    and draft.origin is not None
                ):
                    self._finish_connector_draft(event, pos)
                    return True
                handle = self._connector_handle_at(pos)
                if handle is not None:
                    self._begin_connector_geometry(handle, event, pos)
                    return True
                if self._connector_create_armed():
                    self._begin_connector_draft(event, pos)
                    return True
                item = self._connector_at(pos)
                if item is not None:
                    self._interaction.select_only_author(item.object_id)
                    self._free_grid.sync_selection_projection()
                    self._refresh_author_toolbar()
                    return True
                return False
            if event.type() == QEvent.MouseButtonDblClick:
                draft = self._interaction.draft()
                if draft is not None and draft.tool == TOOL_CONNECTOR:
                    self._finish_connector_draft(event, pos)
                    return True
                item = self._connector_at(pos)
                if item is not None:
                    self._begin_connector_label_edit(item)
                    return True
                return False
            if event.type() == QEvent.MouseButtonRelease:
                if self._interaction.draft() is not None and (
                    self._interaction.draft().tool == TOOL_CONNECTOR
                ):
                    self._finish_connector_draft(event, pos)
                    return True
                if self._connector_geometry_session is not None:
                    self._finish_connector_geometry(event, pos)
                    return True
                return False
        if event.type() == QEvent.MouseMove and isinstance(event, QMouseEvent):
            draft = self._interaction.draft()
            if draft is not None and draft.tool == TOOL_CONNECTOR:
                self._update_connector_draft(event, pos)
                return True
            if self._connector_geometry_session is not None:
                self._update_connector_geometry(event, pos)
                return True
            return False
        return False

    def _begin_connector_draft(self, event: QMouseEvent, pos: QPoint) -> None:
        snap = self._connector_snap_enabled(event)
        origin = self._map_point(pos, snap=snap)
        if origin is None:
            return
        start_target = self._endpoint_target_at(pos, origin, snap=snap, preferred=None)
        if start_target is not None:
            box = self._box_for_target(start_target)
            if box is not None:
                origin = box_anchor_point(box, start_target.anchor, origin) or origin
        self._interaction.begin_draft(
            TOOL_CONNECTOR, origin=origin, object_id=new_author_object_id()
        )
        draft = self._interaction.draft()
        if draft is not None:
            draft.start_target = start_target
            draft.current = origin
        self._paint_connector_draft(
            origin, origin, route=connector_style_from_type(self._interaction.last_connector())["route"]
        )
        self._free_grid.grabMouse()

    def _update_connector_draft(self, event: QMouseEvent, pos: QPoint) -> None:
        draft = self._interaction.draft()
        if draft is None or draft.origin is None:
            return
        snap = self._connector_snap_enabled(event)
        current = self._map_point(pos, snap=snap)
        if current is None:
            return
        if self._connector_shift(event):
            current = constrain_shift_point(draft.origin, current)
        self._interaction.update_draft(current)
        route = connector_style_from_type(draft.connector or self._interaction.last_connector())["route"]
        self._paint_connector_draft(draft.origin, current, route=route)

    def _finish_connector_draft(self, event: QMouseEvent, pos: QPoint) -> None:
        draft = self._interaction.draft()
        if draft is None or draft.origin is None or draft.object_id is None:
            self._interaction.cancel_draft()
            self._clear_connector_draft_paint()
            self._release_text_mouse()
            return
        snap = self._connector_snap_enabled(event)
        current = self._map_point(pos, snap=snap) or draft.current or draft.origin
        if self._connector_shift(event):
            current = constrain_shift_point(draft.origin, current)
        dx = abs(current[0] - draft.origin[0])
        dy = abs(current[1] - draft.origin[1])
        if not draft.awaiting_end and dx < CONNECTOR_CLICK_DRAG_THRESHOLD and dy < CONNECTOR_CLICK_DRAG_THRESHOLD:
            draft.awaiting_end = True
            draft.current = current
            self._release_text_mouse()
            return
        end_target = None
        if snap:
            end_target = self._endpoint_target_at(pos, current, snap=True, preferred=None)
            if end_target is not None:
                box = self._box_for_target(end_target)
                if box is not None:
                    current = box_anchor_point(box, end_target.anchor, draft.origin) or current
        kind = draft.connector or self._interaction.last_connector()
        fmt = self._interaction.connector_format()
        style = connector_style_from_type(kind)
        self._clear_connector_draft_paint()
        self._release_text_mouse()
        self._interaction.commit_draft()
        self.author_create_requested.emit(
            ConnectorCreateIntent(
                object_id=draft.object_id,
                start=draft.origin,
                end=current,
                connector_type=kind,
                start_target=draft.start_target,
                end_target=end_target,
                line_style=fmt.line_style,
                stroke_palette=fmt.stroke_palette,
                stroke_width=fmt.stroke_width,
                start_head=style["start_head"],
                end_head=style["end_head"],
            )
        )
        self._interaction.select_only_author(draft.object_id)
        self._sync_tool_rail_from_controller()
        self._free_grid.sync_tool_cursor()
        self._refresh_author_toolbar()

    def _begin_connector_geometry(self, handle: tuple[str, str], event: QMouseEvent, pos: QPoint) -> None:
        kind, name = handle
        if kind == "anchor":
            self._interaction.set_active_tool(TOOL_CONNECTOR)
            self._begin_connector_draft(event, pos)
            draft = self._interaction.draft()
            if draft is not None:
                draft.start_target = self._anchor_target_from_handle(name, pos)
            return
        item = self._author_item(name)
        if not isinstance(item, ConnectorObject):
            return
        self._interaction.select_only_author(item.object_id)
        self._connector_geometry_session = {
            "object_id": item.object_id,
            "handle": kind,
            "origin": self._board_point_from_pos(pos),
            "start": (item.start.point.x, item.start.point.y),
            "end": (item.end.point.x, item.end.point.y),
            "start_target": item.start.target,
            "end_target": item.end.target,
            "route": item.route,
            "elbow_bias": item.elbow_bias,
        }
        self._free_grid.grabMouse()

    def _update_connector_geometry(self, event: QMouseEvent, pos: QPoint) -> None:
        session = self._connector_geometry_session
        if not session:
            return
        snap = self._connector_snap_enabled(event)
        current = self._map_point(pos, snap=snap)
        if current is None:
            return
        start = session["start"]
        end = session["end"]
        handle = str(session.get("handle") or "")
        if handle == "start":
            if self._connector_shift(event):
                current = constrain_shift_point(end, current)
            start = current
        elif handle == "end":
            if self._connector_shift(event):
                current = constrain_shift_point(start, current)
            end = current
        elif handle == "elbow":
            start_pt, end_pt = start, end
            if abs(end_pt[0] - start_pt[0]) >= abs(end_pt[1] - start_pt[1]):
                span = end_pt[0] - start_pt[0]
                bias = 0.5 if span == 0 else min(1.0, max(0.0, (current[0] - start_pt[0]) / span))
            else:
                span = end_pt[1] - start_pt[1]
                bias = 0.5 if span == 0 else min(1.0, max(0.0, (current[1] - start_pt[1]) / span))
            session["elbow_bias"] = bias
        session["live_start"] = start
        session["live_end"] = end
        self._paint_connector_draft(start, end, route=str(session.get("route") or "straight"))

    def _finish_connector_geometry(self, event: QMouseEvent, pos: QPoint) -> None:
        session = self._connector_geometry_session
        self._connector_geometry_session = None
        self._release_text_mouse()
        self._clear_connector_draft_paint()
        if not session:
            return
        self._update_connector_geometry(event, pos)
        object_id = str(session.get("object_id") or "")
        handle = str(session.get("handle") or "")
        start = session.get("live_start") or session["start"]
        end = session.get("live_end") or session["end"]
        snap = self._connector_snap_enabled(event)
        payload: dict[str, object] = {}
        if handle == "start":
            payload["start"] = start
            if snap:
                target = self._endpoint_target_at(pos, start, snap=True, preferred=None)
                if target is None:
                    payload["clear_start_target"] = True
                else:
                    payload["start_target"] = target
            else:
                payload["clear_start_target"] = True
        elif handle == "end":
            payload["end"] = end
            if snap:
                target = self._endpoint_target_at(pos, end, snap=True, preferred=None)
                if target is None:
                    payload["clear_end_target"] = True
                else:
                    payload["end_target"] = target
            else:
                payload["clear_end_target"] = True
        elif handle == "elbow":
            payload["elbow_bias"] = session.get("elbow_bias")
        if object_id and payload:
            self.author_update_requested.emit(ConnectorUpdateIntent(object_id, **payload))

    def _connector_at(self, pos: QPoint) -> ConnectorObject | None:
        point = self._board_point_from_pos(pos)
        if point is None:
            return None
        for item in reversed(self._board.author_objects):
            if not isinstance(item, ConnectorObject):
                continue
            if hit_connector(
                (item.start.point.x, item.start.point.y),
                (item.end.point.x, item.end.point.y),
                point,
                route=item.route,
                stroke_width=item.stroke_width,
                start_head=item.start_head,
                end_head=item.end_head,
                elbow_bias=item.elbow_bias,
            ):
                return item
        return None

    def _connector_handle_at(self, pos: QPoint) -> tuple[str, str] | None:
        origin = self._free_grid.author_paint_layer().model().origin_offset
        metrics = self._free_grid.metrics()
        ids = self._interaction.author_selection_ids()
        for item in self._board.author_objects:
            if not isinstance(item, ConnectorObject) or item.object_id not in ids:
                continue
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
                return (hit, item.object_id)
        for key in self._interaction.selection():
            box_px = self._selection_box_px(key)
            if box_px is None:
                continue
            side = hit_connection_anchor(box_px, (pos.x(), pos.y()))
            if side is not None:
                return ("anchor", side)
        return None

    def _selection_box_px(self, key):
        origin = self._free_grid.author_paint_layer().model().origin_offset
        metrics = self._free_grid.metrics()
        if isinstance(key, AuthorKey):
            item = self._author_item(key.object_id)
            box = getattr(item, "box", None)
            if box is None:
                return None
            return board_box_to_pixels(
                (box.x, box.y, box.width, box.height), metrics, origin_offset=origin
            )
        card = self._free_grid.card_for(key.ref.section, key.ref.view_id) if hasattr(key, "ref") else None
        if card is None:
            return None
        geom = card.geometry()
        return (float(geom.x()), float(geom.y()), float(geom.width()), float(geom.height()))

    def _anchor_target_from_handle(self, side: str, pos: QPoint) -> AnchorTarget | None:
        for key in self._interaction.selection():
            box_px = self._selection_box_px(key)
            if box_px is None:
                continue
            if hit_connection_anchor(box_px, (pos.x(), pos.y())) == side:
                if isinstance(key, AuthorKey):
                    return AnchorTarget("author", object_id=key.object_id, anchor=side)
                if hasattr(key, "ref"):
                    return AnchorTarget("card", card=key.ref, anchor=side)
        return None

    def _endpoint_target_at(self, pos: QPoint, point, *, snap: bool, preferred) -> AnchorTarget | None:
        del preferred
        if not snap:
            return None
        hit = self._free_grid.classify_press(pos)
        if hit.kind == HIT_AUTHOR and isinstance(hit.item, AuthorKey):
            item = self._author_item(hit.item.object_id)
            if isinstance(item, (StickyObject, TextObject, ShapeObject)):
                box = (item.box.x, item.box.y, item.box.width, item.box.height)
                side = "auto"
                if box_anchor_point(box, "auto", point) is not None:
                    side = "auto"
                return AnchorTarget("author", object_id=item.object_id, anchor=side)
        if hit.kind in {HIT_CARD, HIT_RESIZE_HANDLE} and hit.item is not None and hasattr(hit.item, "ref"):
            return AnchorTarget("card", card=hit.item.ref, anchor="auto")
        return None

    def _box_for_target(self, target: AnchorTarget):
        if target.kind == "author":
            item = self._author_item(str(target.object_id or ""))
            box = getattr(item, "box", None)
            if box is None:
                return None
            return (box.x, box.y, box.width, box.height)
        placement = None
        for candidate in self._board.free_grid:
            if candidate.ref == target.card:
                placement = candidate
                break
        if placement is None:
            return None
        rect = placement.rect
        return (float(rect.column), float(rect.row), float(rect.column_span), float(rect.row_span))

    def _begin_connector_label_edit(self, item: ConnectorObject) -> None:
        if bool(getattr(item, "locked", False)):
            self._emit_feedback(text_for_key(AUTHOR_LOCKED))
            return
        bounds = connector_hit_bounds(
            (item.start.point.x, item.start.point.y),
            (item.end.point.x, item.end.point.y),
            route=item.route,
            stroke_width=item.stroke_width,
            start_head=item.start_head,
            end_head=item.end_head,
            elbow_bias=item.elbow_bias,
        )
        mid_x = bounds[0] + bounds[2] / 2.0
        mid_y = bounds[1] + bounds[3] / 2.0
        box = BoardBox(mid_x - 3.0, mid_y - 0.6, 6.0, 1.2)
        self._connector_geometry_session = None
        self._text_limit_notified = False
        self._editor_kind = "connector"
        self._free_grid.author_text_editor().begin_edit(
            object_id=item.object_id,
            box=box,
            text=item.text,
            metrics=self._free_grid.metrics(),
            origin_offset=self._free_grid.author_paint_layer().model().origin_offset,
        )
        self._interaction.set_editor_active(True)
        self._interaction.select_only_author(item.object_id)
        self._free_grid.sync_selection_projection()

    def _on_connector_format_requested(self, key: str, value: object) -> None:
        ids = tuple(self._interaction.author_selection_ids())
        items = [
            item
            for item in (self._author_item(object_id) for object_id in ids)
            if isinstance(item, ConnectorObject)
        ]
        if not items:
            return
        if key == "label":
            if len(items) == 1:
                self._begin_connector_label_edit(items[0])
            return
        changes = next_style_changes(items[0], key, value)
        if not changes:
            return
        remembered = {
            "connector_type": connector_type_from_style(route=items[0].route, end_head=items[0].end_head),
            "route": items[0].route,
            "line_style": items[0].line_style,
            "stroke_palette": items[0].stroke_palette,
            "stroke_width": items[0].stroke_width,
            "start_head": items[0].start_head,
            "end_head": items[0].end_head,
        }
        for field, next_value in changes.items():
            if field in remembered:
                remembered[field] = next_value
            if field == "route":
                remembered["connector_type"] = connector_type_from_style(
                    route=next_value, end_head=remembered["end_head"]
                )
        self._interaction.set_connector_format(**remembered)
        for item in items:
            self.author_update_requested.emit(ConnectorUpdateIntent(item.object_id, **changes))
        QTimer.singleShot(0, self._refresh_author_toolbar)

    def _install_card_connector_filters(self) -> None:
        seen: set[int] = set()
        for card in self._free_grid.card_widgets():
            identity = id(card)
            seen.add(identity)
            if identity not in self._filtered_cards:
                card.installEventFilter(self._filter_host)
                self._filtered_cards.add(identity)
        self._filtered_cards.intersection_update(seen)


PointerRouter.FORWARDED_METHODS = tuple(
    name
    for name, value in vars(PointerRouter).items()
    if callable(value) and not name.startswith("__")
)

