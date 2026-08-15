#!/usr/bin/env python3
"""View-switch quality probe: real-machine timing for the view-switch-quality-
settlement work.

Consolidates the six investigation scripts behind
``docs/analyzer/specs/2026-08-15-view-switch-quality-settlement-spec.md``
(originally under ``docs/analyzer/verify/2026-08-15-view-switch-quality-probes/
probes/``) into one argparse-driven tool. Each subcommand reproduces one table
from spec §1 so the baseline can be re-run and diffed as the implementation
lands. Synthetic signals, canvas sizes and output columns are carried over
unchanged from the originals.

IMPORTANT — real machine only: every subcommand except ``stale-ink`` measures
Cocoa paint/repaint wall-clock time or real event-loop timer landings. Numbers
from ``QT_QPA_PLATFORM=offscreen`` are NOT valid performance evidence (see
CLAUDE.md Gotchas: "验真机渲染") — do not set that env var when running them.
``stale-ink`` is the one exception: it reproduces a *logic* defect (ink
measured against a stub Y span before the real Y range is restored), so it
reproduces identically under ``offscreen`` — useful for a quick sanity check,
but the checked-in baseline under ``results/`` was still taken real-machine
for consistency with the other five.

Usage:
    .venv/bin/python scripts/probe_view_switch_quality.py time-mainwindow --json-out out.json
    .venv/bin/python scripts/probe_view_switch_quality.py time-canvas --json-out out.json
    .venv/bin/python scripts/probe_view_switch_quality.py ylim-order --json-out out.json
    .venv/bin/python scripts/probe_view_switch_quality.py stale-ink --json-out out.json
    .venv/bin/python scripts/probe_view_switch_quality.py analysis-frames --json-out out.json
    .venv/bin/python scripts/probe_view_switch_quality.py analysis-calibrate --json-out out.json
    .venv/bin/python scripts/probe_view_switch_quality.py spectrum-switch --json-out out.json

``analysis-calibrate`` is the one subcommand that is not a spec §1 baseline
reproduction: it is the calibration sweep behind spec §5's three analysis-canvas
ink-band rows (plan Task 4). ``analysis-frames`` stays as the untouched §1.4
baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


WIDTH, HEIGHT = 1600, 950
COLORS = ("#1769e0", "#00a67d", "#ff2038", "#ff5a0a", "#8747ff", "#d41445",
          "#0ca678", "#c2255c")


# --------------------------------------------------------------------------
# Shared helpers (pattern lifted from scripts/probe_aa_ink_budget.py: waiting
# for real window exposure and flagging suspiciously-fast/missed repaints —
# see that module's docstrings for the concrete failures these guard against).
# --------------------------------------------------------------------------

def _qapp():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait_window_exposed(app, widget, *, timeout_ms=4000.0):
    """Spin the event loop until the window server has really mapped ``widget``.

    ``show()`` + one ``processEvents()`` is not enough on Cocoa when a probe
    creates and closes widgets back to back: the next window can still be
    unexposed when the first repaint is requested, and an unexposed window
    turns ``viewport.repaint()`` into a silent no-op. Returns True when
    exposed; callers should record a False as a suspect measurement rather
    than trusting the frame times that follow.
    """
    handle = widget.windowHandle()
    deadline = time.perf_counter() + float(timeout_ms) / 1000.0
    while time.perf_counter() < deadline:
        app.processEvents()
        if handle is None:
            handle = widget.windowHandle()
        try:
            if handle is not None and handle.isExposed():
                app.processEvents()
                return True
        except Exception:
            return False
        time.sleep(0.01)
    return False


def _settle(app, ms=250):
    """Spin the event loop for roughly ``ms`` milliseconds.

    Used to let idle quality timers (150 ms), dense-raster rebuild timers
    (0/40 ms) and similar deferred work land before a snapshot is taken.
    """
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def _timed_repaint(canvas, viewport, *, retries=1, floor_ms=0.5):
    """Time one forced, non-coalesced repaint; flags a suspiciously-fast frame.

    Explicitly marks the whole scene dirty (``scene().update()``) before every
    attempt, then repaints and times it. If the timed value is still under
    ``floor_ms`` after ``retries`` extra attempts, the caller should treat the
    frame as suspect (a missed repaint, not a genuinely free one) rather than
    trust the number. Pass ``retries=0, floor_ms=0.0`` for a plain single
    measurement with no suspect tracking.
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


def _environment(app, canvas=None, **extra):
    info = {"platform_plugin": app.platformName()}
    if canvas is not None:
        try:
            info["dpr"] = float(canvas._glw.devicePixelRatioF())
        except Exception:
            pass
    info.update(extra)
    return info


# --------------------------------------------------------------------------
# time-mainwindow : MainWindow product path, four view-switch scenarios
# (spec §1.1; was probes/probe_mainwindow_view_switch.py)
# --------------------------------------------------------------------------

def _time_mainwindow_make_frame(n_ch, n_points, fs):
    import numpy as np
    import pandas as pd

    t = np.arange(n_points, dtype=np.float64) / fs
    cols = {"Time": t}
    names = ["方向盘扭矩", "电机转速", "电机扭矩", "Rack Force", "Rack Travel",
             "电机相电流U", "电机相电流V", "转向角"]
    for i in range(n_ch):
        cols[names[i]] = 100.0 * np.sin(2.0 * np.pi * (0.20 + 0.03 * i) * t)
    return pd.DataFrame(cols), names[:n_ch]


class _Timers:
    def __init__(self):
        self.acc = {}

    def wrap(self, obj, name, label=None):
        label = label or name
        original = getattr(obj, name)

        def wrapped(*a, **k):
            t0 = time.perf_counter()
            try:
                return original(*a, **k)
            finally:
                self.acc[label] = self.acc.get(label, 0.0) + (
                    time.perf_counter() - t0) * 1000.0
        setattr(obj, name, wrapped)
        return original

    def reset(self):
        self.acc = {}


def _time_mainwindow_snapshot(canvas):
    q = canvas._quality
    inks = []
    for ck, _n, (_ax, line) in canvas._channel_lines.composite_items():
        pdi = getattr(line, "plot_data_item", None)
        try:
            if pdi is not None and not pdi.isVisible():
                continue
        except Exception:
            continue
        st = canvas._line_ink_state.get(ck)
        inks.append(round(st[0]) if st else None)
    status = q.quality_status()
    return {
        "rebuild_reason": getattr(canvas, "_last_full_rebuild_reason", None),
        "delta": dict(canvas._last_selection_delta or {}),
        "visible_inks": inks,
        "frame_ink": round(q._frame_native_ink_total()),
        "ink_allowed": q.ink_allowed, "ink_seeded": q.ink_seeded,
        "aa_on": q.aa_on,
        "raster_entries": len(canvas._dense_raster.entries),
        "ink_raster_admitted": len(canvas._ink_raster_admitted),
        "dot": f"{status.get('state')} / {status.get('tooltip')}",
        "path": status.get("render_path"),
    }


def _time_mainwindow_run_scenario(app, w, fid, names, *, plot_mode_a, plot_mode_b,
                                   hidden_in_a, label, timers):
    canvas = w.canvas_time
    print(f"\n==== 场景：{label} ====", flush=True)

    # --- View 1: 通道 0-2
    w.chart_stack.set_plot_mode(plot_mode_a)
    w.navigator.set_checked_channels([(fid, names[i]) for i in range(3)])
    if hidden_in_a:
        w.navigator.set_hidden_channels([(fid, names[1])])
    else:
        w.navigator.set_hidden_channels([])
    w.plot_time(); _settle(app, 400)
    xl = canvas.get_visible_xlim()
    span = xl[1] - xl[0]
    canvas.restore_visible_xlim((xl[0] + span * 0.4, xl[0] + span * 0.6))
    _settle(app, 400)
    w._capture_current_view()

    # --- View 2: 通道 3-4
    w._on_view_new(); _settle(app, 200)
    w.chart_stack.set_plot_mode(plot_mode_b)
    w.navigator.set_hidden_channels([])
    w.navigator.set_checked_channels([(fid, names[i]) for i in (3, 4)])
    w.plot_time(); _settle(app, 400)
    xl = canvas.get_visible_xlim()
    span = xl[1] - xl[0]
    canvas.restore_visible_xlim((xl[0], xl[0] + span * 0.1))
    _settle(app, 400)
    w._capture_current_view()

    runs = []
    for i in range(3):
        for target in (0, 1):
            timers.reset()
            t0 = time.perf_counter()
            w._switch_view(target)
            switch_ms = (time.perf_counter() - t0) * 1000.0
            # 切完立刻的状态（idle timer 还没到）
            snap_now = _time_mainwindow_snapshot(canvas)
            _settle(app, 350)  # 让 150ms idle timer 与 raster 定时器都落地
            snap_settled = _time_mainwindow_snapshot(canvas)
            r = {
                "target": target, "switch_ms": switch_ms,
                "timers": dict(timers.acc),
                "now": snap_now, "settled": snap_settled,
            }
            runs.append(r)
            tm = timers.acc
            print(
                f"  [{i}] -> View {target + 1}: 切换调用 {switch_ms:7.1f} ms | "
                f"build_data={tm.get('_build_time_plot_data', 0):5.1f} "
                f"delta={tm.get('try_apply_selection_delta', 0):5.1f} "
                f"plot_channels={tm.get('plot_channels', 0):6.1f} "
                f"restore_x={tm.get('restore_visible_xlim', 0):5.1f} "
                f"restore_y={tm.get('restore_visible_ylims', 0):5.1f} "
                f"apply_controls={tm.get('apply_controls_from_state', 0):5.1f} "
                f"project_controls={tm.get('_project_view_controls', 0):5.1f} "
                f"capture={tm.get('_capture_focused_view', 0):5.1f}",
                flush=True,
            )
            print(
                f"        路径: {snap_now['rebuild_reason'] if not snap_now['delta'].get('applied') else snap_now['delta'].get('reason')} | "
                f"ink(可见)={snap_now['visible_inks']} | 稳定后 aa_on={snap_settled['aa_on']} "
                f"ink_allowed={snap_settled['ink_allowed']} raster={snap_settled['raster_entries']} "
                f"收编={snap_settled['ink_raster_admitted']} | 点: {snap_settled['dot']}",
                flush=True,
            )
    # 收尾：删掉 View 2，回到 View 1，让下一场景干净开始
    w._switch_view(0); _settle(app, 200)
    w.view_manager.delete_view(1); _settle(app, 200)
    w.navigator.set_hidden_channels([])
    return runs


