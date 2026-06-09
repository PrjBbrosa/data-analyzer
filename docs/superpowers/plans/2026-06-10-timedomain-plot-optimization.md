# 时域 Plot 性能优化与内核精简（第一批）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/superpowers/specs/2026-06-10-timedomain-plot-optimization.md` 消除时域 plot 重建型事件与鼠标 tick 热路径的重复做工，并删除高确定性死代码——功能、像素结果、测试契约零变化。

**Architecture:** 全部是定点修改：pg_canvas 包内 5 个协作器（quality/renderer/tick_density/cursor/overlay_axes）+ canvas.py 状态字段 + main_window 数据流闸门 + io 装载拷贝。不新增渲染原语，不改导出链，不动 monkeypatch seam（pg_canvases.py shim、envelope re-export、canvas 单行委托、`enable_span_selector`）。

**Tech Stack:** PyQt5 + pyqtgraph 0.14、numpy、pytest + pytest-qt（offscreen，conftest 已设 `QT_QPA_PLATFORM=offscreen`）。

**关键背景（执行前必读）:**
- 工作目录含空格：`/Users/donghang/Downloads/data analyzer`，所有命令注意引号。
- 测试命令一律 `python -m pytest ...`（pytest.ini 默认排除 `slow` 标记）。
- `_CanvasBackref` 委托机制：协作器（如 `QualityManager`）的 `__getattr__` 转发到 canvas；写属性时只有列在 `_owned_names` 的名字落在协作器自身，其余写回 canvas。给协作器加新自有状态字段时**必须**同时加进 `_owned_names`。
- ui/ 文件已无同名方法重复定义问题，直接定点改即可。
- 行为红线见 spec §6。测试失败禁止弱化断言；先找根因。

**任务顺序即执行顺序**（A1-A10 性能，B1-B3 精简）。每任务一个 commit。

---

### Task 0: 建立测试文件骨架 + 基线

**Files:**
- Create: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 确认基线全绿**

```bash
cd "/Users/donghang/Downloads/data analyzer"
python -m pytest tests/ui -q
```

Expected: 全部 PASS（若基线已有失败，停下来报告，不要继续）。

- [ ] **Step 2: 创建共享测试骨架**

写入 `tests/ui/test_timedomain_hotpath_perf.py`：

```python
"""Hot-path "don't redo work" regression tests.

Each test pins one contract from
docs/superpowers/specs/2026-06-10-timedomain-plot-optimization.md (Wave A).
They assert on CALL COUNTS of internal seams, not on pixels: the
optimizations must make repeated/no-op invocations free without changing
any rendered output (rendered-output parity is covered by the existing
test_pg_timedomain_canvas.py suite).
"""
import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def _rows(n=3):
    """Channel rows in the MainWindow shape (name, visible, t, sig, color, unit, fid)."""
    t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
    waves = [
        ("speed", 1000.0 * np.sin(2 * np.pi * 5 * t), "#1769e0", "rpm"),
        ("torque", 50.0 + 5.0 * np.cos(2 * np.pi * 3 * t), "#ef4444", "Nm"),
        ("pressure", 0.2 * t + 0.1 * np.sin(2 * np.pi * 7 * t), "#00b894", "bar"),
        ("temp", 60.0 + 2.0 * np.cos(2 * np.pi * 1.5 * t), "#fbbf24", "C"),
    ]
    return [
        (name, True, t, sig, color, unit, "fid-1")
        for name, sig, color, unit in waves[:n]
    ]


def _make_canvas(qtbot, rows, mode):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    canvas.resize(600, 360)
    canvas.show()
    canvas.plot_channels(rows, mode=mode)
    canvas._flush_pending_refresh()
    return canvas
```

- [ ] **Step 3: 空跑确认骨架可收集**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -q
```

Expected: `no tests ran`（collected 0 items，无 import error）。

- [ ] **Step 4: Commit**

```bash
git add tests/ui/test_timedomain_hotpath_perf.py
git commit -m "test: scaffold hot-path perf regression suite"
```

---

### Task A1: quality 状态机——值不变不发射 + AA-off 幂等早退

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/quality.py`
- Test: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/ui/test_timedomain_hotpath_perf.py`：

```python
def test_repeated_quality_disable_emits_nothing_and_skips_scene_scan(
    qtbot, qapp, monkeypatch
):
    from mf4_analyzer.ui.pg_canvas.quality import QualityManager

    canvas = _make_canvas(qtbot, _rows(2), "subplot")
    canvas.disable_interactive_quality()  # settle into AA-off once (warm-up)

    emissions = []
    canvas.quality_status_changed.connect(lambda st: emissions.append(st))
    scans = []
    orig = QualityManager._density_status
    monkeypatch.setattr(
        QualityManager,
        "_density_status",
        lambda self: scans.append(1) or orig(self),
    )

    for _ in range(5):
        canvas.disable_interactive_quality()

    # Drag ticks 2..N: AA already off, idle timer already stopped — the
    # status cannot have changed, so no scene traversal and no emission.
    assert emissions == []
    assert scans == []
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_repeated_quality_disable_emits_nothing_and_skips_scene_scan -v
```

Expected: FAIL（emissions 有 5 条 / scans 非空）。

- [ ] **Step 3: 实现**

`quality.py` 四处修改。

(a) `_owned_names`（第 66-71 行）增加一项：

```python
    _owned_names = frozenset({
        "aa_on",
        "density_allowed",
        "density_seeded",
        "last_emitted_status",
        "timer",
    })
```

(b) `__init__`（第 86-94 行）末尾两行替换为三行（前两行是既有内容，仅新增第三行）：

```python
        self.density_allowed = False
        self.density_seeded = False
        self.last_emitted_status = None
