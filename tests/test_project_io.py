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


def test_project_save_is_same_directory_atomic_replace(tmp_path, monkeypatch):
    path = tmp_path / "session.tlproj"
    replaced = []
    original_replace = pio.os.replace

    def observe_replace(source, target):
        source = type(path)(source)
        target = type(path)(target)
        assert source.parent == path.parent
        assert source.exists()
        assert json.loads(source.read_text(encoding="utf-8"))["schema_version"] == 3
        replaced.append((source, target))
        return original_replace(source, target)

    monkeypatch.setattr(pio.os, "replace", observe_replace)
    pio.save_project_to_json(_doc(), path)

    assert replaced and replaced[0][1] == path
    assert json.loads(path.read_text(encoding="utf-8"))["current_mode"] == "time"


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
    assert loaded.ultraview is None


def test_load_and_resave_drop_retired_wwt_display_fields_without_schema_bump(tmp_path):
    path = tmp_path / "legacy.tlproj"
    raw = {
        "schema_version": 3,
        "active_file": None,
        "current_mode": "time",
        "files": [],
        "views": [{
            "name": "Legacy WWT",
            "tab_color": "#2d7ff9",
            "x_viewport_intent": {"source": "wwt_native"},
            "axis_opts": {
                "native_ticks": {"x": {"major": 20.0}},
                "x_viewport_intent": {"source": "wwt_native"},
            },
        }],
        "view_manager": {},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = pio.load_project_from_json(path)
    assert "x_viewport_intent" not in loaded.views[0]
    assert "native_ticks" not in loaded.views[0]["axis_opts"]
    assert "x_viewport_intent" not in loaded.views[0]["axis_opts"]

    rewritten = tmp_path / "rewritten.tlproj"
    pio.save_project_to_json(loaded, rewritten)
    saved = json.loads(rewritten.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 3
    assert "x_viewport_intent" not in saved["views"][0]
    assert "native_ticks" not in saved["views"][0]["axis_opts"]


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
        "ylims": {
            '["f0","rpm"]': [0.0, 10.0],
            '["f1","spd"]': [1.0, 2.0],
            "[display] rpm": [3.0, 4.0],  # unparseable legacy key → kept
        },
        "axis_opts": {"x_axis": {"mode": "channel", "fid": "f1",
                                 "channel": "spd", "label": "spd"}},
    }
    # f0 -> f3 kept; f1 missing (absent from map) -> dropped
    out = pio.remap_view_fids([view], {"f0": "f3"})[0]
    assert out["checked"] == [["f3", "rpm"]]
    assert out["hidden_channels"] == [["f3", "rpm"]]
    assert out["colors"] == {'["f3","rpm"]': "#ff0000"}
    assert out["overlay_primary"] is None
    assert out["ylims"] == {
        '["f3","rpm"]': [0.0, 10.0],
        "[display] rpm": [3.0, 4.0],
    }
    assert out["axis_opts"]["x_axis"]["fid"] is None
    assert out["axis_opts"]["x_axis"]["mode"] == "time"
    assert out["axis_opts"]["x_axis"]["resolver"] is None


def test_remap_drops_retired_native_state_and_remaps_channel_axis_groups():
    view = {
        "name": "Legacy WWT",
        "tab_color": "#fff",
        "x_viewport_intent": {"source": "wwt_native"},
        "axis_opts": {
            "native_ticks": {"x": {"major": 20.0}},
            "x_viewport_intent": {"source": "wwt_native"},
            "channel_axis_groups": {
                '["old","force"]': "axis-force",
                '["missing","speed"]': "axis-speed",
                "malformed": "axis-bad",
            },
        },
        "curve_bindings": [{
            "binding_id": "record-only",
            "y_ref": {
                "kind": "wwt_record", "fid": "old", "record_index": 2,
                "channel": None,
            },
            "x_ref": {
                "kind": "wwt_record", "fid": "old", "record_index": 1,
                "channel": None,
            },
            "display_name": "Tolerance",
            "unit": "mm",
            "color": "#f00",
            "axis_id": "axis-force",
            "y_range": [-1.0, 1.0],
        }],
        "hidden_curve_binding_ids": ["record-only", "gone"],
    }

    out = pio.remap_view_fids([view], {"old": "new"})[0]

    assert "x_viewport_intent" not in out
    assert "native_ticks" not in out["axis_opts"]
    assert "x_viewport_intent" not in out["axis_opts"]
    assert out["axis_opts"]["channel_axis_groups"] == {
        '["new","force"]': "axis-force",
    }
    assert out["curve_bindings"][0]["x_ref"]["fid"] == "new"
    assert out["hidden_curve_binding_ids"] == ["record-only"]


def test_remap_ylims_skipped_when_absent():
    view = {"name": "V", "tab_color": "#fff", "checked": [["f0", "rpm"]]}
    out = pio.remap_view_fids([view], {"f0": "f9"})[0]
    assert out["checked"] == [["f9", "rpm"]]
    assert out.get("ylims", {}) == {}


def test_remap_migrates_legacy_channel_axis_to_exact_source():
    view = {
        "name": "Legacy",
        "checked": [],
        "axis_opts": {
            "x_axis": {
                "mode": "channel",
                "fid": "old-fid",
                "channel": "angle",
                "label": "Angle",
            }
        },
    }

    out = pio.remap_view_fids([view], {"old-fid": "new-fid"})[0]

    assert out["axis_opts"]["x_axis"] == {
        "mode": "channel",
        "resolver": "exact_source",
        "fid": "new-fid",
        "channel": "angle",
        "label": "Angle",
    }


def test_remap_preserves_per_source_name_without_a_fid():
    view = {
        "name": "Logical",
        "checked": [],
        "axis_opts": {
            "x_axis": {
                "mode": "channel",
                "resolver": "per_source_name",
                "fid": None,
                "channel": "angle",
                "label": "Angle",
            }
        },
    }

    out = pio.remap_view_fids([view], {})[0]

    assert out["axis_opts"]["x_axis"] == view["axis_opts"]["x_axis"]


@pytest.mark.parametrize(
    "x_axis",
    [
        {"mode": "channel", "resolver": "unknown", "channel": "angle"},
        {"mode": "channel", "resolver": "per_source_name", "channel": None},
        {
            "mode": "channel",
            "resolver": "exact_source",
            "fid": None,
            "channel": "angle",
        },
    ],
)
def test_remap_degrades_malformed_channel_axis_to_time(x_axis):
    view = {
        "name": "Malformed",
        "checked": [],
        "axis_opts": {"x_axis": x_axis},
    }

    out = pio.remap_view_fids([view], {})[0]

    assert out["axis_opts"]["x_axis"] == {
        "mode": "time",
        "resolver": None,
        "fid": None,
        "channel": None,
        "label": x_axis.get("label", ""),
    }


def test_remap_identity_when_map_matches():
    view = {"name": "V", "tab_color": "#fff",
            "checked": [["f0", "rpm"]],
            "hidden_channels": [["f0", "rpm"]],
            "colors": {}, "overlay_primary": None}
    out = pio.remap_view_fids([view], {"f0": "f0"})[0]
    assert out["checked"] == [["f0", "rpm"]]
    assert out["hidden_channels"] == [["f0", "rpm"]]


def test_remap_rewrites_directional_frf_time_view_signature():
    view = {
        "name": "Renamed by user",
        "checked": [["f0", "command"], ["f0", "response"]],
        "hidden_channels": [],
        "colors": {},
        "overlay_primary": None,
        "axis_opts": {
            "x_axis": {"mode": "time"},
            "frf_source_signature": {
                "input": ["f0", "command"],
                "output": ["f0", "response"],
                "effective_time_range": [1.0, 2.0],
            },
        },
    }

    out = pio.remap_view_fids([view], {"f0": "f9"})[0]

    assert out["axis_opts"]["frf_source_signature"] == {
        "input": ["f9", "command"],
        "output": ["f9", "response"],
        "effective_time_range": [1.0, 2.0],
    }


def test_remap_drops_frf_time_view_signature_when_either_endpoint_is_missing():
    view = {
        "name": "FRF",
        "checked": [["f0", "command"], ["f1", "response"]],
        "hidden_channels": [],
        "colors": {},
        "overlay_primary": None,
        "axis_opts": {
            "frf_source_signature": {
                "input": ["f0", "command"],
                "output": ["f1", "response"],
                "effective_time_range": [1.0, 2.0],
            },
        },
    }

    out = pio.remap_view_fids([view], {"f0": "f9"})[0]

    assert "frf_source_signature" not in out["axis_opts"]


def test_remap_rewrites_remarks_fid_drops_missing_and_keeps_cursor_placement():
    view = {
        "name": "V",
        "tab_color": "#fff",
        "checked": [["f0", "rpm"], ["f1", "spd"]],
        "remarks": [
            {
                "source": ["f0", "rpm"],
                "x": 1.25,
                "y": 3.5,
                "label_dx": 0.08,
                "label_dy": 0.4,
                "note": "keep",
            },
            {
                "source": ["f1", "spd"],
                "x": 2.0,
                "y": 4.0,
                "label_dx": 0.0,
                "label_dy": 0.1,
            },
        ],
        "cursor_placement": {"ax": 1.0, "bx": 2.5, "placing": True},
        "cursor_mode": "dual",
    }

    out = pio.remap_view_fids([view], {"f0": "f9"})[0]

    assert out["remarks"] == [
        {
            "source": ["f9", "rpm"],
            "x": 1.25,
            "y": 3.5,
            "label_dx": 0.08,
            "label_dy": 0.4,
            "note": "keep",
        }
    ]
    assert out["cursor_placement"] == {"ax": 1.0, "bx": 2.5, "placing": True}


def test_ultraview_field_is_last_and_positional_construction_unchanged():
    import dataclasses

    names = [item.name for item in dataclasses.fields(pio.ProjectDocument)]
    assert names[-1] == "ultraview"
    doc = pio.ProjectDocument("f0", "fft")
    assert doc.active_file == "f0"
    assert doc.current_mode == "fft"
    assert doc.ultraview is None
    assert pio.SCHEMA_VERSION == 3


def test_ultraview_board_roundtrips_without_runtime_keys(tmp_path):
    path = tmp_path / "uv.tlproj"
    payload = {
        "schema": 1,
        "board": {
            "board_id": "board-keep",
            "name": "全局对比-A",
            "layout_id": "grid_2x2",
            "primary_ratio": 0.55,
            "show_titles": False,
            "show_sources": True,
            "placements": [
                {"slot_id": "tl", "section": "time", "view_id": "view-time"},
                {"slot_id": "tr", "section": "fft", "view_id": "missing-but-legal"},
            ],
            "unplaced": [
                {"section": "frf", "view_id": "tray-ref"},
            ],
        },
    }
    doc = _doc()
    doc.ultraview = payload
    pio.save_project_to_json(doc, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 3
    assert raw["ultraview"]["board"]["name"] == "全局对比-A"
    forbidden = {
        "digest", "selected", "presentation", "image", "qimage",
        "captured_digest", "runtime", "lru", "filter", "focus",
        "snapshot", "left_snapshot", "inspector_snapshot",
    }

    def _walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in forbidden, key
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(raw["ultraview"])
    loaded = pio.load_project_from_json(path)
    assert loaded.ultraview["board"]["placements"][1]["view_id"] == "missing-but-legal"
    assert loaded.ultraview["board"]["unplaced"][0]["view_id"] == "tray-ref"
    assert loaded.ultraview["board"]["show_titles"] is False
    assert loaded.ultraview["board"]["layout_id"] == "grid_2x2"


def test_unknown_current_mode_falls_back_to_time(tmp_path):
    path = tmp_path / "mode.tlproj"
    pio.save_project_to_json(_doc(), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["current_mode"] = "ultraview"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = pio.load_project_from_json(path)
    assert loaded.current_mode == "time"


def test_non_object_ultraview_block_loads_as_none(tmp_path):
    path = tmp_path / "bad-uv.tlproj"
    pio.save_project_to_json(_doc(), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["ultraview"] = ["not", "a", "mapping"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = pio.load_project_from_json(path)
    assert loaded.ultraview is None


def test_old_reader_drops_ultraview_on_resave(tmp_path):
    path = tmp_path / "new.tlproj"
    doc = _doc()
    doc.ultraview = {"schema": 1, "board": {"name": "保留"}}
    pio.save_project_to_json(doc, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("ultraview", None)
    old_path = tmp_path / "old-reader.tlproj"
    old_path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = pio.load_project_from_json(old_path)
    assert loaded.ultraview is None
    rewrite = tmp_path / "rewritten.tlproj"
    pio.save_project_to_json(loaded, rewrite)
    rewritten = json.loads(rewrite.read_text(encoding="utf-8"))
    assert rewritten["ultraview"] is None


def test_schema_v3_roundtrips_file_and_channel_order(tmp_path):
    path = tmp_path / "ordered.tlproj"
    doc = pio.ProjectDocument(
        active_file="f1",
        current_mode="time",
        files=[
            pio.ProjectFileRef(
                fid="f1",
                path_abs="/data/b.mf4",
                path_rel="b.mf4",
                fs=1000.0,
                time_source="generated",
                channel_order=["torque", "speed"],
            ),
            pio.ProjectFileRef(
                fid="f0a",
                path_abs="/data/grouped.hdf",
                path_rel="grouped.hdf",
                fs=1000.0,
                time_source="generated",
                channel_order=["x", "y"],
            ),
            pio.ProjectFileRef(
                fid="f0b",
                path_abs="/data/grouped.hdf",
                path_rel="grouped.hdf",
                fs=2000.0,
                time_source="generated",
                channel_order=["z"],
            ),
        ],
        views=[],
        view_manager={},
    )
    pio.save_project_to_json(doc, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 3
    assert [entry["fid"] for entry in raw["files"]] == ["f1", "f0a", "f0b"]
    assert raw["files"][0]["channel_order"] == ["torque", "speed"]
    assert raw["files"][1]["channel_order"] == ["x", "y"]
    assert raw["files"][2]["channel_order"] == ["z"]

    loaded = pio.load_project_from_json(path)
    assert [ref.fid for ref in loaded.files] == ["f1", "f0a", "f0b"]
    assert loaded.files[0].channel_order == ["torque", "speed"]
    assert loaded.files[1].channel_order == ["x", "y"]
    assert loaded.files[2].channel_order == ["z"]


def test_schema_v1_and_v2_default_missing_channel_order(tmp_path):
    for version in (1, 2):
        path = tmp_path / f"old-v{version}.tlproj"
        raw = {
            "schema_version": version,
            "active_file": "f0",
            "current_mode": "time",
            "files": [
                {
                    "fid": "f0",
                    "path_abs": "/data/a.mf4",
                    "path_rel": "a.mf4",
                    "fs": 1000.0,
                    "time_source": "generated",
                }
            ],
            "views": [],
            "view_manager": {},
        }
        path.write_text(json.dumps(raw), encoding="utf-8")
        loaded = pio.load_project_from_json(path)
        assert loaded.files[0].channel_order == []
