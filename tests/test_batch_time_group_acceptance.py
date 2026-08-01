from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from mf4_analyzer.batch import BatchRunner
from mf4_analyzer.batch_manifest import load_batch_manifest
from mf4_analyzer.batch_time_group_acceptance import (
    _inspect_mode,
    _make_sources,
    _preset,
    _validated_generated_paths,
)


ROOT = Path(__file__).resolve().parents[1]


def _grouped_result(tmp_path: Path, group_by: str):
    files = _make_sources(tmp_path / "sources")
    return BatchRunner(files).run(_preset(group_by), tmp_path / group_by)


def _mutated_result(result, mutate):
    manifest_path = Path(result.manifest_path)
    manifest = load_batch_manifest(manifest_path)
    mutate(manifest)
    mutated_path = manifest_path.with_name(f"mutated-{manifest_path.name}")
    mutated_path.write_text(json.dumps(manifest), encoding="utf-8")
    return SimpleNamespace(
        status=result.status,
        blocked=result.blocked,
        manifest_path=str(mutated_path),
    )


def test_inspect_mode_rejects_alias_data_artifact(tmp_path):
    result = _grouped_result(tmp_path, "channel")

    aliased = _mutated_result(
        result,
        lambda manifest: manifest["entries"][1]["artifacts"].__setitem__(
            "data", dict(manifest["entries"][0]["artifacts"]["data"])
        ),
    )

    with pytest.raises(RuntimeError, match="data artifact paths are not unique"):
        _inspect_mode(
            aliased,
            "channel",
            expected_directory=Path(aliased.manifest_path).parent,
        )


def test_inspect_mode_rejects_alias_group_image_artifact(tmp_path):
    result = _grouped_result(tmp_path, "source")

    aliased = _mutated_result(
        result,
        lambda manifest: manifest["render_groups"][1].__setitem__(
            "artifact", dict(manifest["render_groups"][0]["artifact"])
        ),
    )

    with pytest.raises(RuntimeError, match="image artifact paths are not unique"):
        _inspect_mode(
            aliased,
            "source",
            expected_directory=Path(aliased.manifest_path).parent,
        )


def test_inspect_mode_rejects_swapped_group_artifact_identities(tmp_path):
    result = _grouped_result(tmp_path, "channel")

    def swap_group_artifacts(manifest):
        first, second = manifest["render_groups"]
        first["artifact"], second["artifact"] = (
            dict(second["artifact"]),
            dict(first["artifact"]),
        )

    swapped = _mutated_result(result, swap_group_artifacts)

    with pytest.raises(RuntimeError, match="group artifact identity mismatch"):
        _inspect_mode(
            swapped,
            "channel",
            expected_directory=Path(swapped.manifest_path).parent,
        )


def test_inspect_mode_rejects_manifest_outside_expected_mode_directory(tmp_path):
    result = _grouped_result(tmp_path, "source")

    with pytest.raises(RuntimeError, match="manifest directory mismatch"):
        _inspect_mode(
            result,
            "source",
            expected_directory=tmp_path / "wrong-mode-directory",
        )


def test_inspect_mode_rejects_artifact_outside_manifest_directory(tmp_path):
    result = _grouped_result(tmp_path, "none")
    manifest = load_batch_manifest(result.manifest_path)
    original = Path(manifest["entries"][0]["artifacts"]["data"]["path"])
    outside = tmp_path / "outside.csv"
    outside.write_bytes(original.read_bytes())

    escaped = _mutated_result(
        result,
        lambda payload: payload["entries"][0]["artifacts"]["data"].update(
            path=str(outside)
        ),
    )

    with pytest.raises(RuntimeError, match="data artifact outside manifest directory"):
        _inspect_mode(
            escaped,
            "none",
            expected_directory=Path(escaped.manifest_path).parent,
        )


