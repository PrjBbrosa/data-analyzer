"""Per-curve XY binding JSON, remap, resolution, and shape errors."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.project_io import collect_dropped_time_refs, remap_view_fids
from mf4_analyzer.ui.time_curve_bindings import (
    TimeCurveBinding,
    TimeDataRef,
    filter_curve_bindings,
    remap_curve_bindings,
    resolve_time_curve_binding,
    resolve_time_data_ref,
)
from mf4_analyzer.ui.view_state import ViewState


def _sample_binding() -> TimeCurveBinding:
    return TimeCurveBinding(
        binding_id="window-6-record-18",
        y_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=18),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=17),
        display_name="Rack Force [KN]",
        unit="KN",
        color="#000080",
        axis_id="window-6-axis-18",
        y_range=(0.0, 18.0),
        y_tick_interval=1.0,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )


def test_time_curve_binding_roundtrip_equals_original():
    channel_ref = TimeDataRef(kind="channel", fid="f1", channel="Rack Force")
    record_ref = TimeDataRef(kind="wwt_record", fid="f1", record_index=17)
    binding = _sample_binding()
    assert TimeDataRef.from_dict(channel_ref.to_dict()) == channel_ref
    assert TimeDataRef.from_dict(record_ref.to_dict()) == record_ref
    assert TimeCurveBinding.from_dict(binding.to_dict()) == binding


def test_channel_and_wwt_record_ref_invariants():
    with pytest.raises(ValueError, match="channel ref"):
        TimeDataRef(kind="channel", fid="f1", channel="A", record_index=1)
    with pytest.raises(ValueError, match="wwt_record ref"):
        TimeDataRef(kind="wwt_record", fid="f1", record_index=1, channel="A")
    with pytest.raises(ValueError, match="wwt_record ref"):
        TimeDataRef(kind="wwt_record", fid="f1", channel=None, record_index=None)


def test_resolver_returns_exact_arrays_and_structured_issues():
    x = np.linspace(-1.0, 1.0, 8)
    y = np.arange(8, dtype=np.float64)
    files = {
        "f1": SimpleNamespace(
            data=pd.DataFrame({"Rack Force": y, "Time": np.arange(8.0)}),
            source_metadata={
                "wwt_record_store": {17: x, 18: y},
            },
            time_array=np.arange(8.0) / 1000.0,
        )
    }
    channel_ref = TimeDataRef(kind="channel", fid="f1", channel="Rack Force")
    values, issue = resolve_time_data_ref(channel_ref, files)
    assert issue is None
    np.testing.assert_array_equal(values, y)

    record_ref = TimeDataRef(kind="wwt_record", fid="f1", record_index=17)
    values, issue = resolve_time_data_ref(record_ref, files)
    assert issue is None
    np.testing.assert_array_equal(values, x)
    assert values is not files["f1"].time_array

    missing_owner, issue = resolve_time_data_ref(
        TimeDataRef(kind="channel", fid="gone", channel="Rack Force"), files
    )
    assert missing_owner is None and issue.code == "missing_owner"

    missing_ch, issue = resolve_time_data_ref(
        TimeDataRef(kind="channel", fid="f1", channel="nope"), files
    )
    assert missing_ch is None and issue.code == "missing_channel"

    missing_rec, issue = resolve_time_data_ref(
        TimeDataRef(kind="wwt_record", fid="f1", record_index=99), files
    )
    assert missing_rec is None and issue.code == "missing_record"

    binding = _sample_binding()
    x_out, y_out, issue = resolve_time_curve_binding(binding, files)
    assert issue is None
    np.testing.assert_array_equal(x_out, x)
    np.testing.assert_array_equal(y_out, y)

    files["f1"].source_metadata["wwt_record_store"][17] = np.linspace(-1.0, 1.0, 5)
    x_out, y_out, issue = resolve_time_curve_binding(binding, files)
    assert x_out is None and y_out is None
    assert issue.code == "unaligned"
    assert issue.detail == "5,8"
    assert "min(" not in issue.detail


def test_remap_and_filter_bindings_drop_missing_owners():
    binding = _sample_binding()
    remapped = remap_curve_bindings([binding], {"f1": "f9"})
    assert remapped[0].x_ref.fid == "f9"
    assert remapped[0].y_ref.fid == "f9"
    assert remap_curve_bindings([binding], {}) == []

    mixed = TimeCurveBinding(
        binding_id="mixed",
        y_ref=TimeDataRef(kind="channel", fid="f1", channel="Rack Force"),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=17),
        display_name="Rack Force",
        unit="N",
        color="#000080",
        axis_id="a",
        y_range=(0.0, 1.0),
        y_tick_interval=None,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )
    kept = filter_curve_bindings(
        [binding, mixed], removed_channels={("f1", "Rack Force")}
    )
    assert kept == [binding]
    dropped = filter_curve_bindings([binding, mixed], removed_fids={"f1"})
    assert dropped == []


def test_viewstate_json_roundtrip_and_project_remap_keep_bindings():
    binding = _sample_binding()
    state = ViewState(
        name="WinWert 1",
        tab_color="#2d7ff9",
        attached_file_ids=["f1"],
        curve_bindings=[binding],
    )
    restored = ViewState.from_dict(state.to_dict())
    assert restored.curve_bindings == [binding]

    malformed = ViewState.from_dict({
        "name": "V",
        "tab_color": "#2d7ff9",
        "curve_bindings": [{"not": "a binding"}, binding.to_dict()],
    })
    assert malformed.curve_bindings == [binding]
    assert ViewState.from_dict({
        "name": "V",
        "tab_color": "#2d7ff9",
    }).curve_bindings == []

    payload = remap_view_fids([state.to_dict()], {"f1": "f9"})[0]
    remapped = ViewState.from_dict(payload)
    assert remapped.curve_bindings[0].x_ref.fid == "f9"
    assert remapped.curve_bindings[0].y_ref.fid == "f9"

    dropped = collect_dropped_time_refs([state.to_dict()], {})
    assert ("", "f1", "binding:x") in dropped or any(
        item[2] == "binding:x" for item in dropped
    )
    assert any(item[2] == "binding:y" for item in dropped)
