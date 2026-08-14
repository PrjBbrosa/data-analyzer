"""Direct-manipulation state machine for UltraView free-grid cards.

Qt-free: pixel positions are ``(x, y)`` tuples. Widgets feed events in and
commit through the existing ``geometry_requested`` intent. No second write path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from mf4_analyzer.ui.ultraview_state import FreeGridPlacement, GridRect, UltraViewRef

from .free_grid import (
    GridMetrics,
    rect_is_available,
    rect_to_pixels,
    snapped_move_rect,
    snapped_resize_rect,
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

    def ghost_pixels(self, metrics: GridMetrics, pos: tuple[int, int]) -> Rect:
        if self.handle is not None:
            return rect_to_pixels(self.candidate, metrics)
        x, y, width, height = rect_to_pixels(self.origin, metrics)
        dx = int(pos[0]) - self.press[0]
        dy = int(pos[1]) - self.press[1]
        return x + dx, y + dy, width, height

    def highlight_pixels(self, metrics: GridMetrics) -> Rect:
        return rect_to_pixels(self.candidate, metrics)

    def badge(self) -> str:
        if self.handle is None:
            return ""
        return f"{self.candidate.column_span}×{self.candidate.row_span}"


MoveSession = GestureSession


@dataclass
class FreeGridGesture:
    """Owned move/resize session. Widgets must not keep a parallel copy."""

    _owned_names: ClassVar[tuple[str, ...]] = ("_session",)
    _session: GestureSession | None = field(default=None, init=False)

    def session(self) -> GestureSession | None:
        return self._session

    def is_active(self) -> bool:
        return self._session is not None and self._session.active

    def is_armed(self) -> bool:
        return self._session is not None

    def press(
        self,
        ref: UltraViewRef,
        origin: GridRect,
        board_pos: tuple[int, int],
        grab_offset: tuple[int, int],
        handle: str | None = None,
    ) -> None:
        self._session = GestureSession(
            ref=ref,
            origin=origin,
            press=(int(board_pos[0]), int(board_pos[1])),
            grab_offset=(int(grab_offset[0]), int(grab_offset[1])),
            candidate=origin,
            handle=handle,
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
        if session.handle is None:
            session.candidate = snapped_move_rect(session.origin, (dx, dy), metrics)
        else:
            session.candidate = snapped_resize_rect(
                session.origin,
                (dx, dy),
                metrics,
                session.handle,
                keep_aspect=session.keep_aspect,
            )
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
