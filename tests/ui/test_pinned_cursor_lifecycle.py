"""Pinned-cursor persistence and §7.3 lifecycle: hide, close, revision, View.

Persistence cases stay Qt-free. Remaining event cases use ChartStack / MainWindow.
"""
from __future__ import annotations

import json
from uuid import uuid4

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState
from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.chart_stack.pinned_cursor_controller import (
    HIDDEN_CHANNEL_TEXT,
    INCOMPATIBLE_AXIS_TEXT,
    PENDING_TEXT,
    PIN_STATUS_INCOMPATIBLE_AXIS,
    PIN_STATUS_PENDING,
    PIN_STATUS_READY,
    PIN_STATUS_UNAVAILABLE,
    UNCHECKED_TEXT,
)
from mf4_analyzer.ui.pinned_cursor_state import (
    collection_to_dict,
    empty_collection,
    next_record,
)
from mf4_analyzer.ui.time_xaxis import CHANNEL_MODE, CursorXAxisContext
from mf4_analyzer.ui.project_io import (
    ProjectDocument,
    load_project_from_json,
    remap_analysis_view_fids,
    remap_view_fids,
    save_project_to_json,
)
from mf4_analyzer.ui.view_state import ViewManager, ViewState, is_reusable_blank_view


def _single_pins(
    fid="f0",
    channel="torque",
    x=1.25,
    domain="time",
    extra_bindings=None,
):
    collection = empty_collection()
    bindings = [{"fid": fid, "channel": channel}]
    if extra_bindings:
        bindings.extend(extra_bindings)
    spec = {
        "mode": "single",
        "domain": domain,
        "x": x,
        "x_unit": "s" if domain == "time" else "Hz",
        "bindings": bindings,
        "presentation": "full",
    }
    if domain == "channel":
        spec["axis_identity"] = [fid, "steer_angle"]
        spec["x_unit"] = "mm"
    collection, _intent = next_record(collection, spec)
    return collection


def test_viewstate_roundtrip_keeps_pins_when_cursor_is_off():
    pins = _single_pins()
    state = ViewState(
        name="View 1",
        tab_color="#2d7ff9",
        cursor_mode="off",
        cursor_placement={"ax": 1.0, "bx": 2.0},
        pinned_cursors=pins,
    )
    payload = json.loads(json.dumps(state.to_dict()))
    restored = ViewState.from_dict(payload)
    assert restored.cursor_mode == "off"
    assert restored.cursor_placement == {"ax": 1.0, "bx": 2.0}
    assert restored.pinned_cursors.scope_id == pins.scope_id
    assert restored.pinned_cursors.records[0].record_id == pins.records[0].record_id
    assert restored.pinned_cursors.records[0].ordinal == 1
    assert restored.pinned_cursors.records[0].x == 1.25


def test_missing_pinned_cursors_field_is_empty_collection():
    restored = ViewState.from_dict({"name": "Legacy", "tab_color": "#2d7ff9"})
    assert restored.pinned_cursors.records == ()
    assert restored.pinned_cursors.next_ordinal == 1
    assert is_reusable_blank_view(restored) is True


def test_nonempty_pin_collection_is_not_reusable_blank():
    state = ViewState(name="View 1", tab_color="#2d7ff9")
    assert is_reusable_blank_view(state) is True
    state.pinned_cursors = _single_pins()
    assert is_reusable_blank_view(state) is False


def test_duplicate_remints_scope_and_record_ids_keeps_ordinals(qapp):
    manager = ViewManager()
    original = manager.get(0)
    original.pinned_cursors = _single_pins()
    original_scope = original.pinned_cursors.scope_id
    original_ids = [item.record_id for item in original.pinned_cursors.records]
    idx = manager.duplicate(0)
    copied = manager.get(idx)
    assert copied.view_id != original.view_id
    assert copied.pinned_cursors.scope_id != original_scope
    copied_ids = [item.record_id for item in copied.pinned_cursors.records]
    assert original_ids != copied_ids
    assert [item.ordinal for item in copied.pinned_cursors.records] == [1]
    assert copied.pinned_cursors.records[0].x == 1.25
    assert original.pinned_cursors.scope_id == original_scope
    assert [item.record_id for item in original.pinned_cursors.records] == original_ids


