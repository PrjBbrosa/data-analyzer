"""Decompose where a time-domain View switch and a Section switch spend time.

Two scenarios on a synthetic CSV:

``--scenario view`` (default) gives View A and View B three different
channels each, then alternates View A <-> B through the real
``view_tabbar.switch_requested`` path.

``--scenario section`` computes Time, FFT, Order and FFT-vs-Time results
first (EPS-like motor speed ramp + motor torque with order content), then
walks an Eulerian circuit over every directed Section pair through the real
``toolbar.mode_changed`` path, so every "A -> B" direction is sampled.

Per switch it records:

* synchronous handler time and the longest main-thread block (1 ms heartbeat);
* per-stage inclusive timings (projection, plot, cache re-render, settle,
  UltraView capture);
* every GraphicsView paint with its owning canvas class, duration, AA state
  and whether it ran inside the UltraView automatic capture;
* page-transition overlay frame gaps (a hitch in the fade shows up here);
* Python GC pauses.

A/B switches (diagnosis only, never a product setting):
  PROBE_NO_AA_UPGRADE=1      skip the idle/discrete AA upgrade (time canvas
                             and analysis line canvas)
  PROBE_NO_UV_AUTOCAPTURE=1  skip UltraView automatic preview captures
  PROBE_NO_SLICE_AA=1        draw the heatmap slice curve without AA
  PROBE_TICK_MEMO=1          skip heatmap bottom-tick recompute when the
                             (axis, range, width, target) input is unchanged
  PROBE_ACK_PREPARE=1        settle pyqtgraph lazy auto-range before the FFT
                             canvas samples its paint-ack geometry

Evidence class: whatever platform it runs on.  Under ``offscreen`` the paint
numbers are a CPU-raster proxy only (same QRasterPaintEngine as Windows
widgets, but no GDI/DWM flush and a different font engine); they are not
Windows foreground or frozen-exe evidence.  On a Windows machine run it
without ``QT_QPA_PLATFORM`` from the source checkout.

Usage:
  TMPDIR=/tmp QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 PYTHONPATH=. \
    .venv/bin/python scripts/probe_switch_smoothness.py \
    --win-w 1536 --win-h 824 --motion light --out result.json
  ... scripts/probe_switch_smoothness.py --scenario section --reps 3 ...
"""
from __future__ import annotations

import argparse
import functools
import gc
import json
import os
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PyQt5.QtCore import QCoreApplication, QSettings, QTimer  # noqa: E402

QCoreApplication.setOrganizationName("TraceLabProbe")
QCoreApplication.setApplicationName("SmoothnessProbe")
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())

from mf4_analyzer.app import _configure_high_dpi  # noqa: E402

_configure_high_dpi()

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")
from mf4_analyzer.ui_kit import load_stylesheet, setup_chinese_font  # noqa: E402

setup_chinese_font()
load_stylesheet(app)

from mf4_analyzer.ui.main_window import MainWindow  # noqa: E402
from mf4_analyzer.ui.chart_stack import stack as stack_mod  # noqa: E402
from mf4_analyzer.ui.chart_stack import page_transition as pt_mod  # noqa: E402
from mf4_analyzer.ui import view_bridge  # noqa: E402
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF  # noqa: E402
import pyqtgraph as pg  # noqa: E402

TIMES = defaultdict(list)
_GC = {"t0": None, "pauses": []}


def _gc_cb(phase, info):
    if phase == "start":
        _GC["t0"] = time.perf_counter()
    elif _GC["t0"] is not None:
        _GC["pauses"].append((info.get("generation"), (time.perf_counter() - _GC["t0"]) * 1000.0))
        _GC["t0"] = None


gc.callbacks.append(_gc_cb)
_DEPTH = defaultdict(int)


def _wrap(owner, name, label=None):
    label = label or f"{getattr(owner, '__name__', owner)}.{name}"
    orig = getattr(owner, name)

    @functools.wraps(orig)
    def wrapper(*args, **kwargs):
        _DEPTH[label] += 1
        t0 = time.perf_counter()
        try:
            return orig(*args, **kwargs)
        finally:
            _DEPTH[label] -= 1
            if _DEPTH[label] == 0:
                TIMES[label].append((time.perf_counter() - t0) * 1000.0)

    setattr(owner, name, wrapper)


