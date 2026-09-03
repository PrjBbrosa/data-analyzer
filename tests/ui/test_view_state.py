import json

from mf4_analyzer.ui.view_state import (
    MAX_VIEWS,
    TIME_DOMAIN_MAX_VIEWS,
    ViewManager,
    ViewState,
    default_view_tab_color,
    is_reusable_blank_view,
)
from mf4_analyzer.ui.project_io import remap_view_fids


def test_viewstate_roundtrips_through_dict():
    st = ViewState(
        name="转速对比",
        tab_color="#2d7ff9",
        checked=[("f1", "rpm"), ("f1", "speed")],
        hidden_channels=[("f1", "speed")],
        colors={("f1", "rpm"): "#2d7ff9", ("f1", "speed"): "#e8590c"},
        plot_mode="overlay",
        cursor_mode="dual",
        xlim=(0.0, 12.4),
        ylims={"[f] rpm": (-1.0, 1.0)},
        overlay_primary=("f1", "rpm"),
        axis_opts={
            "range_filter": {"enabled": True, "start": 0.0, "end": 12.4},
            "x_axis": {
                "mode": "time",
                "fid": None,
                "channel": None,
                "label": "Time (s)",
            },
            "tick_density": {"x": 10, "y": 6},
        },
    )

    payload = json.loads(json.dumps(st.to_dict()))
    again = ViewState.from_dict(payload)

    assert again == st
    assert again.checked == [("f1", "rpm"), ("f1", "speed")]
    assert again.hidden_channels == [("f1", "speed")]
    assert again.colors[("f1", "rpm")] == "#2d7ff9"
    assert again.xlim == (0.0, 12.4)
    assert again.ylims["[f] rpm"] == (-1.0, 1.0)
    assert again.overlay_primary == ("f1", "rpm")
    assert "plot_order" not in payload


def test_viewstate_color_keys_roundtrip_when_values_contain_separator():
    st = ViewState(
        name="View 1",
        tab_color="#2d7ff9",
        colors={
            ("file\tone", "rpm"): "#2d7ff9",
            ("file2", "speed\tactual"): "#e8590c",
        },
    )

    payload = json.loads(json.dumps(st.to_dict()))
    again = ViewState.from_dict(payload)

    assert again.colors == st.colors


def test_viewstate_defaults_are_empty():
    st = ViewState(name="View 1", tab_color="#2d7ff9")

    assert st.attached_file_ids == []
    assert st.checked == []
    assert st.hidden_channels == []
    assert st.colors == {}
    assert st.plot_mode == "subplot"
    assert st.cursor_mode == "off"
    assert st.xlim is None
    assert st.ylims == {}
    assert st.overlay_primary is None
    assert st.axis_opts == {}
    assert st.remarks == []
    assert st.cursor_placement is None
    assert st.curve_bindings == []
    assert st.hidden_curve_binding_ids == []
    assert not hasattr(st, "x_viewport_intent")
    assert isinstance(st.view_id, str) and st.view_id


def test_view_id_round_trips_and_legacy_payload_gets_a_fresh_id():
    state = ViewState(name="View 1", tab_color="#2d7ff9")
    restored = ViewState.from_dict(state.to_dict())
    legacy = ViewState.from_dict({"name": "Legacy", "tab_color": "#2d7ff9"})

    assert restored.view_id == state.view_id
    assert legacy.view_id
    assert legacy.view_id != state.view_id


def test_viewstate_legacy_payload_defaults_all_checked_channels_visible():
    st = ViewState.from_dict({
        "name": "Legacy",
        "tab_color": "#2d7ff9",
        "checked": [["f1", "rpm"]],
    })

    assert st.checked == [("f1", "rpm")]
    assert st.hidden_channels == []


def test_viewstate_attached_file_ids_roundtrip_in_order():
    st = ViewState(
        name="View 1",
        tab_color="#2d7ff9",
        attached_file_ids=["f2", "f1"],
    )

    again = ViewState.from_dict(json.loads(json.dumps(st.to_dict())))

    assert again.attached_file_ids == ["f2", "f1"]


