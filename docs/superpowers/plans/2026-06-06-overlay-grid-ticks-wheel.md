# 叠加模式网格/刻度统一 + 纵向滚轮纠偏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让时域叠加模式的网格线与每通道刻度天然重合（整步长 graticule），网格密度由 inspector 的 Y 密度控件驱动，并修正纵向滚轮使其作用于选中通道、X 主轴 `[0,1]` 永不被动、无选中时给提示。

**Architecture:** 三层。① 纯函数层 `_nice_per_div` / `_frame_to_nice` / `_fmt_tick`（无 Qt 依赖，最易 TDD）。② `TimeDomainCanvasPG` 渲染层：用实例属性 `_overlay_divisions` 统一网格与刻度，`_repin_overlay_channel_ticks` 把每通道刻度钉到 `k/N` 网格线，`_handle_wheel_dispatch` 叠加纵向分支只动选中通道。③ `_ChartCard` 提示层：新信号 `overlay_y_needs_selection` → `flash_hint`。

**Tech Stack:** Python 3.12、PyQt5、pyqtgraph 0.14、pytest（offscreen Qt，`tests/ui/conftest.py` 的 `qapp` 会话 fixture）。

参照设计：`docs/superpowers/specs/2026-06-06-overlay-grid-ticks-wheel-design.md`。

---

## File Structure

- `mf4_analyzer/ui/pg_canvases.py` — 叠加渲染主体。新增模块级纯函数 + 实例属性 + 重钉方法 + 改 `_handle_wheel_dispatch`、`_build_overlay_y_grid`、`set_tick_density`、`_snap_overlay_channel_to_grid`、信号区。
- `mf4_analyzer/ui/chart_stack.py` — `_ChartCard` 连接新信号 + `flash_hint`。
- `mf4_analyzer/ui/inspector_sections.py` — `spin_yt` 默认值 6→8（一行）。
- `tests/ui/test_overlay_grid_ticks.py` — 新建：纯函数 + 重钉 + 滚轮分发的行为测试。
- `tests/ui/test_chart_stack.py` — 追加：`flash_hint` 提示行为。

约定（参照现有测试）：canvas 由 `_pg_canvas(qapp)`-风格构造（`TimeDomainCanvasPG()` → `resize(640,360)` → `show()` → `processEvents()`）；`plot_channels` 行元组为 7 元素 `(name, visible, t, sig, color, unit, data_id)`；叠加用 `mode="overlay"`。

---

## Task 1: 纯函数 `_nice_per_div` / `_frame_to_nice` / `_fmt_tick`

**Files:**
- Create: `tests/ui/test_overlay_grid_ticks.py`
- Modify: `mf4_analyzer/ui/pg_canvases.py`（模块级，紧邻 `_snap_y_to_divisions`，`pg_canvases.py:862` 附近）

- [ ] **Step 1: 写失败测试**

新建 `tests/ui/test_overlay_grid_ticks.py`：

```python
"""叠加模式整步长 graticule + 纵向滚轮纠偏的行为测试。

参照 docs/superpowers/plans/2026-06-06-overlay-grid-ticks-wheel.md。
纯函数测试不需要 Qt；canvas 测试用 conftest 的 qapp 会话 fixture。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from mf4_analyzer.ui import pg_canvases as pgc
from mf4_analyzer.ui.pg_canvases import _nice_per_div, _frame_to_nice, _fmt_tick


_NICE = pgc._NICE_STEP_MANTISSAS


def _mantissa(v):
    exp = math.floor(math.log10(v))
    return v / (10.0 ** exp)


class TestNicePerDiv:
    @pytest.mark.parametrize("raw, expected", [
        (1.0, 1.0),
        (1.013, 1.2),
        (1.35, 1.5),
        (2.01, 2.5),
        (8.01, 10.0),      # 尾数 8<mant<10 → 进位到下一个十年
        (0.013, 0.015),    # 小量级：尾数序列同样适用
        (130.0, 150.0),
    ])
    def test_returns_smallest_nice_ge_raw(self, raw, expected):
        got = _nice_per_div(raw)
        assert got == pytest.approx(expected, rel=1e-9)
        assert got >= raw - 1e-9

    def test_mantissa_always_in_nice_set(self):
        for raw in (0.07, 0.7, 3.3, 17.0, 410.0, 0.0009):
            got = _nice_per_div(raw)
            assert any(abs(_mantissa(got) - m) < 1e-6 for m in _NICE + [1.0])

    def test_nonpositive_and_nonfinite_return_none(self):
        assert _nice_per_div(0.0) is None
        assert _nice_per_div(-2.0) is None
        assert _nice_per_div(float("nan")) is None
        assert _nice_per_div(float("inf")) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestNicePerDiv -v`
