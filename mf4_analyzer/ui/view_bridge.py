"""Bridge between time-domain ViewState data and live UI widgets.

This module is intentionally the only place that knows how to collect and
write back view-tab screen state across MainWindow, FileNavigator, ChartStack,
Inspector, and the time-domain canvas. Replotting is left to MainWindow.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from typing import Any, Iterable

from .time_xaxis import CustomXAxisSpec, CHANNEL_MODE, EXACT_SOURCE
from .view_state import ChannelKey, ViewState


def capture_axis_opts(window) -> dict[str, Any]:
    """Capture inspector-driven axis/display options for a time-domain view."""
    top = window.inspector.top
    range_start, range_end = top.range_values()
    tick_x, tick_y = top.tick_density()
    xaxis_spec = getattr(window, "_custom_xaxis_spec", None)
    if not isinstance(xaxis_spec, CustomXAxisSpec):
        custom_fid = getattr(window, "_custom_xaxis_fid", None)
        custom_ch = getattr(window, "_custom_xaxis_ch", None)
        if custom_fid is not None and custom_ch is not None:
            xaxis_spec = CustomXAxisSpec(
                mode=CHANNEL_MODE,
                resolver=EXACT_SOURCE,
                source_fid=str(custom_fid),
                channel=str(custom_ch),
            )
        else:
            xaxis_spec = CustomXAxisSpec()

    label = getattr(window, "_custom_xlabel", None)
    if label is None:
        if xaxis_spec.mode == CHANNEL_MODE:
            # The combo/label widgets are drafts until Apply.  A channel spec
            # is the applied truth, so never capture an un-applied edit here.
            label = xaxis_spec.label
        else:
            label = xaxis_spec.label or top.xaxis_label()
    if not label and xaxis_spec.channel:
        label = str(xaxis_spec.channel)
    xaxis_spec = replace(xaxis_spec, label=str(label or ""))

    return {
        "range_filter": {
            "enabled": bool(top.range_enabled()),
            "start": float(range_start),
            "end": float(range_end),
        },
        "x_axis": xaxis_spec.to_axis_opts(),
        "tick_density": {"x": int(tick_x), "y": int(tick_y)},
    }


def capture_view(window) -> ViewState:
    """Aggregate the current interactive time-domain screen state."""
    navigator = window.navigator
    chart_stack = window.chart_stack
    canvas = chart_stack.canvas_time

    checked_rows = list(navigator.get_checked_channels())
    checked = [_channel_key(row) for row in checked_rows]
    hidden_channels = [
        _channel_key(row) for row in navigator.get_hidden_channels()
    ]
    colors = _capture_colors(navigator, checked_rows)

    return ViewState(
        name="",
        tab_color="",
        attached_file_ids=list(navigator.get_attached_file_ids()),
        checked=checked,
        hidden_channels=hidden_channels,
        colors=colors,
        plot_mode=chart_stack.plot_mode(),
        cursor_mode=chart_stack.cursor_mode(),
        xlim=canvas.get_visible_xlim(),
        ylims=canvas.get_visible_ylims(),
        overlay_primary=getattr(window, "_overlay_primary", None),
        axis_opts=capture_axis_opts(window),
    )


def capture_controls_into(state: ViewState, window, canvas=None) -> None:
    """Capture widget/control state into ``state`` for the given time pane."""
    fresh = capture_view(window)
    state.attached_file_ids = fresh.attached_file_ids
    state.checked = fresh.checked
    state.hidden_channels = fresh.hidden_channels
    state.colors = fresh.colors
    state.overlay_primary = fresh.overlay_primary
    state.axis_opts = fresh.axis_opts

    chart_stack = window.chart_stack
    target = canvas if canvas is not None else chart_stack.canvas_time
    plot_for_canvas = getattr(chart_stack, "plot_mode_for_canvas", None)
    if callable(plot_for_canvas):
        state.plot_mode = plot_for_canvas(target)
    else:
        state.plot_mode = chart_stack.plot_mode()
    cursor_for_canvas = getattr(chart_stack, "cursor_mode_for_canvas", None)
    if callable(cursor_for_canvas):
        state.cursor_mode = cursor_for_canvas(target)
    else:
        state.cursor_mode = chart_stack.cursor_mode()


def capture_canvas_ranges_into(state: ViewState, canvas) -> None:
    """Capture live visible X/Y ranges from a specific canvas into ``state``.

    A TimeDomain canvas that explicitly has no primary axis is in an owner
    empty state, not a new ``(0, 1)`` viewport. Keep its prior semantic ranges
    for the next non-empty render. Generic canvases without this attribute
    retain the historical capture behavior.
    """
    if hasattr(canvas, "_primary_xaxis_ax") and canvas._primary_xaxis_ax is None:
        return
    get_xlim = getattr(canvas, "get_visible_xlim", None)
    get_ylims = getattr(canvas, "get_visible_ylims", None)
    if callable(get_xlim):
        state.xlim = get_xlim()
    if callable(get_ylims):
        current_ylims = get_ylims()
        retained_hidden = {
            key: ylim
            for key, ylim in (state.ylims or {}).items()
            if _ylim_key_belongs_to_hidden(key, state.hidden_channels)
        }
        retained_hidden.update(current_ylims)
        state.ylims = retained_hidden


def capture_into(state: ViewState, window) -> None:
    """Update an existing state from the UI while preserving tab metadata."""
    canvas = window.chart_stack.canvas_time
    capture_controls_into(state, window, canvas)
    capture_canvas_ranges_into(state, canvas)


def apply_controls_from_state(state: ViewState, window, canvas=None) -> None:
    """Write control state to widgets/card owning ``canvas`` without replotting."""
    navigator = window.navigator
    chart_stack = window.chart_stack
    target = canvas if canvas is not None else chart_stack.canvas_time

    with _signals_blocked(navigator), _signals_blocked(chart_stack):
        navigator.set_attached_file_ids(state.attached_file_ids)
        navigator.set_channel_colors(state.colors)
        navigator.set_checked_channels(state.checked)
        navigator.set_hidden_channels(state.hidden_channels)
        plot_setter = getattr(chart_stack, "set_plot_mode_for_canvas", None)
        cursor_setter = getattr(chart_stack, "set_cursor_mode_for_canvas", None)
        if callable(plot_setter):
            plot_setter(target, state.plot_mode)
        else:
            chart_stack.set_plot_mode(state.plot_mode)
        if callable(cursor_setter):
            cursor_setter(target, state.cursor_mode)
        else:
            chart_stack.set_cursor_mode(state.cursor_mode)
            _apply_cursor_to_canvas(target, state.cursor_mode)

    window._overlay_primary = state.overlay_primary
    restore_axis_opts = getattr(window, "_restore_view_axis_opts", None)
    if callable(restore_axis_opts):
        restore_axis_opts(state.axis_opts)


def apply_view(state: ViewState, window) -> None:
    """Write view state back to primary widgets without triggering a replot."""
    apply_controls_from_state(state, window, window.chart_stack.canvas_time)


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


def _ylim_key_belongs_to_hidden(key: Any, hidden: Iterable[ChannelKey]) -> bool:
    """Match a canvas ViewState Y key to a hidden raw channel key."""
    data_id = None
    display_name = None
    try:
        decoded = json.loads(str(key))
        if isinstance(decoded, list) and len(decoded) >= 2:
            data_id, display_name = decoded[:2]
    except (TypeError, ValueError, json.JSONDecodeError):
        text = str(key)
        if "::" in text:
            data_id, display_name = text.split("::", 1)
    if data_id is None or display_name is None:
        return False

    data_id = str(data_id)
    display_name = str(display_name)
    for fid, channel in hidden:
        channel = str(channel)
        if data_id != str(fid):
            continue
        if display_name == channel or display_name.endswith(f"] {channel}"):
            return True
    return False


def _apply_cursor_to_canvas(canvas, mode: str) -> None:
    visible_setter = getattr(canvas, "set_cursor_visible", None)
    dual_setter = getattr(canvas, "set_dual_cursor_mode", None)
    if callable(visible_setter):
        visible_setter(mode != "off")
    if callable(dual_setter):
        dual_setter(mode == "dual")


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
