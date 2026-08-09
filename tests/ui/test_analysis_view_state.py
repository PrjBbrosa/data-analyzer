"""AnalysisViewState/PaneState: model + serialization round-trip."""
import pytest

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState


def test_default_view_one_empty_pane():
    v = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    assert len(v.panes) == 1
    assert v.panes[0].sources == []
    assert v.compare == {"x_linked": True, "levels_locked": True}
    assert isinstance(v.view_id, str) and v.view_id


def test_round_trip_preserves_everything():
    v = AnalysisViewState(name="对比", tab_color="#e8590c")
    v.panes = [
        PaneState(
            sources=[("f1", "vib_x"), ("f2", "vib_x")],
            time_range=(1.25, 2.75),
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
    assert v2.panes[1].rpm_source == ("f1", "rpm")
    assert v2.panes[1].time_range == (5.0, 8.0)
    assert v2.params["nfft"] == 4096
    assert v2.compare["x_linked"] is False
    assert v2.view_id == v.view_id


def test_from_dict_tolerates_missing_fields():
    v = AnalysisViewState.from_dict({"name": "x", "tab_color": "#fff"})
    assert v.panes[0].sources == []
    assert v.panes[0].time_range is None
    assert v.params == {}
    assert isinstance(v.view_id, str) and v.view_id


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
    assert restored.source_time_view_id == "time-view-123"


def test_analysis_view_schema3_is_additive_and_field_presence_tolerant():
    view = AnalysisViewState(name="FRF", tab_color="#2d7ff9")
    view.panes[0].input_source = ("f1", "in")
    view.panes[0].output_source = ("f1", "out")

    payload = view.to_dict()

    assert payload["schema"] == 3
    legacy = AnalysisViewState.from_dict({
        "schema": 2,
        "name": "Legacy",
        "tab_color": "#2d7ff9",
        "panes": [{"sources": [["f1", "sig"]], "ylim": [-1, 1]}],
    })
    assert legacy.panes[0].sources == [("f1", "sig")]
    assert legacy.panes[0].input_source is None
    assert legacy.panes[0].output_source is None
    assert legacy.panes[0].ylims == {}
    assert legacy.panes[0].ylim == (-1.0, 1.0)
    assert legacy.panes[0].effective_time_range is None


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
