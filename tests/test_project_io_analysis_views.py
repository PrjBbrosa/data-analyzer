"""project_io: analysis_views persistence + fid remap."""
from mf4_analyzer.ui.analysis_view_state import (
    AnalysisViewState,
    PaneState,
    analysis_view_has_sources,
)
from mf4_analyzer.ui.project_io import (
    ProjectDocument, collect_dropped_analysis_refs, load_project_from_json,
    normalize_analysis_comparisons, remap_analysis_view_fids, save_project_to_json,
)


def _doc():
    return ProjectDocument(
        active_file="f1", current_mode="fft",
        analysis_views={
            "fft": {
                "active": 0,
                "views": [{
                    "schema": 1, "name": "View 1", "tab_color": "#2d7ff9",
                    "panes": [{"sources": [["f1", "vib"], ["f2", "vib"]],
                               "rpm_source": None, "xlim": None, "ylim": None}],
                    "params": {"nfft": 2048},
                    "compare": {"x_linked": True, "levels_locked": True},
                }],
            },
        },
    )


def test_round_trip(tmp_path):
    p = tmp_path / "s.tlproj"
    save_project_to_json(_doc(), p)
    loaded = load_project_from_json(p)
    assert loaded.analysis_views["fft"]["views"][0]["params"]["nfft"] == 2048


def test_comparisons_round_trip_without_becoming_view_compare(tmp_path):
    doc = _doc()
    doc.analysis_views["fft"]["comparisons"] = {
        "host-a": {
            "peer": "peer-b",
            "axis_linked": False,
            "levels_locked": True,
        },
    }
    path = tmp_path / "comparisons.tlproj"
    save_project_to_json(doc, path)
    loaded = load_project_from_json(path)
    row = loaded.analysis_views["fft"]["comparisons"]["host-a"]
    assert row["peer"] == "peer-b"
    assert row["axis_linked"] is False
    assert row["levels_locked"] is True
    assert loaded.analysis_views["fft"]["views"][0]["params"]["nfft"] == 2048
    assert "peer" not in loaded.analysis_views["fft"]["views"][0]["compare"]


def test_absent_comparisons_normalize_to_empty():
    payload, dropped = normalize_analysis_comparisons(None, ["host"])
    assert payload == {}
    assert dropped == []


def test_normalize_drops_missing_peer_and_rejects_non_bool_flags():
    payload, dropped = normalize_analysis_comparisons(
        {
            "host": {
                "peer": "gone",
                "axis_linked": "false",
                "levels_locked": 1,
                "canvas": "token",
            },
            "other": {
                "peer": "host",
                "axis_linked": True,
                "levels_locked": False,
                "result": [1, 2, 3],
            },
        },
        ["host", "other"],
    )
    assert dropped == ["host"]
    assert "host" not in payload
    assert payload["other"] == {
        "peer": "host",
        "axis_linked": True,
        "levels_locked": False,
    }


def test_remap_keeps_comparison_view_ids_when_a_view_id_matches_a_file_id():
    analysis_views = {
        "fft": {
            "active": 0,
            "views": [{
                "schema": 1,
                "name": "View 1",
                "view_id": "f1",
                "panes": [{"sources": [["f1", "vib"]]}],
            }, {
                "schema": 1,
                "name": "View 2",
                "view_id": "peer-view",
                "panes": [{"sources": []}],
            }],
            "comparisons": {
                "f1": {
                    "peer": "peer-view",
                    "axis_linked": False,
                    "levels_locked": True,
                    "canvas": {"token": 1},
                },
            },
        },
    }
    out = remap_analysis_view_fids(analysis_views, {"f1": "F1"})
    assert out["fft"]["views"][0]["panes"][0]["sources"] == [["F1", "vib"]]
    assert out["fft"]["views"][0]["view_id"] == "f1"
    assert out["fft"]["comparisons"]["f1"]["peer"] == "peer-view"
    assert "F1" not in out["fft"]["comparisons"]
    payload, dropped = normalize_analysis_comparisons(
        out["fft"]["comparisons"], ["f1", "peer-view"],
    )
    assert dropped == []
    assert payload["f1"] == {
        "peer": "peer-view",
        "axis_linked": False,
        "levels_locked": True,
    }


