"""Fail-closed frozen acceptance route for MF4 batch CSV/PNG export."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from .batch import AnalysisPreset, BatchOutput, BatchRunner
from .batch_manifest import load_batch_manifest


DEFAULT_CHANNEL = "EpsDrvrSteerTq"


class _UnsafeEvidencePath(ValueError):
    """The evidence target could overwrite an input or batch output."""


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_path(path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _same_path(left: Path, right: Path) -> bool:
    if os.path.normcase(str(left)) == os.path.normcase(str(right)):
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def _validate_evidence_path(
    result_json: Path,
    output_dir: Path,
    sources: tuple[Path, ...],
    authoritative_paths: tuple[Path, ...],
) -> None:
    if any(_same_path(result_json, source) for source in sources):
        raise _UnsafeEvidencePath("acceptance JSON must not alias an input MF4")
    if any(_same_path(result_json, path) for path in authoritative_paths):
        raise _UnsafeEvidencePath(
            "acceptance JSON must not alias frozen runtime evidence"
        )
    if result_json == output_dir or result_json.is_relative_to(output_dir):
        raise _UnsafeEvidencePath(
            "acceptance JSON must be outside the batch output directory"
        )


def _validated_sources(sources: tuple[Path, ...]) -> tuple[Path, ...]:
    distinct = {os.path.normcase(str(path)) for path in sources}
    if len(sources) != 3 or len(distinct) != 3:
        raise ValueError("acceptance requires exactly three distinct MF4 sources")
    for source in sources:
        if source.suffix.lower() != ".mf4":
            raise ValueError(f"acceptance source is not MF4: {source}")
        if not source.is_file():
            raise FileNotFoundError(f"acceptance source not found: {source}")
    return sources


def _frozen_runtime_facts(frozen_smoke_json) -> dict[str, object]:
    if not bool(getattr(sys, "frozen", False)):
        raise RuntimeError("frozen batch acceptance requires a frozen executable")
    if frozen_smoke_json in (None, ""):
        raise ValueError("frozen batch acceptance requires the 4-output smoke JSON")

    executable = _canonical_path(sys.executable)
    smoke_path = _canonical_path(frozen_smoke_json)
    if not executable.is_file():
        raise FileNotFoundError(f"frozen executable not found: {executable}")
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    if (
        smoke.get("ok") is not True
        or smoke.get("runtime") != "frozen-onedir-executable"
        or smoke.get("artifact_count") != 4
    ):
        raise RuntimeError("4-output frozen smoke evidence is not a passing gate")
    smoke_executable = _canonical_path(smoke.get("executable", ""))
    if not _same_path(executable, smoke_executable):
        raise RuntimeError("frozen smoke executable does not match sys.executable")

    executable_sha256 = _sha256_file(executable)
    smoke_sha256 = str(smoke.get("executable_sha256") or "")
    if smoke_sha256 != executable_sha256:
        raise RuntimeError("frozen smoke executable SHA-256 does not match runtime")
    qt_qpa_platform = str(smoke.get("qt_qpa_platform") or "")
    qt_platform_name = str(smoke.get("qt_platform_name") or "")
    if not qt_qpa_platform or not qt_platform_name:
        raise RuntimeError("frozen smoke lacks requested and actual Qt platform facts")
    cjk_proof = smoke.get("cjk_proof") or {}
    if not isinstance(cjk_proof, dict):
        raise RuntimeError("frozen smoke CJK proof is malformed")
    ink_pixels = int(cjk_proof.get("ink_pixels") or 0)
    empty_ink_pixels = int(cjk_proof.get("empty_ink_pixels") or 0)
    if (
        cjk_proof.get("supports") is not True
        or cjk_proof.get("pass") is not True
        or ink_pixels <= empty_ink_pixels + 120
    ):
        raise RuntimeError("frozen smoke CJK double proof is not a passing gate")
    return {
        "runtime": "frozen-onedir-executable",
        "sys_executable": str(executable),
        "executable_sha256": executable_sha256,
        "frozen_smoke_json": str(smoke_path),
        "frozen_smoke_executable_sha256": smoke_sha256,
        "qt_qpa_platform": qt_qpa_platform,
        "qt_platform_name": qt_platform_name,
        "frozen_smoke_cjk_proof": dict(cjk_proof),
    }


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


def _verify_result(
    result,
    output_dir: Path,
    sources: tuple[Path, ...],
    channel: str,
    runtime_facts: dict[str, object],
):
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

    expected_source_keys = {os.path.normcase(str(path)) for path in sources}
    manifest_source_keys: set[str] = set()
    source_identities: set[str] = set()
    for entry in entries:
        source = entry.get("source") or {}
        source_path = str(source.get("path") or "")
        source_identity = str(source.get("identity") or "")
        if not source_path or not source_identity:
            raise RuntimeError("manifest source path/identity is missing")
        path_key = os.path.normcase(str(_canonical_path(source_path)))
        identity_key = os.path.normcase(str(_canonical_path(source_identity)))
        if path_key != identity_key:
            raise RuntimeError("manifest source path/identity do not correspond")
        manifest_source_keys.add(path_key)
        source_identities.add(source_identity)
    if manifest_source_keys != expected_source_keys:
        raise RuntimeError("manifest sources do not match the requested source set")

    artifacts: list[dict[str, object]] = []
    artifact_paths: set[Path] = set()
    for entry in entries:
        if entry.get("status") != "done" or entry.get("channel") != channel:
            raise RuntimeError("manifest entry status/channel mismatch")
        if entry.get("degraded_reason"):
            raise RuntimeError("manifest entry was degraded")
        expected_outputs = {"data": "csv", "image": "png"}
        if entry.get("requested_outputs") != expected_outputs:
            raise RuntimeError("manifest requested outputs are not CSV+PNG")
        if entry.get("effective_outputs") != expected_outputs:
            raise RuntimeError("manifest effective outputs are not CSV+PNG")
        entry_artifacts = entry.get("artifacts") or {}
        if set(entry_artifacts) != {"data", "image"}:
            raise RuntimeError("manifest entry lacks its data/image artifact pair")
        for kind, expected_format in (("data", "csv"), ("image", "png")):
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
            if kind == "image":
                from PyQt5.QtGui import QImage, QImageReader

                image = QImage(str(path))
                encoded_format = bytes(QImageReader.imageFormat(str(path))).lower()
                if (
                    image.isNull()
                    or encoded_format != b"png"
                    or (image.width(), image.height()) != (640, 360)
                ):
                    raise RuntimeError(f"invalid PNG artifact: {path}")
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
        **runtime_facts,
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
    frozen_smoke_json=None,
) -> int:
    """Run the production batch path and persist all acceptance truth to JSON."""

    channel = DEFAULT_CHANNEL
    sources = tuple(_canonical_path(path) for path in source_paths)
    output_dir = _canonical_path(output_dir)
    result_json = _canonical_path(result_json)
    executable = _canonical_path(sys.executable)
    smoke_json = (
        _canonical_path(frozen_smoke_json)
        if frozen_smoke_json not in (None, "")
        else None
    )
    authoritative_paths = (
        (executable,) if smoke_json is None else (executable, smoke_json)
    )
    try:
        _validate_evidence_path(
            result_json,
            output_dir,
            sources,
            authoritative_paths,
        )
        sources = _validated_sources(sources)
        runtime_facts = _frozen_runtime_facts(smoke_json)
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError(f"acceptance output directory must be empty: {output_dir}")
        preset = AnalysisPreset.free_config(
            name="frozen MF4 CSV+PNG acceptance",
            method="time",
            target_signals=(str(channel),),
            target_policy="common",
            outputs=BatchOutput(
                export_data=True,
                export_image=True,
                data_format="csv",
                image_format="png",
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
        evidence = _verify_result(
            result,
            output_dir,
            sources,
            channel,
            runtime_facts,
        )
    except _UnsafeEvidencePath:
        return 2
    except Exception as exc:
        evidence = {
            "ok": False,
            "execution": "production-batch-runner",
            "runtime": (
                "frozen-onedir-executable"
                if bool(getattr(sys, "frozen", False))
                else "source-execution"
            ),
            "channel": channel,
            "error": f"{type(exc).__name__}: {exc}",
        }
        _write_json(result_json, evidence)
        return 1

    _write_json(result_json, evidence)
    return 0


__all__ = ["DEFAULT_CHANNEL", "run"]
