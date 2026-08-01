"""Deterministic non-GUI render probe for a frozen TraceLab executable."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import warnings

import numpy as np
import pandas as pd

from .batch_render import (
    BatchRenderContext,
    BatchRenderOptions,
    BatchSeries,
    BatchTimeFigureSpec,
    _available_cjk_font_families,
    render_batch_image,
)


SMOKE_TITLE = "单帧振动加速度"
SMOKE_KINDS = ("time", "fft", "fft_time", "order_time")
SMOKE_FORMATS = ("png", "pdf", "svg")


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
        channel="加速度-$raw$",
        unit="$m/s^2$",
        method="frozen-smoke",
        task_id="batch-render-frozen-smoke",
    )
    outputs: list[dict[str, object]] = []
    caught_messages: list[str] = []
    error = ""
    try:
        payloads = _payloads()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
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
            caught_messages = [str(item.message) for item in caught]
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    glyph_warnings = [
        message
        for message in caught_messages
        if "glyph" in message.lower() or "missing from font" in message.lower()
    ]
    cjk_families = list(_available_cjk_font_families())
    ok = (
        not error
        and len(outputs) == len(SMOKE_KINDS) * len(SMOKE_FORMATS)
        and all(record["bytes"] > 0 for record in outputs)
        and not glyph_warnings
        and bool(cjk_families)
    )
    result: dict[str, object] = {
        "ok": ok,
        "title": SMOKE_TITLE,
        "outputs": outputs,
        "warnings": caught_messages,
        "glyph_warnings": glyph_warnings,
        "cjk_font_families": cjk_families,
    }
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