```

(c) `disable_interactive_quality`（第 148-167 行）整体替换为：

```python
    def disable_interactive_quality(self):
        """Force the interactive path back to AA-off and cancel idle upgrade."""
        timer_was_active = False
        try:
            timer_was_active = self.timer.isActive()
            self.timer.stop()
        except Exception:
            pass
        if not self.aa_on:
            # Hot path: every pan/zoom mouse tick after the first lands here
            # with AA already off. Only a just-cancelled idle timer can have
            # changed the reader-facing status (yellow -> red); otherwise the
            # status is exactly what the last emit reported, so skip the
            # rebuild — quality_status() walks the scene twice per call.
            if timer_was_active:
                self._emit_quality_status_changed()
            return
        self._set_curves_antialias(False)
        # Fix D: a stale device-coordinate cache would smear during the
        # pan/zoom that this call precedes. Clear unconditionally so no stale
        # cache survives mode switches.
        self._set_curves_cache_mode(QGraphicsItem.NoCache)
        self.aa_on = False
        try:
            self._glw.update()
        except Exception:
            pass
        self._emit_quality_status_changed()
```

(d) `_emit_quality_status_changed`（第 338-342 行）整体替换为：

```python
    def _emit_quality_status_changed(self):
        try:
            status = self.quality_status()
            if status == self.last_emitted_status:
                return
            self.last_emitted_status = status
            self.quality_status_changed.emit(status)
        except Exception:
            pass
```

(e) `reset_for_rebuild`（第 96-107 行）在 `self.density_seeded = False` 之后、emit 之前加一行（重建后曲线集变了，强制下一次重新发射）：

```python
        self.last_emitted_status = None
```

- [ ] **Step 4: 跑新测试 + quality 相关既有测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "quality or aa or idle"
python -m pytest tests/ui/test_chart_stack.py -q
```

Expected: 全 PASS。若既有测试断言「每次调用都发射」，那是在锁实现细节而非行为——检查该测试意图后把它改为断言最终状态（并在 commit message 注明），不得反向放弃去重。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/quality.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(quality): dedupe status emissions; skip scene scans on no-op disable"
```

---

### Task A2: resize 重活全部并入 settle pass

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（`resizeEvent` ~:1993、`_on_resize_settled` ~:2025）
- Test: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 写失败测试**

```python
def test_resize_defers_label_rework_to_settle(qtbot, qapp):
    canvas = _make_canvas(qtbot, _rows(2), "subplot")
    assert canvas._subplot_label_specs  # precondition: labels exist

    calls = []
    canvas._recheck_subplot_label_placement = lambda: calls.append(1)
    canvas.resize(640, 400)
    qapp.processEvents()
    # resizeEvent itself must NOT tear down / rebuild label TextItems.
    assert calls == []
    canvas._on_resize_settled()
    # The settle pass does it exactly once.
    assert calls == [1]
```

- [ ] **Step 2: 确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_resize_defers_label_rework_to_settle -v
```

Expected: FAIL（resizeEvent 同步调用了 recheck，`calls == [1]` 在第一个 assert 处炸）。

- [ ] **Step 3: 实现**

(a) `resizeEvent`（canvas.py:1993-2023）整体替换为：

```python
    def resizeEvent(self, event):
        """Defer ALL resize-driven recompute to the 40 ms settle pass.

        The inside/outside label recheck tears down and rebuilds TextItems
        and the axis-width unification re-runs a full layout activation;
        doing that synchronously for every intermediate size while the user
        drags the window border doubled the resize work (the settle pass
        below repeated both). resizeEvent now only invalidates the idle-AA
        density seed and arms the settle timer; _on_resize_settled does the
        label recheck, retick, axis unification and envelope refresh once.
        """
        try:
            super().resizeEvent(event)
        finally:
            # Fix C (2026-05-31): the plot-area width just changed, so the
            # idle-AA density budget and envelope point count are stale.
            try:
                self._quality.density_seeded = False
                self._resize_settle_timer.start()
            except Exception:
                pass
```

(b) `_on_resize_settled`（canvas.py:2025-2062）在 `self._refresh_overlay_axis_labels()` 的 try 块**之后**、`_apply_target_x_ticks_to_all_axes` 的 try 块**之前**插入（保持旧 resizeEvent 中「先 label 后 unify」的相对顺序）：

```python
        try:
            if self._subplot_label_specs:
                self._recheck_subplot_label_placement()
        except Exception:
            pass
```

- [ ] **Step 4: 跑测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "resize or label or inside"
python -m pytest tests/ui/test_canvas_compactness.py -q
```

Expected: 全 PASS。若既有测试在 `canvas.resize(...)` 后立刻断言 label 已翻转（同步时序假设），在该测试中补一行 `canvas._on_resize_settled()` 再断言（行为不变，时序后移 40ms），commit message 注明。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(canvas): move resize label/axis rework into the settle pass"
```

---

### Task A3: X 刻度计算记忆化

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/tick_density.py`
- Test: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 写失败测试**

```python
def test_x_tick_computation_memoized_across_rows_and_ticks(qtbot, qapp, monkeypatch):
    from mf4_analyzer.ui.pg_canvas.tick_density import TickDensityController

    canvas = _make_canvas(qtbot, _rows(3), "subplot")
    ctrl = canvas._tick_density_controller

    calls = []
    orig = TickDensityController._compute_target_x_ticks
    monkeypatch.setattr(
        TickDensityController,
        "_compute_target_x_ticks",
        lambda self, *a: calls.append(1) or orig(self, *a),
    )

    ctrl.ticks_cache.clear()
    ctrl._apply_target_x_ticks_to_all_axes()
    # 3 subplot rows share one (xlim, axis_width, density) key after axis
    # unification -> at most one real computation.
    assert len(calls) <= 1

    calls.clear()
    ctrl._apply_target_x_ticks_to_all_axes()
    # Identical viewport (a debounce tick with unchanged xlim): pure cache.
    assert calls == []
```

- [ ] **Step 2: 确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_x_tick_computation_memoized_across_rows_and_ticks -v
```

Expected: FAIL（`ticks_cache` 属性不存在，AttributeError——注意 `_CanvasBackref.__getattr__` 会把未知属性转发到 canvas 再 raise）。

- [ ] **Step 3: 实现**

`tick_density.py` 三处修改。

(a) `_owned_names`（第 65 行）：

```python
    _owned_names = frozenset({"density", "ticks_cache"})
```

(b) `__init__`（第 82-85 行）加：

```python
        self.ticks_cache = {}
```

(c) `_apply_target_x_ticks`（第 135-150 行）整体替换为：

