"""Deterministic non-GUI render probe for a frozen TraceLab executable.

Colormap *prop* constants (``cmap="turbo"``) may be pinned by this smoke so
endpoint hunting stays unambiguous; RGB expectations live in the verifier and
must be read back from the product runtime — see
``docs/analyzer/specs/2026-08-12-guideline-hardening-spec.md`` §3.3.
A second heatmap pass omits ``cmap`` so the shipping-default local LUT
(``DEFAULT_HEATMAP_CMAP`` / gnuplot2) is exercised in the frozen package.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from PyQt5.QtCore import QPoint, QRectF

from .batch_render import (
    BatchRenderContext,
    BatchRenderOptions,
    BatchSeries,
    BatchTimeFigureSpec,
    render_batch_image,
)
from .batch_render_qt._builder import (
    _axis_tick_text_records,
    _text_of,
    build_batch_scene,
)
from .batch_render_qt._dispatch import ensure_app, render_on_gui_thread
from .batch_render_qt._fonts import header_ink_proof, resolve_cjk_font
from .batch_render_qt._theme import (
    EXPORT_FONT_DPI,
    export_chart_font,
    export_font_device_px,
    logical_export_dpi,
)
from .qt_chart_fonts import ASCII_CONTRACT_TEXT


SMOKE_TITLE = "单帧振动加速度"
SMOKE_KINDS = ("time", "fft", "fft_time", "order_time")
SMOKE_DEFAULT_CMAP_KINDS = ("fft_time", "order_time")
SMOKE_FORMATS = ("png",)
SMOKE_ARTIFACT_COUNT = (
    len(SMOKE_KINDS) * len(SMOKE_FORMATS)
    + len(SMOKE_DEFAULT_CMAP_KINDS) * len(SMOKE_FORMATS)
)
SMOKE_LAYOUT_KIND = "time"
SMOKE_LAYOUT_ARTIFACT = "time.png"


def _payloads() -> dict[str, object]:
    time = BatchTimeFigureSpec(
        series=(
            BatchSeries(
                x=np.asarray([0.0, 1.0]),
                y=np.asarray([0.0, 1.0]),
                label="raw",
            ),
            BatchSeries(
                x=np.asarray([0.0, 1.0]),
                y=np.asarray([0.25, 0.75]),
                label="filtered",
                linestyle="--",
            ),
        ),
    )
    fft = pd.DataFrame(
        {"frequency_hz": [0.0, 100.0, 200.0], "amplitude": [0.0, 1.0, 0.25]}
    )
    turbo_matrix = np.asarray([[0.0, 1.0], [0.0, 1.0]], dtype=float)
    return {
        "time": time,
        "fft": fft,
        "fft_time": SimpleNamespace(
            x=np.asarray([0.0, 1.0]),
            y=np.asarray([10.0, 20.0]),
            matrix=turbo_matrix,
            x_name="time_s",
            y_name="frequency_hz",
        ),
        "order_time": SimpleNamespace(
            x=np.asarray([0.0, 1.0]),
            y=np.asarray([1.0, 2.0]),
            matrix=turbo_matrix,
            x_name="time_s",
            y_name="order",
        ),
    }


def _rect_tuple(rect) -> list[float]:
    return [
        round(float(rect.x()), 3),
        round(float(rect.y()), 3),
        round(float(rect.width()), 3),
        round(float(rect.height()), 3),
    ]


def _png_rect(scene, scene_rect: QRectF) -> list[int]:
    mapped = scene.widget.mapFromScene(scene_rect).boundingRect()
    origin = scene.widget.viewport().mapTo(scene.widget, QPoint(0, 0))
    mapped.translate(origin)
    clipped = mapped.intersected(scene.widget.rect())
    return [int(clipped.x()), int(clipped.y()), int(clipped.width()), int(clipped.height())]


def _same_axis_overlaps(records: list[tuple[object, str]]) -> list[list[str]]:
    overlaps = []
    for index, (rect_a, text_a) in enumerate(records):
        for rect_b, text_b in records[index + 1 :]:
            intersection = rect_a.intersected(rect_b)
            if intersection.width() > 0.5 and intersection.height() > 0.5:
                overlaps.append([text_a, text_b])
    return overlaps


def _legend_text(legend) -> str:
    if legend is None:
        return ""
    parts: list[str] = []
    for item in getattr(legend, "items", []) or []:
        label = item[1] if isinstance(item, (tuple, list)) and len(item) >= 2 else item
        text = _text_of(label).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def collect_time_layout_page(
    payload,
    *,
    options: BatchRenderOptions,
    context: BatchRenderContext,
) -> dict[str, object]:
    """Reuse renderer tick/header geometry; PNG pixel checks live in the verifier."""

    def _collect() -> dict[str, object]:
        scene = build_batch_scene(
            payload, params={}, options=options, context=context,
        )
        try:
            scene.show_and_settle()
            app = ensure_app()
            app.processEvents()
            page_scene = scene.widget.ci.sceneBoundingRect()
            title_item = scene.page_labels[0] if scene.page_labels else None
            if title_item is None:
                raise RuntimeError("batch smoke page has no title label")
            title_scene = title_item.sceneBoundingRect()
            if scene.legend is None:
                raise RuntimeError("batch smoke time page has no legend")
            legend_scene = scene.legend.sceneBoundingRect()
            ticks: list[dict[str, object]] = []
            same_axis_overlaps: list[list[str]] = []
            overflow: list[str] = []
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
                                "rect": _png_rect(scene, rect),
                                "panel": plot_index,
                            }
                        )
                        if not page_scene.contains(rect.center()):
                            overflow.append(text)
                        if not panel.adjusted(-2.0, -2.0, 2.0, 2.0).intersects(rect):
                            overflow.append(f"panel:{text}")
            adjacent = [
                [index_a, index_b, text_a, text_b]
                for index_a, index_b, text_a, text_b in scene.adjacent_text_overlaps()
            ]
            dpr = float(scene.widget.devicePixelRatioF())
            return {
                "kind": SMOKE_LAYOUT_KIND,
                "artifact": SMOKE_LAYOUT_ARTIFACT,
                "title": {
                    "text": _text_of(title_item),
                    "rect": _png_rect(scene, title_scene),
                },
                "legend": {
                    "text": _legend_text(scene.legend),
                    "rect": _png_rect(scene, legend_scene),
                },
                "ticks": ticks,
                "same_axis_tick_overlaps": same_axis_overlaps,
                "adjacent_overlaps": adjacent,
                "overflow": overflow,
                "device_pixel_ratio": dpr,
            }
        finally:
            scene.close()

    return render_on_gui_thread(_collect)


def layout_page_is_readable(page: dict[str, object] | None) -> bool:
    if not isinstance(page, dict):
        return False
    title = page.get("title") or {}
    legend = page.get("legend") or {}
    ticks = page.get("ticks") or []
    title_rect = title.get("rect") if isinstance(title, dict) else None
    legend_rect = legend.get("rect") if isinstance(legend, dict) else None
    if not isinstance(title_rect, list) or len(title_rect) != 4:
        return False
    if not isinstance(legend_rect, list) or len(legend_rect) != 4:
        return False
    if int(title_rect[2]) < 1 or int(title_rect[3]) < 1:
        return False
    if int(legend_rect[2]) < 1 or int(legend_rect[3]) < 1:
        return False
    if not isinstance(ticks, list) or len(ticks) < 2:
        return False
    if page.get("same_axis_tick_overlaps"):
        return False
    if page.get("adjacent_overlaps"):
        return False
    if page.get("overflow"):
        return False
    return True


def _smoke_options() -> BatchRenderOptions:
    return BatchRenderOptions(
        width_px=640,
        height_px=360,
        dpi=72,
        format="png",
    )


def run(output_directory: Path, result_json: Path) -> int:
    """Render the complete matrix and carry probe truth through JSON/exit code."""
    output_directory = Path(output_directory)
    result_json = Path(result_json)
    output_directory.mkdir(parents=True, exist_ok=True)
    result_json.parent.mkdir(parents=True, exist_ok=True)
    context = BatchRenderContext(
        source_display_name=SMOKE_TITLE,
        channel="加速度",
        unit="m/s²",
        method="frozen-smoke",
        task_id="batch-render-frozen-smoke",
    )
    options = _smoke_options()
    outputs: list[dict[str, object]] = []
    error = ""
    environment_gate = ""
    qt_qpa_platform = str(os.environ.get("QT_QPA_PLATFORM") or "")
    qt_platform_name = ""
    layout_diagnostics: dict[str, object] = {}
    cjk_proof: dict[str, object] = {
        "font": "",
        "supports": False,
        "ink_pixels": 0,
        "empty_ink_pixels": 0,
        "pass": False,
    }
    try:
        app = ensure_app()
        qt_qpa_platform = str(os.environ.get("QT_QPA_PLATFORM") or "")
        qt_platform_name = str(app.platformName() or "")
        cjk_font = resolve_cjk_font()
        if cjk_font is None:
            environment_gate = (
                "CJK font coverage unavailable for 单帧振动加速度"
            )
        else:
            cjk_proof = header_ink_proof(cjk_font, SMOKE_TITLE)
            ascii_proof = header_ink_proof(cjk_font, ASCII_CONTRACT_TEXT)
            cjk_proof = {
                **cjk_proof,
                "ascii_pass": ascii_proof.get("pass"),
                "ascii_ink_pixels": ascii_proof.get("ink_pixels"),
            }
            if cjk_proof.get("pass") is not True or ascii_proof.get("pass") is not True:
                environment_gate = (
                    "CJK font produced no drawable ink for 单帧振动加速度"
                )
        if not environment_gate:
            payloads = _payloads()
            base_params = {
                "amplitude_mode": "amplitude",
                "z_auto": False,
                "z_floor": 0.0,
                "z_ceiling": 1.0,
            }
            for kind in SMOKE_KINDS:
                for image_format in SMOKE_FORMATS:
                    target = output_directory / f"{kind}.{image_format}"
                    if target.exists():
                        target.unlink()
                    render_batch_image(
                        (kind, payloads[kind]),
                        target,
                        params={
                            **base_params,
                            # 显式点名色图，不吃产品默认值。turbo 端点色在 verify
                            # 侧运行时从 pg.colormap.get("turbo") 回读；钉死道具常量
                            # 是对的，RGB 期望禁止字面量重声明（spec §3.3 / C2）。
                            "cmap": "turbo",
                        },
                        options=options,
                        context=context,
                    )
                    outputs.append({"path": str(target), "bytes": target.stat().st_size})
            # Shipping-default local LUT path (gnuplot2). Omit cmap so the frozen
            # package actually resolves DEFAULT_HEATMAP_CMAP rather than a prop pin.
            for kind in SMOKE_DEFAULT_CMAP_KINDS:
                for image_format in SMOKE_FORMATS:
                    target = output_directory / f"{kind}_default_cmap.{image_format}"
                    if target.exists():
                        target.unlink()
                    render_batch_image(
                        (kind, payloads[kind]),
                        target,
                        params=dict(base_params),
                        options=options,
                        context=context,
                    )
                    outputs.append({"path": str(target), "bytes": target.stat().st_size})
            axis_font = export_chart_font(12.0)
            screen = app.primaryScreen()
            dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
            page = collect_time_layout_page(
                (SMOKE_LAYOUT_KIND, payloads[SMOKE_LAYOUT_KIND]),
                options=options,
                context=context,
            )
            layout_diagnostics = {
                "export_font_dpi": EXPORT_FONT_DPI,
                "logical_dpi_x": logical_export_dpi(),
                "device_pixel_ratio": page.get("device_pixel_ratio", dpr),
                "axis_font_device_px": export_font_device_px(axis_font),
                "cjk_font": str(cjk_proof.get("font") or ""),
                "page": page,
            }
            if not layout_page_is_readable(page):
                environment_gate = (
                    "final page layout is unreadable: overlapping ticks, "
                    "missing title/legend, or overflowing labels"
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    ok = (
        not error
        and not environment_gate
        and len(outputs) == SMOKE_ARTIFACT_COUNT
        and all(record["bytes"] > 0 for record in outputs)
        and bool(qt_qpa_platform)
        and bool(qt_platform_name)
        and cjk_proof.get("supports") is True
        and cjk_proof.get("pass") is True
        and layout_page_is_readable(layout_diagnostics.get("page"))
    )
    result: dict[str, object] = {
        "ok": ok,
        "title": SMOKE_TITLE,
        "outputs": outputs,
        "artifact_count": len(outputs),
        "qt_qpa_platform": qt_qpa_platform,
        "qt_platform_name": qt_platform_name,
        "cjk_proof": cjk_proof,
        "cjk_font_families": (
            [str(cjk_proof.get("font"))] if cjk_proof.get("font") else []
        ),
        "layout_diagnostics": layout_diagnostics,
    }
    if environment_gate:
        result["environment_gate"] = environment_gate
    if error:
        result["error"] = error
    result_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-render-runtime-smoke", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    return run(args.output_dir, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
