"""Direct-manipulation state machine for UltraView free-grid cards.

Qt-free: pixel positions are ``(x, y)`` tuples. Widgets feed events in and
commit through the existing ``geometry_requested`` intent. No second write path.
Card selection is a projection of ``BoardInteractionController``; this module
owns only the move/resize/marquee session.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Iterable

from mf4_analyzer.ui.ultraview_state import FreeGridPlacement, GridRect, UltraViewRef

from .author_tools import BoardInteractionController
from .free_grid import (
    GridMetrics,
    LAYOUT_MOVE,
    LAYOUT_RESIZE,
    LayoutPlan,
    avoidance_preferred_delta,
    clamp_rect,
    group_translate_rects,
    pixels_to_grid_delta,
    plan_layout,
    rect_to_pixels,
    snapped_resize_rect,
    translated_move_rect,
)

Rect = tuple[int, int, int, int]
# Qt.LeftButton, stored as an int so this module stays free of PyQt.
_LEFT_BUTTON = 1


@dataclass
class GestureSession:
    ref: UltraViewRef
    origin: GridRect
    press: tuple[int, int]
    grab_offset: tuple[int, int]
    candidate: GridRect
    legal: bool = True
    active: bool = False
    handle: str | None = None
    keep_aspect: bool = False
    group_origins: dict[UltraViewRef, GridRect] = field(default_factory=dict)
    group_candidates: dict[UltraViewRef, GridRect] = field(default_factory=dict)
    plan: LayoutPlan | None = None
    layout_revision: int = 0
    plan_reused: bool = False
    button: int = _LEFT_BUTTON

    def ghost_pixels(self, metrics: GridMetrics, pos: tuple[int, int]) -> Rect:
        """Follow layer for a move; resize stays on the snapped preview.

        A move keeps the press point inside the card: the snapshot origin is
        the press-time card rect plus the whole pointer delta, including the
        distance already travelled when the drag threshold trips. The drop
        outline stays on ``highlight_pixels``.
        """
        if self.handle is not None:
            return rect_to_pixels(self._preview_rect(), metrics)
        return self._follow_pixels(self.origin, metrics, pos)

    def _follow_pixels(
        self, origin: GridRect, metrics: GridMetrics, pos: tuple[int, int]
    ) -> Rect:
        base = rect_to_pixels(origin, metrics)
        dx = int(pos[0]) - int(self.press[0])
        dy = int(pos[1]) - int(self.press[1])
        return (base[0] + dx, base[1] + dy, base[2], base[3])

    def _preview_rect(self) -> GridRect:
        if self.plan is not None and self.plan.accepted and self.plan.mover_after is not None:
            return self.plan.mover_after
        if clamp_rect(self.candidate) != self.candidate:
            return clamp_rect(self.candidate)
        return self.candidate

    def highlight_pixels(self, metrics: GridMetrics) -> Rect:
        return rect_to_pixels(self.candidate, metrics)

    def group_ghost_pixels(
        self, metrics: GridMetrics, pos: tuple[int, int]
    ) -> tuple[Rect, ...]:
        """Follow-layer snapshots. Drop outlines stay on ``group_highlight_pixels``.

        Moving cards keep the press point: each bitmap is that card's press-time
        pixel rect plus the pointer delta. Displaced neighbours stay on the
        snapped plan rect. Resize keeps the snapped preview, because the span
        itself is the grid result.

        An out-of-board group drag commits nothing (``plan=None``), so those
        snapshots stay a rigid pixel translation. Clamping each member on its
        own drew a squashed shape that matched neither the pointer nor the
        outcome (review 2026-08-15 §4.3).
        """
        if self.handle is not None:
            if self.plan is not None and self.plan.accepted:
                return tuple(
                    rect_to_pixels(rect, metrics)
                    for _ref, rect in self.plan.preview_rects()
                )
            return (rect_to_pixels(self._preview_rect(), metrics),)
        if self.plan is not None and self.plan.accepted:
            rects: list[Rect] = []
            for ref, grid_rect in self.plan.preview_rects():
                origin = self.group_origins.get(ref)
                if origin is not None:
                    rects.append(self._follow_pixels(origin, metrics, pos))
                else:
                    rects.append(rect_to_pixels(grid_rect, metrics))
            return tuple(rects)
        if len(self.group_origins) > 1:
            return tuple(
                self._follow_pixels(origin, metrics, pos)
                for origin in self.group_origins.values()
            )
        return (self._follow_pixels(self.origin, metrics, pos),)

    def group_highlight_pixels(self, metrics: GridMetrics) -> tuple[Rect, ...]:
        if self.plan is not None and self.plan.accepted:
            return tuple(
                rect_to_pixels(rect, metrics) for _ref, rect in self.plan.preview_rects()
            )
        if self.handle is not None or len(self.group_candidates) <= 1:
            return (self.highlight_pixels(metrics),)
        return tuple(
            rect_to_pixels(rect, metrics) for rect in self._rigid_group_rects()
        )

    def _rigid_group_rects(self) -> tuple[GridRect, ...]:
        """Un-clamped rigid translation of the selection, in press order."""
        column_delta = self.candidate.column - self.origin.column
        row_delta = self.candidate.row - self.origin.row
        rects: list[GridRect] = []
        for ref, origin in self.group_origins.items():
            rect = self.group_candidates.get(ref)
            if rect is None:
                rect = GridRect(
                    origin.column + column_delta,
                    origin.row + row_delta,
                    origin.column_span,
                    origin.row_span,
                )
            rects.append(rect)
        return tuple(rects)

    def preview_refs(self) -> tuple[UltraViewRef, ...]:
        if self.plan is not None and self.plan.accepted:
            return tuple(ref for ref, _rect in self.plan.preview_rects())
        if self.is_group_move():
            return tuple(self.group_origins)
        return (self.ref,)

    def badge(self) -> str:
        return f"{self.candidate.column_span}×{self.candidate.row_span}"

    def is_group_move(self) -> bool:
        return self.handle is None and len(self.group_origins) > 1


@dataclass
class MarqueeSession:
    origin: tuple[int, int]
    current: tuple[int, int]
    additive: bool = False
    button: int = _LEFT_BUTTON

    def rect(self) -> Rect:
        x0, y0 = self.origin
        x1, y1 = self.current
        left, right = min(x0, x1), max(x0, x1)
        top, bottom = min(y0, y1), max(y0, y1)
        return left, top, right - left, bottom - top


MoveSession = GestureSession


@dataclass
class FreeGridGesture:
    """Owned move/resize session. Card selection is a projection of the controller."""

    interaction: BoardInteractionController = field(
        default_factory=BoardInteractionController
    )
    _owned_names: ClassVar[tuple[str, ...]] = (
        "_session",
        "_marquee",
        "_plan_fingerprint",
        "_gesture_id",
    )
    _next_gesture_id: ClassVar[int] = 0
    _session: GestureSession | None = field(default=None, init=False)
    _marquee: MarqueeSession | None = field(default=None, init=False)
    _plan_fingerprint: tuple | None = field(default=None, init=False)
    _gesture_id: int = field(default=0, init=False)

    def gesture_id(self) -> int:
        return int(self._gesture_id)

    def candidate_fingerprint(self) -> tuple | None:
        return self._plan_fingerprint

    def session(self) -> GestureSession | None:
        return self._session

    def is_active(self) -> bool:
        return self._session is not None and self._session.active

    def is_armed(self) -> bool:
        return self._session is not None

    def selection(self) -> frozenset[UltraViewRef]:
        return self.interaction.card_selection()

    def select_only(self, ref: UltraViewRef) -> None:
        self.interaction.select_only_card(ref)

    def toggle_selected(self, ref: UltraViewRef) -> None:
        self.interaction.toggle_card(ref)

    def set_selection(self, refs: Iterable[UltraViewRef]) -> None:
        self.interaction.replace_card_selection(refs)

    def add_to_selection(self, refs: Iterable[UltraViewRef]) -> None:
        self.interaction.add_cards_to_selection(refs)

    def clear_selection(self) -> None:
        self.interaction.clear_card_keys()

    def restrict_selection(self, wanted: Iterable[UltraViewRef]) -> None:
        self.interaction.restrict_cards(wanted)

    def marquee(self) -> MarqueeSession | None:
        return self._marquee

    def marquee_rect(self) -> Rect | None:
        if self._marquee is None:
            return None
        return self._marquee.rect()

    def begin_marquee(self, pos: tuple[int, int], additive: bool) -> None:
        point = (int(pos[0]), int(pos[1]))
        self._marquee = MarqueeSession(
            origin=point, current=point, additive=bool(additive)
        )

    def update_marquee(self, pos: tuple[int, int]) -> MarqueeSession | None:
        if self._marquee is None:
            return None
        self._marquee.current = (int(pos[0]), int(pos[1]))
        return self._marquee

    def take_marquee(self) -> MarqueeSession | None:
        session = self._marquee
        self._marquee = None
        return session

    def cancel_marquee(self) -> bool:
        if self._marquee is None:
            return False
        self._marquee = None
        return True

    def press(
        self,
        ref: UltraViewRef,
        origin: GridRect,
        board_pos: tuple[int, int],
        grab_offset: tuple[int, int],
        handle: str | None = None,
        group_origins: dict[UltraViewRef, GridRect] | None = None,
        layout_revision: int = 0,
    ) -> None:
        origins = dict(group_origins) if group_origins else {ref: origin}
        type(self)._next_gesture_id += 1
        self._gesture_id = type(self)._next_gesture_id
        self._plan_fingerprint = None
        self._session = GestureSession(
            ref=ref,
            origin=origin,
            press=(int(board_pos[0]), int(board_pos[1])),
            grab_offset=(int(grab_offset[0]), int(grab_offset[1])),
            candidate=origin,
            handle=handle,
            group_origins=origins,
            group_candidates=dict(origins),
            layout_revision=int(layout_revision),
        )

    def press_resize(
        self,
        ref: UltraViewRef,
        origin: GridRect,
        handle: str,
        board_pos: tuple[int, int],
        grab_offset: tuple[int, int],
        layout_revision: int = 0,
    ) -> None:
        self.press(
            ref,
            origin,
            board_pos,
            grab_offset,
            handle=handle,
            layout_revision=layout_revision,
        )

    def update(
        self,
        board_pos: tuple[int, int],
        metrics: GridMetrics,
        placements: list[FreeGridPlacement] | tuple[FreeGridPlacement, ...],
        start_drag_distance: int,
        keep_aspect: bool = False,
    ) -> GestureSession | None:
        session = self._session
        if session is None:
            return None
        pos = (int(board_pos[0]), int(board_pos[1]))
        dx = pos[0] - session.press[0]
        dy = pos[1] - session.press[1]
        if not session.active:
            if abs(dx) + abs(dy) < max(1, int(start_drag_distance)):
                session.plan_reused = False
                return session
            session.active = True
        session.keep_aspect = bool(keep_aspect) and session.handle is not None
        if session.handle is None and session.is_group_move():
            column_delta, row_delta = pixels_to_grid_delta((dx, dy), metrics)
            translated, in_bounds = group_translate_rects(
                session.group_origins, (), column_delta, row_delta
            )
            candidate = translated.get(session.ref, session.origin)
            fingerprint = _layout_fingerprint(
                session, candidate, translated, LAYOUT_MOVE
            )
            if fingerprint == self._plan_fingerprint:
                session.plan_reused = True
                return session
            session.plan_reused = False
            session.group_candidates = translated
            session.candidate = candidate
            self._plan_fingerprint = fingerprint
            if not in_bounds:
                session.plan = None
                session.legal = False
                return session
            session.plan = plan_layout(
                placements,
                session.ref,
                session.candidate,
                LAYOUT_MOVE,
                layout_revision=session.layout_revision,
                preferred=avoidance_preferred_delta(session.origin, session.candidate),
                incoming=translated,
            )
            session.legal = session.plan.accepted
            if session.plan.accepted and session.plan.mover_after is not None:
                session.candidate = session.plan.mover_after
            return session
        if session.handle is None:
            candidate = translated_move_rect(session.origin, (dx, dy), metrics)
            incoming = {session.ref: candidate}
        else:
            candidate = snapped_resize_rect(
                session.origin,
                (dx, dy),
                metrics,
                session.handle,
                keep_aspect=session.keep_aspect,
            )
            incoming = {session.ref: candidate}
        operation = LAYOUT_RESIZE if session.handle is not None else LAYOUT_MOVE
        fingerprint = _layout_fingerprint(session, candidate, incoming, operation)
        if fingerprint == self._plan_fingerprint:
            session.plan_reused = True
            return session
        session.plan_reused = False
        session.candidate = candidate
        session.group_candidates = dict(incoming)
        self._plan_fingerprint = fingerprint
        session.plan = plan_layout(
            placements,
            session.ref,
            session.candidate,
            operation,
            layout_revision=session.layout_revision,
            preferred=avoidance_preferred_delta(session.origin, session.candidate),
            incoming=session.group_candidates,
        )
        session.legal = session.plan.accepted
        if session.plan.accepted and session.plan.mover_after is not None:
            session.candidate = session.plan.mover_after
            session.group_candidates[session.ref] = session.plan.mover_after
        return session

    def cancel_lost_button(self, buttons: int) -> bool:
        """Drop a move or marquee whose button is no longer down. Does not commit."""
        cancelled = False
        session = self._session
        if session is not None and not (int(buttons) & int(session.button)):
            self.cancel()
            cancelled = True
        marquee = self._marquee
        if marquee is not None and not (int(buttons) & int(marquee.button)):
            self.cancel_marquee()
            cancelled = True
        return cancelled

    def cancel(self) -> GestureSession | None:
        session = self._session
        self._session = None
        self._plan_fingerprint = None
        return session

    def take(self) -> GestureSession | None:
        return self.cancel()


def _layout_fingerprint(
    session: GestureSession,
    candidate: GridRect,
    incoming: dict[UltraViewRef, GridRect],
    operation: str,
) -> tuple:
    """Cache key for drag-time plan_layout: skip identical snapped candidates."""
    incoming_key = tuple(
        (
            ref.section,
            ref.view_id,
            rect.column,
            rect.row,
            rect.column_span,
            rect.row_span,
        )
        for ref, rect in sorted(
            incoming.items(),
            key=lambda item: (item[0].section, item[0].view_id),
        )
    )
    return (
        session.layout_revision,
        session.ref.section,
        session.ref.view_id,
        candidate.column,
        candidate.row,
        candidate.column_span,
        candidate.row_span,
        operation,
        incoming_key,
        session.keep_aspect,
    )
