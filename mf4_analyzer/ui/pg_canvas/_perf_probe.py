"""时域渲染计时探针 —— 诊断用，定位后整体移除。

环境变量 ``TRACELAB_PERF=1`` 开启；默认关闭时**零开销**（所有调用先做一次
``os.environ.get`` 短路判断，不进入任何计时分支、不触发文件 I/O、import 本模块
本身亦无副作用）。

用途：在 Windows 真机定位「6 个 129.5 kHz 通道 + 滤波 时域绘图卡十几秒」的真正
热点 —— 离屏量不到真机光栅成本，必须在真机量。探针回答两个问题：
  (1) 卡在哪个阶段：滤波计算 / 数据组装(_build_time_plot_data) / setData /
      首帧 paint 光栅？
  (2) 分屏减桶优化是否真的生效（每条 dense 通道的 effective bucket width、
      summed displayed points）？

输出：同时写日志文件 ``Path.home()/"tracelab_perf.log"``（每行带时间戳，Windows
友好）和 print 到 stdout。每次「绘图」开一段 (``section``)，每次 paintEvent 一行。

挂钩点（均用 ``if ENABLED`` 包裹，便于诊断后整体删除）：
  * ``window._plot_time_on_canvas`` —— 整段绘图 + _build_time_plot_data +
    plot_channels 的子计时（见 window.py）。
  * ``window._build_time_plot_data`` —— 滤波 apply 累计 ms（见 window.py）。
  * ``canvas.plot_channels`` —— 建轴/bind/首次 setData 的整段计时（见 canvas.py）。
  * 时域画布 viewport 的 paintEvent —— 包装原方法计 perf_counter 差（见 canvas.py
    安装 install_paint_probe）。

诊断完成后删除步骤：删本文件 + 删 window.py / canvas.py 中三处 ``# [perf-probe]``
标记的代码块即可，无残留。
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# 单次读环境变量，模块导入即定。默认关 → ENABLED is False → 所有挂钩短路。
ENABLED = bool(os.environ.get("TRACELAB_PERF"))

_LOG_PATH = Path.home() / "tracelab_perf.log"

# 滤波 apply 累计耗时（ms），由 window._build_time_plot_data 在每次绘图前 reset，
# 每次 filters.apply 前后累加，绘图段结束时读出并清零。
_filter_apply_ms = 0.0

# 每次绘图段内的 paintEvent 计数 + 累计耗时，供段落汇总参考。
_paint_count = 0
_paint_total_ms = 0.0


def _emit(line: str) -> None:
    """写一行到日志文件 + stdout，带毫秒时间戳。仅 ENABLED 时调用。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S") + f".{int((time.time() % 1) * 1000):03d}"
    text = f"[{ts}] {line}"
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
    try:
        print("TRACELAB " + text, file=sys.stdout, flush=True)
    except Exception:
        pass


def log(line: str) -> None:
    """对外日志入口。调用方应自行 ``if _perf_probe.ENABLED`` 包裹以保零开销。"""
    if not ENABLED:
        return
    _emit(line)


@contextmanager
def section(label: str):
    """一段绘图计时上下文。退出时记 总耗时(ms) 一行。"""
    if not ENABLED:
        yield
        return
    _emit(f"--- {label} BEGIN ---")
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = (time.perf_counter() - t0) * 1000.0
        _emit(f"--- {label} END --- total={dt:.1f} ms")


@contextmanager
def timed(label: str):
    """子计时上下文，退出记一行 ``label: X ms``。"""
    if not ENABLED:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = (time.perf_counter() - t0) * 1000.0
        _emit(f"{label}: {dt:.1f} ms")


def reset_filter_accum() -> None:
    global _filter_apply_ms
    if not ENABLED:
        return
    _filter_apply_ms = 0.0


@contextmanager
def filter_apply():
    """包住单次 filters.apply，累加到 _filter_apply_ms。"""
    if not ENABLED:
        yield
        return
    global _filter_apply_ms
    t0 = time.perf_counter()
    try:
        yield
    finally:
        _filter_apply_ms += (time.perf_counter() - t0) * 1000.0


def log_filter_total() -> None:
    if not ENABLED:
        return
    _emit(f"filter apply 累计: {_filter_apply_ms:.1f} ms")


def reset_paint_counter() -> None:
    global _paint_count, _paint_total_ms
    if not ENABLED:
        return
    _paint_count = 0
    _paint_total_ms = 0.0


def _record_paint(dt_ms: float) -> None:
    global _paint_count, _paint_total_ms
    _paint_count += 1
    _paint_total_ms += dt_ms
    _emit(f"paintEvent #{_paint_count}: {dt_ms:.1f} ms")