def cmd_time_mainwindow(_args):
    from mf4_analyzer.ui.main_window import MainWindow

    app = _qapp()
    w = MainWindow()
    w.resize(WIDTH, HEIGHT)
    w.show(); w.raise_(); w.activateWindow()
    exposed = _wait_window_exposed(app, w)
    print(f"platform={app.platformName()} exposed={exposed}", flush=True)

    df, names = _time_mainwindow_make_frame(8, 1_000_000, 20_000.0)
    w._register_file_data("probe.mf4", df, ["Time", *names],
                          {n: "Nm" for n in names})
    fid = next(iter(w.files))
    w._on_source_load_finished([fid])
    _settle(app, 300)

    timers = _Timers()
    timers.wrap(w, "_build_time_plot_data")
    timers.wrap(w.canvas_time, "try_apply_selection_delta")
    timers.wrap(w.canvas_time, "plot_channels")
    timers.wrap(w.canvas_time, "restore_visible_xlim")
    timers.wrap(w.canvas_time, "restore_visible_ylims")
    timers.wrap(w, "_project_view_controls")
    timers.wrap(w, "_capture_focused_view")
    timers.wrap(w._view_bridge, "apply_controls_from_state")

    scenarios = [
        dict(label="subplot ↔ subplot（全显）", plot_mode_a="subplot",
             plot_mode_b="subplot", hidden_in_a=False),
        dict(label="subplot ↔ subplot（View1 有隐藏通道）", plot_mode_a="subplot",
             plot_mode_b="subplot", hidden_in_a=True),
        dict(label="overlay ↔ overlay", plot_mode_a="overlay",
             plot_mode_b="overlay", hidden_in_a=False),
        dict(label="subplot ↔ overlay（两 View 布局不同）", plot_mode_a="subplot",
             plot_mode_b="overlay", hidden_in_a=False),
    ]
    scenarios_out = {}
    for sc in scenarios:
        scenarios_out[sc["label"]] = _time_mainwindow_run_scenario(
            app, w, fid, names, timers=timers, **sc)

    w.close(); app.processEvents()
    return {
        "command": "time-mainwindow",
        "environment": _environment(app, exposed=exposed),
        "scenarios": scenarios_out,
    }


# --------------------------------------------------------------------------
# time-canvas : canvas-level view-switch cost, two quality backends
# (spec §1.1/§1.2; was probes/probe_view_switch_aa.py)
# --------------------------------------------------------------------------

def _time_canvas_make_rows(names, *, n_points, fs, kind, tag):
    import numpy as np

    t = np.arange(int(n_points), dtype=np.float64) / float(fs)
    rows = []
    for i, name in enumerate(names):
        if kind == "smooth":
            sig = 100.0 * np.sin(2.0 * np.pi * (0.20 + 0.06 * i) * t)
        else:  # dense / 满幅振荡
            sig = 100.0 * np.sin(2.0 * np.pi * (2300.0 + 137.0 * i) * t)
            sig += 8.0 * np.sin(2.0 * np.pi * (0.7 + 0.1 * i) * t)
        rows.append((name, True, t, sig, COLORS[i % len(COLORS)], "Nm", tag))
    return rows


def _time_canvas_run_switch(app, canvas, viewport, rows, xlim, label, ctx_key):
    q = canvas._quality

    # --- 1: 全量重建（产品路径开头 disable_interactive_quality + clear）
    t0 = time.perf_counter()
    canvas.plot_channels(
        rows, mode="subplot", xlabel="Time (s)",
        defer_first_frame=True, render_context_key=ctx_key,
        full_rebuild_reason="view-switch-probe",
    )
    rebuild_ms = (time.perf_counter() - t0) * 1000.0

    # --- 2: 恢复 xlim（内部同步 flush 一次高精度刷新）
    t0 = time.perf_counter()
    canvas.restore_visible_xlim(xlim)
    restore_ms = (time.perf_counter() - t0) * 1000.0

    # --- 3: 切换后用户看到的第一帧
    first_frame_ms, s1 = _timed_repaint(canvas, viewport)

    # --- 4: dense-raster 重建（clear() 已把 entries 清空）。
    #     plot_channels 尾部 schedule_rebuild(delay_ms=0)，所以 0 延时定时器
    #     会在下一次 processEvents 里落地——把它一并算进这一段。
    t0 = time.perf_counter()
    app.processEvents()
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    raster_ms = (time.perf_counter() - t0) * 1000.0
    app.processEvents()
    raster_entries = len(canvas._dense_raster.entries)
    raster_frame_ms, s4 = _timed_repaint(canvas, viewport)

    # --- 5: 空闲计时器到点 -> ink 判定 + 打开向量 AA
    t0 = time.perf_counter()
    ink_total = q._frame_native_ink_total()
    ink_measure_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    q.try_enable_idle_quality()
    enable_ms = (time.perf_counter() - t0) * 1000.0
    aa_engaged = bool(q.aa_on)

    first_aa_ms, s2 = _timed_repaint(canvas, viewport)
    app.processEvents()
    tripped = q.aa_backstop_reason
    steady_reforced = False
    if not q.aa_on and aa_engaged:
        steady_reforced = True
        q._set_curves_antialias(True)
        q.aa_on = True
    steady_aa_ms, s3 = _timed_repaint(canvas, viewport)
    app.processEvents()

    status = q.quality_status()
    result = {
        "label": label,
        "rebuild_ms": rebuild_ms,
        "restore_xlim_ms": restore_ms,
        "first_frame_ms": first_frame_ms,
        "raster_flush_ms": raster_ms,
        "raster_entries": raster_entries,
        "raster_frame_ms": raster_frame_ms,
        "ink_measure_ms": ink_measure_ms,
        "frame_ink_dev_px": float(ink_total),
        "aa_enable_call_ms": enable_ms,
        "first_aa_frame_ms": first_aa_ms,
        "steady_aa_frame_ms": steady_aa_ms,
        "aa_engaged": aa_engaged,
        "render_path": status.get("render_path"),
        "quality_state": status.get("state"),
        "backstop": ([str(tripped[0]), float(tripped[1])] if tripped else None),
        "steady_reforced": steady_reforced,
        "suspect": {"first": s1, "raster_frame": s4,
                    "first_aa": s2, "steady": s3},
    }
    result["to_first_frame_ms"] = rebuild_ms + restore_ms + first_frame_ms
    result["to_settled_ms"] = (
        result["to_first_frame_ms"] + raster_ms + raster_frame_ms
        + enable_ms + first_aa_ms
    )
    print(
        f"{label:<26} rebuild={rebuild_ms:7.1f} restore={restore_ms:6.1f} "
        f"frame={first_frame_ms:6.1f} | raster_flush={raster_ms:7.1f}"
        f"({raster_entries}) rframe={raster_frame_ms:6.1f} | "
        f"aa_on={str(aa_engaged):<5} aa_enable={enable_ms:6.1f} "
        f"AA1={first_aa_ms:7.1f} AAn={steady_aa_ms:6.1f} | "
        f"首帧={result['to_first_frame_ms']:7.1f} 稳定={result['to_settled_ms']:7.1f} ms "
        f"[{status.get('render_path') or status.get('state')}]"
        + (f"  BACKSTOP={tripped[0]}" if tripped else ""),
        flush=True,
    )
    return result


