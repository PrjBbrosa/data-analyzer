# FFT 时域预览：右轴对齐网格 + 刻度密度 + 工具栏补齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修好 FFT 时域预览（`PgLineCanvas._plot_time`）的三件事：(A) 左轴与各右轴统一框成 `n` 等分 nice 刻度、落在同一组水平网格线上，且 Y 刻度密度驱动 `n`（修右轴不对齐 + 密度对右轴无效）；(B) 标注扩展到下方时域图；(C) 返回/前进视图历史在 FFT 画布生效。

**Architecture:** A 复用纯函数 `ticks_math._frame_to_nice`/`_fmt_tick`，新增 `_reframe_time_y_to_grid()` 把主轴(曲线0/左轴)与每条 aux 右轴都框成 `n` 等分并钉死刻度；预览主 vb 承载第 0 条曲线，其左轴网格即 `k/n` graticule，右轴框成同 `n` 等分即对齐，无需额外 InfiniteLine。B 在 `_on_click`/`add_remark_at`/`remove_remark_near` 增加时域分支（overlay 按屏幕像素选最近点）。C 在 `PgLineCanvas` 侧补 `register_replot_callback` + `_channel_lines` 形态契约，让既有 `PgNavigationToolbar` 历史逻辑直接生效（不改工具栏、不碰 time domain）。

**Tech Stack:** PyQt5、pyqtgraph 0.14、pytest-qt、既有 `tests/ui/test_pg_line_canvas.py`（含 `canvas`/`qapp` 夹具）。

**配套 spec：** `docs/superpowers/specs/2026-06-14-fft-time-preview-axis-align-and-toolbar-design.md`

---

## 协调前置（必读）

- 本 plan 全部落在 `mf4_analyzer/ui/pg_canvas/line_canvas.py` + `tests/ui/test_pg_line_canvas.py`。
- 早前 codex 在该文件改折叠/分隔条（`_SplitDivider`），**当前代码已含其成果**。仍须执行前 `git log --oneline -5` + `git status` 确认该文件 clean、无在途改动，避免撞 hunk（`workflow-parallel-codex-same-worktree`）。
- 下文行号为 2026-06-14 快照、会漂移；**以函数/符号名定位**。
- 命令示例用 `.venv/bin/python -m pytest ... -q`；Windows 用 `.venv\Scripts\python -m pytest`，离屏加 `QT_QPA_PLATFORM=offscreen`。
- 范围可裁：若决定先不做 C，跳过 Task 3，A/B 自洽。

## File Structure

- `mf4_analyzer/ui/pg_canvas/line_canvas.py` — A：`_time_divisions` + `_reframe_time_y_to_grid()` + `set_tick_density` 改造 + 各重置/拟合/建曲线调用点；B：标注时域分支；C：`register_replot_callback`/`_run_replot_callbacks`/`_channel_lines` 契约。
- `tests/ui/test_pg_line_canvas.py` — 全部回归测试。

依赖（只读复用，不改）：`mf4_analyzer/ui/pg_canvas/ticks_math.py`（`_frame_to_nice`/`_fmt_tick`）；`mf4_analyzer/ui/chart_stack.py`（`PgNavigationToolbar`，仅在 C 的测试中作为被驱动方）。

---

## Task 1: A — Y 轴 nice 网格框定（右轴对齐 + 密度联动）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Test: `tests/ui/test_pg_line_canvas.py`

### 1a：`_reframe_time_y_to_grid` + 建曲线后对齐

- [ ] **Step 1: 写失败测试**

