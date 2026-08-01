"""Source-runtime acceptance for grouped time-domain batch exports."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .batch import AnalysisPreset, BatchOutput, BatchRunner
from .batch_manifest import load_batch_manifest
from .io.file_data import FileData


_CHANNELS = ("speed", "accel")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _make_sources(directory: Path) -> dict[int, FileData]:
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[int, FileData] = {}
    time = np.arange(256, dtype=float) / 128.0
    for index in range(2):
        frame = pd.DataFrame(
            {
                "time": time,
                "speed": 40.0 + index + 3.0 * np.sin(2.0 * np.pi * time),
                "accel": (index + 1.0) * np.cos(4.0 * np.pi * time),
            }
        )
        path = directory / f"source-{index + 1}.csv"
        frame.to_csv(path, index=False)
        loaded = pd.read_csv(path)
        files[index] = FileData(
            path,
            loaded,
            list(loaded.columns),
            {"speed": "km/h", "accel": "m/s^2"},
            idx=index,
        )
    return files


def _preset(group_by: str, *, resume: bool = False) -> AnalysisPreset:
    params = {} if group_by == "none" else {"render_group_by": group_by}
    preset = AnalysisPreset.free_config(
        name=f"batch time group acceptance {group_by}",
        method="time",
        target_signals=_CHANNELS,
        params=params,
        outputs=BatchOutput(
            export_data=True,
            export_image=True,
            data_format="csv",
            image_format="png",
            image_size="custom",
            image_width=640,
            image_height=360,
            image_dpi=96,
            conflict_policy="auto_number",
            write_manifest=True,
            resume_policy="manifest" if resume else "none",
        ),
    )
    return replace(preset, file_ids=(0, 1))


def _verified_artifact_path(facts: object, expected_format: str) -> Path:
    if not isinstance(facts, dict):
        raise RuntimeError(f"missing {expected_format} artifact facts")
    path = Path(str(facts.get("path") or "")).resolve()
    content = path.read_bytes()
    if not content:
        raise RuntimeError(f"empty acceptance artifact: {path}")
    if facts.get("format") != expected_format:
        raise RuntimeError(f"wrong acceptance artifact format: {path}")
    if facts.get("size") != len(content):
        raise RuntimeError(f"wrong acceptance artifact size: {path}")
    if facts.get("checksum_status") != "complete":
        raise RuntimeError(f"incomplete acceptance checksum: {path}")
    if facts.get("sha256") != hashlib.sha256(content).hexdigest():
        raise RuntimeError(f"wrong acceptance artifact checksum: {path}")
    return path


def _inspect_mode(result, group_by: str) -> tuple[dict[str, object], list[Path]]:
    if result.status != "done" or result.blocked or result.manifest_path is None:
        raise RuntimeError(
            f"{group_by} run failed: status={result.status}; blocked={result.blocked}"
        )
    manifest_path = Path(result.manifest_path).resolve()
    manifest = load_batch_manifest(manifest_path)
    entries = manifest["entries"]
    groups = manifest.get("render_groups", [])
    if len(entries) != 4 or any(entry.get("status") != "done" for entry in entries):
        raise RuntimeError(f"{group_by} did not publish four done tasks")

    entry_by_id = {entry["task_id"]: entry for entry in entries}
    if len(entry_by_id) != 4:
        raise RuntimeError(f"{group_by} task identities are not unique")
    data_paths = [
        _verified_artifact_path(entry["artifacts"].get("data"), "csv")
        for entry in entries
    ]
    if group_by == "none":
        if groups or "render_groups" in manifest:
            raise RuntimeError("none mode unexpectedly wrote render groups")
        image_paths = [
            _verified_artifact_path(entry["artifacts"].get("image"), "png")
            for entry in entries
        ]
        linkage_ok = True
    else:
        image_paths = [
            _verified_artifact_path(group.get("artifact"), "png")
            for group in groups
        ]
        linked_ids = []
        linkage_ok = True
        for group in groups:
            if group.get("status") != "done" or group.get("group_by") != group_by:
                linkage_ok = False
                break
            for member in group.get("members", []):
                task_id = member.get("task_id")
                linked_ids.append(task_id)
                entry = entry_by_id.get(task_id)
                member_source = member.get("source") or {}
                entry_source = (entry or {}).get("source") or {}
                if entry is None or any(
                    member_source.get(field) != entry_source.get(field)
                    for field in ("identity", "size", "mtime_ns")
                ):
                    linkage_ok = False
        linkage_ok = linkage_ok and sorted(linked_ids) == sorted(entry_by_id)
    if not linkage_ok:
        raise RuntimeError(f"{group_by} manifest member linkage is incomplete")

    expected_images = 4 if group_by == "none" else 2
    expected_groups = 0 if group_by == "none" else 2
    if len(data_paths) != 4 or len(image_paths) != expected_images:
        raise RuntimeError(f"{group_by} artifact count mismatch")
    if len(groups) != expected_groups:
        raise RuntimeError(f"{group_by} render-group count mismatch")
    summary = {
        "task_count": len(entries),
        "data_count": len(data_paths),
        "image_count": len(image_paths),
        "group_count": len(groups),
        "member_linkage": linkage_ok,
    }
    return summary, [manifest_path, *data_paths, *image_paths]


def _snapshot(paths: list[Path]) -> dict[Path, tuple[bytes, int]]:
    return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}


def run(output_directory: Path, result_json: Path) -> int:
    """Run all grouping modes and persist machine-readable acceptance evidence."""

    output_directory = Path(output_directory).expanduser().resolve(strict=False)
    result_json = Path(result_json).expanduser().resolve(strict=False)
    run_root = output_directory / uuid.uuid4().hex
    try:
        files = _make_sources(run_root / "sources")
        modes: dict[str, dict[str, object]] = {}
        generated: list[Path] = [Path(fd.filepath).resolve() for fd in files.values()]
        manifests: dict[str, str] = {}
        channel_result = None
        channel_data_paths: list[Path] = []
        channel_image_paths: list[Path] = []

        for group_by in ("none", "source", "channel"):
            mode_directory = run_root / group_by
            result = BatchRunner(files).run(_preset(group_by), mode_directory)
            summary, paths = _inspect_mode(result, group_by)
            modes[group_by] = summary
            generated.extend(paths)
            manifests[group_by] = str(Path(result.manifest_path).resolve())
            if group_by == "channel":
                channel_result = result
                channel_manifest = load_batch_manifest(result.manifest_path)
                channel_data_paths = [
                    _verified_artifact_path(entry["artifacts"].get("data"), "csv")
                    for entry in channel_manifest["entries"]
                ]
                channel_image_paths = [
                    _verified_artifact_path(group.get("artifact"), "png")
                    for group in channel_manifest["render_groups"]
                ]

        if channel_result is None or not channel_image_paths:
            raise RuntimeError("channel grouping did not produce a resumable image")
        csv_before = _snapshot(channel_data_paths)
        deleted_image = channel_image_paths[0]
        deleted_image.unlink()
        resumed = BatchRunner(files).run(
            _preset("channel", resume=True),
            run_root / "channel",
            resume_manifest=channel_result.manifest_path,
        )
        if resumed.status != "done" or resumed.manifest_path is None:
            raise RuntimeError(
                f"channel resume failed: status={resumed.status}; blocked={resumed.blocked}"
            )
        csv_after = _snapshot(channel_data_paths)
        resume_facts = {
            "csv_bytes_unchanged": all(
                csv_after[path][0] == before[0]
                for path, before in csv_before.items()
            ),
            "csv_mtimes_unchanged": all(
                csv_after[path][1] == before[1]
                for path, before in csv_before.items()
            ),
            "deleted_image_recreated": (
                deleted_image.is_file() and deleted_image.stat().st_size > 0
            ),
            "resumed_task_count": sum(
                item.status == "resumed" for item in resumed.items
            ),
        }
        if resume_facts != {
            "csv_bytes_unchanged": True,
            "csv_mtimes_unchanged": True,
            "deleted_image_recreated": True,
            "resumed_task_count": 4,
        }:
            raise RuntimeError(f"channel resume evidence failed: {resume_facts}")
        resumed_manifest = Path(resumed.manifest_path).resolve()
        generated.extend((deleted_image, resumed_manifest))
        manifests["channel_resume"] = str(resumed_manifest)
        generated_paths = sorted({str(path.resolve()) for path in generated})
        evidence: dict[str, object] = {
            "status": "success",
            "source_count": len(files),
            "source_paths": [str(Path(fd.filepath).resolve()) for fd in files.values()],
            "modes": modes,
            "resume": resume_facts,
            "manifests": manifests,
            "generated_paths": generated_paths,
        }
    except Exception as exc:
        evidence = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "generated_paths": sorted(
                str(path.resolve()) for path in run_root.rglob("*") if path.is_file()
            ),
        }
        _write_json(result_json, evidence)
        return 1

    _write_json(result_json, evidence)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    args = parser.parse_args(argv)
    return run(args.output_dir, args.result_json)


if __name__ == "__main__":
    raise SystemExit(main())