def cmd_time_canvas(_args):
    import numpy as np

    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    app = _qapp()
    canvas = TimeDomainCanvasPG()
    canvas.resize(WIDTH, HEIGHT)
    canvas.show()
    canvas.raise_()
    canvas.activateWindow()
    exposed = _wait_window_exposed(app, canvas)
    viewport = canvas._glw.viewport()
    print(
        f"platform={app.platformName()} dpr={canvas._glw.devicePixelRatioF()} "
        f"exposed={exposed}",
        flush=True,
    )

    fixtures = {
        # 低 ink：走原生向量 AA
        "smoothA": _time_canvas_make_rows(
            ["方向盘扭矩", "电机转速", "电机扭矩"],
            n_points=200_000, fs=1000.0, kind="smooth", tag="fileA"),
        "smoothB": _time_canvas_make_rows(
            ["Rack Force", "Rack Travel"],
            n_points=400_000, fs=2000.0, kind="smooth", tag="fileB"),
        # 满幅振荡：ink 超预算，走 dense-raster
        "denseA": _time_canvas_make_rows(
            ["电机相电流 U", "电机相电流 V", "电机相电流 W"],
            n_points=1_000_000, fs=20_000.0, kind="dense", tag="fileC"),
        "denseB": _time_canvas_make_rows(
            ["转矩传感器原始", "扭矩纹波"],
            n_points=1_000_000, fs=20_000.0, kind="dense", tag="fileD"),
    }

    def xwin(rows, lo_frac, hi_frac):
        t = rows[0][2]
        span = float(t[-1] - t[0])
        return (float(t[0] + span * lo_frac), float(t[0] + span * hi_frac))

    plans = [
        ("向量AA", "smoothA", "smoothB", 0.40, 0.60, 0.0, 0.10),
        ("光栅",   "denseA",  "denseB",  0.40, 0.60, 0.0, 0.10),
    ]

    all_runs = {}
    for tag, ka, kb, alo, ahi, blo, bhi in plans:
        print(f"\n== {tag} 路径：{ka} <-> {kb} ==", flush=True)
        runs = []
        for i in range(3):
            runs.append(_time_canvas_run_switch(
                app, canvas, viewport, fixtures[ka],
                xwin(fixtures[ka], alo, ahi), f"[{i}] -> {ka}", ("probe", ka)))
            runs.append(_time_canvas_run_switch(
                app, canvas, viewport, fixtures[kb],
                xwin(fixtures[kb], blo, bhi), f"[{i}] -> {kb}", ("probe", kb)))
        all_runs[tag] = runs
        warm = runs[2:]
        keys = ("rebuild_ms", "restore_xlim_ms", "first_frame_ms",
                "raster_flush_ms", "raster_frame_ms", "ink_measure_ms",
                "aa_enable_call_ms", "first_aa_frame_ms", "steady_aa_frame_ms",
                "to_first_frame_ms", "to_settled_ms")
        print(f"-- {tag} 稳定段中位数（丢首轮 2 次） --", flush=True)
        for k in keys:
            print(f"   {k:<24} {float(np.median([r[k] for r in warm])):8.1f} ms",
                  flush=True)

    canvas.close()
    app.processEvents()

    return {
        "command": "time-canvas",
        "environment": _environment(app, canvas, exposed=exposed),
        "runs": all_runs,
    }


# --------------------------------------------------------------------------
# ylim-order : A/B, product X-then-Y order vs Y-then-X-flush order
# (spec §1.2; was probes/probe_view_switch_ylim_order.py)
# --------------------------------------------------------------------------

def _ylim_order_make_rows(n, *, n_points, fs, tag):
    import numpy as np

    t = np.arange(int(n_points), dtype=np.float64) / float(fs)
    return [
        (f"CH{i}", True, t,
         100.0 * np.sin(2.0 * np.pi * (0.20 + 0.03 * i) * t),
         COLORS[i % len(COLORS)], "Nm", tag)
        for i in range(n)
    ]


def _ylim_order_one_switch(app, canvas, viewport, rows, xlim, ylims, *,
                            ylim_first, ctx):
    t0 = time.perf_counter()
    canvas.plot_channels(rows, mode="subplot", xlabel="Time (s)",
                         defer_first_frame=True, render_context_key=ctx,
                         full_rebuild_reason="probe")
    if ylim_first:
        canvas.restore_visible_ylims(ylims)
        canvas.restore_visible_xlim(xlim)
    else:
        canvas.restore_visible_xlim(xlim)
        canvas.restore_visible_ylims(ylims)
    restore_ms = (time.perf_counter() - t0) * 1000.0

    frame_ms, _s = _timed_repaint(canvas, viewport, retries=0, floor_ms=0.0)

    t0 = time.perf_counter()
    app.processEvents()                       # 0 延时 raster rebuild 定时器
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    raster_ms = (time.perf_counter() - t0) * 1000.0
    app.processEvents()
    raster_frame_ms, _s = _timed_repaint(canvas, viewport, retries=0, floor_ms=0.0)

    q = canvas._quality
    t0 = time.perf_counter()
    q.try_enable_idle_quality()
    enable_ms = (time.perf_counter() - t0) * 1000.0
    aa_frame_ms, _s = _timed_repaint(canvas, viewport, retries=0, floor_ms=0.0)
    app.processEvents()

    inks = []
    elig = 0
    for ck, _n, _p in canvas._channel_lines.composite_items():
        state = canvas._line_ink_state.get(ck)
        inks.append(round(state[0]) if state else None)
        if canvas._raster_backend_eligible(ck):
            elig += 1
    st = q.quality_status()
    return {
        "restore_ms": restore_ms,
        "frame_ms": frame_ms,
        "raster_ms": raster_ms,
        "raster_frame_ms": raster_frame_ms,
        "aa_enable_ms": enable_ms,
        "aa_frame_ms": aa_frame_ms,
        "total_ms": (restore_ms + frame_ms + raster_ms + raster_frame_ms
                     + enable_ms + aa_frame_ms),
        "inks": inks,
        "raster_eligible": elig,
        "raster_entries": len(canvas._dense_raster.entries),
        "aa_on": bool(q.aa_on),
        "path": st.get("render_path"),
        "state": st.get("state"),
    }


def cmd_ylim_order(args):
    import numpy as np

    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    n_ch = int(getattr(args, "n_channels", 8) or 8)
    app = _qapp()
    canvas = TimeDomainCanvasPG()
    canvas.resize(WIDTH, HEIGHT)
    canvas.show(); canvas.raise_(); canvas.activateWindow()
    exposed = _wait_window_exposed(app, canvas)
    viewport = canvas._glw.viewport()
    print(f"platform={app.platformName()} dpr={canvas._glw.devicePixelRatioF()} "
          f"exposed={exposed} n_ch={n_ch}", flush=True)

    a = _ylim_order_make_rows(n_ch, n_points=1_000_000, fs=20_000.0, tag="fileA")
    b = _ylim_order_make_rows(max(2, n_ch - 3), n_points=600_000, fs=20_000.0,
                               tag="fileB")

    def xwin(rows, lo, hi):
        t = rows[0][2]
        span = float(t[-1] - t[0])
        return (float(t[0] + span * lo), float(t[0] + span * hi))

    xa = xwin(a, 0.40, 0.60)
    xb = xwin(b, 0.00, 0.10)

    # ylims 用产品会存下来的形状：canvas 的 view-state key -> (lo, hi)
    def capture_ylims(rows, xlim, ctx):
        canvas.plot_channels(rows, mode="subplot", xlabel="Time (s)",
                             defer_first_frame=False, render_context_key=ctx)
        canvas.restore_visible_xlim(xlim)
        canvas._flush_pending_refresh()
        app.processEvents()
        return canvas.get_visible_ylims()

    ya = capture_ylims(a, xa, ("cap", "A"))
    yb = capture_ylims(b, xb, ("cap", "B"))

    orders_out = {}
    for ylim_first in (False, True):
        tag = "先 Y 后 flush（对照/修复）" if ylim_first else "当前产品顺序"
        runs = []
        for i in range(3):
            runs.append(_ylim_order_one_switch(app, canvas, viewport, a, xa, ya,
                                               ylim_first=ylim_first, ctx=("p", "A")))
            runs.append(_ylim_order_one_switch(app, canvas, viewport, b, xb, yb,
                                               ylim_first=ylim_first, ctx=("p", "B")))
        warm = runs[2:]
        print(f"\n== {tag} ==", flush=True)
        for r in runs:
            print(f"   restore={r['restore_ms']:7.1f} frame={r['frame_ms']:6.1f} "
                  f"raster={r['raster_ms']:7.1f}({r['raster_entries']}) "
                  f"rframe={r['raster_frame_ms']:6.1f} aa_on={str(r['aa_on']):<5} "
                  f"aa_frame={r['aa_frame_ms']:6.1f} 合计={r['total_ms']:7.1f} "
                  f"| 光栅收编={r['raster_eligible']} ink[0..2]={r['inks'][:3]} "
                  f"[{r['path'] or r['state']}]", flush=True)
        median_total = float(np.median([r["total_ms"] for r in warm]))
        median_raster = float(np.median([r["raster_ms"] for r in warm]))
        print(f"   中位合计 {median_total:7.1f} ms"
              f"   光栅重建中位 {median_raster:6.1f} ms"
              f"   光栅收编 {warm[-1]['raster_eligible']}/{n_ch}", flush=True)
        orders_out[tag] = {
            "ylim_first": ylim_first, "runs": runs,
            "median_total_ms": median_total, "median_raster_ms": median_raster,
            "raster_eligible_last": warm[-1]["raster_eligible"],
        }

    canvas.close()
    app.processEvents()
    return {
        "command": "ylim-order",
        "environment": _environment(app, canvas, exposed=exposed, n_channels=n_ch),
        "orders": orders_out,
    }


# --------------------------------------------------------------------------
# stale-ink : the three consequences of measuring ink before Y is restored
# (spec §1.2; was probes/probe_stale_ink_effects.py). Also reproduces
# headlessly -- this is a logic defect, not a paint-cost measurement.
# --------------------------------------------------------------------------