def test_old_file_without_field_defaults_empty(tmp_path):
    p = tmp_path / "old.tlproj"
    save_project_to_json(ProjectDocument(active_file=None, current_mode="time"), p)
    raw = p.read_text(encoding="utf-8")
    import json
    d = json.loads(raw)
    d.pop("analysis_views", None)
    p.write_text(json.dumps(d), encoding="utf-8")
    loaded = load_project_from_json(p)
    assert loaded.analysis_views == {}


def test_remap_drops_missing_fids():
    av = _doc().analysis_views
    out = remap_analysis_view_fids(av, {"f1": "F1"})  # f2 missing → dropped
    srcs = out["fft"]["views"][0]["panes"][0]["sources"]
    assert srcs == [["F1", "vib"]]


def test_remap_analysis_line_colors_follow_file_ids():
    from mf4_analyzer.ui.chart_appearance_model import appearance_channel_key

    kept = appearance_channel_key("f1", "vib")
    dropped = appearance_channel_key("f-missing", "vib")
    analysis_views = {
        "fft": {
            "active": 0,
            "views": [{
                "schema": 11,
                "name": "FFT",
                "panes": [{
                    "sources": [["f1", "vib"]],
                    "chart_appearances": {
                        "spectrum": {
                            "title": "Kept",
                            "line_colors": {kept: "#ff0000", dropped: "#00ff00"},
                        },
                        "preview": {"title": ""},
                    },
                }],
            }],
        },
    }
    out = remap_analysis_view_fids(analysis_views, {"f1": "F1"})
    appearances = out["fft"]["views"][0]["panes"][0]["chart_appearances"]
    assert appearances["spectrum"]["title"] == "Kept"
    assert appearances["spectrum"]["line_colors"] == {
        appearance_channel_key("F1", "vib"): "#ff0000",
    }
    assert appearances["preview"]["title"] == ""
    assert "chart_appearances" in analysis_views["fft"]["views"][0]["panes"][0]


def test_remap_analysis_remarks_rewrites_fid_and_drops_missing():
    analysis_views = {
        "fft": {
            "active": 0,
            "views": [{
                "schema": 8,
                "name": "FFT",
                "tab_color": "#2d7ff9",
                "panes": [{
                    "sources": [["f1", "vib"]],
                    "remarks": [
                        {
                            "source": ["f1", "vib"],
                            "x": 12.0,
                            "y": 0.4,
                            "panel": "amp",
                        },
                        {
                            "source": ["f-missing", "vib"],
                            "x": 20.0,
                            "y": 0.1,
                            "panel": "amp",
                        },
                    ],
                    "cursor_placement": {"ax": 12.0, "bx": 40.0},
                }],
            }],
        },
    }
    out = remap_analysis_view_fids(analysis_views, {"f1": "F1"})
    pane = out["fft"]["views"][0]["panes"][0]
    assert pane["remarks"] == [{
        "source": ["F1", "vib"],
        "x": 12.0,
        "y": 0.4,
        "panel": "amp",
    }]
    assert pane["cursor_placement"] == {"ax": 12.0, "bx": 40.0}


def test_remap_analysis_pins_rewrites_known_fids_drops_unknown():
    from uuid import uuid4
    from mf4_analyzer.ui.pinned_cursor_state import (
        collection_from_dict,
        collection_to_dict,
    )

    pins = collection_to_dict(collection_from_dict({
        "payload_version": 1,
        "scope_id": str(uuid4()),
        "next_ordinal": 2,
        "records": [{
            "payload_version": 1,
            "record_id": str(uuid4()),
            "ordinal": 1,
            "mode": "single",
            "domain": "frequency",
            "x": 40.0,
            "x_unit": "Hz",
            "bindings": [
                {"fid": "f1", "channel": "vib"},
                {"fid": "gone", "channel": "rpm"},
            ],
        }],
    }))
    analysis_views = {
        "fft": {
            "active": 0,
            "views": [{
                "schema": 11,
                "name": "FFT",
                "tab_color": "#2d7ff9",
                "panes": [{
                    "sources": [["f1", "vib"]],
                    "cursor_placement": {"ax": 12.0, "bx": 40.0},
                    "pinned_cursors": pins,
                }],
            }],
        },
    }
    out = remap_analysis_view_fids(analysis_views, {"f1": "F1"})
    pane = out["fft"]["views"][0]["panes"][0]
    assert pane["cursor_placement"] == {"ax": 12.0, "bx": 40.0}
    record = pane["pinned_cursors"]["records"][0]
    assert [item["fid"] for item in record["bindings"]] == ["F1"]
    assert record["ordinal"] == 1
    dropped = collect_dropped_analysis_refs(analysis_views, {"f1": "F1"})
    assert ("fft", "FFT", 0, "pin") in dropped


