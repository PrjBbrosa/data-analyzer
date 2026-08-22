"""Own FreeGrid move/resize feedback: latest pointer, coalescer, frame.

``ViewportFeedbackSurface`` remains the one high-frequency surface and is
created by ``FreeGridBoard``. This controller must not construct a second
surface or a second coalesce timer. Edge auto-pan stays on ViewportController.
"""
from __future__ import annotations

from typing import Protocol

from PyQt5 import sip
from PyQt5.QtCore import QPoint, QRect, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget

from mf4_analyzer.ui.ultraview_state import FreeGridPlacement, GridRect, UltraViewRef

from .card_widgets import FreeGridCard
from .feedback import format_displace_preview
from .free_grid import GridMetrics
from .gesture import FreeGridGesture
from .ghost_overlay import (
    PREVIEW_COLLISION_REJECT,
    PREVIEW_DISPLACED_WARNING,
    PREVIEW_MOVER_VALID,
    PREVIEW_SAFETY_WALL,
)
from .viewport_feedback import ViewportFeedbackSurface

PointerSample = tuple[tuple[int, int], bool, QPoint | None]


class FreeGridFeedbackHost(Protocol):
    """Explicit Board ports. The controller never reads host private fields."""

    def gesture(self) -> FreeGridGesture: ...

    def metrics(self) -> GridMetrics: ...

    def card_for(self, section: str, view_id: str) -> FreeGridCard | None: ...

    def ghost_source_for(self, ref: UltraViewRef) -> QPixmap | QImage | None: ...

    def current_placements(self) -> tuple[FreeGridPlacement, ...]: ...

    def workspace_origin_offset(self) -> tuple[int, int]: ...

    def workspace_pixel_rect(
        self, logical_rect: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]: ...

    def current_zoom(self) -> float: ...

    def is_workspace_gesture_active(self) -> bool: ...

    def emit_workspace_pointer(self, global_pos: QPoint) -> None: ...

    def emit_workspace_gesture(
        self, active: bool, global_pos: QPoint | None = None
    ) -> None: ...

    def note_live_feedback_started(self) -> None: ...

    def is_live_feedback_dimmed(self) -> bool: ...

    def grab_mouse_for_feedback(self) -> None: ...

    def apply_safety_cursor(self, safety: bool) -> None: ...

    def sync_editor_exclusion(self) -> None: ...

    def session_hits_safety(self, session) -> bool: ...

    def safety_bounds_pixel_rect(self) -> QRect: ...

    def safety_sides_for(self, rect: GridRect) -> tuple[str, ...]: ...

    def host_is_deleted(self) -> bool: ...


def _pointer_sample_tuple(
    board_pos: tuple[int, int],
    *,
    keep_aspect: bool = False,
    global_pos: QPoint | None = None,
) -> PointerSample:
    return (
        (int(board_pos[0]), int(board_pos[1])),
        bool(keep_aspect),
        QPoint(global_pos) if global_pos is not None else None,
    )