```python
    def _apply_target_x_ticks(self, axis, handle):
        try:
            lo, hi = handle.get_xlim()
            axis_width = float(axis.size().width())
        except Exception:
            self._reset_x_ticks_to_adaptive(axis)
            return
        # Memoize per (xlim, width, density): subplot rows are pinned to the
        # SAME xlim (sibling propagation) and the SAME axis width (axis
        # unification), so N rows recomputing the ~30-candidate nice-step
        # search + per-label QFontMetrics measurement N times per debounce
        # tick was pure waste. Empty results are cached too. The key fully
        # determines the output (tickStrings/format depend only on values
        # and spacing), so no invalidation hook is needed; the dict is
        # size-capped instead.
        key = (float(lo), float(hi), round(axis_width, 1), int(self.density[0]))
        ticks = self.ticks_cache.get(key)
        if ticks is None:
            ticks = self._compute_target_x_ticks(
                axis, float(lo), float(hi), axis_width
            )
            if len(self.ticks_cache) > 32:
                self.ticks_cache.clear()
            self.ticks_cache[key] = ticks
        if not ticks:
            self._reset_x_ticks_to_adaptive(axis)
            return
        try:
            axis.setStyle(maxTickLevel=0)
            axis.setTicks([ticks, []])
        except Exception:
            self._reset_x_ticks_to_adaptive(axis)
```

- [ ] **Step 4: 跑测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "tick or density"
python -m pytest tests/ui/test_inspector.py -q
```

Expected: 全 PASS。若第一个断言因各行 bottom 轴宽度有亚像素差而成 2-3 次 compute，把断言放宽为 `len(calls) == len({round(...,1) for ...})` 之前，先核实宽度是否真的不同（打印 `axis.size().width()`），并把发现记入 commit message——不要无脑放宽。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/tick_density.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(ticks): memoize target X-tick computation per (xlim,width,density)"
```

---

### Task A4: refresh 尾部闸门 + reset_view 去重复 flush

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/renderer.py`（`_refresh_visible_data` :149-201）
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（init ~:314、`clear()` ~:1071、`invalidate_envelope_cache` ~:1433、`reset_view_to_data_extents` ~:855）
- Test: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 写失败测试**

```python
def test_repeated_flush_with_same_xlim_skips_tail_work(qtbot, qapp, monkeypatch):
    from mf4_analyzer.ui.pg_canvas.tick_density import TickDensityController

    canvas = _make_canvas(qtbot, _rows(2), "subplot")  # helper already flushed once

    emitted = []
    canvas.xrange_changed.connect(lambda lo, hi: emitted.append((lo, hi)))
    reticks = []
    monkeypatch.setattr(
        TickDensityController,
        "_apply_target_x_ticks_to_all_axes",
        lambda self: reticks.append(1),
    )

    canvas._flush_pending_refresh()
    canvas._flush_pending_refresh()

    # Same xlim + same pixel width + every channel gated by its range key:
    # the tail (retick + xrange/visible_range emits + quality emit) must not run.
    assert emitted == []
    assert reticks == []
```

- [ ] **Step 2: 确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_repeated_flush_with_same_xlim_skips_tail_work -v
```

Expected: FAIL（每次 flush 都 emit + retick）。

- [ ] **Step 3: 实现**

(a) canvas.py ~:314，`self._last_range_key: dict = {}` 之后加：

```python
        # (xlim_lo, xlim_hi, pixel_width) of the last _refresh_visible_data
        # that ran its tail (retick + range signals). Lets a flush whose every
        # channel hit the range-key gate skip the tail entirely.
        self._last_refresh_signature = None
```

(b) canvas.py `clear()` ~:1071，`self._last_range_key.clear()` 之后加：

```python
        self._last_refresh_signature = None
```

(c) canvas.py `invalidate_envelope_cache` 全清分支（~:1433-1436）改为：

```python
        if data_id is None and channel is None:
            self._curve_path_cache.clear()
            self._last_range_key.clear()
            self._last_refresh_signature = None
            return
```

(d) renderer.py `_refresh_visible_data`：循环内 `self._last_range_key[name] = range_key`（:189）后加一行 `updated_any = True`，循环前（`for name, ...` 之前）加 `updated_any = False`；尾部（:196-201）替换为：

```python
        # Debounced tail work: retick axes and notify listeners only once after
        # rapid drag ticks settle, instead of blocking every mouse-move event.
        signature = (float(xlim[0]), float(xlim[1]), int(pixel_width))
        if not updated_any and signature == self._last_refresh_signature:
            # Every channel hit its range-key gate and the viewport is
            # byte-identical to the last flush: retick + the xrange/visible
            # emits (inspector spinboxes, view_bridge ylim capture) and the
            # quality emit would all be no-ops for their listeners. Skip.
            return
        self._last_refresh_signature = signature
        self._tick_density_controller._apply_target_x_ticks_to_all_axes()
        self._emit_xrange_changed()
        self._refresh = True
        self.schedule_idle_quality()
```

（`_last_refresh_signature` 的读写经 `_CanvasBackref` 透明转发到 canvas，无需加 owned names。）

(e) canvas.py `reset_view_to_data_extents`：删除 try 体内的第一次 flush（:859-864 的注释块 + try/except），即把

```python
            self._set_xrange_to_data_union()
            # (2) Drain the debounced refresh scheduled by the X mutation so
            # the visible curve holds the global-window envelope.
            try:
                self._flush_pending_refresh()
            except Exception:
                pass
            # (3) Set Y per handle from the RAW channel data (full, finite),
```

改为：

```python
            self._set_xrange_to_data_union()
            # (2) Set Y per handle from the RAW channel data (full, finite),
```

并把该方法 docstring 中「set the X union FIRST, flush the debounced refresh ... THEN set Y from raw」一句改为：

```
        Ordering honors pyqt-ui/2026-04-25-flush-after-axis-mutation-not-
        before: set the X union and Y ranges first (all synchronous, no
        intermediate frame can paint), then the single try/finally tail
        flush drains the debounce so the frame after Home holds the
        global-window envelope.
```

后续的 `# (3)` 注释编号改 `# (2)`（保持注释序号连续即可）。

- [ ] **Step 4: 跑测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "reset_view or home or flush or refresh or xrange"
python -m pytest tests/ui/test_xlim_refresh.py -q
```

Expected: 全 PASS（`test_xlim_refresh.py` 若不存在则跳过该行——以 `ls tests/ui | grep xlim` 为准）。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/renderer.py mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(renderer): gate refresh tail on viewport signature; drop duplicate Home flush"
```