```python
def _overlay_entries():
    import numpy as np
    t = np.linspace(0.0, 10.0, 500)
    return [
        {'label': 'a', 'color': '#2563eb', 'freq': np.linspace(0, 50, 128),
         'amp': np.ones(128), 'time': t, 'signal': 0.04 * np.sin(t)},
        {'label': 'b', 'color': '#22c55e', 'freq': np.linspace(0, 50, 128),
         'amp': np.ones(128), 'time': t, 'signal': 1.0 * np.sin(t)},
        {'label': 'c', 'color': '#f59e0b', 'freq': np.linspace(0, 50, 128),
         'amp': np.ones(128), 'time': t, 'signal': 50.0 * np.sin(t)},
    ]


def _major_tick_values(axis):
    # pyqtgraph AxisItem: pinned ticks live in axis._tickLevels[0]
    levels = getattr(axis, '_tickLevels', None)
    assert levels, "axis has no pinned major ticks"
    return [v for v, _label in levels[0]]


def test_time_preview_axes_share_grid_divisions(canvas):
    canvas.set_tick_density(10, 8)            # n = 8
    canvas.plot_spectra(_overlay_entries(), xlim=(0.0, 50.0),
                        amp_label='Amplitude', title='t')
    import pytest
    left = canvas._plot_time.getAxis('left')
    rights = list(canvas._time_overlay_axes)
    assert len(rights) == 2
    # 每条轴都恰好 n+1 = 9 条 major 刻度
    for axis in (left, *rights):
        assert len(_major_tick_values(axis)) == 9
    # 每条轴刻度在各自 ViewBox 里的归一化位置序列一致 = 对齐到同一组网格线
    def fractions(axis, vb):
        (lo, hi) = vb.viewRange()[1]
        return [round((v - lo) / (hi - lo), 6) for v in _major_tick_values(axis)]
    base = fractions(left, canvas._plot_time.vb)
    for axis, vb in zip(rights, canvas._time_overlay_vbs):
        assert fractions(axis, vb) == pytest.approx(base, abs=1e-6)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_time_preview_axes_share_grid_divisions -q`
Expected: FAIL — 当前右轴是 autoRange、无钉死刻度（`_tickLevels` 为 None / 条数不等）。

- [ ] **Step 3: 加 `_time_divisions` 状态**

`__init__` 里（紧邻 `self._time_overlay_axes = []` 一带）加：

```python
        # 时域预览 Y 网格等分数（mirror time-domain overlay divisions）。由 Y
        # 刻度密度驱动；左轴+各右轴都框成这么多等分 → 刻度落在同一组网格线。
        self._time_divisions = 8
```

- [ ] **Step 4: 实现 `_reframe_time_y_to_grid`**

在 `_sync_time_overlay_vbs` 附近新增（导入处加 `from .ticks_math import _frame_to_nice, _fmt_tick`）：

```python
    def _reframe_time_y_to_grid(self) -> None:
        """把时域预览的主轴(曲线0/左轴)与每条 aux 右轴都框成 _time_divisions 等分
        nice 刻度并钉死，使刻度落在同一组 k/n 水平网格线上（对齐 time domain）。"""
        n = max(3, min(20, int(self._time_divisions)))
        pairs = []  # (vb, axis)
        if self._time_curves:
            pairs.append((self._plot_time.vb, self._plot_time.getAxis('left')))
        for vb, axis, curve in zip(self._time_overlay_vbs,
                                   self._time_overlay_axes,
                                   self._time_curves[1:]):
            pairs.append((vb, axis))
        # 主轴用曲线0；aux 用各自曲线
        curves = [self._time_curves[0]] if self._time_curves else []
        curves += list(self._time_curves[1:])
        for (vb, axis), curve in zip(pairs, curves):
            try:
                xs, ys = curve.getData()
                ys = np.asarray(ys, dtype=float)
                ys = ys[np.isfinite(ys)]
                if ys.size == 0:
                    continue
                lo, hi = float(ys.min()), float(ys.max())
            except Exception:
                continue
            bottom, top, ticks = _frame_to_nice(lo, hi, n)
            try:
                vb.enableAutoRange(axis='y', enable=False)
                vb.setYRange(bottom, top, padding=0)
                axis.setStyle(maxTickLevel=0)
                axis.setTicks([[(v, _fmt_tick(v)) for v in ticks], []])
            except Exception:
                pass
        # 预览 Y 固定在 graticule：左键拖动只平移 X（= 选 FFT 窗口）。
        try:
            self._plot_time.vb.setMouseEnabled(x=True, y=False)
        except Exception:
            pass
```

> 注：aux 列表与 `_time_curves[1:]` 一一对应（`_plot_time_preview_entries` 里第 i≥1 条曲线建一条 aux）。上面的 `pairs`/`curves` 配对要保证主轴配曲线0、第 k 条 aux 配曲线 k；实现时以一个统一循环更稳：先 `[(main_vb, left_axis, curve0)]`，再 `zip(aux_vbs, aux_axes, curves[1:])`，executor 按实际结构写成单循环，别照搬上面的双列表。

- [ ] **Step 5: 建曲线后调用**

`_plot_time_preview_entries` 末尾，把 `self._plot_time.enableAutoRange(axis='y')`（约 :935）替换为 `self._reframe_time_y_to_grid()`。