class FreeGridFeedbackController:
    """One owner for pointer samples, the 0 ms coalescer, and live frames."""

    def __init__(
        self,
        host: FreeGridFeedbackHost,
        overlay: ViewportFeedbackSurface,
        timer_parent: QWidget,
    ) -> None:
        self._host = host
        self._overlay = overlay
        self._latest_pointer_sample: PointerSample | None = None
        self._last_pointer_sample: PointerSample | None = None
        self._last_consumed_candidate_fingerprint: tuple | None = None
        self._feedback_generation = 0
        self._diag_planner_calls = 0
        self._diag_frame_presents = 0
        self._gesture_presenting = False
        self._last_legal_ghosts: tuple = ()
        self._last_legal_highlights: tuple[tuple[int, int, int, int], ...] = ()
        self._pointer_coalesce_timer = QTimer(timer_parent)
        self._pointer_coalesce_timer.setSingleShot(True)
        self._pointer_coalesce_timer.setInterval(0)
        self._pointer_coalesce_timer.timeout.connect(self._consume_latest_pointer_sample)

    @property
    def overlay(self) -> ViewportFeedbackSurface:
        return self._overlay

    @property
    def pointer_coalesce_timer(self) -> QTimer:
        return self._pointer_coalesce_timer

    @property
    def latest_pointer_sample(self) -> PointerSample | None:
        return self._latest_pointer_sample

    @latest_pointer_sample.setter
    def latest_pointer_sample(self, value: PointerSample | None) -> None:
        self._latest_pointer_sample = value

    @property
    def last_pointer_sample(self) -> PointerSample | None:
        return self._last_pointer_sample

    @last_pointer_sample.setter
    def last_pointer_sample(self, value: PointerSample | None) -> None:
        self._last_pointer_sample = value

    @property
    def gesture_presenting(self) -> bool:
        return self._gesture_presenting

    @gesture_presenting.setter
    def gesture_presenting(self, value: bool) -> None:
        self._gesture_presenting = bool(value)

    @property
    def planner_calls(self) -> int:
        return int(self._diag_planner_calls)

    @property
    def frame_presents(self) -> int:
        return int(self._diag_frame_presents)

    @property
    def generation(self) -> int:
        return int(self._feedback_generation)

    def bind_surface(self, board: QWidget, viewport: QWidget) -> None:
        self._overlay.bind_transform_host(board, viewport)

    def ingest_pointer_sample(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> None:
        sample = _pointer_sample_tuple(
            board_pos, keep_aspect=keep_aspect, global_pos=global_pos
        )
        self._latest_pointer_sample = sample
        self._last_pointer_sample = sample
        if global_pos is not None and self._host.is_workspace_gesture_active():
            self._host.emit_workspace_pointer(QPoint(global_pos))
        session = self._host.gesture().session()
        if session is None or not session.active:
            # Crossing the drag threshold must paint this frame. Later
            # pointer events overwrite latest_sample and wait for the 0 ms
            # coalescer so one display frame consumes one sample.
            self.flush_pointer_sample()
            return
        if self._gesture_presenting:
            self._schedule_pointer_coalesce()
            return
        self._schedule_pointer_coalesce()

    def queue_pointer_sample(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> None:
        sample = _pointer_sample_tuple(
            board_pos, keep_aspect=keep_aspect, global_pos=global_pos
        )
        self._latest_pointer_sample = sample
        self._last_pointer_sample = sample
        self._schedule_pointer_coalesce()

    def _schedule_pointer_coalesce(self) -> None:
        timer = self._pointer_coalesce_timer
        try:
            if sip.isdeleted(timer):
                return
            if not timer.isActive():
                timer.start()
        except RuntimeError:
            return

    def stop_coalesce(self, *, drop: bool) -> None:
        timer = self._pointer_coalesce_timer
        try:
            if not sip.isdeleted(timer):
                timer.stop()
        except RuntimeError:
            pass
        if drop:
            self._latest_pointer_sample = None

    def flush_pointer_sample(self) -> None:
        self.stop_coalesce(drop=False)
        self._consume_latest_pointer_sample()

    def reproject_live_preview(self) -> None:
        """Re-draw the current sample after zoom/origin/overlay size changes."""
        if not self._host.gesture().is_active():
            return
        sample = self._latest_pointer_sample or self._last_pointer_sample
        if sample is None:
            return
        self._latest_pointer_sample = sample
        if self._gesture_presenting:
            self._schedule_pointer_coalesce()
            return
        self.flush_pointer_sample()

    def invalidate_candidate_fingerprint(self) -> None:
        self._last_consumed_candidate_fingerprint = None

    def reset_pointer_state(self) -> None:
        self._last_pointer_sample = None
        self._last_consumed_candidate_fingerprint = None
        self._last_legal_ghosts = ()
        self._last_legal_highlights = ()

    def clear_displayed_frame(self, gesture_id: int | None = None) -> None:
        self._overlay.clear(gesture_id)

    def _consume_latest_pointer_sample(self) -> None:
        try:
            if self._host.host_is_deleted():
                self._latest_pointer_sample = None
                return
        except RuntimeError:
            self._latest_pointer_sample = None
            return
        sample = self._latest_pointer_sample
        self._latest_pointer_sample = None
        if sample is None:
            return
        board_pos, keep_aspect, global_pos = sample
        self._update_gesture_at(
            board_pos, keep_aspect=keep_aspect, global_pos=global_pos
        )

    def _update_gesture_at(
        self,
        board_pos: tuple[int, int],
        *,
        keep_aspect: bool = False,
        global_pos: QPoint | None = None,
    ) -> None:
        if self._gesture_presenting:
            self._latest_pointer_sample = _pointer_sample_tuple(
                board_pos, keep_aspect=keep_aspect, global_pos=global_pos
            )
            self._last_pointer_sample = self._latest_pointer_sample
            self._schedule_pointer_coalesce()
            return
        gesture = self._host.gesture()
        session = gesture.update(
            board_pos,
            self._host.metrics(),
            self._host.current_placements(),
            QApplication.startDragDistance(),
            keep_aspect=keep_aspect,
        )
        if session is None or not session.active:
            return
        fingerprint = gesture.candidate_fingerprint()
        if not session.plan_reused:
            self._diag_planner_calls += 1
        if (
            session.plan_reused
            and fingerprint is not None
            and fingerprint == self._last_consumed_candidate_fingerprint
            and self._overlay.is_showing()
        ):
            if global_pos is not None:
                self._host.emit_workspace_gesture(True, global_pos)
            return
        self._gesture_presenting = True
        try:
            self._present_live_gesture(session, board_pos, global_pos)
            self._last_consumed_candidate_fingerprint = fingerprint
        finally:
            self._gesture_presenting = False
            if self._latest_pointer_sample is not None:
                self._schedule_pointer_coalesce()

    def _present_live_gesture(
        self,
        session,
        board_pos: tuple[int, int],
        global_pos: QPoint | None,
    ) -> None:
        host = self._host
        host.grab_mouse_for_feedback()
        first_live = not host.is_live_feedback_dimmed()
        if first_live:
            host.note_live_feedback_started()
            # Extent/edge-pan refresh must land as a pending sample, not a
            # dropped re-entrant present of the pre-origin coordinates.
            host.emit_workspace_gesture(True, global_pos)
        members = session.group_origins or {session.ref: session.origin}
        refs = list(session.preview_refs())
        for ref in refs:
            host.ghost_source_for(ref)
        ghosts = []
        ghost_rects = tuple(
            host.workspace_pixel_rect(rect)
            for rect in session.group_ghost_pixels(host.metrics(), board_pos)
        )
        if len(ghost_rects) != len(refs):
            refs = [session.ref]
            ghost_rects = (
                host.workspace_pixel_rect(
                    session.ghost_pixels(host.metrics(), board_pos)
                ),
            )
        mover_refs = set(members)
        displaced_count = 0
        safety = host.session_hits_safety(session)
        for ref, ghost in zip(refs, ghost_rects):
            image = host.ghost_source_for(ref)
            if session.legal:
                if ref in mover_refs:
                    role = PREVIEW_MOVER_VALID
                else:
                    role = PREVIEW_DISPLACED_WARNING
                    displaced_count += 1
            elif safety:
                role = PREVIEW_SAFETY_WALL
            else:
                role = PREVIEW_COLLISION_REJECT
            ghosts.append((image, ghost, role))
        highlights = tuple(
            host.workspace_pixel_rect(rect)
            for rect in session.group_highlight_pixels(host.metrics())
        )
        origin_masks = []
        involved = set(mover_refs)
        if session.plan is not None:
            involved.update(ref for ref, _rect in session.plan.preview_rects())
        for ref in involved:
            card = host.card_for(ref.section, ref.view_id)
            if card is None:
                continue
            geom = card.geometry()
            origin_masks.append((geom.x(), geom.y(), geom.width(), geom.height()))
        if session.legal:
            self._last_legal_ghosts = tuple(ghosts)
            self._last_legal_highlights = highlights
        elif safety:
            # Only the mover leaving the safety wall keeps the last legal
            # ghost. A neighbour that cannot be pushed is a collision reject
            # and must keep the attempted red outline.
            ghosts, highlights = self._last_legal_preview(ghosts, highlights)
            displaced_count = sum(
                1
                for item in ghosts
                if len(item) > 2 and item[2] == PREVIEW_DISPLACED_WARNING
            )
        displace_copy = (
            format_displace_preview(displaced_count) if displaced_count else ""
        )
        self._feedback_generation += 1
        self._diag_frame_presents += 1
        host.sync_editor_exclusion()
        self._overlay.set_move_previews(
            ghosts,
            highlights,
            legal=session.legal,
            badge=session.badge(),
            handles=session.handle is not None,
            safety_wall=safety,
            safety_bounds=host.safety_bounds_pixel_rect() if safety else None,
            safety_sides=host.safety_sides_for(session.candidate) if safety else (),
            origin_masks=origin_masks,
            displace_copy=displace_copy,
            gesture_id=int(host.gesture().gesture_id() or 0),
            generation=self._feedback_generation,
            layout_revision=int(session.layout_revision),
            operation="resize" if session.handle is not None else "move",
            candidate_fingerprint=(
                host.workspace_origin_offset(),
                float(host.current_zoom()),
                host.gesture().candidate_fingerprint(),
            ),
        )
        host.apply_safety_cursor(safety)
        if not first_live:
            host.emit_workspace_gesture(True, global_pos)

    def _last_legal_preview(self, ghosts, highlights):
        if self._last_legal_highlights:
            return self._last_legal_ghosts, self._last_legal_highlights
        return ghosts, highlights
