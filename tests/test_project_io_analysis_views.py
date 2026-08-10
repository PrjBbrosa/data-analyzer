"""project_io: analysis_views persistence + fid remap."""
from mf4_analyzer.ui.analysis_view_state import (
    AnalysisViewState,
    PaneState,
    analysis_view_has_sources,
)
from mf4_analyzer.ui.project_io import (
    ProjectDocument, collect_dropped_analysis_refs, load_project_from_json,
    remap_analysis_view_fids, save_project_to_json,
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
    assert d["schema"] == 7

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