def test_viewstate_roundtrip_preserves_per_source_name_axis_payload():
    x_axis = {
        "mode": "channel",
        "resolver": "per_source_name",
        "fid": None,
        "channel": "angle",
        "label": "Steering angle",
    }
    st = ViewState(
        name="Logical X",
        tab_color="#2d7ff9",
        axis_opts={"x_axis": x_axis},
    )

    again = ViewState.from_dict(json.loads(json.dumps(st.to_dict())))

    assert again.axis_opts["x_axis"] == x_axis


def test_remap_view_fids_migrates_legacy_missing_attachments():
    views = [{"name": "legacy", "checked": [], "hidden_channels": []}]

    got = remap_view_fids(views, {"old-a": "f0", "old-b": "f1"})

    assert got[0]["attached_file_ids"] == ["f0", "f1"]


def test_remap_view_fids_preserves_explicit_empty_attachments():
    views = [{"name": "empty", "attached_file_ids": [], "checked": []}]

    got = remap_view_fids(views, {"old-a": "f0"})

    assert got[0]["attached_file_ids"] == []


def test_viewstate_from_dict_legacy_payload_has_empty_overlay_fields():
    st = ViewState.from_dict({"name": "Legacy", "tab_color": "#2d7ff9"})

    assert st.remarks == []
    assert st.cursor_placement is None


def test_viewstate_remarks_and_dual_placement_roundtrip_through_dict():
    st = ViewState(
        name="View 1",
        tab_color="#2d7ff9",
        cursor_mode="dual",
        remarks=[
            {
                "source": ["f1", "rpm"],
                "x": 1.25,
                "y": 3.5,
                "label_dx": 0.08,
                "label_dy": 0.4,
                "note": "keep",
            }
        ],
        cursor_placement={"ax": 1.0, "bx": 2.5, "placing": True},
    )

    payload = json.loads(json.dumps(st.to_dict()))
    again = ViewState.from_dict(payload)

    assert again.remarks == [
        {
            "source": ["f1", "rpm"],
            "x": 1.25,
            "y": 3.5,
            "label_dx": 0.08,
            "label_dy": 0.4,
            "note": "keep",
        }
    ]
    assert again.cursor_placement == {"ax": 1.0, "bx": 2.5}
    assert "placing" not in (payload["cursor_placement"] or {})


def test_viewstate_to_dict_keeps_placement_when_cursor_mode_is_off():
    """D3 2026-08-16: cursor_mode no longer gates cursor_placement."""
    st = ViewState(
        name="View 1",
        tab_color="#2d7ff9",
        cursor_mode="off",
        cursor_placement={"ax": 1.0, "bx": 2.0},
    )

    payload = st.to_dict()
    assert payload["cursor_placement"] == {"ax": 1.0, "bx": 2.0}
    again = ViewState.from_dict(payload)
    assert again.cursor_mode == "off"
    assert again.cursor_placement == {"ax": 1.0, "bx": 2.0}


def test_time_domain_cap_is_twenty_four_and_analysis_default_stays_twelve():
    assert MAX_VIEWS == 12
    assert TIME_DOMAIN_MAX_VIEWS == 24
    assert ViewManager().max_views == MAX_VIEWS
    assert ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS).max_views == 24


def test_default_view_tab_color_matches_make_and_cycles_every_twelve():
    manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
    first_twelve = [default_view_tab_color(i) for i in range(12)]
    second_twelve = [default_view_tab_color(i) for i in range(12, 24)]

    assert first_twelve == second_twelve
    assert first_twelve[:6] == [
        "#2d7ff9", "#e8590c", "#2f9e44", "#9c36b5", "#e03131", "#1098ad",
    ]
    assert len(set(first_twelve)) == 12
    for idx in range(TIME_DOMAIN_MAX_VIEWS):
        assert default_view_tab_color(idx) == manager._make(idx).tab_color


