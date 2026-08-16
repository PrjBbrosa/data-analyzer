import json

from mf4_analyzer.ui.view_state import ViewState
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