Expected: FAIL — `ImportError: cannot import name '_nice_per_div'`。

- [ ] **Step 3: 实现纯函数**

在 `pg_canvases.py` 模块级（`_snap_y_to_divisions` 之后）新增。确认文件顶部已 `import math`；若无则补 `import math`（与现有 `import numpy as np` 同区）。

```python
# Nice-number graticule helpers (overlay grid/ticks unification,
# 2026-06-06 overlay-grid-ticks-wheel design §3 component A).
_NICE_STEP_MANTISSAS = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8]  # × 10^k


def _nice_per_div(raw):
    """Smallest nice number (mantissa in _NICE_STEP_MANTISSAS × 10^k)
    that is >= ``raw``. Returns None for non-positive / non-finite input."""
    if not (isinstance(raw, (int, float)) and math.isfinite(raw) and raw > 0):
        return None
    exp = math.floor(math.log10(raw))
    base = 10.0 ** exp
    mant = raw / base
    for s in _NICE_STEP_MANTISSAS:
        if s >= mant - 1e-9:
            return s * base
    return 10.0 * base


def _fmt_tick(value):
    """Compact tick label: integers without a decimal point, otherwise the
    shortest round-trip-ish decimal. Avoids widening the axis column."""
    if not math.isfinite(value):
        return ""
    if abs(value) >= 1e6 or (value != 0.0 and abs(value) < 1e-4):
        return f"{value:.2e}"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}"
    return f"{value:g}"


def _frame_to_nice(lo, hi, n):
    """Frame target window [lo, hi] into ``n`` equal divisions whose
    boundaries fall on nice numbers. Returns (bottom, top, ticks) where
    ticks has n+1 entries and [bottom, top] ⊇ [lo, hi].

    Uses (n-1) as the denominator so that a grid-aligned ``bottom``
    (floor to per_div) is provably wide enough to contain the data.
    """
    lo = float(lo)
    hi = float(hi)
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if not (span > 0) or not math.isfinite(span):
        c = (lo + hi) / 2.0
        if not math.isfinite(c):
            c = 0.0
        span = max(abs(c), 1.0)
        lo, hi = c - span / 2.0, c + span / 2.0
    denom = max(1, int(n) - 1)
    per_div = _nice_per_div(span / denom) or (span / denom)
    bottom = math.floor(lo / per_div) * per_div
    top = bottom + int(n) * per_div
    ticks = [bottom + k * per_div for k in range(int(n) + 1)]
    return bottom, top, ticks
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestNicePerDiv -v`
Expected: PASS（3 个测试 / 含参数化）。

- [ ] **Step 5: 追加 `_frame_to_nice` 含纳性 + 规整性测试并跑通**

在测试文件追加：

