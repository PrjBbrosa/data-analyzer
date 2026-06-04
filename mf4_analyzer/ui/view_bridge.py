"""Bridge between time-domain ViewState data and live UI widgets.

This module is intentionally the only place that knows how to collect and
write back view-tab screen state across MainWindow, FileNavigator, ChartStack,
Inspector, and the time-domain canvas. Replotting is left to MainWindow.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable

from .view_state import ChannelKey, ViewState


def capture_axis_opts(window) -> dict[str, Any]:
    """Capture inspector-driven axis/display options for a time-domain view."""
    top = window.inspector.top
    range_start, range_end = top.range_values()
    tick_x, tick_y = top.tick_density()
    custom_fid = getattr(window, "_custom_xaxis_fid", None)
    custom_ch = getattr(window, "_custom_xaxis_ch", None)
    custom_active = custom_fid is not None and custom_ch is not None
    label = getattr(window, "_custom_xlabel", None) or top.xaxis_label()
    if not label:
        label = str(custom_ch) if custom_active else "Time (s)"

    return {
        "range_filter": {
            "enabled": bool(top.range_enabled()),
            "start": float(range_start),
            "end": float(range_end),
        },
        "x_axis": {
            "mode": "channel" if custom_active else "time",
            "fid": custom_fid,
            "channel": custom_ch,
            "label": label,
        },
        "tick_density": {"x": int(tick_x), "y": int(tick_y)},
    }


def capture_view(window) -> ViewState:
    """Aggregate the current interactive time-domain screen state."""
    navigator = window.navigator
    chart_stack = window.chart_stack
    canvas = chart_stack.canvas_time

    checked_rows = list(navigator.get_checked_channels())
    checked = [_channel_key(row) for row in checked_rows]
    colors = _capture_colors(navigator, checked_rows)

    return ViewState(
        name="",
        tab_color="",
        checked=checked,
        colors=colors,
        plot_mode=chart_stack.plot_mode(),
        cursor_mode=chart_stack.cursor_mode(),
        xlim=canvas.get_visible_xlim(),
        ylims=canvas.get_visible_ylims(),
        overlay_primary=getattr(window, "_overlay_primary", None),
        axis_opts=capture_axis_opts(window),
    )


def capture_into(state: ViewState, window) -> None:
    """Update an existing state from the UI while preserving tab metadata."""
    fresh = capture_view(window)
    state.checked = fresh.checked
    state.colors = fresh.colors
    state.plot_mode = fresh.plot_mode
    state.cursor_mode = fresh.cursor_mode
    state.xlim = fresh.xlim
    state.ylims = fresh.ylims
    state.overlay_primary = fresh.overlay_primary
    state.axis_opts = fresh.axis_opts


def apply_view(state: ViewState, window) -> None:
    """Write view state back to widgets without triggering a replot."""
    navigator = window.navigator
    chart_stack = window.chart_stack

    with _signals_blocked(navigator), _signals_blocked(chart_stack):
        navigator.set_channel_colors(state.colors)
        navigator.set_checked_channels(state.checked)
        chart_stack.set_plot_mode(state.plot_mode)
        chart_stack.set_cursor_mode(state.cursor_mode)

    _sync_canvas_cursor_mode(window, state.cursor_mode)
    window._overlay_primary = state.overlay_primary
    restore_axis_opts = getattr(window, "_restore_view_axis_opts", None)
    if callable(restore_axis_opts):
        restore_axis_opts(state.axis_opts)


def restore_axes(state: ViewState, window) -> None:
    """Restore post-replot visible ranges through canvas contract methods."""
    canvas = window.chart_stack.canvas_time
    canvas.restore_visible_xlim(state.xlim)
    canvas.restore_visible_ylims(state.ylims)


def _capture_colors(navigator, checked_rows: Iterable[Any]) -> dict[ChannelKey, str]:
    checked_keys = {_channel_key(row) for row in checked_rows}
    getter = getattr(navigator, "get_channel_colors", None)
    if callable(getter):
        colors = {_channel_key(key): color for key, color in getter().items()}
        return {key: color for key, color in colors.items() if key in checked_keys}

    colors: dict[ChannelKey, str] = {}
    for row in checked_rows:
        try:
            fid, channel, color = row[:3]
        except (TypeError, ValueError):
            continue
        colors[(str(fid), str(channel))] = color
    return colors


def _channel_key(value: Any) -> ChannelKey:
    fid, channel = value[:2]
    return (str(fid), str(channel))


def _sync_canvas_cursor_mode(window, mode: str) -> None:
    handler = getattr(window, "_on_cursor_mode_changed", None)
    if callable(handler):
        handler(mode)
        return

    canvas = getattr(window.chart_stack, "canvas_time", None)
    set_visible = getattr(canvas, "set_cursor_visible", None)
    if callable(set_visible):
        set_visible(mode != "off")
    set_dual = getattr(canvas, "set_dual_cursor_mode", None)
    if callable(set_dual):
        set_dual(mode == "dual")


@contextmanager
def _signals_blocked(widget):
    blocker = getattr(widget, "blockSignals", None)
    if not callable(blocker):
        yield
        return

    old = blocker(True)
    try:
        yield
    finally:
        blocker(old)
