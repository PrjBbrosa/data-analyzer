"""Qt-free View proposal contracts for synthetic WWT factory profiles."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mf4_analyzer._palette import FILE_PALETTES
from mf4_analyzer.io.wwt_document import load_wwt_document
from mf4_analyzer.ui.time_xaxis import (
    CHANNEL_MODE,
    EXACT_SOURCE,
    CustomXAxisSpec,
)
from mf4_analyzer.ui.wwt_view_import import (
    RegisteredWwtSources,
    build_wwt_view_proposals,
    register_groups_for_test,
)
from tests._helpers import wwt_factory as wwt

_ROOT = Path(__file__).resolve().parents[2]


def _proposals(path):
    loaded = load_wwt_document(path)
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    return build_wwt_view_proposals(loaded.document, registered), registered, loaded


def test_channel_xy_proposal_uses_only_registered_y_and_tracelab_color(tmp_path):
    proposals, registered, _loaded = _proposals(
        wwt.channel_xy_with_auxiliaries(tmp_path / "xy.wwt")
    )
    assert len(proposals) == 1
    view = proposals[0].state
    assert view.plot_mode == "overlay"
    assert view.xlim == (wwt.CHAN_X_LO, wwt.CHAN_X_HI)
    assert view.axis_opts["native_ticks"]["x"]["major"] == wwt.CHAN_X_TICK
    assert wwt.CHAN_X in view.name
    assert view.axis_opts["x_axis"] == CustomXAxisSpec(
        mode=CHANNEL_MODE,
        resolver=EXACT_SOURCE,
        source_fid="f1",
        channel=wwt.CHAN_X,
        label=f"{wwt.CHAN_X} [{wwt.CHAN_X_UNIT}]",
    ).to_axis_opts()
    by_name = {binding.display_name: binding for binding in view.curve_bindings}
    assert set(by_name) == {f"{wwt.CHAN_Y} [{wwt.CHAN_Y_UNIT}]"}
    force = by_name[f"{wwt.CHAN_Y} [{wwt.CHAN_Y_UNIT}]"]
    assert force.color == FILE_PALETTES[0][0]
    assert force.color != "#000080"
    assert force.y_range == (wwt.CHAN_Y_LO, wwt.CHAN_Y_HI)
    assert force.y_tick_interval == wwt.CHAN_Y_TICK
    assert force.y_grid_interval == wwt.CHAN_Y_GRID
    assert force.x_ref.kind == "channel"
    assert force.x_ref.channel == wwt.CHAN_X
    assert force.y_ref.kind == "channel"
    assert force.y_ref.channel == wwt.CHAN_Y
    assert ("f1", wwt.CHAN_Y) in view.checked
    assert view.colors == {}
    assert wwt.LIMIT_HI not in registered.record_channels.values()
    assert all(channel != wwt.LIMIT_HI for _fid, channel in registered.record_channels.values())


def test_measurement_proposal_drops_record_only_tolerance_y(tmp_path):
    proposals, registered, _loaded = _proposals(
        wwt.measurement_plus_record_only_tolerance(path=tmp_path / "tol.wwt")
    )
    assert len(proposals) == 1
    view = proposals[0].state
    assert view.xlim == (wwt.CHAN_X_LO, wwt.CHAN_X_HI)
    assert view.plot_mode == "overlay"
    by_name = {binding.display_name: binding for binding in view.curve_bindings}
    assert set(by_name) == {f"{wwt.MEAS_Y} [{wwt.MEAS_Y_UNIT}]"}
    meas = by_name[f"{wwt.MEAS_Y} [{wwt.MEAS_Y_UNIT}]"]
    assert meas.x_ref.kind == "channel"
    assert meas.x_ref.channel == wwt.CHAN_X
    assert meas.y_ref.kind == "channel"
    assert meas.y_ref.channel == wwt.MEAS_Y
    assert meas.color == FILE_PALETTES[0][0]
    assert meas.y_range == (wwt.MEAS_Y_LO, wwt.MEAS_Y_HI)
    assert ("f1", wwt.MEAS_Y) in view.checked
    assert ("f1", wwt.TOL_Y) not in view.checked
    assert wwt.TOL_Y not in {ch for _fid, ch in registered.record_channels.values()}
    assert set(view.axis_opts["native_ticks"]["y"]) == {meas.axis_id}


def test_registered_y_may_keep_record_only_x_without_promoting_auxiliary_y(tmp_path):
    loaded = load_wwt_document(
        wwt.channel_xy_with_auxiliaries(tmp_path / "record-x.wwt")
    )
    window = loaded.document.windows[0]
    registered_y = next(row for row in window.curves if row.record_index == 2)
    record_x = next(
        record for record in loaded.document.records if record.name == wwt.LINE_X
    )
    changed_y = replace(registered_y, x_record_index=record_x.index)
    changed_window = replace(
        window,
        curves=tuple(
            changed_y if row.record_index == registered_y.record_index else row
            for row in window.curves
        ),
    )
    document = replace(loaded.document, windows=(changed_window,))
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")

    proposals = build_wwt_view_proposals(document, registered)

    assert len(proposals) == 1
    bindings = proposals[0].state.curve_bindings
    assert len(bindings) == 1
    assert bindings[0].y_ref.kind == "channel"
    assert bindings[0].x_ref.kind == "wwt_record"
    # There is no honest Inspector schema for per-curve/record X. Fail closed
    # to the legacy state instead of claiming a specific registered channel.
    assert proposals[0].state.axis_opts["x_axis"]["mode"] == "time"


def test_two_registered_y_axes_are_not_joined_by_record_only_aux_axis(tmp_path):
    loaded = load_wwt_document(
        wwt.measurement_plus_record_only_tolerance(path=tmp_path / "axes.wwt")
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
    view = proposals[0].state
    assert len(view.curve_bindings) == 2
    assert {binding.y_ref.channel for binding in view.curve_bindings} == {
        wwt.MEAS_Y,
        wwt.TOL_Y,
    }
    assert len(view.axis_opts["native_ticks"]["y"]) == 2
    assert all("record-4" not in axis for axis in view.axis_opts["native_ticks"]["y"])


def test_multi_window_proposals_omit_record_only_y_window(tmp_path):
    proposals, registered, loaded = _proposals(
        wwt.multi_window_overlap_and_formula(tmp_path / "multi.wwt")
    )
    assert len(proposals) == wwt.MULTI_WINDOW_COUNT - 1
    assert [p.state.name.split(" · ")[0] for p in proposals] == [
        "WinWert 1", "WinWert 2",
    ]
    assert [p.rect_mm for p in proposals] == [
        wwt.RECT_WIN_A, wwt.RECT_WIN_B,
    ]
    assert [p.line_width_mm for p in proposals] == [wwt.LINE_WIDTH_MM] * 2

    form_index = next(
        record.index for record in loaded.document.records if record.name == wwt.FORM_Y
    )
    assert registered.record_channels[form_index][1] == wwt.FORM_Y
    assert registered.record_channels[form_index][0].startswith("f")

    win0 = {b.display_name: b for b in proposals[0].state.curve_bindings}
    win1 = {b.display_name: b for b in proposals[1].state.curve_bindings}
    chan_y = win0[f"{wwt.CHAN_Y} [{wwt.CHAN_Y_UNIT}]"]
    form_y = win1[f"{wwt.FORM_Y} [{wwt.FORM_Y_UNIT}]"]
    assert chan_y.y_ref.kind == "channel" and chan_y.x_ref.kind == "channel"
    assert form_y.y_ref.kind == "channel" and form_y.y_ref.channel == wwt.FORM_Y
    assert form_y.x_ref.kind == "channel" and form_y.x_ref.channel == wwt.CHAN_X
    assert all(
        binding.y_ref.kind == "channel"
        for proposal in proposals
        for binding in proposal.state.curve_bindings
    )


def test_optional_customer_wwt_proposal_smoke_when_present():
    folder = _ROOT / "testdoc" / "WWT"
    samples = sorted(folder.glob("*.wwt")) if folder.is_dir() else []
    if not samples:
        pytest.skip(f"optional customer WWT sample missing: {folder}")
    proposals, registered, loaded = _proposals(samples[0])
    assert loaded.document.records
    assert registered.fids
    assert isinstance(proposals, list)