```python
class TestFrameToNice:
    @pytest.mark.parametrize("lo, hi, n", [
        (0.317, 8.42, 8),
        (-5.0, 5.0, 8),
        (-12.3, -1.1, 6),
        (0.0, 0.0, 8),          # 平信号退化
        (1e3, 1.0008e3, 10),    # 窄带高基线
        (-0.0008, 0.0009, 8),   # 小量级跨零
    ])
    def test_contains_and_nice(self, lo, hi, n):
        bottom, top, ticks = _frame_to_nice(lo, hi, n)
        assert bottom <= min(lo, hi) + 1e-9
        assert top >= max(hi, lo) - 1e-9
        assert len(ticks) == n + 1
        per_div = ticks[1] - ticks[0]
        # 每个 tick 都是 per_div 的整数倍（标签规整的充要条件）
        for v in ticks:
            ratio = v / per_div
            assert abs(ratio - round(ratio)) < 1e-6
        # 等距
        diffs = np.diff(ticks)
        assert np.allclose(diffs, diffs[0], rtol=1e-9)

    def test_concrete_example_matches_spec(self):
        bottom, top, ticks = _frame_to_nice(0.317, 8.42, 8)
        assert bottom == pytest.approx(0.0)
        assert top == pytest.approx(9.6)
        assert ticks == pytest.approx([0, 1.2, 2.4, 3.6, 4.8, 6.0, 7.2, 8.4, 9.6])
```

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py -v`
Expected: PASS（全部）。

- [ ] **Step 6: 提交**

```bash
git add tests/ui/test_overlay_grid_ticks.py mf4_analyzer/ui/pg_canvases.py
git commit -m "feat(overlay): nice-number graticule helpers (_nice_per_div/_frame_to_nice/_fmt_tick)"
```

---

## Task 2: `_overlay_divisions` 实例属性 + 网格用之 + inspector 默认 8

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（`_N_OVERLAY_DIVISIONS` 常量 `:160`、`__init__` 区 `:1091` 附近、`_build_overlay_y_grid` `:2043`、`set_tick_density` `:2812`）
- Modify: `mf4_analyzer/ui/inspector_sections.py:1520`
- Test: `tests/ui/test_overlay_grid_ticks.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
class TestOverlayDivisions:
    def _overlay(self, qapp, n_ch=2, npts=200):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, npts)
        rows = []
        for i in range(n_ch):
            sig = (i + 1) * np.sin(2 * np.pi * (i + 1) * t) + 0.3 * i
            rows.append((f"ch{i}", True, t, sig, "#1769e0", "u", f"fid-{i}"))
        canvas.plot_channels(rows, mode="overlay")
        return canvas

    def test_default_divisions_is_8(self, qapp):
        canvas = self._overlay(qapp)
        assert canvas._overlay_divisions == 8
        # 内部网格线 = N-1 条
        assert len(canvas._overlay_grid_lines) == 8 - 1

    def test_set_tick_density_drives_divisions_and_gridlines(self, qapp):
        canvas = self._overlay(qapp)
        canvas.set_tick_density(10, 12)
        assert canvas._overlay_divisions == 12
        assert len(canvas._overlay_grid_lines) == 12 - 1

    def test_density_clamped_to_3_20(self, qapp):
        canvas = self._overlay(qapp)
        canvas.set_tick_density(10, 99)
        assert canvas._overlay_divisions == 20
        canvas.set_tick_density(10, 1)
        assert canvas._overlay_divisions == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestOverlayDivisions -v`
Expected: FAIL — `AttributeError: '_overlay_divisions'` 或网格线数仍为 8-1（常量未联动）。

- [ ] **Step 3: 实现 — 常量改实例属性**

`pg_canvases.py:160` 删除 `_N_OVERLAY_DIVISIONS = 8 ...` 行（连注释保留为说明亦可，但不再被引用）。在 `__init__` 中（与 `self._overlay_grid_lines: list = []` 同区，`:1131` 附近）新增：

```python
        # Overlay graticule division count = inspector Y tick density.
        # Default 8 keeps grid + per-channel ticks aligned (see
        # 2026-06-06 overlay-grid-ticks-wheel design §3A).
        self._overlay_divisions = 8
```

`_build_overlay_y_grid`（`:2066`）把 `n = _N_OVERLAY_DIVISIONS` 改为：

```python
        n = self._overlay_divisions
```

- [ ] **Step 4: 实现 — `set_tick_density` 叠加分支**

`set_tick_density`（`:2812`）当前结尾调用 `_apply_tick_density_to_all_axes()` 等。改为在算出 `x_n, y_n` 后分叉：

```python
    def set_tick_density(self, x, y):
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except Exception:
            x_n, y_n = self._tick_density
        self._tick_density = (x_n, y_n)
        if getattr(self, "_overlay_mode", False):
            # 叠加：Y 密度 = 网格分格数；显式整步长刻度，跳过通用自适应 Y 密度。
            self._overlay_divisions = max(3, min(20, y_n))
            self._build_overlay_y_grid()
            self._repin_overlay_channel_ticks()
            self._apply_target_x_ticks_to_all_axes()
        else:
            self._apply_tick_density_to_all_axes()
            self._unify_subplot_left_axis_widths()
            self._unify_subplot_bottom_axis_heights()
        self._refresh = True
        self.draw_idle()
