"""Qt-free View proposal contracts for the three user-specified WWT files."""
from __future__ import annotations

from pathlib import Path

from mf4_analyzer.io.wwt_display import WwtWindowRectMm
from mf4_analyzer.io.wwt_document import load_wwt_document
from mf4_analyzer.ui.wwt_view_import import (
    build_wwt_view_proposals,
    register_groups_for_test,
)

_ROOT = Path(__file__).resolve().parents[2]


def proposals_for(filename: str):
    loaded = load_wwt_document(_ROOT / "testdoc" / "WWT" / filename)
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    return build_wwt_view_proposals(loaded.document, registered), registered


def test_sfns_proposal_matches_literal_xy_range_ticks_and_color():
    proposals, registered = proposals_for("SFNS_10_P779_0007.wwt")
    assert len(proposals) == 1
    view = proposals[0].state
    assert view.plot_mode == "overlay"
    assert view.xlim == (-100.0, 100.0)
    assert view.axis_opts["native_ticks"]["x"]["major"] == 10.0
    assert "Rack travel" in view.name or "Rack Travel" in view.name
    by_name = {binding.display_name: binding for binding in view.curve_bindings}
    force = by_name["Rack Force [N]"]
    assert force.color == "#000080"
    assert force.y_range == (-1500.0, 1500.0)
    assert force.y_tick_interval == 500.0
    assert force.y_grid_interval == 100.0
    assert force.x_ref.kind == "channel"
    assert force.x_ref.channel == "Rack Travel"
    assert force.y_ref.kind == "channel"
    assert force.y_ref.channel == "Rack Force"
    assert ("f2", "Rack Force") in view.checked
    assert view.colors[("f2", "Rack Force")] == "#000080"


def test_yp_proposal_keeps_tolerance_and_measurement_with_distinct_x_refs():
    proposals, _registered = proposals_for("YP_SS_P779_0007.wwt")
    assert len(proposals) == 1
    view = proposals[0].state
    assert view.xlim == (-720.0, 720.0)
    assert view.plot_mode == "overlay"
    by_name = {binding.display_name: binding for binding in view.curve_bindings}
    assert by_name["Tol_oben [mm]"].color == "#ff0000"
    assert by_name["Tol_oben [mm]"].x_ref.record_index == 3
    assert by_name["Druckstückspiel [mm]"].x_ref.channel == "Lenkwinkel"
    assert by_name["Tol_oben [mm]"].axis_id == by_name["Druckstückspiel [mm]"].axis_id
    assert by_name["Druckstückspiel [mm]"].color == "#000080"
    assert by_name["Druckstückspiel [mm]"].y_range == (0.0, 0.2)
    assert ("f1", "Druckstückspiel") in view.checked
    assert ("f1", "Tol_oben") not in view.checked


def test_ucan_seven_proposals_keep_computed_and_xy_refs_and_geometry():
    proposals, registered = proposals_for("UCAN-b6_P779_0007.wwt")
    assert len(proposals) == 7
    assert [p.state.name.split(" · ")[0] for p in proposals] == [
        f"WinWert {i}" for i in range(1, 8)
    ]
    assert [p.rect_mm for p in proposals] == [
        WwtWindowRectMm(25.0, 65.0, 100.0, 60.0),
        WwtWindowRectMm(41.0, 138.2, 90.0, 60.0),
        WwtWindowRectMm(147.5, 62.5, 50.0, 60.0),
        WwtWindowRectMm(215.5, 62.5, 50.0, 60.0),
        WwtWindowRectMm(147.5, 138.0, 50.0, 60.0),
        WwtWindowRectMm(214.5, 138.0, 50.0, 60.0),
        WwtWindowRectMm(214.5, 138.0, 50.0, 60.0),
    ]
    assert [p.line_width_mm for p in proposals] == [0.2] * 7

    computed = {
        4: "Diff.Moment A",
        5: "Diff.Moment B",
        11: "Spurstangenkraft",
        12: "Motor torque A+B",
    }
    saw_xy = set()
    for proposal in proposals:
        for binding in proposal.state.curve_bindings:
            for ref in (binding.y_ref, binding.x_ref):
                if ref.kind == "channel" and ref.channel in computed.values():
                    assert ref.kind == "channel"
                if ref.kind == "wwt_record":
                    saw_xy.add(ref.record_index)
    for record_index, name in computed.items():
        assert registered.record_channels[record_index][1] == name
        assert registered.record_channels[record_index][0].startswith("f")
    assert {17, 18, 19, 20} <= saw_xy

    window1 = proposals[1].state
    by_name = {binding.display_name: binding for binding in window1.curve_bindings}
    assert "Diff.Limit A [Nm]" in by_name
    assert "Diff.Moment A [Nm]" in by_name
    assert by_name["Diff.Moment A [Nm]"].y_ref.kind == "channel"
    assert by_name["Diff.Limit A [Nm]"].y_ref.kind == "channel"
    window6 = proposals[5].state
    assert any(binding.y_ref.kind == "wwt_record" for binding in window6.curve_bindings)
    for binding in window6.curve_bindings:
        if binding.y_ref.kind == "wwt_record":
            assert binding.y_ref.record_index in {17, 18, 19, 20}
        if binding.x_ref.kind == "wwt_record":
            assert binding.x_ref.record_index in {17, 18, 19, 20}
