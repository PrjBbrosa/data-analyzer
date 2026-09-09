"""AnalysisViewState/PaneState: model + serialization round-trip."""
import logging

import pytest

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState


def _baseline(**overrides):
    payload = {
        "version": 1,
        "kind": "fft",
        "slot": 2,
        "display_name": "均衡",
        "params": {"window": "hanning", "nfft": 4096, "nested": {"x_auto": True}},
    }
    payload.update(overrides)
    return payload


def test_default_view_one_empty_pane():
    v = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    assert len(v.panes) == 1
    assert v.panes[0].sources == []
    assert v.compare == {"x_linked": True, "levels_locked": True}
    assert isinstance(v.view_id, str) and v.view_id
    assert v.attached_file_ids == []
    assert v.preset_baseline is None


def test_analysis_view_default_attachment_is_explicitly_empty():
    v = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    assert v.attached_file_ids == []
    payload = v.to_dict()
    assert payload["schema"] == 9
    assert payload["attached_file_ids"] == []
    assert payload["preset_baseline"] is None
    restored = AnalysisViewState.from_dict(payload)
    assert restored.attached_file_ids == []
    assert restored.preset_baseline is None


def test_schema6_analysis_view_derives_attachment_from_all_pane_roles():
    payload = {
        "schema": 6,
        "name": "Legacy",
        "tab_color": "#2d7ff9",
        "panes": [
            {
                "sources": [["f1", "a"], ["f2", "b"]],
                "rpm_source": ["f3", "rpm"],
            },
            {
                "sources": [["f2", "c"]],
                "input_source": ["f4", "in"],
                "output_source": ["f4", "out"],
            },
        ],
    }
    state = AnalysisViewState.from_dict(payload)
    assert state.attached_file_ids == ["f1", "f2", "f3", "f4"]
    # Explicit empty must not be back-filled from pane roles.
    empty = AnalysisViewState.from_dict({
        "schema": 7,
        "name": "Empty",
        "tab_color": "#2d7ff9",
        "attached_file_ids": [],
        "panes": [{"sources": [["f1", "a"]]}],
    })
    assert empty.attached_file_ids == []


def test_validate_requires_source_fids_subseteq_attachments():
    v = AnalysisViewState(name="v", tab_color="#fff")
    v.attached_file_ids = ["f1"]
    v.panes[0].sources = [("f1", "a"), ("f2", "b")]
    errs = v.validate(allow_overlay=True)
    assert any("attached" in e or "f2" in e for e in errs)


def test_round_trip_preserves_everything():
    v = AnalysisViewState(name="对比", tab_color="#e8590c")
    v.panes = [
        PaneState(
            sources=[("f1", "vib_x"), ("f2", "vib_x")],
            time_range=(1.25, 2.75),
            remarks=[{
                "source": ["f1", "vib_x"],
                "x": 12.0,
                "y": 0.4,
                "panel": "amp",
            }],
            cursor_placement={"ax": 12.0, "bx": 40.0},
        ),
        PaneState(
            sources=[("f1", "vib_y")],
            rpm_source=("f1", "rpm"),
            time_range=(5.0, 8.0),
        ),
    ]
    v.params = {"nfft": 4096, "window": "hanning"}
    v.compare = {"x_linked": False, "levels_locked": True}
    v2 = AnalysisViewState.from_dict(v.to_dict())
    assert v2.name == "对比"
    assert v2.panes[0].sources == [("f1", "vib_x"), ("f2", "vib_x")]
    assert v2.panes[0].time_range == (1.25, 2.75)
    assert v2.panes[0].remarks[0]["panel"] == "amp"
    assert v2.panes[0].cursor_placement["ax"] == 12.0
    assert v2.panes[1].rpm_source == ("f1", "rpm")
    assert v2.panes[1].time_range == (5.0, 8.0)
    assert v2.params["nfft"] == 4096
    assert v2.compare["x_linked"] is False
    assert v2.view_id == v.view_id