---

### Task A5: sibling 传播等值分支跳过轴 sync

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（`_propagate_xlim_to_siblings` :1586-1588）
- Test: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 写失败测试**

```python
def test_propagate_equal_ranges_skips_axis_item_sync(qtbot, qapp):
    canvas = _make_canvas(qtbot, _rows(3), "subplot")
    canvas._propagate_xlim_to_siblings()  # converge every sibling first

    calls = []
    canvas._sync_x_axis_item_range = lambda *a: calls.append(a)
    canvas._propagate_xlim_to_siblings()
    # All siblings already hold the exact range: zero AxisItem.setRange calls
    # (setRange unconditionally drops the tick picture even for equal values).
    assert calls == []
```

- [ ] **Step 2: 确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_propagate_equal_ranges_skips_axis_item_sync -v
```

Expected: FAIL（等值分支对每个 sibling 各调一次 sync）。

- [ ] **Step 3: 实现**

canvas.py :1586-1588，把

```python
            if cur_lo == float(lo) and cur_hi == float(hi):
                self._sync_x_axis_item_range(handle, lo, hi)
                continue
```

改为：

```python
            if cur_lo == float(lo) and cur_hi == float(hi):
                # Already identical — do NOT re-sync the AxisItem either:
                # pyqtgraph's AxisItem.setRange unconditionally invalidates
                # its tick picture (picture = None + update()) even for
                # equal values, which forced a per-tick label re-layout on
                # every sibling row during pan. The axis was synced when
                # this range was first pushed to the sibling.
                continue
```

- [ ] **Step 4: 跑测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "propagate or sibling or subplot"
```

Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(canvas): skip AxisItem re-sync when sibling range already equal"
```

---

### Task A6: monotonicity 跨重建指纹缓存

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（init ~:314、`invalidate_monotonicity_cache` :1458-1464、`full_reset` :1089-1095）
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py`（`_bind_channel` :386 + 新方法）
- Test: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 写失败测试**

```python
def test_monotonicity_cached_across_rebuilds(qtbot, qapp, monkeypatch):
    import mf4_analyzer.ui.pg_canvas.overlay_axes as oa

    calls = []
    orig = oa._is_monotonic_array
    monkeypatch.setattr(
        oa, "_is_monotonic_array", lambda t: calls.append(1) or orig(t)
    )

    rows = _rows(2)
    canvas = _make_canvas(qtbot, rows, "subplot")
    assert len(calls) == 2  # first build scans each channel once

    canvas.plot_channels(rows, mode="overlay")  # same arrays, new layout
    assert len(calls) == 2  # rebuild served from the fingerprint cache

    canvas.invalidate_monotonicity_cache()
    canvas.plot_channels(rows, mode="subplot")
    assert len(calls) == 4  # explicit invalidation forces a rescan
```

（说明：`build_envelope` 内部自己也会调 canvases 模块命名空间里的 `_is_monotonic_array`，但那是 `canvases.py` 的全局绑定，monkeypatch `oa.` 不影响它——这里只统计 bind 处的扫描。）

- [ ] **Step 2: 确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_monotonicity_cached_across_rebuilds -v
```

Expected: FAIL（第二次 plot_channels 后 `len(calls) == 4`）。

- [ ] **Step 3: 实现**

(a) canvas.py ~:314（`self._last_refresh_signature = None` 之后）加：

```python
        # (data_id, name, len, t[0], t[-1]) -> bool. Survives plot_channels
        # rebuilds (clear() does NOT touch it) so checking a channel on/off or
        # toggling 分/叠 does not rescan unchanged time arrays. The O(1)
        # fingerprint changes whenever the range filter slices a different
        # window or a custom X axis swaps the array; explicit invalidation
        # flows through invalidate_monotonicity_cache() / full_reset().
        self._monotonic_fingerprint_cache: dict = {}
```

(b) canvas.py `invalidate_monotonicity_cache`（:1458-1464）方法体末尾加：

```python
        self._monotonic_fingerprint_cache.clear()
```

(c) canvas.py `full_reset`（:1089-1095）在 `self._last_range_key.clear()` 后加：

```python
        self._monotonic_fingerprint_cache.clear()
```

(d) overlay_axes.py `_bind_channel` :386，把

```python
        self._channel_is_monotonic[name] = _is_monotonic_array(t_arr)
```

改为：

```python
        self._channel_is_monotonic[name] = self._cached_is_monotonic(
            data_id, name, t_arr
        )
```

(e) overlay_axes.py 在 `_bind_channel` 方法之后新增方法（同类内）：

```python
    def _cached_is_monotonic(self, data_id, name, t_arr):
        """Cross-rebuild monotonicity lookup keyed on a cheap fingerprint.

        plot_channels rebuilds run _bind_channel for every channel even when
        the underlying arrays did not change (checking a channel on/off,
        分/叠 toggles, tab switches) — previously a full np.diff scan per
        channel per rebuild. A wrong-but-cached False only downgrades
        positions_envelope to its numpy reference path (correct output,
        slower); a stale True cannot happen because the fingerprint pins
        length and both endpoints of the exact array bound.
        """
        try:
            n = int(len(t_arr))
            if n:
                key = (data_id, name, n, float(t_arr[0]), float(t_arr[-1]))
            else:
                key = (data_id, name, 0, 0.0, 0.0)
        except Exception:
            return _is_monotonic_array(t_arr)
        cache = self._monotonic_fingerprint_cache
        cached = cache.get(key)
        if cached is None:
            if len(cache) > 256:
                cache.clear()
            cached = bool(_is_monotonic_array(t_arr))
            cache[key] = cached
        return cached
```

- [ ] **Step 4: 跑测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "monotonic or envelope"
python -m pytest tests/ui/test_canvases_envelope.py tests/ui/test_envelope.py -q
```

Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/pg_canvas/overlay_axes.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(canvas): fingerprint-cache channel monotonicity across rebuilds"
```

---

### Task A7: 隐藏 stats_strip 不再做全量统计

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`（`_plot_time_on_canvas` :1718-1855）

