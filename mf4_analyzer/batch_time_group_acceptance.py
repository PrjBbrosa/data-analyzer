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
                "position": 10.0 + (index + 1.0) * 5.0 * time,
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
            {"position": "m", "speed": "km/h", "accel": "m/s^2"},
            idx=index,
        )
    return files


def _preset(group_by: str, *, resume: bool = False) -> AnalysisPreset:
    params = {
        "render_layout": "subplot",
        "x_source": "channel",
        "x_channel": "position",
    }
    if group_by != "none":
        params["render_group_by"] = group_by
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


def _subplot_geometry_proof(files: dict[int, FileData]) -> dict[str, object]:
    """Exercise the B2 scene-geometry assertion with the acceptance payloads."""

    from .batch_render import (
        BatchRenderContext,
        BatchRenderOptions,
        BatchSeries,
        BatchTimeFigureSpec,
    )
    from .batch_render_qt._builder import build_batch_scene
    from .batch_render_qt._dispatch import render_on_gui_thread
    from .batch_render_qt._export import render_scene_image

    def inspect() -> dict[str, object]:
        overlap_records: list[tuple[int, int, str, str]] = []
        sources = tuple(files.values())
        scene_inputs = []
        for fd in sources:
            scene_inputs.append(
                (
                    "source",
                    tuple(
                        BatchSeries(
                            x=fd.data["position"].to_numpy(dtype=float),
                            y=fd.data[channel].to_numpy(dtype=float),
                            label=channel,
                            unit=str(fd.channel_units.get(channel, "")),
                            x_unit="m",
                            panel=index,
                        )
                        for index, channel in enumerate(_CHANNELS)
                    ),
                    _CHANNELS,
                )
            )
        for channel in _CHANNELS:
            scene_inputs.append(
                (
                    "channel",
                    tuple(
                        BatchSeries(
                            x=fd.data["position"].to_numpy(dtype=float),
                            y=fd.data[channel].to_numpy(dtype=float),
                            label=Path(fd.filepath).name,
                            unit=str(fd.channel_units.get(channel, "")),
                            x_unit="m",
                            panel=index,
                        )
                        for index, fd in enumerate(sources)
                    ),
                    tuple(Path(fd.filepath).name for fd in sources),
                )
            )
        for group_by, series, titles in scene_inputs:
            spec = BatchTimeFigureSpec(
                series=series,
                layout="subplot",
                x_source="channel",
                x_origin="absolute",
                x_label="position (m)",
                panel_titles=titles,
            )
            scene = build_batch_scene(
                ("time", spec),
                params={
                    "render_group_by": group_by,
                    "render_layout": "subplot",
                    "x_source": "channel",
                    "x_channel": "position",
                },
                options=BatchRenderOptions(width_px=640, height_px=360, dpi=96),
                context=BatchRenderContext(
                    source_display_name="time group acceptance",
                    channel="grouped time",
                    unit="",
                    method="time",
                    task_id=f"geometry-{group_by}",
                ),
            )
            try:
                image = render_scene_image(scene)
                if image.isNull() or (image.width(), image.height()) != (640, 360):
                    raise RuntimeError("subplot geometry probe did not render a valid image")
                overlap_records.extend(scene.adjacent_text_overlaps())
            finally:
                scene.close()
        if overlap_records:
            raise RuntimeError(
                f"subplot adjacent text geometry overlaps: {overlap_records}"
            )
        return {
            "render_layout": "subplot",
            "x_source": "channel",
            "x_channel": "position",
            "subplot_geometry_checked": True,
            "subplot_text_overlaps": [],
        }

    return render_on_gui_thread(inspect)


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


