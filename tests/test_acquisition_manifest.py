import json

import pytest

from mf4_analyzer.acquisition.manifest import (
    Mf4DatasetEntry,
    load_manifest,
    resolve_entry_path,
    select_entries,
    sha256_file,
)


def test_load_manifest_normalizes_entries(tmp_path):
    sample = tmp_path / "sample.mf4"
    sample.write_bytes(b"abc")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "x04c-low-temp",
                        "path": str(sample),
                        "path_kind": "local",
                        "sets": ["smoke", "golden"],
                        "vehicle": "X04C_PPV_01",
                        "platform": "X04C",
                        "scenario": "low_temp_low_tire_pressure",
                        "issue_tags": ["ripple"],
                        "expected_channels": ["vehicle_speed"],
                        "sha256": sha256_file(sample),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)

    assert entries == [
        Mf4DatasetEntry(
            id="x04c-low-temp",
            path=str(sample),
            path_kind="local",
            sets=("smoke", "golden"),
            vehicle="X04C_PPV_01",
            platform="X04C",
            scenario="low_temp_low_tire_pressure",
            issue_tags=("ripple",),
            expected_channels=("vehicle_speed",),
            sha256=sha256_file(sample),
            required=True,
        )
    ]


def test_select_entries_filters_by_dataset(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"id": "a", "path": "a.mf4", "sets": ["smoke"], "required": False},
                    {"id": "b", "path": "b.mf4", "sets": ["golden"], "required": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)

    assert [entry.id for entry in select_entries(entries, "smoke")] == ["a"]


def test_load_manifest_rejects_missing_id(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"version": 1, "entries": [{"path": "a.mf4", "sets": ["smoke"]}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="entry id is required"):
        load_manifest(manifest)


def test_resolve_entry_path_handles_relative_to_manifest(tmp_path):
    manifest = tmp_path / "data" / "manifest.local.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "rel",
                        "path": "../golden/x.mf4",
                        "sets": ["smoke"],
                        "required": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    entries = load_manifest(manifest)

    resolved = resolve_entry_path(entries[0], manifest_path=manifest)

    assert resolved == (tmp_path / "golden" / "x.mf4").resolve()


def test_load_manifest_rejects_unknown_path_kind(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"id": "a", "path": "a.mf4", "sets": ["smoke"], "path_kind": "weird"}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="path_kind"):
        load_manifest(manifest)


def test_load_manifest_rejects_required_local_entry_without_sha256(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "needs-hash",
                        "path": "a.mf4",
                        "sets": ["smoke"],
                        "required": True,
                        "path_kind": "local",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="needs-hash.*sha256"):
        load_manifest(manifest)


def test_load_manifest_accepts_optional_entry_without_sha256(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "placeholder",
                        "path": "a.mf4",
                        "sets": ["smoke"],
                        "required": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)

    assert entries[0].sha256 is None


def test_load_manifest_accepts_external_entry_without_sha256(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "remote",
                        "path": "s3://bucket/key.mf4",
                        "sets": ["golden"],
                        "required": True,
                        "path_kind": "external",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)

    assert entries[0].sha256 is None
