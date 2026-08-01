#!/usr/bin/env python3
"""Compare real single-file TimeDomainCanvasPG output with Batch Qt output.

This Gate 4.5 evidence probe deliberately exercises two production paths:

* ``TimeDomainCanvasPG.plot_channels() -> grab_pixmap()`` for the single-file
  reference, including the export refresh and dense-raster flush owned by the
  canvas; and
* ``AnalysisPreset -> BatchRunner -> batch_render_qt`` for the 1920x1080 PNG.

The Batch PNG is never decorated.  Labels are added only to a separate contact
sheet.  Both the full source images and plot-area crops are retained so the
JSON can distinguish exact output geometry from the visual comparison crop.

Offscreen example::

    TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
      /path/to/python scratchpad/batch-qt-render/gate45_singlefile_parity.py \
      --expect-platform offscreen

Native macOS example::

    TMPDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. \
      /path/to/python scratchpad/batch-qt-render/gate45_singlefile_parity.py \
      --expect-platform cocoa --output-dir /tmp/tracelab-gate45-singlefile
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
import uuid


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from mf4_analyzer._palette import FILE_PALETTES
from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
from mf4_analyzer.batch_manifest import load_batch_manifest
from mf4_analyzer.io import DEFAULT_SOURCE_ADAPTER_REGISTRY
from mf4_analyzer.ui.pg_canvas.render_profile import (
    classify_render_profile,
    source_revision_for,
)


DEFAULT_SOURCE = Path(
    "/Users/donghang/Downloads/data analyzer/testdoc/X04C_Ripple.mf4"
)
HIGH_VARIATION_CHANNEL = (
    "Rte_RotationSpeedCalculation_vAbsSteeringAngleSpeed_xdu16"
)
SMOOTH_CHANNEL = "Rte_ActRet_mActiveReturnMotorTorq4Check_xds16"
DEFAULT_OUTPUT_ROOT = Path("/tmp/tracelab-gate45-singlefile-parity")
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
OUTPUT_DPI = 144
SMOOTH_WINDOW_SAMPLES = 1800


@dataclass(frozen=True)
class ParityCase:
    key: str
    title: str
    channel: str
    time_range: tuple[float, float] | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                _json_safe(payload),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _rect_record(rect) -> dict[str, int]:
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "width": int(rect.width()),
        "height": int(rect.height()),
    }


def _range_record(values) -> list[float]:
    return [float(values[0]), float(values[1])]


def _profile_record(profile) -> dict[str, Any]:
    return {
        "strategy": str(profile.strategy),
        "source_length": int(profile.source_length),
        "finite_count": int(profile.finite_count),
        "monotonic_time": bool(profile.monotonic_time),
        "approx_unique_count": int(profile.approx_unique_count),
        "transition_fraction": float(profile.transition_fraction),
        "normalized_step_quantiles": [
            float(value) for value in profile.normalized_step_quantiles
        ],
        "discrete_small_domain": bool(profile.discrete_small_domain),
    }


def _image_record(path: Path) -> dict[str, Any]:
    from PyQt5.QtGui import QImageReader

    target = path.resolve(strict=True)
    reader = QImageReader(str(target))
    image = reader.read()
    if image.isNull():
        raise RuntimeError(f"cannot decode image {target}: {reader.errorString()}")
    return {
        "path": str(target),
        "width": int(image.width()),
        "height": int(image.height()),
        "bytes": int(target.stat().st_size),
        "sha256": _sha256(target),
    }


def _save_crop(image, rect, path: Path) -> dict[str, Any]:
    from PyQt5.QtCore import QRect

    bounded = QRect(rect).intersected(image.rect())
    if not bounded.isValid() or bounded.isEmpty():
        raise RuntimeError(f"invalid plot crop {bounded} for {image.size()}")
    cropped = image.copy(bounded)
    if cropped.isNull() or not cropped.save(str(path), "PNG"):
        raise RuntimeError(f"failed to save plot crop: {path}")
    record = _image_record(path)
    record["source_rect"] = _rect_record(bounded)
    return record


def _pen_color(pen) -> str:
    try:
        return str(pen.color().name()).lower()
    except Exception:
        return str(pen)


def _smooth_time_range(time_values: np.ndarray, signal: np.ndarray) -> tuple[float, float]:
    """Choose a deterministic, visibly varying low-density real-data window."""

    count = min(SMOOTH_WINDOW_SAMPLES, int(signal.size))
    if count < 2:
        raise RuntimeError("smooth channel has fewer than two samples")
    stride = max(1, count // 2)
    starts = list(range(0, signal.size - count + 1, stride))
    final_start = signal.size - count
    if not starts or starts[-1] != final_start:
        starts.append(final_start)

    def score(start: int) -> tuple[float, float, int]:
        window = np.asarray(signal[start : start + count], dtype=float)
        finite = window[np.isfinite(window)]
        if finite.size < 2:
            return (-1.0, -1.0, -start)
        return (float(np.std(finite)), float(np.ptp(finite)), -start)

    selected = max(starts, key=score)
    lo = float(time_values[selected])
    hi = float(time_values[selected + count - 1])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        raise RuntimeError("cannot select a finite smooth-channel time window")
    return lo, hi


def _case_arrays(file_data, case: ParityCase):
    raw_time = np.asarray(file_data.time_array, dtype=float)
    raw_signal = file_data.data[case.channel].to_numpy(dtype=float, copy=False)
    if case.time_range is None:
        return raw_time, raw_signal
    lo, hi = case.time_range
    mask = (raw_time >= lo) & (raw_time <= hi)
    return raw_time[mask], raw_signal[mask]


def _reference_plot_rect(canvas):
    from PyQt5.QtCore import QPoint, QRectF

    plot_items = []
    for handle in canvas.axes_list:
        plot = getattr(handle, "plot_item", None)
        if plot is not None and plot not in plot_items:
            plot_items.append(plot)
    if not plot_items:
        return canvas.rect()
    scene_rect = QRectF(plot_items[0].sceneBoundingRect())
    for plot in plot_items[1:]:
        scene_rect = scene_rect.united(plot.sceneBoundingRect())
    viewport_rect = canvas._glw.mapFromScene(scene_rect).boundingRect()
    origin = canvas._glw.mapTo(canvas, QPoint(0, 0))
    viewport_rect.translate(origin)
    return viewport_rect.intersected(canvas.rect())


def _render_reference(
    app,
    file_data,
    source_id: str,
    case: ParityCase,
    case_dir: Path,
) -> dict[str, Any]:
    from PyQt5.QtGui import QImage
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    time_values, signal = _case_arrays(file_data, case)
    unit = str(file_data.channel_units.get(case.channel, "") or "")
    color = FILE_PALETTES[0][0]
    display_name = file_data.get_prefixed_channel(case.channel)
    canvas = TimeDomainCanvasPG()
    canvas.resize(OUTPUT_WIDTH, OUTPUT_HEIGHT)
    canvas.show()
    app.processEvents()
    try:
        canvas.plot_channels(
            [
                (
                    display_name,
                    True,
                    time_values,
                    signal,
                    color,
                    unit,
                    source_id,
                )
            ],
            mode="subplot",
            xlabel="Time (s)",
            render_context_key=("gate45-singlefile-parity", case.key),
            full_rebuild_reason="gate45-singlefile-parity",
        )
        app.processEvents()
        canvas.try_enable_idle_quality()
        app.processEvents()

        pair = canvas._channel_lines[display_name]
        axis = pair[0]
        curve = pair[1].plot_data_item
        painter_curve = curve.curve
        idle_antialias = bool(painter_curve.opts.get("antialias", False))
        export_observations: list[dict[str, Any]] = []
        original_grab_scaled = canvas._grab_widget_scaled

        def observe_export(widget, scale):
            shown_x, _shown_y = curve.getData()
            export_observations.append(
                {
                    "antialias": bool(
                        painter_curve.opts.get("antialias", False)
                    ),
                    "display_point_count": int(len(shown_x)),
                    "scale": float(scale),
                }
            )
            return original_grab_scaled(widget, scale)

        canvas._grab_widget_scaled = observe_export
        try:
            pixmap = canvas.grab_pixmap(scale=1.0)
        finally:
            canvas._grab_widget_scaled = original_grab_scaled
        if pixmap.isNull():
            raise RuntimeError("single-file grab returned a null pixmap")
        device_pixel_ratio = float(pixmap.devicePixelRatioF())
        if not np.isfinite(device_pixel_ratio) or device_pixel_ratio <= 0.0:
            device_pixel_ratio = 1.0
        logical_width = int(round(pixmap.width() / device_pixel_ratio))
        logical_height = int(round(pixmap.height() / device_pixel_ratio))
        if logical_width != OUTPUT_WIDTH or logical_height != OUTPUT_HEIGHT:
            raise RuntimeError(
                "single-file grab logical geometry drifted: "
                f"{logical_width}x{logical_height} from native "
                f"{pixmap.width()}x{pixmap.height()} DPR={device_pixel_ratio:g}"
            )
        native_path = case_dir / "reference_grab_native.png"
        if not pixmap.save(str(native_path), "PNG"):
            raise RuntimeError(f"failed to save native single-file grab: {native_path}")
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        if image.width() != OUTPUT_WIDTH or image.height() != OUTPUT_HEIGHT:
            from PyQt5.QtCore import Qt

            image = image.scaled(
                OUTPUT_WIDTH,
                OUTPUT_HEIGHT,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        image.setDevicePixelRatio(1.0)
        full_path = case_dir / "reference_full.png"
        if not image.save(str(full_path), "PNG"):
            raise RuntimeError(f"failed to save single-file reference: {full_path}")
        plot_rect = _reference_plot_rect(canvas)
        crop_path = case_dir / "reference_plot.png"
        crop_record = _save_crop(image, plot_rect, crop_path)
        shown_x, _shown_y = curve.getData()
        profiles = list(canvas._channel_render_profiles.values())
        profile = profiles[0] if profiles else classify_render_profile(
            time_values,
            signal,
            source_revision_for(time_values, signal),
        )
        view_range = axis.view_box.viewRange()
        return {
            "reference_surface": (
                "TimeDomainCanvasPG production plot_channels/bind/export/grab surface"
            ),
            "execution": "TimeDomainCanvasPG.plot_channels -> grab_pixmap",
            "native_grab": _image_record(native_path),
            "device_pixel_ratio": device_pixel_ratio,
            "full_image": _image_record(full_path),
            "plot_crop": crop_record,
            "axis_range": {
                "x": _range_record(view_range[0]),
                "y": _range_record(view_range[1]),
            },
            "display_point_count": int(len(shown_x)),
            "envelope_point_count": int(len(shown_x)),
            "color": _pen_color(curve.opts.get("pen")),
            "idle_antialias": idle_antialias,
            "export_observations": export_observations,
            "export_antialias": bool(
                export_observations
                and all(item["antialias"] for item in export_observations)
            ),
            "quality_status": dict(canvas.quality_status()),
            "render_profile": _profile_record(profile),
        }
    finally:
        canvas.close()
        app.processEvents()


def _inspect_batch_scene(scene) -> dict[str, Any]:
    from PyQt5.QtCore import QPoint, QRect, QRectF
    from PyQt5.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QLineEdit,
        QSpinBox,
    )

    if hasattr(scene, "plot_rect_in_widget"):
        plot_rect = scene.plot_rect_in_widget()
    elif scene.plots:
        scene_rect = QRectF(scene.plots[0].sceneBoundingRect())
        for plot in scene.plots[1:]:
            scene_rect = scene_rect.united(plot.sceneBoundingRect())
        plot_rect = scene.widget.mapFromScene(scene_rect).boundingRect()
        origin = scene.widget.viewport().mapTo(scene.widget, QPoint(0, 0))
        plot_rect.translate(origin)
        plot_rect = plot_rect.intersected(scene.widget.rect())
    else:
        plot_rect = QRect(scene.widget.rect())

    curves = []
    for index, curve in enumerate(scene.curves):
        shown_x, _shown_y = curve.getData()
        binding = (
            scene._time_curve_bindings[index]
            if index < len(scene._time_curve_bindings)
            else None
        )
        curves.append(
            {
                "display_point_count": int(len(shown_x)),
                "envelope_point_count": int(len(shown_x)),
                "color": _pen_color(curve.opts.get("pen")),
                "antialias": bool(curve.opts.get("antialias", False)),
                "render_profile": (
                    _profile_record(binding.profile) if binding is not None else None
                ),
            }
        )
    control_count = sum(
        len(scene.widget.findChildren(widget_type))
        for widget_type in (QAbstractButton, QComboBox, QLineEdit, QSpinBox)
    )
    return {
        "plot_rect": _rect_record(plot_rect),
        "axis_ranges": [
            {
                "x": _range_record(plot.vb.viewRange()[0]),
                "y": _range_record(plot.vb.viewRange()[1]),
            }
            for plot in scene.plots
        ],
        "curves": curves,
        "qt_control_count": int(control_count),
        "panel_titles": list(scene.panel_titles),
    }


def _render_batch(
    source_path: Path,
    case: ParityCase,
    case_dir: Path,
) -> dict[str, Any]:
    from PyQt5.QtGui import QImageReader
    import mf4_analyzer.batch_render_qt as qt_renderer

    batch_dir = case_dir / "batch"
    batch_dir.mkdir(parents=True, exist_ok=False)
    params: dict[str, Any] = {
        "render_group_by": "source",
        "render_layout": "subplot",
        # Single-file TimeDomainCanvasPG displays the acquisition-time axis
        # verbatim, including a non-zero source start or a selected subrange.
        "x_origin": "absolute",
    }
    if case.time_range is not None:
        params["time_range"] = list(case.time_range)
    preset = AnalysisPreset.free_config(
        name=f"Gate 4.5 single-file parity: {case.key}",
        method="time",
        target_signals=(case.channel,),
        target_policy="common",
        params=params,
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            image_format="png",
            image_size="custom",
            image_width=OUTPUT_WIDTH,
            image_height=OUTPUT_HEIGHT,
            image_dpi=OUTPUT_DPI,
            image_background="white",
            image_line_width=1.5,
            conflict_policy="error",
            write_manifest=True,
            resume_policy="none",
        ),
    )
    preset = replace(preset, source_paths=(str(source_path),))

    scene_records: list[dict[str, Any]] = []
    original_render_scene = qt_renderer.render_scene_image

    def inspect_render(scene, *, metadata=None):
        image = original_render_scene(scene, metadata=metadata)
        scene_records.append(_inspect_batch_scene(scene))
        return image

    qt_renderer.render_scene_image = inspect_render
    try:
        result = BatchRunner({}).run(preset, batch_dir)
    finally:
        qt_renderer.render_scene_image = original_render_scene

    if result.status != "done" or result.blocked:
        raise RuntimeError(
            f"batch run failed for {case.key}: "
            f"status={result.status}, blocked={result.blocked}"
        )
    if result.degraded_count or len(result.items) != 1:
        raise RuntimeError(
            f"unexpected batch result for {case.key}: "
            f"items={len(result.items)}, degraded={result.degraded_count}"
        )
    item = result.items[0]
    if item.status != "done":
        raise RuntimeError(
            f"batch item failed for {case.key}: {item.status}: {item.message}"
        )
    if len(scene_records) != 1:
        raise RuntimeError(
            f"expected one inspected batch scene, got {len(scene_records)}"
        )

    if not result.manifest_path:
        raise RuntimeError(f"batch run did not produce a manifest for {case.key}")
    manifest = load_batch_manifest(result.manifest_path)
    group_artifacts = [
        group.get("artifact")
        for group in manifest.get("render_groups", ())
        if isinstance(group.get("artifact"), Mapping)
    ]
    if len(group_artifacts) != 1 or not group_artifacts[0].get("path"):
        raise RuntimeError(
            f"expected one grouped Batch PNG artifact, got {group_artifacts}"
        )
    batch_path = Path(str(group_artifacts[0]["path"])).resolve(strict=True)
    reader = QImageReader(str(batch_path))
    batch_image = reader.read()
    if batch_image.isNull():
        raise RuntimeError(
            f"cannot decode batch PNG {batch_path}: {reader.errorString()}"
        )
    if batch_image.width() != OUTPUT_WIDTH or batch_image.height() != OUTPUT_HEIGHT:
        raise RuntimeError(
            f"batch PNG geometry drifted: "
            f"{batch_image.width()}x{batch_image.height()}"
        )
    scene_record = scene_records[0]
    rect = scene_record["plot_rect"]
    from PyQt5.QtCore import QRect

    plot_rect = QRect(rect["x"], rect["y"], rect["width"], rect["height"])
    crop_path = case_dir / "batch_plot.png"
    crop_record = _save_crop(batch_image, plot_rect, crop_path)
    return {
        "execution": "AnalysisPreset -> BatchRunner -> batch_render_qt",
        "preset": {
            "name": preset.name,
            "method": preset.method,
            "params": dict(preset.params),
            "target_signals": list(preset.target_signals),
            "source_paths": list(preset.source_paths),
            "output": asdict(preset.outputs),
        },
        "run_status": result.status,
        "manifest_path": str(Path(result.manifest_path).resolve()) if result.manifest_path else None,
        "warnings": list(result.warnings),
        "full_image": _image_record(batch_path),
        "plot_crop": crop_record,
        "axis_range": scene_record["axis_ranges"][0],
        "display_point_count": scene_record["curves"][0]["display_point_count"],
        "envelope_point_count": scene_record["curves"][0]["envelope_point_count"],
        "color": scene_record["curves"][0]["color"],
        "antialias": scene_record["curves"][0]["antialias"],
        "render_profile": scene_record["curves"][0]["render_profile"],
        "qt_control_count": scene_record["qt_control_count"],
        "panel_titles": scene_record["panel_titles"],
    }


def _axis_delta(reference: Mapping[str, Any], batch: Mapping[str, Any]):
    return {
        axis: [
            float(batch[axis][index]) - float(reference[axis][index])
            for index in (0, 1)
        ]
        for axis in ("x", "y")
    }


def _draw_contact_sheet(case_records: list[Mapping[str, Any]], target: Path) -> None:
    from PyQt5.QtCore import QRect, Qt
    from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen

    sheet = QImage(OUTPUT_WIDTH, OUTPUT_HEIGHT, QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#f4f7fb"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.Antialiasing, True)
    title_font = QFont()
    title_font.setPointSizeF(16.0)
    title_font.setBold(True)
    label_font = QFont()
    label_font.setPointSizeF(10.0)
    label_font.setBold(True)
    painter.setPen(QColor("#273449"))
    painter.setFont(title_font)
    painter.drawText(
        QRect(24, 10, OUTPUT_WIDTH - 48, 42),
        Qt.AlignLeft | Qt.AlignVCenter,
        "Gate 4.5 · real MF4 · single-file vs Batch Qt plot crops",
    )

    outer_margin = 24
    gutter = 20
    top = 60
    row_gap = 16
    row_height = (OUTPUT_HEIGHT - top - outer_margin - row_gap) // 2
    cell_width = (OUTPUT_WIDTH - 2 * outer_margin - gutter) // 2
    label_height = 34
    pen = QPen(QColor("#cbd5e1"))
    pen.setWidth(1)

    for row_index, record in enumerate(case_records):
        y = top + row_index * (row_height + row_gap)
        sources = (
            ("Single-file reference", record["reference"]["plot_crop"]["path"]),
            ("Batch Qt (production PNG crop)", record["batch"]["plot_crop"]["path"]),
        )
        for column, (side_label, raw_path) in enumerate(sources):
            x = outer_margin + column * (cell_width + gutter)
            cell = QRect(x, y, cell_width, row_height)
            painter.fillRect(cell, QColor("#ffffff"))
            painter.setPen(pen)
            painter.drawRect(cell.adjusted(0, 0, -1, -1))
            painter.setPen(QColor("#273449"))
            painter.setFont(label_font)
            painter.drawText(
                QRect(x + 10, y, cell_width - 20, label_height),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{record['title']} · {side_label}",
            )
            source = QImage(str(raw_path))
            if source.isNull():
                raise RuntimeError(f"cannot load contact-sheet source: {raw_path}")
            available = QRect(
                x + 8,
                y + label_height,
                cell_width - 16,
                row_height - label_height - 8,
            )
            scaled = source.scaled(
                available.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            draw_x = available.x() + (available.width() - scaled.width()) // 2
            draw_y = available.y() + (available.height() - scaled.height()) // 2
            painter.drawImage(draw_x, draw_y, scaled)
    painter.end()
    if not sheet.save(str(target), "PNG"):
        raise RuntimeError(f"failed to save contact sheet: {target}")


def _isolate_qsettings(run_root: Path) -> None:
    from PyQt5.QtCore import QSettings

    settings_root = run_root / "qsettings"
    cache_root = run_root / "cache"
    settings_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CONFIG_HOME"] = str(settings_root)
    os.environ["XDG_CACHE_HOME"] = str(cache_root)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    for fmt in (QSettings.IniFormat, QSettings.NativeFormat):
        QSettings.setPath(fmt, QSettings.UserScope, str(settings_root))


def run(args: argparse.Namespace) -> int:
    source_path = args.source.expanduser().resolve(strict=True)
    output_base = args.output_dir.expanduser().resolve(strict=False)
    run_root = output_base / (
        datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8]
    )
    run_root.mkdir(parents=True, exist_ok=False)
    evidence_path = run_root / "gate45-singlefile-parity.json"
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "started_at": _utc_now(),
        "run_root": str(run_root),
        "source_path": str(source_path),
        "requested_qt_platform": os.environ.get("QT_QPA_PLATFORM", ""),
        "expected_qt_platform": args.expect_platform or "",
        "output_geometry": {
            "width": OUTPUT_WIDTH,
            "height": OUTPUT_HEIGHT,
            "dpi": OUTPUT_DPI,
        },
        "visual_pass_claimed": False,
        "visual_review_required": True,
        "reference_surface": (
            "TimeDomainCanvasPG production plot_channels/bind/export/grab surface"
        ),
    }
    try:
        _isolate_qsettings(run_root)
        from mf4_analyzer.batch_render_qt._dispatch import ensure_app

        app = ensure_app()
        actual_platform = str(app.platformName())
        evidence["actual_qt_platform"] = actual_platform
        if args.expect_platform and actual_platform != args.expect_platform:
            raise RuntimeError(
                f"Qt platform mismatch: {actual_platform!r} != "
                f"{args.expect_platform!r}"
            )

        loaded_sources = tuple(
            DEFAULT_SOURCE_ADAPTER_REGISTRY.load_sources(str(source_path))
        )
        if len(loaded_sources) != 1:
            raise RuntimeError(
                f"expected one logical source, got {len(loaded_sources)}"
            )
        loaded = loaded_sources[0]
        file_data = loaded.file_data
        for channel in (HIGH_VARIATION_CHANNEL, SMOOTH_CHANNEL):
            if channel not in file_data.data.columns:
                raise RuntimeError(f"required real channel is missing: {channel}")
        raw_time = np.asarray(file_data.time_array, dtype=float)
        smooth_signal = file_data.data[SMOOTH_CHANNEL].to_numpy(
            dtype=float, copy=False
        )
        smooth_range = _smooth_time_range(raw_time, smooth_signal)
        cases = (
            ParityCase(
                "high_variation",
                "High variation · full range",
                HIGH_VARIATION_CHANNEL,
                None,
            ),
            ParityCase(
                "smooth",
                "Smooth line · low-density real window",
                SMOOTH_CHANNEL,
                smooth_range,
            ),
        )

        evidence["source"] = {
            "path": str(source_path),
            "bytes": int(source_path.stat().st_size),
            "sha256": _sha256(source_path),
            "source_id": str(loaded.source_id),
            "group_id": str(loaded.group_id),
            "display_name": str(loaded.display_name),
            "sample_count": int(len(file_data.data)),
            "channel_count": int(len(file_data.get_signal_channels())),
            "fs": float(file_data.fs),
            "time_source": str(getattr(file_data, "_time_source", "")),
        }

        case_records = []
        for index, case in enumerate(cases, 1):
            print(f"[{index}/{len(cases)}] {case.key}: {case.channel}", flush=True)
            case_dir = run_root / case.key
            case_dir.mkdir(parents=True, exist_ok=False)
            time_values, signal = _case_arrays(file_data, case)
            raw_profile = classify_render_profile(
                time_values,
                signal,
                source_revision_for(
                    time_values,
                    signal,
                    explicit_revision=(str(loaded.source_id), case.channel),
                ),
            )
            reference = _render_reference(
                app,
                file_data,
                str(loaded.source_id),
                case,
                case_dir,
            )
            batch = _render_batch(source_path, case, case_dir)
            record = {
                "key": case.key,
                "title": case.title,
                "channel": case.channel,
                "unit": str(file_data.channel_units.get(case.channel, "") or ""),
                "time_range": list(case.time_range) if case.time_range else None,
                "selected_sample_count": int(len(signal)),
                "raw_profile": _profile_record(raw_profile),
                "reference": reference,
                "batch": batch,
                "comparison": {
                    "axis_delta_batch_minus_reference": _axis_delta(
                        reference["axis_range"], batch["axis_range"]
                    ),
                    "color_match": reference["color"] == batch["color"],
                    "batch_exact_1920x1080": (
                        batch["full_image"]["width"] == OUTPUT_WIDTH
                        and batch["full_image"]["height"] == OUTPUT_HEIGHT
                    ),
                    "batch_has_no_qt_controls": batch["qt_control_count"] == 0,
                    "smooth_aa_preserved": (
                        True
                        if case.key != "smooth"
                        else bool(reference["export_antialias"] and batch["antialias"])
                    ),
                },
            }
            case_records.append(record)
            app.processEvents()

        contact_path = run_root / "gate45-contact-sheet.png"
        _draw_contact_sheet(case_records, contact_path)
        checks = [record["comparison"] for record in case_records]
        evidence.update(
            {
                "status": "success",
                "finished_at": _utc_now(),
                "cases": case_records,
                "contact_sheet": _image_record(contact_path),
                "summary": {
                    "case_count": len(case_records),
                    "all_batch_images_exact_1920x1080": all(
                        check["batch_exact_1920x1080"] for check in checks
                    ),
                    "all_batch_scenes_control_free": all(
                        check["batch_has_no_qt_controls"] for check in checks
                    ),
                    "all_colors_match": all(check["color_match"] for check in checks),
                    "smooth_antialias_preserved": next(
                        check["smooth_aa_preserved"]
                        for record, check in zip(case_records, checks)
                        if record["key"] == "smooth"
                    ),
                },
                "acceptance_boundary": (
                    "This probe records machine geometry/render facts and a contact "
                    "sheet. Offscreen output is not a Cocoa foreground or Windows "
                    "release sign-off; a human must inspect the rendered evidence."
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
        _write_json(evidence_path, evidence)
        print(f"FAILED: {evidence['error']}", file=sys.stderr)
        print(f"Evidence: {evidence_path}", file=sys.stderr)
        return 1

    _write_json(evidence_path, evidence)
    print("PASS (machine evidence; visual review still required)", flush=True)
    print(f"Evidence: {evidence_path}", flush=True)
    print(f"Contact sheet: {evidence['contact_sheet']['path']}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Real MDF/MF4 input (defaults to X04C_Ripple.mf4).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Parent directory; a unique run directory is created beneath it.",
    )
    parser.add_argument(
        "--expect-platform",
        choices=("offscreen", "cocoa"),
        default=None,
        help="Fail if QApplication resolves to a different platform plugin.",
    )
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