for owner, name in (
    (MainWindow, "_switch_view"),
    (MainWindow, "_render_view_onto_canvas"),
    (MainWindow, "_project_view_controls"),
    (MainWindow, "_plot_time_on_canvas"),
    (MainWindow, "_build_time_plot_data"),
    (MainWindow, "_on_mode_changed"),
    (MainWindow, "_render_time_section_entry"),
    (MainWindow, "_enter_fft_mode"),
    (MainWindow, "_on_analysis_view_switched"),
    (MainWindow, "_capture_focused_view"),
    (stack_mod.ChartStack, "begin_page_transition"),
    (pt_mod.PageTransitionController, "capture_local_endpoint"),
    (pt_mod.TransitionOverlay, "paintEvent"),
    (view_bridge, "apply_controls_from_state"),
    (pg.GraphicsView, "paintEvent"),
):
    if hasattr(owner, name):
        _wrap(owner, name)

from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG  # noqa: E402
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas  # noqa: E402
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas  # noqa: E402
from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas  # noqa: E402
from mf4_analyzer.ui.main_window import ultraview_capture_coordinator as uvc  # noqa: E402

_CANVAS_CLASSES = (TimeDomainCanvasPG, PgLineCanvas, PgHeatmapCanvas, PgFrfCanvas)

for owner, name in (
    (TimeDomainCanvasPG, "plot_channels"),
    (TimeDomainCanvasPG, "settle_view_restore"),
    (TimeDomainCanvasPG, "restore_visible_ylims"),
    (TimeDomainCanvasPG, "_refresh_visible_data"),
    (MainWindow, "_begin_compute_progress"),
    (MainWindow, "_apply_view_chart_appearance"),
    (MainWindow, "_sync_record_curve_tree"),
    (MainWindow, "_capture_active_analysis_view"),
    (MainWindow, "_apply_active_analysis_context"),
    (MainWindow, "_render_analysis_view_from_cache"),
    (MainWindow, "_render_order_on"),
    (MainWindow, "_render_fft_time_on"),
    (MainWindow, "_plot_fft_entries"),
    (MainWindow, "_refresh_fft_time_preview"),
    (MainWindow, "_sync_section_effective_facts"),
    (MainWindow, "_project_analysis_attachments"),
    (MainWindow, "_refresh_analysis_candidates"),
    (MainWindow, "_maybe_fill_empty_analysis_on_mode_entry"),
    (MainWindow, "_stamp_db_reference_nudge_facts"),
    (MainWindow, "_resolve_and_apply_db_reference"),
    (MainWindow, "plot_time"),
    (stack_mod.ChartStack, "set_mode"),
    (stack_mod.ChartStack, "ensure_analysis_page_ready"),
    (PgLineCanvas, "plot_spectra"),
    (PgHeatmapCanvas, "plot_or_update_heatmap"),
    (PgHeatmapCanvas, "plot_result"),
    (uvc.UltraViewCaptureCoordinator, "_publish_grab"),
):
    if hasattr(owner, name):
        _wrap(owner, name)

TRANSITIONS = []
_orig_cross = MainWindow._begin_cross_section_page_transition


def _cross(self, *a, **k):
    r = _orig_cross(self, *a, **k)
    TRANSITIONS.append(r is not None)
    return r


MainWindow._begin_cross_section_page_transition = _cross

DELTA = []
_orig_delta = TimeDomainCanvasPG.try_apply_selection_delta


def _delta(self, *a, **k):
    t0 = time.perf_counter()
    r = _orig_delta(self, *a, **k)
    DELTA.append((r.get("reason") if isinstance(r, dict) else r, r.get("applied") if isinstance(r, dict) else None, round((time.perf_counter() - t0) * 1000, 2)))
    return r


TimeDomainCanvasPG.try_apply_selection_delta = _delta

FRAMES = []
PAINTS = []
_IN_GRAB = [0]
_orig_pub = uvc.UltraViewCaptureCoordinator._publish_grab


def _pub(self, *a, **k):
    _IN_GRAB[0] += 1
    try:
        return _orig_pub(self, *a, **k)
    finally:
        _IN_GRAB[0] -= 1


uvc.UltraViewCaptureCoordinator._publish_grab = _pub
_orig_gv_paint = pg.GraphicsView.paintEvent
_T_CLICK = [0.0]