- [ ] **Step 6: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_time_preview_axes_share_grid_divisions -q`
Expected: PASS。

### 1b：刻度密度驱动 divisions（右轴随密度变）

- [ ] **Step 1: 写失败测试**

```python
def test_tick_density_changes_right_axis_divisions(canvas):
    canvas.plot_spectra(_overlay_entries(), xlim=(0.0, 50.0),
                        amp_label='Amplitude', title='t')
    canvas.set_tick_density(10, 6)
    assert canvas._time_divisions == 6
    for axis in canvas._time_overlay_axes:
        assert len(_major_tick_values(axis)) == 7
    canvas.set_tick_density(10, 12)
    assert canvas._time_divisions == 12
    for axis in canvas._time_overlay_axes:
        assert len(_major_tick_values(axis)) == 13
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_tick_density_changes_right_axis_divisions -q`
Expected: FAIL — 当前 `set_tick_density` 不碰右轴、无 `_time_divisions`。

- [ ] **Step 3: 改 `set_tick_density`**（见 spec §3.2 完整代码）

谱图保持 `setTickDensity`；时域 bottom 仍用密度；Y 改为 `self._time_divisions = max(3, min(20, y_n))` + `self._reframe_time_y_to_grid()`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "share_grid_divisions or right_axis_divisions" -q`
Expected: PASS。

### 1c：拟合/重置路径也对齐 + 单/恒定信号兜底

- [ ] **Step 1: 写失败/护栏测试**

```python
def test_fit_y_keeps_time_axes_on_grid(canvas):
    import pytest
    canvas.plot_spectra(_overlay_entries(), xlim=(0.0, 50.0),
                        amp_label='Amplitude', title='t')
    canvas._fit_y_to_visible_x(canvas._plot_time)
    left = canvas._plot_time.getAxis('left')
    (lo, hi) = canvas._plot_time.vb.viewRange()[1]
    fr = [round((v - lo) / (hi - lo), 6) for v in _major_tick_values(left)]
    assert fr == pytest.approx([k / 8 for k in range(9)], abs=1e-6)


def test_constant_signal_does_not_raise(canvas):
    import numpy as np
    t = np.linspace(0, 1, 100)
    canvas.plot_spectra(
        [{'label': 'k', 'color': '#2563eb', 'freq': np.linspace(0, 50, 64),
          'amp': np.ones(64), 'time': t, 'signal': np.full_like(t, 3.0)}],
        xlim=(0.0, 50.0), amp_label='Amplitude', title='t')
    canvas._reframe_time_y_to_grid()   # min==max，不得抛错
```

- [ ] **Step 2: 实现调用点**

`_fit_y_to_visible_x`（`plot is self._plot_time` 分支）末尾追加 `self._reframe_time_y_to_grid()`；`reset_view_to_data_extents` 与 `_reset_time_preview_to_extents` 里设完 X 后调 `self._reframe_time_y_to_grid()`（替换其中的 `enableAutoRange(axis='y')`）。`_frame_to_nice` 已对零跨度兜底；空曲线在循环里 `continue`。

- [ ] **Step 3: 跑测试确认通过 + 既有套件**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q`
Expected: PASS（含既有用例不回归；如有断言旧 autoRange 行为的用例需同步更新，且在 commit message 说明）。

- [ ] **Step 4: 视觉验证（对照用户截图）**

渲染叠加 3 通道的 FFT，抓 `_glw.grab()`：左轴与两右轴刻度条数一致、都落在同一组横向网格线上。

- [ ] **Step 5: 提交**

```
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "fix(fft): frame time-preview left+right Y axes to shared nice graticule + drive divisions by tick density"
```

---

## Task 2: B — 标注扩展到时域预览图

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（`set_remark_enabled`/`_on_click`/`add_remark_at`/`remove_remark_near`/`clear_remarks`）
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试**

```python
def test_annotation_enabled_disables_time_menu(canvas):
    canvas.plot_spectra(_overlay_entries(), xlim=(0.0, 50.0),
                        amp_label='Amplitude', title='t')
    canvas.set_remark_enabled(True)
    assert canvas._plot_time.vb.menuEnabled() is False
    canvas.set_remark_enabled(False)
    assert canvas._plot_time.vb.menuEnabled() is True


