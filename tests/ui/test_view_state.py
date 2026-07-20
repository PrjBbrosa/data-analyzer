import json

from mf4_analyzer.ui.view_state import ViewState


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

    assert st.checked == []
    assert st.hidden_channels == []
    assert st.colors == {}
    assert st.plot_mode == "subplot"
    assert st.cursor_mode == "off"
    assert st.xlim is None
    assert st.ylims == {}
    assert st.overlay_primary is None
    assert st.axis_opts == {}


def test_viewstate_legacy_payload_defaults_all_checked_channels_visible():
    st = ViewState.from_dict({
        "name": "Legacy",
        "tab_color": "#2d7ff9",
        "checked": [["f1", "rpm"]],
    })

    assert st.checked == [("f1", "rpm")]
    assert st.hidden_channels == []