```

（`_repin_overlay_channel_ticks` 在 Task 3 定义；本任务先放一个安全占位：在类中加 `def _repin_overlay_channel_ticks(self): pass`，Task 3 再实现真体，使本任务可独立跑通。）

- [ ] **Step 5: 实现 — inspector 默认 8**

`inspector_sections.py:1520`：

```python
        self.spin_yt.setValue(8)
```

并把同行附近工具提示/注释保持一致即可（无需改 `setRange(3, 20)`）。

- [ ] **Step 6: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestOverlayDivisions -v`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py mf4_analyzer/ui/inspector_sections.py tests/ui/test_overlay_grid_ticks.py
git commit -m "feat(overlay): divisions follow inspector Y density (default 8)"
```

---

## Task 3: `_repin_overlay_channel_ticks` — 刻度钉到 k/N 网格

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（替换 Task 2 的占位实现；build 收尾 `:1321` 处调用）
- Test: `tests/ui/test_overlay_grid_ticks.py`

- [ ] **Step 1: 写失败测试 — 刻度落点 == k/N 屏幕分数**

追加。核心断言：把每通道 tick 值经其 aux ViewBox 映回 `[ylo,top]` 再归一化，应等于 `k/N`。

```python
class TestRepinTicks:
    def _overlay(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t) + 1.0, "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.4 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        return canvas

    def test_each_channel_ticks_align_to_divisions(self, qapp):
        canvas = self._overlay(qapp)
        canvas._repin_overlay_channel_ticks()
        n = canvas._overlay_divisions
        for handle in canvas.axes_list:
            lo, hi = handle.get_ylim()
            span = hi - lo
            assert span > 0
            axis = handle.y_axis_item()
            tick_levels = axis._tickLevels  # 显式 setTicks 后 pyqtgraph 缓存于此
            major = tick_levels[0]
            fracs = sorted(((v - lo) / span) for v, _label in major)
            expected = [k / n for k in range(n + 1)]
            assert fracs == pytest.approx(expected, abs=1e-6)

    def test_tick_values_are_nice_multiples(self, qapp):
        canvas = self._overlay(qapp)
        canvas._repin_overlay_channel_ticks()
        for handle in canvas.axes_list:
            axis = handle.y_axis_item()
            major = axis._tickLevels[0]
            vals = sorted(v for v, _l in major)
            per_div = vals[1] - vals[0]
            for v in vals:
                r = v / per_div
                assert abs(r - round(r)) < 1e-6
```

> 注：`axis_item()` / `y_axis_item()` 的可用性按 `PgAxisHandle` 实际 API 选一个；实现 Step 3 时以 `handle.axis_item` 暴露的真实方法为准（见 `_axis_handle.py`），必要时在测试里改成实际取 AxisItem 的方式。`_tickLevels` 是 pyqtgraph `AxisItem.setTicks` 后的内部缓存；若版本不暴露，改为断言 `handle.get_ylim()` 与 `_frame_to_nice` 一致 + 调用次数。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestRepinTicks -v`
Expected: FAIL — 占位 `pass` 未设刻度，`_tickLevels` 为空或不对齐。

- [ ] **Step 3: 实现 `_repin_overlay_channel_ticks`**

替换 Task 2 的占位。取每通道 handle 的当前 ylim，框成整步长，回写 ylim 并显式 setTicks：

```python
    def _repin_overlay_channel_ticks(self):
        """Frame every overlay channel's Y range to nice divisions and pin
        its AxisItem ticks onto the k/N graticule lines (design §3A)."""
        if not getattr(self, "_overlay_mode", False):
            return
        n = self._overlay_divisions
        for handle in self.axes_list:
            try:
                lo, hi = handle.get_ylim()
            except Exception:
                continue
            bottom, top, ticks = _frame_to_nice(lo, hi, n)
            try:
                handle.set_ylim(bottom, top)
            except Exception:
                continue
            axis = handle.y_axis_item()  # _axis_handle.py:735 → 该通道的 AxisItem
            if axis is None:
                continue
            try:
                axis.setTicks([[(v, _fmt_tick(v)) for v in ticks], []])
            except Exception:
                pass
```

`PgAxisHandle.y_axis_item()`（`_axis_handle.py:735`）对叠加 aux handle 返回构造时存入的 `_axis_item`（通道1=左轴、通道2+=追加右轴），与 `_add_overlay_axis_handle` 里 `axis_item=axis_item` 一致，无需额外助手。