本任务无新增单测（需要完整 MainWindow + 文件装载 fixture，性价比低）；回归由既有 smoke / stats 可见性套件覆盖，闸门逻辑一目了然。

- [ ] **Step 1: 实现**

(a) `_plot_time_on_canvas` 内、`data = []; st = {}`（:1807-1808）之前加：

```python
        from .chart_stack import _STATS_STRIP_ENABLED
        # The stats strip is disabled at the product level; computing
        # min/max/mean/rms/std/ptp over EVERY full channel array (plus the
        # sig**2 temporary) per replot fed a widget that is never visible.
        collect_stats = update_primary_ui and _STATS_STRIP_ENABLED
```

(b) 统计行（:1834-1835）改为：

```python
            if collect_stats:
                st[name] = {'min': np.min(sig), 'max': np.max(sig), 'mean': np.mean(sig), 'rms': np.sqrt(np.mean(sig ** 2)),
                            'std': np.std(sig), 'p2p': np.ptp(sig), 'unit': unit}
```

(c) 尾部（:1853-1855）改为：

```python
        if update_primary_ui:
            if collect_stats:
                self.chart_stack.stats_strip.update_stats(st)
            self.statusBar.showMessage(f"绘制: {len(checked)} 通道, {len(set(fid for fid, _, _ in checked))} 文件")
```

（:1840 空数据分支与 :1722/:1730 的 `update_stats({})` 清空调用**保留**，保证开关将来打开时清空行为不变。）

- [ ] **Step 2: 跑回归**

```bash
python -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_chart_stack_stats_visibility.py -q
python -m pytest tests/ui/test_chart_stack.py -q
```

Expected: 全 PASS。

- [ ] **Step 3: Commit**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "perf(main_window): skip per-channel full-array stats while stats strip is product-disabled"
```

---

### Task A8: 装载期拷贝消除

**Files:**
- Modify: `mf4_analyzer/io/loader.py`（:132、:136、:143、:147）
- Modify: `mf4_analyzer/io/file_data.py`（:33）
- Test: `tests/ui/test_timedomain_hotpath_perf.py`（FileData 共享内存测试，无 Qt 依赖）

- [ ] **Step 1: 写失败测试**

```python
def test_filedata_time_column_shares_memory_with_dataframe():
    import pandas as pd
    from mf4_analyzer.io.file_data import FileData

    df = pd.DataFrame({"time": np.arange(8.0), "a": np.arange(8.0)})
    fd = FileData("x.csv", df, list(df.columns), {}, 0)
    # The float64 time column must be exposed as a view, not an
    # astype(copy=True) duplicate of the full column.
    assert np.shares_memory(fd.time_array, df["time"].to_numpy(copy=False))
```

- [ ] **Step 2: 确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_filedata_time_column_shares_memory_with_dataframe -v
```

Expected: FAIL（`.values.astype(float)` 必拷贝 → shares_memory False）。

- [ ] **Step 3: 实现**

(a) file_data.py :33，把

```python
                self.time_array = df[ch].values.astype(float)
```

改为：

```python
                # View, not copy: consumers treat time_array as read-only
                # (documented at the main_window plot path).
                self.time_array = df[ch].to_numpy(copy=False).astype(float, copy=False)
```

(b) loader.py 主分支 :132 与 except 分支 :143，把

```python
                    sigs[ch_name] = {'s': np.array(s, float), 't': np.array(sig.timestamps, float)}
```

改为（两处相同）：

```python
                    # asarray: zero-copy when asammdf already yields float64
                    # (flatten() above copies the >1-D case anyway).
                    sigs[ch_name] = {'s': np.asarray(s, dtype=np.float64), 't': np.asarray(sig.timestamps, dtype=np.float64)}
```

(c) loader.py 主分支 :136 与 except 分支 :147，把

```python
                        ref_ts = np.array(sig.timestamps, float)
```

改为（两处相同）：

```python
                        ref_ts = sigs[ch_name]['t']  # share, don't re-copy
```

- [ ] **Step 4: 跑测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/test_mf4_loader.py tests/ui/test_open_and_save_entry.py -q
python -m pytest tests/ui/test_main_window_smoke.py -q
```

Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/io/loader.py mf4_analyzer/io/file_data.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(io): drop three redundant full-array copies on load"
```

---

### Task A9: defer_first_frame——重建路径不再算全量 envelope

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（`plot_channels` :400、四处 `_bind_channel` 调用、`plot_channels_preserving_xlim` :711）
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py`（`_bind_channel` :346）
- Modify: `mf4_analyzer/ui/main_window.py`（`_plot_time_on_canvas` :1718、plot 调用 :1844、`_render_view_to_canvas` :659）
- Test: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 写失败测试**

```python
def test_preserving_rebuild_skips_full_range_bind_envelope(qtbot, qapp, monkeypatch):
    import mf4_analyzer.ui.pg_canvases as legacy

    calls = []
    orig = legacy.build_envelope
    monkeypatch.setattr(
        legacy, "build_envelope", lambda *a, **k: calls.append(1) or orig(*a, **k)
    )

    rows = _rows(2)
    canvas = _make_canvas(qtbot, rows, "overlay")
    assert len(calls) == 2  # plain plot_channels still binds the first frame

    calls.clear()
    canvas.plot_channels_preserving_xlim(rows, mode="subplot")
    # Deferred bind: the restore+flush right after the build paints the first
    # frame from the viewport envelope; the full-range bind envelope is gone.
    assert calls == []
    for _axis, line in canvas._channel_lines.values():
        xd, _yd = line.plot_data_item.getData()
        assert xd is not None and len(xd) > 0
```

- [ ] **Step 2: 确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_preserving_rebuild_skips_full_range_bind_envelope -v
```

Expected: FAIL（preserving 路径仍每通道调一次 `build_envelope`，`calls == [1, 1]`）。

- [ ] **Step 3: 实现 — overlay_axes.py `_bind_channel`**

签名（:346）改为：

```python
    def _bind_channel(self, axis_handle, name, t, sig, color, unit, data_id, *, xlabel=None, skip_envelope=False):
```

envelope 块（:351-362）改为：