def test_remap_frf_role_endpoints_is_directional_and_symmetric():
    analysis_views = {
        "frf": {
            "active": 0,
            "views": [{
                "schema": 3,
                "name": "FRF",
                "tab_color": "#2d7ff9",
                "panes": [{
                    "sources": [],
                    "input_source": ["f1", "force"],
                    "output_source": ["f2", "accel"],
                }],
            }],
        },
    }

    both = remap_analysis_view_fids(
        analysis_views, {"f1": "new-in", "f2": "new-out"}
    )
    pane = both["frf"]["views"][0]["panes"][0]
    assert pane["input_source"] == ["new-in", "force"]
    assert pane["output_source"] == ["new-out", "accel"]

    missing_output = remap_analysis_view_fids(
        analysis_views, {"f1": "new-in"}
    )
    pane = missing_output["frf"]["views"][0]["panes"][0]
    assert pane["input_source"] == ["new-in", "force"]
    assert pane["output_source"] is None


def test_project_restore_source_predicate_requires_a_complete_frf_pair():
    frf = AnalysisViewState(name="FRF", tab_color="#2d7ff9")
    frf.panes = [
        PaneState(input_source=("f1", "in"), output_source=("f1", "out"))
    ]
    incomplete = AnalysisViewState(name="FRF", tab_color="#2d7ff9")
    incomplete.panes = [PaneState(input_source=("f1", "in"))]
    fft = AnalysisViewState(name="FFT", tab_color="#2d7ff9")
    fft.panes[0].sources = [("f1", "sig")]

    assert analysis_view_has_sources("frf", frf) is True
    assert analysis_view_has_sources("frf", incomplete) is False
    assert analysis_view_has_sources("fft", fft) is True


# ----------------------------------------------------------------------
# Task 8 Step 8.1 plus FRF: AnalysisViewState nested schema 1 -> 2 -> 3 -> 4 -> 5
# migration (spec §13 S3/S5). The migration keys off "params has db_reference and no
# db_reference_mode", NOT the nested schema number -- from_dict() ignores
# the schema field entirely, so schema-2 through schema-5 projects all apply the
# snapshot db_reference manual-style.
# ----------------------------------------------------------------------
def test_analysis_view_schema6_round_trip_preserves_db_reference_mode_and_value():
    v = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    v.params = {
        "db_reference_mode": "manual",
        "db_reference": 2.5e-6,
        "nfft": 4096,
    }
    d = v.to_dict()
    assert d["schema"] == 12
    assert d["preset_baseline"] is None

    v2 = AnalysisViewState.from_dict(d)
    assert v2.params["db_reference_mode"] == "manual"
    assert v2.params["db_reference"] == 2.5e-6
    assert v2.params["nfft"] == 4096


def test_schema1_view_value_without_mode_migrates_to_manual():
    # A schema-1 payload from before db_reference_mode existed: the bare
    # numeric value IS the old authoritative display reference (spec S5) --
    # ALL such existing views/presets/projects migrate to Manual, even
    # though the nested "schema" field literally still says 1.
    legacy = {
        "schema": 1,
        "name": "View 1",
        "tab_color": "#2d7ff9",
        "panes": [{"sources": [["f1", "vib"]]}],
        "params": {"db_reference": 1.0, "nfft": 2048},
    }
    v = AnalysisViewState.from_dict(legacy)
    assert v.params["db_reference_mode"] == "manual"
    assert v.params["db_reference"] == 1.0
    assert v.params["nfft"] == 2048


