import pytest

from tests.ui.test_view_switch_integration import (
    _assert_pair,
    _checked_pairs,
    _fid,
    _make_loaded_window,
    _narrow_xlim,
    _set_channel_xaxis,
    _set_checked,
    _set_distinct_ylims,
    _set_range,
    _set_ticks,
)


def _line_names(canvas):
    return list(getattr(canvas, "_channel_lines", {}) or {})


def _has_channel(canvas, channel):
    return any(channel in name for name in _line_names(canvas))


def _assert_canvas_ylims(canvas, expected):
    actual = canvas.get_visible_ylims()
    assert set(actual) == set(expected)
    for key, pair in expected.items():
        assert actual[key] == pytest.approx(pair)


def _make_speed_vs_torque_views(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)

    _set_checked(w, "speed")
    w.chart_stack.set_plot_mode("overlay")
    w.chart_stack.set_cursor_mode("single")
    w.inspector.top.set_xaxis_mode("time")
    w.inspector.top.edit_xlabel.setText("Elapsed")
    w._custom_xaxis_fid = None
    w._custom_xaxis_ch = None
    w._custom_xlabel = "Elapsed"
    _set_ticks(w, 8, 5)
    w.plot_time()
    view1_xlim = _narrow_xlim(w, 0.20, 0.62)
    _set_range(w, True, 0.10, 0.90)
    view1_ylims = _set_distinct_ylims(w, 0.10)
    w._capture_current_view()

    w._on_view_new()
    qapp.processEvents()

    _set_checked(w, "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.chart_stack.set_cursor_mode("dual")
    _set_channel_xaxis(w, fid, "speed", "Speed Axis")
    _set_ticks(w, 13, 7)
    w.plot_time()
    view2_xlim = _narrow_xlim(w, 0.10, 0.55)
    _set_range(w, True, 0.20, 0.80)
    view2_ylims = _set_distinct_ylims(w, 0.18)
    w._capture_current_view()

    w._switch_view(0)
    qapp.processEvents()

    return w, fid, view1_xlim, view1_ylims, view2_xlim, view2_ylims


def test_directional_merge_only_host_splits(
    qtbot, qapp, loaded_csv
):
    w, _fid_value, view1_xlim, view1_ylims, view2_xlim, view2_ylims = (
        _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    )

    assert w.view_manager.active == 0
    w.view_manager.set_split(1)
    qapp.processEvents()

    assert w.chart_stack.split_active() is True
    assert w.view_manager.split_with == 1
    assert _has_channel(w.canvas_time, "speed")
    assert _has_channel(w.chart_stack.secondary_canvas(), "torque")

    w._switch_view(1)
    qapp.processEvents()

    assert w.chart_stack.split_active() is False
    assert w.view_manager.active == 1
    assert w.view_manager.split_with is None
    assert _has_channel(w.canvas_time, "torque")
    assert not _has_channel(w.canvas_time, "speed")
    _assert_pair(w.canvas_time.get_visible_xlim(), view2_xlim)
    _assert_canvas_ylims(w.canvas_time, view2_ylims)

    w._switch_view(0)
    qapp.processEvents()

    assert w.chart_stack.split_active() is True
    assert w.view_manager.active == 0
    assert w.view_manager.split_with == 1
    assert _has_channel(w.canvas_time, "speed")
    assert _has_channel(w.chart_stack.secondary_canvas(), "torque")
    _assert_pair(w.canvas_time.get_visible_xlim(), view1_xlim)
    _assert_canvas_ylims(w.canvas_time, view1_ylims)
    _assert_pair(w.chart_stack.secondary_canvas().get_visible_xlim(), view2_xlim)
    _assert_canvas_ylims(w.chart_stack.secondary_canvas(), view2_ylims)


def test_split_render_does_not_pollute_active_view_ui(qtbot, qapp, loaded_csv):
    w, fid, view1_xlim, view1_ylims, _view2_xlim, _view2_ylims = (
        _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    )

    w.view_manager.set_split(1)
    qapp.processEvents()

    assert w.chart_stack.split_active() is True
    assert w.view_manager.active == 0
    assert _checked_pairs(w) == [(fid, "speed")]
    assert w.chart_stack.plot_mode() == "overlay"
    assert w.chart_stack.cursor_mode() == "single"
    assert w.inspector.top.range_enabled() is True
    assert w.inspector.top.range_values() == pytest.approx((0.10, 0.90))
    assert w.inspector.top.xaxis_mode() == "time"
    assert w._custom_xaxis_fid is None
    assert w._custom_xaxis_ch is None
    assert w._custom_xlabel == "Elapsed"
    assert w.inspector.top.xaxis_label() == "Elapsed"
    assert w.inspector.top.tick_density() == (8, 5)
    assert _has_channel(w.canvas_time, "speed")
    assert not _has_channel(w.canvas_time, "torque")
    _assert_pair(w.canvas_time.get_visible_xlim(), view1_xlim)
    _assert_canvas_ylims(w.canvas_time, view1_ylims)


def test_split_render_preserves_active_cursor_pill(qtbot, qapp, loaded_csv):
    w, _fid_value, _v1_xlim, _v1_ylims, _v2_xlim, _v2_ylims = (
        _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    )
    w.view_manager.get(1).cursor_mode = "off"
    w.chart_stack.set_cursor_mode("single")
    w.chart_stack._pill.set_primary("A=1.0s")
    w.chart_stack._pill.setVisible(True)

    w.view_manager.set_split(1)
    qapp.processEvents()

    assert w.chart_stack.cursor_mode() == "single"
    assert w.chart_stack.cursor_pill_visible() is True
    assert w.chart_stack.cursor_pill_text() == "A=1.0s"


def test_secondary_pane_keeps_its_own_plot_mode_across_switches(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack

    # View 0 = speed/overlay, View 1 = torque/subplot.
    w.view_manager.get(0).plot_mode = "overlay"
    w.view_manager.get(1).plot_mode = "subplot"

    assert w.view_manager.active == 0
    w.view_manager.set_split(1)
    qapp.processEvents()

    # primary = View 0 (overlay), secondary = View 1 (subplot).
    assert cs.plot_mode_for_canvas(cs.canvas_time) == "overlay"
    assert cs.plot_mode_for_canvas(cs.secondary_canvas()) == "subplot"

    # Switch to View 1 (source): source opens as single pane with its layout.
    w._switch_view(1)
    qapp.processEvents()
    assert cs.split_active() is False
    assert cs.plot_mode_for_canvas(cs.canvas_time) == "subplot"

    # Switch back to View 0 (host): split returns and each pane keeps its layout.
    w._switch_view(0)
    qapp.processEvents()
    assert cs.split_active() is True
    assert cs.plot_mode_for_canvas(cs.canvas_time) == "overlay"
    assert cs.plot_mode_for_canvas(cs.secondary_canvas()) == "subplot"


def test_split_none_exits(qtbot, qapp, loaded_csv):
    w, _fid_value, _v1_xlim, _v1_ylims, _v2_xlim, _v2_ylims = (
        _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    )

    w.view_manager.set_split(1)
    qapp.processEvents()
    assert w.chart_stack.split_active() is True

    w.view_manager.set_split(None)
    qapp.processEvents()

    assert w.chart_stack.split_active() is False