def _stale_ink_dump(canvas, tag):
    parts = []
    detail = []
    for ck, n, (_ax, line) in canvas._channel_lines.composite_items():
        xd, _ = line.plot_data_item.getData()
        st = canvas._line_ink_state.get(ck)
        pts = 0 if xd is None else len(xd)
        ink = round(st[0]) if st else None
        over_budget = st[1] if st else None
        raster_admitted = canvas._raster_backend_eligible(ck)
        parts.append(f"{n}: 绘点={pts} ink={ink} 超预算={over_budget} "
                     f"光栅收编={raster_admitted}")
        detail.append({
            "name": str(n), "points": pts, "ink": ink,
            "over_budget": over_budget, "raster_admitted": bool(raster_admitted),
        })
    q = canvas._quality
    aa_allowed = q._idle_aa_density_ok()
    state = q.quality_status()["state"]
    print(f"{tag:<26} " + " | ".join(parts)
          + f" | AA判定={aa_allowed} 点={state}")
    return {"tag": tag, "channels": detail, "aa_allowed": aa_allowed, "state": state}


def cmd_stale_ink(_args):
    import numpy as np

    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    app = _qapp()
    c = TimeDomainCanvasPG(); c.resize(WIDTH, HEIGHT); c.show(); c.raise_()
    exposed = _wait_window_exposed(app, c)
    t = np.arange(1_000_000) / 20000.0
    rows = [(f"CH{i}", True, t, 100 * np.sin(2 * np.pi * (0.5 + 0.1 * i) * t),
             "#1769e0", "Nm", "fileA") for i in range(2)]

    print(f"platform={app.platformName()} dpr={c._glw.devicePixelRatioF()} "
          f"exposed={exposed}")
    c.plot_channels(rows, mode="overlay", defer_first_frame=False,
                    render_context_key=("cap", "A"))
    c.restore_visible_xlim((10.0, 25.0)); c._flush_pending_refresh(); app.processEvents()
    ylims = c.get_visible_ylims()
    snapshots = [_stale_ink_dump(c, "首次进 View（bind envelope）")]

    c.plot_channels(rows, mode="overlay", defer_first_frame=True,
                    render_context_key=("p", "A"))
    c.restore_visible_xlim((10.0, 25.0))
    c.restore_visible_ylims(ylims)
    app.processEvents()
    snapshots.append(_stale_ink_dump(c, "回切后（当前顺序）"))
    for _ in range(10):
        app.processEvents(); time.sleep(0.05)
    snapshots.append(_stale_ink_dump(c, "回切后再空转 500 ms"))
    c._last_range_key.clear(); c._flush_pending_refresh(); app.processEvents()
    snapshots.append(_stale_ink_dump(c, "强制按真实 Y 重刷（=用户动一下）"))
    c.close(); app.processEvents()

    return {
        "command": "stale-ink",
        "environment": _environment(app, c, exposed=exposed),
        "snapshots": snapshots,
    }


# --------------------------------------------------------------------------
# analysis-frames : PgLineCanvas spectrum-row ink vs AA frame + PgFrfCanvas
# AA/non-AA frames across bin counts (spec §1.4; was
# probes/probe_analysis_aa_frames.py)
# --------------------------------------------------------------------------

def _analysis_frames_warm(app, widget):
    widget.show(); widget.raise_(); widget.activateWindow()
    for _ in range(80):
        app.processEvents(); time.sleep(0.01)


def _analysis_frames_frame_ms(canvas, n=3):
    import numpy as np

    ms = []
    for _ in range(n):
        t0 = time.perf_counter()
        canvas._glw.scene().update(); canvas._glw.viewport().repaint()
        ms.append((time.perf_counter() - t0) * 1000.0)
    return float(np.median(ms))


def _analysis_frames_spectrum_cases(app):
    import numpy as np

    from mf4_analyzer.render_profile import envelope_ink_dev_px
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_OFF, _INK_AA_ON

    c = PgLineCanvas(); c.resize(1400, 900); _analysis_frames_warm(app, c)
    rng = np.random.default_rng(7)
    freq = np.linspace(0, 2000, 65536); t = np.linspace(0, 10, 40000)
    noise = np.abs(rng.standard_normal(65536))
    peak = 200.0 * np.exp(-((freq - 300.0) ** 2) / 40.0)
    dpr = c._glw.devicePixelRatioF()
    print(f"== PgLineCanvas 谱行：同 4095 绘点，只改竖直墨迹 "
          f"(band ON={_INK_AA_ON/1000:.0f}k OFF={_INK_AA_OFF/1000:.0f}k) ==")

    cases_out = []

    def case(msg, gain, ncurves=3):
        entries = [{
            "label": f"ch{i}", "color": "#1769e0", "freq": freq,
            "amp": noise * (1 + 0.1 * i) + peak * gain,
            "time": t, "signal": 40 * np.sin(2 * np.pi * (3 + i) * t),
        } for i in range(ncurves)]
        c._aa_on = True
        c.plot_spectra(entries, xlim=(0, 2000), amp_label="A", title="t")
        app.processEvents()
        ylo, yhi = c._plot_amp.vb.viewRange()[1]; yspan = abs(yhi - ylo)
        h = c._plot_amp.vb.sceneBoundingRect().height()
        ink = sum(envelope_ink_dev_px(cv.getData()[1], y_span=yspan,
                                      row_height_px=h, dpr=dpr)
                  for cv in c._amp_curves)
        pts = sum(len(cv.getData()[0]) for cv in c._amp_curves)
        aa = all(bool(cv.opts.get("antialias")) for cv in c._amp_curves)
        ms = _analysis_frames_frame_ms(c)
        verdict = ("ALLOW" if ink <= _INK_AA_ON else
                   ("BLOCK" if ink > _INK_AA_OFF else "band"))
        print(f"  {msg:<22} 曲线={ncurves} 绘点={pts:5d} 点数闸门放行AA={aa!s:<5} "
              f"yspan={yspan:8.2f} ink={ink/1000:8.1f}k 时域带={verdict:<5} "
              f"帧中位={ms:8.1f} ms")
        cases_out.append({
            "label": msg, "n_curves": ncurves, "pts": pts,
            "point_gate_allows_aa": aa, "yspan": float(yspan), "ink": float(ink),
            "band_verdict": verdict, "frame_ms": ms,
        })

    case("纯噪声底", 0.0)
    case("峰/底=10", 0.05)
    case("峰/底=40", 0.2)
    case("峰/底=200", 1.0)
    case("峰/底=200 · 1 条", 1.0, 1)
    case("纯噪声底 · 1 条", 0.0, 1)
    case("纯噪声底 · 6 条", 0.0, 6)
    c._aa_on = False
    entries = [{"label": "x", "color": "#1769e0", "freq": freq, "amp": noise,
                "time": t, "signal": np.sin(t)} for _ in range(3)]
    c.plot_spectra(entries, xlim=(0, 2000), amp_label="A", title="t")
    app.processEvents()
    control_ms = _analysis_frames_frame_ms(c)
    print(f"  {'AA 关 · 纯噪声底 (对照)':<22} 帧中位={control_ms:8.1f} ms")
    cases_out.append({"label": "AA 关 · 纯噪声底 (对照)", "frame_ms": control_ms,
                      "aa_off_control": True})
    c.close(); app.processEvents()
    return {"ink_aa_on": float(_INK_AA_ON), "ink_aa_off": float(_INK_AA_OFF),
            "cases": cases_out}


def _analysis_frames_frf_cases(app):
    from types import SimpleNamespace

    import numpy as np

    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    c = PgFrfCanvas(); c.resize(1400, 900); _analysis_frames_warm(app, c)
    rng = np.random.default_rng(3)

    def res(nbins, noisy):
        f = np.linspace(0, 1000, nbins)
        H = 1.0 / (1 - (f / 120) ** 2 + 1j * 0.05 * (f / 120))
        if noisy:
            H = H * (1 + 0.6 * rng.standard_normal(nbins)) \
                * np.exp(1j * rng.standard_normal(nbins) * 1.5)
        coh = np.clip(0.9 - 0.5 * rng.random(nbins) * noisy, 0, 1)
        return SimpleNamespace(
            frequencies=f, transfer=H.astype(complex), coherence=coh,
            effective=SimpleNamespace(fs=2000.0, df=f[1] - f[0], segments=8),
            warnings=(),
        )

    print("== PgFrfCanvas：AA 帧 vs 非 AA 帧 ==")
    cases_out = []
    for nbins, noisy, label in ((2049, 0, "2k bins 干净"),
                                (2049, 1, "2k bins 噪声相位/相干"),
                                (8193, 1, "8k bins 噪声"),
                                (32769, 1, "32k bins 噪声")):
        c.set_result(res(nbins, noisy), {"frequency_scale": "linear"}, {})
        app.processEvents()
        aa_ms = _analysis_frames_frame_ms(c)
        c.disable_interactive_quality(); app.processEvents()
        off_ms = _analysis_frames_frame_ms(c)
        c._enable_idle_quality()
        print(f"  {label:<20} AA帧中位={aa_ms:8.1f} ms   非AA帧={off_ms:7.1f} ms")
        cases_out.append({
            "label": label, "n_bins": nbins, "noisy": bool(noisy),
            "aa_frame_ms": aa_ms, "non_aa_frame_ms": off_ms,
        })
    c.close(); app.processEvents()
    return {"cases": cases_out}


def cmd_analysis_frames(_args):
    app = _qapp()
    print(f"platform={app.platformName()}")
    spectrum = _analysis_frames_spectrum_cases(app)
    frf = _analysis_frames_frf_cases(app)
    return {
        "command": "analysis-frames",
        "environment": _environment(app),
        "spectrum": spectrum,
        "frf": frf,
    }


