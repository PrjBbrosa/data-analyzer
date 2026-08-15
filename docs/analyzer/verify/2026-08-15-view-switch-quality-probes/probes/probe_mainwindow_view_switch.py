#!/usr/bin/env python3
"""MainWindow 级真机探针：时域 View 来回切换到底走了哪条路、每段花多少。

用产品自己的入口：`_register_file_data` + `_on_source_load_finished` 装一份
8 通道数据；建两个 View（不同通道集）；`_switch_view` 来回切；在每次切换里
给关键方法打点（monkeypatch 计时），并在切完读画布侧的：
  * `_last_full_rebuild_reason` / `_last_selection_delta`  —— 走了重建还是复用
  * `_line_ink_state` 记录到的 ink 与 QualityManager 判定 / 质量点
  * dense-raster entries 数
四种布局各跑一遍：subplot 全显 / subplot 带隐藏通道 / overlay / 两个 View 布局不同。

真机跑（不要设 QT_QPA_PLATFORM=offscreen）。
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path("/Users/donghang/Downloads/data analyzer")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait_exposed(app, widget, timeout_ms=5000.0):
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


def _settle(app, ms=250):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


class Timers:
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


def make_frame(n_ch, n_points, fs):
    import numpy as np
    import pandas as pd
    t = np.arange(n_points, dtype=np.float64) / fs
    cols = {"Time": t}
    names = ["方向盘扭矩", "电机转速", "电机扭矩", "Rack Force", "Rack Travel",
             "电机相电流U", "电机相电流V", "转向角"]
    for i in range(n_ch):
        cols[names[i]] = 100.0 * np.sin(2.0 * np.pi * (0.20 + 0.03 * i) * t)
    return pd.DataFrame(cols), names[:n_ch]


def canvas_snapshot(canvas):
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


def run_scenario(app, w, fid, names, *, plot_mode_a, plot_mode_b,
                 hidden_in_a, label, timers):
    from PyQt5.QtCore import QTimer

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
            snap_now = canvas_snapshot(canvas)
            _settle(app, 350)  # 让 150ms idle timer 与 raster 定时器都落地
            snap_settled = canvas_snapshot(canvas)
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


def main():
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui import view_bridge

    app = _qapp()
    w = MainWindow()
    w.resize(1600, 950)
    w.show(); w.raise_(); w.activateWindow()
    exposed = _wait_exposed(app, w)
    print(f"platform={app.platformName()} exposed={exposed}", flush=True)

    df, names = make_frame(8, 1_000_000, 20_000.0)
    w._register_file_data("probe.mf4", df, ["Time", *names],
                          {n: "Nm" for n in names})
    fid = next(iter(w.files))
    w._on_source_load_finished([fid])
    _settle(app, 300)

    timers = Timers()
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
    out = {}
    for sc in scenarios:
        out[sc["label"]] = run_scenario(app, w, fid, names, timers=timers, **sc)

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if path:
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    w.close(); app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