- [ ] **Step 4: build 收尾处调用**

`plot_channels` 收尾（`:1321` `self._apply_tick_density_to_all_axes()` 之后、叠加分支内）追加一次重钉，使首帧即对齐：

```python
        if self._overlay_mode:
            self._repin_overlay_channel_ticks()
```

放在 `_apply_tick_density_to_all_axes()` 之后、`_unify_subplot_*` 之前的叠加判断里（参照 `:1316` 已有的 `if self._overlay_mode:` 块，可并入）。

- [ ] **Step 5: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestRepinTicks -v`
Expected: PASS。若 `_tickLevels` 不可用，按 Step 1 注释回退到 ylim/调用断言。

- [ ] **Step 6: 回归既有叠加测试**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_chart_stack.py -q`
Expected: PASS（X 稳定等既有断言不受影响）。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_overlay_grid_ticks.py
git commit -m "feat(overlay): pin per-channel ticks onto k/N graticule"
```

---

## Task 4: 纵向滚轮纠偏 — 只动选中通道，X 主轴永不被动

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（`_handle_wheel_dispatch` `:3782`；信号区 `:913`）
- Test: `tests/ui/test_overlay_grid_ticks.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
from PyQt5.QtCore import Qt


class TestOverlayWheel:
    def _overlay(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t), "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.5 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        return canvas

    def test_no_selection_shift_wheel_keeps_xmaster_locked(self, qapp):
        canvas = self._overlay(qapp)
        canvas.select_overlay_channel(None)
        emitted = []
        canvas.overlay_y_needs_selection.connect(lambda: emitted.append(1))
        xm = canvas._x_master_handle
        before_x = xm.get_xlim()
        consumed = canvas._handle_wheel_dispatch(
            delta=120.0, modifiers=Qt.ShiftModifier, x_pos=0.5, y_pos=0.5,
        )
        assert consumed is True                       # 吞掉，不落回基类
        assert xm.get_ylim() == pytest.approx((0.0, 1.0))   # 网格坐标系不动
        assert xm.get_xlim() == pytest.approx(before_x)
        assert emitted == [1]                         # 发了一次提示

    def test_selection_shift_wheel_zooms_only_that_channel(self, qapp):
        canvas = self._overlay(qapp)
        canvas.select_overlay_channel("ch0")
        ax0 = canvas._channel_lines["ch0"][0]
        ax1 = canvas._channel_lines["ch1"][0]
        y0_before = ax0.get_ylim()
        y1_before = ax1.get_ylim()
        x_before = canvas._x_master_handle.get_xlim()
        span0_before = y0_before[1] - y0_before[0]
        canvas._handle_wheel_dispatch(
            delta=120.0, modifiers=Qt.ShiftModifier, x_pos=0.5, y_pos=1.0,
        )
        span0_after = ax0.get_ylim()[1] - ax0.get_ylim()[0]
        assert span0_after < span0_before              # 放大 → 跨度变小
        assert ax1.get_ylim() == pytest.approx(y1_before)   # 别的通道不动
        assert canvas._x_master_handle.get_xlim() == pytest.approx(x_before)

    def test_selection_plain_wheel_pans_one_division(self, qapp):
        canvas = self._overlay(qapp)
        canvas.select_overlay_channel("ch0")
        ax0 = canvas._channel_lines["ch0"][0]
        lo0, hi0 = ax0.get_ylim()
        per_div = (hi0 - lo0) / canvas._overlay_divisions
        canvas._handle_wheel_dispatch(
            delta=120.0, modifiers=Qt.NoModifier, x_pos=0.5, y_pos=0.5,
        )
        lo1, hi1 = ax0.get_ylim()
        assert (lo1 - lo0) == pytest.approx(per_div, rel=1e-6)
        assert (hi1 - hi0) == pytest.approx(per_div, rel=1e-6)

    def test_ctrl_wheel_still_zooms_x(self, qapp):
        canvas = self._overlay(qapp)
        canvas.select_overlay_channel(None)
        xm = canvas._x_master_handle
        x_before = xm.get_xlim()
        canvas._handle_wheel_dispatch(
            delta=120.0, modifiers=Qt.ControlModifier, x_pos=0.5, y_pos=0.5,
        )
        assert xm.get_xlim() != pytest.approx(x_before)   # X 仍可缩放
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestOverlayWheel -v`
Expected: FAIL — `overlay_y_needs_selection` 不存在；且现状 shift 会改 X 主轴 ylim。

- [ ] **Step 3: 实现 — 新增信号**

`pg_canvases.py` 信号区（`overlay_channel_selected = pyqtSignal(object)` 旁，`:913`）：

```python
    overlay_y_needs_selection = pyqtSignal()
