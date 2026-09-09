"""Capture/apply params between a section Contextual and AnalysisViewState.

Mirrors view_bridge.py's capture_view/apply_controls_from_state pattern
(spec §4). ``current_params()`` is the complete View-persistence surface when
a contextual provides it; older duck-typed contextuals still expose only
``get_params()`` / ``apply_params(d)``.
"""
from __future__ import annotations

import copy

from .view_overlay_state import (
    normalize_cursor_placement,
    normalize_remarks,
)


def _copy_preset_baseline(value):
    return copy.deepcopy(value) if isinstance(value, dict) else None


def _preset_bar(ctx):
    bar = getattr(ctx, "preset_bar", None)
    return bar if bar is not None and hasattr(bar, "baseline") else None


def _read_preset_baseline(ctx):
    bar = _preset_bar(ctx)
    if bar is not None:
        return bar.baseline()
    return getattr(ctx, "preset_baseline", None)


def _write_preset_baseline(ctx, baseline) -> None:
    bar = _preset_bar(ctx)
    if bar is not None and hasattr(bar, "set_baseline"):
        bar.set_baseline(baseline)
        return
    ctx.preset_baseline = baseline


def capture_params_to_state(ctx, state) -> None:
    current_params = getattr(ctx, "current_params", None)
    params_getter = current_params if callable(current_params) else ctx.get_params
    state.params = dict(params_getter())
    state.preset_baseline = _copy_preset_baseline(_read_preset_baseline(ctx))


def apply_params_from_state(ctx, state) -> None:
    stored = _copy_preset_baseline(getattr(state, "preset_baseline", None))
    bar = _preset_bar(ctx)
    if state.params:
        if bar is not None:
            bar.set_baseline(stored)
        else:
            ctx.preset_baseline = stored
        ctx.apply_params(dict(state.params))
        if stored is None and bar is not None:
            inferred = bar.infer_baseline_from_current()
            if inferred is not None:
                bar.set_baseline(inferred)
        return
    # Empty params mean a blank View: restore contextual defaults instead of
    # leaving the previous View's live controls in place. Construction
    # defaults that happen to equal a builtin still must not claim a baseline.
    reset = getattr(ctx, "reset_to_defaults", None)
    if callable(reset):
        reset()
    _write_preset_baseline(ctx, None)


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