def test_add_and_clear_remark_on_time_preview(canvas):
    canvas.plot_spectra(_overlay_entries(), xlim=(0.0, 50.0),
                        amp_label='Amplitude', title='t')
    canvas.set_remark_enabled(True)
    n0 = len(canvas._remarks)
    canvas.add_remark_at('time', 5.0, 0.0)
    assert len(canvas._remarks) == n0 + 1
    assert canvas._remarks[-1]['plot'] is canvas._plot_time \
        or canvas._remarks[-1].get('vb') in canvas._time_overlay_vbs \
        or canvas._remarks[-1].get('vb') is canvas._plot_time.vb
    canvas.clear_remarks()
    assert len(canvas._remarks) == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "time_menu or remark_on_time" -q`
Expected: FAIL — `add_remark_at('time', ...)` 当前直接 return（仅 `'amp'`）；time menu 恒 True。

- [ ] **Step 3: `set_remark_enabled` 屏蔽时域菜单**

```python
    def set_remark_enabled(self, enabled: bool) -> None:
        self._remark_enabled = bool(enabled)
        self._plot_amp.vb.setMenuEnabled(not self._remark_enabled)
        self._plot_time.vb.setMenuEnabled(not self._remark_enabled)
```

- [ ] **Step 4: `add_remark_at` 增加 time 分支**

`which == 'time'` 时：在 `self._time_curves` 里**按屏幕像素**选最近采样点（每条曲线点经其 vb `mapViewToScene` 投到场景，与点击 scene 坐标比距离；单曲线退化为主轴最近点），把 `pg.TextItem(f"({sx:.3g}, {sy:.4g})")` + 红点加到该曲线所属 vb（主曲线用 `_plot_time`/`_plot_time.vb`，aux 曲线用对应 `_time_overlay_vbs`），`self._remarks.append({'label','dot','plot','vb'})`。

> 屏幕空间选点理由见 spec §6：overlay 各曲线 Y 尺度不同，数据空间比距离会偏向大尺度轴。

- [ ] **Step 5: `remove_remark_near` 增加 time 分支 + `clear_remarks` 兼容 vb**

`which == 'time'`：在 time remark 里按 X 选最近移除。`clear_remarks` 用 `r['plot'].removeItem(...)`（aux 上的 item 也能从 `r['plot']` 或 `r['vb']` 移除——按存的 vb 移除更稳）。

- [ ] **Step 6: `_on_click` 增加时域分支**

谱图分支后追加：若 `self._plot_time.vb.sceneBoundingRect().contains(ev.scenePos())` 且 `_remark_enabled`：左键 `add_remark_at('time', v.x(), v.y())`、右键 `remove_remark_near('time', v.x())`（`v = self._plot_time.vb.mapSceneToView(ev.scenePos())`）。

- [ ] **Step 7: 跑测试 + 既有标注用例不回归**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "remark or annotation or markup" -q`
Expected: PASS。

- [ ] **Step 8: 视觉验证 + 提交**

手动：FFT 开标注→下方时域图左键加点、右键删点、清除生效；谱图标注不变。

```
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "feat(fft): allow annotations on the time-preview plot, not just the spectrum row"
```

---

## Task 3: C — 返回/前进视图历史在 FFT 画布生效

> 可选项。若本批决定不做，跳过整个 Task 3。

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（`register_replot_callback`/`_run_replot_callbacks`/`_channel_lines` 契约 + 各 plot_* 末尾调用）
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试（直接驱动工具栏历史）**

```python
def test_fft_view_history_back_forward(canvas):
    import pytest
    from mf4_analyzer.ui.chart_stack import PgNavigationToolbar
    tb = PgNavigationToolbar(canvas)
    calls = []
    canvas.register_replot_callback(lambda: calls.append(1))
    canvas.plot_spectra(_overlay_entries(), xlim=(0.0, 50.0),
                        amp_label='Amplitude', title='t')
    assert calls, "replot callback not fired"
    tb.rebind_history_capture()                 # 卡片正常路径会自动调；此处显式
    assert tb._view_stack, "baseline view not seeded"
    # 模拟一次手动范围变化（pan）后提交历史
    canvas._plot_time.vb.setXRange(2.0, 6.0, padding=0)
    tb._commit_pending_view()
    assert len(tb._view_stack) >= 2
    x_now = tuple(canvas._plot_time.vb.viewRange()[0])
    tb.back()
    x_back = tuple(canvas._plot_time.vb.viewRange()[0])
    assert x_back != pytest.approx(x_now, abs=1e-6)   # 回到上一视图
    tb.forward()
    assert tuple(canvas._plot_time.vb.viewRange()[0]) == pytest.approx(x_now, abs=1e-6)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_fft_view_history_back_forward -q`