```

- [ ] **Step 4: 实现 — `_handle_wheel_dispatch` 叠加纵向分支**

在 `_handle_wheel_dispatch`（`:3782`）算出 `ctrl/shift/factor/step` 后，于 `try:` 块前插入叠加专用纵向分支（Ctrl 仍走原 X 缩放路径）：

```python
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        self.disable_interactive_quality()

        # 叠加模式：纵向（shift 缩放 / 普通平移）只作用于选中通道，
        # X 主轴 [0,1] 网格坐标系永不被动（design §3B）。
        if getattr(self, "_overlay_mode", False) and not ctrl:
            sel = self._selected_overlay_axes()
            if sel is None:
                self.overlay_y_needs_selection.emit()
                return True  # 吞掉，避免落回基类缩放 X 主轴
            try:
                lo, hi = sel.get_ylim()
            except Exception:
                return True
            n = self._overlay_divisions
            if shift:
                c = float(y_pos) if np.isfinite(y_pos) else (lo + hi) / 2.0
                new_lo = c - (c - lo) * factor
                new_hi = c + (hi - c) * factor
            else:
                per_div = (hi - lo) / n
                new_lo = lo + step * per_div
                new_hi = hi + step * per_div
            bottom, top, ticks = _frame_to_nice(new_lo, new_hi, n)
            try:
                sel.set_ylim(bottom, top)
                axis = sel.y_axis_item()
                if axis is not None:
                    axis.setTicks([[(v, _fmt_tick(v)) for v in ticks], []])
            except Exception:
                pass
            self._refresh = True
            self.draw_idle()
            self.schedule_idle_quality()
            return True

        target = self._axis_handle_for_view_box(view_box) or self._primary_xaxis_ax
        if target is None:
            return False
        # ……（以下原有 ctrl/shift/plain 逻辑保持不变，供 subplot/单图 + 叠加 Ctrl 用）
```

> 注意：`step`/`factor` 在现实现里于 `target` 解析之后才算。需把 `step = 1 if delta > 0 ...` 与 `factor = 0.85 ...` 两行**上移**到本分支之前（它们不依赖 `target`），或在分支内就地重算。实现时确保 `delta==0` 早退（`step==0` 返回 `False`）仍在最前。

- [ ] **Step 5: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestOverlayWheel -v`
Expected: PASS。

- [ ] **Step 6: 回归滚轮相关既有测试**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/ -k "wheel or overlay or chart_stack or timedomain" -q`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_overlay_grid_ticks.py
git commit -m "fix(overlay): vertical wheel targets selected channel, never the [0,1] graticule"
```

---

## Task 5: 「先选通道」提示（信号 → `flash_hint`）

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`（`_ChartCard` 信号连接 `:1271` 附近 + 新 `flash_hint`）
- Test: `tests/ui/test_chart_stack.py`

- [ ] **Step 1: 写失败测试**

`tests/ui/test_chart_stack.py` 追加（沿用该文件已有 qapp/卡片构造方式；下例用通用构造，落地时对齐文件内既有 helper）：

```python
def test_flash_hint_shows_then_restores(qapp):
    from mf4_analyzer.ui.chart_stack import _ChartCard
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    from PyQt5.QtCore import QCoreApplication
    canvas = TimeDomainCanvasPG()
    card = _ChartCard(canvas)
    card.resize(640, 360)
    card.show()
    QCoreApplication.processEvents()
    card.flash_hint("先选中一个通道，再用 Shift+滚轮缩放纵向")
    assert "先选中一个通道" in card._hint_context.text()
