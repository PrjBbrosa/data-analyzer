"""Fail-closed frozen acceptance route for MF4 batch CSV/PDF export."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import uuid

from .batch import AnalysisPreset, BatchOutput, BatchRunner
from .batch_manifest import load_batch_manifest


DEFAULT_CHANNEL = "EpsDrvrSteerTq"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path = Path(path)
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


def _validated_sources(source_paths) -> tuple[Path, ...]:
    sources = tuple(Path(path).expanduser().resolve(strict=False) for path in source_paths)
    distinct = {os.path.normcase(str(path)) for path in sources}
    if len(sources) != 3 or len(distinct) != 3:
        raise ValueError("acceptance requires exactly three distinct MF4 sources")
    for source in sources:
        if source.suffix.lower() != ".mf4":
            raise ValueError(f"acceptance source is not MF4: {source}")
        if not source.is_file():
            raise FileNotFoundError(f"acceptance source not found: {source}")
    return sources


def _residual_paths(output_dir: Path) -> list[str]:
    return sorted(
        str(path.resolve())
        for path in output_dir.rglob("*")
        if path.is_file()
        and (
            path.name.endswith(".partial.json")
            or ".batch-stage." in path.name
            or path.name.endswith(".batch-reserve")
        )
    )


def _verify_result(result, output_dir: Path, sources: tuple[Path, ...], channel: str):
    if result.status != "done" or result.blocked:
        raise RuntimeError(
            f"BatchRunner did not complete: status={result.status}; blocked={result.blocked}"
        )
    if result.degraded_count or result.warnings:
        raise RuntimeError(
            f"BatchRunner degraded unexpectedly: {result.warnings}"
        )
    if len(result.items) != 3 or any(item.status != "done" for item in result.items):
        raise RuntimeError("BatchRunner did not return exactly three done items")
    if result.manifest_path is None:
        raise RuntimeError("BatchRunner did not publish a terminal manifest")

    manifest_path = Path(result.manifest_path).resolve()
    manifest = load_batch_manifest(manifest_path)
    entries = manifest.get("entries", [])
    if manifest.get("run_status") != "done" or len(entries) != 3:
        raise RuntimeError("terminal manifest does not contain three done entries")

    source_identities = {
        str((entry.get("source") or {}).get("identity") or "") for entry in entries
    }
    source_identities.discard("")
    if len(source_identities) != 3:
        raise RuntimeError("manifest does not contain three distinct source identities")

    artifacts: list[dict[str, object]] = []
    artifact_paths: set[Path] = set()
    for entry in entries:
        if entry.get("status") != "done" or entry.get("channel") != channel:
            raise RuntimeError("manifest entry status/channel mismatch")
        if entry.get("degraded_reason"):
            raise RuntimeError("manifest entry was degraded")
        expected_outputs = {"data": "csv", "image": "pdf"}
        if entry.get("requested_outputs") != expected_outputs:
            raise RuntimeError("manifest requested outputs are not CSV+PDF")
        if entry.get("effective_outputs") != expected_outputs:
            raise RuntimeError("manifest effective outputs are not CSV+PDF")
        entry_artifacts = entry.get("artifacts") or {}
        if set(entry_artifacts) != {"data", "image"}:
            raise RuntimeError("manifest entry lacks its data/image artifact pair")
        for kind, expected_format in (("data", "csv"), ("image", "pdf")):
            facts = entry_artifacts[kind]
            path = Path(facts.get("path", "")).resolve()
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if not content:
                raise RuntimeError(f"empty batch artifact: {path}")
            if facts.get("format") != expected_format:
                raise RuntimeError(f"wrong artifact format for {path}")
            if facts.get("size") != len(content):
                raise RuntimeError(f"artifact size mismatch for {path}")
            if facts.get("sha256") != digest or facts.get("checksum_status") != "complete":
                raise RuntimeError(f"artifact checksum mismatch for {path}")
            if kind == "image" and not (
                content.startswith(b"%PDF-") and content.rstrip().endswith(b"%%EOF")
            ):
                raise RuntimeError(f"invalid PDF artifact: {path}")
            artifact_paths.add(path)
            artifacts.append(
                {
                    "kind": kind,
                    "format": expected_format,
                    "path": str(path),
                    "size": len(content),
                    "sha256": digest,
                }
            )

    if len(artifact_paths) != 6:
        raise RuntimeError("BatchRunner did not publish exactly six unique artifacts")
    residuals = _residual_paths(output_dir)
    if residuals:
        raise RuntimeError(f"batch atomic-write residues remain: {residuals}")

    expected_files = artifact_paths | {manifest_path}
    actual_files = {path.resolve() for path in output_dir.rglob("*") if path.is_file()}
    if actual_files != expected_files:
        raise RuntimeError(
            "batch output directory contains unexpected files: "
            f"{sorted(str(path) for path in actual_files - expected_files)}"
        )

    return {
        "ok": True,
        "execution": "production-batch-runner",
        "channel": channel,
        "source_count": len(sources),
        "source_identity_count": len(source_identities),
        "sources": [str(path) for path in sources],
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "manifest_path": str(manifest_path),
        "manifest_run_id": manifest.get("run_id"),
        "manifest_summary": manifest.get("summary"),
        "residual_paths": residuals,
    }


def run(
    source_paths,
    output_dir,
    result_json,
    *,
    channel: str = DEFAULT_CHANNEL,
) -> int:
    """Run the production batch path and persist all acceptance truth to JSON."""

    result_json = Path(result_json)
    try:
        sources = _validated_sources(source_paths)
        output_dir = Path(output_dir).expanduser().resolve(strict=False)
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError(f"acceptance output directory must be empty: {output_dir}")
        preset = AnalysisPreset.free_config(
            name="frozen MF4 CSV+PDF acceptance",
            method="time",
            target_signals=(str(channel),),
            target_policy="common",
            outputs=BatchOutput(
                export_data=True,
                export_image=True,
                data_format="csv",
                image_format="pdf",
                image_size="custom",
                image_width=640,
                image_height=360,
                image_dpi=96,
                conflict_policy="error",
                write_manifest=True,
                resume_policy="none",
            ),
        )
        preset = replace(preset, source_paths=tuple(str(path) for path in sources))
        result = BatchRunner({}).run(preset, output_dir)
        evidence = _verify_result(result, output_dir, sources, str(channel))
    except Exception as exc:
        evidence = {
            "ok": False,
            "execution": "production-batch-runner",
            "channel": str(channel),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _write_json(result_json, evidence)
        return 1

    _write_json(result_json, evidence)
    return 0


__all__ = ["DEFAULT_CHANNEL", "run"]