# --------------------------------------------------------------------------
# analysis-calibrate : real-machine calibration of the analysis-canvas ink
# bands (spec §5 rows "谱行 _SPECTRUM_INK_AA_ON/OFF", "FRF 三行 ink 带",
# "预览行 ink 带"; plan Task 4).
#
# ``analysis-frames`` above is the *baseline* reproduction of spec §1.4 and is
# deliberately left untouched. This subcommand is the calibration sweep: three
# groups (spectrum row / time-preview row / FRF three rows), each swept across
# configurations that vary vertical ink while everything else stays fixed,
# each configuration measured over >=2 passes, and each group reduced to a
# least-squares ink -> AA-frame-ms line. The band then falls out of the fit:
#
#     OFF = ink where the fit crosses _BACKSTOP_STEADY_AA_MS (250 ms)
#     ON  = OFF * 2/3      (same ratio as the time-domain 200k/300k band)
#
# both rounded to 5k dev-px. AA is forced on/off explicitly per measurement
# rather than left to the product's point-count gate, so the numbers describe
# canvas physics, not today's gate.
#
# Real machine only -- these are Cocoa paint timings.
# --------------------------------------------------------------------------

_CALIB_TARGET_MS = 250.0          # = quality._BACKSTOP_STEADY_AA_MS
_CALIB_ON_RATIO = 2.0 / 3.0       # = _INK_AA_ON / _INK_AA_OFF (200k / 300k)
_CALIB_UNSTABLE_SPREAD = 0.30     # (max-min)/median across passes
_CALIB_MIN_PASSES = 2
_CALIB_MAX_PASSES = 4
# Points slower than this are outside the region the band has to get right;
# a second fit restricted to them exposes a two-regime curve (spec §1.4's
# 7 baseline points already hint at one: ~1.4 ms/k below 212k, ~3.3 above).
_CALIB_NEAR_TARGET_MS = 600.0


def _calib_loadavg():
    import os

    try:
        return [round(float(v), 2) for v in os.getloadavg()]
    except (OSError, AttributeError):
        return None


def _calib_frames(canvas, viewport, n=3):
    """Median of ``n`` forced, non-coalesced repaints; True if any looked missed."""
    import numpy as np

    values, suspect = [], False
    for _ in range(n):
        ms, miss = _timed_repaint(canvas, viewport, retries=1, floor_ms=0.5)
        values.append(ms)
        suspect = suspect or miss
    return float(np.median(values)), suspect


def _calib_spread(values):
    import numpy as np

    arr = [float(v) for v in values]
    med = float(np.median(arr))
    if med <= 0.0:
        return med, 0.0
    return med, (max(arr) - min(arr)) / med


def _calib_case(label, run_pass, **meta):
    """Run ``run_pass`` >=2 times, re-running while AA-frame spread is wide.

    Another agent may be running an offscreen pytest suite on this machine, so
    a single pass is not trustworthy: passes are repeated up to
    ``_CALIB_MAX_PASSES`` while the AA-frame spread stays above 30%, and the
    case is flagged ``unstable`` if it never settles.
    """
    import numpy as np

    passes = []
    while True:
        passes.append(run_pass())
        if len(passes) < _CALIB_MIN_PASSES:
            continue
        _med, spread = _calib_spread([p["aa_frame_ms"] for p in passes])
        if spread <= _CALIB_UNSTABLE_SPREAD or len(passes) >= _CALIB_MAX_PASSES:
            break
    aa_ms, spread = _calib_spread([p["aa_frame_ms"] for p in passes])
    off_ms = float(np.median([p["off_frame_ms"] for p in passes]))
    ink = float(np.median([p["ink"] for p in passes]))
    out = {
        "label": label,
        "ink": ink,
        "aa_frame_ms": aa_ms,
        "off_frame_ms": off_ms,
        "aa_spread": spread,
        "unstable": spread > _CALIB_UNSTABLE_SPREAD,
        "n_passes": len(passes),
        "suspect_frame": any(p.get("suspect") for p in passes),
        "loadavg": _calib_loadavg(),
        "passes": passes,
    }
    out.update(meta)
    flag = " UNSTABLE" if out["unstable"] else ""
    print(f"  {label:<28} ink={ink/1000:8.1f}k  AA帧={aa_ms:8.1f} ms  "
          f"非AA={off_ms:7.1f} ms  passes={len(passes)} "
          f"spread={spread*100:4.0f}%{flag}", flush=True)
    return out


def _calib_fit(cases, label, *, max_ms=None, min_ms=None, where=None):
    """Least-squares ms = slope*ink + intercept over the given cases.

    ``max_ms`` / ``min_ms`` / ``where`` restrict the sample: the band is read
    off the whole set and off the near-target segment, while per-shape and
    per-regime subsets are fitted separately as *diagnostics*. A single line
    is only honest if those subsets agree — they do not for the spectrum row
    (superlinear above ~350k ink) nor for FRF (the low-coherence split costs
    far more per unit ink than a noisy phase), which is why the band is taken
    from the most conservative candidate rather than from one global fit.
    """
    import numpy as np

    pts = [c for c in cases
           if (max_ms is None or c["aa_frame_ms"] <= max_ms)
           and (min_ms is None or c["aa_frame_ms"] > min_ms)
           and (where is None or where(c))]
    if len(pts) < 2:
        return None
    xs = np.array([c["ink"] for c in pts], dtype=float)
    ys = np.array([c["aa_frame_ms"] for c in pts], dtype=float)
    if float(xs.max() - xs.min()) < 0.05 * float(xs.max()):
        # Degenerate: this subset carries essentially no ink information, so
        # any slope through it is an artefact of float noise. This is exactly
        # the FRF "clean" family — same 2.5k ink at 1k/2k/4k bins while the
        # frame still doubles, i.e. cost driven by point count, not ink. That
        # is a genuine finding (it is why the product gate keeps a point-count
        # leg AND'ed with the ink leg), but it is not a line.
        return None
    design = np.vstack([xs, np.ones_like(xs)]).T
    (slope, intercept), *_ = np.linalg.lstsq(design, ys, rcond=None)
    pred = slope * xs + intercept
    ss_res = float(np.sum((ys - pred) ** 2))
    ss_tot = float(np.sum((ys - ys.mean()) ** 2))
    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
    ink_at_target = ((_CALIB_TARGET_MS - intercept) / slope) if slope > 0 else None
    return {
        "label": label,
        "n_points": len(pts),
        "max_ms_filter": max_ms,
        "min_ms_filter": min_ms,
        "ink_range": [float(xs.min()), float(xs.max())],
        "slope_ms_per_k_dev_px": float(slope) * 1000.0,
        "intercept_ms": float(intercept),
        "r2": float(r2),
        "ink_at_target_ms": (float(ink_at_target)
                             if ink_at_target is not None else None),
        "unstable_points": sum(1 for c in pts if c["unstable"]),
    }


def _calib_round5k(value):
    return int(round(float(value) / 5000.0) * 5000)


def _calib_band(fits):
    """Pick the conservative (smallest) OFF across the supplied fits."""
    usable = [f for f in fits
              if f and f.get("ink_at_target_ms") and f["ink_at_target_ms"] > 0]
    if not usable:
        return None
    chosen = min(usable, key=lambda f: f["ink_at_target_ms"])
    off = _calib_round5k(chosen["ink_at_target_ms"])
    on = _calib_round5k(off * _CALIB_ON_RATIO)
    return {
        "chosen_fit": chosen["label"],
        "ink_at_target_ms_raw": chosen["ink_at_target_ms"],
        "off": off,
        "on": on,
        "target_ms": _CALIB_TARGET_MS,
    }


def _calib_report_fits(title, fits, band, diagnostics=()):
    def line(fit):
        print(f"   {fit['label']:<26} n={fit['n_points']:<2} "
              f"斜率={fit['slope_ms_per_k_dev_px']:7.3f} ms/k·dev-px  "
              f"截距={fit['intercept_ms']:8.1f} ms  R²={fit['r2']:.4f}  "
              f"250ms@ink={((fit['ink_at_target_ms'] or 0) / 1000):8.1f}k",
              flush=True)

    print(f"-- {title} 拟合（定带用）--")
    for fit in fits:
        if fit is not None:
            line(fit)
    if band:
        print(f"   => 推荐 OFF={band['off']/1000:.0f}k  ON={band['on']/1000:.0f}k "
              f"(取自 {band['chosen_fit']}，规则=候选中最保守/最小 OFF)",
              flush=True)
    usable_diag = [d for d in diagnostics if d is not None]
    if usable_diag:
        print(f"-- {title} 分段诊断（不参与定带，用于判断单线是否成立）--")
        for fit in usable_diag:
            line(fit)
        slopes = [d["slope_ms_per_k_dev_px"] for d in usable_diag
                  if d["slope_ms_per_k_dev_px"] > 0]
        if len(slopes) >= 2:
            print(f"   分段斜率跨度 {min(slopes):.3f} → {max(slopes):.3f} "
                  f"({max(slopes)/min(slopes):.2f}×)"
                  f"{'  ← 单条直线不成立' if max(slopes)/min(slopes) > 1.5 else ''}",
                  flush=True)
    print(flush=True)


def _calib_open(canvas_cls, app, *, width=1400, height=900):
    canvas = canvas_cls()
    canvas.resize(width, height)
    canvas.show(); canvas.raise_(); canvas.activateWindow()
    exposed = _wait_window_exposed(app, canvas)
    _settle(app, 400)
    return canvas, canvas._glw.viewport(), exposed