```

并加一个「信号触发提示」的连通性断言：

```python
def test_overlay_needs_selection_signal_flashes_hint(qapp):
    from mf4_analyzer.ui.chart_stack import _ChartCard
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    from PyQt5.QtCore import QCoreApplication
    canvas = TimeDomainCanvasPG()
    card = _ChartCard(canvas)
    card.show()
    QCoreApplication.processEvents()
    canvas.overlay_y_needs_selection.emit()
    QCoreApplication.processEvents()
    assert "先选中一个通道" in card._hint_context.text()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_chart_stack.py -k flash_hint -v`
Expected: FAIL — `flash_hint` 不存在 / 信号未连。

- [ ] **Step 3: 实现 `flash_hint` + 连接信号**

`_ChartCard.__init__` 中、已有 `overlay_channel_selected` 连接旁（`:1276` 附近）追加：

```python
        if hasattr(self.canvas, "overlay_y_needs_selection"):
            self.canvas.overlay_y_needs_selection.connect(
                lambda: self.flash_hint("先选中一个通道，再用 Shift+滚轮缩放纵向")
            )
        self._flash_hint_timer = QTimer(self)
        self._flash_hint_timer.setSingleShot(True)
        self._flash_hint_timer.setInterval(2500)
        self._flash_hint_timer.timeout.connect(lambda: self._set_context_hint(reset=True))
```

新增方法（与 `_set_context_hint` 同区，`:1169` 附近）：

```python
    def flash_hint(self, text):
        """Show a transient one-line hint in the context slot, then restore
        the rotating context hint after a short delay (debounced)."""
        self._hint_context.setText(text)
        self._flash_hint_timer.start()  # restart resets the 2.5s window
```

确认 `QTimer` 已在 `chart_stack.py` 顶部从 `PyQt5.QtCore` 导入（文件已用 `QTimer`，见 `:827`，无需新增导入）。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_chart_stack.py -k "flash_hint or needs_selection" -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_chart_stack.py
git commit -m "feat(overlay): flash 'select a channel' hint on no-selection vertical wheel"
```

---

## Task 6: 拖拽松手吸附 → 改用整步长 re-frame + 重钉

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（`_snap_overlay_channel_to_grid` `:2085` / 其调用点 `_handle_overlay_mouse_release` `:2761`）
- Test: `tests/ui/test_overlay_grid_ticks.py`

- [ ] **Step 1: 写失败测试**

追加：拖拽结束后，选中通道刻度应回到整步长且对齐网格。

```python
class TestDragSnap:
    def _overlay_selected(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [("ch0", True, t, 2.0 * np.sin(2 * np.pi * t), "#1769e0", "V", "fid-0")]
        canvas.plot_channels(rows, mode="overlay")
        canvas.select_overlay_channel("ch0")
        return canvas

    def test_release_reframes_to_nice(self, qapp):
        canvas = self._overlay_selected(qapp)
        ax0 = canvas._channel_lines["ch0"][0]
        # 人为制造一个非整步长窗口
        ax0.set_ylim(-1.731, 2.269)
        canvas._snap_overlay_channel_to_grid(ax0)
        lo, hi = ax0.get_ylim()
        n = canvas._overlay_divisions
        per_div = (hi - lo) / n
        # 边界为 per_div 整数倍
        assert abs(lo / per_div - round(lo / per_div)) < 1e-6
        assert abs(hi / per_div - round(hi / per_div)) < 1e-6
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestDragSnap -v`
Expected: FAIL — 现有 `_snap_overlay_channel_to_grid` 做的是场景坐标中心吸附，不保证整步长边界。

- [ ] **Step 3: 实现 — 替换吸附体**

把 `_snap_overlay_channel_to_grid`（`:2085`）的实现替换为整步长 re-frame（保留方法名与「退化几何静默 no-op」语义）：

```python
    def _snap_overlay_channel_to_grid(self, ax):
        """On drag release, re-frame the channel's Y range to nice
        divisions so ticks land back on the k/N graticule (design §3A/B)."""
        if ax is None:
            return
        try:
            lo, hi = ax.get_ylim()
        except Exception:
            return
        if not (hi - lo > 0):
            return
        bottom, top, ticks = _frame_to_nice(lo, hi, self._overlay_divisions)
        try:
            ax.set_ylim(bottom, top)
            axis = ax.y_axis_item()
            if axis is not None:
                axis.setTicks([[(v, _fmt_tick(v)) for v in ticks], []])
        except Exception:
            pass
```

