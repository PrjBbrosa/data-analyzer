#!/usr/bin/env python3
"""Complete Batch 0 Qt/pyqtgraph render feasibility evidence generator.

This file is deliberately isolated under ``scratchpad/``. It imports the
existing single-file canvases read-only and builds an independent batch-page
prototype for parity and feasibility evidence; it is not product code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore
from PyQt5.QtCore import (
    QBuffer,
    QByteArray,
    QEventLoop,
    QIODevice,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QThread,
    QTimer,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtGui import QBrush, QColor, QFont, QFontDatabase, QImage, QPainter, QRawFont
from PyQt5.QtWidgets import QApplication, QDialog, QFrame, QWidget

from mf4_analyzer._palette import FILE_PALETTES
from mf4_analyzer.ui.pg_canvas._shared import (
    _hide_native_auto_button,
    show_major_grid_left_bottom_only,
)
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.fonts import (
    _apply_pg_axis_font,
    _pg_chart_font,
)
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
    PgHeatmapCanvas,
    _SmoothImageItem,
    _resolve_colormap,
)
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
from mf4_analyzer.ui.pg_canvas.ticks_math import _fmt_tick, _frame_to_nice


ROOT = Path(__file__).resolve().parent
IMAGES = ROOT / "images"
CONTACTS = ROOT / "contact-sheets"
EVIDENCE_PATH = ROOT / "evidence.json"
CJK_TEXT = "单帧振动加速度"
WIDTH = 1920
HEIGHT = 1080
DPI = 144
PERF_RUNS = 20


@dataclass(frozen=True)
class Theme:
    name: str
    background: QColor
    text: str
    muted: str
    subtle: str
    axis: str
    grid: str
    legend: str


THEMES = {
    "white": Theme(
        "white", QColor("#ffffff"), "#273449", "#64748b", "#8a97a8",
        "#9ca3af", "#d8e0ea", "#ffffff",
    ),
    "transparent": Theme(
        "transparent", QColor(0, 0, 0, 0), "#273449", "#64748b", "#8a97a8",
        "#9ca3af", "#d8e0ea", "#ffffff",
    ),
    "dark": Theme(
        "dark", QColor("#101418"), "#f2f5f7", "#aeb9c5", "#8e9aa7",
        "#6b7785", "#708090", "#20262d",
    ),
}


@lru_cache(maxsize=1)
def _git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload() -> dict:
    time_x = np.linspace(0.0, 10.0, 100_000, dtype=np.float64)
    acceleration = (
        0.72 * np.sin(2.0 * np.pi * 7.0 * time_x)
        + 0.17 * np.sin(2.0 * np.pi * 31.0 * time_x)
    )
    speed = 1500.0 + 165.0 * np.cos(2.0 * np.pi * 0.35 * time_x)
    panels = [
        (0.55 + 0.035 * i)
        * np.sin(2.0 * np.pi * (2.0 + i * 1.3) * time_x + i * 0.2)
        for i in range(8)
    ]
    freq = np.linspace(0.0, 2_000.0, 4_096, dtype=np.float64)
    fft = (
        -105.0
        + 61.0 * np.exp(-((freq - 320.0) / 48.0) ** 2)
        + 43.0 * np.exp(-((freq - 780.0) / 90.0) ** 2)
        + 18.0 * np.exp(-((freq - 1_280.0) / 170.0) ** 2)
    )
    heat_x = np.array([0.0, 1.0, 2.0], dtype=float)
    heat_y = np.array([10.0, 20.0], dtype=float)
    heat = np.array([[0.05, 0.58, 0.31], [0.94, 0.17, 0.73]], dtype=float)
    return {
        "time_x": time_x,
        "acceleration": acceleration,
        "speed": speed,
        "panels": panels,
        "freq": freq,
        "fft": fft,
        "heat_x": heat_x,
        "heat_y": heat_y,
        "heat": heat,
    }


PAYLOAD = payload()


def _envelope(x: np.ndarray, y: np.ndarray, columns: int) -> tuple[np.ndarray, np.ndarray]:
    """Small spike-only min/max envelope representative of prepared payload."""
    bucket_count = max(1, min(int(columns), len(x) // 2))
    usable = bucket_count * (len(x) // bucket_count)
    if usable < 2 or len(x) <= columns * 2:
        return x, y
    bx = x[:usable].reshape(bucket_count, -1)
    by = y[:usable].reshape(bucket_count, -1)
    mins = np.argmin(by, axis=1)
    maxs = np.argmax(by, axis=1)
    order = np.stack((mins, maxs), axis=1)
    order.sort(axis=1)
    rows = np.arange(bucket_count)[:, None]
    return bx[rows, order].ravel(), by[rows, order].ravel()


def _prepare_glw(glw: pg.GraphicsLayoutWidget, theme: Theme) -> None:
    glw.setAttribute(Qt.WA_DontShowOnScreen, True)
    glw.setFrameShape(QFrame.NoFrame)
    glw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    glw.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    glw.setFocusPolicy(Qt.NoFocus)
    glw.setStyleSheet("border: 0; background: transparent;")
    glw.viewport().setAutoFillBackground(False)
    glw.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
    if theme.name == "transparent":
        glw.setAttribute(Qt.WA_TranslucentBackground, True)
        glw.setBackground(None)
        glw.setBackgroundBrush(QBrush(Qt.NoBrush))
    else:
        glw.setBackground(theme.background)
    glw.ci.setContentsMargins(12, 10, 12, 10)
    glw.ci.setSpacing(4)


def _quiet_plot(plot, theme: Theme, *, right: bool = False) -> None:
    _hide_native_auto_button(plot)
    plot.hideButtons()
    plot.setMenuEnabled(False)
    plot.setMouseEnabled(x=False, y=False)
    plot.vb.setMouseEnabled(x=False, y=False)
    plot.vb.setBorder(pg.mkPen(theme.axis, width=1))
    show_major_grid_left_bottom_only(plot, alpha=0.28)
    sides = ("left", "right", "bottom", "top")
    for side in sides:
        axis = plot.getAxis(side)
        axis.setPen(pg.mkPen(theme.axis, width=1))
        axis.setTextPen(pg.mkPen(theme.muted))
        axis.setStyle(maxTickLevel=0)
        axis.enableAutoSIPrefix(False)
        _apply_pg_axis_font(axis, 9)
    if not right:
        plot.hideAxis("right")
    plot.hideAxis("top")


def _add_label(glw, *, row: int, text: str, theme: Theme, size: float, color: str, bold=False):
    item = glw.addLabel(
        text,
        row=row,
        col=0,
        color=color,
        size=f"{size:g}pt",
        bold=bold,
    )
    item.item.setFont(_pg_chart_font(max(1, round(size))))
    return item


def _page_shell(theme: Theme, title: str) -> pg.GraphicsLayoutWidget:
    glw = pg.GraphicsLayoutWidget()
    _prepare_glw(glw, theme)
    _add_label(
        glw,
        row=0,
        text=f"{title} · measurement.mf4 · source group" if title else "",
        theme=theme,
        size=12,
        color=theme.text,
        bold=True,
    )
    _add_label(
        glw,
        row=1,
        text="Channel · Qt/pyqtgraph feasibility spike",
        theme=theme,
        size=9,
        color=theme.muted,
    )
    _add_label(
        glw,
        row=2,
        text="window=Hann · NFFT=4096 · Fs=10 kHz · members=8/8 · DPI=144",
        theme=theme,
        size=8.5,
        color=theme.muted,
    )
    return glw


def _footer(glw, row: int, theme: Theme) -> None:
    _add_label(
        glw,
        row=row,
        text="Task SPIKE-0 · TraceLab batch export",
        theme=theme,
        size=7.5,
        color=theme.subtle,
    )


def _build_batch(case: str, theme: Theme, title: str = CJK_TEXT):
    colors = FILE_PALETTES[0]
    glw = _page_shell(theme, title)
    plots = []
    machine = {"case": case, "curve_antialias": [], "chrome": []}

    if case == "time-dual-y":
        plot = glw.addPlot(row=3, col=0)
        _quiet_plot(plot, theme, right=True)
        plots.append(plot)
        plot.setLabel("bottom", "Time (s)")
        plot.setLabel("left", "Acceleration (g)", color=colors[0])
        plot.showAxis("right")
        right_axis = plot.getAxis("right")
        right_axis.setLabel("Speed (rpm)", color=colors[1])
        right_axis.setPen(pg.mkPen(colors[1], width=1))
        right_axis.setTextPen(pg.mkPen(colors[1]))
        _apply_pg_axis_font(right_axis, 9)
        right_view = pg.ViewBox(enableMenu=False)
        right_view.setMouseEnabled(x=False, y=False)
        plot.scene().addItem(right_view)
        right_axis.linkToView(right_view)
        right_view.setXLink(plot.vb)

        def sync_right() -> None:
            right_view.setGeometry(plot.vb.sceneBoundingRect())
            right_view.linkedViewChanged(plot.vb, right_view.XAxis)

        plot.vb.sigResized.connect(sync_right)
        x1, y1 = _envelope(PAYLOAD["time_x"], PAYLOAD["acceleration"], 1_700)
        x2, y2 = _envelope(PAYLOAD["time_x"], PAYLOAD["speed"], 1_700)
        left_curve = pg.PlotDataItem(
            x1, y1, pen=pg.mkPen(colors[0], width=1.5), antialias=True
        )
        right_curve = pg.PlotDataItem(
            x2, y2, pen=pg.mkPen(colors[1], width=1.5), antialias=True
        )
        plot.addItem(left_curve)
        right_view.addItem(right_curve)
        plot.setXRange(0.0, 10.0, padding=0)
        legend = plot.addLegend(offset=(10, 10))
        legend.setBrush(pg.mkBrush(theme.legend))
        legend.addItem(left_curve, "Acceleration")
        legend.addItem(right_curve, "Speed")
        sync_right()
        machine["curve_antialias"] = [
            bool(left_curve.opts.get("antialias")),
            bool(right_curve.opts.get("antialias")),
        ]
        machine["curve_points"] = [len(x1), len(x2)]
        # Y deliberately remains in pyqtgraph auto-range here. Once the
        # widget has its final geometry, _render_batch captures the padded
        # auto ranges and applies the same shared nice-division framing used
        # by the existing single-file overlay canvas.
        glw._spike_dual_y_views = (
            ("Acceleration", plot.vb, plot.getAxis("left")),
            ("Speed", right_view, right_axis),
        )
        glw._spike_sync_right = sync_right
        _footer(glw, 4, theme)
        glw.ci.layout.setRowStretchFactor(3, 1)

    elif case == "time-subplot8":
        for index, values in enumerate(PAYLOAD["panels"]):
            row = 3 + index
            plot = glw.addPlot(row=row, col=0)
            _quiet_plot(plot, theme)
            plots.append(plot)
            plot.setTitle(
                f"Channel {index + 1} · g",
                color=theme.text,
                size="10pt",
            )
            plot.setLabel("left", "g")
            if index == 7:
                plot.setLabel("bottom", "Time (s)")
            else:
                plot.hideAxis("bottom")
            ex, ey = _envelope(PAYLOAD["time_x"], values, 1_700)
            curve = plot.plot(
                ex,
                ey,
                pen=pg.mkPen(colors[index], width=1.5),
                antialias=True,
            )
            plot.setXRange(0.0, 10.0, padding=0)
            machine["curve_antialias"].append(bool(curve.opts.get("antialias")))
        _footer(glw, 11, theme)
        for row in range(3, 11):
            glw.ci.layout.setRowStretchFactor(row, 1)
        machine["raw_points_per_panel"] = 100_000
        machine["rendered_envelope_points_per_panel"] = len(ex)

    elif case == "fft":
        plot = glw.addPlot(row=3, col=0)
        _quiet_plot(plot, theme)
        plots.append(plot)
        plot.setLabel("bottom", "Frequency (Hz)")
        plot.setLabel("left", "Amplitude (dB)")
        legend = plot.addLegend(offset=(10, 10))
        legend.setBrush(pg.mkBrush(theme.legend))
        curve = plot.plot(
            PAYLOAD["freq"],
            PAYLOAD["fft"],
            pen=pg.mkPen("#1769e0" if theme.name != "dark" else "#f2f5f7", width=1.5),
            antialias=True,
            name="Channel",
        )
        plot.setXRange(0.0, 2_000.0, padding=0)
        plot.setYRange(-110.0, -35.0, padding=0)
        machine["curve_antialias"] = [bool(curve.opts.get("antialias"))]
        _footer(glw, 4, theme)
        glw.ci.layout.setRowStretchFactor(3, 1)

    elif case == "heatmap":
        plot = glw.addPlot(row=3, col=0)
        _quiet_plot(plot, theme)
        plots.append(plot)
        plot.setLabel("bottom", "Time (s)")
        plot.setLabel("left", "Frequency (Hz)")
        cm = _resolve_colormap("turbo")
        # Match the existing PgHeatmapCanvas's real default
        # ``interp=None -> bilinear`` path exactly. Its _SmoothImageItem
        # scopes QPainter.SmoothPixmapTransform around ImageItem.paint;
        # using a plain ImageItem here produced visibly different 2x3 blocks.
        image = _SmoothImageItem()
        image.setOpts(axisOrder="row-major")
        image.set_smooth_transform(True)
        matrix = PAYLOAD["heat"]
        image.setImage(matrix, autoLevels=False)
        extent = QRectF(-0.5, 5.0, 3.0, 20.0)
        image.setRect(extent)
        image.setColorMap(cm)
        image.setLevels((0.0, 1.0))
        plot.addItem(image)
        cbar = pg.ColorBarItem(
            values=(0.0, 1.0),
            colorMap=cm,
            label="Amplitude",
            interactive=False,
            colorMapMenu=False,
        )
        cbar.setImageItem(image, insert_in=plot)
        _apply_pg_axis_font(cbar.getAxis("left"), 9)
        _apply_pg_axis_font(cbar.getAxis("right"), 9)
        plot.setXRange(extent.left(), extent.right(), padding=0)
        plot.setYRange(extent.top(), extent.bottom(), padding=0)
        machine["matrix_matches"] = bool(np.array_equal(image.image, matrix))
        machine["smooth_transform"] = image.smooth_transform_enabled()
        machine["matrix_shape"] = list(image.image.shape)
        machine["levels"] = list(map(float, image.getLevels()))
        machine["extent"] = [
            extent.left(), extent.top(), extent.width(), extent.height()
        ]
        machine["colorbar_interactive"] = False
        _footer(glw, 4, theme)
        glw.ci.layout.setRowStretchFactor(3, 1)
    else:
        raise ValueError(case)

    for plot in plots:
        auto_button = getattr(plot, "autoBtn", None)
        machine["chrome"].append(
            {
                "auto_button_hidden": auto_button is None or not auto_button.isVisible(),
                "menu_disabled": not bool(getattr(plot, "menuEnabled", lambda: False)()),
                "mouse_x_disabled": not bool(plot.vb.state["mouseEnabled"][0]),
                "mouse_y_disabled": not bool(plot.vb.state["mouseEnabled"][1]),
            }
        )
    return glw, plots, machine


def _settle_batch_dual_y(widget, machine: dict) -> None:
    """Apply the single-file overlay's auto-padding + nice-grid semantics."""
    views = getattr(widget, "_spike_dual_y_views", ())
    sync_right = getattr(widget, "_spike_sync_right", None)
    if callable(sync_right):
        sync_right()
    auto_padded = []
    for name, view, _axis in views:
        view.enableAutoRange(axis="y", enable=True)
        view.updateAutoRange()
        x_range, y_range = view.viewRange()
        auto_padded.append({
            "channel": name,
            "x": [float(value) for value in x_range],
            "y": [float(value) for value in y_range],
        })

    divisions = 10
    for _name, view, axis in views:
        lo, hi = view.viewRange()[1]
        bottom, top, ticks = _frame_to_nice(lo, hi, divisions)
        per_div = (top - bottom) / divisions
        view.enableAutoRange(axis="y", enable=False)
        view.setYRange(bottom, top, padding=0)
        axis.setStyle(maxTickLevel=0)
        axis.setTicks([
            [(value, _fmt_tick(value, per_div)) for value in ticks],
            [],
        ])

    machine["axis_range_semantics"] = (
        "pyqtgraph auto-range padding, then existing overlay "
        "_frame_to_nice at 10 Y divisions"
    )
    machine["axis_auto_padded_ranges"] = auto_padded
    machine["axis_ranges"] = [
        {
            "channel": name,
            "x": [float(value) for value in view.viewRange()[0]],
            "y": [float(value) for value in view.viewRange()[1]],
        }
        for name, view, _axis in views
    ]


