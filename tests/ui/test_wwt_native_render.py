"""Native tick facts, millimetre line width, and binding payload rows."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.wwt_document import load_wwt_document
from mf4_analyzer.ui.chart_defaults import DEFAULT_CHART_TICK_DENSITY
from mf4_analyzer.ui.pg_canvas import native_axes as native_axes_mod
from mf4_analyzer.ui.pg_canvas.native_axes import (
    apply_native_ticks,
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
    canvas.axes_list[0].set_ylim(second_spec["lo"], second_spec["hi"])
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


def _plot_wwt_view(qapp, view, files, checked_channel_keys):
    from PyQt5.QtCore import QCoreApplication

    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    result = bound_time_plot_rows(
        view.curve_bindings,
        files,
        checked_channel_keys=checked_channel_keys,
    )
    assert not result.issues
    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels(
        result.rows,
        mode="overlay",
        defer_first_frame=True,
    )
    canvas.restore_visible_xlim(view.xlim, flush=False)
    native_y = ((view.axis_opts or {}).get("native_ticks") or {}).get("y")
    canvas.restore_visible_ylims(view.ylims, native_axis_ranges=native_y)
    canvas.settle_view_restore()
    QCoreApplication.processEvents()
    return canvas, result


def test_shared_axis_restore_keeps_owner_ylim_not_sibling_fit(qapp, tmp_path):
    from tests._helpers import wwt_factory as wwt

    loaded = load_wwt_document(
        wwt.shared_axis_evaluation_before_owner(path=tmp_path / "yp-axis.wwt")
    )
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    proposals = build_wwt_view_proposals(loaded.document, registered)
    assert len(proposals) == 1
    view = proposals[0].state
    group = loaded.groups[0]
    files = {
        "f1": SimpleNamespace(
            data=group["data"],
            source_metadata=group["source_metadata"],
            time_array=group["data"]["Time"].to_numpy(),
        )
    }
    canvas, result = _plot_wwt_view(
        qapp, view, files, checked_channel_keys={("f1", wwt.MEAS_Y)},
    )
    assert len(result.rows) == 2
    assert len(canvas.axes_list) == 1
    lo, hi = canvas.axes_list[0].get_ylim()
    assert (lo, hi) == pytest.approx((wwt.MEAS_Y_LO, wwt.MEAS_Y_HI))
    assert hi - lo > 0.5


def test_yp_shared_axis_restore_keeps_0_to_0_2_when_customer_sample_present(qapp):
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
    meas = next(
        binding for binding in view.curve_bindings
        if "Druckstückspiel" in binding.display_name
    )
    checked = set()
    if meas.y_ref.kind == "channel" and meas.y_ref.channel:
        checked.add((meas.y_ref.fid, meas.y_ref.channel))
    canvas, result = _plot_wwt_view(qapp, view, files, checked_channel_keys=checked)
    assert len(result.rows) == 2
    assert len(canvas.axes_list) == 1
    assert canvas.axes_list[0].get_ylim() == pytest.approx((0.0, 0.2))
    facts = view.axis_opts["native_ticks"]["y"][meas.axis_id]
    assert (facts["lo"], facts["hi"]) == (0.0, 0.2)


def _load_nltnp_dual_axis_view(tmp_path):
    from tests._helpers import wwt_factory as wwt

    loaded = load_wwt_document(wwt.nltnp_like_dual_axis(path=tmp_path / "nltnp.wwt"))
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    proposals = build_wwt_view_proposals(loaded.document, registered)
    assert len(proposals) == 1
    view = proposals[0].state
    group = loaded.groups[0]
    files = {
        "f1": SimpleNamespace(
            data=group["data"],
            source_metadata=group["source_metadata"],
            time_array=group["data"]["Time"].to_numpy(),
        )
    }
    return view, files, set(view.checked)


def _production_restore_wwt_view(qapp, view, files, checked_channel_keys):
    """Execute the production View-restore sequence, not the false-green helper.

    Order matches ``_view_mixin._render_view_onto_canvas``: plot overlay with
    ``defer_first_frame=True`` → restore X (flush=False) → restore Y with
    native_axis_ranges → install canvas native tick policy → density without
    Y reframe → project ticks from the final ranges → settle. ``_plot_wwt_view``
    skips density and native policy, so it cannot freeze the Task 0 mismatches.
    """
    from PyQt5.QtCore import QCoreApplication

    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    result = bound_time_plot_rows(
        view.curve_bindings,
        files,
        checked_channel_keys=checked_channel_keys,
    )
    assert not result.issues
    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels(
        result.rows,
        mode="overlay",
        defer_first_frame=True,
    )
    canvas.restore_visible_xlim(view.xlim, flush=False)
    axis_opts = view.axis_opts or {}
    native_ticks = axis_opts.get("native_ticks") or {}
    native_y = native_ticks.get("y") if isinstance(native_ticks, dict) else None
    canvas.restore_visible_ylims(
        view.ylims,
        native_axis_ranges=native_y or None,
    )
    tick_opts = axis_opts.get("tick_density") or {}
    default_x, default_y = DEFAULT_CHART_TICK_DENSITY
    xt = int(tick_opts.get("x", default_x))
    yt = int(tick_opts.get("y", default_y))
    if native_ticks:
        canvas.set_native_tick_policy(native_ticks)
        canvas.set_tick_density(xt, yt, reframe_overlay_y=False)
        canvas.project_native_ticks()
    else:
        canvas.set_native_tick_policy(None)
        canvas.set_tick_density(xt, yt)
    canvas.settle_view_restore()
    QCoreApplication.processEvents()
    return canvas, result


def test_mixed_native_restore_reprojects_generic_axes_from_final_ranges(qapp):
    """A partial native policy must not strand generic axes on build-time ticks.

    Real WinWert Views can mix selected/native axis owners with visible axes
    that have no native cadence.  ``defer_first_frame`` builds every overlay
    axis on the temporary 0..1 range; the first generic density pass pins
    explicit ticks there.  After Y restore, unmatched axes must receive fresh
    generic ticks from their final range instead of keeping that stale level.
    """
    from PyQt5.QtCore import QCoreApplication

    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    t = np.linspace(0.0, 1.0, 128, dtype=np.float64)
    rows = [
        (
            "native-a", True, t, np.linspace(-1.0, 1.0, t.size),
            "#1769e0", "V", "f", {"axis_group": "native-a"},
        ),
        (
            "native-b", True, t, np.linspace(0.0, 100.0, t.size),
            "#e07b17", "A", "f", {"axis_group": "native-b"},
        ),
        (
            "generic-a", True, t, np.linspace(-12.0, 18.0, t.size),
            "#17a07b", "Nm", "f", {"axis_group": "generic-a"},
        ),
        (
            "generic-b", True, t, np.linspace(-12.0, 18.0, t.size),
            "#c026d3", "Nm", "f", {"axis_group": "generic-b"},
        ),
    ]
    native_ticks = {
        "x": {"major": 0.2, "grid": 0.1},
        "y": {
            "native-a": {"major": 0.2, "grid": 0.1, "lo": -1.0, "hi": 1.0},
            "native-b": {"major": 20.0, "grid": 10.0, "lo": 0.0, "hi": 100.0},
        },
    }
    persisted_ylims = {
        '["f","generic-a"]': (-12.0, 18.0),
        '["f","generic-b"]': (-12.0, 18.0),
    }

    canvas = TimeDomainCanvasPG()
    canvas.resize(1100, 720)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels(rows, mode="overlay", defer_first_frame=True)
    canvas.set_tick_density(10, 15)

    handles = {handle.axis_group: handle for handle in canvas.axes_list}
    for axis_id in ("generic-a", "generic-b"):
        assert _major_tick_values(handles[axis_id].y_axis_item()) == pytest.approx(
            tuple(np.linspace(0.0, 1.2, 16))
        ), "precondition: build-time placeholder ticks must be explicit"

    canvas.restore_visible_xlim((0.0, 1.0), flush=False)
    canvas.restore_visible_ylims(
        persisted_ylims,
        native_axis_ranges=native_ticks["y"],
    )
    canvas.set_native_tick_policy(native_ticks)
    canvas.set_tick_density(10, 15, reframe_overlay_y=False)
    canvas.project_native_ticks()
    canvas.settle_view_restore()
    QCoreApplication.processEvents()

    for axis_id in ("generic-a", "generic-b"):
        handle = handles[axis_id]
        assert handle.get_ylim() == pytest.approx((-12.0, 18.0))
        assert tuple(float(v) for v in handle.y_axis_item().range) == pytest.approx(
            (-12.0, 18.0)
        )
        majors = _major_tick_values(handle.y_axis_item())
        assert majors[0] == pytest.approx(-12.0)
        assert majors[-1] == pytest.approx(18.0)
        assert len(majors) == 16

    assert _major_tick_values(handles["native-a"].y_axis_item()) == tuple(
        value for value, _label in native_tick_levels(-1.0, 1.0, 0.2, 0.1).major
    )
    assert _major_tick_values(handles["native-b"].y_axis_item()) == tuple(
        value for value, _label in native_tick_levels(0.0, 100.0, 20.0, 10.0).major
    )
    canvas.deleteLater()


def _native_y_ids_for_range(native_y, lo, hi):
    matched = []
    for axis_id, spec in (native_y or {}).items():
        if not isinstance(spec, dict):
            continue
        spec_lo, spec_hi = spec.get("lo"), spec.get("hi")
        if spec_lo is None or spec_hi is None:
            continue
        if abs(float(spec_lo) - float(lo)) < 1e-9 and abs(float(spec_hi) - float(hi)) < 1e-9:
            matched.append(axis_id)
    return matched


def _handle_for_axis_ids(canvas, axis_ids):
    wanted = set(axis_ids)
    for handle in getattr(canvas, "axes_list", []) or ():
        if getattr(handle, "axis_group", None) in wanted:
            return handle
    raise AssertionError(
        f"no overlay handle with axis_group in {wanted!r}; "
        f"got {[getattr(h, 'axis_group', None) for h in (canvas.axes_list or ())]}"
    )


def _axis_item_range(axis):
    rng = getattr(axis, "range", None)
    assert rng is not None and len(rng) >= 2, f"AxisItem.range missing on {axis!r}"
    return (float(rng[0]), float(rng[1]))


def _assert_handle_ylim_matches_axis_item(handle, *, label):
    ylim = handle.get_ylim()
    axis = handle.y_axis_item()
    assert axis is not None, f"{label}: missing Y AxisItem"
    axis_range = _axis_item_range(axis)
    assert axis_range == pytest.approx(ylim), (
        f"{label}: AxisItem.range={axis_range!r} != handle.get_ylim()={ylim!r}"
    )


def _assert_majors_cover_effective_range(majors, lo, hi, step, *, label):
    values = tuple(float(v) for v in majors)
    assert values, f"{label}: no major ticks (range={lo!r}..{hi!r})"
    first, last = values[0], values[-1]
    assert lo - 1e-9 <= first <= hi + 1e-9, (
        f"{label}: first major {first} is outside effective range {lo}..{hi}"
    )
    assert lo - 1e-9 <= last <= hi + 1e-9, (
        f"{label}: last major {last} is outside effective range {lo}..{hi}"
    )
    top_gap = float(hi) - last
    assert top_gap < float(step) - 1e-12, (
        f"{label}: unlabeled top gap {top_gap} is not smaller than one major "
        f"step {step}; range={lo}..{hi} majors first/last={first}/{last} "
        f"all={values}"
    )


def _x_tick_handle_axes(canvas):
    handles = []
    getter = getattr(canvas, "_x_tick_axis_handles", None)
    if callable(getter):
        handles = list(getter())
    else:
        handles = list(getattr(canvas, "axes_list", []) or [])
    seen = set()
    out = []
    for handle in handles:
        axis = handle.x_axis_item() if hasattr(handle, "x_axis_item") else None
        if axis is None or id(axis) in seen:
            continue
        seen.add(id(axis))
        out.append((handle, axis))
    return out


def test_native_dual_axis_restore_keeps_ranges_after_default_density(qapp, tmp_path):
    from tests._helpers import wwt_factory as wwt

    view, files, checked = _load_nltnp_dual_axis_view(tmp_path)
    canvas, _result = _production_restore_wwt_view(qapp, view, files, checked)
    native_y = ((view.axis_opts or {}).get("native_ticks") or {}).get("y") or {}
    torque = _handle_for_axis_ids(
        canvas,
        _native_y_ids_for_range(
            native_y, wwt.SPEED_ALIAS_TORQUE_LO, wwt.SPEED_ALIAS_TORQUE_HI,
        ),
    )
    speed = _handle_for_axis_ids(
        canvas,
        _native_y_ids_for_range(native_y, wwt.SPEED_ALIAS_LO, wwt.SPEED_ALIAS_HI),
    )

    torque_ylim = torque.get_ylim()
    speed_ylim = speed.get_ylim()
    # Current baseline: default density _repin_overlay_channel_ticks() reframes
    # speed from native 0..460 to ~0..600 (and torque toward ~-10.5..12).
    range_problems = []
    if torque_ylim != pytest.approx(
        (wwt.SPEED_ALIAS_TORQUE_LO, wwt.SPEED_ALIAS_TORQUE_HI)
    ):
        range_problems.append(
            f"torque actual={torque_ylim!r} expected="
            f"({wwt.SPEED_ALIAS_TORQUE_LO}, {wwt.SPEED_ALIAS_TORQUE_HI})"
        )
    if speed_ylim != pytest.approx((wwt.SPEED_ALIAS_LO, wwt.SPEED_ALIAS_HI)):
        range_problems.append(
            f"speed actual={speed_ylim!r} expected="
            f"({wwt.SPEED_ALIAS_LO}, {wwt.SPEED_ALIAS_HI}); "
            f"must not weaken to the ~0..600 density reframe"
        )
    assert not range_problems, "; ".join(range_problems)
    _assert_handle_ylim_matches_axis_item(torque, label="torque")
    _assert_handle_ylim_matches_axis_item(speed, label="speed")
    _assert_majors_cover_effective_range(
        _major_tick_values(torque.y_axis_item()),
        torque_ylim[0], torque_ylim[1], wwt.SPEED_ALIAS_TORQUE_TICK,
        label="torque",
    )
    _assert_majors_cover_effective_range(
        _major_tick_values(speed.y_axis_item()),
        speed_ylim[0], speed_ylim[1], wwt.SPEED_ALIAS_TICK,
        label="speed",
    )


def test_native_ticks_project_over_persisted_user_viewport(qapp, tmp_path):
    from tests._helpers import wwt_factory as wwt

    view, files, checked = _load_nltnp_dual_axis_view(tmp_path)
    persisted = (40.0, 520.0)
    speed_tokens = (wwt.SPEED_ALIAS_STEER, wwt.SPEED_ALIAS_Y)
    matched = []
    for key in list(view.ylims):
        if any(token in str(key) for token in speed_tokens):
            view.ylims[key] = persisted
            matched.append(key)
    assert matched, (
        f"expected speed owner/companion keys in view.ylims, got {list(view.ylims)}"
    )

    canvas, _result = _production_restore_wwt_view(qapp, view, files, checked)
    native_y = ((view.axis_opts or {}).get("native_ticks") or {}).get("y") or {}
    speed = _handle_for_axis_ids(
        canvas,
        _native_y_ids_for_range(native_y, wwt.SPEED_ALIAS_LO, wwt.SPEED_ALIAS_HI),
    )
    speed_ylim = speed.get_ylim()
    majors = _major_tick_values(speed.y_axis_item())
    # Current apply_native_y_ticks enumerates spec lo/hi (0..460), so labels
    # stop at 460 instead of projecting cadence 20 over the persisted viewport.
    # Density may also reframe the persisted 40..520 range; report both.
    problems = []
    if speed_ylim != pytest.approx(persisted):
        problems.append(
            f"speed ylim actual={speed_ylim!r} expected={persisted!r}"
        )
    if not any(abs(float(v) - persisted[0]) < 1e-9 for v in majors):
        problems.append(
            f"majors missing persisted lo {persisted[0]}; got {majors}"
        )
    if not any(abs(float(v) - persisted[1]) < 1e-9 for v in majors):
        problems.append(
            f"majors missing persisted hi {persisted[1]} (must not stop at "
            f"{wwt.SPEED_ALIAS_HI}); got {majors}"
        )
    for value in majors:
        offset = (float(value) - persisted[0]) / wwt.SPEED_ALIAS_TICK
        if abs(offset - round(offset)) >= 1e-6:
            problems.append(
                f"major {value} is not on cadence {wwt.SPEED_ALIAS_TICK} "
                f"over {persisted}"
            )
            break
    assert not problems, "; ".join(problems)


def test_native_x_ticks_survive_settle_and_resize(qapp, tmp_path):
    from tests._helpers import wwt_factory as wwt

    view, files, checked = _load_nltnp_dual_axis_view(tmp_path)
    canvas, _result = _production_restore_wwt_view(qapp, view, files, checked)
    canvas.settle_view_restore()
    canvas.resize(1100, 480)
    qapp.processEvents()
    canvas._on_resize_settled()
    qapp.processEvents()

    expected = native_tick_levels(
        wwt.NLTNP_X_LO, wwt.NLTNP_X_HI, wwt.NLTNP_X_TICK, wwt.NLTNP_X_GRID,
    )
    expected_majors = tuple(value for value, _ in expected.major)
    pairs = _x_tick_handle_axes(canvas)
    assert pairs, "expected at least one X AxisItem after overlay restore"
    for handle, axis in pairs:
        got = _major_tick_values(axis)
        assert got == expected_majors, (
            f"native X 120/60 cadence overwritten after settle/resize: "
            f"actual={got!r} expected={expected_majors!r}"
        )
        xlim = handle.get_xlim()
        axis_range = _axis_item_range(axis)
        assert axis_range == pytest.approx(xlim), (
            f"X AxisItem.range={axis_range!r} != handle.get_xlim()={xlim!r}"
        )
        vb = getattr(handle, "view_box", None)
        if vb is not None and hasattr(vb, "viewRange"):
            vb_x = tuple(float(v) for v in vb.viewRange()[0])
            assert axis_range == pytest.approx(vb_x), (
                f"X AxisItem.range={axis_range!r} != ViewBox x range={vb_x!r}"
            )


def test_plain_view_after_wwt_has_no_stale_native_policy(qapp, tmp_path):
    from tests._helpers import wwt_factory as wwt

    view, files, checked = _load_nltnp_dual_axis_view(tmp_path)
    canvas, _result = _production_restore_wwt_view(qapp, view, files, checked)
    wwt_ids = set((((view.axis_opts or {}).get("native_ticks") or {}).get("y") or {}))
    native_speed_majors = tuple(
        value for value, _ in native_tick_levels(
            wwt.SPEED_ALIAS_LO, wwt.SPEED_ALIAS_HI,
            wwt.SPEED_ALIAS_TICK, wwt.SPEED_ALIAS_GRID,
        ).major
    )

    t = np.linspace(0.0, 1.0, 128, dtype=np.float64)
    canvas.plot_channels(
        [
            ("sine", True, t, np.sin(2.0 * np.pi * t), "#0a0", "V", "plain"),
            ("cosine", True, t, np.cos(2.0 * np.pi * t), "#a00", "V", "plain"),
        ],
        mode="overlay",
    )
    qapp.processEvents()

    leftover_ids = [
        getattr(handle, "axis_group", None) for handle in canvas.axes_list
        if getattr(handle, "axis_group", None) in wwt_ids
    ]
    assert leftover_ids == [], (
        f"plain overlay inherited WWT axis_id(s) {leftover_ids!r}"
    )
    for handle in canvas.axes_list:
        majors = _major_tick_values(handle.y_axis_item())
        assert majors != native_speed_majors, (
            f"plain overlay inherited native speed 20-cadence ticks {majors!r}"
        )
        ylim = handle.get_ylim()
        assert ylim != pytest.approx((wwt.SPEED_ALIAS_LO, wwt.SPEED_ALIAS_HI)), (
            f"plain overlay inherited native speed range {ylim!r}"
        )
        assert ylim != pytest.approx(
            (wwt.SPEED_ALIAS_TORQUE_LO, wwt.SPEED_ALIAS_TORQUE_HI)
        ), (
            f"plain overlay inherited native torque range {ylim!r}"
        )


def test_native_adaptive_overflow_clears_stale_explicit_ticks(qapp):
    from PyQt5.QtCore import QCoreApplication

    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    t = np.linspace(0.0, 1.0, 32, dtype=np.float64)
    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels(
        [("plain", True, t, t, "#0a0", "N", "f1")],
        mode="overlay",
    )
    axis = canvas.axes_list[0].y_axis_item()
    planted = native_tick_levels(0.0, 460.0, 20.0, 10.0)
    assert planted.adaptive is False
    apply_native_ticks(axis, planted)
    assert getattr(axis, "_tickLevels", None), "precondition: explicit ticks planted"

    overflow = native_tick_levels(0.0, 2000.0, 1.0, 1.0)
    assert overflow.adaptive is True
    apply_native_ticks(axis, overflow)
    levels = getattr(axis, "_tickLevels", None)
    assert levels is None or levels in ((), []), (
        "adaptive/overflow must clear stale explicit ticks via setTicks(None); "
        f"got _tickLevels={levels!r}"
    )


def test_explicit_density_change_exits_native_mode_before_reframe(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow
    from tests._helpers import wwt_factory as wwt

    path = wwt.nltnp_like_dual_axis(path=tmp_path / "nltnp.wwt")
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw.resize(1200, 760)
    mw.show()
    qapp.processEvents()
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mw._ultraview, "add_time_views_from_native_layout", lambda *_a, **_k: (),
    )
    mw._load_one(str(path))
    qapp.processEvents()
    mw._apply_active_view(mw.view_manager.active)
    qapp.processEvents()

    state = mw.view_manager.get(mw.view_manager.active)
    assert (state.axis_opts or {}).get("native_ticks"), (
        "precondition: loaded WWT ViewState must carry native_ticks"
    )
    native_speed_majors = tuple(
        value for value, _ in native_tick_levels(
            wwt.SPEED_ALIAS_LO, wwt.SPEED_ALIAS_HI,
            wwt.SPEED_ALIAS_TICK, wwt.SPEED_ALIAS_GRID,
        ).major
    )

    # Density change alone must exit native mode. Home/Fit are not required.
    mw._update_all_tick_density_pair(10, 8)
    qapp.processEvents()
    after = mw.view_manager.get(mw.view_manager.active)
    assert "native_ticks" not in (after.axis_opts or {}), (
        f"explicit density must pop native_ticks; got {after.axis_opts!r}"
    )
    canvas = mw.canvas_time
    for handle in canvas.axes_list:
        majors = _major_tick_values(handle.y_axis_item())
        assert majors != native_speed_majors, (
            f"canvas Y ticks still native 20-step over 0..460 after density "
            f"change: {majors!r}"
        )

    mw._apply_active_view(mw.view_manager.active)
    qapp.processEvents()
    restored = mw.view_manager.get(mw.view_manager.active)
    assert "native_ticks" not in (restored.axis_opts or {}), (
        f"_apply_active_view resurrected native_ticks: {restored.axis_opts!r}"
    )
    for handle in mw.canvas_time.axes_list:
        majors = _major_tick_values(handle.y_axis_item())
        assert majors != native_speed_majors, (
            f"re-apply resurrected native speed ticks: {majors!r}"
        )


def test_native_tick_policy_clears_on_rebuild_and_empty_plot(qapp, tmp_path):
    view, files, checked = _load_nltnp_dual_axis_view(tmp_path)
    canvas, _result = _production_restore_wwt_view(qapp, view, files, checked)
    policy = canvas._tick_density_controller.native_tick_policy
    assert isinstance(policy, dict)
    assert "y" in policy
    canvas.clear()
    assert canvas._tick_density_controller.native_tick_policy is None
    t = np.linspace(0.0, 1.0, 16, dtype=np.float64)
    canvas.plot_channels([], mode="overlay")
    qapp.processEvents()
    assert canvas._tick_density_controller.native_tick_policy is None
    canvas.set_native_tick_policy(view.axis_opts["native_ticks"])
    assert canvas._tick_density_controller.native_tick_policy is not None
    canvas.plot_channels(
        [("plain", True, t, t, "#0a0", "N", "plain")],
        mode="overlay",
    )
    qapp.processEvents()
    assert canvas._tick_density_controller.native_tick_policy is None
