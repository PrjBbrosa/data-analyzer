#!/usr/bin/env python3
"""Run the Gate 4.5 batch-render matrix against real MF4 inputs.

This is a machine-evidence runner, not a visual sign-off.  It deliberately
uses the production ``AnalysisPreset -> BatchRunner -> Qt renderer`` path and
never constructs a renderer-private scene or synthetic signal.

Quick structural exercise::

    QT_QPA_PLATFORM=offscreen PYTHONPATH=. python \
      scratchpad/batch-qt-render/gate45_real_matrix.py --quick

Native macOS matrix (still requires a human to open every PNG)::

    QT_QPA_PLATFORM=cocoa PYTHONPATH=. python \
      scratchpad/batch-qt-render/gate45_real_matrix.py \
      --expect-platform cocoa --output-dir /tmp/tracelab-gate45-real

Use ``--source`` repeatedly to replace the default real-file set.  The first
source is the primary analysis input; additional sources exercise
``render_group_by=channel`` with channels common to every input.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence
import uuid

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
from mf4_analyzer.batch_manifest import load_batch_manifest
from mf4_analyzer.io import DEFAULT_SOURCE_ADAPTER_REGISTRY


DEFAULT_PRIMARY = Path(
    "/Users/donghang/Downloads/data analyzer/testdoc/X04C_Ripple.mf4"
)
DEFAULT_SECONDARY = Path(
    "/Users/donghang/Downloads/data analyzer/testdoc/tiaofri.MF4"
)
DEFAULT_OUTPUT_ROOT = Path("/tmp/tracelab-gate45-real-matrix")
TIME_LIKE_UNITS = frozenset({"s", "sec", "second", "seconds"})


@dataclass(frozen=True)
class ChannelFact:
    name: str
    unit: str
    finite_count: int
    span: float

    @property
    def varying(self) -> bool:
        return self.finite_count >= 2 and np.isfinite(self.span) and self.span > 0.0


@dataclass(frozen=True)
class MatrixCase:
    name: str
    method: str
    source_paths: tuple[Path, ...]
    target_signals: tuple[str, ...]
    params: Mapping[str, Any]
    theme: str
    width: int
    height: int
    dpi: int = 144


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ("git", *args), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _is_time_like(name: str, unit: str) -> bool:
    token = str(name or "").strip().lower()
    unit_token = str(unit or "").strip().lower()
    return unit_token in TIME_LIKE_UNITS and (
        token == "t" or token.startswith("t ") or "time" in token
    )


def _channel_facts(file_data) -> list[ChannelFact]:
    facts: list[ChannelFact] = []
    for channel in file_data.get_signal_channels():
        unit = str(file_data.channel_units.get(channel, "") or "")
        if _is_time_like(channel, unit):
            continue
        try:
            values = file_data.data[channel].to_numpy(dtype=float, copy=False)
        except (KeyError, TypeError, ValueError):
            continue
        finite = np.asarray(values, dtype=float)
        finite = finite[np.isfinite(finite)]
        span = float(np.ptp(finite)) if finite.size else float("nan")
        facts.append(ChannelFact(channel, unit, int(finite.size), span))
    return sorted(
        facts,
        key=lambda item: (
            not item.varying,
            -item.span if np.isfinite(item.span) else float("inf"),
            item.name,
        ),
    )


def _discover_sources(paths: Sequence[Path]):
    discovered: dict[Path, tuple[Any, ...]] = {}
    records: list[dict[str, Any]] = []
    for path in paths:
        loaded = tuple(DEFAULT_SOURCE_ADAPTER_REGISTRY.load_sources(str(path)))
        if not loaded:
            raise RuntimeError(f"source adapter returned no logical sources: {path}")
        discovered[path] = loaded
        logical_records = []
        for source in loaded:
            fd = source.file_data
            logical_records.append(
                {
                    "source_id": str(source.source_id),
                    "group_id": str(source.group_id),
                    "display_name": str(source.display_name),
                    "sample_count": int(len(fd.data)),
                    "signal_channel_count": int(len(fd.get_signal_channels())),
                    "fs": float(fd.fs),
                    "time_source": str(getattr(fd, "_time_source", "")),
                }
            )
        records.append(
            {
                "path": str(path),
                "size": int(path.stat().st_size),
                "sha256": _sha256(path),
                "logical_sources": logical_records,
            }
        )
    return discovered, records


def _unit_key(unit: str) -> str:
    return str(unit or "").strip().casefold()


def _choose_distinct_unit_pair(facts: Sequence[ChannelFact]) -> tuple[str, str]:
    varying = [fact for fact in facts if fact.varying]
    for index, left in enumerate(varying):
        for right in varying[index + 1 :]:
            if _unit_key(left.unit) != _unit_key(right.unit):
                return left.name, right.name
    raise RuntimeError("real source has no two varying channels with distinct Y units")


def _choose_eight_channels(facts: Sequence[ChannelFact]) -> tuple[str, ...]:
    by_unit: dict[str, list[ChannelFact]] = {}
    for fact in facts:
        by_unit.setdefault(_unit_key(fact.unit), []).append(fact)
    candidates: list[tuple[int, int, tuple[str, ...]]] = []
    unit_keys = tuple(by_unit)
    for group_size in (1, 2):
        for selected_units in combinations(unit_keys, group_size):
            pool = [
                fact for fact in facts if _unit_key(fact.unit) in selected_units
            ]
            if len(pool) < 8:
                continue
            selected = tuple(fact.name for fact in pool[:8])
            varying_count = sum(fact.varying for fact in pool[:8])
            candidates.append((varying_count, len(pool), selected))
    if not candidates:
        raise RuntimeError(
            "real source does not expose eight numeric channels within the "
            "production two-Y-unit figure limit"
        )
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _choose_custom_x_pair(facts: Sequence[ChannelFact]) -> tuple[str, str]:
    varying = [fact for fact in facts if fact.varying]
    x_fact = next(
        (fact for fact in varying if "deg" in _unit_key(fact.unit)),
        varying[0] if varying else None,
    )
    if x_fact is None:
        raise RuntimeError("real source has no varying channel for custom X")
    signal_fact = next(
        (
            fact
            for fact in varying
            if fact.name != x_fact.name and "nm" in _unit_key(fact.unit)
        ),
        next((fact for fact in varying if fact.name != x_fact.name), None),
    )
    if signal_fact is None:
        raise RuntimeError("real source has no separate varying signal for custom X")
    return x_fact.name, signal_fact.name


def _common_varying_facts(
    per_path_facts: Mapping[Path, Sequence[ChannelFact]],
) -> list[ChannelFact]:
    fact_maps = {
        path: {fact.name: fact for fact in facts}
        for path, facts in per_path_facts.items()
    }
    common = set.intersection(*(set(items) for items in fact_maps.values()))
    result = []
    for name in common:
        members = [fact_maps[path][name] for path in per_path_facts]
        if not all(member.varying for member in members):
            continue
        result.append(
            ChannelFact(
                name=name,
                unit=members[0].unit,
                finite_count=min(member.finite_count for member in members),
                span=min(member.span for member in members),
            )
        )
    return sorted(result, key=lambda item: (-item.span, item.name))


def _matrix_cases(
    paths: tuple[Path, ...],
    per_path_facts: Mapping[Path, Sequence[ChannelFact]],
    *,
    quick: bool,
) -> tuple[list[MatrixCase], dict[str, Any]]:
    primary = paths[0]
    primary_facts = per_path_facts[primary]
    common_facts = _common_varying_facts(per_path_facts)
    group_source_facts = common_facts if len(paths) > 1 else list(primary_facts)
    dual_y = _choose_distinct_unit_pair(group_source_facts)
    subplot_channels = _choose_eight_channels(primary_facts)
    x_channel, analysis_channel = _choose_custom_x_pair(primary_facts)
    common_targets = tuple(fact.name for fact in common_facts[:2])
    if not common_targets:
        raise RuntimeError("real source set has no common varying channel for channel grouping")

    normal_size = (960, 540) if quick else (1920, 1080)
    large_size = normal_size if quick else (3840, 2160)

    def case(
        name: str,
        method: str,
        source_paths: Iterable[Path],
        signals: Iterable[str],
        params: Mapping[str, Any],
        theme: str,
        size: tuple[int, int] = normal_size,
    ) -> MatrixCase:
        return MatrixCase(
            name=name,
            method=method,
            source_paths=tuple(source_paths),
            target_signals=tuple(signals),
            params=dict(params),
            theme=theme,
            width=size[0],
            height=size[1],
        )

    cases = [
        case(
            "time-overlay-dual-y-group-source",
            "time",
            paths,
            dual_y,
            {"render_group_by": "source", "render_layout": "overlay"},
            "white",
        ),
        case(
            "time-subplot8-4k",
            "time",
            (primary,),
            subplot_channels,
            {"render_group_by": "source", "render_layout": "subplot"},
            "dark",
            large_size,
        ),
        case(
            "time-group-channel",
            "time",
            paths,
            common_targets,
            {"render_group_by": "channel", "render_layout": "overlay"},
            "transparent",
        ),
        case(
            "time-custom-x-channel",
            "time",
            (primary,),
            (analysis_channel,),
            {"x_source": "channel", "x_channel": x_channel},
            "white",
        ),
        case(
            "fft-db",
            "fft",
            (primary,),
            (analysis_channel,),
            {
                "nfft": 1024,
                "window": "hanning",
                "amp_y": "dB",
                "db_reference_mode": "manual",
                "db_reference": 1.0,
            },
            "white",
        ),
        case(
            "fft-time-db-auto",
            "fft_time",
            (primary,),
            (analysis_channel,),
            {
                "nfft": 512,
                "window": "hanning",
                "overlap": 0.75,
                "remove_mean": True,
                "amplitude_mode": "amplitude_db",
                "db_reference_mode": "manual",
                "db_reference": 1.0,
                "z_auto": True,
                "cmap": "turbo",
            },
            "dark",
        ),
        case(
            "order-time-db-auto-manual-rpm",
            "order_time",
            (primary,),
            (analysis_channel,),
            {
                "nfft": 512,
                "samples_per_rev": 256,
                "max_order": 2.0,
                "order_res": 0.1,
                "time_res": 0.5,
                "window": "hanning",
                "rpm_mode": "manual",
                "manual_rpm": 1200.0,
                "amplitude_mode": "amplitude_db",
                "db_reference_mode": "manual",
                "db_reference": 1.0,
                "z_auto": True,
                "cmap": "turbo",
            },
            "transparent",
        ),
    ]
    selection = {
        "dual_y_channels": dual_y,
        "subplot8_channels": subplot_channels,
        "channel_group_channels": common_targets,
        "custom_x_channel": x_channel,
        "analysis_channel": analysis_channel,
        "manual_order_rpm": 1200.0,
        "manual_order_max": 2.0,
    }
    return cases, selection


def _image_record(path: Path, expected: MatrixCase) -> dict[str, Any]:
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImageReader

    path = path.resolve()
    content_size = path.stat().st_size
    if content_size <= 0:
        raise RuntimeError(f"empty PNG: {path}")
    reader = QImageReader(str(path))
    if bytes(reader.format()).lower() != b"png":
        raise RuntimeError(f"artifact is not PNG: {path}")
    image = reader.read()
    if image.isNull():
        raise RuntimeError(f"Qt cannot decode PNG: {path}: {reader.errorString()}")
    actual_size = (image.width(), image.height())
    requested_size = (expected.width, expected.height)
    if actual_size != requested_size:
        raise RuntimeError(
            f"PNG dimensions drifted for {expected.name}: {actual_size} != {requested_size}"
        )
    sample = image.scaled(64, 64, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    sampled_rgba = {
        int(sample.pixel(x, y))
        for y in range(sample.height())
        for x in range(sample.width())
    }
    if len(sampled_rgba) < 2:
        raise RuntimeError(f"PNG has no visible content variation: {path}")
    return {
        "path": str(path),
        "size": content_size,
        "sha256": _sha256(path),
        "width": image.width(),
        "height": image.height(),
        "requested_width": expected.width,
        "requested_height": expected.height,
        "sampled_rgba_count": len(sampled_rgba),
        "has_alpha_channel": bool(image.hasAlphaChannel()),
    }


def _manifest_png_facts(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    facts: list[Mapping[str, Any]] = []
    for entry in manifest.get("entries", ()):
        image = (entry.get("artifacts") or {}).get("image")
        if isinstance(image, Mapping):
            facts.append(image)
    for group in manifest.get("render_groups", ()):
        image = group.get("artifact")
        if isinstance(image, Mapping):
            facts.append(image)
    return facts


def _verify_case(case: MatrixCase, result, case_dir: Path) -> dict[str, Any]:
    if result.status != "done" or result.blocked:
        raise RuntimeError(
            f"{case.name} failed: status={result.status}; blocked={result.blocked}"
        )
    if result.degraded_count:
        raise RuntimeError(f"{case.name} unexpectedly degraded image output")
    if not result.items or any(item.status != "done" for item in result.items):
        raise RuntimeError(
            f"{case.name} item failures: "
            f"{[(item.signal, item.status, item.message) for item in result.items]}"
        )
    if any(item.degraded_reason for item in result.items):
        raise RuntimeError(f"{case.name} contains degraded item output")
    if any(
        item.requested_outputs != {"image": "png"}
        or item.effective_outputs != {"image": "png"}
        for item in result.items
    ):
        raise RuntimeError(f"{case.name} did not remain PNG-only")
    if not result.manifest_path:
        raise RuntimeError(f"{case.name} did not write a manifest")

    manifest_path = Path(result.manifest_path).resolve()
    manifest = load_batch_manifest(manifest_path)
    if manifest.get("run_status") != "done" or manifest.get("blocked_reasons"):
        raise RuntimeError(f"{case.name} manifest did not finish cleanly")
    summary = manifest.get("summary") or {}
    if summary.get("failed") or summary.get("cancelled"):
        raise RuntimeError(f"{case.name} manifest summary contains failures: {summary}")

    png_paths = sorted(path.resolve() for path in case_dir.glob("*.png"))
    if not png_paths:
        raise RuntimeError(f"{case.name} produced no PNG")
    prohibited = sorted(
        str(path.resolve())
        for path in case_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".csv", ".xlsx", ".pdf", ".svg"}
    )
    if prohibited:
        raise RuntimeError(f"{case.name} produced non-PNG data/vector artifacts: {prohibited}")

    manifest_facts = _manifest_png_facts(manifest)
    manifest_paths = {
        Path(str(fact.get("path") or "")).resolve() for fact in manifest_facts
    }
    if manifest_paths != set(png_paths):
        raise RuntimeError(
            f"{case.name} manifest/PNG set mismatch: {manifest_paths} != {set(png_paths)}"
        )
    for fact in manifest_facts:
        if (
            fact.get("format") != "png"
            or fact.get("checksum_status") != "complete"
            or int(fact.get("width", -1)) != case.width
            or int(fact.get("height", -1)) != case.height
            or int(fact.get("dpi", -1)) != case.dpi
        ):
            raise RuntimeError(f"{case.name} invalid manifest PNG facts: {fact}")
        path = Path(str(fact["path"])).resolve()
        if fact.get("sha256") != _sha256(path):
            raise RuntimeError(f"{case.name} manifest checksum mismatch: {path}")

    return {
        "name": case.name,
        "method": case.method,
        "theme": case.theme,
        "source_paths": [str(path) for path in case.source_paths],
        "target_signals": list(case.target_signals),
        "params": dict(case.params),
        "requested_size": [case.width, case.height],
        "dpi": case.dpi,
        "run_status": result.status,
        "item_count": len(result.items),
        "item_statuses": [item.status for item in result.items],
        "warnings": list(result.warnings),
        "manifest_path": str(manifest_path),
        "manifest_summary": summary,
        "render_group_count": len(manifest.get("render_groups", ())),
        "images": [_image_record(path, case) for path in png_paths],
        "machine_checks": {
            "png_only": True,
            "nonempty": True,
            "exact_dimensions": True,
            "no_failed_items": True,
            "manifest_checksums_complete": True,
            "visible_content_variation": True,
        },
    }


def _run_case(case: MatrixCase, output_root: Path) -> dict[str, Any]:
    case_dir = output_root / case.name
    case_dir.mkdir(parents=True, exist_ok=False)
    preset = AnalysisPreset.free_config(
        name=f"Gate 4.5 real matrix: {case.name}",
        method=case.method,
        target_signals=case.target_signals,
        target_policy="common",
        params=dict(case.params),
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            image_format="png",
            image_size="custom",
            image_width=case.width,
            image_height=case.height,
            image_dpi=case.dpi,
            image_background=case.theme,
            image_line_width=1.5,
            conflict_policy="error",
            write_manifest=True,
            resume_policy="none",
        ),
    )
    preset = replace(
        preset, source_paths=tuple(str(path) for path in case.source_paths)
    )
    result = BatchRunner({}).run(preset, case_dir)
    return _verify_case(case, result, case_dir)


def _resolve_paths(raw_paths: Sequence[str] | None) -> tuple[Path, ...]:
    configured = (
        [DEFAULT_PRIMARY, DEFAULT_SECONDARY]
        if not raw_paths
        else [Path(value) for value in raw_paths]
    )
    paths = tuple(
        dict.fromkeys(path.expanduser().resolve(strict=True) for path in configured)
    )
    if not paths:
        raise ValueError("at least one --source is required")
    for path in paths:
        if path.suffix.lower() not in {".mf4", ".mdf"}:
            raise ValueError(f"Gate 4.5 source is not MDF/MF4: {path}")
    return paths


def run(args: argparse.Namespace) -> int:
    started_at = _utc_now()
    output_base = args.output_dir.expanduser().resolve(strict=False)
    run_root = output_base / (
        datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8]
    )
    run_root.mkdir(parents=True, exist_ok=False)
    result_json = (
        args.result_json.expanduser().resolve(strict=False)
        if args.result_json is not None
        else run_root / "gate45-real-matrix.json"
    )
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "execution": "production-batch-runner-real-mf4",
        "started_at": started_at,
        "quick": bool(args.quick),
        "run_root": str(run_root),
        "result_json": str(result_json),
        "requested_qt_platform": os.environ.get("QT_QPA_PLATFORM", ""),
        "expected_qt_platform": args.expect_platform or "",
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_status_short": _git_value("status", "--short"),
        "visual_pass_claimed": False,
        "visual_review_required": True,
    }
    try:
        paths = _resolve_paths(args.source)
        discovered, source_records = _discover_sources(paths)
        primary_logical = discovered[paths[0]][0].file_data
        per_path_facts = {
            path: _channel_facts(discovered[path][0].file_data) for path in paths
        }
        cases, selection = _matrix_cases(paths, per_path_facts, quick=args.quick)

        from mf4_analyzer.batch_render_qt._dispatch import ensure_app

        app = ensure_app()
        actual_platform = str(app.platformName())
        if args.expect_platform and actual_platform != args.expect_platform:
            raise RuntimeError(
                f"Qt platform mismatch: {actual_platform!r} != {args.expect_platform!r}"
            )

        case_records = []
        for index, case in enumerate(cases, 1):
            print(
                f"[{index}/{len(cases)}] {case.name}: {case.width}x{case.height} "
                f"{case.theme}",
                flush=True,
            )
            case_records.append(_run_case(case, run_root))
            app.processEvents()

        all_images = [
            image for case_record in case_records for image in case_record["images"]
        ]
        full_4k = any(
            image["width"] == 3840 and image["height"] == 2160
            for image in all_images
        )
        themes = {case_record["theme"] for case_record in case_records}
        methods = {case_record["method"] for case_record in case_records}
        evidence.update(
            {
                "status": "success",
                "finished_at": _utc_now(),
                "actual_qt_platform": actual_platform,
                "sources": source_records,
                "primary_source_sample_count": int(len(primary_logical.data)),
                "selection": selection,
                "cases": case_records,
                "summary": {
                    "case_count": len(case_records),
                    "image_count": len(all_images),
                    "methods": sorted(methods),
                    "themes": sorted(themes),
                    "has_4k": full_4k,
                    "group_by_source": any(
                        record["params"].get("render_group_by") == "source"
                        for record in case_records
                    ),
                    "group_by_channel": any(
                        record["params"].get("render_group_by") == "channel"
                        for record in case_records
                    ),
                    "custom_x_channel": any(
                        record["params"].get("x_source") == "channel"
                        for record in case_records
                    ),
                    "all_machine_checks_passed": True,
                },
                "gate45_machine_scope_complete": bool(
                    not args.quick
                    and full_4k
                    and methods == {"time", "fft", "fft_time", "order_time"}
                    and themes == {"white", "dark", "transparent"}
                ),
                "gate45_native_cocoa_eligible": bool(
                    not args.quick and full_4k and actual_platform == "cocoa"
                ),
                "acceptance_boundary": (
                    "Machine assertions only. A human must open every PNG and "
                    "perform the foreground interaction/heartbeat checks before "
                    "Gate 4.5 can be signed PASS."
                ),
            }
        )
    except Exception as exc:
        evidence.update(
            {
                "status": "failed",
                "finished_at": _utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        _write_json(result_json, evidence)
        print(f"FAILED: {evidence['error']}", file=sys.stderr)
        print(f"Evidence: {result_json}", file=sys.stderr)
        return 1

    _write_json(result_json, evidence)
    print(f"PASS (machine-only): {len(evidence['cases'])} cases", flush=True)
    print(f"Evidence: {result_json}", flush=True)
    print("Visual/Cocoa foreground sign-off is still required.", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        help=(
            "Real MF4/MDF path; repeat for multi-source channel grouping. "
            "Defaults to X04C_Ripple.mf4 plus tiaofri.MF4."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Parent directory; a unique run directory is created beneath it.",
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Optional evidence JSON path; defaults inside the unique run directory.",
    )
    parser.add_argument(
        "--expect-platform",
        choices=("cocoa", "offscreen", "windows"),
        help="Fail if QApplication.platformName() does not match.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use 960x540 for structural exercise; does not satisfy the 4K Gate matrix.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
