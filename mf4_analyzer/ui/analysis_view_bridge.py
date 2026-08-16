"""Capture/apply params between a section Contextual and AnalysisViewState.

Mirrors view_bridge.py's capture_view/apply_controls_from_state pattern
(spec §4). ``current_params()`` is the complete View-persistence surface when
a contextual provides it; older duck-typed contextuals still expose only
``get_params()`` / ``apply_params(d)``.
"""
from __future__ import annotations

from .view_overlay_state import (
    normalize_cursor_placement,
    normalize_remarks,
)


def capture_params_to_state(ctx, state) -> None:
    current_params = getattr(ctx, "current_params", None)
    params_getter = current_params if callable(current_params) else ctx.get_params
    state.params = dict(params_getter())


def apply_params_from_state(ctx, state) -> None:
    if state.params:
        ctx.apply_params(dict(state.params))
        return
    # Empty params mean a blank View: restore contextual defaults instead of
    # leaving the previous View's live controls in place.
    reset = getattr(ctx, "reset_to_defaults", None)
    if callable(reset):
        reset()


def capture_overlay_from_canvas(canvas, pane) -> None:
    """Write live analysis remarks / frequency placement onto one pane."""
    snapshot = getattr(canvas, "snapshot_remarks", None)
    if callable(snapshot):
        pane.remarks = normalize_remarks(snapshot())
    placement = getattr(canvas, "snapshot_cursor_placement", None)
    if callable(placement):
        pane.cursor_placement = normalize_cursor_placement(
            placement(), cursor_mode=getattr(pane, "cursor_mode", "off"),
        )


def apply_overlay_to_canvas(canvas, pane) -> None:
    """Replace canvas overlay intent from the pane. Plot closeout projects."""
    restore = getattr(canvas, "restore_remarks", None)
    if callable(restore):
        restore(getattr(pane, "remarks", None) or [])
    restore_placement = getattr(canvas, "restore_cursor_placement", None)
    if callable(restore_placement):
        restore_placement(getattr(pane, "cursor_placement", None))
