#!/usr/bin/env python3
"""Generate Batch 2 time/FFT Qt-render parity evidence.

The production renderer never imports concrete application canvases. This
verification-only harness does: it drives the same prepared arrays into the
new report renderer and the existing single-file pyqtgraph canvases, derives
plot crops from live scene geometry, and records structural + visual tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt5 import QtCore
from PyQt5.QtCore import QPoint, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPainter
from PyQt5.QtWidgets import QApplication, QWidget

from mf4_analyzer._palette import FILE_PALETTES
from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_qt import (
    BatchRenderContext,
    BatchSeries,
    BatchTimeFigureSpec,
)
from mf4_analyzer.batch_render_qt._builder import build_batch_scene
from mf4_analyzer.batch_render_qt._dispatch import ensure_app
from mf4_analyzer.batch_render_qt._export import render_scene_image
from mf4_analyzer.batch_render_qt._page import render_metadata
from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "superpowers" / "verify" / "batch-qt-render"
DPI = 144


@dataclass(frozen=True)
class ParityCase:
    name: str
    module: str
    payload: tuple[str, Any]
    params: dict[str, Any]
    context: BatchRenderContext
    reference: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _source_state_sha() -> str:
    paths = [
        ROOT / "mf4_analyzer" / "batch_image_options.py",
        ROOT / "tests" / "test_batch_render_qt.py",
        ROOT / "tests" / "test_batch_qt_render_parity.py",
        Path(__file__).resolve(),
        *sorted((ROOT / "mf4_analyzer" / "batch_render_qt").glob("*.py")),
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _context(method: str) -> BatchRenderContext:
    return BatchRenderContext(
        source_display_name="单帧振动.mf4",
        group="Batch 2 parity",
        channel="Acceleration",
        unit="g",
        method=method,
        task_id=f"T2-{method.upper()}",
        effective_facts={
            "window": "Hann",
            "nfft_effective": 1024,
            "actual_fs": 4096,
            "overlap": 0.5,
            "members": "1/1",
        },
    )


def _cases() -> list[ParityCase]:
    colors = FILE_PALETTES[0]
    x = np.linspace(0.0, 2.0, 401)
    raw = 0.76 * np.sin(2 * np.pi * 7.0 * x) + 0.18 * np.sin(
        2 * np.pi * 29.0 * x
    )
    filtered = 0.70 * np.sin(2 * np.pi * 7.0 * x)
    speed = 1500.0 + 180.0 * np.cos(2 * np.pi * 0.5 * x)
    panels = tuple(
        (0.52 + 0.04 * index)
        * np.sin(2 * np.pi * (2.0 + index * 1.2) * x + index * 0.17)
        for index in range(8)
    )
    angle = np.linspace(100.0, 820.0, x.size)
    custom_y = 0.8 * np.sin(np.deg2rad(angle * 3.0))
    freq = np.linspace(0.0, 1000.0, 1025)
    fft_linear = (
        0.002
        + 0.94 * np.exp(-((freq - 180.0) / 28.0) ** 2)
        + 0.31 * np.exp(-((freq - 520.0) / 63.0) ** 2)
    )
    fft_db = SpectrogramAnalyzer.amplitude_to_db(fft_linear, reference=1.0)

    single_spec = BatchTimeFigureSpec(
        (BatchSeries(x, raw, "Acceleration", unit="g"),)
    )
    raw_filtered_spec = BatchTimeFigureSpec(
        (
            BatchSeries(x, raw, "Acceleration · original", unit="g"),
            BatchSeries(
                x,
                filtered,
                "Acceleration · filtered",
                unit="g",
                linestyle="--",
            ),
        )
    )
    dual_spec = BatchTimeFigureSpec(
        (
            BatchSeries(x, raw, "Acceleration", unit="g"),
            BatchSeries(x, speed, "Speed", unit="rpm"),
        )
    )
    subplot_spec = BatchTimeFigureSpec(
        tuple(
            BatchSeries(x, values, f"Channel {index + 1}", unit="g", panel=index)
            for index, values in enumerate(panels)
        ),
        layout="subplot",
        panel_titles=tuple(f"Channel {index + 1}" for index in range(8)),
    )
    custom_spec = BatchTimeFigureSpec(
        (BatchSeries(angle, custom_y, "Angle-domain", unit="g", x_unit="deg"),),
        x_source="channel",
        x_origin="absolute",
        x_label="Angle (deg)",
    )
    common_fft_frame = pd.DataFrame(
        {"frequency_hz": freq, "amplitude": fft_linear}
    )
    preview_time = np.linspace(0.0, 1.0, 512)
    preview_signal = np.sin(2 * np.pi * 7.0 * preview_time)

    return [
        ParityCase(
            "time-single",
            "time",
            ("time", single_spec),
            {},
            _context("time"),
            {
                "mode": "overlay",
                "xlabel": "Time (s)",
                "rows": [
                    ("Acceleration", True, x, raw, colors[0], "g", "fid-a")
                ],
            },
        ),
        ParityCase(
            "time-raw-filtered",
            "time",
            ("time", raw_filtered_spec),
            {},
            _context("time"),
            {
                "mode": "overlay",
                "xlabel": "Time (s)",
                "rows": [
                    (
                        "Acceleration",
                        True,
                        x,
                        raw,
                        colors[0],
                        "g",
                        "fid-a",
                        {},
                    ),
                    (
                        "Acceleration · filtered",
                        True,
                        x,
                        filtered,
                        colors[0],
                        "g",
                        "fid-a",
                        {"companion_of": "Acceleration", "dash": True},
                    ),
                ],
            },
        ),
        ParityCase(
            "time-dual-y",
            "time",
            ("time", dual_spec),
            {},
            _context("time"),
            {
                "mode": "overlay",
                "xlabel": "Time (s)",
                "rows": [
                    ("Acceleration", True, x, raw, colors[0], "g", "fid-a"),
                    ("Speed", True, x, speed, colors[1], "rpm", "fid-b"),
                ],
            },
        ),
        ParityCase(
            "time-subplot8",
            "time",
            ("time", subplot_spec),
            {"render_group_by": "source"},
            _context("time"),
            {
                "mode": "subplot",
                "xlabel": "Time (s)",
                "rows": [
                    (
                        f"Channel {index + 1}",
                        True,
                        x,
                        values,
                        colors[index],
                        "g",
                        f"fid-{index}",
                    )
                    for index, values in enumerate(panels)
                ],
            },
        ),
        ParityCase(
            "time-custom-x",
            "time",
            ("time", custom_spec),
            {},
            _context("time"),
            {
                "mode": "overlay",
                "xlabel": "Angle (deg)",
                "rows": [
                    (
                        "Angle-domain",
                        True,
                        angle,
                        custom_y,
                        colors[0],
                        "g",
                        "fid-angle",
                    )
                ],
            },
        ),
        ParityCase(
            "fft-linear",
            "fft",
            ("fft", common_fft_frame),
            {},
            _context("fft"),
            {
                "freq": freq,
                "amp": fft_linear,
                "xlim": (0.0, 1000.0),
                "amp_label": "Amplitude (g)",
                "y_auto": True,
                "time": preview_time,
                "signal": preview_signal,
            },
        ),
        ParityCase(
            "fft-db",
            "fft",
            ("fft", common_fft_frame),
            {
                "amplitude_mode": "amplitude_db",
                "db_reference_mode": "manual",
                "db_reference": 1.0,
            },
            _context("fft"),
            {
                "freq": freq,
                "amp": fft_db,
                "xlim": (0.0, 1000.0),
                "amp_label": "Amplitude (dB re 1)",
                "y_auto": True,
                "time": preview_time,
                "signal": preview_signal,
            },
        ),
        ParityCase(
            "fft-manual-range",
            "fft",
            ("fft", common_fft_frame),
            {
                "x_auto": False,
                "x_min": 100.0,
                "x_max": 800.0,
                "y_auto": False,
                "y_min": 0.0,
                "y_max": 1.1,
            },
            _context("fft"),
            {
                "freq": freq,
                "amp": fft_linear,
                "xlim": (100.0, 800.0),
                "amp_label": "Amplitude (g)",
                "y_auto": False,
                "y_min": 0.0,
                "y_max": 1.1,
                "time": preview_time,
                "signal": preview_signal,
            },
        ),
    ]


def _scene_union(plots) -> QRectF:
    rect = QRectF(plots[0].sceneBoundingRect())
    for plot in plots[1:]:
        rect = rect.united(plot.sceneBoundingRect())
    return rect


def _scene_rect_in_widget(widget: QWidget, glw, scene_rect: QRectF) -> QRect:
    viewport_rect = glw.mapFromScene(scene_rect).boundingRect()
    origin = glw.viewport().mapTo(widget, QPoint(0, 0))
    viewport_rect.translate(origin)
    return viewport_rect.intersected(widget.rect())


def _render_widget(widget: QWidget, width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("#ffffff"))
    image.setDotsPerMeterX(round(DPI / 0.0254))
    image.setDotsPerMeterY(round(DPI / 0.0254))
    painter = QPainter(image)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    widget.render(painter)
    painter.end()
    return image


def _settle_reference(canvas, glw, plots, target_size: tuple[int, int]) -> QRect:
    app = QApplication.instance()
    for _ in range(8):
        app.processEvents()
        rect = _scene_rect_in_widget(canvas, glw, _scene_union(plots))
        width_delta = target_size[0] - rect.width()
        height_delta = target_size[1] - rect.height()
        if abs(width_delta) <= 1 and abs(height_delta) <= 1:
            return rect
        canvas.resize(
            max(320, canvas.width() + width_delta),
            max(320, canvas.height() + height_delta),
        )
    app.processEvents()
    return _scene_rect_in_widget(canvas, glw, _scene_union(plots))


def _pen_record(curve) -> dict[str, Any]:
    pen = curve.opts.get("pen")
    return {
        "color": pen.color().name(),
        "style": int(pen.style()),
        "width": float(pen.widthF()),
        "antialias": bool(curve.opts.get("antialias")),
    }


def _visual_pen_record(record: dict[str, Any]) -> dict[str, Any]:
    """Compare visual tokens while keeping export AA as a separate hard gate.

    TimeDomainCanvasPG may temporarily keep its interactive PlotDataItem AA
    flag off; the batch exporter is deliberately stricter and must always be
    true, so equality of that implementation flag would be the wrong parity
    contract.
    """

    return {
        "color": record["color"],
        "style": record["style"],
        "width": record["width"],
    }


def _ranges(views) -> list[dict[str, list[float]]]:
    return [
        {
            "x": [float(value) for value in view.viewRange()[0]],
            "y": [float(value) for value in view.viewRange()[1]],
        }
        for view in views
    ]


def _arrays_equal(left, right) -> bool:
    return bool(
        np.array_equal(np.asarray(left[0]), np.asarray(right[0]))
        and np.array_equal(np.asarray(left[1]), np.asarray(right[1]))
    )


def _range_close(left, right, *, y=True) -> bool:
    if len(left) != len(right):
        return False
    for lvalue, rvalue in zip(left, right):
        if not np.allclose(lvalue["x"], rvalue["x"], rtol=1e-7, atol=1e-7):
            return False
        if y and not np.allclose(
            lvalue["y"], rvalue["y"], rtol=1e-6, atol=1e-6
        ):
            return False
    return True


def _non_background_pixels(image: QImage, background="#ffffff") -> int:
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    pixels = np.frombuffer(ptr, dtype=np.uint8).reshape(
        converted.height(), converted.width(), 4
    )
    color = QColor(background)
    ref = np.array([color.red(), color.green(), color.blue(), color.alpha()])
    return int(np.count_nonzero(np.any(pixels != ref, axis=2)))


def _outer_corners_match(image: QImage, background: QColor) -> bool:
    return all(
        image.pixelColor(x, y) == background
        for x, y in (
            (1, 1),
            (image.width() - 2, 1),
            (1, image.height() - 2),
            (image.width() - 2, image.height() - 2),
        )
    )


def _plot_corner_ink_counts(scene, image: QImage) -> list[int]:
    """Return ink counts for every PlotItem corner, in TL/TR/BL/BR order.

    The lower-left sample is the critical one: pyqtgraph places its native
    auto-range button there.  Sampling all four corners keeps this pixel guard
    independent from the structural ``autoBtn.isVisible()`` assertion.
    """

    counts: list[int] = []
    viewport_origin = scene.widget.viewport().mapTo(scene.widget, QPoint(0, 0))
    for plot in scene.plots:
        rect = scene.widget.mapFromScene(plot.sceneBoundingRect()).boundingRect()
        rect.translate(viewport_origin)
        rect = rect.intersected(scene.widget.rect())
        width = min(16, rect.width())
        height = min(16, rect.height())
        for x, y in (
            (rect.left(), rect.top()),
            (rect.right() - width + 1, rect.top()),
            (rect.left(), rect.bottom() - height + 1),
            (rect.right() - width + 1, rect.bottom() - height + 1),
        ):
            patch = image.copy(x, y, width, height)
            counts.append(
                _non_background_pixels(patch, scene.theme.background)
            )
    return counts


def _save(image: QImage, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"failed to save {path}")
    return {
        "path": str(path),
        "width": image.width(),
        "height": image.height(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _batch_side(case: ParityCase, options: BatchRenderOptions, output_dir: Path):
    scene = build_batch_scene(
        case.payload,
        params=case.params,
        options=options,
        context=case.context,
    )
    try:
        image = render_scene_image(scene, metadata=render_metadata(case.context))
        rect = scene.plot_rect_in_widget()
        crop = image.copy(rect)
        curve_data = [curve.getData() for curve in scene.curves]
        views = [plot.vb for plot in scene.plots] + list(scene.auxiliary_views)
        machine = {
            "curve_data": curve_data,
            "curve_tokens": [_pen_record(curve) for curve in scene.curves],
            "ranges": _ranges(views),
            "viewport": [rect.width(), rect.height()],
            "text_overlaps": scene.adjacent_text_overlaps(),
            "plot_ink_pixels": _non_background_pixels(crop),
            "plot_corner_ink_pixels": _plot_corner_ink_counts(scene, image),
            "widget_chrome": {
                "frame_hidden": scene.widget.frameShape() == scene.widget.NoFrame,
                "horizontal_scrollbar_hidden": (
                    scene.widget.horizontalScrollBarPolicy()
                    == Qt.ScrollBarAlwaysOff
                ),
                "vertical_scrollbar_hidden": (
                    scene.widget.verticalScrollBarPolicy()
                    == Qt.ScrollBarAlwaysOff
                ),
                "focus_disabled": scene.widget.focusPolicy() == Qt.NoFocus,
                "outer_corners_clean": _outer_corners_match(
                    image, scene.theme.background
                ),
            },
            "chrome": [
                {
                    "auto_button_hidden": (
                        getattr(plot, "autoBtn", None) is None
                        or not plot.autoBtn.isVisible()
                    ),
                    "menu_disabled": plot.menuEnabled() is False,
                    "mouse_disabled": plot.vb.state["mouseEnabled"] == [False, False],
                }
                for plot in scene.plots
            ],
            "texts": scene.texts(),
            "axis_font_points": [
                float(plot.getAxis("bottom").style["tickFont"].pointSizeF())
                for plot in scene.plots
            ],
            "axis_pen_colors": [
                plot.getAxis("left").pen().color().name()
                for plot in scene.plots
            ],
            "grid_values": [
                [
                    plot.getAxis("left").grid,
                    plot.getAxis("bottom").grid,
                    plot.getAxis("top").grid,
                    plot.getAxis("right").grid,
                ]
                for plot in scene.plots
            ],
        }
        full_record = _save(image, output_dir / "batch" / f"{case.name}.png")
        crop_record = _save(crop, output_dir / "crops" / f"{case.name}-batch.png")
        return image, crop, machine, full_record, crop_record
    finally:
        scene.close()


def _reference_time(case: ParityCase, target_size: tuple[int, int]):
    app = QApplication.instance()
    canvas = TimeDomainCanvasPG()
    canvas.resize(max(640, target_size[0]), max(480, target_size[1]))
    canvas.setAttribute(Qt.WA_DontShowOnScreen, True)
    canvas.show()
    app.processEvents()
    canvas.plot_channels(
        case.reference["rows"],
        mode=case.reference["mode"],
        xlabel=case.reference["xlabel"],
    )
    app.processEvents()
    plots = []
    for axis in canvas.axes_list:
        plot = getattr(axis, "plot_item", None)
        if plot is not None and plot not in plots:
            plots.append(plot)
    entries = list(canvas._channel_lines.items())
    curves = [pair[1].plot_data_item for _name, pair in entries]
    handles = []
    for _name, pair in entries:
        handle = pair[0]
        if all(handle.view_box is not existing.view_box for existing in handles):
            handles.append(handle)
    rect = _settle_reference(canvas, canvas._glw, plots, target_size)
    image = _render_widget(canvas, canvas.width(), canvas.height())
    crop = image.copy(rect)
    machine = {
        "curve_data": [curve.getData() for curve in curves],
        "curve_tokens": [_pen_record(curve) for curve in curves],
        "ranges": _ranges([handle.view_box for handle in handles]),
        "viewport": [rect.width(), rect.height()],
        "plot_ink_pixels": _non_background_pixels(crop),
        "axis_font_points": [
            float(plot.getAxis("bottom").style["tickFont"].pointSizeF())
            for plot in plots
        ],
        "axis_pen_colors": [plot.getAxis("left").pen().color().name() for plot in plots],
        "grid_values": [
            [
                plot.getAxis("left").grid,
                plot.getAxis("bottom").grid,
                plot.getAxis("top").grid,
                plot.getAxis("right").grid,
            ]
            for plot in plots
        ],
        "overlay_grid_line_count": len(
            getattr(canvas._overlay_axes, "_overlay_grid_lines", [])
        ),
    }
    return canvas, image, crop, machine


def _reference_fft(case: ParityCase, target_size: tuple[int, int]):
    app = QApplication.instance()
    canvas = PgLineCanvas()
    canvas.resize(max(640, target_size[0]), max(480, target_size[1] + 200))
    canvas.setAttribute(Qt.WA_DontShowOnScreen, True)
    canvas.show()
    app.processEvents()
    ref = case.reference
    canvas.plot_spectra(
        [
            {
                "label": "Acceleration",
                "legend_label": "Acceleration",
                "color": "#1769e0",
                "freq": ref["freq"],
                "amp": ref["amp"],
                "time": ref["time"],
                "signal": ref["signal"],
            }
        ],
        xlim=ref["xlim"],
        amp_label=ref["amp_label"],
        title="FFT · Acceleration",
        y_auto=ref["y_auto"],
        y_min=ref.get("y_min", 0.0),
        y_max=ref.get("y_max", 0.0),
    )
    app.processEvents()
    plots = [canvas._plot_amp]
    rect = _settle_reference(canvas, canvas._glw, plots, target_size)
    image = _render_widget(canvas, canvas.width(), canvas.height())
    crop = image.copy(rect)
    curve = canvas._amp_curves[0]
    machine = {
        "curve_data": [curve.getData()],
        "curve_tokens": [_pen_record(curve)],
        "ranges": _ranges([canvas._plot_amp.vb]),
        "viewport": [rect.width(), rect.height()],
        "plot_ink_pixels": _non_background_pixels(crop),
        "axis_font_points": [
            float(canvas._plot_amp.getAxis("bottom").style["tickFont"].pointSizeF())
        ],
        "axis_pen_colors": [canvas._plot_amp.getAxis("left").pen().color().name()],
        "grid_values": [
            [
                canvas._plot_amp.getAxis("left").grid,
                canvas._plot_amp.getAxis("bottom").grid,
                canvas._plot_amp.getAxis("top").grid,
                canvas._plot_amp.getAxis("right").grid,
            ]
        ],
    }
    return canvas, image, crop, machine


def _reference_side(
    case: ParityCase, target_size: tuple[int, int], output_dir: Path
):
    canvas, image, crop, machine = (
        _reference_time(case, target_size)
        if case.module == "time"
        else _reference_fft(case, target_size)
    )
    try:
        full_record = _save(image, output_dir / "reference" / f"{case.name}.png")
        crop_record = _save(crop, output_dir / "crops" / f"{case.name}-reference.png")
        return image, crop, machine, full_record, crop_record
    finally:
        canvas.close()
        canvas.deleteLater()
        QApplication.instance().processEvents()


def _scaled(image: QImage, width=420, height=236) -> QImage:
    return image.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _case_row(name: str, batch_full: QImage, batch_crop: QImage, ref_crop: QImage) -> QImage:
    cell_w, cell_h = 420, 236
    gap, header = 16, 52
    row = QImage(
        gap * 4 + cell_w * 3,
        header + cell_h + gap,
        QImage.Format_ARGB32_Premultiplied,
    )
    row.fill(QColor("#eef2f7"))
    painter = QPainter(row)
    painter.setRenderHints(QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    painter.setPen(QColor("#273449"))
    painter.setFont(QFont("Arial", 11))
    labels = (f"{name} · batch report", "batch plot crop", "single-file plot crop")
    images = (batch_full, batch_crop, ref_crop)
    for index, (label, image) in enumerate(zip(labels, images)):
        x = gap + index * (cell_w + gap)
        painter.drawText(QRect(x, 0, cell_w, header), Qt.AlignCenter, label)
        scaled = _scaled(image, cell_w, cell_h)
        target_x = x + (cell_w - scaled.width()) // 2
        target_y = header + (cell_h - scaled.height()) // 2
        painter.drawImage(QPoint(target_x, target_y), scaled)
    painter.end()
    return row


def _module_sheet(rows: list[QImage]) -> QImage:
    gap = 14
    width = max(row.width() for row in rows)
    height = gap * (len(rows) + 1) + sum(row.height() for row in rows)
    sheet = QImage(width + gap * 2, height, QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#dde4ed"))
    painter = QPainter(sheet)
    y = gap
    for row in rows:
        painter.drawImage(QPoint(gap, y), row)
        y += row.height() + gap
    painter.end()
    return sheet


def _evaluate(case: ParityCase, batch: dict, reference: dict) -> dict[str, bool]:
    tokens_match = [
        _visual_pen_record(record) for record in batch["curve_tokens"]
    ] == [
        _visual_pen_record(record) for record in reference["curve_tokens"]
    ]
    data_match = len(batch["curve_data"]) == len(reference["curve_data"]) and all(
        _arrays_equal(left, right)
        for left, right in zip(batch["curve_data"], reference["curve_data"])
    )
    if case.name == "time-dual-y":
        # The single-file overlay renders its shared horizontal graticule with
        # explicit InfiniteLines (so its main AxisItem y-grid is off), whereas
        # the non-interactive batch view can use the pinned main-axis grid.
        # Verify the two equivalent visible mechanisms instead of equating the
        # private AxisItem.grid integers.
        grid_match = bool(
            batch["grid_values"][0][0]
            and batch["grid_values"][0][1]
            and not batch["grid_values"][0][2]
            and not batch["grid_values"][0][3]
            and reference.get("overlay_grid_line_count", 0) >= 9
        )
    else:
        grid_match = batch["grid_values"] == reference["grid_values"]
    checks = {
        "curve_data_match": data_match,
        "axis_ranges_match": _range_close(batch["ranges"], reference["ranges"]),
        "curve_tokens_match": tokens_match,
        "batch_export_antialias": all(
            record["antialias"] is True for record in batch["curve_tokens"]
        ),
        "axis_font_9pt": all(
            abs(value - 9.0) <= 0.01
            for value in batch["axis_font_points"] + reference["axis_font_points"]
        ),
        "axis_pen_match": batch["axis_pen_colors"] == reference["axis_pen_colors"],
        "grid_match": grid_match,
        "viewport_match": all(
            abs(left - right) <= 1
            for left, right in zip(batch["viewport"], reference["viewport"])
        ),
        "batch_has_plot_ink": batch["plot_ink_pixels"] > 500,
        "reference_has_plot_ink": reference["plot_ink_pixels"] > 500,
        "no_text_overlap": batch["text_overlaps"] == [],
        "no_native_chrome": (
            all(all(record.values()) for record in batch["chrome"])
            and all(batch["widget_chrome"].values())
            and max(batch["plot_corner_ink_pixels"], default=0) < 160
        ),
        "no_main_navigation": not any(
            token in "\n".join(batch["texts"])
            for token in ("时域", "FFT vs Time", "阶次")
        ),
    }
    return checks


def generate(output_dir: Path, *, width: int, height: int) -> dict[str, Any]:
    app = ensure_app()
    output_dir.mkdir(parents=True, exist_ok=True)
    options = BatchRenderOptions(width_px=width, height_px=height, dpi=DPI)
    case_records = []
    rows = {"time": [], "fft": []}
    for case in _cases():
        (
            batch_full,
            batch_crop,
            batch_machine,
            batch_full_record,
            batch_crop_record,
        ) = _batch_side(case, options, output_dir)
        (
            _reference_full,
            reference_crop,
            reference_machine,
            reference_full_record,
            reference_crop_record,
        ) = _reference_side(
            case,
            (batch_crop.width(), batch_crop.height()),
            output_dir,
        )
        checks = _evaluate(case, batch_machine, reference_machine)
        status = "PASS" if all(checks.values()) else "FAIL"
        rows[case.module].append(
            _case_row(case.name, batch_full, batch_crop, reference_crop)
        )
        case_records.append(
            {
                "name": case.name,
                "module": case.module,
                "status": status,
                "assertions": checks,
                "batch": {
                    "full": batch_full_record,
                    "crop": batch_crop_record,
                    "viewport": batch_machine["viewport"],
                    "ranges": batch_machine["ranges"],
                    "curve_tokens": batch_machine["curve_tokens"],
                    "plot_ink_pixels": batch_machine["plot_ink_pixels"],
                    "plot_corner_ink_pixels": batch_machine[
                        "plot_corner_ink_pixels"
                    ],
                    "widget_chrome": batch_machine["widget_chrome"],
                },
                "reference": {
                    "full": reference_full_record,
                    "crop": reference_crop_record,
                    "viewport": reference_machine["viewport"],
                    "ranges": reference_machine["ranges"],
                    "curve_tokens": reference_machine["curve_tokens"],
                    "plot_ink_pixels": reference_machine["plot_ink_pixels"],
                },
            }
        )
        app.processEvents()
    contact_records = {}
    for module, module_rows in rows.items():
        sheet = _module_sheet(module_rows)
        contact_records[module] = _save(
            sheet, output_dir / f"{module}-contact-sheet.png"
        )
    evidence = {
        "status": "PASS" if all(case["status"] == "PASS" for case in case_records) else "FAIL",
        "commit_sha": _git_sha(),
        "source_state_sha256": _source_state_sha(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "qt_qpa_platform_env": os.environ.get("QT_QPA_PLATFORM", ""),
        "qt_platform": app.platformName(),
        "qt_version": QtCore.QT_VERSION_STR,
        "pyqt_version": QtCore.PYQT_VERSION_STR,
        "pyqtgraph_version": pg.__version__,
        "requested_pixels": [width, height],
        "dpi": DPI,
        "cases": case_records,
        "contact_sheets": contact_records,
    }
    (output_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return evidence


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args(argv)
    evidence = generate(args.output_dir, width=args.width, height=args.height)
    failed = [
        case["name"] for case in evidence["cases"] if case["status"] != "PASS"
    ]
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "cases": len(evidence["cases"]),
                "failed": failed,
                "evidence": str(args.output_dir / "evidence.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