def _scene_union(plots) -> QRectF:
    # The parity crop is derived from real PlotItem scene geometry, not a
    # fixed coordinate guess and not a whole-canvas grab. This intentionally
    # includes the axes, title/inside labels, legend and heatmap colorbar.
    rect = QRectF(plots[0].sceneBoundingRect())
    for plot in plots[1:]:
        rect = rect.united(plot.sceneBoundingRect())
    return rect


def _scene_rect_in_widget(widget: QWidget, glw, scene_rect: QRectF) -> QRect:
    viewport_rect = glw.mapFromScene(scene_rect).boundingRect()
    origin = glw.viewport().mapTo(widget, QPoint(0, 0))
    viewport_rect.translate(origin)
    return viewport_rect.intersected(widget.rect())


def _render_widget(widget: QWidget, *, theme: Theme, metadata: dict[str, str]) -> QImage:
    image = QImage(widget.width(), widget.height(), QImage.Format_ARGB32_Premultiplied)
    image.fill(theme.background)
    image.setDotsPerMeterX(round(DPI / 0.0254))
    image.setDotsPerMeterY(round(DPI / 0.0254))
    for key, value in metadata.items():
        image.setText(key, value)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    QWidget.render(widget, painter, QPoint())
    painter.end()
    return image


def _encode_png(image: QImage) -> int:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("PNG encoding failed")
    buffer.close()
    return data.size()