```python
        if skip_envelope:
            # plot_channels(defer_first_frame=True): the caller guarantees an
            # xlim restore + flush right after the build, whose viewport
            # envelope immediately overwrites whatever we bind here. Skip the
            # full-range envelope (O(n_total) per channel, never painted).
            bind_t = bind_s = np.empty(0, dtype=np.float64)
        else:
            try:
                from mf4_analyzer.ui import pg_canvases as legacy_pg_canvases
                envelope_builder = legacy_pg_canvases.build_envelope
            except Exception:
                from mf4_analyzer.ui.canvases import build_envelope as envelope_builder
            bind_t, bind_s = envelope_builder(
                np.asarray(t),
                np.asarray(sig),
                xlim=None,
                pixel_width=self._initial_bind_pixel_width(axis_handle),
                is_monotonic=None,
            )
```

- [ ] **Step 4: 实现 — canvas.py `plot_channels`**

(a) 签名（:400）改为：

```python
    def plot_channels(self, ch_list, mode="overlay", xlabel="Time (s)", defer_first_frame=False):
```

docstring 末尾补一段：

```
        ``defer_first_frame=True`` binds empty curve stubs instead of the
        full-range envelope; ONLY pass it when an xlim restore + flush
        follows the build (plot_channels_preserving_xlim / MainWindow's
        view-render path). A debounced refresh is armed as a safety net so
        a skipped restore still paints one timer tick later.
```

(b) 四处 `_bind_channel(...)` 调用各补 `skip_envelope=defer_first_frame`：

- subplot 循环（:437-440）：

```python
                self._overlay_axes._bind_channel(
                    handle, name, t, sig, color, unit, data_id,
                    xlabel=xlabel if i == len(vis) - 1 else None,
                    skip_envelope=defer_first_frame,
                )
```

- overlay 第一通道（:491）：

```python
            self._overlay_axes._bind_channel(
                first_handle, *vis[0], xlabel=xlabel,
                skip_envelope=defer_first_frame,
            )
```

- overlay 其余通道（:496-505）：在 `xlabel=xlabel,` 之后加 `skip_envelope=defer_first_frame,`。
- single 分支（:527-536）：同样在 `xlabel=xlabel,` 之后加 `skip_envelope=defer_first_frame,`。

(c) build 尾部 `self.schedule_idle_quality()`（:580）之后、cursor 恢复块之前加：

```python
        if defer_first_frame:
            # Safety net: the bind stage shipped empty stubs. The caller's
            # restore+flush paints the real first frame; if that restore is
            # skipped (no captured xlim / no overlap), this debounced refresh
            # still fills the curves at the data-union window one tick later.
            self._refresh_pending = True
            self._refresh_timer.start()
```

(d) `plot_channels_preserving_xlim`（:711-725）body 改为：

```python
        cur_xlim = self._capture_primary_xlim()
        self.plot_channels(
            ch_list, mode=mode, xlabel=xlabel,
            defer_first_frame=(cur_xlim is not None),
        )
        if cur_xlim is not None:
            self._restore_primary_xlim(cur_xlim)
```

- [ ] **Step 5: 实现 — main_window.py**

(a) `_plot_time_on_canvas` 签名（:1718）改为：

```python
    def _plot_time_on_canvas(self, canvas, update_primary_ui=True, defer_first_frame=False):
```

(b) plot 调用（:1844）改为：

```python
        canvas.plot_channels(data, mode, xlabel=xlabel, defer_first_frame=defer_first_frame)
```

(c) `_render_view_to_canvas`（:659）改为：

```python
            self._plot_time_on_canvas(
                canvas,
                update_primary_ui=update_primary_ui,
                defer_first_frame=(state.xlim is not None),
            )
```

（:660 的 `canvas.restore_visible_xlim(state.xlim)` 在 xlim 非 None 时必然走 `_restore_primary_xlim` → `_flush_pending_refresh`，即第一帧；`plot_time()` 直接路径保持默认 False——`_set_xrange_to_data_union` blockSignals 不调度刷新，bind envelope 就是首帧，不能跳。）

- [ ] **Step 6: 跑测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
python -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_chart_stack.py -q
```

Expected: 全 PASS（:3972/:3995 两个 preserving 既有用例现在走新 defer 路径，必须绿）。

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/pg_canvas/overlay_axes.py mf4_analyzer/ui/main_window.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(canvas): defer first frame on preserving rebuilds — skip full-range bind envelope"
```

---