def _calib_row_geometry(view_box, app):
    """``(y_span, row_height_px)`` for one plot row, after an autorange flush.

    ``enableAutoRange`` is lazy (spec §3.4): reading ``viewRange()`` right
    after a rebuild can still hand back the *previous* picture's Y window, so
    the ink would be computed against the wrong span. Flush it first.
    """
    try:
        view_box.updateAutoRange()
    except (AttributeError, RuntimeError, TypeError):
        pass
    app.processEvents()
    lo, hi = view_box.viewRange()[1]
    return abs(float(hi) - float(lo)), float(view_box.sceneBoundingRect().height())


# --- group 1: spectrum row -------------------------------------------------
# Fixed 3 curves / ~1365 drawn points each (peak-hold output), only the
# peak-to-floor ratio varies -> only the vertical ink varies. Same synthetic
# construction as _analysis_frames_spectrum_cases so the points line up with
# the spec §1.4 baseline table.
_CALIB_SPECTRUM_RATIOS = (None, 50.0, 20.0, 10.0, 5.0, 2.0, 1.0)
_CALIB_SPECTRUM_PEAK = 200.0


def _calib_spectrum(app):
    import numpy as np

    from mf4_analyzer.render_profile import envelope_ink_dev_px
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    canvas, viewport, exposed = _calib_open(PgLineCanvas, app)
    dpr = float(canvas._glw.devicePixelRatioF())
    rng = np.random.default_rng(7)
    freq = np.linspace(0.0, 2000.0, 65536)
    t = np.linspace(0.0, 10.0, 40000)
    noise = np.abs(rng.standard_normal(65536))
    peak = _CALIB_SPECTRUM_PEAK * np.exp(-((freq - 300.0) ** 2) / 40.0)
    n_curves = 3

    print(f"== 组 1 谱行：3 曲线 / 绘点固定，只改峰底比 (dpr={dpr}) ==", flush=True)

    def make_pass(gain):
        def run():
            entries = [{
                "label": f"电机转速 {i}", "color": COLORS[i % len(COLORS)],
                "freq": freq, "amp": noise * (1 + 0.1 * i) + peak * gain,
                "time": t, "signal": 40.0 * np.sin(2 * np.pi * (3 + i) * t),
            } for i in range(n_curves)]
            canvas._aa_on = True
            canvas.plot_spectra(entries, xlim=(0.0, 2000.0),
                                amp_label="Amplitude", title="标定")
            app.processEvents()
            _settle(app, 80)
            y_span, row_h = _calib_row_geometry(canvas._plot_amp.vb, app)
            ink = sum(envelope_ink_dev_px(cv.getData()[1], y_span=y_span,
                                          row_height_px=row_h, dpr=dpr)
                      for cv in canvas._amp_curves)
            pts = sum(len(cv.getData()[0]) for cv in canvas._amp_curves)
            point_gate = all(bool(cv.opts.get("antialias"))
                             for cv in canvas._amp_curves)
            # The preview row below is held AA-off throughout (its own point
            # gate blocks it at 3 x 40k sources anyway), so it contributes a
            # constant, non-AA cost that the fit's intercept absorbs.
            for cv in canvas._time_curves:
                canvas._set_curve_aa(cv, False)
            for cv in canvas._amp_curves:
                canvas._set_curve_aa(cv, True)
            app.processEvents()
            aa_ms, aa_miss = _calib_frames(canvas, viewport)
            for cv in canvas._amp_curves:
                canvas._set_curve_aa(cv, False)
            app.processEvents()
            off_ms, off_miss = _calib_frames(canvas, viewport)
            return {"ink": float(ink), "aa_frame_ms": aa_ms,
                    "off_frame_ms": off_ms, "drawn_points": int(pts),
                    "y_span": float(y_span), "row_height_px": float(row_h),
                    "point_gate_allows_aa": bool(point_gate),
                    "suspect": bool(aa_miss or off_miss)}
        return run

    cases = []
    for ratio in _CALIB_SPECTRUM_RATIOS:
        if ratio is None:
            gain, label = 0.0, "纯噪声底 (无峰)"
        else:
            gain, label = ratio / _CALIB_SPECTRUM_PEAK, f"峰/底={ratio:g}"
        cases.append(_calib_case(label, make_pass(gain),
                                 peak_to_floor=ratio, gain=gain,
                                 n_curves=n_curves))

    canvas.close(); app.processEvents()
    fits = [_calib_fit(cases, "全部点"),
            _calib_fit(cases, f"≤{_CALIB_NEAR_TARGET_MS:.0f}ms 近目标段",
                       max_ms=_CALIB_NEAR_TARGET_MS)]
    diagnostics = [_calib_fit(cases, f">{_CALIB_NEAR_TARGET_MS:.0f}ms 高墨段",
                              min_ms=_CALIB_NEAR_TARGET_MS)]
    band = _calib_band(fits)
    _calib_report_fits("组 1 谱行", fits, band, diagnostics)
    return {"exposed": exposed, "dpr": dpr, "n_curves": n_curves,
            "cases": cases, "fits": [f for f in fits if f],
            "diagnostic_fits": [f for f in diagnostics if f], "band": band}


# --- group 2: time-preview row --------------------------------------------
# The preview row is what plot_spectra's entries' time/signal build; measured
# here through plot_time_preview(clear_spectrum=True) so the spectrum row
# above is empty and the frame cost is the preview row's alone.
_CALIB_PREVIEW_FREQS = (3.0, 5.0, 7.0, 11.0)
_CALIB_PREVIEW_AMPS = (40.0, 25.0, 60.0, 15.0)
_CALIB_PREVIEW_POINTS = 40_000


def _calib_preview(app):
    import numpy as np

    from mf4_analyzer.render_profile import envelope_ink_dev_px
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_OFF, _INK_AA_ON

    canvas, viewport, exposed = _calib_open(PgLineCanvas, app)
    dpr = float(canvas._glw.devicePixelRatioF())
    t = np.linspace(0.0, 10.0, _CALIB_PREVIEW_POINTS)

    print(f"== 组 2 时域预览行：2/3/4 条包络 × Y(默认 / 拉窄到填满) "
          f"(时域带 ON={_INK_AA_ON/1000:.0f}k OFF={_INK_AA_OFF/1000:.0f}k) ==",
          flush=True)

    def make_pass(n_curves, y_mode):
        def run():
            entries = [{
                "label": f"电机转速 {i}", "color": COLORS[i % len(COLORS)],
                "time": t,
                "signal": _CALIB_PREVIEW_AMPS[i] * np.sin(
                    2 * np.pi * _CALIB_PREVIEW_FREQS[i] * t),
            } for i in range(n_curves)]
            canvas._aa_on = True
            canvas.plot_time_preview(entries, title="时域预览",
                                     clear_spectrum=True)
            app.processEvents()
            _settle(app, 80)
            pairs = canvas._time_axis_pairs()
            curves = list(canvas._time_curves)
            if y_mode == "filled":
                # Narrow each row's own Y window onto its trace (5% inside the
                # data extents) so the envelope fills the row edge to edge.
                for idx, curve in enumerate(curves):
                    if idx >= len(pairs):
                        break
                    vb = pairs[idx][0]
                    _xd, yd = curve.getData()
                    arr = np.asarray(yd, dtype=float)
                    arr = arr[np.isfinite(arr)]
                    if arr.size < 2:
                        continue
                    lo, hi = float(arr.min()), float(arr.max())
                    mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0 * 0.95
                    if half <= 0:
                        continue
                    try:
                        vb.enableAutoRange(axis="y", enable=False)
                        vb.setYRange(mid - half, mid + half, padding=0)
                    except (AttributeError, RuntimeError, TypeError):
                        continue
                app.processEvents()
            ink = 0.0
            per_curve = []
            for idx, curve in enumerate(curves):
                if idx >= len(pairs):
                    break
                vb = pairs[idx][0]
                if y_mode == "filled":
                    lo, hi = vb.viewRange()[1]
                    y_span = abs(float(hi) - float(lo))
                    row_h = float(vb.sceneBoundingRect().height())
                else:
                    y_span, row_h = _calib_row_geometry(vb, app)
                value = envelope_ink_dev_px(curve.getData()[1], y_span=y_span,
                                            row_height_px=row_h, dpr=dpr)
                ink += value
                per_curve.append({"ink": float(value), "y_span": float(y_span),
                                  "row_height_px": float(row_h)})
            pts = sum(0 if c.getData()[0] is None else len(c.getData()[0])
                      for c in curves)
            point_gate = canvas._time_preview_aa_allowed()
            for curve in curves:
                canvas._set_curve_aa(curve, True)
            app.processEvents()
            aa_ms, aa_miss = _calib_frames(canvas, viewport)
            for curve in curves:
                canvas._set_curve_aa(curve, False)
            app.processEvents()
            off_ms, off_miss = _calib_frames(canvas, viewport)
            return {"ink": float(ink), "aa_frame_ms": aa_ms,
                    "off_frame_ms": off_ms, "drawn_points": int(pts),
                    "per_curve": per_curve,
                    "point_gate_allows_aa": bool(point_gate),
                    "suspect": bool(aa_miss or off_miss)}
        return run

    cases = []
    for n_curves in (2, 3, 4):
        for y_mode, y_label in (("default", "Y默认"), ("filled", "Y拉窄填满")):
            cases.append(_calib_case(
                f"{n_curves} 条 · {y_label}", make_pass(n_curves, y_mode),
                n_curves=n_curves, y_mode=y_mode))

    canvas.close(); app.processEvents()
    fits = [_calib_fit(cases, "全部点"),
            _calib_fit(cases, f"≤{_CALIB_NEAR_TARGET_MS:.0f}ms 近目标段",
                       max_ms=_CALIB_NEAR_TARGET_MS)]
    diagnostics = [
        _calib_fit(cases, "仅 Y默认",
                   where=lambda c: c["y_mode"] == "default"),
        _calib_fit(cases, "仅 Y拉窄填满",
                   where=lambda c: c["y_mode"] == "filled"),
    ]
    band = _calib_band(fits)
    _calib_report_fits("组 2 时域预览行", fits, band, diagnostics)

    # Verdict vs the time-domain band: _INK_AA_OFF=300k is what 250 ms costs
    # there, i.e. an implied 250/300 = 0.833 ms per 1000 dev-px.
    implied = _CALIB_TARGET_MS / (_INK_AA_OFF / 1000.0)
    ref_fit = next((f for f in fits if f), None)
    verdict = None
    if ref_fit and ref_fit["slope_ms_per_k_dev_px"] > 0:
        ratio = ref_fit["slope_ms_per_k_dev_px"] / implied
        reuse = 0.5 <= ratio <= 2.0
        verdict = {
            "timedomain_implied_slope_ms_per_k_dev_px": implied,
            "preview_slope_ms_per_k_dev_px": ref_fit["slope_ms_per_k_dev_px"],
            "slope_ratio": ratio,
            "reuse_timedomain_band": bool(reuse),
            "timedomain_band": {"on": int(_INK_AA_ON), "off": int(_INK_AA_OFF)},
        }
        print(f"   预览行斜率 {ref_fit['slope_ms_per_k_dev_px']:.3f} vs 时域隐含 "
              f"{implied:.3f} ms/k·dev-px → 比值 {ratio:.2f}× "
              f"→ {'复用 _INK_AA_ON/OFF' if reuse else '需单列一对常量'}\n",
              flush=True)
    return {"exposed": exposed, "dpr": dpr, "cases": cases,
            "fits": [f for f in fits if f],
            "diagnostic_fits": [f for f in diagnostics if f],
            "band": band, "verdict": verdict}


