"""Launch and verify the batch-render smoke of a Windows onedir executable.

Reference values for colormap endpoints must be read back from the product
runtime (``pg.colormap.get`` / ``_resolve_colormap``), never re-declared as
literals — see ``docs/analyzer/specs/2026-08-12-guideline-hardening-spec.md``
§3.3 (C2/C3 verify-tool contract).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import pyqtgraph as pg
from PyQt5.QtGui import QImage, QImageReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mf4_analyzer.qt_analysis_shared import (  # noqa: E402
    DEFAULT_HEATMAP_CMAP,
    _resolve_colormap,
)


TITLE = "单帧振动加速度"
KINDS = ("time", "fft", "fft_time", "order_time")
FORMATS = ("png",)
# Heatmaps that exercise the shipping-default local LUT (gnuplot2), not turbo.
DEFAULT_CMAP_HEATMAP_KINDS = ("fft_time", "order_time")
EXPECTED_NAMES = {
    f"{kind}.{image_format}" for kind in KINDS for image_format in FORMATS
} | {
    f"{kind}_default_cmap.{image_format}"
    for kind in DEFAULT_CMAP_HEATMAP_KINDS
    for image_format in FORMATS
}


def _endpoint_rgb(color_map: pg.ColorMap) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return (low, high) RGB triples from a live ColorMap LUT."""
    lut = color_map.getLookupTable(0.0, 1.0, 256, alpha=False)
    low = tuple(int(channel) for channel in lut[0][:3])
    high = tuple(int(channel) for channel in lut[-1][:3])
    return low, high


def _turbo_endpoint_rgb() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    color_map = pg.colormap.get("turbo")
    if color_map is None:
        raise RuntimeError("pyqtgraph colormap 'turbo' is unavailable")
    return _endpoint_rgb(color_map)