def _inspect_mode(
    result,
    group_by: str,
    *,
    expected_directory: Path,
    expected_entry_status: str = "done",
    expected_source_identities: set[str] | None = None,
) -> tuple[dict[str, object], list[Path]]:
    if result.status != "done" or result.blocked or result.manifest_path is None:
        raise RuntimeError(
            f"{group_by} run failed: status={result.status}; blocked={result.blocked}"
        )
    manifest_path = Path(result.manifest_path).resolve()
    manifest_directory = manifest_path.parent
    expected_directory = (
        Path(expected_directory).expanduser().resolve(strict=False)
    )
    if manifest_directory != expected_directory:
        raise RuntimeError(
            f"{group_by} manifest directory mismatch: {manifest_directory}"
        )
    manifest = load_batch_manifest(manifest_path)
    entries = manifest["entries"]
    groups = manifest.get("render_groups", [])
    if len(entries) != 4 or any(
        entry.get("status") != expected_entry_status for entry in entries
    ):
        raise RuntimeError(
            f"{group_by} did not publish four {expected_entry_status} tasks"
        )

    entry_by_id = {entry["task_id"]: entry for entry in entries}
    if len(entry_by_id) != 4:
        raise RuntimeError(f"{group_by} task identities are not unique")
    actual_source_identities = {
        str(entry["source"]["identity"]) for entry in entries
    }
    expected_sources = (
        actual_source_identities
        if expected_source_identities is None
        else set(expected_source_identities)
    )
    expected_tasks = {
        (source_identity, channel)
        for source_identity in expected_sources
        for channel in _CHANNELS
    }
    actual_tasks = {
        (str(entry["source"]["identity"]), str(entry["channel"]))
        for entry in entries
    }
    if actual_tasks != expected_tasks:
        raise RuntimeError(f"{group_by} task source/channel coverage is not exact")
    data_paths = [
        _verified_artifact_path(entry["artifacts"].get("data"), "csv")
        for entry in entries
    ]
    if len(set(data_paths)) != len(data_paths):
        raise RuntimeError(f"{group_by} data artifact paths are not unique")
    if any(path.parent != manifest_directory for path in data_paths):
        raise RuntimeError(
            f"{group_by} data artifact outside manifest directory"
        )
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
        observed_group_keys: set[str] = set()
        linkage_ok = True
        for group in groups:
            if group.get("status") != "done" or group.get("group_by") != group_by:
                linkage_ok = False
                break
            members = group.get("members", [])
            if len(members) != 2:
                raise RuntimeError(f"{group_by} render-group semantics are invalid")
            grouped_entries = []
            for member in members:
                task_id = member.get("task_id")
                linked_ids.append(task_id)
                entry = entry_by_id.get(task_id)
                grouped_entries.append(entry)
                member_source = member.get("source") or {}
                entry_source = (entry or {}).get("source") or {}
                if entry is None or any(
                    member_source.get(field) != entry_source.get(field)
                    for field in ("identity", "path", "size", "mtime_ns")
                ):
                    linkage_ok = False
            if not linkage_ok:
                break
            if group_by == "source":
                group_keys = {
                    str(entry["source"]["identity"])
                    for entry in grouped_entries
                }
            else:
                group_keys = {str(entry["channel"]) for entry in grouped_entries}
            if len(group_keys) != 1:
                raise RuntimeError(f"{group_by} render-group semantics are invalid")
            observed_group_keys.update(group_keys)
        linkage_ok = linkage_ok and sorted(linked_ids) == sorted(entry_by_id)
        expected_group_keys = (
            expected_sources if group_by == "source" else set(_CHANNELS)
        )
        if observed_group_keys != expected_group_keys:
            raise RuntimeError(f"{group_by} render-group semantics are invalid")
    if not linkage_ok:
        raise RuntimeError(f"{group_by} manifest member linkage is incomplete")

    expected_images = 4 if group_by == "none" else 2
    expected_groups = 0 if group_by == "none" else 2
    if len(data_paths) != 4 or len(image_paths) != expected_images:
        raise RuntimeError(f"{group_by} artifact count mismatch")
    if len(groups) != expected_groups:
        raise RuntimeError(f"{group_by} render-group count mismatch")
    if len(set(image_paths)) != len(image_paths):
        raise RuntimeError(f"{group_by} image artifact paths are not unique")
    if any(path.parent != manifest_directory for path in image_paths):
        raise RuntimeError(
            f"{group_by} image artifact outside manifest directory"
        )
    if group_by != "none" and any(
        path.stem != str(group.get("stem") or "")
        for group, path in zip(groups, image_paths)
    ):
        raise RuntimeError(f"{group_by} group artifact identity mismatch")
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


def _validated_generated_paths(
    paths: list[Path],
    *,
    expected_count: int,
    expected_root: Path | None = None,
) -> list[str]:
    resolved = [str(path.resolve()) for path in paths]
    if len(resolved) != len(set(resolved)):
        raise RuntimeError("acceptance generated paths contain aliases")
    if len(resolved) != expected_count:
        raise RuntimeError(
            f"acceptance generated path count mismatch: {len(resolved)}"
        )
    if expected_root is not None:
        actual_files = {
            str(path.resolve())
            for path in expected_root.rglob("*")
            if path.is_file()
        }
        if set(resolved) != actual_files:
            raise RuntimeError("acceptance generated paths are not complete")
    return sorted(resolved)