def test_pane_and_analysis_schema11_roundtrip_and_schema10_load():
    pins = _single_pins(fid="f1", channel="vib", x=40.0, domain="frequency")
    pane = PaneState(
        sources=[("f1", "vib")],
        cursor_mode="off",
        cursor_placement={"ax": 12.0, "bx": 40.0},
        pinned_cursors=pins,
    )
    view = AnalysisViewState(name="FFT", tab_color="#2d7ff9", panes=[pane])
    payload = json.loads(json.dumps(view.to_dict()))
    assert payload["schema"] == 11
    restored = AnalysisViewState.from_dict(payload)
    assert restored.panes[0].cursor_placement == {"ax": 12.0, "bx": 40.0}
    assert restored.panes[0].pinned_cursors.scope_id == pins.scope_id
    assert restored.panes[0].pinned_cursors.records[0].ordinal == 1

    legacy = AnalysisViewState.from_dict({
        "schema": 10,
        "name": "Legacy",
        "tab_color": "#2d7ff9",
        "panes": [{"sources": [["f1", "a"]]}],
    })
    assert legacy.panes[0].pinned_cursors.records == ()
    assert legacy.to_dict()["schema"] == 11


def test_remap_view_pins_rewrites_known_drops_unknown_and_placement():
    pins = _single_pins(
        fid="f0",
        domain="channel",
        extra_bindings=[{"fid": "missing", "channel": "rpm"}],
    )
    view = ViewState(
        name="V",
        tab_color="#fff",
        cursor_placement={"ax": 1.0, "bx": 2.5},
        pinned_cursors=pins,
    ).to_dict()
    out = remap_view_fids([view], {"f0": "f9"})[0]
    assert out["cursor_placement"] == {"ax": 1.0, "bx": 2.5}
    restored = ViewState.from_dict(out)
    intent = restored.pinned_cursors.records[0]
    assert [item.fid for item in intent.bindings] == ["f9"]
    assert intent.axis_identity == ("f9", "steer_angle")
    assert intent.ordinal == 1
    assert restored.pinned_cursors.scope_id == pins.scope_id


def test_remap_analysis_pins_inside_pane_loop():
    pins = _single_pins(
        fid="f1",
        channel="vib",
        x=40.0,
        domain="frequency",
        extra_bindings=[{"fid": "gone", "channel": "rpm"}],
    )
    analysis_views = {
        "fft": {
            "active": 0,
            "views": [{
                "schema": 11,
                "name": "FFT",
                "tab_color": "#2d7ff9",
                "panes": [{
                    "sources": [["f1", "vib"]],
                    "cursor_placement": {"ax": 12.0, "bx": 40.0},
                    "pinned_cursors": collection_to_dict(pins),
                }],
            }],
        },
    }
    out = remap_analysis_view_fids(analysis_views, {"f1": "F1"})
    pane = out["fft"]["views"][0]["panes"][0]
    assert pane["cursor_placement"] == {"ax": 12.0, "bx": 40.0}
    restored = PaneState.from_dict(pane)
    assert [item.fid for item in restored.pinned_cursors.records[0].bindings] == [
        "F1",
    ]


def test_one_corrupt_pin_does_not_break_project_payload(tmp_path):
    pins = collection_to_dict(_single_pins())
    pins["records"].append({
        "payload_version": 1,
        "record_id": str(uuid4()),
        "ordinal": 2,
        "mode": "nope",
        "domain": "time",
        "x": 9.0,
    })
    doc = ProjectDocument(
        active_file="f0",
        current_mode="time",
        views=[{
            "name": "View 1",
            "tab_color": "#2d7ff9",
            "checked": [["f0", "rpm"]],
            "pinned_cursors": pins,
        }],
    )
    path = tmp_path / "pins.tlproj"
    save_project_to_json(doc, path)
    loaded = load_project_from_json(path)
    state = ViewState.from_dict(loaded.views[0])
    assert len(state.pinned_cursors.records) == 1
    assert state.pinned_cursors.records[0].x == 1.25


