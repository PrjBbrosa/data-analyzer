"""Round-1 View isolation: co-axis, filter, and colors on the real UI path.

These cases drive ChannelTree + View bridge + MainWindow switch/split/save.
They must fail on the current session-shared bugs (V01/V02/V03) before the
owner changes land.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from mf4_analyzer.signal.filters import FilterSpec
from mf4_analyzer.ui import project_io as pio
from mf4_analyzer.ui import view_bridge
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.ultraview_state import UltraViewRef
from mf4_analyzer.ui.view_state import ViewState, is_reusable_blank_view
from mf4_analyzer.ui.widgets import MultiFileChannelWidget

from tests.ui.test_channel_axis_groups import _AxisCaptureTop
from tests.ui.test_channel_widget_setters import _FakeFileData
from tests.ui.test_ultraview_capture import _make_coord, _ref
from tests.ui.test_view_switch_integration import (
    _checked_pairs,
    _fid,
    _make_loaded_window,
    _set_checked,
)


def _flush(qapp, turns=4):
    for _ in range(turns):
        qapp.processEvents()


def _palette_color(window, fid, channel):
    fd = window.files[fid]
    palette = fd.get_color_palette()
    channels = list(fd.get_signal_channels())
    return palette[channels.index(channel) % len(palette)]


def _grouped_channels(window, fid):
    groups = {}
    for (file_id, channel), gid in window.channel_list.checked_axis_groups().items():
        if str(file_id) != str(fid):
            continue
        groups.setdefault(gid, set()).add(str(channel))
    return {frozenset(members) for members in groups.values()}


def _state_grouped_channels(state, fid):
    raw = (state.axis_opts or {}).get("channel_axis_groups") or {}
    groups = {}
    for raw_key, gid in raw.items():
        key = raw_key
        if isinstance(raw_key, str):
            try:
                key = json.loads(raw_key)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if not isinstance(key, (list, tuple)) or len(key) != 2:
            continue
        if str(key[0]) != str(fid):
            continue
        groups.setdefault(str(gid), set()).add(str(key[1]))
    return {frozenset(members) for members in groups.values()}


def _enable_lowpass(window, cutoff, *, order=4):
    panel = window.inspector.filter_panel
    panel.set_kind("低通")
    panel.set_cutoff(float(cutoff))
    panel.set_order(int(order))
    panel.set_enabled(True)
    return panel


def _filter_cutoff(window):
    return float(window.inspector.filter_panel.filter_spec().cutoff)


def _has_filtered_companion(canvas):
    return bool(getattr(canvas, "_companion_names", None))


def _subplot_rows(canvas):
    return len(getattr(canvas, "axes_list", []) or [])


def _new_attached_view(window, qapp, fid):
    window._on_view_new()
    _flush(qapp)
    window._attach_files_to_focused_view([fid])
    _flush(qapp)
    return window.view_manager.active


def _write_two_channel_csv(path, *, speed_amp=1000.0, torque_amp=50.0):
    import numpy as np

    t = np.linspace(0.0, 1.0, 400)
    pd.DataFrame({
        "time": t,
        "speed": speed_amp * np.sin(2 * np.pi * 5 * t),
        "torque": torque_amp + 5 * np.cos(2 * np.pi * 3 * t),
    }).to_csv(path, index=False)


def test_ordinary_merge_is_captured_from_real_channel_tree(qapp):
    tree = MultiFileChannelWidget()
    gid = tree.merge_axis_group([("f1", "speed"), ("f1", "torque")])
    assert gid is not None
    opts = view_bridge.capture_axis_opts(SimpleNamespace(
        inspector=SimpleNamespace(top=_AxisCaptureTop()),
        channel_list=tree,
    ))
    groups = opts.get("channel_axis_groups") or {}
    assert groups['["f1","speed"]'] == groups['["f1","torque"]']
    assert tree._axis_groups == {}


def test_capture_keeps_unchecked_color_overrides_from_real_tree(qapp):
    tree = MultiFileChannelWidget()
    tree.add_file("f1", _FakeFileData())
    tree.set_attached_file_ids(["f1"])
    tree.set_checked_channels([("f1", "rpm"), ("f1", "spd")])
    tree.set_channel_colors({("f1", "spd"): "#abcdef"})
    tree.set_checked_channels([("f1", "rpm")])

    colors = view_bridge._capture_colors(tree, tree.get_checked_channels())

    assert colors[("f1", "spd")] == "#abcdef"
    assert ("f1", "rpm") not in colors


def test_viewstate_owns_time_filter_and_blank_predicate():
    blank = ViewState(name="View 1", tab_color="#2d7ff9")
    assert hasattr(blank, "time_filter")
    payload = json.loads(json.dumps(blank.to_dict()))
    again = ViewState.from_dict(payload)
    assert again.time_filter["enabled"] is False
    assert is_reusable_blank_view(blank) is True

    edited = ViewState.from_dict(payload)
    edited.time_filter = {
        "enabled": True,
        "spec": FilterSpec("low", order=6, cutoff=50.0).to_dict(),
        "show_original": True,
        "show_filtered": True,
    }
    assert is_reusable_blank_view(edited) is False


def test_project_codec_is_schema_4_and_still_reads_legacy(tmp_path):
    assert pio.SCHEMA_VERSION == 4
    assert {1, 2, 3, 4} <= set(pio.SUPPORTED_SCHEMA_VERSIONS)

    legacy = tmp_path / "old.tlproj"
    legacy.write_text(json.dumps({
        "schema_version": 3,
        "active_file": None,
        "current_mode": "time",
        "files": [],
        "views": [{"name": "View 1", "tab_color": "#2d7ff9"}],
        "view_manager": {"active": 0, "split_pairs": {}},
        "filter": {
            "enabled": True,
            "spec": FilterSpec("low", order=4, cutoff=40.0).to_dict(),
            "show_original": False,
            "show_filtered": True,
        },
    }), encoding="utf-8")
    doc = pio.load_project_from_json(legacy)
    views = [ViewState.from_dict(row) for row in doc.views]
    assert views[0].time_filter["enabled"] is True
    assert views[0].time_filter["spec"]["cutoff"] == pytest.approx(40.0)


def test_ultraview_time_payload_reads_requested_view_filter_not_project_getter():
    window, coord = _make_coord()
    state = window.view_manager.get(0)
    state.view_id = "view-a"
    state.checked = [("f1", "torque")]
    assert hasattr(state, "time_filter")
    state.time_filter = {
        "enabled": True,
        "spec": FilterSpec("low", order=4, cutoff=40.0).to_dict(),
        "show_original": True,
        "show_filtered": True,
    }
    window._filter["enabled"] = False
    window._filter["spec"] = {}

    payload = coord._capture._time_payload(window, _ref("view-a"))
    assert payload is not None
    assert payload["filter"]["enabled"] is True
    assert payload["filter"]["spec"]["cutoff"] == pytest.approx(40.0)

    window.view_manager.new_view()
    other = window.view_manager.get(1)
    other.view_id = "view-b"
    other.checked = [("f1", "torque")]
    other.time_filter = {
        "enabled": False,
        "spec": FilterSpec("low", order=4, cutoff=100.0).to_dict(),
        "show_original": True,
        "show_filtered": True,
    }
    other_payload = coord._capture._time_payload(
        window, UltraViewRef("time", "view-b"),
    )
    assert other_payload["filter"]["enabled"] is False
    digest_a = coord.current_digest_for(_ref("view-a"))
    digest_b = coord.current_digest_for(UltraViewRef("time", "view-b"))
    assert digest_a != digest_b


def test_ordinary_coaxis_is_isolated_on_real_view_switch(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    w.chart_stack.set_plot_mode("subplot")
    _set_checked(w, "speed", "torque")
    w.plot_time()
    _flush(qapp)
    assert _subplot_rows(w.canvas_time) == 2

    w.channel_list.merge_axis_group([(fid, "speed"), (fid, "torque")])
    _flush(qapp)
    assert _grouped_channels(w, fid) == {frozenset({"speed", "torque"})}
    assert _subplot_rows(w.canvas_time) == 1
    w._capture_current_view()
    assert _state_grouped_channels(w.view_manager.get(0), fid) == {
        frozenset({"speed", "torque"})
    }

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "speed", "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    _flush(qapp)
    assert _grouped_channels(w, fid) == set()
    assert _subplot_rows(w.canvas_time) == 2

    w.channel_list.split_axis_group([(fid, "speed"), (fid, "torque")])
    _flush(qapp)

    w._switch_view(0)
    _flush(qapp)
    assert _checked_pairs(w) == [(fid, "speed"), (fid, "torque")]
    assert _grouped_channels(w, fid) == {frozenset({"speed", "torque"})}
    assert _subplot_rows(w.canvas_time) == 1


def test_filter_intent_is_isolated_on_real_view_switch(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "speed")
    _enable_lowpass(w, 50.0, order=6)
    w.plot_time()
    _flush(qapp)
    assert w.inspector.filter_panel.is_enabled() is True
    assert _filter_cutoff(w) == pytest.approx(50.0)
    assert any("Hz)" in row[0] for row in w._build_time_plot_data().rows)
    assert _has_filtered_companion(w.canvas_time)

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "speed")
    w.plot_time()
    _flush(qapp)
    assert w.inspector.filter_panel.is_enabled() is False
    assert not any("Hz)" in row[0] for row in w._build_time_plot_data().rows)
    assert not _has_filtered_companion(w.canvas_time)

    _enable_lowpass(w, 200.0, order=4)
    w.inspector.filter_panel.chk_orig.setChecked(False)
    w.plot_time()
    _flush(qapp)

    w._switch_view(0)
    _flush(qapp)
    panel = w.inspector.filter_panel
    assert panel.is_enabled() is True
    assert _filter_cutoff(w) == pytest.approx(50.0)
    assert panel.filter_spec().order == 6
    assert panel.show_original() is True
    assert any("Hz)" in row[0] for row in w._build_time_plot_data().rows)


def test_color_overrides_survive_uncheck_hide_and_do_not_bleed(
    qtbot, qapp, loaded_csv,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    default_speed = _palette_color(w, fid, "speed")
    default_torque = _palette_color(w, fid, "torque")
    _set_checked(w, "speed", "torque")
    w.navigator.set_channel_colors({
        (fid, "speed"): "#ff0000",
        (fid, "torque"): "#00aa00",
    })
    assert w.navigator.set_channel_visible(fid, "torque", False) is True
    w.plot_time()
    _flush(qapp)
    _set_checked(w, "speed")
    w.plot_time()
    _flush(qapp)
    w._capture_current_view()
    assert w.view_manager.get(0).colors[(fid, "torque")] == "#00aa00"
    assert w.view_manager.get(0).colors[(fid, "speed")] == "#ff0000"

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "speed", "torque")
    w.navigator.set_channel_colors({
        (fid, "speed"): "#0000ff",
        (fid, "torque"): "#ff00ff",
    })
    w.plot_time()
    _flush(qapp)

    w._switch_view(0)
    _flush(qapp)
    colors = w.navigator.get_channel_colors()
    assert colors[(fid, "speed")] == "#ff0000"
    assert colors[(fid, "torque")] == "#00aa00"
    _set_checked(w, "speed", "torque")
    w.plot_time()
    _flush(qapp)
    colors = w.navigator.get_channel_colors()
    assert colors[(fid, "speed")] == "#ff0000"
    assert colors[(fid, "torque")] == "#00aa00"
    assert colors[(fid, "speed")] != default_speed
    assert colors[(fid, "torque")] != default_torque

    w._switch_view(1)
    _flush(qapp)
    colors = w.navigator.get_channel_colors()
    assert colors[(fid, "speed")] == "#0000ff"
    assert colors[(fid, "torque")] == "#ff00ff"


def test_new_duplicate_close_keep_independent_intent(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    default_speed = _palette_color(w, fid, "speed")
    w.chart_stack.set_plot_mode("subplot")
    _set_checked(w, "speed", "torque")
    w.channel_list.merge_axis_group([(fid, "speed"), (fid, "torque")])
    _enable_lowpass(w, 50.0)
    w.navigator.set_channel_colors({(fid, "speed"): "#ff0000"})
    w.plot_time()
    _flush(qapp)

    w._on_view_duplicate(0)
    _flush(qapp)
    assert w.view_manager.active == 1
    assert _grouped_channels(w, fid) == {frozenset({"speed", "torque"})}
    assert w.inspector.filter_panel.is_enabled() is True
    assert _filter_cutoff(w) == pytest.approx(50.0)
    assert w.navigator.get_channel_colors()[(fid, "speed")] == "#ff0000"

    w.channel_list.split_axis_group([(fid, "speed"), (fid, "torque")])
    _enable_lowpass(w, 180.0)
    w.navigator.set_channel_colors({(fid, "speed"): "#0000ff"})
    w.plot_time()
    _flush(qapp)

    w._switch_view(0)
    _flush(qapp)
    assert _grouped_channels(w, fid) == {frozenset({"speed", "torque"})}
    assert _filter_cutoff(w) == pytest.approx(50.0)
    assert w.navigator.get_channel_colors()[(fid, "speed")] == "#ff0000"

    monkeypatch.setattr(w, "_confirm_view_delete", lambda *_a: True)
    w._on_view_delete(1)
    _flush(qapp)
    _new_attached_view(w, qapp, fid)
    _set_checked(w, "speed", "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    _flush(qapp)
    assert _grouped_channels(w, fid) == set()
    assert w.inspector.filter_panel.is_enabled() is False
    assert w.navigator.get_channel_colors()[(fid, "speed")] == default_speed
    assert _subplot_rows(w.canvas_time) == 2


def _companion_names(canvas):
    return [str(name) for name in (getattr(canvas, "_companion_names", None) or [])]


def test_split_unfocused_redraw_does_not_borrow_focused_filter(
    qtbot, qapp, loaded_csv,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "speed")
    _enable_lowpass(w, 50.0)
    w.plot_time()
    _flush(qapp)
    w._capture_current_view()

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    _enable_lowpass(w, 220.0)
    w.plot_time()
    _flush(qapp)
    w._capture_current_view()

    w._switch_view(0)
    _flush(qapp)
    assert w.inspector.filter_panel.is_enabled() is True
    assert _filter_cutoff(w) == pytest.approx(50.0)
    assert any("50Hz" in name for name in _companion_names(w.canvas_time))

    w.view_manager.set_split(1)
    _flush(qapp)
    primary = w.canvas_time
    secondary = w.chart_stack.secondary_canvas()
    assert primary is not None and secondary is not None
    w.chart_stack.set_focused_card(w.chart_stack._secondary_card)
    _flush(qapp)
    assert _filter_cutoff(w) == pytest.approx(220.0)
    w._replot_canvas_for_view(0, primary)
    _flush(qapp)
    assert any("50Hz" in name for name in _companion_names(primary))
    assert not any("220Hz" in name for name in _companion_names(primary))
    assert any("220Hz" in name for name in _companion_names(secondary))


def test_cross_file_same_channel_names_stay_independent(qtbot, qapp, tmp_path):
    csv_a = tmp_path / "a.csv"
    csv_b = tmp_path / "b.csv"
    _write_two_channel_csv(csv_a, speed_amp=1000.0)
    _write_two_channel_csv(csv_b, speed_amp=20.0, torque_amp=3.0)

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1400, 820)
    w.show()
    qtbot.waitExposed(w)
    w._load_one(str(csv_a))
    w._load_one(str(csv_b))
    qapp.processEvents()
    fid_a, fid_b = list(w.files)
    w._attach_files_to_focused_view([fid_a, fid_b])
    w.chart_stack.set_plot_mode("subplot")
    w.navigator.set_checked_channels([
        (fid_a, "speed"), (fid_a, "torque"),
        (fid_b, "speed"), (fid_b, "torque"),
    ])
    w.channel_list.merge_axis_group([(fid_a, "speed"), (fid_a, "torque")])
    w.navigator.set_channel_colors({
        (fid_a, "speed"): "#ff0000",
        (fid_b, "speed"): "#0000ff",
    })
    w.plot_time()
    _flush(qapp)

    assert _grouped_channels(w, fid_a) == {frozenset({"speed", "torque"})}
    assert _grouped_channels(w, fid_b) == set()
    colors = w.navigator.get_channel_colors()
    assert colors[(fid_a, "speed")] == "#ff0000"
    assert colors[(fid_b, "speed")] == "#0000ff"

    w._on_view_new()
    _flush(qapp)
    w._attach_files_to_focused_view([fid_a, fid_b])
    w.navigator.set_checked_channels([
        (fid_a, "speed"), (fid_a, "torque"),
        (fid_b, "speed"), (fid_b, "torque"),
    ])
    w.chart_stack.set_plot_mode("subplot")
    w.channel_list.merge_axis_group([(fid_b, "speed"), (fid_b, "torque")])
    w.navigator.set_channel_colors({
        (fid_a, "speed"): "#00ff00",
        (fid_b, "speed"): "#ffff00",
    })
    w.plot_time()
    _flush(qapp)

    w._switch_view(0)
    _flush(qapp)
    assert _grouped_channels(w, fid_a) == {frozenset({"speed", "torque"})}
    assert _grouped_channels(w, fid_b) == set()
    colors = w.navigator.get_channel_colors()
    assert colors[(fid_a, "speed")] == "#ff0000"
    assert colors[(fid_b, "speed")] == "#0000ff"


def test_save_reopen_and_schema3_filter_migration(qtbot, qapp, tmp_path):
    csv_a = tmp_path / "a.csv"
    _write_two_channel_csv(csv_a)
    proj = tmp_path / "legacy.tlproj"

    w = MainWindow()
    qtbot.addWidget(w)
    w._load_one(str(csv_a))
    fid = next(iter(w.files))
    w.chart_stack.set_plot_mode("subplot")
    _set_checked(w, "speed", "torque")
    w.channel_list.merge_axis_group([(fid, "speed"), (fid, "torque")])
    _enable_lowpass(w, 40.0, order=6)
    w.navigator.set_channel_colors({(fid, "speed"): "#ff0000"})
    w.plot_time()
    qapp.processEvents()
    w._capture_current_view()
    w._on_view_new()
    qapp.processEvents()
    w._attach_files_to_focused_view([fid])
    _set_checked(w, "speed", "torque")
    w.plot_time()
    qapp.processEvents()
    w._capture_current_view()
    w.save_project(proj)

    raw = json.loads(proj.read_text(encoding="utf-8"))
    raw["schema_version"] = 3
    for view in raw.get("views", []):
        view.pop("time_filter", None)
    raw["filter"] = {
        "enabled": True,
        "spec": FilterSpec("low", order=6, cutoff=40.0).to_dict(),
        "show_original": True,
        "show_filtered": True,
    }
    proj.write_text(json.dumps(raw), encoding="utf-8")

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    qapp.processEvents()
    restored_fid = next(iter(restored.files))
    restored._switch_view(0)
    qapp.processEvents()
    assert restored.inspector.filter_panel.is_enabled() is True
    assert _filter_cutoff(restored) == pytest.approx(40.0)
    assert restored.navigator.get_channel_colors()[(restored_fid, "speed")] == (
        "#ff0000"
    )
    assert _grouped_channels(restored, restored_fid) == {
        frozenset({"speed", "torque"})
    }

    restored._switch_view(1)
    qapp.processEvents()
    _enable_lowpass(restored, 90.0)
    restored.navigator.set_channel_colors({(restored_fid, "speed"): "#0000ff"})
    restored.channel_list.split_axis_group([
        (restored_fid, "speed"), (restored_fid, "torque"),
    ])
    restored.plot_time()
    qapp.processEvents()

    restored._switch_view(0)
    qapp.processEvents()
    assert _filter_cutoff(restored) == pytest.approx(40.0)
    assert restored.navigator.get_channel_colors()[(restored_fid, "speed")] == (
        "#ff0000"
    )
    assert _grouped_channels(restored, restored_fid) == {
        frozenset({"speed", "torque"})
    }


def _is_mostly_black(image):
    from PyQt5.QtGui import QColor

    if image is None or image.isNull() or image.width() < 16 or image.height() < 16:
        return True
    samples = (
        (image.width() // 2, image.height() // 2),
        (24, 24),
        (image.width() - 24, image.height() - 24),
        (image.width() // 3, image.height() // 3),
    )
    return all(
        QColor(image.pixel(x, y)).lightness() < 12
        for x, y in samples
    )


def _save_canvas_png(qtbot, qapp, canvas, path, *, turns=8):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    host = getattr(canvas, "_glw", None) or canvas
    image = None
    for _ in range(40):
        _flush(qapp, turns=turns)
        host.update()
        canvas.update()
        _flush(qapp, turns=2)
        image = host.grab().toImage()
        if not _is_mostly_black(image):
            break
        qtbot.wait(25)
    assert image is not None and not image.isNull()
    assert not _is_mostly_black(image), f"canvas grab stayed empty: {path}"
    assert image.save(str(path), "PNG")
    return image


def _wait_time_view_idle(qtbot, window):
    stack = window.chart_stack
    qtbot.waitUntil(
        lambda: not stack.page_transition().is_active(),
        timeout=3000,
    )
    qtbot.waitUntil(
        lambda: bool(window.canvas_time.axes_list),
        timeout=3000,
    )


def test_offscreen_render_keeps_view_intent_after_editing_other_view(
    qtbot, qapp, loaded_csv,
):
    evidence = Path(".state/view-state-isolation")
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    w.chart_stack.set_plot_mode("subplot")
    _set_checked(w, "speed", "torque")
    w.channel_list.merge_axis_group([(fid, "speed"), (fid, "torque")])
    _enable_lowpass(w, 50.0)
    w.navigator.set_channel_colors({
        (fid, "speed"): "#ff0000",
        (fid, "torque"): "#00aa00",
    })
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    w.resize(1100, 700)
    view_a = _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round1-view-a.png",
    )

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "speed", "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    view_b = _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round1-view-b.png",
    )
    assert view_a != view_b

    w.channel_list.split_axis_group([(fid, "speed"), (fid, "torque")])
    _enable_lowpass(w, 220.0)
    w.navigator.set_channel_colors({
        (fid, "speed"): "#0000ff",
        (fid, "torque"): "#ff00ff",
    })
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round1-view-b-edited.png",
    )

    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round1-view-a-after-b.png",
    )
    assert _grouped_channels(w, fid) == {frozenset({"speed", "torque"})}
    assert _filter_cutoff(w) == pytest.approx(50.0)
    colors = w.navigator.get_channel_colors()
    assert colors[(fid, "speed")] == "#ff0000"
    assert colors[(fid, "torque")] == "#00aa00"


def test_secondary_plot_mode_replot_does_not_steal_focused_filter(
    qtbot, qapp, loaded_csv,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "speed")
    _enable_lowpass(w, 50.0)
    w.plot_time()
    _flush(qapp)
    w._capture_current_view()

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    _enable_lowpass(w, 220.0)
    w.plot_time()
    _flush(qapp)
    w._capture_current_view()

    w._switch_view(0)
    _flush(qapp)
    w.view_manager.set_split(1)
    _flush(qapp)
    w.chart_stack.set_focused_card(w.chart_stack._time_card)
    _flush(qapp)
    assert _filter_cutoff(w) == pytest.approx(50.0)

    secondary = w.view_manager.get(1)
    assert secondary.time_filter["spec"]["cutoff"] == pytest.approx(220.0)
    w._replot_secondary_preserving_xlim()
    _flush(qapp)
    assert secondary.time_filter["spec"]["cutoff"] == pytest.approx(220.0)
    assert w.view_manager.get(0).time_filter["spec"]["cutoff"] == pytest.approx(
        50.0
    )
    assert _filter_cutoff(w) == pytest.approx(50.0)


def test_filter_panel_syncs_while_time_render_busy(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "speed")
    _enable_lowpass(w, 50.0)
    w._sync_focused_view_time_filter()
    assert w.view_manager.get(0).time_filter["spec"]["cutoff"] == pytest.approx(
        50.0
    )
    with w._time_render_scope():
        assert w._time_render_busy() is True
        _enable_lowpass(w, 80.0)
        assert w.view_manager.get(0).time_filter["spec"]["cutoff"] == pytest.approx(
            80.0
        )


def test_schema4_ab_save_reopen_and_dirty_cycle(qtbot, qapp, tmp_path, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "speed")
    _enable_lowpass(w, 50.0)
    w.plot_time()
    _flush(qapp)
    w._capture_current_view()

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "speed")
    _enable_lowpass(w, 220.0)
    w.plot_time()
    _flush(qapp)
    w._capture_current_view()

    proj = tmp_path / "ab-filter.tlproj"
    w.save_project(proj)
    raw = json.loads(proj.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 4
    assert raw.get("filter") is None
    cutoffs = [
        view["time_filter"]["spec"]["cutoff"] for view in raw["views"]
    ]
    assert cutoffs[0] == pytest.approx(50.0)
    assert cutoffs[1] == pytest.approx(220.0)
    assert w._project_session_is_dirty() is False

    w._switch_view(0)
    _flush(qapp)
    _enable_lowpass(w, 70.0)
    w._sync_focused_view_time_filter()
    assert w._project_session_is_dirty() is True
    w.save_project(proj)
    assert w._project_session_is_dirty() is False

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    _flush(qapp)
    restored._switch_view(0)
    _flush(qapp)
    assert _filter_cutoff(restored) == pytest.approx(70.0)
    restored._switch_view(1)
    _flush(qapp)
    assert _filter_cutoff(restored) == pytest.approx(220.0)
