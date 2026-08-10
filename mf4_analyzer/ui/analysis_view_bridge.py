"""Capture/apply params between a section Contextual and AnalysisViewState.

Mirrors view_bridge.py's capture_view/apply_controls_from_state pattern
(spec §4). All three analysis Contextuals expose get_params()/
apply_params(d); the bridge stays duck-typed so tests can stub them.
"""
from __future__ import annotations


def capture_params_to_state(ctx, state) -> None:
    state.params = dict(ctx.get_params())


def apply_params_from_state(ctx, state) -> None:
    if state.params:
        ctx.apply_params(dict(state.params))
        return
    # Empty params mean a blank View: restore contextual defaults instead of
    # leaving the previous View's live controls in place.
    reset = getattr(ctx, "reset_to_defaults", None)
    if callable(reset):
        reset()
