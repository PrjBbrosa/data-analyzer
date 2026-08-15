#!/usr/bin/env python3
"""真机计时：分析区（FFT 线图）View 切换的 AA 成本。

分析区的 View 切换走 _on_analysis_view_switched -> _render_analysis_view_from_cache
-> canvas.plot_spectra(...)。plot_spectra 会：
  1) removeItem 掉所有旧曲线，_reset_spectrum_aa_density_gate()
  2) 以 antialias=False 建全部新曲线
  3) `if self._aa_on: self._apply_idle_curve_aa()` —— 同步把 AA 重新加回去

也就是说分析区不是"空闲后再上 AA"，而是切换调用里同步付掉。这里分别量：
  * plot_spectra 全过程
  * 其中重新开 AA 的那一步（_apply_idle_curve_aa）
  * 之后的首帧 / 稳态帧
以及一个对照：把 _aa_on 置 False（即不在切换里开 AA）时同一次切换的耗时。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/donghang/Downloads/data analyzer")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


def make_entries(n_curves, n_bins, n_time, seed):
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


def timed_repaint(canvas, viewport):
    started = time.perf_counter()
    canvas._glw.scene().update()
    viewport.repaint()
    return (time.perf_counter() - started) * 1000.0


def main():
    import numpy as np
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    app = _qapp()
    canvas = PgLineCanvas()
    canvas.resize(1400, 900)
    canvas.show(); canvas.raise_(); canvas.activateWindow()
    exposed = _wait_exposed(app, canvas)
    viewport = canvas._glw.viewport()
    print(f"platform={app.platformName()} dpr={canvas._glw.devicePixelRatioF()} "
          f"exposed={exposed}", flush=True)

    views = {
        "A": make_entries(3, 65_536, 40_000, 1),
        "B": make_entries(2, 32_768, 20_000, 2),
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
        frame1 = timed_repaint(canvas, viewport)
        frame2 = timed_repaint(canvas, viewport)
        return {
            "plot_ms": plot_ms, "aa_apply_ms": aa_calls["ms"],
            "aa_apply_n": aa_calls["n"],
            "frame1_ms": frame1, "frame2_ms": frame2,
            "total_ms": plot_ms + frame1,
            "aa_on": bool(canvas._aa_on),
        }

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
        print(f"== {tag}：中位 plot_spectra "
              f"{float(np.median([r['plot_ms'] for r in warm])):.1f} ms, "
              f"中位首帧 {float(np.median([r['frame1_ms'] for r in warm])):.1f} ms, "
              f"中位合计 {float(np.median([r['total_ms'] for r in warm])):.1f} ms\n",
              flush=True)

    canvas.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