def test_from_dict_tolerates_missing_fields():
    v = AnalysisViewState.from_dict({"name": "x", "tab_color": "#fff"})
    assert v.panes[0].sources == []
    assert v.panes[0].time_range is None
    assert v.panes[0].remarks == []
    assert v.panes[0].cursor_placement is None
    assert v.params == {}
    assert v.preset_baseline is None
    assert isinstance(v.view_id, str) and v.view_id


def test_none_time_range_round_trip_stays_full():
    pane = PaneState(sources=[("f1", "sig")], time_range=None)
    payload = pane.to_dict()
    assert payload["time_range"] is None
    assert "draft" not in payload
    assert "source_signature" not in payload
    assert "needs_review" not in payload
    restored = PaneState.from_dict(payload)
    assert restored.time_range is None
    view = AnalysisViewState(name="FFT", tab_color="#2d7ff9")
    assert view.to_dict()["schema"] == 9
    assert AnalysisViewState.from_dict(view.to_dict()).panes[0].time_range is None


def test_inverted_time_range_is_not_normalized_to_full():
    pane = PaneState(sources=[("f1", "sig")], time_range=(8.0, 2.0))
    payload = pane.to_dict()
    assert payload["time_range"] == [8.0, 2.0]
    restored = PaneState.from_dict(payload)
    assert restored.time_range == (8.0, 2.0)
    garbage = PaneState.from_dict({
        "sources": [["f1", "sig"]],
        "time_range": ["bad"],
    })
    assert garbage.time_range is not None
    assert garbage.time_range[1] <= garbage.time_range[0]


def test_from_dict_tolerates_existing_pane_missing_time_range():
    v = AnalysisViewState.from_dict({
        "name": "x",
        "tab_color": "#fff",
        "panes": [{
            "sources": [["f1", "vib_x"]],
            "rpm_source": ["f1", "rpm"],
        }],
    })

    assert v.panes[0].sources == [("f1", "vib_x")]
    assert v.panes[0].rpm_source == ("f1", "rpm")
    assert v.panes[0].time_range is None


def test_overlay_validation():
    v = AnalysisViewState(name="v", tab_color="#fff")
    v.attached_file_ids = ["f1"]
    v.panes[0].sources = [("f1", "a"), ("f1", "b")]
    assert v.validate(allow_overlay=True) == []
    errs = v.validate(allow_overlay=False)
    assert errs and "overlay" in errs[0]


def test_pane_count_capped_at_two():
    v = AnalysisViewState(name="v", tab_color="#fff")
    assert v.add_pane() is True
    assert v.add_pane() is False
    assert len(v.panes) == 2
    v.remove_second_pane()
    assert len(v.panes) == 1


def test_frf_role_state_round_trip_keeps_sources_as_a_separate_contract():
    pane = PaneState(
        input_source=("f1", "force"),
        output_source=("f1", "accel"),
        time_range=(1.0, 3.0),
        effective_time_range=(1.001, 2.999),
        xlim=(2.0, 200.0),
        ylim=(-20.0, 20.0),
        ylims={
            "magnitude": (-40.0, 20.0),
            "phase": (-180.0, 180.0),
            "coherence": (0.0, 1.0),
        },
        source_time_view_id="time-view-123",
        cursor_mode="dual",
        remarks=[{
            "source": ["f1", "accel"],
            "x": 10.0,
            "y": 1.5,
            "panel": "magnitude",
        }],
        cursor_placement={"ax": 10.0, "bx": 40.0},
    )

    payload = pane.to_dict()
    restored = PaneState.from_dict(payload)

    assert payload["sources"] == []
    assert restored.input_source == ("f1", "force")
    assert restored.output_source == ("f1", "accel")
    assert restored.sources == []
    assert restored.time_range == (1.0, 3.0)
    assert restored.effective_time_range == (1.001, 2.999)
    assert restored.ylim == (-20.0, 20.0)
    assert restored.ylims == pane.ylims
    assert "source_time_view_id" not in payload
    assert restored.source_time_view_id is None
    assert restored.cursor_mode == "dual"
    assert restored.remarks == [{
        "source": ["f1", "accel"],
        "x": 10.0,
        "y": 1.5,
        "panel": "magnitude",
    }]
    assert restored.cursor_placement == {"ax": 10.0, "bx": 40.0}


