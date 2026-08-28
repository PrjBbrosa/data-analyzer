"""Native tick facts, millimetre line width, and binding payload rows."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.wwt_document import load_wwt_document
from mf4_analyzer.ui.pg_canvas.native_axes import line_width_px, native_tick_levels
from mf4_analyzer.ui.time_curve_bindings import bound_time_plot_rows
from mf4_analyzer.ui.wwt_view_import import (
    build_wwt_view_proposals,
    register_groups_for_test,
)

_ROOT = Path(__file__).resolve().parents[2]


def test_native_tick_levels_label_major_and_leave_grid_unlabelled():
    levels = native_tick_levels(-720.0, 720.0, 120.0, 60.0)
    assert [value for value, _ in levels.major] == list(np.arange(-720.0, 721.0, 120.0))
    assert all(label for _, label in levels.major)
    assert [value for value, label in levels.grid if not label][:3] == [
        -660.0, -540.0, -420.0,
    ]
    assert not ({value for value, _ in levels.major} & {value for value, _ in levels.grid})
    assert levels.adaptive is False


def test_native_tick_levels_grid_cap_falls_back_adaptive():
    levels = native_tick_levels(0.0, 1.0, 0.1, 1e-6, max_grid=2000)
    assert levels.adaptive is True
    assert levels.warning == "grid_cap"
    assert levels.major == ()
    assert levels.grid == ()


def test_line_width_mm_uses_logical_dpi_and_minimum_visible_width():
    assert line_width_px(0.2, 96.0) == 1.0
    assert line_width_px(0.5, 96.0) == pytest.approx(1.8897637795)


def test_yp_bindings_keep_distinct_x_lengths_and_reject_unaligned():
    loaded = load_wwt_document(_ROOT / "testdoc" / "WWT" / "YP_SS_P779_0007.wwt")
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    proposals = build_wwt_view_proposals(loaded.document, registered)
    view = proposals[0].state
    files = {
        "f1": SimpleNamespace(
            data=loaded.groups[0]["data"],
            source_metadata={"wwt_record_store": loaded.document.records},
            time_array=loaded.groups[0]["data"]["Time"].to_numpy(),
        )
    }
    rows, issues, consumed = bound_time_plot_rows(view.curve_bindings, files)
    assert not issues
    assert len(rows) == 2
    lengths = sorted(int(row[2].shape[0]) for row in rows)
    assert lengths[0] != lengths[1]
    assert all(int(row[2].shape[0]) == int(row[3].shape[0]) for row in rows)
    assert ("f1", "Druckstückspiel") in consumed

    mismatched = {
        "f1": SimpleNamespace(
            data=pd.DataFrame({"Lenkwinkel": np.arange(4.0), "Druckstückspiel": np.arange(4.0)}),
            source_metadata={
                "wwt_record_store": {
                    3: np.arange(6.0),
                    1: np.arange(5.0),
                }
            },
            time_array=np.arange(4.0),
        )
    }
    from mf4_analyzer.ui.time_curve_bindings import TimeCurveBinding, TimeDataRef, resolve_time_curve_binding
    bad = TimeCurveBinding(
        binding_id="bad",
        y_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=1),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=3),
        display_name="bad",
        unit="mm",
        color="#ff0000",
        axis_id="a",
        y_range=(0.0, 1.0),
        y_tick_interval=None,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )
    x_out, y_out, issue = resolve_time_curve_binding(bad, mismatched)
    assert x_out is None and y_out is None
    assert issue.code == "unaligned"
    assert issue.detail == "6,5"