def _gv_paint(self, ev):
    t0 = time.perf_counter()
    r = _orig_gv_paint(self, ev)
    canvas = self.parent()
    while canvas is not None and not isinstance(canvas, _CANVAS_CLASSES):
        canvas = canvas.parent()
    aa = None
    kind = type(canvas).__name__ if canvas is not None else None
    if canvas is not None:
        q = getattr(canvas, "_quality", None)
        aa = getattr(q, "aa_on", None) if q is not None else getattr(canvas, "_aa_on", None)
    PAINTS.append((round((t0 - _T_CLICK[0]) * 1000, 1), round((time.perf_counter() - t0) * 1000, 1), aa, bool(_IN_GRAB[0]), kind))
    return r


pg.GraphicsView.paintEvent = _gv_paint

if os.environ.get("PROBE_NO_AA_UPGRADE"):
    from mf4_analyzer.ui.pg_canvas import quality as _q
    _q.QualityManager.try_enable_idle_quality = lambda self: None
    PgLineCanvas._enable_idle_quality = lambda self: None
if os.environ.get("PROBE_NO_UV_AUTOCAPTURE"):
    uvc.UltraViewCaptureCoordinator.request_capture = lambda self, *a, **k: None
    uvc.UltraViewCaptureCoordinator.offer_capture_bound_canvas = lambda self, *a, **k: None
if os.environ.get("PROBE_NO_SLICE_AA"):
    _orig_set_curve_aa = PgHeatmapCanvas._set_curve_aa
    PgHeatmapCanvas._set_curve_aa = staticmethod(lambda curve, on: _orig_set_curve_aa(curve, False))
if os.environ.get("PROBE_TICK_MEMO"):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as _hc
    _orig_ticks = _hc._apply_target_bottom_ticks
    _TICK_LAST = {}

    def _memo_ticks(axis, view_box, target_count, owner=None):
        try:
            key = (tuple(view_box.viewRange()[0]), float(axis.size().width()), int(target_count),
                   bool(owner is None or owner.isVisible()))
        except RuntimeError:
            return _orig_ticks(axis, view_box, target_count, owner)
        hit = _TICK_LAST.get(id(axis))
        if hit is not None and hit[0] == key:
            return hit[1]
        result = _orig_ticks(axis, view_box, target_count, owner)
        _TICK_LAST[id(axis)] = (key, result)
        return result

    _hc._apply_target_bottom_ticks = _memo_ticks
if os.environ.get("PROBE_ACK_PREPARE"):
    _orig_ack_request = PgLineCanvas.request_presentation_paint_ack

    def _ack_request(self, request_id):
        try:
            self._glw.scene().prepareForPaint()
        except RuntimeError:
            pass
        return _orig_ack_request(self, request_id)

    PgLineCanvas.request_presentation_paint_ack = _ack_request
_orig_ov_paint = pt_mod.TransitionOverlay.paintEvent


def _ov_paint(self, ev):
    FRAMES.append(time.perf_counter())
    return _orig_ov_paint(self, ev)


pt_mod.TransitionOverlay.paintEvent = _ov_paint


class Heartbeat:
    """1 ms timer; records the largest gap = longest main-thread block."""

    def __init__(self):
        self.timer = QTimer()
        self.timer.setInterval(1)
        self.timer.timeout.connect(self._tick)
        self.last = None
        self.gaps = []

    def start(self):
        self.gaps = []
        self.last = time.perf_counter()
        self.timer.start()

    def _tick(self):
        now = time.perf_counter()
        self.gaps.append((now - self.last) * 1000.0)
        self.last = now

    def stop(self):
        self.timer.stop()
        # A block that ends inside the final processEvents() never gets a
        # following tick; close the window explicitly so it is not dropped.
        self._tick()
        return max(self.gaps) if self.gaps else None


def pump(ms):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.001)


def make_csv(path, points, channels, fs, *, eps=False):
    t = np.arange(points) / fs
    rng = np.random.default_rng(7)
    data = {"time": t}
    for i in range(channels):
        f = 3 + 2 * i
        data[f"ch{i}"] = (
            np.sin(2 * np.pi * f * t) * (10 + i)
            + 0.3 * rng.standard_normal(points)
        )
    if eps:
        # Motor speed run-up with 2nd/6th order torque ripple, so COT and
        # the spectrogram have real content to draw.
        rpm = np.linspace(600.0, 3000.0, points)
        phase = 2 * np.pi * np.cumsum(rpm / 60.0) / fs
        data["motor_speed"] = rpm
        data["motor_torque"] = (
            2.0 + 0.4 * np.sin(2 * phase) + 0.15 * np.sin(6 * phase)
            + 0.05 * rng.standard_normal(points)
        )
    pd.DataFrame(data).to_csv(path, index=False)


