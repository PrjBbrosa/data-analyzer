"""M5 project migration: schema 6 is opt-in, legacy projects stay legacy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mf4_analyzer.io.source_adapters import DEFAULT_SOURCE_ADAPTER_REGISTRY
from mf4_analyzer.ui.project_io import (
    NATIVE_POLICY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    CHANNEL_EDIT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    ProjectDocument,
    ProjectFileRef,
    UnsupportedProjectVersion,
    UpgradeCancelled,
    UpgradeRefused,
    apply_native_upgrade,
    canonical_project_digest,
    legacy_shared_axis_notice,
    load_project_from_json,
    preview_native_upgrade,
    save_project_to_json,
    save_upgraded_project,
)


def _doc(files, **kwargs):
    return ProjectDocument(
        active_file="f1",
        current_mode="time",
        files=files,
        views=kwargs.get("views", [{"name": "时域", "xlim": [0.2, 1.5], "ylims": {"y": [0, 3]}}]),
        view_manager={"active": 0, "split_pairs": {}},
        analysis_views={"fft": {"active": 0, "views": [{"view_id": "a", "xlim": [1, 9]}]}},
    )


def _file(**kwargs):
    payload = dict(
        fid="f1",
        path_abs="/data/steer.mf4",
        path_rel="steer.mf4",
        fs=1000.0,
        time_source="column",
        channel_order=["Torque"],
    )
    payload.update(kwargs)
    return ProjectFileRef(**payload)


def _identity(token="phys:torque", name="TorqueSensor"):
    return {
        "token": token,
        "group": 0,
        "index": 2,
        "parent": [],
        "coordinates": [],
        "original_name": name,
    }


def test_ordinary_projects_still_write_schema_4_or_5(tmp_path):
    plain = _doc([_file()])
    edited = _doc([_file(channel_edits=[{
        "op": "derive", "name": "abs_tq", "unit": "Nm",
        "kind": "single", "fn": "abs", "src": "Torque", "param": None,
    }])])
    save_project_to_json(plain, tmp_path / "plain.tlproj")
    save_project_to_json(edited, tmp_path / "edited.tlproj")
    plain_raw = json.loads((tmp_path / "plain.tlproj").read_text(encoding="utf-8"))
    edited_raw = json.loads((tmp_path / "edited.tlproj").read_text(encoding="utf-8"))
    assert plain_raw["schema_version"] == SCHEMA_VERSION == 4
    assert edited_raw["schema_version"] == CHANNEL_EDIT_SCHEMA_VERSION == 5
    assert "sampling_policy" not in plain_raw["files"][0]
    assert "sampling_policy" not in edited_raw["files"][0]
    assert NATIVE_POLICY_SCHEMA_VERSION == 6
    assert SUPPORTED_SCHEMA_VERSIONS == {1, 2, 3, 4, 5, 6}


def test_native_policy_writes_schema_6_without_samples(tmp_path):
    doc = _doc([_file(
        sampling_policy="native",
        physical_keys=[_identity(name="Torque")],
        alignment_intents=[{
            "kind": "pair",
            "axis": "clk-a",
            "method": "direct",
            "segment": 0,
            "representation": "physical",
            "status": "derived_intent",
        }],
    )])
    path = tmp_path / "native.tlproj"
    save_project_to_json(doc, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 6
    blob = path.read_text(encoding="utf-8")
    for banned in ("\"samples\"", "\"cache\"", "\"process_token\"", "\"temp_path\""):
        assert banned not in blob
    loaded = load_project_from_json(path)
    row = loaded.files[0]
    assert row.sampling_policy == "native"
    assert row.physical_keys[0]["token"] == "phys:torque"
    assert row.alignment_intents[0]["method"] == "direct"
    assert loaded.views[0]["xlim"] == [0.2, 1.5]
    assert legacy_shared_axis_notice(loaded) is None


def test_unknown_schema_is_still_rejected(tmp_path):
    path = tmp_path / "future.tlproj"
    path.write_text(json.dumps({"schema_version": 7, "files": []}), encoding="utf-8")
    with pytest.raises(UnsupportedProjectVersion) as caught:
        load_project_from_json(path)
    assert caught.value.schema_version == 7


def test_schema_6_rejects_stored_samples(tmp_path):
    path = tmp_path / "samples.tlproj"
    path.write_text(json.dumps({
        "schema_version": 6,
        "files": [{
            "fid": "f1",
            "path_abs": "/data/steer.mf4",
            "path_rel": None,
            "fs": 1.0,
            "time_source": "column",
            "sampling_policy": "native",
            "samples": [1, 2, 3],
        }],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="样本|缓存"):
        load_project_from_json(path)


def test_old_project_reopens_as_legacy_and_resaves_without_schema_6(tmp_path):
    path = tmp_path / "old.tlproj"
    save_project_to_json(_doc([_file(time_source="manual", fs=1234.0)]), path)
    loaded = load_project_from_json(path)
    notice = legacy_shared_axis_notice(loaded)
    assert notice and "公共轴" in notice
    assert loaded.files[0].sampling_policy in ("", "legacy")
    again = tmp_path / "old-again.tlproj"
    save_project_to_json(loaded, again)
    raw = json.loads(again.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 4
    assert "sampling_policy" not in raw["files"][0]


def test_upgrade_preview_can_be_cancelled_and_does_not_guess_names(tmp_path):
    source = tmp_path / "session.tlproj"
    measurement = tmp_path / "steer.mf4"
    measurement.write_bytes(b"mf4-bytes")
    doc = _doc([_file(
        path_abs=str(measurement),
        time_source="manual",
        fs=800.0,
        channel_order=["Torque"],
        channel_edits=[
            {
                "op": "derive", "name": "d_tq", "unit": "Nm/s",
                "kind": "single", "fn": "derivative", "src": "Torque", "param": None,
            },
            {
                "op": "derive", "name": "sum", "unit": "",
                "kind": "dual", "fn": "add", "a": "Torque", "b": "Speed",
            },
        ],
    )])
    doc.views[0]["render_cache"] = [1, 2, 3]
    save_project_to_json(doc, source)
    before = source.read_bytes()
    digest = canonical_project_digest(doc)
    identities = {"f1": [_identity(name="Torque")]}
    preview = preview_native_upgrade(doc, identities)
    assert canonical_project_digest(doc) == digest
    assert any("Torque" in item for item in preview.unresolved)
    assert any(item.get("status") == "unapplied" for item in preview.fs_overrides)
    assert any(item.get("name") == "d_tq" and item.get("axis") == "inherit" for item in preview.formulas)
    assert any(item.get("name") == "sum" and item.get("status") == "unapplied" for item in preview.formulas)
    with pytest.raises(UpgradeCancelled):
        apply_native_upgrade(doc, identities, accept=False)
    assert measurement.read_bytes() == b"mf4-bytes"
    assert source.read_bytes() == before
    upgraded = apply_native_upgrade(
        doc, identities, accept=True, bindings={("f1", "Torque"): "phys:torque"},
    )
    assert doc.files[0].sampling_policy in ("", "legacy")
    assert upgraded.files[0].sampling_policy == "native"
    assert upgraded.files[0].physical_keys[0]["token"] == "phys:torque"
    assert upgraded.views[0]["xlim"] == [0.2, 1.5]
    assert "render_cache" not in upgraded.views[0]
    formulas = {item["name"]: item for item in upgraded.files[0].channel_edits if item["op"] == "derive"}
    assert formulas["d_tq"]["axis"] == "inherit"
    assert formulas["d_tq"]["apply_status"] == "derived_intent"
    assert formulas["sum"]["apply_status"] == "unapplied"
    intents = upgraded.files[0].alignment_intents
    assert any(item["kind"] == "legacy_fs_reinterpret" and item["status"] == "unapplied" for item in intents)
    with pytest.raises(UpgradeRefused):
        save_upgraded_project(
            upgraded, source, source_project=source, source_files=[measurement],
        )
    with pytest.raises(UpgradeRefused):
        save_upgraded_project(
            upgraded, measurement, source_project=source, source_files=[measurement],
        )
    dest = tmp_path / "upgraded.tlproj"
    save_upgraded_project(
        upgraded, dest, source_project=source, source_files=[measurement],
    )
    assert source.read_bytes() == before
    assert measurement.read_bytes() == b"mf4-bytes"
    assert json.loads(dest.read_text(encoding="utf-8"))["schema_version"] == 6


def test_exact_display_name_is_not_enough_to_bind(tmp_path):
    doc = _doc([_file(channel_order=["Torque"])])
    identities = {"f1": [_identity(name="Torque")]}
    preview = preview_native_upgrade(doc, identities)
    assert preview.unresolved
    upgraded = apply_native_upgrade(doc, identities, accept=True)
    assert upgraded.files[0].physical_keys == []
    assert "Torque" in upgraded.files[0].suspended_channels


def test_product_open_path_is_still_load_mf4():
    adapter = next(
        item for item in DEFAULT_SOURCE_ADAPTER_REGISTRY.adapters if item.key == "mdf"
    )
    assert adapter.loader_name == "load_mf4"
    mixin = Path("mf4_analyzer/ui/main_window/_project_io_mixin.py").read_text(encoding="utf-8")
    assert '{".mf4": "load_mf4", ".mdf": "load_mf4"' in mixin
    assert "load_mf4_native" not in mixin.split("methods = {", 1)[1].split("}", 1)[0]