### Task A10: overlay cursor 竖线 3N → 3

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/cursor.py`（`_ensure_cursor_items` :261-281 + 新 helper）
- Test: `tests/ui/test_timedomain_hotpath_perf.py`

- [ ] **Step 1: 先核实竖线消费方都与长度无关**

```bash
grep -n "_cursor_line_items\|_cursor_a_items\|_cursor_b_items" mf4_analyzer/ui/pg_canvas/*.py mf4_analyzer/ui/*.py
```

Expected: 命中仅限 cursor.py 的 ensure/hide/set_pos/remove/clear/属性 getter、canvas.py 的恢复调用（:582-592）与 characterization 测试的属性名列表。若发现按 `len(items) == len(axes_list)` 配对消费的代码，停下评估后再继续。

- [ ] **Step 2: 写失败测试**

```python
def test_overlay_uses_single_cursor_line_item(qtbot, qapp):
    canvas = _make_canvas(qtbot, _rows(3), "overlay")
    items = canvas._cursor._ensure_cursor_items("_cursor_line_items", color="#1769e0")
    # Overlay aux ViewBoxes all share one full-plot rect and one X transform:
    # one line on the X-master covers every channel (was: N identical lines).
    assert len(items) == 1

    canvas.plot_channels(_rows(3), mode="subplot")
    items = canvas._cursor._ensure_cursor_items("_cursor_line_items", color="#1769e0")
    assert len(items) == 3  # subplot keeps one per row (rows do not overlap)
```

- [ ] **Step 3: 确认失败**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py::test_overlay_uses_single_cursor_line_item -v
```

Expected: FAIL（overlay 下 `len(items) == 3`）。

- [ ] **Step 4: 实现**

cursor.py，在 `_ensure_cursor_items` 前加 helper，并改写 `_ensure_cursor_items`：

```python
    def _cursor_line_handles(self):
        """ViewBox owners for the vertical cursor/hover lines.

        Overlay mode: every aux ViewBox is pinned to the same full-plot rect
        and the same X transform, so N per-channel lines rendered at one
        identical screen position; a single line on the X-master is visually
        byte-identical and removes N-1 items from every repaint. Subplot
        rows have disjoint rects and keep one line each. Y-value items
        (dual-cursor extreme markers) must NOT use this — they live in each
        channel's own Y coordinate system.
        """
        if self._overlay_mode and self._x_master_handle is not None:
            return [self._x_master_handle]
        return list(self.axes_list)

    def _ensure_cursor_items(self, attr_name, *, color, width=1.0, style=Qt.SolidLine):
        handles = self._cursor_line_handles()
        items = getattr(self, attr_name, [])
        if len(items) == len(handles):
            return items
        self._remove_cursor_items(items)
        pen = pg.mkPen(color=color, width=width, style=style)
        new_items = []
        for handle in handles:
            vb = handle.view_box
            if vb is None:
                continue
            line = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=pen)
            line.setZValue(1000)
            line.setVisible(False)
            try:
                vb.addItem(line, ignoreBounds=True)
                new_items.append(line)
            except Exception:
                pass
        setattr(self, attr_name, new_items)
        return new_items
```

（`_ensure_dual_cursor_extreme_markers` 一行都不改。）

- [ ] **Step 5: 跑测试**

```bash
python -m pytest tests/ui/test_timedomain_hotpath_perf.py -v
python -m pytest tests/ui/test_pg_timedomain_canvas.py -q -k "cursor or hover or dual"
python -m pytest tests/ui/test_pg_canvas_decomposition_characterization.py -q
```

Expected: 全 PASS。若有既有测试断言 overlay 下竖线数量 == 通道数，那是在锁「每 ViewBox 一根」的实现冗余——更新该断言为 1 并在 commit message 引用本 spec A10。

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/cursor.py tests/ui/test_timedomain_hotpath_perf.py
git commit -m "perf(cursor): single shared vertical cursor line in overlay mode (3N -> 3 items)"
```

---

### Task A-final: Wave A 全量回归

- [ ] **Step 1: 全 ui 套件**

```bash
python -m pytest tests/ui -q
```

Expected: 全 PASS。

- [ ] **Step 2: 全仓套件**

```bash
python -m pytest tests -q
```

Expected: 全 PASS。失败则用 superpowers:systematic-debugging 找根因后修复并 commit。

---

### Task B1: 高确定性死代码删除

**Files:**
- Modify: `mf4_analyzer/ui/_axis_interaction.py`、`ui/dialogs.py`、`ui/chart_stack.py`、`ui/main_window.py`、`ui/markup/editor.py`、`ui/pg_canvas/canvas.py`、`ui/view_state.py`、`ui/file_navigator.py`、`ui/drawers/batch/input_panel.py`、`ui/drawers/batch/pipeline_strip.py`、`ui/widgets/__init__.py`

行号会因 Wave A 漂移——**按符号定位，删除前逐项 grep 复核为零生产引用**。

- [ ] **Step 1: 逐项验证 + 删除**

对下表每一项执行 `grep -rn "<symbol>" mf4_analyzer tests scripts "MF4 Data Analyzer V1.py"`，确认除定义处外零命中（或仅命中允许保留的位置），然后删除整个 def/class 块：

| 符号 | 文件 | 注意 |
|---|---|---|
| `edit_axis_dialog` | `ui/_axis_interaction.py` | 连同其 import 的 `AxisEditDialog` 引用 |
| `AxisEditDialog` | `ui/dialogs.py` | 在上一项之后删；顺带删 :34 的 `MplAxisHandle` 死 import |
| `mount_view_tabbar` | `ui/chart_stack.py`（TimeChartCard） | **保留 `self.view_tabbar = None` 那一行**（tests/ui/test_split_container.py:47、test_view_tabbar_mount.py:15 断言它） |
| `take_time_hint_bar` | `ui/chart_stack.py`（ChartStack） | 生产只用 `take_hint_bar` |
| `close_active` | `ui/main_window.py` | 无 action/快捷键接线 |
| `_on_span` | `ui/main_window.py` | `span_selected` 信号全仓无 `.connect`；`inspector_sections.set_range_from_span` 变成仅测试引用——**本批不删它** |
| `_apply_style` | `ui/markup/editor.py`（MarkupEditor） | 调用方都用 `_apply_style_to`；顺带删 :7 死 import `QFont` |
| `_position_inside_label_items` | `ui/pg_canvas/canvas.py` | 复数版；单数 `_position_inside_label_item` 是活的，别删错 |
| `has_split_pair` | `ui/view_state.py`（ViewManager） | 调用方都用 `partner_for` |
| `fullText` | `ui/file_navigator.py`（_ElidedLabel） | 非 Qt 虚函数 |
| `set_files_source` | `ui/drawers/batch/input_panel.py` | `_files_source` 构造期赋值仍保留 |

- [ ] **Step 2: pyflakes 清理（白名单内）**

```bash
python -m pyflakes mf4_analyzer/ui/main_window.py mf4_analyzer/ui/dialogs.py mf4_analyzer/ui/markup/editor.py mf4_analyzer/ui/drawers/batch/pipeline_strip.py mf4_analyzer/ui/widgets/__init__.py
```

（pyflakes 不在则 `python -m pip install pyflakes`。）只删它报出的 F401 未用 import 与 F841 未用赋值（pipeline_strip.py 的 `title_row`、widgets/__init__.py 的 `fid`）。**绝对不碰**：`pg_canvas/*` 的 `from . import _binding`、`pg_canvas/canvas.py` 的 `positions_envelope`/`build_envelope` re-export、`pg_canvases.py` 的全部 import（shim 契约）。

- [ ] **Step 3: 全量回归**

```bash
python -m pytest tests/ui -q
```

Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add -A mf4_analyzer/ui
git commit -m "refactor(ui): delete verified-dead methods and unused imports (~120 lines)"
```

---

### Task B2: `_CanvasBackref` 六合一

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/_backref.py`
- Modify: `annotations.py`、`cursor.py`、`overlay_axes.py`、`quality.py`、`renderer.py`、`tick_density.py`（均在 `mf4_analyzer/ui/pg_canvas/`）

- [ ] **Step 1: 确认无外部按模块路径引用**

```bash
grep -rn "_CanvasBackref\|_MISSING" tests scripts | grep -v Binary
```

Expected: 零命中（已验证；若有，停下评估）。

- [ ] **Step 2: 创建 `_backref.py`**

内容 = quality.py 现有的超集版本，原样搬运：

```python
"""Shared delegate-to-canvas base for pg_canvas collaborator objects.

Was copy-pasted verbatim into six collaborator modules during the Phase-4
decomposition; renderer.py carried a strict subset (no _owned_names branch),
which this superset reproduces exactly when a subclass leaves _owned_names
empty. Attribute reads check the canvas __dict__ first for names listed in
_delegate_names (the monkeypatch seam), then fall back to the collaborator;
writes land on the collaborator only for _owned_names/_delegate_names and
are forwarded to the canvas otherwise.
"""

_MISSING = object()


class _CanvasBackref:
    _delegate_names = frozenset()
    _owned_names = frozenset()

    def __init__(self, canvas):
        object.__setattr__(self, "_c", canvas)

    def __getattribute__(self, name):
        if name not in {
            "_c",
            "_delegate_names",
            "_owned_names",
            "__dict__",
            "__class__",
            "__getattr__",
            "__getattribute__",
            "__setattr__",
        }:
            delegate_names = object.__getattribute__(self, "_delegate_names")
            if name in delegate_names:
                canvas = object.__getattribute__(self, "_c")
                value = getattr(canvas, "__dict__", {}).get(name, _MISSING)
                if value is not _MISSING:
                    return value
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        if name == "_c":
            object.__setattr__(self, name, value)
            return
        owned_names = object.__getattribute__(self, "_owned_names")
        delegate_names = object.__getattribute__(self, "_delegate_names")
        if name in owned_names or name in delegate_names:
            object.__setattr__(self, name, value)
            return
        setattr(self._c, name, value)
```

- [ ] **Step 3: 六个模块替换**

每个模块删除本地的 `_MISSING = object()` 与 `class _CanvasBackref: ...` 整块，加 import：

```python
from ._backref import _CanvasBackref
```

注意：renderer.py 的本地版本没有 `_owned_names`——超集版在 `_owned_names` 为空 frozenset 时行为逐字节等价（`__setattr__` 的 owned 检查恒 False），无需任何适配。若某模块本地还引用 `_MISSING`（grep 确认），import 行改为 `from ._backref import _CanvasBackref, _MISSING`。

- [ ] **Step 4: 跑回归**

```bash
python -m pytest tests/ui/test_pg_canvas_decomposition_characterization.py tests/ui/test_pg_timedomain_canvas.py -q
python -m pytest tests/ui -q
```

Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas
git commit -m "refactor(pg_canvas): unify six verbatim _CanvasBackref copies into _backref.py"
```

---

### Task B3: `_subplot_ylabel_text` / `_view_state_channel_key` 双定义收敛

**Files:**
- Create: `mf4_analyzer/ui/pg_canvas/_shared.py`
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（:115-127 区域）、`mf4_analyzer/ui/pg_canvas/overlay_axes.py`（:42-54 区域）

- [ ] **Step 1: 创建 `_shared.py`**

```python
"""Helpers shared by canvas.py and overlay_axes.py.

Both modules carried verbatim copies (canvas cannot import from
overlay_axes or vice versa without a cycle: canvas imports
OverlayAxisManager). canvas.py must keep re-exporting
_view_state_channel_key as a module attribute — the pg_canvases shim
re-exports it from there (mf4_analyzer/ui/pg_canvases.py).
"""
import json

from mf4_analyzer.ui.canvases import _compact_axis_label


def _subplot_ylabel_text(name, unit):
    """Subplot left-axis label: compact channel name plus unit suffix."""
    compact = _compact_axis_label(name, unit, max_chars=20)
    return f"{compact}" + (f" ({unit})" if unit else "")


def _view_state_channel_key(data_id, name):
    stable_data_id = None if data_id is None else str(data_id)
    return json.dumps(
        [stable_data_id, str(name)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
```

先确认 `_compact_axis_label` 的来源与两份原拷贝一致：

```bash
grep -n "_compact_axis_label" mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/pg_canvas/overlay_axes.py | head
```

若任一文件是从别处 import 的，跟随该来源。

- [ ] **Step 2: 两边删本地定义、改 import**

canvas.py 删 :115-127 的两个函数定义，在 renderer import 块之后加：

```python
from mf4_analyzer.ui.pg_canvas._shared import (  # noqa: F401  (shim re-export)
    _subplot_ylabel_text,
    _view_state_channel_key,
)
```

overlay_axes.py 删 :42-54 的两个函数定义，加：

```python
from ._shared import _subplot_ylabel_text, _view_state_channel_key
```

- [ ] **Step 3: 验证 shim 链路完好 + 回归**

```bash
python -c "from mf4_analyzer.ui.pg_canvases import _view_state_channel_key; print(_view_state_channel_key('a','b'))"
python -m pytest tests/ui -q
```

Expected: 打印 `["a","b"]`；测试全 PASS。

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas
git commit -m "refactor(pg_canvas): single source for duplicated label/key helpers"
```

---

### Task FINAL: 收尾验证

- [ ] **Step 1: 全仓测试**

```bash
python -m pytest tests -q
```

Expected: 全 PASS。

- [ ] **Step 2: 行数核对（精简目标 G3）**

```bash
git diff --stat $(git merge-base HEAD main)..HEAD -- mf4_analyzer | tail -3
```

Expected: mf4_analyzer 净减 ≥300 行（B1+B2+B3 合计 ~330，扣除 Wave A 新增）。

- [ ] **Step 3: 手动性能抽查（非阻塞，记录数字即可）**

启动应用，载入一个多通道大文件（≥5 通道、≥1M 点）：

```bash
python "MF4 Data Analyzer V1.py"
```

对照 spec §6 检查：(a) 勾选/取消一个通道的延迟（预期明显下降）；(b) overlay 拖动流畅度；(c) 窗口拖边是否还有逐帧卡顿；(d) cursor/双 cursor 读数、Home（查看全部）、复制为图片全部正常。把观察写进最终汇报。

- [ ] **Step 4: 用 superpowers:finishing-a-development-branch 决定合并方式**
