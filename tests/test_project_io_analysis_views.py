"""project_io: analysis_views persistence + fid remap."""
from mf4_analyzer.ui.project_io import (
    ProjectDocument, load_project_from_json, remap_analysis_view_fids,
    save_project_to_json,
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
