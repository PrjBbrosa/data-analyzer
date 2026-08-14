"""Direct-manipulation state machine for UltraView free-grid cards.

Qt-free: pixel positions are ``(x, y)`` tuples. Widgets feed events in and
commit through the existing ``geometry_requested`` intent. No second write path.
Selection and marquee live here so the board does not keep a parallel copy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Iterable

from mf4_analyzer.ui.ultraview_state import FreeGridPlacement, GridRect, UltraViewRef

from .free_grid import (
    GridMetrics,
    group_translate_rects,
    clamp_rect,
    pixels_to_grid_delta,
    rect_is_available,
    rect_to_pixels,
    snapped_resize_rect,
    translated_move_rect,
)

Rect = tuple[int, int, int, int]


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

    def ghost_pixels(self, metrics: GridMetrics, pos: tuple[int, int]) -> Rect:
        if self.handle is not None:
            return rect_to_pixels(self.candidate, metrics)
        x, y, width, height = rect_to_pixels(self.origin, metrics)
        dx = int(pos[0]) - self.press[0]
        dy = int(pos[1]) - self.press[1]
        return x + dx, y + dy, width, height

    def highlight_pixels(self, metrics: GridMetrics) -> Rect:
        return rect_to_pixels(self.candidate, metrics)

    def group_ghost_pixels(
        self, metrics: GridMetrics, pos: tuple[int, int]
    ) -> tuple[Rect, ...]:
        if self.handle is not None or len(self.group_origins) <= 1:
            return (self.ghost_pixels(metrics, pos),)
        dx = int(pos[0]) - self.press[0]
        dy = int(pos[1]) - self.press[1]
        ghosts = []
        for origin in self.group_origins.values():
            x, y, width, height = rect_to_pixels(origin, metrics)
            ghosts.append((x + dx, y + dy, width, height))
        return tuple(ghosts)

    def group_highlight_pixels(self, metrics: GridMetrics) -> tuple[Rect, ...]:
        if self.handle is not None or len(self.group_candidates) <= 1:
            return (self.highlight_pixels(metrics),)
        return tuple(
            rect_to_pixels(rect, metrics) for rect in self.group_candidates.values()
        )

    def badge(self) -> str:
        if self.handle is None:
            return ""
        return f"{self.candidate.column_span}×{self.candidate.row_span}"

    def is_group_move(self) -> bool:
        return self.handle is None and len(self.group_origins) > 1


@dataclass
class MarqueeSession:
    origin: tuple[int, int]
    current: tuple[int, int]
    additive: bool = False

    def rect(self) -> Rect:
        x0, y0 = self.origin
        x1, y1 = self.current
        left, right = min(x0, x1), max(x0, x1)
        top, bottom = min(y0, y1), max(y0, y1)
        return left, top, right - left, bottom - top


MoveSession = GestureSession


@dataclass
class FreeGridGesture:
    """Owned move/resize/selection session. Widgets must not keep a parallel copy."""

    _owned_names: ClassVar[tuple[str, ...]] = ("_session", "_selection", "_marquee")
    _session: GestureSession | None = field(default=None, init=False)
    _selection: frozenset[UltraViewRef] = field(default_factory=frozenset, init=False)
    _marquee: MarqueeSession | None = field(default=None, init=False)

    def session(self) -> GestureSession | None:
        return self._session

    def is_active(self) -> bool:
        return self._session is not None and self._session.active

    def is_armed(self) -> bool:
        return self._session is not None

    def selection(self) -> frozenset[UltraViewRef]:
        return self._selection

    def select_only(self, ref: UltraViewRef) -> None:
        self._selection = frozenset((ref,))

    def toggle_selected(self, ref: UltraViewRef) -> None:
        current = set(self._selection)
        if ref in current:
            current.discard(ref)
        else:
            current.add(ref)
        self._selection = frozenset(current)

    def set_selection(self, refs: Iterable[UltraViewRef]) -> None:
        self._selection = frozenset(refs)

    def add_to_selection(self, refs: Iterable[UltraViewRef]) -> None:
        self._selection = self._selection | frozenset(refs)

    def clear_selection(self) -> None:
        self._selection = frozenset()

    def restrict_selection(self, wanted: Iterable[UltraViewRef]) -> None:
        allowed = set(wanted)
        self._selection = frozenset(ref for ref in self._selection if ref in allowed)

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
    ) -> None:
        origins = dict(group_origins) if group_origins else {ref: origin}
        self._session = GestureSession(
            ref=ref,
            origin=origin,
            press=(int(board_pos[0]), int(board_pos[1])),
            grab_offset=(int(grab_offset[0]), int(grab_offset[1])),
            candidate=origin,
            handle=handle,
            group_origins=origins,
            group_candidates=dict(origins),
        )

    def press_resize(
        self,
        ref: UltraViewRef,
        origin: GridRect,
        handle: str,
        board_pos: tuple[int, int],
        grab_offset: tuple[int, int],
    ) -> None:
        self.press(ref, origin, board_pos, grab_offset, handle=handle)

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
                return session
            session.active = True
        session.keep_aspect = bool(keep_aspect) and session.handle is not None
        if session.handle is None and session.is_group_move():
            column_delta, row_delta = pixels_to_grid_delta((dx, dy), metrics)
            others = [
                item.rect for item in placements if item.ref not in session.group_origins
            ]
            translated, legal = group_translate_rects(
                session.group_origins, others, column_delta, row_delta
            )
            session.group_candidates = translated
            session.legal = legal
            session.candidate = translated.get(session.ref, session.origin)
            return session
        if session.handle is None:
            session.candidate = translated_move_rect(session.origin, (dx, dy), metrics)
            in_bounds = session.candidate == clamp_rect(session.candidate)
            session.group_candidates = {session.ref: session.candidate}
            session.legal = in_bounds and rect_is_available(
                session.candidate, placements, excluding=session.ref
            )
            return session
        session.candidate = snapped_resize_rect(
            session.origin,
            (dx, dy),
            metrics,
            session.handle,
            keep_aspect=session.keep_aspect,
        )
        session.group_candidates = {session.ref: session.candidate}
        session.legal = rect_is_available(
            session.candidate, placements, excluding=session.ref
        )
        return session

    def cancel(self) -> GestureSession | None:
        session = self._session
        self._session = None
        return session

    def take(self) -> GestureSession | None:
        return self.cancel()