# --- group 3: FRF three rows ----------------------------------------------
_CALIB_FRF_BINS = (1025, 2049, 4097)
_CALIB_FRF_MODES = (("clean", "干净"), ("noisy_phase", "噪声相位"),
                    ("noisy_coh", "噪声相干"))


def _calib_frf_result(nbins, mode, rng):
    from types import SimpleNamespace

    import numpy as np

    f = np.linspace(0.0, 1000.0, nbins)
    transfer = 1.0 / (1 - (f / 120.0) ** 2 + 1j * 0.05 * (f / 120.0))
    coherence = 0.92 - 0.02 * (f / 1000.0)
    if mode == "noisy_phase":
        # Amplitude jitter +-60% and a randomly rotated phase: the phase row
        # flips +-180 deg between neighbouring bins, which is the largest ink
        # source this canvas family can produce.
        transfer = (transfer * (1 + 0.6 * rng.standard_normal(nbins))
                    * np.exp(1j * rng.standard_normal(nbins) * 1.5))
    elif mode == "noisy_coh":
        coherence = np.clip(rng.random(nbins), 0.0, 1.0)
    return SimpleNamespace(
        frequencies=f, transfer=transfer.astype(complex),
        coherence=np.clip(coherence, 0.0, 1.0),
        effective=SimpleNamespace(fs=2000.0, df=float(f[1] - f[0]), segments=8),
        warnings=(),
    )


def _calib_frf(app):
    import numpy as np

    from mf4_analyzer.render_profile import envelope_ink_dev_px
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas, viewport, exposed = _calib_open(PgFrfCanvas, app)
    dpr = float(canvas._glw.devicePixelRatioF())
    print("== 组 3 FRF：bins × 构形，ink 对幅值/相位/相干三行求和 ==", flush=True)

    def rows():
        return (
            ("magnitude", canvas._plot_magnitude,
             (canvas._magnitude_curve, canvas._magnitude_low_curve)),
            ("phase", canvas._plot_phase,
             (canvas._phase_curve, canvas._phase_low_curve)),
            ("coherence", canvas._plot_coherence, (canvas._coherence_curve,)),
        )

    def make_pass(nbins, mode):
        def run():
            rng = np.random.default_rng(3 + nbins)
            canvas.set_result(_calib_frf_result(nbins, mode, rng),
                              {"frequency_scale": "linear"}, {})
            app.processEvents()
            _settle(app, 80)
            ink = 0.0
            per_row = {}
            for name, plot, curves in rows():
                y_span, row_h = _calib_row_geometry(plot.vb, app)
                row_ink = 0.0
                for curve in curves:
                    _xd, yd = curve.getData()
                    if yd is None:
                        continue
                    row_ink += envelope_ink_dev_px(yd, y_span=y_span,
                                                   row_height_px=row_h, dpr=dpr)
                ink += row_ink
                per_row[name] = {"ink": float(row_ink), "y_span": float(y_span),
                                 "row_height_px": float(row_h)}
            for _n, _p, curves in rows():
                for curve in curves:
                    canvas._set_curve_aa(curve, True)
            app.processEvents()
            aa_ms, aa_miss = _calib_frames(canvas, viewport)
            for _n, _p, curves in rows():
                for curve in curves:
                    canvas._set_curve_aa(curve, False)
            app.processEvents()
            off_ms, off_miss = _calib_frames(canvas, viewport)
            return {"ink": float(ink), "aa_frame_ms": aa_ms,
                    "off_frame_ms": off_ms, "per_row": per_row,
                    "suspect": bool(aa_miss or off_miss)}
        return run

    cases = []
    for nbins in _CALIB_FRF_BINS:
        for mode, mode_label in _CALIB_FRF_MODES:
            cases.append(_calib_case(
                f"{nbins} bins · {mode_label}", make_pass(nbins, mode),
                n_bins=nbins, mode=mode))

    canvas.close(); app.processEvents()
    fits = [_calib_fit(cases, "全部点"),
            _calib_fit(cases, f"≤{_CALIB_NEAR_TARGET_MS:.0f}ms 近目标段",
                       max_ms=_CALIB_NEAR_TARGET_MS)]
    # Per-shape diagnostics: the low-coherence split (NaN-broken sub-paths on
    # the magnitude/phase rows plus a full-range coherence trace) and the
    # noisy-phase shape do NOT share a slope, so the band must be driven by
    # the more expensive one per unit ink.
    diagnostics = [_calib_fit(cases, f"仅 {label}",
                              where=lambda c, m=mode: c["mode"] == m)
                   for mode, label in _CALIB_FRF_MODES]
    band = _calib_band(fits)
    _calib_report_fits("组 3 FRF 三行", fits, band, diagnostics)
    # The clean family is dropped from the fits (near-constant ink) but is the
    # clearest evidence that ink alone cannot carry this gate.
    clean = [c for c in cases if c["mode"] == "clean"]
    clean_note = None
    if len(clean) >= 2:
        clean_note = {
            "ink_range": [min(c["ink"] for c in clean),
                          max(c["ink"] for c in clean)],
            "frames_ms": {c["n_bins"]: c["aa_frame_ms"] for c in clean},
        }
        spans = "/".join(f"{c['n_bins']}→{c['aa_frame_ms']:.1f}ms" for c in clean)
        print(f"   干净构形：ink 恒为 ~{clean[0]['ink']/1000:.1f}k 而帧随 bins 涨"
              f"（{spans}）→ ink 腿必须与点数腿 AND，不能单独定 AA\n", flush=True)
    return {"exposed": exposed, "dpr": dpr, "cases": cases,
            "fits": [f for f in fits if f],
            "diagnostic_fits": [f for f in diagnostics if f],
            "clean_family_note": clean_note, "band": band}


def cmd_analysis_calibrate(_args):
    import platform

    app = _qapp()
    print(f"platform={app.platformName()} os={platform.platform()} "
          f"loadavg={_calib_loadavg()}", flush=True)
    if app.platformName() == "offscreen":
        print("!! offscreen 平台测不出 paint 成本，本次读数不得当作标定依据 "
              "(CLAUDE.md Gotchas 验真机渲染)", flush=True)
    spectrum = _calib_spectrum(app)
    preview = _calib_preview(app)
    frf = _calib_frf(app)

    recommended = {
        "spectrum_row": spectrum["band"],
        "time_preview_row": {"band": preview["band"],
                             "verdict": preview.get("verdict")},
        "frf_rows": frf["band"],
        "target_ms": _CALIB_TARGET_MS,
        "on_over_off_ratio": _CALIB_ON_RATIO,
    }
    print("== 推荐常量（spec §5 回填用）==", flush=True)
    if spectrum["band"]:
        print(f"  _SPECTRUM_INK_AA_ON/OFF = "
              f"{spectrum['band']['on']/1000:.0f}k / "
              f"{spectrum['band']['off']/1000:.0f}k", flush=True)
    verdict = preview.get("verdict") or {}
    if verdict.get("reuse_timedomain_band"):
        print(f"  预览行 = 复用 _INK_AA_ON/OFF (200k/300k)；实测斜率比 "
              f"{verdict['slope_ratio']:.2f}× ≤ 2×", flush=True)
    elif preview["band"]:
        print(f"  预览行 = {preview['band']['on']/1000:.0f}k / "
              f"{preview['band']['off']/1000:.0f}k（斜率比 "
              f"{verdict.get('slope_ratio', float('nan')):.2f}× > 2×，单列）",
              flush=True)
    if frf["band"]:
        print(f"  FRF 三行 ink 带 = {frf['band']['on']/1000:.0f}k / "
              f"{frf['band']['off']/1000:.0f}k", flush=True)

    return {
        "command": "analysis-calibrate",
        "environment": _environment(app, os_platform=platform.platform(),
                                    loadavg=_calib_loadavg()),
        "spectrum": spectrum,
        "time_preview": preview,
        "frf": frf,
        "recommended": recommended,
    }