def test_duplicate_analysis_view_remints_pane_collection(qapp):
    manager = ViewManager(state_factory=AnalysisViewState)
    original = manager.get(0)
    original.panes[0].pinned_cursors = _single_pins(
        fid="f1", channel="vib", x=40.0, domain="frequency",
    )
    original_scope = original.panes[0].pinned_cursors.scope_id
    original_record = original.panes[0].pinned_cursors.records[0].record_id
    idx = manager.duplicate(0)
    copied = manager.get(idx)
    assert copied.panes[0].pinned_cursors.scope_id != original_scope
    assert copied.panes[0].pinned_cursors.records[0].record_id != original_record
    assert copied.panes[0].pinned_cursors.records[0].ordinal == 1
    assert original.panes[0].pinned_cursors.records[0].record_id == original_record


def _t():
    return np.linspace(0.0, 1.0, 200)


def _plot_two(canvas, *, scale=1.0):
    t = _t()
    canvas.plot_channels(
        [
            (
                "speed", True, t, scale * np.sin(2 * np.pi * t),
                "#1769e0", "rpm", "fid-a",
            ),
            (
                "torque", True, t, scale * np.cos(2 * np.pi * t),
                "#e01769", "Nm", "fid-a",
            ),
        ],
        mode="overlay",
    )


def _make_stack(qtbot, qapp):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1100, 560)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "single")
    _plot_two(cs.canvas_time)
    qapp.processEvents()
    return cs


def _flush(qapp, turns=4):
    for _ in range(turns):
        qapp.processEvents()


