"""Native tick facts, millimetre line width, and binding payload rows."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.wwt_document import load_wwt_document
from mf4_analyzer.ui.pg_canvas import native_axes as native_axes_mod
from mf4_analyzer.ui.pg_canvas.native_axes import (
    apply_native_y_ticks,
    line_width_px,
    native_tick_levels,
)
from mf4_analyzer.ui.time_curve_bindings import bound_time_plot_rows
from mf4_analyzer.ui.wwt_view_import import (
    RegisteredWwtSources,
    build_wwt_view_proposals,
    register_groups_for_test,
)

_ROOT = Path(__file__).resolve().parents[2]
_YP_SAMPLE = _ROOT / "testdoc" / "WWT" / "YP_SS_000089.wwt"
_TICK_CAP = 2000


def _raise_if_enumerated(*_args, **_kwargs):
    raise AssertionError("enumerator must not run after candidate-count preflight")


def test_native_tick_levels_label_major_and_leave_grid_unlabelled():
    levels = native_tick_levels(-720.0, 720.0, 120.0, 60.0)
    assert [value for value, _ in levels.major] == list(np.arange(-720.0, 721.0, 120.0))
    assert all(label for _, label in levels.major)
    assert [value for value, label in levels.grid if not label][:3] == [
        -660.0, -540.0, -420.0,
    ]
    assert not ({value for value, _ in levels.major} & {value for value, _ in levels.grid})
    assert levels.adaptive is False
    assert levels.warning is None


def test_native_tick_levels_accepts_exactly_cap_candidates(monkeypatch):
    calls = []
    original = native_axes_mod._values_for_step

    def _count_calls(lo, hi, step, *args, **kwargs):
        calls.append((lo, hi, step))
        return original(lo, hi, step, *args, **kwargs)

    monkeypatch.setattr(native_axes_mod, "_values_for_step", _count_calls)
    levels = native_tick_levels(0.0, 1999.0, 1.0, None, max_grid=_TICK_CAP)
    assert levels.adaptive is False
    assert levels.warning is None
    assert [value for value, _ in levels.major] == list(range(2000))
    assert levels.grid == ()
    assert calls == [(0.0, 1999.0, 1.0)]

    grid_levels = native_tick_levels(0.0, 1999.0, None, 1.0, max_grid=_TICK_CAP)
    assert grid_levels.adaptive is False
    assert len(grid_levels.grid) == 2000
    assert grid_levels.grid[0] == (0.0, "")
    assert grid_levels.grid[-1] == (1999.0, "")


def test_native_tick_levels_rejects_2001_candidates_before_enumeration(monkeypatch):
    monkeypatch.setattr(native_axes_mod, "_values_for_step", _raise_if_enumerated)
    levels = native_tick_levels(0.0, 2000.0, 1.0, 1.0, max_grid=_TICK_CAP)
    assert levels.adaptive is True
    assert levels.warning == "tick_cap"
    assert levels.major == ()
    assert levels.grid == ()


def test_native_tick_levels_major_overflow_falls_back_whole_axis(monkeypatch):
    monkeypatch.setattr(native_axes_mod, "_values_for_step", _raise_if_enumerated)
    # Major candidates = 2001; grid would only be 21. The whole axis must
    # fall back — no native majors with adaptive/failed grid, or vice versa.
    levels = native_tick_levels(0.0, 2000.0, 1.0, 100.0, max_grid=_TICK_CAP)
    assert levels.adaptive is True
    assert levels.warning == "tick_cap"
    assert levels.major == ()
    assert levels.grid == ()


def test_native_tick_levels_grid_cap_does_not_leave_native_majors(monkeypatch):
    monkeypatch.setattr(native_axes_mod, "_values_for_step", _raise_if_enumerated)
    levels = native_tick_levels(0.0, 1.0, 0.1, 1e-6, max_grid=_TICK_CAP)
    assert levels.adaptive is True
    assert levels.warning == "tick_cap"
    assert levels.major == ()
    assert levels.grid == ()


@pytest.mark.parametrize(
    "lo, hi, major, grid",
    [
        (1e308, 1.1e308, 1e-308, 1e-308),
        (1e308, 1.1e308, 1e-308, None),
        (0.0, 1e308, 1e-308, 1.0),
        (-1e308, 1e308, 1.0, 1e-308),
    ],
)
def test_native_tick_levels_extreme_finite_inputs_do_not_overflow(
    monkeypatch, lo, hi, major, grid
):
    monkeypatch.setattr(native_axes_mod, "_values_for_step", _raise_if_enumerated)
    levels = native_tick_levels(lo, hi, major, grid, max_grid=_TICK_CAP)
    assert levels.adaptive is True
    assert levels.warning == "tick_cap"
    assert levels.major == ()
    assert levels.grid == ()


@pytest.mark.parametrize(
    "lo, hi, major, grid",
    [
        (float("nan"), 1.0, 0.1, 0.05),
        (0.0, float("nan"), 0.1, 0.05),
        (float("inf"), 1.0, 0.1, 0.05),
        (0.0, float("inf"), 0.1, 0.05),
        (float("-inf"), 1.0, 0.1, 0.05),
        (1.0, 0.0, 0.1, 0.05),
        (1.0, 1.0, 0.1, 0.05),
        (0.0, 0.0, 0.1, 0.05),
    ],
)
def test_native_tick_levels_invalid_range_is_adaptive(lo, hi, major, grid):
    levels = native_tick_levels(lo, hi, major, grid, max_grid=_TICK_CAP)
    assert levels.adaptive is True
    assert levels.warning == "invalid_range"
    assert levels.major == ()
    assert levels.grid == ()


@pytest.mark.parametrize(
    "major, grid",
    [
        (0.0, 0.0),
        (-1.0, -0.5),
        (float("nan"), float("inf")),
        (float("-inf"), float("nan")),
        (None, None),
    ],
)
def test_native_tick_levels_invalid_step_is_adaptive_without_exception(major, grid):
    levels = native_tick_levels(0.0, 1.0, major, grid, max_grid=_TICK_CAP)
    assert levels.adaptive is True
    assert levels.warning is None
    assert levels.major == ()
    assert levels.grid == ()


def test_line_width_mm_uses_logical_dpi_and_minimum_visible_width():
    assert line_width_px(0.2, 96.0) == 1.0
    assert line_width_px(0.5, 96.0) == pytest.approx(1.8897637795)


def test_record_length_mismatch_is_unaligned_without_testdoc():
    from mf4_analyzer.ui.time_curve_bindings import (
        TimeCurveBinding,
        TimeDataRef,
        resolve_time_curve_binding,
    )

    mismatched = {
        "f1": SimpleNamespace(
            data=pd.DataFrame({"Y": np.arange(4.0)}),
            source_metadata={
                "wwt_record_store": {
                    3: np.arange(6.0),
                    1: np.arange(5.0),
                }
            },
            time_array=np.arange(4.0),
        )
    }
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


def test_native_rows_plot_record_only_y_with_winwert_color(tmp_path):
    from tests._helpers import wwt_factory as wwt

    loaded = load_wwt_document(
        wwt.measurement_plus_record_only_tolerance(path=tmp_path / "plot.wwt")
    )
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    proposals = build_wwt_view_proposals(loaded.document, registered)
    assert len(proposals) == 1
    view = proposals[0].state
    kinds = [binding.y_ref.kind for binding in view.curve_bindings]
    assert kinds == ["channel", "wwt_record"]
    tol = next(
        binding for binding in view.curve_bindings if binding.y_ref.kind == "wwt_record"
    )
    assert tol.color == wwt.palette_hex(wwt.TOL_Y_COLOR)

    group = loaded.groups[0]
    files = {
        "f1": SimpleNamespace(
            data=group["data"],
            source_metadata=group["source_metadata"],
            time_array=group["data"]["Time"].to_numpy(),
        )
    }
    channel_key = ("f1", wwt.MEAS_Y)
    result = bound_time_plot_rows(
        view.curve_bindings,
        files,
        checked_channel_keys={channel_key},
        channel_colors={channel_key: "#13a36b"},
    )

    assert not result.issues
    assert len(result.rows) == 2
    by_name = {row[0]: row for row in result.rows}
    assert wwt.MEAS_Y in by_name
    assert by_name[wwt.MEAS_Y][4] == "#13a36b"
    tol_row = next(row for row in result.rows if wwt.TOL_Y in str(row[0]))
    assert tol_row[4] == wwt.palette_hex(wwt.TOL_Y_COLOR)
    assert result.claimed_channel_keys == {channel_key}
    assert result.successful_channel_keys == {channel_key}

    hidden = bound_time_plot_rows(
        view.curve_bindings,
        files,
        checked_channel_keys=set(),
        channel_colors={channel_key: "#13a36b"},
    )
    assert not hidden.issues
    assert len(hidden.rows) == 1
    assert wwt.TOL_Y in str(hidden.rows[0][0])
    assert hidden.rows[0][4] == wwt.palette_hex(wwt.TOL_Y_COLOR)
    assert channel_key in hidden.claimed_channel_keys
    assert channel_key not in hidden.successful_channel_keys


def test_yp_bindings_plot_tol_oben_and_measurement_when_customer_sample_present():
    if not _YP_SAMPLE.is_file():
        pytest.skip(f"optional customer WWT sample missing: {_YP_SAMPLE}")
    loaded = load_wwt_document(_YP_SAMPLE)
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    proposals = build_wwt_view_proposals(loaded.document, registered)
    assert len(proposals) == 1
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
    names = [row[0] for row in rows]
    assert any("Tol_oben" in str(name) for name in names)
    assert any("Druckstückspiel" in str(name) for name in names)
    tol = next(
        binding for binding in view.curve_bindings
        if "Tol_oben" in binding.display_name
    )
    meas = next(
        binding for binding in view.curve_bindings
        if "Druckstückspiel" in binding.display_name
    )
    assert tol.y_ref.kind == "wwt_record"
    tol_row = next(row for row in rows if "Tol_oben" in str(row[0]))
    assert str(tol_row[4]).lower() in {"#ff0000", "#f00"}
    meas_row = next(row for row in rows if "Druckstückspiel" in str(row[0]))
    assert str(meas_row[4]).lower() == "#000080"
    assert meas.color == "#000080"
    assert all(int(row[2].shape[0]) == int(row[3].shape[0]) for row in rows)
    assert ("f1", "Druckstückspiel") in consumed
    assert tol.axis_id == meas.axis_id
    facts = view.axis_opts["native_ticks"]["y"][meas.axis_id]
    assert (facts["lo"], facts["hi"]) == (0.0, 0.2)
    assert facts["major"] == 0.05


def _two_axis_proposal(tmp_path):
    from dataclasses import replace

    from tests._helpers import wwt_factory as wwt

    loaded = load_wwt_document(
        wwt.measurement_plus_record_only_tolerance(path=tmp_path / "pair.wwt")
    )
    window = loaded.document.windows[0]
    tolerance = next(row for row in window.curves if row.record_index == 5)
    auxiliary = replace(
        tolerance,
        record_index=4,
        x_record_index=4,
        label="Aux guide [mm]",
        selected=False,
    )
    second_channel = replace(tolerance, selected=True, lo=0.0, hi=100.0)
    changed_window = replace(
        window,
        curves=tuple(
            second_channel if row.record_index == 5 else row
            for row in window.curves
        ) + (auxiliary,),
    )
    document = replace(loaded.document, windows=(changed_window,))
    registered = RegisteredWwtSources(
        owner_fid="f1",
        fids=("f1",),
        record_channels={
            1: ("f1", wwt.CHAN_X),
            2: ("f1", wwt.MEAS_Y),
            5: ("f1", wwt.TOL_Y),
        },
    )
    proposals = build_wwt_view_proposals(document, registered)
    assert len(proposals) == 1
    return proposals[0].state


def _major_tick_values(axis):
    levels = getattr(axis, "_tickLevels", None) or ()
    if not levels:
        return ()
    return tuple(value for value, _label in levels[0])


def test_native_y_ticks_pair_by_axis_id_when_leading_binding_is_omitted(qapp, tmp_path):
    """Omitting the first channel-backed row must not zip-shift owner ticks."""
    from PyQt5.QtCore import QCoreApplication

    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    view = _two_axis_proposal(tmp_path)
    axis_ids = list(view.axis_opts["native_ticks"]["y"])
    assert len(axis_ids) == 2
    first_id, second_id = axis_ids
    # Distinct owner facts that stay under the native tick cap. The
    # proposal's 0..100 / 0.05 grid would overflow and fall back adaptive.
    first_spec = {"major": 0.25, "grid": 0.05, "lo": 0.0, "hi": 1.0}
    second_spec = {"major": 20.0, "grid": 10.0, "lo": 0.0, "hi": 100.0}
    native_y = {first_id: first_spec, second_id: second_spec}

    t = np.linspace(0.0, 1.0, 32, dtype=np.float64)
    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels(
        [("kept", True, t, t, "#0a0", "N", "f1", {"axis_group": second_id})],
        mode="overlay",
    )
    apply_native_y_ticks(canvas, native_y)

    assert len(canvas.axes_list) == 1
    assert canvas.axes_list[0].axis_group == second_id
    got = _major_tick_values(canvas.axes_list[0].y_axis_item())
    kept = native_tick_levels(
        second_spec["lo"], second_spec["hi"],
        second_spec["major"], second_spec["grid"],
    )
    shifted = native_tick_levels(
        first_spec["lo"], first_spec["hi"],
        first_spec["major"], first_spec["grid"],
    )
    assert got == tuple(value for value, _ in kept.major)
    assert got != tuple(value for value, _ in shifted.major)
    assert got[-1] == pytest.approx(second_spec["hi"])
