import pytest

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.view_tabbar import ViewTabBar


def _make_loaded_window(qtbot, qapp, loaded_csv):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1400, 820)
    w.show()
    qtbot.waitExposed(w)
    w.load_file(loaded_csv)
    qapp.processEvents()
    return w


def _fid(w):
    return next(iter(w.files))


def _set_checked(w, *channels):
    fid = _fid(w)
    w.navigator.set_checked_channels([(fid, ch) for ch in channels])


def _checked_pairs(w):
    return [(fid, ch) for fid, ch, _color in w.navigator.get_checked_channels()]


def _set_channel_xaxis(w, fid, channel, label):
    top = w.inspector.top
    top.set_xaxis_mode("channel")
    w._on_xaxis_mode_changed("channel")
    combo = top._combo_xaxis_ch
    idx = next(i for i in range(combo.count()) if combo.itemData(i) == (fid, channel))
    combo.setCurrentIndex(idx)
    top.edit_xlabel.setText(label)
    w._apply_xaxis()


def _set_range(w, enabled, start, end):
    top = w.inspector.top
    top.chk_range.setChecked(enabled)
    top.set_range_values(start, end)


def _set_ticks(w, x, y):
    top = w.inspector.top
    top.spin_xt.setValue(x)
    top.spin_yt.setValue(y)


def _narrow_xlim(w, start_fraction, end_fraction):
    xlim = w.canvas_time.get_visible_xlim()
    assert xlim is not None
    lo, hi = xlim
    span = hi - lo
    target = (lo + span * start_fraction, lo + span * end_fraction)
    w.canvas_time.restore_visible_xlim(target)
    return target


def _set_distinct_ylims(w, shrink_fraction):
    current = w.canvas_time.get_visible_ylims()
    assert current
    out = {}
    for key, (lo, hi) in current.items():
        span = hi - lo
        if span <= 0:
            span = 1.0
        out[key] = (lo + span * shrink_fraction, hi - span * shrink_fraction)
    w.canvas_time.restore_visible_ylims(out)
    return out


def _assert_pair(actual, expected):
    assert actual == pytest.approx(expected)


def _assert_ylims(w, expected):
    actual = w.canvas_time.get_visible_ylims()
    assert set(actual) == set(expected)
    for key, pair in expected.items():
        assert actual[key] == pytest.approx(pair)


def test_main_window_mounts_view_tabbar(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)

    assert w.view_manager is not None
    assert isinstance(w.view_tabbar, ViewTabBar)
    assert w.view_tabbar is w.chart_stack._view_tabbar
    assert w.chart_stack._time_card.view_tabbar is None
    assert w.view_tabbar.parentWidget() is w.chart_stack._time_bottom_dock

    layout = w.chart_stack._time_bottom_dock.layout()
    assert layout.indexOf(w.view_tabbar) >= 0
    assert layout.indexOf(w.chart_stack._time_hint_bar) == -1
    assert w.chart_stack._time_hint_bar.parentWidget() is w.statusBar


def test_switch_view_preserves_per_view_channels(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)

    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()

    w._on_view_new()
    qapp.processEvents()

    _set_checked(w, "torque")
    w.plot_time()
    qapp.processEvents()

    w._switch_view(0)
    qapp.processEvents()
    assert _checked_pairs(w) == [(fid, "speed")]

    w._switch_view(1)
    qapp.processEvents()
    assert _checked_pairs(w) == [(fid, "torque")]


