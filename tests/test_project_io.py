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


def test_unknown_version_rejected(tmp_path):
    path = tmp_path / "s.tlproj"
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    with pytest.raises(pio.UnsupportedProjectVersion):
        pio.load_project_from_json(path)
