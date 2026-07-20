# tests/test_project_io.py
import json
import pytest
from mf4_analyzer.ui import project_io as pio


def _doc():
    return pio.ProjectDocument(
        active_file="f0",
        current_mode="time",
        files=[
            pio.ProjectFileRef(fid="f0", path_abs="/data/a.mf4",
                               path_rel="a.mf4", fs=2000.0, time_source="manual"),
        ],
        views=[{"name": "View 1", "tab_color": "#2d7ff9", "checked": [["f0", "rpm"]]}],
        view_manager={"active": 0, "split_pairs": {}},
    )


def test_roundtrip(tmp_path):
    path = tmp_path / "s.tlproj"
    pio.save_project_to_json(_doc(), path)
    loaded = pio.load_project_from_json(path)
    assert loaded.active_file == "f0"
    assert loaded.current_mode == "time"
    assert loaded.files[0].fid == "f0"
    assert loaded.files[0].fs == 2000.0
    assert loaded.files[0].time_source == "manual"
    assert loaded.views[0]["name"] == "View 1"
    assert loaded.view_manager["active"] == 0


def test_schema_version_written(tmp_path):
    path = tmp_path / "s.tlproj"
    pio.save_project_to_json(_doc(), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == pio.SCHEMA_VERSION


def test_filter_block_roundtrips_in_schema_v2(tmp_path):
    path = tmp_path / "s.tlproj"
    doc = _doc()
    doc.filter = {
        "enabled": True,
        "spec": {
            "kind": "band",
            "order": 6,
            "cutoff": 0.0,
            "cutoff_lo": 12.5,
            "cutoff_hi": 345.0,
        },
        "show_original": False,
        "show_filtered": True,
    }

    pio.save_project_to_json(doc, path)
    loaded = pio.load_project_from_json(path)

    assert loaded.filter == doc.filter


def test_schema_v1_without_filter_loads_as_filter_none(tmp_path):
    path = tmp_path / "old.tlproj"
    raw = {
        "schema_version": 1,
        "active_file": None,
        "current_mode": "time",
        "files": [],
        "views": [],
        "view_manager": {},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = pio.load_project_from_json(path)

    assert loaded.filter is None


def test_unknown_version_rejected(tmp_path):
    path = tmp_path / "s.tlproj"
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    with pytest.raises(pio.UnsupportedProjectVersion):
        pio.load_project_from_json(path)


def test_resolve_prefers_relative(tmp_path):
    (tmp_path / "data").mkdir()
    real = tmp_path / "data" / "a.csv"
    real.write_text("x", encoding="utf-8")
    proj = tmp_path / "s.tlproj"
    ref = pio.ProjectFileRef(fid="f0", path_abs="/gone/a.csv",
                             path_rel="data/a.csv", fs=1000.0, time_source="generated")
    assert pio.resolve_file_path(ref, proj) == real.resolve()


def test_resolve_falls_back_to_abs(tmp_path):
    real = tmp_path / "b.csv"
    real.write_text("x", encoding="utf-8")
    proj = tmp_path / "s.tlproj"
    ref = pio.ProjectFileRef(fid="f0", path_abs=str(real),
                             path_rel="missing/b.csv", fs=1000.0, time_source="generated")
    assert pio.resolve_file_path(ref, proj) == real


def test_resolve_missing_returns_none(tmp_path):
    proj = tmp_path / "s.tlproj"
    ref = pio.ProjectFileRef(fid="f0", path_abs="/gone/x.csv",
                             path_rel="also/gone.csv", fs=1000.0, time_source="generated")
    assert pio.resolve_file_path(ref, proj) is None


def test_remap_rewrites_and_drops():
    view = {
        "name": "V", "tab_color": "#fff",
        "checked": [["f0", "rpm"], ["f1", "spd"]],
        "hidden_channels": [["f0", "rpm"], ["f1", "spd"]],
        "colors": {'["f0","rpm"]': "#ff0000", '["f1","spd"]': "#00ff00"},
        "overlay_primary": ["f1", "spd"],
        "ylims": {"[a] rpm": [0.0, 10.0]},
        "axis_opts": {"x_axis": {"mode": "channel", "fid": "f1",
                                 "channel": "spd", "label": "spd"}},
    }
    # f0 -> f3 kept; f1 missing (absent from map) -> dropped
    out = pio.remap_view_fids([view], {"f0": "f3"})[0]
    assert out["checked"] == [["f3", "rpm"]]
    assert out["hidden_channels"] == [["f3", "rpm"]]
    assert out["colors"] == {'["f3","rpm"]': "#ff0000"}
    assert out["overlay_primary"] is None
    assert out["ylims"] == {"[a] rpm": [0.0, 10.0]}          # untouched
    assert out["axis_opts"]["x_axis"]["fid"] is None
    assert out["axis_opts"]["x_axis"]["mode"] == "time"


def test_remap_identity_when_map_matches():
    view = {"name": "V", "tab_color": "#fff",
            "checked": [["f0", "rpm"]],
            "hidden_channels": [["f0", "rpm"]],
            "colors": {}, "overlay_primary": None}
    out = pio.remap_view_fids([view], {"f0": "f0"})[0]
    assert out["checked"] == [["f0", "rpm"]]
    assert out["hidden_channels"] == [["f0", "rpm"]]
