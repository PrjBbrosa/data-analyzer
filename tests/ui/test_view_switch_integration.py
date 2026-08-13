import pytest

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec
from mf4_analyzer.ui.view_tabbar import ViewTabBar


def _assert_subplot_materially_fills_viewport(canvas, expected_rows):
    assert len(canvas.axes_list) == expected_rows
    viewport = canvas._glw.viewport().rect()
    rects = [handle.view_box.sceneBoundingRect() for handle in canvas.axes_list]
    assert all(
        rect.width() >= max(1.0, viewport.width() * 0.25)
        for rect in rects
    )
    assert all(
        rect.height() >= max(1.0, viewport.height() * 0.10 / expected_rows)
        for rect in rects
    )
    combined_height = max(rect.bottom() for rect in rects) - min(
        rect.top() for rect in rects
    )
    assert combined_height >= max(1.0, viewport.height() * 0.25)


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
    idx = next(
        i for i in range(combo.count())
        if combo.itemData(i) == ("per_source_name", None, channel)
    )
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


def test_subplot_empty_view_round_trip_rebuilds_full_canvas_geometry(
    qtbot, qapp, loaded_csv,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    w.chart_stack.set_plot_mode("subplot")
    _set_checked(w, "speed", "torque")
    w.plot_time()
    qapp.processEvents()
    _assert_subplot_materially_fills_viewport(w.canvas_time, 2)
    old_view_boxes = [handle.view_box for handle in w.canvas_time.axes_list]
    outer_size = w.size()
    saved_xlim = _narrow_xlim(w, 0.20, 0.65)
    w._capture_current_view()

    w._on_view_new()
    qapp.processEvents()

    assert w.size() == outer_size
    assert w.canvas_time.axes_list == []
    assert w.canvas_time._selection_bound_keys == set()
    assert w.canvas_time._subplot_retained_order == []

    w._switch_view(0)
    qapp.processEvents()

    assert w.size() == outer_size
    assert w.canvas_time._last_full_rebuild_reason == "no-render-model"
    assert all(
        all(handle.view_box is not old for old in old_view_boxes)
        for handle in w.canvas_time.axes_list
    )
    assert w.canvas_time.get_visible_xlim() == pytest.approx(saved_xlim)
    _assert_subplot_materially_fills_viewport(w.canvas_time, 2)


def test_main_window_mounts_view_tabbar(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)

    assert w.view_manager is not None
    assert isinstance(w.view_tabbar, ViewTabBar)
    assert w.view_tabbar is w.chart_stack._view_tabbar
    assert w.chart_stack._time_card.view_tabbar is None
    rail = w.chart_stack.findChild(type(w.chart_stack._time_bottom_dock), "timeViewRail")
    assert w.view_tabbar.parentWidget() is rail
    assert rail.parentWidget() is w.chart_stack._time_bottom_dock

    layout = w.chart_stack._time_bottom_dock.layout()
    assert layout.indexOf(rail) >= 0
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
    w._attach_files_to_focused_view([fid])

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
    w._custom_xaxis_spec = CustomXAxisSpec(label="Elapsed")
    w._custom_xlabel = "Elapsed"
    _set_ticks(w, 8, 5)
    view1_xlim = _narrow_xlim(w, 0.20, 0.62)
    _set_range(w, True, 0.10, 0.90)
    view1_ylims = _set_distinct_ylims(w, 0.12)
    w._capture_current_view()

    w._on_view_new()
    qapp.processEvents()
    w._attach_files_to_focused_view([fid])

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
    assert w._custom_xaxis_fid is None
    assert w._custom_xaxis_ch is None
    assert w._custom_xaxis_spec == CustomXAxisSpec(
        mode="channel",
        resolver="per_source_name",
        source_fid=None,
        channel="speed",
        label="Speed Axis",
    )
    assert w._custom_xlabel == "Speed Axis"
    assert w.inspector.top._combo_xaxis_ch.currentData() == (
        "per_source_name", None, "speed"
    )
    assert w.inspector.top.xaxis_label() == "Speed Axis"
    assert w.inspector.top.tick_density() == (13, 7)
    _assert_pair(w.canvas_time.get_visible_xlim(), view2_xlim)
    _assert_ylims(w, view2_ylims)


def test_range_capture_preserves_applied_xaxis_when_combo_has_unapplied_draft(
    qtbot, qapp, loaded_csv,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    _set_channel_xaxis(w, fid, "speed", "Speed Axis")
    state = w.view_manager.get(0)
    w._capture_current_view()
    applied = dict(state.axis_opts["x_axis"])

    combo = w.inspector.top._combo_xaxis_ch
    draft_idx = next(
        i for i in range(combo.count())
        if combo.itemData(i) == ("per_source_name", None, "torque")
    )
    combo.setCurrentIndex(draft_idx)
    assert w.inspector.top.xaxis_label() == "torque"

    w._capture_range_change_into_view(state, w.canvas_time)

    assert state.axis_opts["x_axis"] == applied
    assert state.axis_opts["x_axis"]["channel"] == "speed"
    assert w._custom_xaxis_spec.channel == "speed"


def test_restore_unknown_xaxis_resolver_degrades_to_time(
    qtbot, qapp, loaded_csv,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)

    w._restore_view_axis_opts({
        "x_axis": {
            "mode": "channel",
            "resolver": "future_resolver",
            "fid": fid,
            "channel": "speed",
            "label": "Saved label",
        }
    })

    assert w._custom_xaxis_spec == CustomXAxisSpec(label="Saved label")
    assert w.inspector.top.xaxis_mode() == "time"
    assert not w.inspector.top._combo_xaxis_ch.isEnabled()


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
    w._attach_files_to_focused_view([fid])
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


def test_delete_inactive_before_active_captures_current_view(
    qtbot, qapp, loaded_csv, monkeypatch
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    monkeypatch.setattr(w, "_confirm_view_delete", lambda *_a: True)

    _set_checked(w, "torque")
    w.plot_time()
    w._capture_current_view()

    w._on_view_new()
    qapp.processEvents()
    w._attach_files_to_focused_view([fid])
    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()

    w._on_view_delete(0)
    qapp.processEvents()

    assert len(w.view_manager.views) == 1
    assert w.view_manager.active == 0
    assert w.view_manager.get(0).checked == [(fid, "speed")]
    assert _checked_pairs(w) == [(fid, "speed")]


def test_delete_view_cancel_keeps_view(qtbot, qapp, loaded_csv, monkeypatch):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    prompts = []
    monkeypatch.setattr(
        w, "_confirm_view_delete", lambda name: prompts.append(name) or False
    )

    w._on_view_new()
    qapp.processEvents()
    assert len(w.view_manager.views) == 2
    target_name = w.view_manager.get(0).name

    w._on_view_delete(0)
    qapp.processEvents()

    # Cancelling the confirm keeps every view intact.
    assert prompts == [target_name]
    assert len(w.view_manager.views) == 2


def test_delete_view_confirm_copy_defaults_to_cancel(qtbot, qapp, loaded_csv):
    from PyQt5.QtWidgets import QMessageBox

    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    w._on_view_new()
    qapp.processEvents()

    boxes = []
    orig_exec = QMessageBox.exec_
    try:
        QMessageBox.exec_ = lambda box: boxes.append(box) or 0
        assert w._confirm_view_delete("视图 1") is False
    finally:
        QMessageBox.exec_ = orig_exec

    assert len(boxes) == 1
    box = boxes[0]
    # windowTitle() is intentionally not asserted: macOS renders QMessageBox as
    # a native alert and reads the title back as "" (same quirk the batch-cancel
    # test hits). Body text + buttons are reliable across platforms.
    assert "视图 1" in box.text()
    assert box.defaultButton().text() == "取消"
    labels = {b.text() for b in box.buttons()}
    assert {"删除", "取消"} <= labels
