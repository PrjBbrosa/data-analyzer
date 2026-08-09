"""Contracts for the deliberately small analysis parameter surface."""
from __future__ import annotations

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState
from mf4_analyzer.ui.drawers.batch.method_buttons import (
    DynamicParamForm,
    _METHOD_FIELDS,
)
from mf4_analyzer.ui.inspector_sections import FrfContextual
from mf4_analyzer.ui.inspector_sections.contextual_fft_time import FFTTimeContextual
from mf4_analyzer.ui.main_window._frf_mixin import FrfMixin


def test_removed_switches_have_no_widget_or_state_backdoor(qtbot):
    frf = FrfContextual()
    fft_time = FFTTimeContextual()
    form = DynamicParamForm()
    for widget in (frf, fft_time, form):
        qtbot.addWidget(widget)

    for name in ("chk_periodic", "chk_detrend", "combo_range_mode"):
        assert not hasattr(frf, name)
    assert not hasattr(fft_time, "chk_remove_mean")

    assert frf.compute_params()["periodic_window"] is True
    assert frf.compute_params()["detrend"] == "constant"
    frf.apply_params({"periodic_window": False, "detrend": "none"})
    assert frf._collect_preset()["periodic_window"] is True
    assert frf._collect_preset()["detrend"] == "constant"

    assert fft_time.get_params()["remove_mean"] is True
    fft_time.apply_params({"remove_mean": False})
    fft_time._apply_preset_values({"remove_mean": False})
    assert fft_time._collect_preset()["remove_mean"] is True

    assert "periodic_window" not in _METHOD_FIELDS["frf"]
    assert "detrend" not in _METHOD_FIELDS["frf"]
    assert "remove_mean" not in _METHOD_FIELDS["fft_time"]
    assert not {
        "periodic_window", "detrend", "remove_mean",
    } & set(form._labels)


def test_legacy_frf_range_metadata_is_read_once_then_not_written():
    assert PaneState().source_time_view_id is None
    pane = PaneState(source_time_view_id="legacy-time-view")
    assert "source_time_view_id" not in pane.to_dict()

    restored = AnalysisViewState.from_dict({
        "name": "legacy FRF",
        "tab_color": "#2d7ff9",
        "params": {"range_mode": "current_time"},
        "panes": [{
            "time_range": [0.25, 0.75],
            "source_time_view_id": "legacy-time-view",
        }],
    })

    assert restored.panes[0].time_range == (0.25, 0.75)
    assert restored.panes[0].source_time_view_id is None
    assert "range_mode" not in restored.params
    serialized = restored.to_dict()
    assert "source_time_view_id" not in serialized["panes"][0]
    assert "range_mode" not in serialized["params"]


def test_legacy_frf_missing_range_mode_means_full_range():
    restored = AnalysisViewState.from_dict({
        "schema": 5,
        "name": "legacy FRF",
        "tab_color": "#2d7ff9",
        "panes": [{
            "input_source": ["source-a", "input"],
            "output_source": ["source-a", "output"],
            "time_range": [0.25, 0.75],
            "source_time_view_id": "legacy-time-view",
        }],
    })

    assert restored.panes[0].time_range is None
    assert restored.panes[0].source_time_view_id is None


def test_frf_uses_the_shared_range_contract_only():
    for name in (
        "_frf_requested_range",
        "_capture_frf_time_range",
        "_apply_frf_time_range",
        "_on_frf_range_mode_changed",
        "_on_frf_manual_time_range_edited",
        "_on_frf_source_time_xrange_changed",
        "_invalidate_frf_time_view_link",
    ):
        assert not hasattr(FrfMixin, name)
