#!/usr/bin/env python3
"""真机计时：时域 View 来回切换的成本拆解。

复现产品路径 _render_view_to_canvas -> _plot_time_on_canvas -> plot_channels
的画布侧部分，按阶段计时：
  1) plot_channels(defer_first_frame=True)  —— 全量重建（clear + bind）
  2) restore_visible_xlim(state.xlim)       —— 恢复窗口 + 同步 flush 刷新
  3) 第一帧（质量后端都还没上）             —— 用户切完立刻看到的帧
  4) dense-raster flush_pending()           —— 光栅缓存重建（clear() 清过）
  5) try_enable_idle_quality()              —— 向量 AA 重新判定 + 打开
  6) 首帧 AA / 稳态 AA 帧

两类 fixture 走两条不同的质量后端：
  smooth  低 ink，走原生向量 AA
  dense   满幅振荡，ink 超预算，走 dense-raster 光栅缓存

必须真机跑（不要设 QT_QPA_PLATFORM=offscreen），offscreen 量不出 paint 成本。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/donghang/Downloads/data analyzer")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WIDTH, HEIGHT = 1600, 950
COLORS = ("#1769e0", "#00a67d", "#ff2038", "#ff5a0a", "#8747ff", "#d41445")


def _qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait_exposed(app, widget, timeout_ms=4000.0):
    handle = widget.windowHandle()
    deadline = time.perf_counter() + timeout_ms / 1000.0
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


def make_rows(names, *, n_points, fs, kind, tag):
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


def timed_repaint(canvas, viewport, *, retries=1, floor_ms=0.5):
    ms = None
    for _ in range(retries + 1):
        started = time.perf_counter()
        canvas._glw.scene().update()
        viewport.repaint()
        ms = (time.perf_counter() - started) * 1000.0
        if ms >= floor_ms:
            break
    return ms, ms < floor_ms


def run_switch(app, canvas, viewport, rows, xlim, label, ctx_key):
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
    first_frame_ms, s1 = timed_repaint(canvas, viewport)

    # --- 4: dense-raster 重建（clear() 已把 entries 清空）。
    #     plot_channels 尾部 schedule_rebuild(delay_ms=0)，所以 0 延时定时器
    #     会在下一次 processEvents 里落地——把它一并算进这一段。
    t0 = time.perf_counter()
    app.processEvents()
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    raster_ms = (time.perf_counter() - t0) * 1000.0
    app.processEvents()
    raster_entries = len(canvas._dense_raster.entries)
    raster_frame_ms, s4 = timed_repaint(canvas, viewport)

    # --- 5: 空闲计时器到点 -> ink 判定 + 打开向量 AA
    t0 = time.perf_counter()
    ink_total = q._frame_native_ink_total()
    ink_measure_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    q.try_enable_idle_quality()
    enable_ms = (time.perf_counter() - t0) * 1000.0
    aa_engaged = bool(q.aa_on)

    first_aa_ms, s2 = timed_repaint(canvas, viewport)
    app.processEvents()
    tripped = q.aa_backstop_reason
    steady_reforced = False
    if not q.aa_on and aa_engaged:
        steady_reforced = True
        q._set_curves_antialias(True)
        q.aa_on = True
    steady_aa_ms, s3 = timed_repaint(canvas, viewport)
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


def main():
    import numpy as np

    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    app = _qapp()
    canvas = TimeDomainCanvasPG()
    canvas.resize(WIDTH, HEIGHT)
    canvas.show()
    canvas.raise_()
    canvas.activateWindow()
    exposed = _wait_exposed(app, canvas)
    viewport = canvas._glw.viewport()
    print(
        f"platform={app.platformName()} dpr={canvas._glw.devicePixelRatioF()} "
        f"exposed={exposed}",
        flush=True,
    )

    fixtures = {
        # 低 ink：走原生向量 AA
        "smoothA": make_rows(["方向盘扭矩", "电机转速", "电机扭矩"],
                             n_points=200_000, fs=1000.0, kind="smooth",
                             tag="fileA"),
        "smoothB": make_rows(["Rack Force", "Rack Travel"],
                             n_points=400_000, fs=2000.0, kind="smooth",
                             tag="fileB"),
        # 满幅振荡：ink 超预算，走 dense-raster
        "denseA": make_rows(["电机相电流 U", "电机相电流 V", "电机相电流 W"],
                            n_points=1_000_000, fs=20_000.0, kind="dense",
                            tag="fileC"),
        "denseB": make_rows(["转矩传感器原始", "扭矩纹波"],
                            n_points=1_000_000, fs=20_000.0, kind="dense",
                            tag="fileD"),
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
            runs.append(run_switch(
                app, canvas, viewport, fixtures[ka],
                xwin(fixtures[ka], alo, ahi), f"[{i}] -> {ka}", ("probe", ka)))
            runs.append(run_switch(
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

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.write_text(
            json.dumps({"platform": app.platformName(), "exposed": exposed,
                        "runs": all_runs}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