def test_schema1_view_without_reference_does_not_inject_hardcoded_value():
    # A schema-1 view that never had a db_reference key at all (e.g. a
    # Time-only project, or a view whose section never persisted the key)
    # must NOT gain an injected db_reference/db_reference_mode -- the live
    # control's current Auto/Manual state is what drives it.
    legacy = {
        "schema": 1,
        "name": "View 1",
        "tab_color": "#2d7ff9",
        "panes": [{"sources": [["f1", "vib"]]}],
        "params": {"nfft": 2048},
    }
    v = AnalysisViewState.from_dict(legacy)
    assert "db_reference" not in v.params
    assert "db_reference_mode" not in v.params
    assert v.params["nfft"] == 2048


def test_fft_auto_nfft_intent_round_trips_without_freezing_effective():
    state = AnalysisViewState(name="FFT Auto", tab_color="#2d7ff9")
    state.params = {
        "nfft": None,
        "nfft_mode": "auto",
        "t_win_s": 1.5,
        "avg_mode": "线性平均",
        "avg_overlap": 50,
    }
    restored = AnalysisViewState.from_dict(state.to_dict())
    assert restored.params["nfft"] is None
    assert restored.params["nfft_mode"] == "auto"
    assert restored.params["t_win_s"] == 1.5
    assert "nfft_effective" not in restored.params or restored.params["nfft_effective"] is None


def test_preset_baseline_round_trips_through_project_json(tmp_path):
    view = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    view.params = {"nfft": 4096, "window": "hanning"}
    view.preset_baseline = {
        "version": 1,
        "kind": "fft",
        "slot": 2,
        "display_name": "均衡",
        "params": {"window": "hanning", "nfft": 4096},
    }
    path = tmp_path / "baseline.tlproj"
    save_project_to_json(
        ProjectDocument(
            active_file="f1",
            current_mode="fft",
            analysis_views={
                "fft": {"active": 0, "views": [view.to_dict()]},
            },
        ),
        path,
    )
    loaded = load_project_from_json(path)
    payload = loaded.analysis_views["fft"]["views"][0]
    assert payload["schema"] == 12
    assert payload["params"]["nfft"] == 4096
    assert payload["preset_baseline"]["kind"] == "fft"
    assert payload["preset_baseline"]["slot"] == 2
    restored = AnalysisViewState.from_dict(payload)
    assert restored.preset_baseline["display_name"] == "均衡"
    assert restored.preset_baseline["params"] == {"window": "hanning", "nfft": 4096}
    restored.preset_baseline["params"]["nfft"] = 1
    assert view.preset_baseline["params"]["nfft"] == 4096
    assert restored.preset_baseline["version"] == 1
    assert "source_payload" not in restored.preset_baseline


def test_equal_params_cross_slot_baseline_round_trips_through_project_json(tmp_path):
    """A13 serializer half: same compute params, new loaded slot must persist."""
    view = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    params = {"nfft": 4096, "window": "hanning", "overlap": 50}
    view.params = dict(params)
    view.preset_baseline = {
        "version": 2,
        "kind": "fft",
        "slot": 4,
        "display_name": "identical",
        "params": dict(params),
        "source_payload": dict(params),
    }
    path = tmp_path / "baseline-cross-slot.tlproj"
    save_project_to_json(
        ProjectDocument(
            active_file="f1",
            current_mode="fft",
            analysis_views={
                "fft": {"active": 0, "views": [view.to_dict()]},
            },
        ),
        path,
    )
    loaded = load_project_from_json(path)
    restored = AnalysisViewState.from_dict(loaded.analysis_views["fft"]["views"][0])
    assert restored.params == params
    assert restored.preset_baseline["slot"] == 4
    assert restored.preset_baseline["display_name"] == "identical"
    assert restored.preset_baseline["version"] == 2
    assert restored.preset_baseline["source_payload"] == params