def _save_png(image: QImage, path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"failed to save {path}")
    reopened = QImage(str(path))
    return {
        "path": str(path.relative_to(ROOT)),
        "width": reopened.width(),
        "height": reopened.height(),
        "dots_per_meter_x": reopened.dotsPerMeterX(),
        "dots_per_meter_y": reopened.dotsPerMeterY(),
        "dpi_round_trip": reopened.dotsPerMeterX() * 0.0254,
        "metadata": {key: reopened.text(key) for key in reopened.textKeys()},
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _render_batch(case: str, theme_name: str, *, title: str = CJK_TEXT, size=(WIDTH, HEIGHT)):
    app = QApplication.instance()
    theme = THEMES[theme_name]
    widget, plots, machine = _build_batch(case, theme, title=title)
    widget.resize(*size)
    widget.show()
    app.processEvents()
    if case == "time-dual-y":
        _settle_batch_dual_y(widget, machine)
    image = _render_widget(
        widget,
        theme=theme,
        metadata={
            "Title": "TraceLab batch Qt spike",
            "Case": case,
            "Theme": theme_name,
            "Commit": _git_sha(),
        },
    )
    crop_rect = _scene_rect_in_widget(widget, widget, _scene_union(plots))
    crop = image.copy(crop_rect)
    machine["crop_rect"] = [
        crop_rect.x(), crop_rect.y(), crop_rect.width(), crop_rect.height()
    ]
    machine["pixel_size_exact"] = image.size().width() == size[0] and image.size().height() == size[1]
    corner = image.pixelColor(2, 2)
    machine["corner_rgba"] = [corner.red(), corner.green(), corner.blue(), corner.alpha()]
    expected = theme.background
    machine["background_corner_matches"] = corner == expected
    widget.close()
    widget.deleteLater()
    app.processEvents()
    return image, crop, machine


def _apply_reference_white(canvas) -> None:
    glw = canvas._glw
    _prepare_glw(glw, THEMES["white"])
    for plot in [item for item in getattr(canvas, "axes_list", [])]:
        del plot


def _settle_reference(canvas, glw, plots, target_size: tuple[int, int]) -> QRect:
    app = QApplication.instance()
    for _ in range(6):
        app.processEvents()
        rect = _scene_rect_in_widget(canvas, glw, _scene_union(plots))
        dw = target_size[0] - rect.width()
        dh = target_size[1] - rect.height()
        if abs(dw) <= 1 and abs(dh) <= 1:
            return rect
        canvas.resize(max(320, canvas.width() + dw), max(320, canvas.height() + dh))
    app.processEvents()
    return _scene_rect_in_widget(canvas, glw, _scene_union(plots))


def _build_reference(case: str, target_size: tuple[int, int]):
    app = QApplication.instance()
    colors = FILE_PALETTES[0]
    if case == "time-dual-y":
        canvas = TimeDomainCanvasPG()
        canvas.resize(WIDTH, HEIGHT)
        canvas.setAttribute(Qt.WA_DontShowOnScreen, True)
        canvas.show()
        app.processEvents()
        canvas.plot_channels(
            [
                ("Acceleration", True, PAYLOAD["time_x"], PAYLOAD["acceleration"], colors[0], "g", "fid-a"),
                ("Speed", True, PAYLOAD["time_x"], PAYLOAD["speed"], colors[1], "rpm", "fid-b"),
            ],
            mode="overlay",
            xlabel="Time (s)",
        )
        plots = [canvas.axes_list[0].plot_item]
    elif case == "time-subplot8":
        canvas = TimeDomainCanvasPG()
        canvas.resize(WIDTH, HEIGHT)
        canvas.setAttribute(Qt.WA_DontShowOnScreen, True)
        canvas.show()
        app.processEvents()
        rows = [
            (f"Channel {index + 1}", True, PAYLOAD["time_x"], values, colors[index], "g", f"fid-{index}")
            for index, values in enumerate(PAYLOAD["panels"])
        ]
        canvas.plot_channels(rows, mode="subplot", xlabel="Time (s)")
        plots = [axis.plot_item for axis in canvas.axes_list]
    elif case == "fft":
        canvas = PgLineCanvas()
        canvas.resize(WIDTH, HEIGHT)
        canvas.setAttribute(Qt.WA_DontShowOnScreen, True)
        canvas.show()
        app.processEvents()
        canvas.plot_spectra(
            [{
                "label": "Channel",
                "legend_label": "Channel",
                "color": "#1769e0",
                "freq": PAYLOAD["freq"],
                "amp": PAYLOAD["fft"],
                "time": PAYLOAD["time_x"],
                "signal": PAYLOAD["acceleration"],
            }],
            xlim=(0.0, 2_000.0),
            amp_label="Amplitude (dB)",
            title="FFT · Channel",
            y_auto=False,
            y_min=-110.0,
            y_max=-35.0,
        )
        plots = [canvas._plot_amp]
    elif case == "heatmap":
        canvas = PgHeatmapCanvas(with_slice=False)
        canvas.resize(WIDTH, HEIGHT)
        canvas.setAttribute(Qt.WA_DontShowOnScreen, True)
        canvas.show()
        app.processEvents()
        canvas.plot_or_update_heatmap(
            matrix=PAYLOAD["heat"],
            x_extent=(-0.5, 2.5),
            y_extent=(5.0, 25.0),
            x_label="Time (s)",
            y_label="Frequency (Hz)",
            title="FFT vs Time · Channel",
            cmap="turbo",
            cbar_label="Amplitude",
            amplitude_mode="amplitude",
            z_auto=False,
            z_floor=0.0,
            z_ceiling=1.0,
            x_coords=PAYLOAD["heat_x"],
            y_coords=PAYLOAD["heat_y"],
        )
        plots = [canvas._plot]
    else:
        raise ValueError(case)

    _apply_reference_white(canvas)
    app.processEvents()
    rect = _settle_reference(canvas, canvas._glw, plots, target_size)
    image = _render_widget(
        canvas,
        theme=THEMES["white"],
        metadata={"Title": "TraceLab existing single-file canvas", "Case": case},
    )
    crop = image.copy(rect)
    machine = {
        "full_size": [image.width(), image.height()],
        "crop_rect": [rect.x(), rect.y(), rect.width(), rect.height()],
        "target_viewport": list(target_size),
        "viewport_matches": abs(rect.width() - target_size[0]) <= 1 and abs(rect.height() - target_size[1]) <= 1,
    }
    if case == "time-dual-y":
        machine["axis_range_semantics"] = (
            "existing single-file overlay auto-range padding and nice-grid framing"
        )
        machine["axis_ranges"] = [
            {
                "channel": name,
                "x": [float(value) for value in axis.get_xlim()],
                "y": [float(value) for value in axis.get_ylim()],
            }
            for name, axis in zip(("Acceleration", "Speed"), canvas.axes_list)
        ]
    if case == "heatmap":
        machine["matrix_matches"] = bool(np.array_equal(canvas._img.image, PAYLOAD["heat"]))
        machine["levels"] = list(map(float, canvas._img.getLevels()))
    canvas.close()
    canvas.deleteLater()
    app.processEvents()
    return image, crop, machine


def _contact_sheet(left: QImage, right: QImage, labels: tuple[str, str]) -> QImage:
    gap = 24
    header = 48
    width = left.width() + right.width() + gap * 3
    height = max(left.height(), right.height()) + header + gap * 2
    sheet = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#eef2f7"))
    sheet.setDotsPerMeterX(round(DPI / 0.0254))
    sheet.setDotsPerMeterY(round(DPI / 0.0254))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setPen(QColor("#273449"))
    painter.setFont(QFont("Arial", 13))
    painter.drawText(QRect(gap, 0, left.width(), header), Qt.AlignCenter, labels[0])
    x2 = gap * 2 + left.width()
    painter.drawText(QRect(x2, 0, right.width(), header), Qt.AlignCenter, labels[1])
    painter.drawImage(QPoint(gap, header + gap), left)
    painter.drawImage(QPoint(x2, header + gap), right)
    painter.end()
    return sheet


def _draw_checker(painter: QPainter, rect: QRect, cell=16) -> None:
    for y in range(rect.top(), rect.bottom() + 1, cell):
        for x in range(rect.left(), rect.right() + 1, cell):
            odd = ((x - rect.left()) // cell + (y - rect.top()) // cell) % 2
            painter.fillRect(QRect(x, y, cell, cell), QColor("#d6dbe3" if odd else "#ffffff"))


def _theme_sheet(images: dict[tuple[str, str], QImage]) -> QImage:
    cases = ("time-dual-y", "time-subplot8", "fft", "heatmap")
    themes = ("white", "transparent", "dark")
    thumb_w = 720
    thumb_h = 405
    label_h = 34
    gap = 18
    sheet = QImage(
        len(themes) * (thumb_w + gap) + gap,
        len(cases) * (thumb_h + label_h + gap) + gap,
        QImage.Format_ARGB32_Premultiplied,
    )
    sheet.fill(QColor("#eef2f7"))
    sheet.setDotsPerMeterX(round(DPI / 0.0254))
    sheet.setDotsPerMeterY(round(DPI / 0.0254))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setFont(QFont("Arial", 11))
    painter.setPen(QColor("#273449"))
    for row, case in enumerate(cases):
        for col, theme in enumerate(themes):
            x = gap + col * (thumb_w + gap)
            y = gap + row * (thumb_h + label_h + gap)
            painter.drawText(QRect(x, y, thumb_w, label_h), Qt.AlignCenter, f"{case} · {theme}")
            target = QRect(x, y + label_h, thumb_w, thumb_h)
            if theme == "transparent":
                _draw_checker(painter, target)
            painter.drawImage(target, images[(case, theme)])
    painter.end()
    return sheet


def _qimage_array(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    return np.frombuffer(ptr, dtype=np.uint8).reshape(converted.height(), converted.width(), 4).copy()


def _cjk_font_evidence() -> dict:
    candidates = (
        "PingFang SC", "PingFang HK", "Hiragino Sans GB", "Hiragino Sans",
        "Microsoft YaHei", "Microsoft YaHei UI", "Noto Sans CJK SC",
        "Noto Sans SC", "Source Han Sans SC", "Arial Unicode MS", "STHeiti",
        "Songti SC",
    )
    installed = set(QFontDatabase().families())
    for family in candidates:
        if family not in installed:
            continue
        raw = QRawFont.fromFont(QFont(family, 12))
        supports = [bool(raw.supportsCharacter(char)) for char in CJK_TEXT]
        if raw.isValid() and all(supports):
            return {"font": family, "supports": dict(zip(CJK_TEXT, supports)), "pass": True}
    return {"font": None, "supports": {}, "pass": False}


class RenderDispatcher(QObject):
    request = pyqtSignal(object)

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.quitting = False
        self.request.connect(self._execute, type=Qt.BlockingQueuedConnection)
        app.aboutToQuit.connect(self._mark_quitting)

    @pyqtSlot()
    def _mark_quitting(self):
        self.quitting = True

    @pyqtSlot(object)
    def _execute(self, job):
        try:
            job["result"] = job["fn"]()
        except BaseException as exc:  # spike explicitly proves transport
            job["exception"] = exc
            job["traceback"] = traceback.format_exc()

    def call(self, fn: Callable):
        if self.quitting:
            raise RuntimeError("Qt application is exiting; render rejected")
        if QThread.currentThread() is self.app.thread():
            return fn()
        job = {"fn": fn}
        self.request.emit(job)
        if "exception" in job:
            exc = job["exception"]
            exc.add_note(job["traceback"])
            raise exc
        return job.get("result")


class ContractWorker(QThread):
    def __init__(self, dispatcher: RenderDispatcher):
        super().__init__()
        self.dispatcher = dispatcher
        self.result = None
        self.exception = None

    def run(self):
        try:
            gui_thread = self.dispatcher.call(lambda: QThread.currentThread() is self.dispatcher.app.thread())
            try:
                self.dispatcher.call(lambda: (_ for _ in ()).throw(ValueError("spike sentinel")))
            except Exception as exc:
                exception = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback_note": any("spike sentinel" in note for note in getattr(exc, "__notes__", [])),
                }
            else:
                exception = None
            self.result = {"gui_thread": gui_thread, "exception": exception}
        except BaseException:
            self.exception = traceback.format_exc()


class HeartbeatWorker(QThread):
    def __init__(self, dispatcher: RenderDispatcher, count: int):
        super().__init__()
        self.dispatcher = dispatcher
        self.count = count
        self.durations_ms = []
        self.exception = None

    def run(self):
        try:
            for _ in range(self.count):
                start = time.perf_counter()
                self.dispatcher.call(lambda: _render_and_encode("time-subplot8", "white"))
                self.durations_ms.append((time.perf_counter() - start) * 1_000.0)
        except BaseException:
            self.exception = traceback.format_exc()


def _wait_thread(worker: QThread, timeout_ms=120_000) -> bool:
    loop = QEventLoop()
    timed_out = {"value": False}
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (timed_out.__setitem__("value", True), loop.quit()))
    worker.finished.connect(loop.quit)
    timer.start(timeout_ms)
    worker.start()
    loop.exec_()
    timer.stop()
    if timed_out["value"] and worker.isRunning():
        return False
    return worker.wait(5_000)


def _thread_contract(app: QApplication) -> tuple[dict, RenderDispatcher]:
    dispatcher = RenderDispatcher(app)
    dialog = QDialog()
    dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.open()
    app.processEvents()
    worker = ContractWorker(dispatcher)
    reached = _wait_thread(worker, timeout_ms=15_000)
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
    result = {
        "modal_dialog_reachable": reached and worker.exception is None,
        "gui_thread_execution": bool(worker.result and worker.result["gui_thread"]),
        "exception_round_trip": bool(
            worker.result
            and worker.result["exception"]
            and worker.result["exception"]["type"] == "ValueError"
            and worker.result["exception"]["message"] == "spike sentinel"
            and worker.result["exception"]["traceback_note"]
        ),
        "worker_error": worker.exception,
    }
    worker.deleteLater()
    return result, dispatcher


def _render_and_encode(case: str, theme: str, *, size=(WIDTH, HEIGHT)) -> int:
    encoded, _render_ms, _encode_ms = _render_and_encode_profile(case, theme, size=size)
    return encoded


def _render_and_encode_profile(case: str, theme: str, *, size=(WIDTH, HEIGHT)):
    start = time.perf_counter()
    image, _crop, _machine = _render_batch(case, theme, size=size)
    rendered = time.perf_counter()
    encoded = _encode_png(image)
    finished = time.perf_counter()
    return (
        encoded,
        (rendered - start) * 1_000.0,
        (finished - rendered) * 1_000.0,
    )


def _percentile(values: list[float], percentile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), percentile))