def section_circuit(sections):
    """Eulerian circuit over every directed pair, starting at sections[0]."""
    edges = {a: [b for b in sections if b != a] for a in sections}
    stack, path = [sections[0]], []
    while stack:
        v = stack[-1]
        if edges[v]:
            stack.append(edges[v].pop(0))
        else:
            path.append(stack.pop())
    return path[::-1]


def log(msg):
    print(f"[probe] {msg}", file=sys.stderr, flush=True)


def summarize(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return {"median": round(statistics.median(vals), 1),
            "max": round(max(vals), 1), "min": round(min(vals), 1)}


def part_summary(rows):
    agg = defaultdict(list)
    calls = defaultdict(list)
    for r in rows:
        for k, v in r["parts"].items():
            agg[k].append(sum(v))
            calls[k].append(len(v))
    return {
        k: {"median_total_ms": round(statistics.median(v), 1),
            "median_calls": statistics.median(calls[k])}
        for k, v in sorted(agg.items())
    }


def _emit(result, out):
    text = json.dumps(result, indent=1, ensure_ascii=False)
    print(text)
    if out:
        Path(out).write_text(text)
    sys.stdout.flush()
    # The synthetic session is dirty; a normal close() opens the modal
    # unsaved-project prompt and would hang an unattended run.
    os._exit(0)


def _wait_jobs(win, section, timeout_s=60.0):
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        app.processEvents()
        if not win._analysis_jobs.is_running(section):
            break
        time.sleep(0.005)
    pump(400)


def _seed_analysis_results(win, fid, names):
    """Compute one result per analysis Section through the product slots."""
    win.toolbar.mode_changed.emit("fft")
    pump(400)
    win._attach_files_to_active_context([fid])
    win.navigator.set_checked_channels([(fid, "motor_torque"), (fid, names[0])])
    pump(200)
    win.do_fft()
    pump(600)
    for section in ("order", "fft_time"):
        win.toolbar.mode_changed.emit(section)
        pump(400)
        win._attach_files_to_active_context([fid])
        ctx = win._analysis_ctx(section)
        win._echo_combo_signal(ctx.combo_sig, (fid, "motor_torque"))
        if section == "order":
            win._echo_combo_signal(ctx.combo_rpm, (fid, "motor_speed"))
            win.do_order_time()
        else:
            win.do_fft_time()
        _wait_jobs(win, section)
    computed = {}
    for section in ("fft", "order", "fft_time"):
        page = win._analysis_page(section)
        canvas = page.pane_canvas(page.focused_index())
        computed[section] = bool(getattr(canvas, "has_result", lambda: False)())
    return computed


def run_section_scenario(win, fid, args, load_ms):
    names = [f"ch{i}" for i in range(args.channels)]
    computed = _seed_analysis_results(win, fid, names)
    log(f"analysis seeded: {computed}")
    win.toolbar.mode_changed.emit("time")
    pump(800)

    controller = win.chart_stack.page_transition()
    finished = []
    cancelled = []
    controller.transition_finished.connect(lambda *_: finished.append(1))
    controller.transition_cancelled.connect(lambda r: cancelled.append(r))

    sections = ["time", "fft", "order", "fft_time"]
    circuit = section_circuit(sections)
    route = [circuit[0]]
    for _ in range(args.reps):
        route.extend(circuit[1:])
    hb = Heartbeat()
    samples = []
    for i, (src, dst) in enumerate(zip(route, route[1:])):
        log(f"section {i}: {src} -> {dst}")
        TIMES.clear()
        _GC["pauses"].clear()
        DELTA.clear()
        FRAMES.clear()
        PAINTS.clear()
        TRANSITIONS.clear()
        finished.clear()
        cancelled.clear()
        hb.start()
        t_click = time.perf_counter()
        _T_CLICK[0] = t_click
        win.toolbar.mode_changed.emit(dst)
        t_sync = time.perf_counter()
        started = bool(TRANSITIONS and TRANSITIONS[0])
        deadline = t_sync + 1.5
        t_done = None
        while time.perf_counter() < deadline:
            app.processEvents()
            if started and (finished or cancelled) and t_done is None:
                t_done = time.perf_counter()
            if t_done is not None and time.perf_counter() - t_done > 0.05:
                break
            if not started and time.perf_counter() - t_sync > 0.8:
                break
            time.sleep(0.0005)
        pump(500)
        max_gap = hb.stop()
        paints = list(PAINTS)
        samples.append({
            "pair": f"{src}->{dst}",
            "lap": i // (len(circuit) - 1),
            "sync_handler_ms": (t_sync - t_click) * 1000.0,
            "transition_started": started,
            "to_fade_end_ms": (t_done - t_click) * 1000.0 if t_done else None,
            "max_event_loop_block_ms": max_gap,
            "cancelled": list(cancelled),
            "paint_total_ms": round(sum(p[1] for p in paints), 1),
            "aa_paint_ms": round(sum(p[1] for p in paints if p[2]), 1),
            "uv_grab_paint_ms": round(sum(p[1] for p in paints if p[3]), 1),
            "max_paint_ms": max((p[1] for p in paints), default=0.0),
            "paints": paints,
            "delta": list(DELTA),
            "overlay_frame_gaps_ms": [round((b - a) * 1000, 1) for a, b in zip(FRAMES, FRAMES[1:])],
            "gc_pauses_ms": [(g, round(ms, 2)) for g, ms in _GC["pauses"] if ms > 0.5],
            "parts": {k: [round(x, 2) for x in v] for k, v in TIMES.items()},
        })

    warm = [s for s in samples if s["lap"] > 0] or samples
    by_pair = defaultdict(list)
    for s in warm:
        by_pair[s["pair"]].append(s)
    by_target = defaultdict(list)
    for s in warm:
        by_target[s["pair"].split("->")[1]].append(s)
    keys = ("sync_handler_ms", "to_fade_end_ms", "max_event_loop_block_ms",
            "paint_total_ms", "aa_paint_ms", "uv_grab_paint_ms", "max_paint_ms")
    result = {
        "platform": app.platformName(),
        "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
        "dpr": win.devicePixelRatioF(),
        "window_logical": [win.width(), win.height()],
        "points_per_channel": args.points,
        "motion": args.motion,
        "load_ms": round(load_ms, 1),
        "computed": computed,
        "env": {k: v for k, v in os.environ.items() if k.startswith("PROBE_")},
        "by_pair": {
            pair: {k: summarize(rows, k) for k in keys}
            | {"transition_started": [r["transition_started"] for r in rows]}
            for pair, rows in sorted(by_pair.items())
        },
        "by_target": {
            dst: {k: summarize(rows, k) for k in keys} | {"parts": part_summary(rows)}
            for dst, rows in sorted(by_target.items())
        },
        "raw": samples,
    }
    _emit(result, args.out)


def main():
    import faulthandler
    faulthandler.dump_traceback_later(180, repeat=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", type=int, default=200_000)
    ap.add_argument("--channels", type=int, default=8)
    ap.add_argument("--fs", type=float, default=10_000.0)
    ap.add_argument("--motion", choices=("light", "off"), default="light")
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--out", default=None)
    ap.add_argument("--win-w", type=int, default=1600)
    ap.add_argument("--win-h", type=int, default=950)
    ap.add_argument("--scenario", choices=("view", "section"), default="view")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp())
    csv = tmp / "probe.csv"
    make_csv(csv, args.points, args.channels, args.fs, eps=args.scenario == "section")

    log("csv ready")
    win = MainWindow()
    log("window built")
    win.resize(args.win_w, args.win_h)
    win.show()
    pump(300)
    win.chart_stack.set_page_transition_motion_policy(
        POLICY_LIGHT if args.motion == "light" else POLICY_OFF
    )
    t0 = time.perf_counter()
    win.load_file(str(csv))
    pump(500)
    log("loaded")
    load_ms = (time.perf_counter() - t0) * 1000.0
    fid = next(iter(win.files))
    names = [f"ch{i}" for i in range(args.channels)]

    def check(chs):
        win.navigator.set_checked_channels([(fid, c) for c in chs])
        win._ch_changed()
        pump(400)

    check(names[0:3])
    log("view A checked")
    if args.scenario == "section":
        run_section_scenario(win, fid, args, load_ms)
        return
    win._on_view_new()
    pump(300)
    win._attach_files_to_focused_view([fid])
    pump(300)
    check(names[3:6])
    log("view B checked")
    pump(300)

    controller = win.chart_stack.page_transition()
    finished = []
    cancelled = []
    controller.transition_finished.connect(lambda *_: finished.append(1))
    controller.transition_cancelled.connect(lambda r: cancelled.append(r))

    hb = Heartbeat()
    samples = []
    for rep in range(args.reps):
        target = 0 if win.view_manager.active == 1 else 1
        log(f"switch rep {rep}")
        TIMES.clear()
        _GC["pauses"].clear()
        DELTA.clear()
        FRAMES.clear()
        PAINTS.clear()
        finished.clear()
        cancelled.clear()
        hb.start()
        t_click = time.perf_counter()
        _T_CLICK[0] = t_click
        win.view_tabbar.switch_requested.emit(target)
        t_sync = time.perf_counter()
        # wait for the fade to finish (or ~0.6 s if Off)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline:
            app.processEvents()
            if args.motion == "light" and (finished or cancelled):
                break
            if args.motion == "off" and time.perf_counter() - t_sync > 0.6:
                break
            time.sleep(0.0005)
        t_done = time.perf_counter()
        pump(200)
        max_gap = hb.stop()
        samples.append({
            "sync_handler_ms": (t_sync - t_click) * 1000.0,
            "to_fade_end_ms": (t_done - t_click) * 1000.0 if args.motion == "light" else None,
            "max_event_loop_block_ms": max_gap,
            "cancelled": list(cancelled),
            "target": target,
            "paints": list(PAINTS),
            "ink_total": float(win.canvas_time._quality._frame_native_ink_total()),
            "aa_on_after": bool(win.canvas_time._quality.aa_on),
            "delta": list(DELTA),
            "overlay_frame_gaps_ms": [round((b - a) * 1000, 1) for a, b in zip(FRAMES, FRAMES[1:])],
            "first_overlay_frame_after_click_ms": round((FRAMES[0] - t_click) * 1000, 1) if FRAMES else None,
            "gc_pauses_ms": [(g, round(ms, 2)) for g, ms in _GC["pauses"] if ms > 0.5],
            "parts": {k: [round(x, 2) for x in v] for k, v in TIMES.items()},
        })

    # Section round trip time -> fft -> time (no FFT computed: direct-terminal)
    section = []
    for rep in range(4):
        for mode in ("fft", "time"):
            TIMES.clear()
            hb.start()
            t_click = time.perf_counter()
            win.toolbar.mode_changed.emit(mode)
            t_sync = time.perf_counter()
            pump(600)
            max_gap = hb.stop()
            section.append({
                "to": mode,
                "sync_handler_ms": (t_sync - t_click) * 1000.0,
                "max_event_loop_block_ms": max_gap,
                "parts": {k: [round(x, 2) for x in v] for k, v in TIMES.items()},
            })

    # drop first sample (warm-up) from summary
    warm = samples[1:] if len(samples) > 1 else samples
    screen = app.primaryScreen()
    result = {
        "platform": app.platformName(),
        "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
        "dpr": win.devicePixelRatioF(),
        "screen_logical": [screen.size().width(), screen.size().height()],
        "window_logical": [win.width(), win.height()],
        "points_per_channel": args.points,
        "motion": args.motion,
        "load_ms": round(load_ms, 1),
        "view_switch": {
            "sync_handler_ms": summarize(warm, "sync_handler_ms"),
            "to_fade_end_ms": summarize(warm, "to_fade_end_ms"),
            "max_event_loop_block_ms": summarize(warm, "max_event_loop_block_ms"),
            "cancelled": [s["cancelled"] for s in warm if s["cancelled"]],
            "parts": part_summary(warm),
            "raw": samples,
        },
        "gc_counts": gc.get_count(),
        "gc_objects": len(gc.get_objects()),
        "section_switch": {
            mode: {
                "sync_handler_ms": summarize([s for s in section if s["to"] == mode], "sync_handler_ms"),
                "max_event_loop_block_ms": summarize([s for s in section if s["to"] == mode], "max_event_loop_block_ms"),
                "parts": part_summary([s for s in section if s["to"] == mode]),
            }
            for mode in ("fft", "time")
        },
    }
    _emit(result, args.out)


if __name__ == "__main__":
    main()
