"""Launch and verify the batch-render smoke of a Windows onedir executable.

Reference values for colormap endpoints must be read back from the product
runtime (``pg.colormap.get`` / ``_resolve_colormap``), never re-declared as
literals — see ``docs/analyzer/specs/2026-08-12-guideline-hardening-spec.md``
§3.3 (C2/C3 verify-tool contract).
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
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

from mf4_analyzer.batch_render_qt._theme import (  # noqa: E402
    EXPORT_FONT_DPI,
    THEMES,
)
from mf4_analyzer.frozen_evidence_paths import (  # noqa: E402
    UnsafeEvidencePath,
    canonical_path,
    reject_aliased_evidence,
)
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
LAYOUT_ARTIFACT = "time.png"
# Title/legend use the same floor as header_ink_proof; per-tick only needs
# visible ink, not that phrase-sized budget.
REGION_INK_MIN = 120
TICK_INK_MIN = 8
REGION_BACKGROUND_DELTA = 12
_RENDER_EVIDENCE_MESSAGE = (
    "evidence JSON must not alias the frozen executable, an input artifact, "
    "or the child result JSON"
)


def _reject_render_evidence(
    evidence_json: Path,
    *,
    exe: Path | None = None,
    artifacts: Path | None = None,
    child_json: Path | None = None,
    diagnostics_dir: Path | None = None,
) -> None:
    protected: list[Path] = []
    contained_in: list[Path] = []
    if exe is not None:
        protected.append(canonical_path(exe))
    if child_json is not None:
        protected.append(canonical_path(child_json))
    if artifacts is not None:
        contained_in.append(canonical_path(artifacts))
    if diagnostics_dir is not None:
        diagnostics = canonical_path(diagnostics_dir)
        protected.append(diagnostics / "child.json")
        contained_in.append(diagnostics / "outputs")
    reject_aliased_evidence(
        canonical_path(evidence_json),
        tuple(protected),
        contained_in=tuple(contained_in),
        message=_RENDER_EVIDENCE_MESSAGE,
    )


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
    """Return an owned RGB array; never a view of a temporary QImage buffer."""
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise ValueError("cannot read pixels from an empty QImage")
    converted = image.convertToFormat(QImage.Format_RGB888)
    if converted.isNull() or converted.width() <= 0 or converted.height() <= 0:
        raise ValueError("cannot read pixels from an empty QImage")
    ptr = converted.bits()
    if ptr is None:
        raise ValueError("cannot read pixels from an empty QImage")
    ptr.setsize(converted.byteCount())
    height = converted.height()
    width = converted.width()
    rows = np.frombuffer(ptr, dtype=np.uint8).reshape(
        height, converted.bytesPerLine()
    )
    # Copy packed RGB while `converted` is alive; drop bytesPerLine padding.
    owned = np.empty((height, width, 3), dtype=np.uint8)
    owned.reshape(height, width * 3)[:] = rows[:, : width * 3]
    return owned


def _contains_rgb(
    image: QImage, expected: tuple[int, int, int], tolerance: int = 1
) -> int:
    pixels = _pixel_rgb_array(image)
    wanted = np.asarray(expected, dtype=np.int16)
    delta = np.abs(pixels.astype(np.int16) - wanted)
    return int(np.count_nonzero(np.all(delta <= tolerance, axis=2)))


def _theme_background_rgb() -> tuple[int, int, int]:
    color = THEMES["white"].background
    return (int(color.red()), int(color.green()), int(color.blue()))


def _as_rect(value) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        rect = [float(part) for part in value]
    except (TypeError, ValueError):
        return None
    if any(not np.isfinite(part) for part in rect):
        return None
    return rect


def _rects_overlap(rect_a: list[float], rect_b: list[float]) -> bool:
    ax, ay, aw, ah = rect_a
    bx, by, bw, bh = rect_b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    return (right - left) > 0.5 and (bottom - top) > 0.5


def same_axis_tick_overlaps(ticks: list[dict[str, object]]) -> list[list[str]]:
    """Recompute overlaps from PNG-space tick rects; do not trust the child flag."""
    groups: dict[tuple[object, object], list[tuple[list[float], str]]] = {}
    for tick in ticks:
        rect = _as_rect(tick.get("rect"))
        if rect is None:
            continue
        key = (tick.get("panel", 0), tick.get("side"))
        groups.setdefault(key, []).append((rect, str(tick.get("text") or "")))
    overlaps: list[list[str]] = []
    for records in groups.values():
        for index, (rect_a, text_a) in enumerate(records):
            for rect_b, text_b in records[index + 1 :]:
                if _rects_overlap(rect_a, rect_b):
                    overlaps.append([text_a, text_b])
    return overlaps


def _region_ink_count(
    image: QImage,
    rect: list[float],
    background: tuple[int, int, int],
) -> int:
    pixels = _pixel_rgb_array(image)
    x, y, width, height = (int(round(part)) for part in rect)
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(int(pixels.shape[1]), x + max(width, 0))
    y1 = min(int(pixels.shape[0]), y + max(height, 0))
    if x1 <= x0 or y1 <= y0:
        return 0
    crop = pixels[y0:y1, x0:x1]
    wanted = np.asarray(background, dtype=np.int16)
    delta = np.abs(crop.astype(np.int16) - wanted)
    return int(np.count_nonzero(np.any(delta > REGION_BACKGROUND_DELTA, axis=2)))


def verify_page_layout(
    image: QImage, layout: dict[str, object]
) -> dict[str, object]:
    """Independent PNG-region endorsement of title, ticks, and legend."""
    page = layout.get("page")
    if not isinstance(page, dict):
        raise RuntimeError("render child omitted page layout diagnostics")
    if str(page.get("artifact") or "") != LAYOUT_ARTIFACT:
        raise RuntimeError(
            f"layout diagnostics must describe {LAYOUT_ARTIFACT}, got {page.get('artifact')!r}"
        )
    title = page.get("title") if isinstance(page.get("title"), dict) else {}
    legend = page.get("legend") if isinstance(page.get("legend"), dict) else {}
    ticks = page.get("ticks") if isinstance(page.get("ticks"), list) else []
    title_rect = _as_rect(title.get("rect"))
    legend_rect = _as_rect(legend.get("rect"))
    if title_rect is None or title_rect[2] < 1 or title_rect[3] < 1:
        raise RuntimeError("render child omitted a usable title PNG region")
    if legend_rect is None or legend_rect[2] < 1 or legend_rect[3] < 1:
        raise RuntimeError("render child omitted a usable legend PNG region")
    tick_records: list[dict[str, object]] = []
    for tick in ticks:
        if not isinstance(tick, dict):
            continue
        rect = _as_rect(tick.get("rect"))
        if rect is None:
            continue
        tick_records.append(tick)
    if len(tick_records) < 2:
        raise RuntimeError("render child omitted tick PNG regions")
    overlaps = same_axis_tick_overlaps(tick_records)
    adjacent = page.get("adjacent_overlaps") or []
    overflow = page.get("overflow") or []
    if overlaps:
        raise RuntimeError(f"overlapping tick labels in final layout: {overlaps}")
    if adjacent:
        raise RuntimeError(f"adjacent panel text overlaps in final layout: {adjacent}")
    if overflow:
        raise RuntimeError(f"tick labels overflow the page: {overflow}")

    background = _theme_background_rgb()
    title_ink = _region_ink_count(image, title_rect, background)
    legend_ink = _region_ink_count(image, legend_rect, background)
    if title_ink < REGION_INK_MIN:
        raise RuntimeError(
            f"title PNG region has no readable text ({title_ink} ink pixels)"
        )
    if legend_ink < REGION_INK_MIN:
        raise RuntimeError(
            f"legend PNG region has no readable text ({legend_ink} ink pixels)"
        )
    tick_ink_total = 0
    empty_ticks: list[str] = []
    for tick in tick_records:
        rect = _as_rect(tick.get("rect"))
        ink = _region_ink_count(image, rect, background)
        tick_ink_total += ink
        if ink < TICK_INK_MIN:
            empty_ticks.append(str(tick.get("text") or ""))
    if empty_ticks:
        raise RuntimeError(f"tick PNG regions have no readable text: {empty_ticks}")
    if tick_ink_total < REGION_INK_MIN:
        raise RuntimeError(
            f"tick PNG regions together have no readable text ({tick_ink_total} ink pixels)"
        )
    return {
        "title_ink_pixels": title_ink,
        "legend_ink_pixels": legend_ink,
        "tick_ink_pixels": tick_ink_total,
        "tick_count": len(tick_records),
        "same_axis_tick_overlaps": overlaps,
        "background_rgb": list(background),
    }


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

    layout = child.get("layout_diagnostics")
    if not isinstance(layout, dict) or not layout:
        raise RuntimeError("render child omitted font/DPI/layout diagnostics")
    try:
        export_dpi = float(layout.get("export_font_dpi"))
    except (TypeError, ValueError):
        raise RuntimeError("render child omitted export_font_dpi") from None
    if abs(export_dpi - float(EXPORT_FONT_DPI)) > 0.01:
        raise RuntimeError(
            f"export font DPI must be {EXPORT_FONT_DPI:g}, got {export_dpi}"
        )
    try:
        logical_dpi = float(layout.get("logical_dpi_x"))
        axis_font_px = float(layout.get("axis_font_device_px"))
    except (TypeError, ValueError):
        raise RuntimeError("render child omitted DPI/font size diagnostics") from None
    if logical_dpi <= 0.0 or axis_font_px <= 0.0:
        raise RuntimeError("render child reported non-positive DPI/font diagnostics")
    page_proof = verify_page_layout(QImage(str(artifacts / LAYOUT_ARTIFACT)), layout)

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
        "layout_diagnostics": layout,
        "page_layout_proof": page_proof,
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


def verify_frozen(
    exe: Path, expected_platform: str, *, diagnostics_dir: Path | None = None,
) -> dict[str, object]:
    exe = canonical_path(exe)
    if not exe.is_file():
        raise FileNotFoundError(f"frozen executable not found: {exe}")
    if diagnostics_dir is not None:
        diagnostics_dir = canonical_path(diagnostics_dir)
        # A new attempt must never inherit a previous child's JSON or images.
        diagnostics_dir.mkdir(parents=True, exist_ok=False)
    workspace = (
        nullcontext(diagnostics_dir) if diagnostics_dir is not None
        else TemporaryDirectory(prefix="tracelab-frozen-render-")
    )
    with workspace as raw_directory:
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
        (directory / "command.json").write_text(
            json.dumps({"argv": command, "QT_QPA_PLATFORM": expected_platform}, indent=2),
            encoding="utf-8",
        )
        # Stream bytes to disk so crashes/timeouts retain Qt's actual stderr.
        with (directory / "stdout.log").open("wb") as stdout, (
            directory / "stderr.log"
        ).open("wb") as stderr:
            completed = subprocess.run(
                command, stdout=stdout, stderr=stderr, timeout=240, env=environment,
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
    parser.add_argument("--diagnostics-dir", type=Path, help="New directory retaining child logs and PNGs, including failures")
    parser.add_argument(
        "--platform", choices=("offscreen", "windows"), required=True
    )
    parser.add_argument("--evidence-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _reject_render_evidence(
            args.evidence_json,
            exe=args.exe,
            artifacts=args.artifacts,
            child_json=args.child_json,
            diagnostics_dir=args.diagnostics_dir,
        )
    except UnsafeEvidencePath as exc:
        parser.error(str(exc))
    try:
        if args.exe is not None:
            evidence = verify_frozen(
                args.exe, args.platform, diagnostics_dir=args.diagnostics_dir,
            )
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