def _rss_bytes() -> int | None:
    try:
        import psutil
        return int(psutil.Process().memory_info().rss)
    except Exception:
        # macOS reports ru_maxrss in bytes; Linux reports KiB. This is a
        # process peak (the Batch 0 requirement), not an instantaneous RSS.
        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1_024


def _performance(app: QApplication, dispatcher: RenderDispatcher) -> dict:
    results = {}
    for case in ("time-dual-y", "time-subplot8", "heatmap"):
        _render_and_encode(case, "white")
        durations = []
        render_durations = []
        encode_durations = []
        for _ in range(PERF_RUNS):
            _encoded, render_ms, encode_ms = _render_and_encode_profile(case, "white")
            render_durations.append(render_ms)
            encode_durations.append(encode_ms)
            durations.append(render_ms + encode_ms)
        results[case] = {
            "runs": PERF_RUNS,
            "scope": "build + show/processEvents + QImage render + cleanup + PNG encode",
            "p50_ms": statistics.median(durations),
            "p95_ms": _percentile(durations, 95),
            "min_ms": min(durations),
            "max_ms": max(durations),
            "render_component_p50_ms": statistics.median(render_durations),
            "render_component_p95_ms": _percentile(render_durations, 95),
            "png_encode_component_p50_ms": statistics.median(encode_durations),
            "png_encode_component_p95_ms": _percentile(encode_durations, 95),
            "budget_ms": 500.0,
            "pass": _percentile(durations, 95) <= 500.0,
        }

    rss_before = _rss_bytes()
    four_k = {}
    for case in ("time-dual-y", "time-subplot8", "heatmap"):
        start = time.perf_counter()
        encoded = _render_and_encode(case, "white", size=(3_840, 2_160))
        four_k[case] = {
            "elapsed_ms": (time.perf_counter() - start) * 1_000.0,
            "encoded_png_bytes": encoded,
            "rss_after_bytes": _rss_bytes(),
        }
    rss_after = _rss_bytes()

    ticks = [time.perf_counter()]
    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start()
    worker = HeartbeatWorker(dispatcher, PERF_RUNS)
    completed = _wait_thread(worker, timeout_ms=180_000)
    timer.stop()
    ticks.append(time.perf_counter())
    gaps = [(b - a) * 1_000.0 for a, b in zip(ticks, ticks[1:])]
    heartbeat = {
        "render_requests": PERF_RUNS,
        "timer_interval_ms": 50,
        "completed": completed and worker.exception is None,
        "worker_error": worker.exception,
        "tick_count": len(ticks),
        "max_gap_ms": max(gaps) if gaps else None,
        "over_100ms_count": sum(gap > 100.0 for gap in gaps),
        "budget_ms": 200.0,
        "pass": bool(gaps) and max(gaps) <= 200.0 and completed and worker.exception is None,
        "request_p50_ms": statistics.median(worker.durations_ms) if worker.durations_ms else None,
        "request_p95_ms": _percentile(worker.durations_ms, 95) if worker.durations_ms else None,
    }
    worker.deleteLater()
    return {
        "render_1080p": results,
        "four_k": four_k,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_delta_bytes": (
            rss_after - rss_before
            if rss_after is not None and rss_before is not None
            else None
        ),
        "heartbeat": heartbeat,
    }