Expected: FAIL — 无 `register_replot_callback`；`_view_stack` 不种基线（无 `_channel_lines`）。

- [ ] **Step 3: 加 replot 回调机制**

`__init__` 加 `self._replot_callbacks = []`；新增：

```python
    def register_replot_callback(self, cb) -> None:
        if callable(cb):
            self._replot_callbacks.append(cb)

    def _run_replot_callbacks(self) -> None:
        for cb in list(self._replot_callbacks):
            try:
                cb()
            except Exception:
                pass
```

在 `plot_spectra` / `plot_time_preview` / `full_reset` 末尾各调一次 `self._run_replot_callbacks()`。

- [ ] **Step 4: 加 `_channel_lines` 契约壳**

新增一个轻量 handle（X 全量、Y 视方案；推荐 `__time__` 仅 X）：

```python
class _HistoryHandle:
    __slots__ = ("_vb", "_y")
    def __init__(self, view_box, with_y=True):
        self._vb = view_box; self._y = with_y
    def get_xlim(self):
        (lo, hi), _ = self._vb.viewRange(); return (lo, hi)
    def set_xlim(self, lo, hi):
        self._vb.setXRange(lo, hi, padding=0)
    def get_ylim(self):
        _, (lo, hi) = self._vb.viewRange(); return (lo, hi)
    def set_ylim(self, lo, hi):
        if self._y:
            self._vb.setYRange(lo, hi, padding=0)
        # __time__: no-op，避免还原把 Y 拖离 graticule（spec §3.4/§6）
```

`__init__` 末尾建：

```python
        self._channel_lines = {
            '__amp__': (_HistoryHandle(self._plot_amp.vb, with_y=True), None),
            '__time__': (_HistoryHandle(self._plot_time.vb, with_y=False), None),
        }
```

（`_snapshot_view`/`_restore_view` 遍历 `(name, pair)`、取 `pair[0]` 调
get/set_xlim/ylim —— 见 `chart_stack.py:752-788`，本壳满足契约。）

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_fft_view_history_back_forward -q`
Expected: PASS。

- [ ] **Step 6: 既有套件 + time domain 历史不回归**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_chart_stack.py tests/ui/test_pg_timedomain_canvas.py -q`
Expected: PASS。

- [ ] **Step 7: 视觉验证 + 提交**

手动：FFT 里 pan/框选后点"上一视图"回退、"下一视图"前进。

```
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "feat(fft): give PgLineCanvas a replot-callback + channel-lines contract so toolbar back/forward work"
```

---

## Self-Review（写完自查）

**1. Spec 覆盖**：A1/A2→Task 1（1a 框定+对齐、1b 密度、1c 拟合/重置/兜底）；B→Task 2；C→Task 3。三项需求各有任务，无缺口；非目标（图表选项、逐通道 Y 交互、Shift 滚轮）未混入。

**2. Placeholder 扫描**：Task 1 Step 4 的 `_reframe_time_y_to_grid` 给了可落地骨架，但 `pairs/curves` 配对处明确提示 executor 写成"主轴配曲线0 + `zip(aux_vbs, aux_axes, curves[1:])`"的单循环（别照搬双列表）。Task 2 Step 4/5 的 overlay 屏幕空间最近点用文字描述算法、未贴满代码（依赖 aux vb 当时几何，落地按实际写）。其余步骤含可直接落地代码。

**3. 命名一致**：`_time_divisions`/`_reframe_time_y_to_grid`/`register_replot_callback`/`_run_replot_callbacks`/`_channel_lines`/`_HistoryHandle` 跨任务一致；复用 `_frame_to_nice`/`_fmt_tick`/`_tick_counts_to_density` 既有签名；不改 `PgNavigationToolbar` 与 `main_window`。

**4. 风险点**：A 把预览主 vb 锁成 `setMouseEnabled(y=False)`（行为改动，spec §6 已列，目视确认）；C 的 `__time__` 仅还原 X 以免和 graticule 打架；恒定信号经 `_frame_to_nice` 零跨度兜底已覆盖（1c 测试）。

**5. 执行顺序**：Task 1 → 2 → 3 独立可分别提交；建议先 1（视觉主诉求），再 2，C 视范围决定。每个 Task 内严格先红后绿。