def test_generated_path_validation_rejects_aliases_before_sorting(tmp_path):
    artifact = tmp_path / "artifact.csv"
    artifact.write_text("time,value\n0,1\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="generated paths contain aliases"):
        _validated_generated_paths([artifact, artifact], expected_count=1)


@pytest.mark.parametrize("group_by", ["source", "channel"])
def test_inspect_mode_rejects_groups_with_the_wrong_dimension(tmp_path, group_by):
    result = _grouped_result(tmp_path, group_by)

    def regroup_by_opposite_dimension(manifest):
        entries = manifest["entries"]
        key = "channel" if group_by == "source" else "source"
        dimension = lambda entry: (
            entry["channel"]
            if key == "channel"
            else entry["source"]["identity"]
        )
        buckets = {}
        for entry in entries:
            buckets.setdefault(dimension(entry), []).append(entry)
        for group, members in zip(manifest["render_groups"], buckets.values()):
            group["members"] = [
                {
                    "task_id": entry["task_id"],
                    "source": {
                        field: entry["source"][field]
                        for field in ("identity", "path", "size", "mtime_ns")
                    },
                }
                for entry in members
            ]

    malformed = _mutated_result(result, regroup_by_opposite_dimension)

    with pytest.raises(RuntimeError, match=f"{group_by} render-group semantics"):
        _inspect_mode(
            malformed,
            group_by,
            expected_directory=Path(malformed.manifest_path).parent,
        )


def _source_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    return environment


def test_group_acceptance_preset_exercises_subplot_with_channel_x():
    preset = _preset("source")

    assert preset.params == {
        "render_group_by": "source",
        "render_layout": "subplot",
        "x_source": "channel",
        "x_channel": "position",
    }


def test_group_acceptance_cli_proves_modes_linkage_and_deleted_image_resume(
    tmp_path,
):
    output_directory = tmp_path / "acceptance"
    result_json = tmp_path / "acceptance.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mf4_analyzer.batch_time_group_acceptance",
            "--output-dir",
            str(output_directory),
            "--result-json",
            str(result_json),
        ],
        cwd=ROOT,
        env=_source_environment(),
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(result_json.read_text(encoding="utf-8"))
    assert evidence["status"] == "success"
    assert evidence["source_count"] == 2
    assert {Path(path).suffix for path in evidence["source_paths"]} == {".csv"}
    assert all(Path(path).is_file() for path in evidence["source_paths"])
    assert evidence["render_contract"] == {
        "render_layout": "subplot",
        "x_channel": "position",
        "x_source": "channel",
        "subplot_geometry_checked": True,
        "subplot_text_overlaps": [],
    }
    assert evidence["modes"] == {
        "none": {
            "data_count": 4,
            "group_count": 0,
            "image_count": 4,
            "member_linkage": True,
            "task_count": 4,
        },
        "source": {
            "data_count": 4,
            "group_count": 2,
            "image_count": 2,
            "member_linkage": True,
            "task_count": 4,
        },
        "channel": {
            "data_count": 4,
            "group_count": 2,
            "image_count": 2,
            "member_linkage": True,
            "task_count": 4,
        },
    }
    assert evidence["resume"] == {
        "channel_csv_set_unchanged": True,
        "channel_png_set_unchanged": True,
        "csv_bytes_unchanged": True,
        "csv_mtimes_unchanged": True,
        "data_artifact_facts_unchanged": True,
        "data_artifact_paths_unchanged": True,
        "deleted_image_recreated": True,
        "group_artifact_links_unchanged": True,
        "healthy_image_bytes_unchanged": True,
        "healthy_image_mtime_unchanged": True,
        "resumed_entry_statuses": {"resumed": 4},
        "resumed_manifest_inspected": True,
    }
    generated_paths = [Path(path) for path in evidence["generated_paths"]]
    assert len(generated_paths) == 26
    assert len(generated_paths) == len(set(generated_paths))
    assert all(path.is_file() and path.stat().st_size > 0 for path in generated_paths)
