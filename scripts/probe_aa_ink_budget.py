#!/usr/bin/env python3
"""AA ink-budget probe: real-machine timing for the time-domain "ink" fix.

Consolidates the four investigation scripts behind
``docs/analyzer/specs/2026-08-08-timedomain-aa-ink-budget-spec.md`` into one
argparse-driven tool. Each subcommand reproduces one table from the spec
(see spec §1.1 / §1.3 / §3.2) so the baseline can be re-run and diffed as
the implementation lands.

Canonical synthetic signal (matches the spec header): 1,000,000 samples at
20 kHz (``FS * DURATION`` below), primary channel
``100*sin(2*pi*2300*t) + 8*sin(2*pi*0.7*t)`` (amplitude ~=108, i.e. the
"reported" oscillating case). Multi-channel cases increment frequency per
row (``2300 + 137*i`` Hz / ``0.7 + 0.1*i`` Hz), same convention as the
investigation scripts. Canvas is always 1600x950 in subplot mode.

IMPORTANT — real machine only: ``--sweep-y``, ``--sweep-buckets`` and
``--aa-frame`` measure Cocoa paint/repaint wall-clock time. Numbers from
``QT_QPA_PLATFORM=offscreen`` are NOT valid performance evidence (see
CLAUDE.md Gotchas: "验真机渲染") — do not set that env var when running
those three subcommands. ``--raster-build`` is the one exception: it only
builds a QImage off the GPU/window-server path, so it forces
``QT_QPA_PLATFORM=offscreen`` itself and its numbers are valid headless.

Usage:
    .venv/bin/python scripts/probe_aa_ink_budget.py sweep-y --json-out out.json
    .venv/bin/python scripts/probe_aa_ink_budget.py sweep-buckets --json-out out.json
    .venv/bin/python scripts/probe_aa_ink_budget.py aa-frame --json-out out.json
    .venv/bin/python scripts/probe_aa_ink_budget.py raster-build --json-out out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


WIDTH, HEIGHT = 1600, 950
FS = 20_000.0
DURATION = 50.0  # FS * DURATION == 1,000,000 samples, matches the spec header.
COLORS = ("#1769e0", "#00a67d", "#ff2038", "#ff5a0a", "#8747ff", "#d41445")


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------

def _time_base():
    import numpy as np

    n = int(FS * DURATION)
    return np.arange(n, dtype=np.float64) / FS


def make_rows(n_rows, *, kind="oscillating", tag="probe"):
    """Synthetic per-channel rows.

    kind="oscillating": the reported full-scale case,
        100*sin(2*pi*(2300+137*i)*t) + 8*sin(2*pi*(0.7+0.1*i)*t).
    kind="smooth": benign control, a few Hz (many px/cycle),
        100*sin(2*pi*(1+i)*t).
    """
    import numpy as np

    t = _time_base()
    rows = []
    for i in range(n_rows):
        if kind == "smooth":
            sig = 100.0 * np.sin(2.0 * np.pi * (1.0 + i) * t)
        elif kind == "oscillating":
            sig = 100.0 * np.sin(2.0 * np.pi * (2300.0 + 137.0 * i) * t)
            sig += 8.0 * np.sin(2.0 * np.pi * (0.7 + 0.1 * i) * t)
        else:
            raise ValueError(kind)
        rows.append((
            f"Motor Torque {i}", True, t, sig, COLORS[i % len(COLORS)], "Nm", tag,
        ))
    return rows


def _qapp():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _new_canvas(app):
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(WIDTH, HEIGHT)
    canvas.show()
    app.processEvents()
    viewport = canvas._glw.viewport()
    return canvas, viewport


def _plot(app, canvas, viewport, rows, label):
    canvas.plot_channels(rows, mode="subplot", render_context_key=("probe", label))
    app.processEvents()
    viewport.repaint()


def _build_canvas(app, rows, *, label):
    canvas, viewport = _new_canvas(app)
    _plot(app, canvas, viewport, rows, label)
    return canvas, viewport


def _environment(app, canvas=None):
    info = {"platform_plugin": app.platformName()}
    if canvas is not None:
        info["dpr"] = float(canvas._glw.devicePixelRatioF())
    return info


def _percentiles(values):
    import numpy as np

    arr = np.asarray(values, dtype=float)
    return float(np.percentile(arr, 50)), float(np.percentile(arr, 95))


def _timed_repaint(canvas, viewport, *, retries=1, floor_ms=1.0):
    """Time one forced, non-coalesced repaint.

    Explicitly marks the whole scene dirty (``scene().update()``) before
    every attempt, then repaints and times it. A bare ``viewport.update()``
    has been observed to intermittently coalesce into a no-op right after
    show()/close() churn between cases (one case in a run measuring near
    0 ms while the identical code path is normal immediately before and
    after it) — that is not real paint cost, just a missed repaint. If the
    timed value is still under ``floor_ms`` after ``retries`` extra
    attempts, the caller should record the frame as suspect rather than
    trust the number.
    """
    elapsed_ms = None
    for _ in range(retries + 1):
        started = time.perf_counter()
        canvas._glw.scene().update()
        viewport.repaint()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms >= floor_ms:
            break
    return elapsed_ms, elapsed_ms < floor_ms


def _filter_cases(cases, spec):
    """Keep only cases whose label contains one of the comma-separated
    (case-insensitive) substrings in ``spec``; ``spec`` falsy means keep all.
    """
    if not spec:
        return list(cases)
    needles = [part.strip().lower() for part in spec.split(",") if part.strip()]
    if not needles:
        return list(cases)
    return [c for c in cases if any(n in c[2].lower() for n in needles)]


# --------------------------------------------------------------------------
# --sweep-y : fine Y-window ratio sweep (spec §1.1)
# --------------------------------------------------------------------------

def cmd_sweep_y(_args):
    import numpy as np

    app = _qapp()
    rows = make_rows(1, kind="oscillating", tag="sweep-y")
    sig = rows[0][3]
    data_span = float(sig.max() - sig.min())
    canvas, viewport = _build_canvas(app, rows, label="sweep-y")
    env = _environment(app, canvas)

    ck, _name, (axis, line) = next(iter(canvas._channel_lines.composite_items()))
    xlo, xhi = canvas._data_x_union()
    span = xhi - xlo
    window = span * 0.20

    print(f"platform={app.platformName()} dpr={canvas._glw.devicePixelRatioF()} "
          f"data_span={data_span:.1f}", flush=True)
    print(f"{'y_half':>8} {'ratio':>7} {'pts':>6} {'wall':>5} "
          f"{'pan_p50_ms':>11} {'pan_p95_ms':>11}", flush=True)

    y_halves = (2000, 800, 400, 250, 160, 130, 115, 108, 104, 95, 85, 75,
                65, 55, 45, 35, 27, 20, 11)
    rows_out = []
    for y_half in y_halves:
        axis.set_ylim(-float(y_half), float(y_half))
        canvas._last_range_key.clear()
        canvas._flush_pending_refresh()
        app.processEvents()
        viewport.repaint()
        xd, _ = line.plot_data_item.getData()
        pts = 0 if xd is None else len(xd)
        wall = bool(getattr(canvas, "_y_overflow_wall_active", False))

        canvas._begin_view_interaction()
        pan = []
        starts = np.linspace(xlo + span * 0.04, xhi - window - span * 0.04, 8)
        for lo in starts:
            started = time.perf_counter()
            canvas._primary_xaxis_ax.set_xlim(float(lo), float(lo + window))
            viewport.repaint()
            app.processEvents()
            pan.append((time.perf_counter() - started) * 1000.0)
        canvas._end_view_interaction()
        canvas._flush_pending_refresh()
        app.processEvents()

        pan_p50, pan_p95 = _percentiles(pan[2:])
        ratio = data_span / (2.0 * y_half)
        rows_out.append({
            "y_half": y_half, "ratio": ratio, "pts": pts, "wall": wall,
            "pan_p50_ms": pan_p50, "pan_p95_ms": pan_p95,
        })
        print(f"{y_half:>8} {ratio:>7.2f} {pts:>6} {'Y' if wall else 'n':>5} "
              f"{pan_p50:>11.1f} {pan_p95:>11.1f}", flush=True)

    canvas.close()
    app.processEvents()
    return {
        "command": "sweep-y", "environment": env, "data_span": data_span,
        "rows": rows_out,
    }


# --------------------------------------------------------------------------
# --sweep-buckets : envelope bucket-cap sweep at Y fit (spec §3.2, §4.1)
# --------------------------------------------------------------------------

def _run_bucket_case(app, *, n_rows, y_half, bucket_cap, label, iterations=8):
    import numpy as np

    canvas, viewport = _new_canvas(app)
    if bucket_cap is not None:
        original = canvas._renderer._effective_pixel_width

        def capped(pixel_width, *, source_len=None, dense_count=None,
                   _original=original, _cap=bucket_cap):
            width = _original(pixel_width, source_len=source_len,
                               dense_count=dense_count)
            return max(1, min(int(width), int(_cap)))

        canvas._renderer._effective_pixel_width = capped
        canvas._effective_pixel_width = capped

    _plot(app, canvas, viewport,
          make_rows(n_rows, kind="oscillating", tag="sweep-buckets"), label)

    for _ck, _name, (axis, _line) in canvas._channel_lines.composite_items():
        axis.set_ylim(-y_half, y_half)
    canvas._flush_pending_refresh()
    app.processEvents()
    viewport.repaint()

    pts = 0
    for _ck, _name, (_axis, line) in canvas._channel_lines.composite_items():
        xd, _ = line.plot_data_item.getData()
        pts += 0 if xd is None else len(xd)
    wall = bool(getattr(canvas, "_y_overflow_wall_active", False))
    aa_allowed = canvas._quality._idle_aa_density_ok()

    xlo, xhi = canvas._data_x_union()
    span = xhi - xlo
    window = span * 0.20
    starts = np.linspace(xlo + span * 0.04, xhi - window - span * 0.04, iterations)
    canvas._begin_view_interaction()
    pan = []
    for lo in starts:
        started = time.perf_counter()
        canvas._primary_xaxis_ax.set_xlim(float(lo), float(lo + window))
        viewport.repaint()
        app.processEvents()
        pan.append((time.perf_counter() - started) * 1000.0)
    canvas._end_view_interaction()
    canvas._flush_pending_refresh()
    app.processEvents()

    canvas.close()
    app.processEvents()

    pan_p50, pan_p95 = _percentiles(pan[2:])
    ratio = 200.0 / (2.0 * y_half)
    result = {
        "label": label, "bucket_cap": bucket_cap, "ratio": ratio, "pts": pts,
        "wall": wall, "aa_ok": aa_allowed, "pan_p50_ms": pan_p50,
        "pan_p95_ms": pan_p95,
    }
    print(
        f"{label:<34} ratio={ratio:6.2f} pts={pts:6d} "
        f"wall={'Y' if wall else 'n'} aa_ok={'Y' if aa_allowed else 'n'} "
        f"pan p50={pan_p50:7.1f} p95={pan_p95:7.1f}ms", flush=True,
    )
    return result


def cmd_sweep_buckets(_args):
    app = _qapp()
    probe_canvas, _vp = _new_canvas(app)
    env = _environment(app, probe_canvas)
    probe_canvas.close()
    app.processEvents()

    print(f"platform={app.platformName()}", flush=True)
    print("== bucket-cap sweep at Y=+-105 (Y fit, ratio~1.0) ==", flush=True)

    caps = (1550, 1200, 800, 500, 350)
    cases_out = [
        _run_bucket_case(app, n_rows=1, y_half=105.0, bucket_cap=cap,
                          label=f"1ch  Y=+-105 buckets<={cap}")
        for cap in caps
    ]
    return {"command": "sweep-buckets", "environment": env, "cases": cases_out}


# --------------------------------------------------------------------------
# --aa-frame : bounded single-frame vector-AA timing (spec §1.2/§1.3)
# --------------------------------------------------------------------------

def _run_aa_frame_case(app, kind, n_rows, label):
    import numpy as np

    canvas, viewport = _build_canvas(
        app, make_rows(n_rows, kind=kind, tag="aa-frame"), label=label,
    )
    canvas.fit_y_to_visible_x()  # production Y auto-fit
    app.processEvents()
    viewport.repaint()
    _ck, _n, (axis, line) = next(iter(canvas._channel_lines.composite_items()))
    ylim = tuple(round(v, 1) for v in axis.get_ylim())
    xd, _ = line.plot_data_item.getData()
    pts_one = 0 if xd is None else len(xd)

    # AA-off frame (what you get while dragging).
    off = []
    off_suspect = False
    for _ in range(4):
        ms, suspect = _timed_repaint(canvas, viewport)
        off.append(ms)
        off_suspect = off_suspect or suspect
    aa_off_ms = float(np.median(off[1:]))

    allowed = canvas._quality._idle_aa_density_ok()
    enable_started = time.perf_counter()
    canvas._quality.try_enable_idle_quality()  # the 150 ms idle upgrade
    enable_ms = (time.perf_counter() - enable_started) * 1000.0
    first_repaint_ms, first_suspect = _timed_repaint(canvas, viewport)
    app.processEvents()
    first_aa_ms = enable_ms + first_repaint_ms
    aa_on = bool(canvas._quality.aa_on)

    second_aa_ms, cached_suspect = _timed_repaint(canvas, viewport)
    app.processEvents()

    canvas.close()
    app.processEvents()

    suspect = {
        "aa_off": off_suspect, "first_aa": first_suspect,
        "cached_aa": cached_suspect,
    }
    result = {
        "label": label, "ylim": list(ylim), "pts_per_row": pts_one,
        "aa_gate": "allow" if allowed else "block", "aa_on": aa_on,
        "aa_off_frame_ms": aa_off_ms, "first_aa_frame_ms": first_aa_ms,
        "cached_aa_frame_ms": second_aa_ms, "suspect": suspect,
    }
    suspect_txt = "  SUSPECT=" + ",".join(k for k, v in suspect.items() if v) \
        if any(suspect.values()) else ""
    print(f"{label:<26} ylim={str(ylim):<18} pts/row={pts_one:<5} "
          f"aa_gate={result['aa_gate']} aa_on={aa_on}  "
          f"aa_off_frame={aa_off_ms:8.1f}ms  first_aa_frame={first_aa_ms:9.1f}ms  "
          f"cached_aa_frame={second_aa_ms:8.1f}ms{suspect_txt}", flush=True)
    return result


def cmd_aa_frame(args):
    app = _qapp()
    probe_canvas, _vp = _new_canvas(app)
    env = _environment(app, probe_canvas)
    probe_canvas.close()
    app.processEvents()

    print(f"platform={app.platformName()}", flush=True)
    cases = (
        ("smooth", 1, "1ch smooth (control)"),
        ("oscillating", 1, "1ch oscillating"),
        ("oscillating", 6, "6ch oscillating"),
    )
    cases = _filter_cases(cases, getattr(args, "cases", None))
    cases_out = [_run_aa_frame_case(app, kind, n_rows, label)
                 for kind, n_rows, label in cases]
    return {"command": "aa-frame", "environment": env, "cases": cases_out}


# --------------------------------------------------------------------------
# --raster-build : dense_raster non-AA build cost + ink_travel (spec §3.2/§4.3)
# --------------------------------------------------------------------------

def cmd_raster_build(_args):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import numpy as np

    from mf4_analyzer.signal._envelope_cutils import positions_envelope
    from mf4_analyzer.ui.pg_canvas.dense_raster import build_dense_raster_image

    app = _qapp()
    t = _time_base()
    sig = 100.0 * np.sin(2.0 * np.pi * 2300.0 * t) + 8.0 * np.sin(2.0 * np.pi * 0.7 * t)

    cases_out = []
    for label, pw, logical in (
        ("1ch full row  (1550x800)", 1550, (1550, 800)),
        ("6ch row       (1550x120)", 1550, (1550, 120)),
        ("wall-capped   (1800x800)", 1800, (1550, 800)),
    ):
        env_t, env_s = positions_envelope(
            t, sig, xlim=(float(t[0]), float(t[-1])), pixel_width=pw,
            is_monotonic=True,
        )
        # vertical travel (the proposed ink metric), in row pixels
        y_span = 2 * 118.8
        dy = np.abs(np.diff(env_s))
        travel_px = float(np.minimum(dy, y_span).sum() / y_span * logical[1])
        times = []
        image = None
        for _ in range(3):
            started = time.perf_counter()
            image = build_dense_raster_image(
                env_t, env_s,
                data_rect=(float(t[0]), float(t[-1]), -118.8, 118.8),
                logical_size=logical, dpr=2.0, color="#1769e0",
                line_width=1.5,
            )
            times.append((time.perf_counter() - started) * 1000.0)
        assert image is not None
        mb = image.sizeInBytes() / (1024 * 1024)
        build_med_ms = float(np.median(times))
        cases_out.append({
            "label": label, "pts": len(env_s), "ink_travel_px": travel_px,
            "build_med_ms": build_med_ms, "image_mib": mb,
        })
        print(f"{label}  pts={len(env_s):5d}  ink_travel={travel_px/1000:8.1f}k px"
              f"  build_med={build_med_ms:7.1f} ms  image={mb:.1f} MiB", flush=True)

    # control: smooth sine, same geometry
    sig2 = 100.0 * np.sin(2.0 * np.pi * 1.0 * t)
    env_t, env_s = positions_envelope(
        t, sig2, xlim=(float(t[0]), float(t[-1])), pixel_width=1550,
        is_monotonic=True,
    )
    y_span = 2 * 110.0
    dy = np.abs(np.diff(env_s))
    travel_px = float(np.minimum(dy, y_span).sum() / y_span * 800)
    started = time.perf_counter()
    build_dense_raster_image(
        env_t, env_s, data_rect=(float(t[0]), float(t[-1]), -110.0, 110.0),
        logical_size=(1550, 800), dpr=2.0, color="#1769e0", line_width=1.5,
    )
    ms = (time.perf_counter() - started) * 1000.0
    cases_out.append({
        "label": "smooth control (1550x800)", "pts": len(env_s),
        "ink_travel_px": travel_px, "build_ms": ms,
    })
    print(f"smooth control (1550x800)  pts={len(env_s):5d}  "
          f"ink_travel={travel_px/1000:8.1f}k px  build={ms:7.1f} ms", flush=True)

    env = _environment(app)
    env["offscreen_forced"] = True
    env["assumed_dpr"] = 2.0
    return {"command": "raster-build", "environment": env, "cases": cases_out}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

_HANDLERS = {
    "sweep-y": cmd_sweep_y,
    "sweep-buckets": cmd_sweep_buckets,
    "aa-frame": cmd_aa_frame,
    "raster-build": cmd_raster_build,
}


def _arguments():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "sweep-y",
        help="19-point Y-window ratio sweep (0.05<=ratio<=9.8); pan-frame "
             "cost vs ink density (spec Sec 1.1). Real machine only.",
    )
    p.add_argument("--json-out", type=Path)

    p = sub.add_parser(
        "sweep-buckets",
        help="Envelope bucket-cap sweep (1550/1200/800/500/350) at Y=+-105 "
             "ratio~1.0 (spec Sec 3.2/4.1). Real machine only.",
    )
    p.add_argument("--json-out", type=Path)

    p = sub.add_parser(
        "aa-frame",
        help="One bounded vector-AA frame per case: smooth control, 1ch "
             "oscillating, 6ch oscillating (spec Sec 1.2/1.3). Real machine "
             "only; the 1ch oscillating case is expected to take "
             "60-125s for its single frame, not a hang.",
    )
    p.add_argument("--json-out", type=Path)
    p.add_argument(
        "--cases",
        help="Comma-separated case-label substrings to run (case-insensitive), "
             "e.g. '6ch' to rerun only the 6ch oscillating case. Default: all.",
    )

    p = sub.add_parser(
        "raster-build",
        help="dense_raster non-AA build cost + ink_travel metric (spec "
             "Sec 3.2/4.3). Forces QT_QPA_PLATFORM=offscreen itself; "
             "the only subcommand valid headless.",
    )
    p.add_argument("--json-out", type=Path)

    return parser.parse_args()


def main():
    args = _arguments()
    result = _HANDLERS[args.command](args)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