> `_snap_y_to_divisions`（`:862`）若不再被任何调用点引用，可保留（无害）或在收尾任务删除；本任务不强制删。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_overlay_grid_ticks.py::TestDragSnap -v`
Expected: PASS。

- [ ] **Step 5: 回归既有拖拽/快照测试**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_pg_timedomain_canvas.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_overlay_grid_ticks.py
git commit -m "feat(overlay): drag-release snaps channel back to nice graticule"
```

---

## Task 7: 全量回归 + 真机视觉验证

**Files:**
- Create: `scripts/verify_overlay_grid_ticks.py`（手动可视化脚本，参照 `scripts/verify_secondary_cursor_toolbar.py` 风格）

- [ ] **Step 1: 全量 UI 测试回归**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/ -q`
Expected: PASS（无回归）。如失败，定位到具体既有断言修正（多半是 X 稳定/网格线计数断言需对齐新 N=8 默认）。

- [ ] **Step 2: 写可视化验证脚本**

`scripts/verify_overlay_grid_ticks.py`：构造 2–3 通道叠加，渲染并 `grab()` 截图到 `/tmp/overlay_grid_ticks.png`；打印每通道的 ylim 与刻度值，便于核对"刻度==网格线"。

```python
"""手动验证：叠加网格/刻度对齐 + 纵向滚轮纠偏。
用法：python scripts/verify_overlay_grid_ticks.py
产出：/tmp/overlay_grid_ticks.png + 控制台打印每通道刻度。
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 真机调试时去掉此行
import numpy as np
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QCoreApplication
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

app = QApplication.instance() or QApplication([])
c = TimeDomainCanvasPG(); c.resize(900, 480); c.show()
t = np.linspace(0, 1, 512)
rows = [
    ("电压", True, t, 2.0 * np.sin(2 * np.pi * t) + 1.0, "#1769e0", "V", "f0"),
    ("电流", True, t, 0.4 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "f1"),
]
c.plot_channels(rows, mode="overlay")
QCoreApplication.processEvents()
for h in c.axes_list:
    print("ylim:", h.get_ylim())
c.grab().save("/tmp/overlay_grid_ticks.png")
print("saved /tmp/overlay_grid_ticks.png")
```

- [ ] **Step 3: 真机视觉核对（非 offscreen）**

人工执行（去掉脚本里的 offscreen 行，或在真实环境运行主程序）并核对，对照设计 §5 视觉清单：
- 网格线与左/右各通道刻度逐条对齐、标签规整、填充不空旷（≥~80%）。
- 无选中时画面内 shift+滚轮：网格不变 + 出现"先选中一个通道…"提示。
- 选中通道后 shift/普通滚轮：仅该通道纵向缩放/平移，刻度随之重钉仍对齐。
- 拨动 inspector Y 密度（8↔更大）：网格线与刻度同步增减。

> 截图交用户确认（遵循"UI/视觉问题必须验真实渲染"）。

- [ ] **Step 4: 提交**

```bash
git add scripts/verify_overlay_grid_ticks.py
git commit -m "test(overlay): visual verification script for grid/ticks + wheel"
```

---

## Self-Review（写作者自查，已完成）

- **Spec 覆盖**：§3A 网格/刻度统一 → Task 1/2/3/6；§3B 纵向滚轮 → Task 4；§3C 提示 → Task 5；§4 受影响清单逐项有对应 Task；§5 测试 → 各 Task 测试 + Task 7 视觉；§6 风险 R1（退化几何 no-op）→ Task 6 守卫，R2（标签宽度）→ `_fmt_tick`，R3（X 稳定回归）→ Task 3/4/6 回归步，R4（提示去抖）→ Task 5 timer，R5（N 边界）→ Task 2 clamp。
- **占位扫描**：无 TBD/TODO；每个 code step 给出完整代码与精确命令/期望。
- **类型/命名一致**：`_overlay_divisions`、`_frame_to_nice(lo,hi,n)→(bottom,top,ticks)`、`_nice_per_div`、`_fmt_tick`、`_repin_overlay_channel_ticks`、`handle.y_axis_item()`、`overlay_y_needs_selection`、`flash_hint`、`_flash_hint_timer` 跨任务一致。
- **已知落地不确定点（实现时就地定夺，不阻塞）**：pyqtgraph `AxisItem._tickLevels` 是否可断言（Task 3 注释给了 ylim/调用断言的回退）。AxisItem 取法已钉死为 `handle.y_axis_item()`（`_axis_handle.py:735`）。
