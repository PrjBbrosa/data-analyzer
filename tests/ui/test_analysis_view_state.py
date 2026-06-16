"""AnalysisViewState/PaneState: model + serialization round-trip."""
import pytest

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState


def test_default_view_one_empty_pane():
    v = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    assert len(v.panes) == 1
    assert v.panes[0].sources == []
    assert v.compare == {"x_linked": True, "levels_locked": True}


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


def test_from_dict_tolerates_missing_fields():
    v = AnalysisViewState.from_dict({"name": "x", "tab_color": "#fff"})
    assert v.panes[0].sources == []
    assert v.panes[0].time_range is None
    assert v.params == {}


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
