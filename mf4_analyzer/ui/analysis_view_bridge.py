"""Capture/apply params between a section Contextual and AnalysisViewState.

Mirrors view_bridge.py's capture_view/apply_controls_from_state pattern
(spec §4). ``current_params()`` is the complete View-persistence surface when
a contextual provides it; older duck-typed contextuals still expose only
``get_params()`` / ``apply_params(d)``.
"""
from __future__ import annotations


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
