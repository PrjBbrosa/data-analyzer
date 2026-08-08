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
    .venv/bin/python scripts/probe_aa_ink_budget.py overlay-gate --json-out out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
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


def _wait_window_exposed(app, widget, *, timeout_ms=3000.0):
    """Spin the event loop until the window server has really mapped ``widget``.

    ``show()`` + one ``processEvents()`` is NOT enough on Cocoa when a probe
    creates and closes a canvas per case: the next window can still be
    unexposed when the first repaint is requested, and an unexposed window
    turns ``viewport.repaint()`` into a silent no-op. Observed directly — a
    whole case measuring 0.0/0.1/0.0 ms for AA-off, first-AA and steady-AA
    frames while the identical case immediately before it measured
    4.5/203.5/204.7 ms, and the layout width differed too (1490 vs 1511 px),
    i.e. the window had not even settled its geometry. This is the same
    missed-repaint failure ``_timed_repaint``'s floor guard exists to CATCH;
    waiting for exposure is what PREVENTS it, because no number of retries
    can make an unmapped window paint.

    Returns True when exposed. Callers should record a False as a suspect
    measurement rather than trusting the frame times that follow.
    """
    handle = widget.windowHandle()
    deadline = time.perf_counter() + float(timeout_ms) / 1000.0
    while time.perf_counter() < deadline:
        app.processEvents()
        if handle is None:
            handle = widget.windowHandle()
        try:
            if handle is not None and handle.isExposed():
                # One more spin so the exposure-driven relayout/resize lands
                # before anything reads _current_pixel_width().
                app.processEvents()
                return True
        except Exception:
            return False
        time.sleep(0.01)
    return False


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
    print(f"{'y_half':>8} {'ratio':>7} {'pts':>6} {'ink':>5} "
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
        ink_high = bool(getattr(canvas, "_frame_ink_high", False))

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
            "y_half": y_half, "ratio": ratio, "pts": pts, "ink_high": ink_high,
            "pan_p50_ms": pan_p50, "pan_p95_ms": pan_p95,
        })
        print(f"{y_half:>8} {ratio:>7.2f} {pts:>6} {'Y' if ink_high else 'n':>5} "
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
    ink_high = bool(getattr(canvas, "_frame_ink_high", False))
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
        "ink_high": ink_high, "aa_ok": aa_allowed, "pan_p50_ms": pan_p50,
        "pan_p95_ms": pan_p95,
    }
    print(
        f"{label:<34} ratio={ratio:6.2f} pts={pts:6d} "
        f"ink_high={'Y' if ink_high else 'n'} aa_ok={'Y' if aa_allowed else 'n'} "
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
        ("1800-bucket   (1800x800)", 1800, (1550, 800)),
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
# overlay-gate : old overlay density gate vs ink gate, disagreement set
#                (plan 2026-08-08-overlay-density-gate-ink-migration Task 1)
# --------------------------------------------------------------------------
#
# The overlay AA gate still ships TWO independent refusals
# (quality._idle_aa_density_ok):
#
#   old:  _overlay_density_pressure_status() -- >= 2 visible curves whose RAW
#         decimation ratio (source samples / _current_pixel_width) reaches
#         _SUBPLOT_DENSE_DECIMATION (8.0);
#   ink:  the frame's summed native-AA ink vs _INK_AA_ON / _INK_AA_OFF.
#
# The two disagree in both directions, and this subcommand measures the whole
# 2x2 so the migration decision rests on numbers rather than on the argument:
#
#   A  high ratio / low ink  -- old BLOCKS, ink ALLOWS  = false positive, the
#                               class the migration would RELEASE. Its measured
#                               AA frame IS the risk of the migration.
#   B  low ratio / high ink  -- old ALLOWS, ink BLOCKS  = false negative, the
#                               class the old gate never contributed to.
#   C  high ratio / high ink -- both block (no behavior change).
#   D  low ratio / low ink   -- both allow (no behavior change).
#
# GO / NO-GO (fixed by the plan before any number was taken): class A's AA-on
# frame <= 300 ms -> go; > 300 ms -> the conclusion becomes "overlay needs a
# tighter ink band of its own", not "delete the gate".
#
# Fixture calibration (2026-08-08). The plan's first-draft frequencies (1.0 /
# 1.3 Hz for the smooth pairs) do NOT land in their intended quadrants on this
# canvas: they measure 334.2k dev px of frame ink, i.e. above _INK_AA_OFF, so
# the ink gate refuses them and neither A (false positive) nor D (double-low)
# exists at those parameters. Ink is linear in the number of displayed cycles
# (f x duration), so both smooth pairs were retuned DOWN in frequency until the
# frame ink sits just under _INK_AA_ON: 0.56 / 0.73 Hz -> ~187k dev px. That is
# deliberately the WORST case inside the released region rather than a
# comfortable one -- the migration releases exactly those overlays whose frame
# ink clears the band, so the most expensive AA frame it can hand a user is the
# one at the band edge. A2 is a supplementary mid-band point (0.25 / 0.33 Hz,
# ~84k) that gives the cost-vs-ink slope, so a NO-GO verdict can name where an
# overlay-specific band would have to sit instead of just failing.
#
# A and D differ ONLY in source sample count (1M @ 20 kHz vs 10k @ 200 Hz over
# the same 50 s span, identical waveform) -- that isolates the raw density the
# old gate keys on, with ink held constant. B and C are the same controlled
# pair on the oscillating side.
#
# Real machine only: these are Cocoa paint timings. Class B and C AA frames are
# expected to take tens of seconds each (that is the cost the ink gate exists
# to refuse), not a hang.

OVERLAY_GATE_AMPLITUDE = 100.0

OVERLAY_GATE_CASES = (
    {
        "key": "A", "kind": "smooth",
        "label": "A false-positive (hi ratio/lo ink)",
        "expect": "old=block ink=allow",
        "n_points": 1_000_000, "fs": 20_000.0, "freqs": (0.56, 0.73),
    },
    {
        "key": "D", "kind": "smooth",
        "label": "D double-low   (lo ratio/lo ink)",
        "expect": "old=allow ink=allow",
        "n_points": 10_000, "fs": 200.0, "freqs": (0.56, 0.73),
    },
    {
        "key": "A2", "kind": "smooth",
        "label": "A2 mid-band    (hi ratio/lo ink)",
        "expect": "old=block ink=allow",
        "n_points": 1_000_000, "fs": 20_000.0, "freqs": (0.25, 0.33),
    },
    {
        "key": "B", "kind": "oscillating",
        "label": "B false-negative(lo ratio/hi ink)",
        "expect": "old=allow ink=block",
        "n_points": 10_000, "fs": 200.0, "freqs": (97.0, 94.0),
    },
    {
        "key": "C", "kind": "oscillating",
        "label": "C double-high  (hi ratio/hi ink)",
        "expect": "old=block ink=block",
        "n_points": 1_000_000, "fs": 20_000.0, "freqs": (2300.0, 2437.0),
    },
)

OVERLAY_GATE_GO_LIMIT_MS = 300.0


def make_overlay_rows(*, n_points, fs, freqs, tag):
    """Two-channel overlay fixture: pure sines, +-OVERLAY_GATE_AMPLITUDE.

    A plain sine (never a synthesized square / alternating sequence) keeps the
    RenderProfile on ``general``: an alternating full-scale sequence would
    classify as ``dense_discrete`` and be refused by the raster-cost gate
    instead of the ink gate, measuring the wrong mechanism.
    """
    import numpy as np

    t = np.arange(int(n_points), dtype=np.float64) / float(fs)
    rows = []
    for i, freq in enumerate(freqs):
        sig = OVERLAY_GATE_AMPLITUDE * np.sin(2.0 * np.pi * float(freq) * t)
        rows.append((
            f"Motor Speed {i + 1}", True, t, sig,
            COLORS[i % len(COLORS)], "rpm", tag,
        ))
    return rows


def _retired_overlay_pressure_verdict(canvas, pixel_width):
    """Recompute the RETIRED raw-density gate so the comparison survives it.

    The gate itself was deleted from the product in the Task 2 migration
    (`quality._overlay_density_pressure_status`). Its rule is reproduced here
    — and ONLY here, in the probe — so this subcommand keeps answering the
    question it exists to answer ("what would the old gate have said?") after
    the thing it describes is gone. Rule as shipped up to 2026-08-08:
    a visible overlay curve counts when ``source_len / pixel_width >= 8``,
    and the gate blocked once two or more curves counted.
    """
    if not bool(getattr(canvas, "_overlay_mode", False)):
        return {"blocked": False, "count": 0, "labels": ()}
    try:
        width = float(pixel_width)
    except (TypeError, ValueError):
        return {"blocked": False, "count": 0, "labels": ()}
    if width <= 0:
        return {"blocked": False, "count": 0, "labels": ()}
    labels = []
    try:
        entries = list(canvas._channel_lines.composite_items())
    except Exception:
        return {"blocked": False, "count": 0, "labels": ()}
    for ck, name, (_axis, line) in entries:
        try:
            pdi = line.plot_data_item
            if pdi is None or not pdi.isVisible():
                continue
            if len(canvas.channel_data.get(ck)[1]) / width >= 8.0:
                labels.append(str(name))
        except Exception:
            continue
    return {
        "blocked": len(labels) >= 2,
        "count": len(labels),
        "labels": tuple(labels),
    }


def _overlay_gate_line_metrics(canvas):
    """Per-line source density + recorded ink for the current frame."""
    pixel_width = int(canvas._current_pixel_width())
    lines = []
    for ck, name, (axis, line) in canvas._channel_lines.composite_items():
        try:
            source_points = int(len(canvas.channel_data.get(ck)[1]))
        except Exception:
            source_points = 0
        state = canvas._line_ink_state.get(ck)
        try:
            ink = float(state[0])
        except (TypeError, IndexError, ValueError):
            ink = float("nan")
        try:
            xd, _ = line.plot_data_item.getData()
            displayed = 0 if xd is None else int(len(xd))
        except Exception:
            displayed = 0
        try:
            ylim = [round(float(v), 1) for v in axis.get_ylim()]
        except Exception:
            ylim = [0.0, 0.0]
        lines.append({
            "name": str(name),
            "source_points": source_points,
            "decimation_ratio": (
                source_points / pixel_width if pixel_width > 0 else float("inf")
            ),
            "ink_dev_px": ink,
            "displayed_points": displayed,
            "ylim": ylim,
        })
    return pixel_width, lines


def _run_overlay_gate_case(app, case, *, self_check=False):
    import numpy as np

    label = case["label"]
    rows = make_overlay_rows(
        n_points=case["n_points"], fs=case["fs"], freqs=case["freqs"],
        tag=f"overlay-gate-{case['key']}",
    )
    canvas, viewport = _new_canvas(app)
    canvas.raise_()
    canvas.activateWindow()
    exposed = _wait_window_exposed(app, canvas)
    canvas.plot_channels(
        rows, mode="overlay",
        render_context_key=("overlay-gate", case["key"]),
    )
    app.processEvents()
    viewport.repaint()
    # Production Y auto-fit, then settle the pending refresh so the recorded
    # per-line ink belongs to the geometry actually on screen.
    canvas.fit_y_to_visible_x()
    canvas._flush_pending_refresh()
    app.processEvents()
    viewport.repaint()

    quality = canvas._quality
    pixel_width, lines = _overlay_gate_line_metrics(canvas)
    frame_ink = float(quality._frame_native_ink_total())
    pressure = _retired_overlay_pressure_verdict(canvas, pixel_width)
    raster_cost = quality._high_raster_cost_status()
    density = quality._density_status()
    overlay_mode = bool(getattr(canvas, "_overlay_mode", False))

    # Verdict pair. Order matters: read the SHIPPED gate first, then the
    # post-migration one, so the hysteresis seeding the first call performs is
    # the same seeding production would perform today.
    gate_today = bool(quality._idle_aa_density_ok())
    status_today = quality.quality_status()
    # Post-migration IS today: the old gate no longer exists, so the two
    # columns coincide by construction. Kept side by side so a re-run of this
    # subcommand still reads against the pre-migration baseline JSON.
    gate_post = gate_today

    result = {
        "key": case["key"], "label": label, "expect": case["expect"],
        "fixture": {
            "n_points": case["n_points"], "fs": case["fs"],
            "freqs": list(case["freqs"]), "kind": case["kind"],
            "amplitude": OVERLAY_GATE_AMPLITUDE,
        },
        "overlay_mode": overlay_mode,
        "window_exposed": exposed,
        "pixel_width": pixel_width,
        "lines": lines,
        "frame_ink_dev_px": frame_ink,
        "old_gate_blocked": bool(pressure["blocked"]),
        "old_gate_dense_count": int(pressure["count"]),
        "ink_gate_blocked": not gate_post,
        "aa_gate_today": "allow" if gate_today else "block",
        "aa_gate_post_migration": "allow" if gate_post else "block",
        "block_reason_today": status_today.get("block_reason"),
        "raster_cost_blocked": bool(raster_cost["blocked"]),
        "point_metric": int(density["metric"]),
        "point_budget": int(density["off_budget"]),
    }

    ratios = ", ".join(f"{ln['decimation_ratio']:.1f}" for ln in lines)
    inks = ", ".join(f"{ln['ink_dev_px'] / 1000:.1f}k" for ln in lines)
    print(
        f"  {label}  pw={pixel_width} ratio=[{ratios}] ink=[{inks}] "
        f"frame_ink={frame_ink / 1000:.1f}k  old={'BLOCK' if pressure['blocked'] else 'allow'} "
        f"ink={'BLOCK' if result['ink_gate_blocked'] else 'allow'} "
        f"(today={result['aa_gate_today']}, post={result['aa_gate_post_migration']})",
        flush=True,
    )
    if self_check:
        canvas.close()
        app.processEvents()
        return result

    # AA-off frame (what the user gets while dragging). Cancel the pending idle
    # upgrade first: the 150 ms timer can otherwise fire inside one of this
    # probe's own processEvents() calls and hand the "AA-off" slot an AA frame.
    quality.disable_interactive_quality()
    off = []
    off_suspect = False
    for _ in range(4):
        ms, suspect = _timed_repaint(canvas, viewport)
        off.append(ms)
        off_suspect = off_suspect or suspect
    result["aa_off_frame_ms"] = float(np.median(off[1:]))

    # AA-on frames. When the gate refuses -- B and C -- AA is forced on anyway
    # so the refused cost is on the record; forcing deliberately skips
    # _open_aa_backstop_epoch so the measured-frame latch cannot tear AA off
    # between the first frame and the steady one.
    if True:
        enable_started = time.perf_counter()
        quality.try_enable_idle_quality()
        enable_ms = (time.perf_counter() - enable_started) * 1000.0
        aa_engaged = bool(quality.aa_on)
        forced = False
        if not aa_engaged:
            forced = True
            enable_ms = 0.0
            quality._set_curves_antialias(True)
            quality.aa_on = True
        first_repaint_ms, first_suspect = _timed_repaint(canvas, viewport)
        first_aa_ms = enable_ms + first_repaint_ms
        app.processEvents()  # lets a tripped backstop's zero-delay timer land

        backstop_reason = quality.aa_backstop_reason
        steady_reforced = False
        if not quality.aa_on:
            steady_reforced = True
            quality._set_curves_antialias(True)
            quality.aa_on = True
        steady_aa_ms, steady_suspect = _timed_repaint(canvas, viewport)
        app.processEvents()
        # Confirm the timed frames really were antialiased rather than trusting
        # the aa_on flag: a frame billed as "AA on" that painted without AA
        # would understate the very cost this probe exists to bound.
        curves_aa = all(
            bool(it.opts.get("antialias", False))
            for it in quality._collect_curve_items()
        ) and bool(quality._collect_curve_items())
        quality.disable_interactive_quality()

    result.update({
        "aa_engaged_via_gate": aa_engaged,
        "aa_forced": forced,
        "first_aa_frame_ms": first_aa_ms,
        "steady_aa_frame_ms": steady_aa_ms,
        "aa_actually_on_during_frames": curves_aa,
        "steady_reforced_after_backstop": steady_reforced,
        "backstop_reason": (
            [str(backstop_reason[0]), float(backstop_reason[1])]
            if backstop_reason else None
        ),
        "suspect": {
            "aa_off": off_suspect, "first_aa": first_suspect,
            "steady_aa": steady_suspect, "not_exposed": not exposed,
        },
    })
    suspect_txt = "  SUSPECT=" + ",".join(
        k for k, v in result["suspect"].items() if v
    ) if any(result["suspect"].values()) else ""
    print(
        f"      aa_off={result['aa_off_frame_ms']:8.1f}ms  "
        f"first_aa={first_aa_ms:10.1f}ms  steady_aa={steady_aa_ms:10.1f}ms  "
        f"engaged={'gate' if aa_engaged else 'FORCED'}"
        f"{'  backstop=' + str(backstop_reason[0]) if backstop_reason else ''}"
        f"{suspect_txt}",
        flush=True,
    )

    canvas.close()
    app.processEvents()
    return result


def cmd_overlay_gate(args):
    app = _qapp()
    probe_canvas, _vp = _new_canvas(app)
    env = _environment(app, probe_canvas)
    probe_canvas.close()
    app.processEvents()

    self_check = bool(getattr(args, "self_check", False))
    repeats = 1 if self_check else max(1, int(getattr(args, "repeats", 2) or 2))
    cases = [c for c in OVERLAY_GATE_CASES if _overlay_case_selected(c, args)]

    print(f"platform={app.platformName()} dpr={env.get('dpr')}", flush=True)
    print(
        "== overlay AA gate: old raw-density gate vs ink gate =="
        + ("  [self-check: quadrants only, no AA frames]" if self_check else ""),
        flush=True,
    )

    cases_out = []
    for case in cases:
        for run_index in range(repeats):
            print(f"[{case['key']} run {run_index + 1}/{repeats}] expect {case['expect']}",
                  flush=True)
            run = _run_overlay_gate_case(app, case, self_check=self_check)
            # A suspect run is a MISSED repaint, not a fast one. Redo the whole
            # case once on a fresh canvas rather than letting a 0 ms frame into
            # the record — it would drag a max/median toward "affordable" for
            # exactly the class whose affordability is the question.
            if not self_check and any(run.get("suspect", {}).values()):
                print("      -> suspect run, redoing case on a fresh canvas",
                      flush=True)
                retry = _run_overlay_gate_case(app, case, self_check=self_check)
                retry["retried_after_suspect"] = True
                run = retry
            run["run_index"] = run_index
            cases_out.append(run)

    verdict = None
    if not self_check:
        verdict = _overlay_gate_verdict(cases_out)
        if verdict is None:
            print("\nVERDICT: n/a — class A was not run", flush=True)
        else:
            print(
                f"\nVERDICT: {verdict['verdict'].upper()} — class A steady AA frame "
                f"{verdict['class_a_steady_max_ms']:.1f} ms (max over "
                f"{len(verdict['class_a_steady_ms'])} runs, spread "
                f"{verdict['class_a_steady_spread'] * 100:.0f}%) vs limit "
                f"{OVERLAY_GATE_GO_LIMIT_MS:.0f} ms",
                flush=True,
            )
    return {
        "command": "overlay-gate", "environment": env,
        "go_limit_ms": OVERLAY_GATE_GO_LIMIT_MS,
        "self_check": self_check, "repeats": repeats,
        "runs": cases_out, "verdict": verdict,
    }


def _overlay_case_selected(case, args):
    spec = getattr(args, "cases", None)
    if not spec:
        return True
    needles = [p.strip().lower() for p in spec.split(",") if p.strip()]
    if not needles:
        return True
    key = case["key"].lower()
    label = case["label"].lower()
    # Keys are one or two characters, so substring matching against the label
    # would make "A" select every case with an "a" anywhere in its prose
    # ("false-negative", "double-high", ...). Short needles match the KEY
    # exactly; only needles long enough to be words fall back to the label.
    return any(
        n == key or (len(n) >= 3 and n in label) for n in needles
    )


def _overlay_gate_verdict(runs):
    """go / no-go on the plan's single fixed criterion: class A's AA frame.

    Class A is the only class whose behavior the migration changes (old gate
    blocks it, ink gate allows it), so its measured AA cost is the entire risk.
    Takes the WORST run rather than the mean: the criterion is an upper bound
    on what a user can be handed, and reports the first/steady spread so an
    unstable measurement is visible instead of averaged away.
    """
    a_runs = [r for r in runs if r["key"] == "A" and "steady_aa_frame_ms" in r]
    if not a_runs:
        return None
    steady = [float(r["steady_aa_frame_ms"]) for r in a_runs]
    first = [float(r["first_aa_frame_ms"]) for r in a_runs]
    worst_steady = max(steady)
    spread = (
        (max(steady) - min(steady)) / min(steady) if min(steady) > 0 else 0.0
    )
    suspect = [i for i, r in enumerate(a_runs) if any(r.get("suspect", {}).values())]
    forced = [i for i, r in enumerate(a_runs) if r.get("aa_forced")]
    not_aa = [i for i, r in enumerate(a_runs)
              if not r.get("aa_actually_on_during_frames", True)]
    # A verdict is only as good as the frames behind it: a suspect (missed)
    # repaint or a frame that did not actually paint antialiased would both
    # read as "cheap" for the wrong reason, so they void the call instead of
    # producing a cheerful go.
    if suspect or not_aa:
        verdict = "invalid"
    elif worst_steady <= OVERLAY_GATE_GO_LIMIT_MS:
        verdict = "go"
    else:
        verdict = "no-go"
    return {
        "verdict": verdict,
        "class_a_steady_max_ms": worst_steady,
        "class_a_steady_ms": steady,
        "class_a_first_ms": first,
        "class_a_steady_spread": spread,
        "steady_spread_unstable": spread > 0.5,
        "suspect_run_indices": suspect,
        "forced_run_indices": forced,
        "frames_not_antialiased_run_indices": not_aa,
        "limit_ms": OVERLAY_GATE_GO_LIMIT_MS,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

_HANDLERS = {
    "sweep-y": cmd_sweep_y,
    "sweep-buckets": cmd_sweep_buckets,
    "aa-frame": cmd_aa_frame,
    "raster-build": cmd_raster_build,
    "overlay-gate": cmd_overlay_gate,
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

    p = sub.add_parser(
        "overlay-gate",
        help="Overlay AA gate disagreement set: the old raw-density gate vs "
             "the ink gate over the 2x2 (A false positive / B false negative "
             "/ C both block / D both allow), with measured AA frames. Backs "
             "the go/no-go in the overlay-density-gate-ink-migration plan "
             "Task 1. Real machine only; the B and C AA frames are expected "
             "to take tens of seconds each, not a hang.",
    )
    p.add_argument("--json-out", type=Path)
    p.add_argument(
        "--repeats", type=int, default=2,
        help="Runs per case for timing consistency (default 2; a >50%% spread "
             "on class A means the timing is unstable, not that AA got faster).",
    )
    p.add_argument(
        "--cases",
        help="Comma-separated case keys (A,A2,B,C,D) or label substrings. "
             "Default: all.",
    )
    p.add_argument(
        "--self-check", action="store_true",
        help="Quadrant self-check only: print ratio / ink / both gate verdicts "
             "per case and skip every AA frame. Use this to confirm the "
             "fixtures still land in their intended quadrants before paying "
             "for the slow AA timings.",
    )

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