def _install_pins(cs, collection, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    cs.set_pinned_cursors_for_canvas(canvas, collection)
    _flush(QApplication.instance())
    live = cs.pinned_cursors_for_canvas(canvas)
    assert live is not None
    return live.records


def _pill_html(cs, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    pills = cs._pinned_cursors.pills_for(canvas)
    if not pills:
        return ""
    pill = pills[0]
    parts = [pill.primary_text() or "", pill.detail_text() or ""]
    projection = getattr(pill, "_display_projection", None)
    if projection is not None:
        parts.append(str(getattr(projection, "html", "") or ""))
    return "\n".join(parts)


def _hide_channel(canvas, channel):
    for key, name, (_handle, line) in canvas._channel_lines.composite_items():
        label = str(name)
        channel_name = key[1] if isinstance(key, tuple) and len(key) == 2 else label
        if channel not in label and channel != channel_name:
            continue
        pdi = getattr(line, "plot_data_item", None)
        if pdi is not None:
            pdi.setVisible(False)


def test_hide_channel_keeps_identity_and_marks_hidden(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    pins = _single_pins(fid="fid-a", channel="speed", extra_bindings=[
        {"fid": "fid-a", "channel": "torque"},
    ])
    records = _install_pins(cs, pins)
    assert len(records) == 1
    assert {item.channel for item in records[0].bindings} == {"speed", "torque"}
    html_before = _pill_html(cs)
    assert HIDDEN_CHANNEL_TEXT not in html_before

    _hide_channel(cs.canvas_time, "torque")
    cs.canvas_time.presentation_content_invalidated.emit()
    assert cs._pinned_cursors.availability_for(
        cs.canvas_time, records[0].record_id,
    ) == PIN_STATUS_PENDING
    assert PENDING_TEXT in _pill_html(cs)

    _flush(qapp)
    live = cs.pinned_cursors_for_canvas(cs.canvas_time).records[0]
    assert live.record_id == records[0].record_id
    assert {item.channel for item in live.bindings} == {"speed", "torque"}
    html = _pill_html(cs)
    assert HIDDEN_CHANNEL_TEXT in html
    sample = cs._pinned_cursors._owner(cs.canvas_time).samples[live.record_id]
    hidden = [
        channel for channel in sample.channels
        if str(getattr(channel, "diagnostic", "")) == HIDDEN_CHANNEL_TEXT
    ]
    assert hidden
    assert all(getattr(channel, "current_value", None) is None for channel in hidden)


def test_last_file_close_clears_pins_via_controller(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    records = _install_pins(cs, _single_pins(fid="fid-a", channel="speed"))
    assert records
    options = cs.cursor_display_options()
    cs._pinned_cursors.drop_closed_identities(fids=("fid-a",))
    _flush(qapp)
    assert cs.pinned_cursors_for_canvas(cs.canvas_time).records == ()
    cs._pinned_cursors.clear_all()
    assert cs.cursor_display_options() == options
    assert cs._pinned_cursors.pills_for(cs.canvas_time) == ()


def test_mixed_source_close_drops_only_matching_rows(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    pins = _single_pins(
        fid="fid-a",
        channel="speed",
        extra_bindings=[{"fid": "fid-b", "channel": "rpm"}],
    )
    _install_pins(cs, pins)
    cs._pinned_cursors.drop_closed_identities(fids=("fid-b",))
    _flush(qapp)
    live = cs.pinned_cursors_for_canvas(cs.canvas_time).records
    assert len(live) == 1
    assert [item.fid for item in live[0].bindings] == ["fid-a"]
    assert live[0].x == 1.25


def test_filter_plot_channels_pending_then_new_values_discard_old_generation(
    qapp, qtbot,
):
    cs = _make_stack(qtbot, qapp)
    records = _install_pins(cs, _single_pins(fid="fid-a", channel="speed", x=0.25))
    record_id = records[0].record_id
    owner = cs._pinned_cursors._owner(cs.canvas_time)
    old_sample = owner.samples[record_id]
    old_value = old_sample.channels[0].current_value
    old_gen = old_sample.binding_generation
    old_rev = old_sample.data_revision

    cs.canvas_time.presentation_content_invalidated.emit()
    assert cs._pinned_cursors.availability_for(
        cs.canvas_time, record_id,
    ) == PIN_STATUS_PENDING
    assert PENDING_TEXT in _pill_html(cs)

    _plot_two(cs.canvas_time, scale=4.0)
    _flush(qapp)
    assert cs._pinned_cursors.availability_for(
        cs.canvas_time, record_id,
    ) == PIN_STATUS_READY
    new_sample = owner.samples[record_id]
    assert new_sample.channels[0].current_value != pytest.approx(old_value)
    gen, rev = cs._pinned_cursors._canvas_generations(cs.canvas_time)
    assert cs._pinned_cursors._sample_matches_generation(old_sample, gen, rev) is False
    assert (
        new_sample.binding_generation != old_gen
        or new_sample.data_revision != old_rev
        or new_sample.channels[0].current_value != pytest.approx(old_value)
    )


def test_custom_x_switch_is_incompatible_axis_not_remapped_seconds(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    records = _install_pins(cs, _single_pins(fid="fid-a", channel="speed", x=0.4))
    original_x = records[0].x
    record_id = records[0].record_id

    cs.canvas_time.set_cursor_x_axis_context(CursorXAxisContext(
        mode=CHANNEL_MODE,
        identity=("fid-a", "steer_angle"),
        unit="mm",
        label="Steer",
    ))
    cs.canvas_time.presentation_content_invalidated.emit()
    _flush(qapp)

    live = cs.pinned_cursors_for_canvas(cs.canvas_time).records[0]
    assert live.x == pytest.approx(original_x)
    assert live.domain == "time"
    assert cs._pinned_cursors.availability_for(
        cs.canvas_time, record_id,
    ) == PIN_STATUS_INCOMPATIBLE_AXIS
    html = _pill_html(cs)
    assert INCOMPATIBLE_AXIS_TEXT in html
    overlay = cs.canvas_time._pinned_overlay
    assert overlay.lines_for(record_id) == []

    cs.canvas_time.set_cursor_x_axis_context(None)
    cs.canvas_time.presentation_content_invalidated.emit()
    _flush(qapp)
    assert cs._pinned_cursors.availability_for(
        cs.canvas_time, record_id,
    ) == PIN_STATUS_READY
    assert cs.pinned_cursors_for_canvas(cs.canvas_time).records[0].x == pytest.approx(
        original_x
    )


def test_view_switch_does_not_carry_p1(qapp, qtbot, loaded_csv):
    from tests.ui.test_view_switch_integration import (
        _fid, _make_loaded_window, _set_checked,
    )

    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "speed")
    w.plot_time()
    _flush(qapp)
    fid = _fid(w)
    pins = _single_pins(fid=fid, channel="speed", x=0.35)
    w.chart_stack.set_pinned_cursors_for_canvas(w.canvas_time, pins)
    _flush(qapp)
    assert w.chart_stack.pinned_cursors_for_canvas(w.canvas_time).records
    assert w.chart_stack._pinned_cursors.pills_for(w.canvas_time)

    w._on_view_new()
    _flush(qapp)
    assert w.chart_stack.pinned_cursors_for_canvas(w.canvas_time).records == ()
    assert w.chart_stack._pinned_cursors.pills_for(w.canvas_time) == ()
    assert w.view_manager.get(w.view_manager.active).pinned_cursors.records == ()

    w._switch_view(0)
    _flush(qapp)
    restored = w.chart_stack.pinned_cursors_for_canvas(w.canvas_time).records
    assert len(restored) == 1
    assert restored[0].ordinal == 1
    assert restored[0].x == pytest.approx(0.35)


def test_copy_view_does_not_share_pin_widgets(qapp, qtbot, loaded_csv):
    from tests.ui.test_view_switch_integration import (
        _fid, _make_loaded_window, _set_checked,
    )

    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "speed")
    w.plot_time()
    _flush(qapp)
    pins = _single_pins(fid=_fid(w), channel="speed", x=0.2)
    w.chart_stack.set_pinned_cursors_for_canvas(w.canvas_time, pins)
    w.view_manager.get(0).pinned_cursors = pins
    original_pills = w.chart_stack._pinned_cursors.pills_for(w.canvas_time)
    original_scope = w.view_manager.get(0).pinned_cursors.scope_id
    assert original_pills

    w._on_view_duplicate(0)
    _flush(qapp)
    copied = w.view_manager.get(w.view_manager.active)
    assert copied.pinned_cursors.scope_id != original_scope
    copy_pills = w.chart_stack._pinned_cursors.pills_for(w.canvas_time)
    assert copy_pills
    assert original_pills[0] is not copy_pills[0]
    assert copied.pinned_cursors.records[0].record_id != pins.records[0].record_id


def test_reset_cursor_state_and_off_mode_keep_pins(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    records = _install_pins(cs, _single_pins(fid="fid-a", channel="speed"))
    record_id = records[0].record_id
    cs.canvas_time.reset_cursor_state()
    cs.clear_cursor_pill()
    _flush(qapp)
    assert cs.pinned_cursors_for_canvas(cs.canvas_time).records[0].record_id == record_id
    assert cs._pinned_cursors.pills_for(cs.canvas_time)

    cs.set_cursor_mode_for_canvas(cs.canvas_time, "off")
    _flush(qapp)
    assert cs.pinned_cursors_for_canvas(cs.canvas_time).records[0].record_id == record_id
    pills = cs._pinned_cursors.pills_for(cs.canvas_time)
    assert pills
    assert pills[0].isVisible() is False


def test_home_keeps_pins(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    records = _install_pins(cs, _single_pins(fid="fid-a", channel="speed", x=0.4))
    home = getattr(cs.canvas_time, "reset_view_to_data_extents", None)
    if callable(home):
        home()
    _flush(qapp)
    assert cs.pinned_cursors_for_canvas(cs.canvas_time).records[0].record_id == (
        records[0].record_id
    )


def test_user_pin_marks_dirty_hover_does_not(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    controller = cs._pinned_cursors
    dirty = []
    controller.intent_changed.connect(lambda: dirty.append(controller.user_intent_revision))
    assert controller.user_intent_revision == 0
    records = _install_pins(cs, _single_pins(fid="fid-a", channel="speed"))
    assert controller.user_intent_revision == 0
    assert dirty == []

    from tests.ui.test_pinned_cursor_interaction import _aim, _press_p, _viewport

    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.55, controller)
    _press_p(vp)
    _flush(qapp)
    assert controller.user_intent_revision >= 1
    assert dirty
    marked = controller.user_intent_revision
    record_id = cs.pinned_cursors_for_canvas(cs.canvas_time).records[-1].record_id
    controller._set_hover(cs.canvas_time, record_id)
    controller._set_hover(cs.canvas_time, None)
    cs.canvas_time.presentation_content_invalidated.emit()
    _flush(qapp)
    assert controller.user_intent_revision == marked
    assert records[0].x == 1.25


def test_recompute_unavailable_does_not_snap(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    collection = empty_collection()
    collection, _intent = next_record(collection, {
        "mode": "dual",
        "domain": "time",
        "ax": 0.2,
        "bx": 0.8,
        "x_unit": "s",
        "bindings": [{"fid": "fid-a", "channel": "speed"}],
        "presentation": "full",
    })
    records = _install_pins(cs, collection)
    record_id = records[0].record_id
    t = np.linspace(2.0, 3.0, 200)
    cs.canvas_time.plot_channels(
        [
            (
                "speed", True, t, np.sin(2 * np.pi * (t - 2.0)),
                "#1769e0", "rpm", "fid-a",
            ),
        ],
        mode="overlay",
    )
    _flush(qapp)
    live = cs.pinned_cursors_for_canvas(cs.canvas_time).records
    assert live
    assert live[0].ax == pytest.approx(0.2)
    assert live[0].bx == pytest.approx(0.8)
    assert cs._pinned_cursors.availability_for(
        cs.canvas_time, record_id,
    ) == PIN_STATUS_UNAVAILABLE


def test_split_close_hides_projection_keeps_records(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    records = _install_pins(cs, _single_pins(fid="fid-a", channel="speed"))
    cs.enter_split()
    _flush(qapp)
    secondary = cs.secondary_canvas()
    assert secondary is not None
    cs.set_pinned_cursors_for_canvas(secondary, _single_pins(fid="fid-a", channel="torque", x=0.7))
    _flush(qapp)
    assert cs.pinned_cursors_for_canvas(secondary).records
    cs.exit_split()
    _flush(qapp)
    assert cs.pinned_cursors_for_canvas(cs.canvas_time).records[0].record_id == (
        records[0].record_id
    )
    assert cs.split_active() is False
    for pill in cs._pinned_cursors.pills_for(secondary):
        assert pill.isVisible() is False


def test_uncheck_marks_unavailable_without_dirty_recheck_restores(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    controller = cs._pinned_cursors
    records = _install_pins(cs, _single_pins(fid="fid-a", channel="speed"))
    record_id = records[0].record_id
    marked = controller.user_intent_revision
    t = np.linspace(0.0, 1.0, 400)
    cs.canvas_time.plot_channels(
        [
            (
                "torque", True, t, np.cos(2 * np.pi * t),
                "#e01769", "Nm", "fid-a",
            ),
        ],
        mode="overlay",
    )
    _flush(qapp)
    assert controller.availability_for(
        cs.canvas_time, record_id,
    ) == PIN_STATUS_UNAVAILABLE
    live = cs.pinned_cursors_for_canvas(cs.canvas_time).records
    assert live and live[0].record_id == record_id
    assert live[0].bindings[0].channel == "speed"
    assert UNCHECKED_TEXT in _pill_html(cs)
    assert controller.user_intent_revision == marked
    _plot_two(cs.canvas_time)
    _flush(qapp)
    assert controller.availability_for(
        cs.canvas_time, record_id,
    ) == PIN_STATUS_READY
    assert UNCHECKED_TEXT not in _pill_html(cs)
    assert controller.user_intent_revision == marked