def test_switch_view_restores_screen_snapshot_state(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)

    _set_checked(w, "speed")
    w.plot_time()
    w.chart_stack.set_plot_mode("overlay")
    w.chart_stack.set_cursor_mode("single")
    w._overlay_primary = (fid, "speed")
    w.inspector.top.set_xaxis_mode("time")
    w.inspector.top.edit_xlabel.setText("Elapsed")
    w._custom_xaxis_fid = None
    w._custom_xaxis_ch = None
    w._custom_xlabel = "Elapsed"
    _set_ticks(w, 8, 5)
    view1_xlim = _narrow_xlim(w, 0.20, 0.62)
    _set_range(w, True, 0.10, 0.90)
    view1_ylims = _set_distinct_ylims(w, 0.12)
    w._capture_current_view()

    w._on_view_new()
    qapp.processEvents()

    _set_checked(w, "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.chart_stack.set_cursor_mode("dual")
    _set_channel_xaxis(w, fid, "speed", "Speed Axis")
    _set_range(w, True, 0.20, 0.80)
    _set_ticks(w, 13, 7)
    w.plot_time()
    view2_xlim = _narrow_xlim(w, 0.10, 0.55)
    view2_ylims = _set_distinct_ylims(w, 0.18)

    w._switch_view(0)
    qapp.processEvents()

    assert _checked_pairs(w) == [(fid, "speed")]
    assert w.chart_stack.plot_mode() == "overlay"
    assert w.chart_stack.cursor_mode() == "single"
    assert w._overlay_primary == (fid, "speed")
    assert w.inspector.top.range_enabled() is True
    assert w.inspector.top.range_values() == pytest.approx((0.10, 0.90))
    assert w.inspector.top.xaxis_mode() == "time"
    assert w._custom_xaxis_fid is None
    assert w._custom_xaxis_ch is None
    assert w._custom_xlabel == "Elapsed"
    assert w.inspector.top.xaxis_label() == "Elapsed"
    assert w.inspector.top.tick_density() == (8, 5)
    _assert_pair(w.canvas_time.get_visible_xlim(), view1_xlim)
    _assert_ylims(w, view1_ylims)

    w._switch_view(1)
    qapp.processEvents()

    assert _checked_pairs(w) == [(fid, "torque")]
    assert w.chart_stack.plot_mode() == "subplot"
    assert w.chart_stack.cursor_mode() == "dual"
    assert w._overlay_primary is None
    assert w.inspector.top.range_enabled() is True
    assert w.inspector.top.range_values() == pytest.approx((0.20, 0.80))
    assert w.inspector.top.xaxis_mode() == "channel"
    assert w._custom_xaxis_fid == fid
    assert w._custom_xaxis_ch == "speed"
    assert w._custom_xlabel == "Speed Axis"
    assert w.inspector.top._combo_xaxis_ch.currentData() == (fid, "speed")
    assert w.inspector.top.xaxis_label() == "Speed Axis"
    assert w.inspector.top.tick_density() == (13, 7)
    _assert_pair(w.canvas_time.get_visible_xlim(), view2_xlim)
    _assert_ylims(w, view2_ylims)


def test_bridge_can_capture_canvas_ranges_without_replacing_controls(
    qtbot, qapp, loaded_csv
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()

    state = w.view_manager.get(0)
    state.checked = [(fid, "speed")]
    target = _narrow_xlim(w, 0.25, 0.50)
    ylims = _set_distinct_ylims(w, 0.15)

    w._view_bridge.capture_canvas_ranges_into(state, w.canvas_time)

    assert state.checked == [(fid, "speed")]
    assert state.xlim == pytest.approx(target)
    assert set(state.ylims) == set(ylims)


def test_duplicate_current_view_captures_latest_state(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)

    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()

    assert w.view_manager.get(0).checked == []
    w._on_view_duplicate(0)
    qapp.processEvents()

    assert len(w.view_manager.views) == 2
    assert w.view_manager.active == 1
    assert w.view_manager.get(1).checked == [(fid, "speed")]
    assert _checked_pairs(w) == [(fid, "speed")]


def test_duplicate_inactive_before_active_captures_current_view(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)

    _set_checked(w, "torque")
    w.plot_time()
    w._capture_current_view()

    w._on_view_new()
    qapp.processEvents()
    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()

    w._on_view_duplicate(0)
    qapp.processEvents()

    assert len(w.view_manager.views) == 3
    assert w.view_manager.active == 1
    assert w.view_manager.get(1).checked == [(fid, "torque")]
    assert w.view_manager.get(2).checked == [(fid, "speed")]
    assert _checked_pairs(w) == [(fid, "torque")]


def test_delete_inactive_before_active_captures_current_view(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)

    _set_checked(w, "torque")
    w.plot_time()
    w._capture_current_view()

    w._on_view_new()
    qapp.processEvents()
    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()

    w._on_view_delete(0)
    qapp.processEvents()

    assert len(w.view_manager.views) == 1
    assert w.view_manager.active == 0
    assert w.view_manager.get(0).checked == [(fid, "speed")]
    assert _checked_pairs(w) == [(fid, "speed")]