def test_analysis_view_schema6_is_additive_and_migrates_the_old_frf_toggle():
    view = AnalysisViewState(name="FRF", tab_color="#2d7ff9")
    view.panes[0].input_source = ("f1", "in")
    view.panes[0].output_source = ("f1", "out")

    payload = view.to_dict()

    assert payload["schema"] == 9
    assert payload["attached_file_ids"] == []
    assert payload["preset_baseline"] is None
    legacy = AnalysisViewState.from_dict({
        "schema": 2,
        "name": "Legacy",
        "tab_color": "#2d7ff9",
        "panes": [{"sources": [["f1", "sig"]], "ylim": [-1, 1]}],
    })
    assert legacy.panes[0].sources == [("f1", "sig")]
    assert legacy.attached_file_ids == ["f1"]
    assert legacy.panes[0].input_source is None
    assert legacy.panes[0].output_source is None
    assert legacy.panes[0].ylims == {}
    assert legacy.panes[0].ylim == (-1.0, 1.0)
    assert legacy.panes[0].effective_time_range is None
    assert legacy.panes[0].cursor_mode == "off"
    schema4 = AnalysisViewState.from_dict({
        "schema": 4,
        "name": "FRF legacy cursor",
        "tab_color": "#2d7ff9",
        "panes": [{"frf_cursor_enabled": True}],
    })
    assert schema4.panes[0].cursor_mode == "single"


def test_duplicate_frf_pane_state_does_not_share_mutable_ylims(qapp):
    from mf4_analyzer.ui.view_state import ViewManager

    manager = ViewManager(state_factory=AnalysisViewState)
    original = manager.get(0).panes[0]
    original_view_id = manager.get(0).view_id
    original.input_source = ("f1", "in")
    original.output_source = ("f1", "out")
    original.ylims = {"magnitude": (-20.0, 10.0)}

    duplicate_idx = manager.duplicate(0)
    copied = manager.get(duplicate_idx).panes[0]
    copied.output_source = ("f1", "other")
    copied.ylims["magnitude"] = (-10.0, 5.0)

    assert original.output_source == ("f1", "out")
    assert original.ylims == {"magnitude": (-20.0, 10.0)}
    assert manager.get(duplicate_idx).view_id != original_view_id
    original.time_range = (1.0, 3.0)
    enabled_idx = manager.duplicate(0)
    assert manager.get(enabled_idx).panes[0].time_range == (1.0, 3.0)
    assert manager.get(enabled_idx).view_id != manager.get(0).view_id


def test_duplicate_copies_attached_file_ids_independently(qapp):
    from mf4_analyzer.ui.view_state import ViewManager

    manager = ViewManager(state_factory=AnalysisViewState)
    manager.get(0).attached_file_ids = ["f1", "f2"]
    idx = manager.duplicate(0)
    copied = manager.get(idx)
    assert copied.attached_file_ids == ["f1", "f2"]
    copied.attached_file_ids.append("f3")
    assert manager.get(0).attached_file_ids == ["f1", "f2"]


def test_pane_xlim_ylim_roundtrip_as_primary_analysis_viewport():
    pane = PaneState(
        sources=[("f1", "speed")],
        xlim=(20.0, 180.0),
        ylim=(-40.0, 5.0),
    )
    payload = pane.to_dict()
    again = PaneState.from_dict(payload)
    assert again.xlim == (20.0, 180.0)
    assert again.ylim == (-40.0, 5.0)
    view = AnalysisViewState(name="FFT 1", tab_color="#2d7ff9", panes=[pane])
    restored = AnalysisViewState.from_dict(view.to_dict())
    assert restored.panes[0].xlim == (20.0, 180.0)
    assert restored.panes[0].ylim == (-40.0, 5.0)