def test_v2_preset_baseline_round_trips_through_project_json(tmp_path):
    view = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    view.params = {"nfft": 4096, "window": "hanning"}
    view.preset_baseline = {
        "version": 2,
        "kind": "fft",
        "slot": 2,
        "display_name": "均衡",
        "params": {"window": "hanning", "nfft": 4096, "x_auto": True},
        "source_payload": {"window": "hanning", "overlap": 50},
    }
    path = tmp_path / "baseline-v2.tlproj"
    save_project_to_json(
        ProjectDocument(
            active_file="f1",
            current_mode="fft",
            analysis_views={
                "fft": {"active": 0, "views": [view.to_dict()]},
            },
        ),
        path,
    )
    loaded = load_project_from_json(path)
    payload = loaded.analysis_views["fft"]["views"][0]
    assert payload["schema"] == 12
    assert payload["preset_baseline"]["version"] == 2
    restored = AnalysisViewState.from_dict(payload)
    assert restored.preset_baseline["source_payload"]["overlap"] == 50
    restored.preset_baseline["source_payload"]["overlap"] = 1
    assert view.preset_baseline["source_payload"]["overlap"] == 50


def test_corrupt_v2_preset_baseline_in_project_json_is_none(tmp_path):
    view = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    view.preset_baseline = {
        "version": 2,
        "kind": "fft",
        "slot": 1,
        "display_name": "频率",
        "params": {"window": "hanning"},
    }
    path = tmp_path / "baseline-bad.tlproj"
    save_project_to_json(
        ProjectDocument(
            active_file="f1",
            current_mode="fft",
            analysis_views={
                "fft": {"active": 0, "views": [view.to_dict()]},
            },
        ),
        path,
    )
    loaded = load_project_from_json(path)
    restored = AnalysisViewState.from_dict(loaded.analysis_views["fft"]["views"][0])
    assert restored.preset_baseline is None


def test_project_json_time_range_omits_drafts_and_keeps_none_as_full(tmp_path):
    full = AnalysisViewState(name="Full", tab_color="#2d7ff9")
    full.panes[0].sources = [("f1", "vib")]
    full.panes[0].time_range = None
    enabled = AnalysisViewState(name="Enabled", tab_color="#2d7ff9")
    enabled.panes[0].sources = [("f1", "vib")]
    enabled.panes[0].time_range = (0.25, 0.75)
    path = tmp_path / "time-range.tlproj"
    save_project_to_json(
        ProjectDocument(
            active_file="f1",
            current_mode="fft",
            analysis_views={
                "fft": {
                    "active": 0,
                    "views": [full.to_dict(), enabled.to_dict()],
                },
            },
        ),
        path,
    )
    loaded = load_project_from_json(path)
    views = loaded.analysis_views["fft"]["views"]
    assert views[0]["schema"] == 12
    assert views[0]["panes"][0].get("time_range") in (None, [])
    assert views[1]["panes"][0]["time_range"] == [0.25, 0.75]
    for pane in (views[0]["panes"][0], views[1]["panes"][0]):
        assert "draft" not in pane
        assert "source_signature" not in pane
        assert "needs_review" not in pane
    restored_full = AnalysisViewState.from_dict(views[0])
    restored_enabled = AnalysisViewState.from_dict(views[1])
    assert restored_full.panes[0].time_range is None
    assert restored_enabled.panes[0].time_range == (0.25, 0.75)


def test_project_json_without_preset_baseline_loads_as_none(tmp_path):
    path = tmp_path / "legacy.tlproj"
    save_project_to_json(_doc(), path)
    loaded = load_project_from_json(path)
    payload = loaded.analysis_views["fft"]["views"][0]
    assert "preset_baseline" not in payload
    restored = AnalysisViewState.from_dict(payload)
    assert restored.preset_baseline is None