def test_hidden_curve_binding_ids_roundtrip_and_block_blank_reuse():
    from mf4_analyzer.ui.time_curve_bindings import TimeCurveBinding, TimeDataRef

    binding = TimeCurveBinding(
        binding_id="window-1-record-2",
        y_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=2),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=1),
        display_name="TolY",
        unit="mm",
        color="#ff0000",
        axis_id="axis-1",
        y_range=(0.0, 1.0),
        y_tick_interval=0.2,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )
    st = ViewState(
        name="WinWert 1",
        tab_color="#2d7ff9",
        curve_bindings=[binding],
        hidden_curve_binding_ids=["window-1-record-2"],
    )
    again = ViewState.from_dict(st.to_dict())
    assert again.hidden_curve_binding_ids == ["window-1-record-2"]
    copied = ViewState.from_dict(st.to_dict())
    copied.hidden_curve_binding_ids.append("other")
    assert st.hidden_curve_binding_ids == ["window-1-record-2"]
    assert is_reusable_blank_view(ViewState(name="View 1", tab_color="#2d7ff9"))
    hidden_only = ViewState(
        name="View 1",
        tab_color="#2d7ff9",
        hidden_curve_binding_ids=["window-1-record-2"],
    )
    assert is_reusable_blank_view(hidden_only) is False


def test_legacy_x_viewport_intent_is_ignored_and_not_resaved():
    legacy = ViewState.from_dict({
        "name": "WinWert 1",
        "tab_color": "#2d7ff9",
        "xlim": [-100.0, 100.0],
        "x_viewport_intent": {
            "source": "wwt_native",
            "initial_range": [-100.0, 100.0],
            "home_range": [-100.0, 100.0],
        },
        "axis_opts": {
            "x_viewport_intent": {
                "source": "wwt_native",
                "home_range": [-100.0, 100.0],
            },
        },
    })

    payload = json.loads(json.dumps(legacy.to_dict()))
    assert legacy.xlim == (-100.0, 100.0)
    assert not hasattr(legacy, "x_viewport_intent")
    assert "x_viewport_intent" not in legacy.axis_opts
    assert "x_viewport_intent" not in payload
    assert "x_viewport_intent" not in payload["axis_opts"]

    blank = ViewState.from_dict({
        "name": "View 1",
        "tab_color": "#2d7ff9",
        "x_viewport_intent": {"source": "wwt_native"},
    })
    assert is_reusable_blank_view(blank)


def test_legacy_native_axis_opts_are_dropped_and_groups_are_canonical():
    state = ViewState.from_dict({
        "name": "Legacy WWT",
        "tab_color": "#2d7ff9",
        "axis_opts": {
            "native_ticks": {"x": {"major": 20.0}},
            "x_viewport_intent": {"source": "wwt_native"},
            "channel_axis_groups": {
                '["f1","force"]': "axis-1",
                ("f2", "speed"): "axis-2",
                "not-json": "bad",
                '["f3"]': "bad",
                '["f4",""]': "bad",
                '["f5","rpm"]': "",
            },
        },
    })

    assert state.axis_opts == {
        "channel_axis_groups": {
            '["f1","force"]': "axis-1",
            '["f2","speed"]': "axis-2",
        },
    }
    payload = state.to_dict()
    assert "native_ticks" not in payload["axis_opts"]
    assert "x_viewport_intent" not in payload["axis_opts"]


def test_reset_to_defaults_preserving_ids_emits_once_and_normalizes_split_pairs(qapp):
    manager = ViewManager()
    manager.new_view()
    manager.new_view()
    preserved = [manager.views[2].view_id, manager.views[0].view_id]
    removed_id = manager.views[1].view_id
    manager.set_active(1)
    manager.set_split(2)

    emissions = []
    manager.views_changed.connect(lambda: emissions.append("views"))
    manager.active_changed.connect(lambda index: emissions.append(("active", index)))
    manager.split_changed.connect(lambda index: emissions.append(("split", index)))

    removed = manager.reset_to_defaults_preserving_ids(preserved)

    assert removed == (removed_id,)
    assert [state.view_id for state in manager.views] == preserved
    assert [state.name for state in manager.views] == ["View 1", "View 2"]
    assert manager.active == 0
    assert manager.split_with is None
    assert manager._split_pairs == {}
    assert emissions.count("views") == 1
    assert emissions.count(("active", 0)) == 1
    assert emissions.count(("split", None)) == 1