def test_preset_baseline_round_trip_preserves_fields_and_deep_copies_params():
    original_params = {"window": "hanning", "nfft": 4096, "nested": {"x_auto": True}}
    view = AnalysisViewState(name="FFT", tab_color="#2d7ff9")
    view.preset_baseline = _baseline(params=original_params)

    payload = view.to_dict()
    assert payload["schema"] == 9
    assert payload["preset_baseline"]["kind"] == "fft"
    assert payload["preset_baseline"]["slot"] == 2
    assert payload["preset_baseline"]["display_name"] == "均衡"
    payload["preset_baseline"]["params"]["nfft"] = 1
    payload["preset_baseline"]["params"]["nested"]["x_auto"] = False
    assert original_params["nfft"] == 4096
    assert original_params["nested"]["x_auto"] is True

    restored = AnalysisViewState.from_dict(view.to_dict())
    assert restored.preset_baseline["kind"] == "fft"
    assert restored.preset_baseline["slot"] == 2
    assert restored.preset_baseline["display_name"] == "均衡"
    assert restored.preset_baseline["version"] == 1
    assert restored.preset_baseline["params"] == original_params
    assert restored.preset_baseline is not view.preset_baseline
    assert restored.preset_baseline["params"] is not original_params
    assert restored.preset_baseline["params"] is not view.preset_baseline["params"]
    restored.preset_baseline["params"]["nfft"] = 1
    restored.preset_baseline["params"]["nested"]["x_auto"] = False
    assert original_params["nfft"] == 4096
    assert original_params["nested"]["x_auto"] is True
    assert view.preset_baseline["params"]["nfft"] == 4096


def test_schema8_payload_missing_preset_baseline_is_none():
    restored = AnalysisViewState.from_dict({
        "schema": 8,
        "name": "Legacy",
        "tab_color": "#2d7ff9",
        "panes": [{"sources": [["f1", "a"]]}],
        "params": {"nfft": 1024},
    })
    assert restored.preset_baseline is None


def test_null_preset_baseline_is_none():
    restored = AnalysisViewState.from_dict({
        "schema": 9,
        "name": "Empty",
        "tab_color": "#2d7ff9",
        "preset_baseline": None,
    })
    assert restored.preset_baseline is None


@pytest.mark.parametrize("baseline", [
    "not-a-dict",
    ["fft", 2],
    {"version": 1, "kind": "engine", "slot": 2, "display_name": "x", "params": {}},
    {"version": 1, "kind": "order_time", "slot": 2, "display_name": "x", "params": {}},
    {"version": 1, "kind": "fft", "slot": 0, "display_name": "x", "params": {}},
    {"version": 1, "kind": "fft", "slot": 5, "display_name": "x", "params": {}},
    {"version": 1, "kind": "fft", "slot": "2", "display_name": "x", "params": {}},
    {"version": 1, "kind": "fft", "slot": True, "display_name": "x", "params": {}},
    {"version": 2, "kind": "fft", "slot": 1, "display_name": "x", "params": {}},
    {"version": 1, "kind": "fft", "slot": 1, "display_name": 3, "params": {}},
    {"version": 1, "kind": "fft", "slot": 1, "display_name": "x", "params": []},
    {"kind": "fft", "slot": 1, "display_name": "x", "params": {}},
])
def test_corrupt_preset_baseline_becomes_none(baseline, caplog):
    with caplog.at_level(
        logging.WARNING, logger="mf4_analyzer.ui.analysis_view_state"
    ):
        restored = AnalysisViewState.from_dict({
            "name": "v",
            "tab_color": "#fff",
            "preset_baseline": baseline,
        })
    assert restored.preset_baseline is None
    assert "preset_baseline" in caplog.text


def test_duplicate_copies_preset_baseline_values_not_identity(qapp):
    from mf4_analyzer.ui.view_state import ViewManager

    manager = ViewManager(state_factory=AnalysisViewState)
    original = manager.get(0)
    original.preset_baseline = _baseline()
    idx = manager.duplicate(0)
    copied = manager.get(idx)
    assert copied.preset_baseline == original.preset_baseline
    assert copied.preset_baseline is not original.preset_baseline
    assert copied.preset_baseline["params"] is not original.preset_baseline["params"]
    copied.preset_baseline["params"]["nfft"] = 1
    copied.preset_baseline["slot"] = 4
    assert original.preset_baseline["params"]["nfft"] == 4096
    assert original.preset_baseline["slot"] == 2