def install_paint_probe(canvas) -> None:
    """Hook 时域画布 GraphicsView 的 paintEvent，记录每帧真实光栅耗时。

    实现要点（Qt 坑）：pyqtgraph 的 ``_glw`` 本身就是 ``QGraphicsView``（绘制就
    发生在它的 ``paintEvent`` 里，画到自己的 viewport 上）。Qt 从 C++ 派发虚函数
    ``paintEvent``，**只在类层面被 override 时**才回调到 Python —— 给实例属性
    赋一个 ``paintEvent`` 函数 / 给 viewport 换个子类都不会被调用（实测 0 次命中）。
    所以这里用运行时 ``__class__`` 切换：把 ``_glw`` 的类替换成一个在类层面 override
    了 ``paintEvent`` 的动态子类（基类=原 GraphicsLayoutWidget 类），在 super 调用
    前后计 ``perf_counter`` 差。这是抓真实光栅墙的关键 —— 绝大部分卡顿在这里。

    幂等：重复安装只挂一次（_tracelab_paint_hooked 标记）。仅 ENABLED 时安装。
    """
    if not ENABLED:
        return
    glw = getattr(canvas, "_glw", None)
    if glw is None:
        return
    if getattr(glw, "_tracelab_paint_hooked", False):
        return
    base = type(glw)

    class _PaintProbeView(base):  # 类层面 override → Qt C++ 派发会回调
        def paintEvent(self, ev):
            t0 = time.perf_counter()
            try:
                return base.paintEvent(self, ev)
            finally:
                _record_paint((time.perf_counter() - t0) * 1000.0)

    try:
        glw.__class__ = _PaintProbeView
        glw._tracelab_paint_hooked = True
        _emit("paintEvent hook 已安装到时域画布 GraphicsView (__class__ swap)")
    except Exception as exc:
        _emit(f"paintEvent hook 安装失败(已吞): {exc!r}")


def log_canvas_diagnostics(canvas) -> None:
    """绘图后诊断行：可见 primary 通道数 / companion 数 / summed displayed
    points / 分屏 dense 计数 / 每条 dense 通道 effective bucket width。

    用于确认减桶优化是否生效、生效到多少。仅 ENABLED 时执行。
    """
    if not ENABLED:
        return
    try:
        lines = getattr(canvas, "_channel_lines", {}) or {}
        companions = getattr(canvas, "_companion_names", set()) or set()
        overlay = bool(getattr(canvas, "_overlay_mode", False))
        dense_count = int(getattr(canvas, "_subplot_dense_count", 0) or 0)

        # _companion_names is keyed by the composite (data_id, name) identity
        # key; count via composite_items so the membership test matches.
        composite = getattr(lines, "composite_items", None)
        if callable(composite):
            line_triples = list(composite())
        else:
            line_triples = [(n, n, v) for n, v in lines.items()]
        n_total = len(line_triples)
        n_companion = sum(1 for ck, _n, _v in line_triples if ck in companions)
        n_primary = n_total - n_companion

        # summed displayed points: 遍历每条线的 PlotDataItem getData 长度求和。
        summed_pts = 0
        per_line_pts = []
        for _ck, name, line_facade_pair in line_triples:
            _axis, line_facade = line_facade_pair
            pdi = getattr(line_facade, "plot_data_item", None)
            n = 0
            if pdi is not None:
                try:
                    xd, _yd = pdi.getData()
                    n = 0 if xd is None else len(xd)
                except Exception:
                    n = 0
            summed_pts += n
            per_line_pts.append((name, n))

        _emit(
            f"诊断: mode={'overlay' if overlay else 'subplot/single'} "
            f"primary通道={n_primary} companion={n_companion} "
            f"subplot_dense_count={dense_count} "
            f"summed_displayed_points={summed_pts}"
        )

        # 每条 dense 通道的 effective bucket width（确认减桶生效到多少）。
        pw = 0
        try:
            pw = int(canvas._current_pixel_width())
        except Exception:
            pw = 0
        _emit(f"诊断: current_pixel_width={pw}")
        eff_fn = getattr(canvas, "_effective_pixel_width", None)
        channel_data = getattr(canvas, "channel_data", {}) or {}
        for name, entry in channel_data.items():
            if name not in lines:
                continue
            try:
                slen = len(entry[1])
            except Exception:
                continue
            eff = None
            if callable(eff_fn) and pw > 0:
                try:
                    if overlay:
                        eff = eff_fn(pw)
                    else:
                        eff = eff_fn(pw, source_len=slen, dense_count=dense_count)
                except Exception:
                    eff = None
            ratio = (slen / pw) if pw > 0 else 0.0
            _emit(
                f"诊断: 通道 {name!r} source_len={slen} "
                f"decimation_ratio={ratio:.1f} effective_bucket_width={eff}"
            )

        # 逐线显示点数（验证减桶后实际 setData 的点数）。
        for name, n in per_line_pts:
            _emit(f"诊断: 通道 {name!r} displayed_points={n}")
    except Exception as exc:  # 探针绝不能影响主流程
        _emit(f"诊断异常(已吞): {exc!r}")
