#!/usr/bin/env python3
"""Reproducible TimeDomainCanvas interaction benchmark.

Default input is a deterministic 6 x 1,188,000 shared-time synthetic fixture.
Use ``--hdf PATH`` for the release-candidate Cocoa/Windows packaged-equivalent
gate.  Timing is intentionally split into input callback, forced viewport
paint, and final settle; merging them would hide the source of a regression.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


COCOA_LIMITS_MS = {
    "initial_plot": 1300.0,
    "pan_frame_p95": 120.0,
    "pan_settle": 150.0,
    "resize_frame_p95": 300.0,
    "resize_settle": 250.0,
    "warm_checkbox_callback_p95": 30.0,
    "warm_checkbox_paint_p95": 220.0,
}


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hdf", type=Path)
    parser.add_argument("--channels", help="comma-separated HDF channel names")
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--samples", type=int, default=1_188_000)
    parser.add_argument("--width", type=int, default=1900)
    parser.add_argument("--height", type=int, default=1100)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--assert-standards", action="store_true")
    parser.add_argument("--baseline-json", type=Path)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def _stats(values):
    import numpy as np

    data = [float(value) for value in values]
    return {
        "n": len(data),
        "p50_ms": float(np.percentile(data, 50)) if data else None,
        "p95_ms": float(np.percentile(data, 95)) if data else None,
        "max_ms": max(data) if data else None,
        "samples_ms": data,
    }


def _synthetic_rows(row_count, sample_count):
    import numpy as np

    t = np.linspace(0.0, 49.5, sample_count, dtype=np.float64)
    colors = ("#1769e0", "#00a67d", "#ff2038", "#ff5a0a", "#8747ff", "#d41445")
    rows = []
    for idx in range(row_count):
        signal = (
            np.sin((idx + 1.0) * 2.0 * np.pi * t)
            + 0.25 * np.cos((17.0 + idx) * 2.0 * np.pi * t)
        )
        rows.append((
            f"physical-{idx}", True, t, signal, colors[idx % len(colors)],
            "g", "synthetic-shared-time",
        ))
    return rows, "synthetic"


def _hdf_rows(path, requested, row_count):
    from mf4_analyzer.io.loader import DataLoader

    groups = DataLoader.load_hdf(str(path))
    if not groups:
        raise RuntimeError(f"no HDF raster group found: {path}")
    group = max(groups, key=lambda item: len(item["data"]))
    frame = group["data"]
    time_name = next(
        (name for name in frame.columns if str(name).lower() == "time"), None,
    )
    if time_name is None:
        raise RuntimeError("HDF raster has no Time column")
    available = [name for name in frame.columns if name != time_name]
    names = requested or available[:row_count]
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise RuntimeError(f"HDF channels not found: {missing}")
    names = names[:row_count]
    t = frame[time_name].to_numpy(copy=False)
    colors = ("#1769e0", "#00a67d", "#ff2038", "#ff5a0a", "#8747ff", "#d41445")
    units = group.get("units", {})
    rows = [
        (
            str(name), True, t, frame[name].to_numpy(copy=False),
            colors[idx % len(colors)], units.get(name, ""), str(path.resolve()),
        )
        for idx, name in enumerate(names)
    ]
    return rows, str(path.resolve())


def _run(args):
    import numpy as np
    import pyqtgraph
    from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    app = QApplication.instance() or QApplication([])
    requested = (
        [part.strip() for part in args.channels.split(",") if part.strip()]
        if args.channels else None
    )
    if args.hdf:
        rows, source = _hdf_rows(args.hdf, requested, args.rows)
    else:
        rows, source = _synthetic_rows(args.rows, args.samples)
    if len(rows) < 2:
        raise RuntimeError("benchmark requires at least two rows")

    canvas = TimeDomainCanvasPG()
    canvas.resize(args.width, args.height)
    canvas.show()
    app.processEvents()
    viewport = canvas._glw.viewport()

    scan_count = 0
    original_scan = canvas._scan_finite_x_bounds

    def counted_scan(values):
        nonlocal scan_count
        scan_count += 1
        return original_scan(values)

    canvas._scan_finite_x_bounds = counted_scan
    context = ("timedomain-benchmark", source)
    started = time.perf_counter()
    canvas.plot_channels(
        rows, mode="subplot", render_context_key=context,
    )
    app.processEvents()
    viewport.repaint()
    initial_plot_ms = (time.perf_counter() - started) * 1000.0

    setdata_count = 0
    for _key, _name, (_axis, line) in canvas._channel_lines.composite_items():
        pdi = line.plot_data_item
        original_setdata = pdi.setData

        def counted_setdata(*pos, _original=original_setdata, **kwargs):
            nonlocal setdata_count
            setdata_count += 1
            return _original(*pos, **kwargs)

        pdi.setData = counted_setdata

    xlo, xhi = canvas._data_x_union()
    span = xhi - xlo
    window = span * 0.20
    starts = np.linspace(xlo + span * 0.04, xhi - window - span * 0.04, args.iterations)

    canvas._begin_view_interaction()
    pan_frames = []
    before_pan_setdata = setdata_count
    for lo in starts:
        started = time.perf_counter()
        canvas._primary_xaxis_ax.set_xlim(float(lo), float(lo + window))
        viewport.repaint()
        app.processEvents()
        pan_frames.append((time.perf_counter() - started) * 1000.0)
    held_pan_setdata = setdata_count - before_pan_setdata
    started = time.perf_counter()
    canvas._end_view_interaction()
    canvas._flush_pending_refresh()
    viewport.repaint()
    app.processEvents()
    pan_settle_ms = (time.perf_counter() - started) * 1000.0

    resize_frames = []
    widths = (0.94, 1.02, 0.96, 1.04, 0.95, 1.00)
    for idx in range(args.iterations):
        width = int(round(args.width * widths[idx % len(widths)]))
        height = args.height + (40 if idx % 2 else 0)
        started = time.perf_counter()
        canvas.resize(width, height)
        viewport.repaint()
        app.processEvents()
        resize_frames.append((time.perf_counter() - started) * 1000.0)
    started = time.perf_counter()
    canvas._on_resize_settled()
    viewport.repaint()
    app.processEvents()
    resize_settle_ms = (time.perf_counter() - started) * 1000.0

    checkbox_callbacks = []
    checkbox_paints = []
    full_rows = list(rows)
    short_rows = full_rows[:-1]
    for candidate in (short_rows, full_rows) * max(2, args.iterations // 2):
        started = time.perf_counter()
        result = canvas.try_apply_selection_delta(
            candidate, mode="subplot", render_context_key=context,
        )
        callback_ms = (time.perf_counter() - started) * 1000.0
        if not result.get("applied"):
            raise RuntimeError(f"warm checkbox delta fell back: {result}")
        checkbox_callbacks.append(callback_ms)
        started = time.perf_counter()
        viewport.repaint()
        app.processEvents()
        checkbox_paints.append((time.perf_counter() - started) * 1000.0)

    result = {
        "schema_version": 1,
        "environment": {
            "platform_plugin": app.platformName(),
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "qt": QT_VERSION_STR,
            "pyqt": PYQT_VERSION_STR,
            "pyqtgraph": pyqtgraph.__version__,
            "dpr": float(canvas._glw.devicePixelRatioF()),
        },
        "scenario": {
            "source": source,
            "rows": len(rows),
            "samples_per_row": [len(row[3]) for row in rows],
            "shared_time_arrays": len({id(row[2]) for row in rows}),
            "canvas": [args.width, args.height],
            "iterations": args.iterations,
        },
        "metrics": {
            "initial_plot_ms": initial_plot_ms,
            "pan_frames": _stats(pan_frames[2:]),
            "pan_settle_ms": pan_settle_ms,
            "resize_frames": _stats(resize_frames[2:]),
            "resize_settle_ms": resize_settle_ms,
            "warm_checkbox_callback": _stats(checkbox_callbacks[2:]),
            "warm_checkbox_paint": _stats(checkbox_paints[2:]),
        },
        "deterministic": {
            "raw_x_scan_count": scan_count,
            "held_pan_setdata_count": held_pan_setdata,
            "bound_plot_items": len(canvas._selection_bound_keys),
            "active_plot_items": len(canvas.axes_list),
            "last_selection_delta": canvas._last_selection_delta,
        },
    }
    canvas.close()
    return result


def _failures(result, baseline_path=None):
    metrics = result["metrics"]
    observed = {
        "initial_plot": metrics["initial_plot_ms"],
        "pan_frame_p95": metrics["pan_frames"]["p95_ms"],
        "pan_settle": metrics["pan_settle_ms"],
        "resize_frame_p95": metrics["resize_frames"]["p95_ms"],
        "resize_settle": metrics["resize_settle_ms"],
        "warm_checkbox_callback_p95": metrics["warm_checkbox_callback"]["p95_ms"],
        "warm_checkbox_paint_p95": metrics["warm_checkbox_paint"]["p95_ms"],
    }
    failures = [
        f"{name}: {observed[name]:.1f} > {limit:.1f} ms"
        for name, limit in COCOA_LIMITS_MS.items()
        if observed[name] > limit
    ]
    deterministic = result["deterministic"]
    expected_scans = result["scenario"]["shared_time_arrays"]
    if deterministic["raw_x_scan_count"] > expected_scans:
        failures.append(
            f"raw_x_scan_count: {deterministic['raw_x_scan_count']} > {expected_scans}"
        )
    if deterministic["held_pan_setdata_count"] != 0:
        failures.append(
            f"held_pan_setdata_count: {deterministic['held_pan_setdata_count']} != 0"
        )
    if baseline_path:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        old = baseline["metrics"]
        relative = {
            "initial_plot": old["initial_plot_ms"],
            "pan_frame_p95": old["pan_frames"]["p95_ms"],
            "pan_settle": old["pan_settle_ms"],
            "resize_frame_p95": old["resize_frames"]["p95_ms"],
            "resize_settle": old["resize_settle_ms"],
            "warm_checkbox_callback_p95": old["warm_checkbox_callback"]["p95_ms"],
            "warm_checkbox_paint_p95": old["warm_checkbox_paint"]["p95_ms"],
        }
        for name, previous in relative.items():
            if previous and observed[name] > previous * 1.20:
                failures.append(
                    f"{name}: {observed[name]:.1f} ms regressed >20% from {previous:.1f} ms"
                )
    return failures


def main():
    args = _arguments()
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    result = _run(args)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    if args.assert_standards:
        failures = _failures(result, args.baseline_json)
        if failures:
            print("PERFORMANCE GATE FAILED", file=sys.stderr)
            for failure in failures:
                print(f"- {failure}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
