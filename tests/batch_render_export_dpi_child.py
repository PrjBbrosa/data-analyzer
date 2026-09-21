"""Fresh-process Batch export geometry probe. QT_FONT_DPI is an experiment knob only."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PyQt5.QtCore import QCoreApplication, QSettings, QStandardPaths
from PyQt5.QtWidgets import QApplication, QWidget

from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_qt import (
    BatchRenderContext,
    BatchSeries,
    BatchTimeFigureSpec,
)
from mf4_analyzer.batch_render_qt._builder import (
    _axis_tick_text_records,
    build_batch_scene,
)
from mf4_analyzer.batch_render_qt._dispatch import ensure_app
from mf4_analyzer.batch_render_qt._theme import (
    export_chart_font,
    export_font_device_px,
    export_font_px,
)


CASES = (
    {
        "id": "smoke_640x360_fs1",
        "width": 640,
        "height": 360,
        "font_scale": 1.0,
        "layout": "overlay",
        "count": 1,
    },
    {
        "id": "export_1920x1080_fs1",
        "width": 1920,
        "height": 1080,
        "font_scale": 1.0,
        "layout": "overlay",
        "count": 2,
    },
    {
        "id": "export_1920x1080_fs15",
        "width": 1920,
        "height": 1080,
        "font_scale": 1.5,
        "layout": "overlay",
        "count": 2,
    },
    {
        "id": "subplot_1920x1080_fs1",
        "width": 1920,
        "height": 1080,
        "font_scale": 1.0,
        "layout": "subplot",
        "count": 4,
    },
)


def _isolate_qsettings() -> str:
    settings_dir = os.environ["TRACELAB_EXPORT_DPI_QSETTINGS"]
    os.makedirs(settings_dir, exist_ok=True)
    QStandardPaths.setTestModeEnabled(True)
    QCoreApplication.setOrganizationName("TraceLabTask3ExportDpi")
    QCoreApplication.setOrganizationDomain("task3.local")
    QCoreApplication.setApplicationName("ExportDpiMatrix")
    QSettings.setDefaultFormat(QSettings.IniFormat)
    for fmt in (QSettings.IniFormat, QSettings.NativeFormat):
        QSettings.setPath(fmt, QSettings.UserScope, settings_dir)
        QSettings.setPath(fmt, QSettings.SystemScope, settings_dir)
    return settings_dir


def _rect_tuple(rect) -> list[float]:
    return [
        round(float(rect.x()), 3),
        round(float(rect.y()), 3),
        round(float(rect.width()), 3),
        round(float(rect.height()), 3),
    ]


def _series(count: int, *, panels: bool) -> tuple[BatchSeries, ...]:
    x = np.linspace(0.0, 2.0, 401)
    items = []
    for index in range(count):
        y = (index + 1) * np.sin(2 * np.pi * (index + 1) * x)
        items.append(
            BatchSeries(
                x=x,
                y=y,
                label=f"curve-{index + 1}",
                unit="g",
                panel=index if panels else 0,
            )
        )
    return tuple(items)


def _same_axis_overlaps(records: list[tuple[object, str]]) -> list[list[str]]:
    overlaps = []
    for index, (rect_a, text_a) in enumerate(records):
        for rect_b, text_b in records[index + 1 :]:
            intersection = rect_a.intersected(rect_b)
            if intersection.width() > 0.5 and intersection.height() > 0.5:
                overlaps.append([text_a, text_b])
    return overlaps


def _collect_case(app: QApplication, spec: dict) -> dict:
    payload = (
        "time",
        BatchTimeFigureSpec(
            series=_series(spec["count"], panels=spec["layout"] == "subplot"),
            layout=spec["layout"],
            panel_titles=tuple(f"Channel {index + 1}" for index in range(spec["count"]))
            if spec["layout"] == "subplot"
            else (),
        ),
    )
    scene = build_batch_scene(
        payload,
        params={"font_scale": spec["font_scale"]},
        options=BatchRenderOptions(
            width_px=spec["width"],
            height_px=spec["height"],
            dpi=144,
        ),
        context=BatchRenderContext(
            source_display_name="单帧振动.mf4",
            channel='accel["front"]',
            method="time",
        ),
    )
    try:
        scene.show_and_settle()
        app.processEvents()
        plot = scene.plots[0]
        page = scene.widget.ci.sceneBoundingRect()
        ticks = []
        tick_texts = []
        same_axis_overlaps = []
        overflow = []
        for plot_index, plot_item in enumerate(scene.plots):
            panel = plot_item.sceneBoundingRect()
            for side in ("left", "bottom"):
                records = _axis_tick_text_records(plot_item.getAxis(side))
                same_axis_overlaps.extend(_same_axis_overlaps(records))
                for rect, text in records:
                    ticks.append(
                        {
                            "side": side,
                            "text": text,
                            "rect": _rect_tuple(rect),
                            "panel": plot_index,
                        }
                    )
                    tick_texts.append(f"{plot_index}:{side}:{text}")
                    if not page.contains(rect.center()):
                        overflow.append(text)
                    if not panel.adjusted(-2.0, -2.0, 2.0, 2.0).intersects(rect):
                        overflow.append(f"panel:{text}")
        header = scene.page_labels[0].sceneBoundingRect() if scene.page_labels else page
        tick_font = plot.getAxis("bottom").style.get("tickFont")
        adjacent = [
            [index_a, index_b, text_a, text_b]
            for index_a, index_b, text_a, text_b in scene.adjacent_text_overlaps()
        ]
        return {
            "plot_vb": _rect_tuple(plot.vb.sceneBoundingRect()),
            "header": _rect_tuple(header),
            "ticks": ticks,
            "tick_texts": tick_texts,
            "axis_font_px": (
                round(export_font_device_px(tick_font), 3)
                if tick_font is not None
                else -1
            ),
            "same_axis_tick_overlaps": same_axis_overlaps,
            "adjacent_overlaps": adjacent,
            "overflow": overflow,
        }
    finally:
        scene.close()


def main() -> int:
    settings_dir = _isolate_qsettings()
    requested = int(os.environ.get("QT_FONT_DPI", "0") or "0")
    app = ensure_app()
    probe = QWidget()
    probe.resize(40, 20)
    probe.show()
    app.processEvents()
    logical_dpi = int(probe.logicalDpiX())
    adopted = requested == 0 or abs(logical_dpi - requested) <= 1
    font = export_chart_font(12.0)
    cases = {spec["id"]: _collect_case(app, spec) for spec in CASES}
    payload = {
        "requested_dpi": requested,
        "adopted": adopted,
        "platformName": app.platformName(),
        "logicalDpiX": logical_dpi,
        "axis_font_px": round(export_font_device_px(font), 3),
        "theme_12pt_px": export_font_px(12.0),
        "qsettings_dir": settings_dir,
        "cases": cases,
    }
    print(json.dumps(payload, ensure_ascii=False))
    probe.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