def run(output_directory: Path, result_json: Path) -> int:
    """Run all grouping modes and persist machine-readable acceptance evidence."""

    output_directory = Path(output_directory).expanduser().resolve(strict=False)
    result_json = Path(result_json).expanduser().resolve(strict=False)
    run_root = output_directory / uuid.uuid4().hex
    try:
        files = _make_sources(run_root / "sources")
        render_contract = _subplot_geometry_proof(files)
        expected_source_identities = {
            str(Path(fd.filepath).resolve()) for fd in files.values()
        }
        modes: dict[str, dict[str, object]] = {}
        generated: list[Path] = [Path(fd.filepath).resolve() for fd in files.values()]
        manifests: dict[str, str] = {}
        channel_result = None
        channel_data_paths: list[Path] = []
        channel_image_paths: list[Path] = []

        for group_by in ("none", "source", "channel"):
            mode_directory = run_root / group_by
            result = BatchRunner(files).run(_preset(group_by), mode_directory)
            summary, paths = _inspect_mode(
                result,
                group_by,
                expected_directory=mode_directory,
                expected_source_identities=expected_source_identities,
            )
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
        healthy_image = channel_image_paths[1]
        healthy_image_before = _snapshot([healthy_image])
        channel_directory = deleted_image.parent
        channel_csv_files_before = {
            path.resolve() for path in channel_directory.glob("*.csv")
        }
        channel_png_files_before = {
            path.resolve() for path in channel_directory.glob("*.png")
        }
        channel_manifest_before = load_batch_manifest(channel_result.manifest_path)
        data_facts_before = {
            entry["task_id"]: dict(entry["artifacts"]["data"])
            for entry in channel_manifest_before["entries"]
        }
        group_artifact_links_before = {
            group["group_id"]: {
                "stem": group["stem"],
                "artifact": dict(group["artifact"]),
            }
            for group in channel_manifest_before["render_groups"]
        }
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
        resumed_summary, _ = _inspect_mode(
            resumed,
            "channel",
            expected_directory=run_root / "channel",
            expected_entry_status="resumed",
            expected_source_identities=expected_source_identities,
        )
        resumed_manifest_payload = load_batch_manifest(resumed.manifest_path)
        resumed_data_facts = {
            entry["task_id"]: dict(entry["artifacts"]["data"])
            for entry in resumed_manifest_payload["entries"]
        }
        resumed_data_paths = {
            Path(facts["path"]).resolve() for facts in resumed_data_facts.values()
        }
        resumed_group_artifact_links = {
            group["group_id"]: {
                "stem": group["stem"],
                "artifact": dict(group["artifact"]),
            }
            for group in resumed_manifest_payload["render_groups"]
        }
        csv_after = _snapshot(channel_data_paths)
        healthy_image_after = _snapshot([healthy_image])
        channel_csv_files_after = {
            path.resolve() for path in channel_directory.glob("*.csv")
        }
        channel_png_files_after = {
            path.resolve() for path in channel_directory.glob("*.png")
        }
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
            "healthy_image_bytes_unchanged": (
                healthy_image_after[healthy_image][0]
                == healthy_image_before[healthy_image][0]
            ),
            "healthy_image_mtime_unchanged": (
                healthy_image_after[healthy_image][1]
                == healthy_image_before[healthy_image][1]
            ),
            "data_artifact_facts_unchanged": resumed_data_facts == data_facts_before,
            "data_artifact_paths_unchanged": (
                resumed_data_paths == set(channel_data_paths)
            ),
            "group_artifact_links_unchanged": (
                resumed_group_artifact_links == group_artifact_links_before
            ),
            "channel_csv_set_unchanged": (
                channel_csv_files_after == channel_csv_files_before
            ),
            "channel_png_set_unchanged": (
                channel_png_files_after == channel_png_files_before
            ),
            "resumed_entry_statuses": {
                "resumed": sum(
                    entry.get("status") == "resumed"
                    for entry in resumed_manifest_payload["entries"]
                )
            },
            "resumed_manifest_inspected": resumed_summary == modes["channel"],
        }
        if resume_facts != {
            "csv_bytes_unchanged": True,
            "csv_mtimes_unchanged": True,
            "deleted_image_recreated": True,
            "healthy_image_bytes_unchanged": True,
            "healthy_image_mtime_unchanged": True,
            "data_artifact_facts_unchanged": True,
            "data_artifact_paths_unchanged": True,
            "group_artifact_links_unchanged": True,
            "channel_csv_set_unchanged": True,
            "channel_png_set_unchanged": True,
            "resumed_entry_statuses": {"resumed": 4},
            "resumed_manifest_inspected": True,
        }:
            raise RuntimeError(f"channel resume evidence failed: {resume_facts}")
        resumed_manifest = Path(resumed.manifest_path).resolve()
        generated.append(resumed_manifest)
        manifests["channel_resume"] = str(resumed_manifest)
        generated_paths = _validated_generated_paths(
            generated,
            expected_count=26,
            expected_root=run_root,
        )
        evidence: dict[str, object] = {
            "status": "success",
            "source_count": len(files),
            "source_paths": [str(Path(fd.filepath).resolve()) for fd in files.values()],
            "render_contract": render_contract,
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