def test_collect_dropped_analysis_refs_records_missing_pane_roles():
    av = {
        "fft": {
            "active": 0,
            "views": [{
                "view_id": "vid-fft",
                "name": "View 1",
                "panes": [{
                    "sources": [["f1", "a"], ["f2", "b"]],
                    "rpm_source": None,
                }],
            }],
        },
        "order": {
            "active": 0,
            "views": [{
                "view_id": "vid-ord",
                "panes": [{
                    "sources": [["f1", "sig"]],
                    "rpm_source": ["f2", "rpm"],
                }],
            }],
        },
        "frf": {
            "active": 0,
            "views": [{
                "view_id": "vid-frf",
                "panes": [{
                    "sources": [],
                    "input_source": ["f2", "in"],
                    "output_source": ["f1", "out"],
                }],
            }],
        },
    }
    dropped = collect_dropped_analysis_refs(av, {"f1": "F1"})
    assert ("fft", "vid-fft", 0, "signal") in dropped
    assert ("order", "vid-ord", 0, "rpm") in dropped
    assert ("frf", "vid-frf", 0, "input") in dropped
    assert ("frf", "vid-frf", 0, "output") not in dropped
    assert ("order", "vid-ord", 0, "signal") not in dropped


def test_viewport_origins_survive_project_json_and_legacy_migration(tmp_path):
    doc = _doc()
    panes = [PaneState(xlim=(1., 2.), ylim=(3., 4.), viewport_origin={'x': 'user', 'y': 'home'}),
             PaneState.from_dict({'xlim': [5., 6.]})]
    state = AnalysisViewState(name='Saved', tab_color='#ffffff', panes=panes)
    doc.analysis_views['fft']['views'] = [state.to_dict()]
    path = tmp_path / 'viewport.tlproj'
    save_project_to_json(doc, path)
    loaded = load_project_from_json(path)
    restored = AnalysisViewState.from_dict(loaded.analysis_views['fft']['views'][0])
    assert restored.panes[0].viewport_origin == {'x': 'user', 'y': 'home'}
    assert restored.panes[0].xlim == (1., 2.)
    assert restored.panes[0].ylim == (3., 4.)
    assert restored.panes[1].viewport_origin == {'x': 'legacy', 'y': 'auto'}


def test_heatmap_basis_project_roundtrip_and_fid_remap(tmp_path):
    basis = {"version": 1, "policy_owner": "view_default", "source": ["f1", "vib"],
             "amplitude_mode": "amplitude_db", "reference": 1.23456789012345,
             "unit": "N", "quantity": "force"}
    view = AnalysisViewState(name="Heatmap", tab_color="#2d7ff9",
                             params={"z_auto": False, "z_floor": -80.123456789, "z_ceiling": 0.123456789},
                             panes=[PaneState(sources=[("f1", "vib")], heatmap_color_basis=basis)])
    doc = ProjectDocument(active_file="f1", current_mode="fft_time",
                          analysis_views={"fft_time": {"active": 0, "views": [view.to_dict()]}})
    path = tmp_path / "heatmap.tlproj"
    save_project_to_json(doc, path)
    loaded = load_project_from_json(path)
    remapped = remap_analysis_view_fids(loaded.analysis_views, {"f1": "new-file"})
    restored = AnalysisViewState.from_dict(remapped["fft_time"]["views"][0])
    assert restored.params == view.params
    assert restored.panes[0].heatmap_color_basis == dict(basis, source=["new-file", "vib"])
    assert loaded.analysis_views["fft_time"]["views"][0]["panes"][0]["heatmap_color_basis"] == basis
    missing = remap_analysis_view_fids(loaded.analysis_views, {})
    assert "heatmap_color_basis" not in missing["fft_time"]["views"][0]["panes"][0]
    assert missing["fft_time"]["views"][0]["params"] == view.params


def test_corrupt_heatmap_basis_remap_reports_local_loss(caplog):
    doc = _doc()
    pane = doc.analysis_views["fft"]["views"][0]["panes"][0]
    pane["heatmap_color_basis"] = {"reference": False}
    with caplog.at_level("WARNING"):
        remapped = remap_analysis_view_fids(doc.analysis_views, {"f1": "new-file"})
        restored = AnalysisViewState.from_dict(remapped["fft"]["views"][0])
    assert restored.panes[0].heatmap_color_basis is None
    assert restored.panes[0].sources == [("new-file", "vib")]
    assert sum("heatmap_color_basis" in record.message for record in caplog.records) == 1