def _default_cmap_endpoint_rgb() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Shipping-default heatmap endpoints via the product local-LUT resolver."""
    return _endpoint_rgb(_resolve_colormap(DEFAULT_HEATMAP_CMAP))


def _tree_measurement(directory: Path) -> dict[str, object]:
    directory = Path(directory).resolve()
    if directory.name != "_internal" or not directory.is_dir():
        raise ValueError(f"expected an existing _internal directory: {directory}")
    files = tuple(path for path in directory.rglob("*") if path.is_file())
    return {
        "path": str(directory),
        "bytes": sum(path.stat().st_size for path in files),
        "files": len(files),
    }


def _pixel_rgb_array(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format_RGB888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    rows = np.frombuffer(ptr, dtype=np.uint8).reshape(
        converted.height(), converted.bytesPerLine()
    )
    return rows[:, : converted.width() * 3].reshape(
        converted.height(), converted.width(), 3
    )


def _contains_rgb(
    image: QImage, expected: tuple[int, int, int], tolerance: int = 1
) -> int:
    pixels = _pixel_rgb_array(image)
    wanted = np.asarray(expected, dtype=np.int16)
    delta = np.abs(pixels.astype(np.int16) - wanted)
    return int(np.count_nonzero(np.all(delta <= tolerance, axis=2)))


def _contains_rgb_in_interior(
    image: QImage,
    expected: tuple[int, int, int],
    *,
    tolerance: int = 1,
    margin_frac: float = 0.25,
) -> int:
    """Count endpoint matches inside the plot interior only.

    gnuplot2 endpoints are pure black/white; full-frame counting confuses them
    with page chrome / header text. The central crop keeps the heatmap body
    and drops the report chrome.
    """
    pixels = _pixel_rgb_array(image)
    height, width, _ = pixels.shape
    top = int(height * margin_frac)
    bottom = int(height * (1.0 - margin_frac))
    left = int(width * margin_frac)
    right = int(width * (1.0 - margin_frac))
    crop = pixels[top:bottom, left:right]
    wanted = np.asarray(expected, dtype=np.int16)
    delta = np.abs(crop.astype(np.int16) - wanted)
    return int(np.count_nonzero(np.all(delta <= tolerance, axis=2)))


def verify_artifacts(
    artifacts: Path, child_json: Path, expected_platform: str
) -> dict[str, object]:
    artifacts = Path(artifacts)
    child = json.loads(Path(child_json).read_text(encoding="utf-8"))
    if child.get("ok") is not True:
        raise RuntimeError(f"render child reported failure: {child}")
    if child.get("title") != TITLE:
        raise RuntimeError("render child did not use the required CJK title")
    qt_qpa_platform = str(child.get("qt_qpa_platform") or "")
    qt_platform_name = str(child.get("qt_platform_name") or "")
    if not qt_qpa_platform or not qt_platform_name:
        raise RuntimeError("render child did not report requested and actual Qt platforms")
    if (
        qt_qpa_platform.lower() != expected_platform.lower()
        or qt_platform_name.lower() != expected_platform.lower()
    ):
        raise RuntimeError(
            f"requested Qt platform {expected_platform!s}, but child reported "
            f"QT_QPA_PLATFORM={qt_qpa_platform!r} and platformName={qt_platform_name!r}"
        )
    cjk_proof = child.get("cjk_proof") or {}
    ink_pixels = int(cjk_proof.get("ink_pixels") or 0)
    empty_ink_pixels = int(cjk_proof.get("empty_ink_pixels") or 0)
    if (
        cjk_proof.get("supports") is not True
        or cjk_proof.get("pass") is not True
        or ink_pixels <= empty_ink_pixels + 120
    ):
        raise RuntimeError(f"render child CJK double proof failed: {cjk_proof}")
    actual_names = {path.name for path in artifacts.iterdir() if path.is_file()}
    if actual_names != EXPECTED_NAMES:
        raise RuntimeError(
            f"expected exactly {len(EXPECTED_NAMES)} render artifacts; "
            f"missing={sorted(EXPECTED_NAMES - actual_names)}, "
            f"extra={sorted(actual_names - EXPECTED_NAMES)}"
        )

    artifact_records: list[dict[str, object]] = []
    for name in sorted(EXPECTED_NAMES):
        path = artifacts / name
        content = path.read_bytes()
        if not content:
            raise RuntimeError(f"empty render artifact: {path}")
        image = QImage(str(path))
        encoded_format = bytes(QImageReader.imageFormat(str(path))).lower()
        if (
            image.isNull()
            or encoded_format != b"png"
            or (image.width(), image.height()) != (640, 360)
        ):
            raise RuntimeError(f"invalid PNG artifact: {path}")
        artifact_records.append(
            {
                "name": name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "width": image.width(),
                "height": image.height(),
            }
        )

    turbo_low_rgb, turbo_high_rgb = _turbo_endpoint_rgb()
    for kind in ("fft_time", "order_time"):
        image = QImage(str(artifacts / f"{kind}.png"))
        if _contains_rgb(image, turbo_low_rgb) < 1_000:
            raise RuntimeError(f"Turbo low sample missing from {kind}.png")
        if _contains_rgb(image, turbo_high_rgb) < 1_000:
            raise RuntimeError(f"Turbo high sample missing from {kind}.png")

    default_low_rgb, default_high_rgb = _default_cmap_endpoint_rgb()
    for kind in DEFAULT_CMAP_HEATMAP_KINDS:
        name = f"{kind}_default_cmap.png"
        image = QImage(str(artifacts / name))
        if _contains_rgb_in_interior(image, default_low_rgb) < 1_000:
            raise RuntimeError(
                f"{DEFAULT_HEATMAP_CMAP} low sample missing from {name}"
            )
        if _contains_rgb_in_interior(image, default_high_rgb) < 1_000:
            raise RuntimeError(
                f"{DEFAULT_HEATMAP_CMAP} high sample missing from {name}"
            )

    return {
        "ok": True,
        "title": TITLE,
        "artifact_count": len(artifact_records),
        "artifacts": artifact_records,
        "requested_qt_platform": expected_platform,
        "qt_qpa_platform": qt_qpa_platform,
        "qt_platform_name": qt_platform_name,
        "cjk_proof": cjk_proof,
        "cjk_font_families": child.get("cjk_font_families", []),
        "turbo_samples": {
            "low_rgb": list(turbo_low_rgb),
            "high_rgb": list(turbo_high_rgb),
        },
        "default_cmap_samples": {
            "cmap": DEFAULT_HEATMAP_CMAP,
            "low_rgb": list(default_low_rgb),
            "high_rgb": list(default_high_rgb),
        },
    }


def verify_frozen(exe: Path, expected_platform: str) -> dict[str, object]:
    exe = Path(exe).resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"frozen executable not found: {exe}")
    with TemporaryDirectory(prefix="tracelab-frozen-render-") as raw_directory:
        directory = Path(raw_directory)
        artifacts = directory / "outputs"
        child_json = directory / "child.json"
        command = [
            str(exe),
            "--batch-render-runtime-smoke",
            "--output-dir",
            str(artifacts),
            "--json",
            str(child_json),
        ]
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = expected_platform
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=240,
            env=environment,
        )
        if completed.returncode != 0:
            detail = child_json.read_text(encoding="utf-8") if child_json.is_file() else ""
            raise RuntimeError(
                f"frozen render child failed ({completed.returncode}): {detail}"
            )
        evidence = verify_artifacts(artifacts, child_json, expected_platform)
    evidence["runtime"] = "frozen-onedir-executable"
    evidence["executable"] = str(exe)
    evidence["executable_bytes"] = exe.stat().st_size
    evidence["executable_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
    evidence["internal"] = _tree_measurement(exe.parent / "_internal")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--exe", type=Path)
    source.add_argument("--artifacts", type=Path)
    parser.add_argument("--child-json", type=Path)
    parser.add_argument(
        "--platform", choices=("offscreen", "windows"), required=True
    )
    parser.add_argument("--evidence-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.exe is not None:
            evidence = verify_frozen(args.exe, args.platform)
        else:
            if args.child_json is None:
                parser.error("--artifacts requires --child-json")
            evidence = verify_artifacts(
                args.artifacts, args.child_json, args.platform
            )
            evidence["runtime"] = "artifact-validation-only"
    except Exception as exc:
        evidence = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return_code = 1
    else:
        return_code = 0
    args.evidence_json.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_json.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if return_code and sys.stderr is not None:
        sys.stderr.write(f"Frozen batch render verification failed: {evidence['error']}\n")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
