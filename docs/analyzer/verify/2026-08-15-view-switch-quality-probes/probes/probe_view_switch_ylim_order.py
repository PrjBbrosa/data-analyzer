#!/usr/bin/env python3
"""对照：View 切换时 ink 在 Y 恢复之前测量导致的后端误判。

产品顺序（_view_mixin._render_view_to_canvas）：
    plot_channels(defer_first_frame=True)   # Y 还是 stub [0,1]
    restore_visible_xlim(state.xlim)        # 内部同步 flush -> 在这里测 ink
    restore_visible_ylims(state.ylims)      # Y 才被恢复

对照顺序：
    plot_channels(defer_first_frame=True)
    restore_visible_ylims(state.ylims)      # 先把 Y 摆正
    restore_visible_xlim(state.xlim)        # 再 flush，ink 才是真值

两边都量：记录到的 ink、是否被收进光栅后端、光栅 entry 数、整段耗时。
真机跑。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/donghang/Downloads/data analyzer")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WIDTH, HEIGHT = 1600, 950
COLORS = ("#1769e0", "#00a67d", "#ff2038", "#ff5a0a", "#8747ff", "#d41445",
          "#0ca678", "#c2255c")


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


def make_rows(n, *, n_points, fs, tag):
    import numpy as np
    t = np.arange(int(n_points), dtype=np.float64) / float(fs)
    return [
        (f"CH{i}", True, t,
         100.0 * np.sin(2.0 * np.pi * (0.20 + 0.03 * i) * t),
         COLORS[i % len(COLORS)], "Nm", tag)
        for i in range(n)
    ]


def timed_repaint(canvas, viewport):
    started = time.perf_counter()
    canvas._glw.scene().update()
    viewport.repaint()
    return (time.perf_counter() - started) * 1000.0


def one_switch(app, canvas, viewport, rows, xlim, ylims, *, ylim_first, ctx):
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

    frame_ms = timed_repaint(canvas, viewport)

    t0 = time.perf_counter()
    app.processEvents()                       # 0 延时 raster rebuild 定时器
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    raster_ms = (time.perf_counter() - t0) * 1000.0
    app.processEvents()
    raster_frame_ms = timed_repaint(canvas, viewport)

    q = canvas._quality
    t0 = time.perf_counter()
    q.try_enable_idle_quality()
    enable_ms = (time.perf_counter() - t0) * 1000.0
    aa_frame_ms = timed_repaint(canvas, viewport)
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


def main():
    import numpy as np
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG

    n_ch = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    app = _qapp()
    canvas = TimeDomainCanvasPG()
    canvas.resize(WIDTH, HEIGHT)
    canvas.show(); canvas.raise_(); canvas.activateWindow()
    exposed = _wait_exposed(app, canvas)
    viewport = canvas._glw.viewport()
    print(f"platform={app.platformName()} dpr={canvas._glw.devicePixelRatioF()} "
          f"exposed={exposed} n_ch={n_ch}", flush=True)

    a = make_rows(n_ch, n_points=1_000_000, fs=20_000.0, tag="fileA")
    b = make_rows(max(2, n_ch - 3), n_points=600_000, fs=20_000.0, tag="fileB")

    def wins(rows, lo, hi):
        t = rows[0][2]
        span = float(t[-1] - t[0])
        xl = (float(t[0] + span * lo), float(t[0] + span * hi))
        yl = {}
        return xl, yl

    xa, _ = wins(a, 0.40, 0.60)
    xb, _ = wins(b, 0.00, 0.10)

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

    for ylim_first in (False, True):
        tag = "先 Y 后 flush（对照/修复）" if ylim_first else "当前产品顺序"
        runs = []
        for i in range(3):
            runs.append(one_switch(app, canvas, viewport, a, xa, ya,
                                   ylim_first=ylim_first, ctx=("p", "A")))
            runs.append(one_switch(app, canvas, viewport, b, xb, yb,
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
        print(f"   中位合计 {float(np.median([r['total_ms'] for r in warm])):7.1f} ms"
              f"   光栅重建中位 {float(np.median([r['raster_ms'] for r in warm])):6.1f} ms"
              f"   光栅收编 {warm[-1]['raster_eligible']}/{n_ch}", flush=True)

    canvas.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