# --------------------------------------------------------------------------
# spectrum-switch : PgLineCanvas.plot_spectra view-switch call cost, AA
# synchronous-in-switch vs deferred (spec §1.4; was probes/probe_fft_view_switch.py)
# --------------------------------------------------------------------------

def _spectrum_switch_make_entries(n_curves, n_bins, n_time, seed):
    import numpy as np

    rng = np.random.default_rng(seed)
    freq = np.linspace(0.0, 2000.0, n_bins)
    t = np.linspace(0.0, 10.0, n_time)
    entries = []
    for i in range(n_curves):
        amp = np.abs(rng.standard_normal(n_bins)) * (1.0 + 0.2 * i)
        amp += 20.0 * np.exp(-((freq - (120.0 + 40 * i)) ** 2) / 50.0)
        entries.append({
            "label": f"电机转速 {i}", "color": COLORS[i % len(COLORS)],
            "freq": freq, "amp": amp,
            "time": t,
            "signal": 40.0 * np.sin(2.0 * np.pi * (3.0 + i) * t),
        })
    return entries


def cmd_spectrum_switch(_args):
    import numpy as np

    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    app = _qapp()
    canvas = PgLineCanvas()
    canvas.resize(1400, 900)
    canvas.show(); canvas.raise_(); canvas.activateWindow()
    exposed = _wait_window_exposed(app, canvas)
    viewport = canvas._glw.viewport()
    print(f"platform={app.platformName()} dpr={canvas._glw.devicePixelRatioF()} "
          f"exposed={exposed}", flush=True)

    views = {
        "A": _spectrum_switch_make_entries(3, 65_536, 40_000, 1),
        "B": _spectrum_switch_make_entries(2, 32_768, 20_000, 2),
    }

    def switch(key, *, aa_in_switch):
        canvas._aa_on = bool(aa_in_switch)
        aa_calls = {"n": 0, "ms": 0.0}
        original = canvas._apply_idle_curve_aa

        def timed_apply():
            t = time.perf_counter()
            original()
            aa_calls["ms"] += (time.perf_counter() - t) * 1000.0
            aa_calls["n"] += 1

        canvas._apply_idle_curve_aa = timed_apply
        t0 = time.perf_counter()
        canvas.plot_spectra(views[key], xlim=(0.0, 2000.0),
                            amp_label="Amplitude", title=f"View {key}")
        plot_ms = (time.perf_counter() - t0) * 1000.0
        canvas._apply_idle_curve_aa = original
        app.processEvents()
        frame1, _s1 = _timed_repaint(canvas, viewport, retries=0, floor_ms=0.0)
        frame2, _s2 = _timed_repaint(canvas, viewport, retries=0, floor_ms=0.0)
        return {
            "plot_ms": plot_ms, "aa_apply_ms": aa_calls["ms"],
            "aa_apply_n": aa_calls["n"],
            "frame1_ms": frame1, "frame2_ms": frame2,
            "total_ms": plot_ms + frame1,
            "aa_on": bool(canvas._aa_on),
        }

    modes_out = {}
    for aa_in_switch in (True, False):
        tag = ("切换里同步开 AA（当前行为）" if aa_in_switch
               else "对照：切换里不开 AA")
        runs = []
        for i in range(3):
            for key in ("A", "B"):
                r = switch(key, aa_in_switch=aa_in_switch)
                runs.append(r)
                print(f"  {tag[:6]} -> View {key}: plot_spectra={r['plot_ms']:7.1f} "
                      f"(其中 AA 重开 {r['aa_apply_ms']:6.1f} × {r['aa_apply_n']}) "
                      f"首帧={r['frame1_ms']:6.1f} 次帧={r['frame2_ms']:6.1f} "
                      f"合计={r['total_ms']:7.1f} ms", flush=True)
        warm = runs[2:]
        median_plot = float(np.median([r["plot_ms"] for r in warm]))
        median_frame1 = float(np.median([r["frame1_ms"] for r in warm]))
        median_total = float(np.median([r["total_ms"] for r in warm]))
        print(f"== {tag}：中位 plot_spectra "
              f"{median_plot:.1f} ms, "
              f"中位首帧 {median_frame1:.1f} ms, "
              f"中位合计 {median_total:.1f} ms\n",
              flush=True)
        modes_out[tag] = {
            "aa_in_switch": aa_in_switch, "runs": runs,
            "median_plot_ms": median_plot, "median_frame1_ms": median_frame1,
            "median_total_ms": median_total,
        }

    canvas.close()
    app.processEvents()
    return {
        "command": "spectrum-switch",
        "environment": _environment(app, canvas, exposed=exposed),
        "modes": modes_out,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

_HANDLERS = {
    "time-mainwindow": cmd_time_mainwindow,
    "time-canvas": cmd_time_canvas,
    "ylim-order": cmd_ylim_order,
    "stale-ink": cmd_stale_ink,
    "analysis-frames": cmd_analysis_frames,
    "analysis-calibrate": cmd_analysis_calibrate,
    "spectrum-switch": cmd_spectrum_switch,
}


def _arguments():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "time-mainwindow",
        help="MainWindow product path: _register_file_data loads 8ch x 1M "
             "pts, builds two Views, round-trips _switch_view across four "
             "layout scenarios (subplot全显 / subplot含隐藏通道 / overlay / "
             "两 View 布局不同) with per-method timing (spec Sec 1.1). "
             "Real machine only.",
    )
    p.add_argument("--json-out", type=Path)

    p = sub.add_parser(
        "time-canvas",
        help="Canvas-level view-switch cost breakdown, reproducing the "
             "product _render_view_to_canvas sequence stage by stage, "
             "across the vector-AA (smooth) and dense-raster backends "
             "(spec Sec 1.1/1.2). Real machine only.",
    )
    p.add_argument("--json-out", type=Path)

    p = sub.add_parser(
        "ylim-order",
        help="A/B: product order (plot_channels(defer) -> restore X with a "
             "sync flush while Y is still the [0,1] stub -> restore Y) vs "
             "fixed order (Y restored before the X flush) (spec Sec 1.2). "
             "Real machine only.",
    )
    p.add_argument("--n-channels", type=int, default=8,
                   help="Channel count for fixture A (fixture B uses "
                        "max(2, n-3)). Default 8.")
    p.add_argument("--json-out", type=Path)

    p = sub.add_parser(
        "stale-ink",
        help="Reproduces the three consequences of measuring ink against the "
             "stub Y span before the real Y range is restored: envelope "
             "bucket decimation, AA refusal, raster mis-admission; confirms "
             "none of it self-heals after 500 ms idle (spec Sec 1.2). This is "
             "the one subcommand that also reproduces under "
             "QT_QPA_PLATFORM=offscreen -- it is a logic defect, not a paint-"
             "cost measurement.",
    )
    p.add_argument("--json-out", type=Path)

    p = sub.add_parser(
        "analysis-frames",
        help="PgLineCanvas spectrum-row ink vs AA frame cost (same 4095 "
             "plotted points across cases, only the vertical ink varies) "
             "plus PgFrfCanvas AA/non-AA frame cost across bin counts (spec "
             "Sec 1.4). Real machine only; the 32k-bin noisy-phase FRF case "
             "takes several seconds for its single frame, not a hang.",
    )
    p.add_argument("--json-out", type=Path)

    p = sub.add_parser(
        "analysis-calibrate",
        help="Calibration sweep for the analysis-canvas ink bands (spec Sec 5 "
             "rows: spectrum row _SPECTRUM_INK_AA_ON/OFF, FRF three-row band, "
             "time-preview band). Three groups -- spectrum row (3 curves, "
             "peak/floor swept), time-preview row (2/3/4 envelopes x default "
             "vs filled Y), FRF (1k/2k/4k bins x clean/noisy-phase/noisy-"
             "coherence) -- each configuration measured over >=2 passes with "
             "AA forced on and off, reduced to a least-squares ink->ms line, "
             "and turned into OFF = ink at 250 ms (_BACKSTOP_STEADY_AA_MS), "
             "ON = OFF * 2/3. Real machine only.",
    )
    p.add_argument("--json-out", type=Path)

    p = sub.add_parser(
        "spectrum-switch",
        help="PgLineCanvas.plot_spectra view-switch call cost: AA "
             "re-applied synchronously inside the switch (today's behavior) "
             "vs a control where the switch does not re-open AA (spec Sec "
             "1.4). Real machine only.",
    )
    p.add_argument("--json-out", type=Path)

    return parser.parse_args()


def main():
    args = _arguments()
    result = _HANDLERS[args.command](args)
    json_out = getattr(args, "json_out", None)
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
