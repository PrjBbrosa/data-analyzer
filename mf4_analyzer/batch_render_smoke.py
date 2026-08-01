"""Deterministic non-GUI render probe for a frozen TraceLab executable."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .batch_render import (
    BatchRenderContext,
    BatchRenderOptions,
    BatchSeries,
    BatchTimeFigureSpec,
    render_batch_image,
)
from .batch_render_qt._dispatch import ensure_app
from .batch_render_qt._fonts import header_ink_proof, resolve_cjk_font


SMOKE_TITLE = "单帧振动加速度"
SMOKE_KINDS = ("time", "fft", "fft_time", "order_time")
SMOKE_FORMATS = ("png",)


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
    outputs: list[dict[str, object]] = []
    error = ""
    environment_gate = ""
    qt_qpa_platform = str(os.environ.get("QT_QPA_PLATFORM") or "")
    qt_platform_name = ""
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
        payloads = _payloads()
        for kind in SMOKE_KINDS:
            for image_format in SMOKE_FORMATS:
                target = output_directory / f"{kind}.{image_format}"
                if target.exists():
                    target.unlink()
                render_batch_image(
                    (kind, payloads[kind]),
                    target,
                    params={
                        "amplitude_mode": "amplitude",
                        "z_auto": False,
                        "z_floor": 0.0,
                        "z_ceiling": 1.0,
                    },
                    options=BatchRenderOptions(
                        width_px=640,
                        height_px=360,
                        dpi=72,
                        format=image_format,
                    ),
                    context=context,
                )
                outputs.append({"path": str(target), "bytes": target.stat().st_size})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    ok = (
        not error
        and len(outputs) == len(SMOKE_KINDS) * len(SMOKE_FORMATS)
        and all(record["bytes"] > 0 for record in outputs)
        and bool(qt_qpa_platform)
        and bool(qt_platform_name)
        and cjk_proof.get("supports") is True
        and cjk_proof.get("pass") is True
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