def _platform_probe(app: QApplication, mode: str) -> int:
    expected = os.environ.get("QT_QPA_PLATFORM", "")
    image, _crop, machine = _render_batch("time-dual-y", "white")
    folder = "hidpi" if mode == "hidpi" else "cocoa"
    path = IMAGES / folder / "time-dual-y.png"
    artifact = _save_png(image, path)
    screen = app.primaryScreen()
    data = {
        "mode": mode,
        "requested_platform": expected,
        "actual_platform": app.platformName(),
        "screen_dpr": float(screen.devicePixelRatio()) if screen else None,
        "screen_logical_dpi": float(screen.logicalDotsPerInch()) if screen else None,
        "pixel_size_exact": machine["pixel_size_exact"],
        "artifact": artifact,
        "pass": machine["pixel_size_exact"] and artifact["width"] == WIDTH and artifact["height"] == HEIGHT,
    }
    output = ROOT / f"{mode}-evidence.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data["pass"] else 1


def _full(app: QApplication) -> int:
    cases = ("time-dual-y", "time-subplot8", "fft", "heatmap")
    batch_images = {}
    artifacts = []
    case_evidence = {}
    for case in cases:
        case_evidence[case] = {"themes": {}}
        for theme in THEMES:
            image, crop, machine = _render_batch(case, theme)
            batch_images[(case, theme)] = image
            full_path = IMAGES / "offscreen" / f"{case}-{theme}-batch.png"
            crop_path = IMAGES / "offscreen" / f"{case}-{theme}-batch-crop.png"
            artifacts.extend([_save_png(image, full_path), _save_png(crop, crop_path)])
            case_evidence[case]["themes"][theme] = machine

        white_machine = case_evidence[case]["themes"]["white"]
        target = tuple(white_machine["crop_rect"][2:4])
        ref_image, ref_crop, ref_machine = _build_reference(case, target)
        ref_path = IMAGES / "offscreen" / f"{case}-reference.png"
        ref_crop_path = IMAGES / "offscreen" / f"{case}-reference-crop.png"
        artifacts.extend([_save_png(ref_image, ref_path), _save_png(ref_crop, ref_crop_path)])
        contact = _contact_sheet(
            batch_images[(case, "white")].copy(QRect(*white_machine["crop_rect"])),
            ref_crop,
            ("Qt batch prototype plot crop", "Existing single-file plot crop"),
        )
        contact_path = CONTACTS / f"{case}-parity.png"
        artifacts.append(_save_png(contact, contact_path))
        case_evidence[case]["reference"] = ref_machine
        axis_range_pass = True
        if case == "time-dual-y":
            batch_ranges = white_machine["axis_ranges"]
            reference_ranges = ref_machine["axis_ranges"]
            x_equal = all(
                np.allclose(batch["x"], reference["x"], rtol=0.0, atol=1e-9)
                for batch, reference in zip(batch_ranges, reference_ranges)
            )
            y_equal = all(
                np.allclose(batch["y"], reference["y"], rtol=0.0, atol=1e-9)
                for batch, reference in zip(batch_ranges, reference_ranges)
            )
            axis_range_pass = bool(x_equal and y_equal)
            case_evidence[case]["axis_range_assertion"] = {
                "batch": batch_ranges,
                "reference": reference_ranges,
                "absolute_tolerance": 1e-9,
                "x_equal": bool(x_equal),
                "y_equal": bool(y_equal),
                "pass": axis_range_pass,
            }
        case_evidence[case]["parity_machine_pass"] = bool(
            ref_machine["viewport_matches"] and axis_range_pass
        )

    theme_sheet = _theme_sheet(batch_images)
    theme_path = CONTACTS / "all-cases-three-themes.png"
    artifacts.append(_save_png(theme_sheet, theme_path))

    titled, _crop, _machine = _render_batch("time-dual-y", "white", title=CJK_TEXT)
    blank, _crop, _machine = _render_batch("time-dual-y", "white", title="")
    title_header = titled.copy(QRect(0, 0, WIDTH, 155))
    blank_header = blank.copy(QRect(0, 0, WIDTH, 155))
    cjk_sheet = _contact_sheet(title_header, blank_header, ("CJK title", "Blank-title control"))
    cjk_path = CONTACTS / "cjk-ink-proof.png"
    artifacts.append(_save_png(cjk_sheet, cjk_path))
    title_arr = _qimage_array(title_header)
    blank_arr = _qimage_array(blank_header)
    cjk_pixels = int(np.count_nonzero(np.any(title_arr != blank_arr, axis=2)))
    cjk = _cjk_font_evidence()
    cjk.update({"ink_difference_pixels": cjk_pixels, "ink_pass": cjk_pixels >= 500})

    thread, dispatcher = _thread_contract(app)
    perf = _performance(app, dispatcher)
    dispatcher._mark_quitting()
    try:
        dispatcher.call(lambda: True)
    except RuntimeError as exc:
        thread["app_exit_fail_fast"] = "application is exiting" in str(exc)
        thread["app_exit_error"] = str(exc)
    else:
        thread["app_exit_fail_fast"] = False

    metadata_pass = all(
        artifact["width"] > 0
        and artifact["height"] > 0
        and abs(artifact["dpi_round_trip"] - DPI) < 0.1
        for artifact in artifacts
    )
    theme_pass = all(
        details["background_corner_matches"]
        for case in case_evidence.values()
        for details in case["themes"].values()
    )
    chrome_pass = all(
        all(all(check.values()) for check in details["chrome"])
        for case in case_evidence.values()
        for details in case["themes"].values()
    )
    parity_pass = all(case["parity_machine_pass"] for case in case_evidence.values())
    render_budget_pass = all(item["pass"] for item in perf["render_1080p"].values())
    machine_gate = {
        "pixel_and_metadata": metadata_pass,
        "themes": theme_pass,
        "chrome": chrome_pass,
        "cjk": bool(cjk["pass"] and cjk["ink_pass"]),
        "thread_marshal": all(
            thread[key]
            for key in (
                "modal_dialog_reachable", "gui_thread_execution",
                "exception_round_trip", "app_exit_fail_fast",
            )
        ),
        "viewport_parity": parity_pass,
        "render_p95": render_budget_pass,
        "heartbeat": perf["heartbeat"]["pass"],
    }
    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _git_sha(),
        "command_environment": {
            "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM"),
            "TMPDIR": os.environ.get("TMPDIR"),
            "MPLCONFIGDIR": os.environ.get("MPLCONFIGDIR"),
            "PYTHONPATH": os.environ.get("PYTHONPATH"),
        },
        "qt_platform": app.platformName(),
        "python": sys.version,
        "platform": platform.platform(),
        "versions": {
            "qt": QtCore.QT_VERSION_STR,
            "pyqt": QtCore.PYQT_VERSION_STR,
            "pyqtgraph": pg.__version__,
            "numpy": np.__version__,
        },
        "requested_batch_geometry": [WIDTH, HEIGHT],
        "cases": case_evidence,
        "cjk": cjk,
        "thread": thread,
        "performance": perf,
        "artifacts": artifacts,
        "contact_sheets": [
            str((CONTACTS / f"{case}-parity.png").relative_to(ROOT)) for case in cases
        ] + [
            str(theme_path.relative_to(ROOT)),
            str(cjk_path.relative_to(ROOT)),
        ],
        "machine_gate": machine_gate,
        "machine_gate_pass": all(machine_gate.values()),
        "gate0_pass": False,
        "visual_review": "PENDING: execution agent must open every contact sheet",
    }
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "evidence": str(EVIDENCE_PATH),
        "machine_gate": machine_gate,
        "machine_gate_pass": evidence["machine_gate_pass"],
        "performance": perf,
        "contact_sheets": evidence["contact_sheets"],
    }, ensure_ascii=False, indent=2))
    return 0 if evidence["machine_gate_pass"] else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("full", "cocoa", "hidpi"), default="full")
    args = parser.parse_args()
    pg.setConfigOptions(useOpenGL=False)
    app = QApplication.instance() or QApplication([])
    if args.mode in {"cocoa", "hidpi"}:
        return _platform_probe(app, args.mode)
    return _full(app)


if __name__ == "__main__":
    raise SystemExit(main())
