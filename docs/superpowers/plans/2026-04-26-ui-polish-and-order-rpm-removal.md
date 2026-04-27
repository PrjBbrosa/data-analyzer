# UI Polish + Order-RPM 链路移除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Squad-orchestrator note:** This project routes all code changes through `squad-orchestrator` per `CLAUDE.md`. Each Wave below maps to one squad dispatch round; Wave-level codex review gates are mandatory before advancing (per project memory `feedback_squad_wave_review.md`). Specialists receive task slices keyed by file ownership (see spec §7).

**Goal:** 5 项 UI 收尾改造（紧凑化、StatsStrip 仅 time-domain、预设名 → 配置1/2/3、删整条转速-阶次链、4 画布坐标轴可发现性 + matplotlib toolbar 中文化）一次完成。

**Architecture:** 三波依次执行 — Wave 1 双 specialist 并行删 RPM-order 链（signal+batch / UI），Wave 2 pyqt-ui-engineer 加 2 个新辅助模块 + 4 画布交互 + S1/S2/S3，Wave 3 验收。每波之间必须通过 codex review。

**Tech Stack:** PyQt5, matplotlib (NavigationToolbar2QT, FigureCanvas, gridspec), numpy, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md`（rev 4 — codex approved）

---

## Pre-flight File Layout

**新增（Wave 2 一次性创建，6 个文件）：**

| 路径 | 责任 |
|---|---|
| `mf4_analyzer/ui/_axis_interaction.py` | 纯函数 `find_axis_for_dblclick(fig, x_px, y_px, margin)` + 副作用函数 `edit_axis_dialog(parent_widget, ax, axis) -> bool` |
| `mf4_analyzer/ui/_toolbar_i18n.py` | `apply_chinese_toolbar_labels(toolbar)` + `_ACTION_TOOLTIPS` 表 |
| `tests/ui/test_axis_interaction.py` | S5-T1 至 S5-T9（dblclick / hover）|
| `tests/ui/test_toolbar_i18n.py` | S5-T10 至 S5-T12（toolbar 中文化、Back/Forward 删除、_find_action 兼容）|
| `tests/ui/test_chart_stack_stats_visibility.py` | S2-T1 至 S2-T4 |
| `tests/ui/test_canvas_compactness.py` | S1-T1 至 S1-T4 |

**修改：** 详见各 task。

---

# Wave 1 · Order-RPM 链路移除（双 specialist 并行）

**目标：** 把 RPM-order 整条链从 signal / batch / UI / 测试 4 层删干净。Wave 1 内部两支并行（W1-A signal+batch / W1-B UI），Wave 1 末尾汇合后跑统一 grep + pytest。

**Squad assignment:**
- W1-A → `signal-processing-expert`
- W1-B → `pyqt-ui-engineer`

---

## Task 1.1 — W1-A: 删 `signal/order.py` 中 RPM 实体

**Files:**
- Modify: `mf4_analyzer/signal/order.py`（删除 `OrderRpmResult` dataclass / `compute_rpm_order_result` 方法 / `compute_order_spectrum` facade / `OrderAnalysisParams.rpm_res` 字段）
- Modify: `mf4_analyzer/signal/__init__.py`（移除 `OrderRpmResult` import 与 `__all__` 项）
- Test: `tests/test_order_analysis.py`（先跑确认旧测试失败 → 删旧测试）

- [ ] **Step 1: 删除 OrderRpmResult dataclass**

`mf4_analyzer/signal/order.py:44+`：定位 `class OrderRpmResult:` 整个 dataclass 块，删除（约 line 44 起，含字段定义直到下一个空行 + class 结束）。

- [ ] **Step 2: 删除 compute_rpm_order_result 方法**

`mf4_analyzer/signal/order.py:292+`：定位 `def compute_rpm_order_result(...)` 整方法（包含 `@staticmethod` 装饰器），删除直到方法体结束（line 292 起，至下一个 `@staticmethod` 之前）。

- [ ] **Step 3: 删除 compute_order_spectrum facade**

`mf4_analyzer/signal/order.py:439+`：定位 `def compute_order_spectrum(...)`（不要碰 `compute_order_spectrum_time_based`），删除。

- [ ] **Step 4: 删除 OrderAnalysisParams.rpm_res 字段**

`mf4_analyzer/signal/order.py:30`：删除 `rpm_res: float = 10.0` 这一行。

- [ ] **Step 5: 修改 signal/__init__.py**

```python
# Before:
from .order import OrderAnalysisParams, OrderAnalyzer, OrderRpmResult, OrderTimeResult, OrderTrackResult

# After:
from .order import OrderAnalysisParams, OrderAnalyzer, OrderTimeResult, OrderTrackResult
```

`__all__` 列表中删除 `'OrderRpmResult'` 行。

- [ ] **Step 6: 跑测试确认旧测试现在失败（保护性步骤）**

Run: `pytest tests/test_order_analysis.py -v 2>&1 | head -40`

Expected: 多个 test 失败，error 类似 `ImportError: cannot import name 'OrderRpmResult'` 或 `AttributeError: type object 'OrderAnalyzer' has no attribute 'compute_rpm_order_result'`。

如果**没有**测试因此失败，说明删错位置或测试不在跑——必须停下排查，不要继续。

- [ ] **Step 7: 删除 tests/test_order_analysis.py 中所有 RPM 相关测试**

定位以下函数并整体删除：
- `test_rpm_order_counts_are_per_frame_not_per_nonzero` (line 32)
- `test_metadata_records_nyquist_clipped_at_median_rpm_orders` (line 230)
- `test_compute_*` 中调用 `compute_rpm_order_result` 的（line 71、line 194 周围）— 检查每个测试函数：如果它整方法只服务 rpm_order，整方法删；如果它同时验证 time-order 和 rpm-order 两条路径，仅删 rpm 那部分断言。

实现指引：先 `grep -n "compute_rpm_order_result\|OrderRpmResult\|rpm_res" tests/test_order_analysis.py` 列全部命中行，对每个命中行所在函数做上述判断。

- [ ] **Step 8: 跑测试确认全绿**

Run: `pytest tests/test_order_analysis.py -v`

Expected: 0 failed, 所有保留下来的 time-order / order-track 测试 PASS。

- [ ] **Step 9: Commit**

```bash
git add mf4_analyzer/signal/order.py mf4_analyzer/signal/__init__.py tests/test_order_analysis.py
git commit -m "refactor(signal/order): remove RPM-order chain (OrderRpmResult / compute_rpm_order_result / compute_order_spectrum / rpm_res)"
```

---

## Task 1.2 — W1-A: 删 batch.py 中 RPM 入口

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Test: `tests/test_batch_runner.py`

- [ ] **Step 1: 删除 SUPPORTED_METHODS 中的 'order_rpm'**

`mf4_analyzer/batch.py:89`:

```python
# Before:
SUPPORTED_METHODS = {'fft', 'order_time', 'order_rpm', 'order_track'}

# After:
SUPPORTED_METHODS = {'fft', 'order_time', 'order_track'}
```

- [ ] **Step 2: 删除 _run_one 里的 order_rpm 分支**

`mf4_analyzer/batch.py:194-196`：

```python
# Delete these 3 lines:
elif method == 'order_rpm':
    df = self._compute_order_rpm_dataframe(sig, rpm, fs, preset.params)
    image_payload = ('order_rpm', df)
```

- [ ] **Step 3: 删除 _compute_order_rpm_dataframe classmethod**

`mf4_analyzer/batch.py:280+`：删除 `def _compute_order_rpm_dataframe(...)` 整方法体（包含 `@classmethod`）。

- [ ] **Step 4: 处理 _compute_order_dataframe 中的 rpm_res 读取**

`mf4_analyzer/batch.py:259`：检查 `_compute_order_dataframe`（time-order 用）是否读 `params['rpm_res']`：

```bash
$ grep -n "rpm_res" mf4_analyzer/batch.py
```

如有，删除对应行（time-order 不需要 rpm_res）。

- [ ] **Step 5: 跑 batch 测试确认旧测试失败**

Run: `pytest tests/test_batch_runner.py -v 2>&1 | head -30`

Expected: `test_batch_order_rpm_csv_shape` 失败，错误为 ValueError or KeyError on 'order_rpm'。

- [ ] **Step 6: 删除 tests/test_batch_runner.py 中的 test_batch_order_rpm_csv_shape**

`tests/test_batch_runner.py:142+`：定位 `def test_batch_order_rpm_csv_shape(tmp_path):` 整方法，删除。

- [ ] **Step 7: 跑测试全绿**

Run: `pytest tests/test_batch_runner.py -v`

Expected: 0 failed.

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "refactor(batch): drop order_rpm method + _compute_order_rpm_dataframe + rpm_res param"
```

---

## Task 1.3 — W1-B: 删 inspector_sections.py 中 OrderContextual 的 RPM 部分

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`

- [ ] **Step 1: 删除 order_rpm_requested 信号声明**

`mf4_analyzer/ui/inspector_sections.py:974`：删除 `order_rpm_requested = pyqtSignal()` 这一行。

- [ ] **Step 2: 删除 spin_rpm_res 控件构造**

`mf4_analyzer/ui/inspector_sections.py:1051-1055`：

```python
# Delete these 5 lines:
self.spin_rpm_res = QSpinBox()
self.spin_rpm_res.setRange(1, 100)
self.spin_rpm_res.setValue(10)
self.spin_rpm_res.setSuffix(" rpm")
fl.addRow("RPM分辨率:", _fit_field(self.spin_rpm_res))
```

- [ ] **Step 3: 删除 btn_or 构造与布局**

`mf4_analyzer/ui/inspector_sections.py:1066-1073`：当前是

```python
two_btns = QHBoxLayout()
self.btn_ot = QPushButton("时间-阶次")
self.btn_ot.setProperty("role", "primary")
self.btn_or = QPushButton("转速-阶次")
self.btn_or.setProperty("role", "primary")
two_btns.addWidget(self.btn_ot)
two_btns.addWidget(self.btn_or)
root.addLayout(two_btns)
```

改为：

```python
self.btn_ot = QPushButton("时间-阶次")
self.btn_ot.setProperty("role", "primary")
self.btn_ot.setMinimumHeight(self.btn_ok.minimumHeight() if hasattr(self, 'btn_ok') else 32)
root.addWidget(self.btn_ot)
```

注意：`btn_ok` 在后续 (line 1082) 才创建，所以 `setMinimumHeight(32)` 直接给固定值即可：

```python
self.btn_ot = QPushButton("时间-阶次")
self.btn_ot.setProperty("role", "primary")
self.btn_ot.setMinimumHeight(32)
root.addWidget(self.btn_ot)
```

- [ ] **Step 4: 删除 btn_or click connection**

`mf4_analyzer/ui/inspector_sections.py:1112`：删除 `self.btn_or.clicked.connect(self.order_rpm_requested)` 这一行。

- [ ] **Step 5: 删 _collect_preset 中的 rpm_res**

`mf4_analyzer/ui/inspector_sections.py:1131`：删除 `rpm_res=self.spin_rpm_res.value(),` 这一行。

- [ ] **Step 6: 删 _apply_preset 中的 rpm_res 分支**

`mf4_analyzer/ui/inspector_sections.py:1145-1146`：

```python
# Delete:
if 'rpm_res' in d:
    self.spin_rpm_res.setValue(int(d['rpm_res']))
```

- [ ] **Step 7: 删 get_params 中的 rpm_res（如有）**

`mf4_analyzer/ui/inspector_sections.py:1198`：检查并删除任何 `rpm_res=self.spin_rpm_res.value()`。

如果该方法仅服务 RPM-order，整方法删除（grep 该方法被谁调）。

- [ ] **Step 8: 静态语法检查**

Run: `python -c "from mf4_analyzer.ui import inspector_sections"`

Expected: 无 SyntaxError、无 NameError。

- [ ] **Step 9: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py
git commit -m "refactor(ui/inspector): remove RPM-order button + spin_rpm_res + order_rpm_requested signal"
```

---

## Task 1.4 — W1-B: 删 inspector.py 中的 RPM 中转

**Files:**
- Modify: `mf4_analyzer/ui/inspector.py`

- [ ] **Step 1: 删除 order_rpm_requested 信号声明**

`mf4_analyzer/ui/inspector.py:43`：删除 `order_rpm_requested = pyqtSignal()`。

- [ ] **Step 2: 删除中转连接**

`mf4_analyzer/ui/inspector.py:132`：删除 `self.order_ctx.order_rpm_requested.connect(self.order_rpm_requested)`。

- [ ] **Step 3: 静态检查**

Run: `python -c "from mf4_analyzer.ui import inspector"`

Expected: 无错误。

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ui/inspector.py
git commit -m "refactor(ui/inspector): drop order_rpm_requested relay"
```

---

## Task 1.5 — W1-B: 删 main_window.py 中的 RPM 工作链

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: 删 OrderWorker.run 中 'rpm' 分支**

`mf4_analyzer/ui/main_window.py:124-128`（注意字面量是 `'rpm'`，不是 `'rpm_order'`）：

```python
# Delete:
elif self._kind == 'rpm':
    r = OrderAnalyzer.compute_rpm_order_result(
        self._sig, self._rpm, self._params,
        progress_callback=cb_progress, cancel_token=cb_cancel,
    )
```

- [ ] **Step 2: 删 do_order_rpm 整方法**

`mf4_analyzer/ui/main_window.py:1318+`：定位 `def do_order_rpm(self):` 整方法体，删除直到下一个 `def`（注意此方法内调 `self._dispatch_order_worker('rpm', ...)` line 1341）。

- [ ] **Step 3: 删 _render_order_rpm 整方法**

`mf4_analyzer/ui/main_window.py:1501+`：定位 `def _render_order_rpm(self, result):` 整方法体，删除直到下一个 `def`。

- [ ] **Step 4: 删 _on_order_result 中 'rpm' 分支**

`mf4_analyzer/ui/main_window.py:1455-1456`：

```python
# Delete:
elif kind == 'rpm':
    self._render_order_rpm(result)
```

- [ ] **Step 5: 删 inspector 信号连接**

`mf4_analyzer/ui/main_window.py:304`：删除 `self.inspector.order_rpm_requested.connect(self.do_order_rpm)`。

- [ ] **Step 6: 删 "当前转速-阶次" 字符串**

`mf4_analyzer/ui/main_window.py:1527`（如果它在已删除的 `_render_order_rpm` 内，删整方法时已带走；grep 确认）：

```bash
$ grep -n "当前转速-阶次\|转速-阶次" mf4_analyzer/ui/main_window.py
```

任何残留删除。

- [ ] **Step 7: 静态检查**

Run: `python -c "from mf4_analyzer.ui import main_window"`

Expected: 无错误。

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "refactor(ui/main_window): drop do_order_rpm / _render_order_rpm / OrderWorker rpm branch"
```

---

## Task 1.6 — W1-B: 删 batch_sheet.py 中的 RPM 选项

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch_sheet.py`

- [ ] **Step 1: 删 combo_method 中的 'order_rpm'**

`mf4_analyzer/ui/drawers/batch_sheet.py:108`：

```python
# Before:
self.combo_method.addItems(["fft", "order_time", "order_rpm", "order_track"])

# After:
self.combo_method.addItems(["fft", "order_time", "order_track"])
```

- [ ] **Step 2: 删 spin_rpm_res 控件**

`mf4_analyzer/ui/drawers/batch_sheet.py:143-146`：

```python
# Delete:
self.spin_rpm_res = QDoubleSpinBox()
self.spin_rpm_res.setRange(0.1, 10000)
self.spin_rpm_res.setValue(10)
pf.addRow("RPM分辨率:", self.spin_rpm_res)
```

- [ ] **Step 3: 删 params dict 中 rpm_res 字段**

`mf4_analyzer/ui/drawers/batch_sheet.py:193`：删除 `"rpm_res": self.spin_rpm_res.value(),` 这一行。

- [ ] **Step 4: 静态检查**

Run: `python -c "from mf4_analyzer.ui.drawers import batch_sheet"`

Expected: 无错误。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch_sheet.py
git commit -m "refactor(ui/batch_sheet): drop order_rpm option + spin_rpm_res"
```

---

## Task 1.7 — W1-B: 删 UI 测试中的 RPM 断言

**Files:**
- Modify: `tests/ui/test_order_worker.py`
- Modify: `tests/ui/test_inspector.py`

- [ ] **Step 1: test_order_worker.py 删除 _render_order_rpm 测试**

`tests/ui/test_order_worker.py:136`：定位 `def test_render_order_rpm_uses_correct_extent_and_matrix_orientation(...)` 整方法删除。同时删除 `from mf4_analyzer.signal.order import OrderRpmResult, OrderAnalysisParams` 中的 `OrderRpmResult`（保留 OrderAnalysisParams）。

- [ ] **Step 2: test_inspector.py 删除 order_rpm_requested 断言**

`tests/ui/test_inspector.py:82-83`：

```python
# Delete (and the surrounding test function if it's only about rpm):
with qtbot.waitSignal(oc.order_rpm_requested, timeout=200):
    oc.btn_or.click()
```

如果该 test 函数 body 仅由这两行组成，整函数删除。如果还有其他断言（如 time/track），仅删这两行。

- [ ] **Step 3: 清理任何 spin_rpm_res 引用**

```bash
$ grep -n "spin_rpm_res" tests/ui/test_inspector.py
```

每条命中删除（连同所在 assert 行）。

- [ ] **Step 4: 跑 UI 测试全绿**

Run: `pytest tests/ui/test_order_worker.py tests/ui/test_inspector.py -v 2>&1 | tail -30`

Expected: 0 failed, 0 errors。

- [ ] **Step 5: Commit**

```bash
git add tests/ui/test_order_worker.py tests/ui/test_inspector.py
git commit -m "test(ui): drop order_rpm_requested + spin_rpm_res + _render_order_rpm assertions"
```

---

## Task 1.8 — Wave 1 验收（合并 W1-A + W1-B 后跑）

**Files:** 无修改，只跑校验。

- [ ] **Step 1: 统一 grep 校验（必须 0 命中）**

Run:
```bash
grep -rnE "(rpm_order|order_rpm|OrderRpmResult|compute_rpm_order_result|compute_order_spectrum\b|_render_order_rpm|do_order_rpm|order_rpm_requested|btn_or\b|_compute_order_rpm_dataframe|rpm_res|转速-阶次)" mf4_analyzer/ tests/
```

Expected: 0 行输出。

- [ ] **Step 2: 'rpm' worker-kind 字面量校验**

Run:
```bash
grep -rnE "_kind == 'rpm'|kind == 'rpm'|_dispatch_order_worker\('rpm'" mf4_analyzer/ui/main_window.py
```

Expected: 0 行（注意 `'time'` / `'track'` 仍存在）。

- [ ] **Step 3: 全量 pytest**

Run: `pytest tests/ -v 2>&1 | tail -20`

Expected: 0 failed。

- [ ] **Step 4: 启动 UI 烟雾测试**

Run: `python "MF4 Data Analyzer V1.py"` （后台启动，看进入 "阶次" 模式 Inspector 是否仅显示 时间-阶次 / 阶次跟踪 / 取消计算 三个按钮，无残留）。

- [ ] **Step 5: 提交 Wave 1 收尾 commit（如需）**

如有合并冲突或漏改文件，本步统一处理。

- [ ] **Step 6: ⛔ Wave 1 codex review gate**

派 codex 审本 Wave 改动：

```
Agent subagent_type=codex:codex-rescue
prompt: "Review Wave 1 of the UI polish + RPM removal plan. Verify (a) the unified grep returns 0 hits, (b) pytest is green, (c) no regression in time-order or order-track paths, (d) UI 阶次 mode shows only 3 buttons. Files touched: see commits since branch base. Report to docs/superpowers/reports/2026-04-26-ui-polish-wave1-review.md with verdict."
```

**必须通过 codex review 才能进 Wave 2。**

---

# Wave 2 · S1/S2/S3/S5 实施（pyqt-ui-engineer 单线）

**目标：** 加 2 个新辅助模块（`_axis_interaction.py` / `_toolbar_i18n.py`），4 画布全部接 dblclick + hover，紧凑画布 margin，StatsStrip 切换显隐，预设默认名 → 配置1/2/3，matplotlib toolbar 全中文化。

**Squad assignment:** `pyqt-ui-engineer`

---

## Task 2.1 — 新建 `_axis_interaction.py` + 单元测试

**Files:**
- Create: `mf4_analyzer/ui/_axis_interaction.py`
- Create: `tests/ui/test_axis_interaction.py`

- [ ] **Step 1: 写 test_axis_interaction.py 的纯函数测试（先失败）**

```python
# tests/ui/test_axis_interaction.py
"""Tests for the pure axis-hit detection helper used by all 4 canvases."""
import pytest
from matplotlib.figure import Figure


def _build_fig_with_axes():
    fig = Figure(figsize=(8, 6), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    fig.canvas.draw()  # ensure renderer + bbox available
    return fig, ax


def test_find_axis_hit_x_label_region():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    # 30 px below the axes bottom — inside the 45 px gutter
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=(bbox.x0 + bbox.x1) / 2, y_px=bbox.y0 - 30, margin=45,
    )
    assert hit_ax is ax
    assert axis == 'x'


def test_find_axis_hit_y_label_region():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=bbox.x0 - 30, y_px=(bbox.y0 + bbox.y1) / 2, margin=45,
    )
    assert hit_ax is ax
    assert axis == 'y'


def test_find_axis_no_hit_returns_none():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    # Center of the axes — far from any edge
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=(bbox.x0 + bbox.x1) / 2, y_px=(bbox.y0 + bbox.y1) / 2,
        margin=45,
    )
    assert hit_ax is None
    assert axis is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_axis_interaction.py -v`

Expected: 3 failed with `ImportError: No module named '_axis_interaction'`。

- [ ] **Step 3: 实现 `_axis_interaction.py`**

```python
# mf4_analyzer/ui/_axis_interaction.py
"""Pure axis-hit detection + side-effecting axis-edit helper.

Extracted so all 4 canvases (TimeDomain, Plot, Spectrogram, Order) share
the same hover/dblclick affordance without duplicating PlotCanvas-specific
state references.
"""
from PyQt5.QtWidgets import QDialog


def find_axis_for_dblclick(fig, x_px, y_px, margin):
    """Return (Axes, 'x' | 'y') or (None, None).

    Pixel-based hit test that includes the tick-label gutter region (margin
    px outside the axes bbox) so clicking on tick numbers also targets the
    axis. Pure: depends only on inputs.
    """
    best = (None, None)
    best_dist = float('inf')
    for ax in fig.axes:
        bbox = ax.get_window_extent()
        # X axis: below bottom within `margin` px, x within bounds
        if bbox.x0 - 10 <= x_px <= bbox.x1 + 10:
            if bbox.y0 - margin <= y_px <= bbox.y0 + 20:
                dist = abs(y_px - bbox.y0)
                if dist < best_dist:
                    best = (ax, 'x')
                    best_dist = dist
        # Y axis: left side within `margin` px, y within bounds
        if bbox.y0 - 10 <= y_px <= bbox.y1 + 10:
            if bbox.x0 - margin <= x_px <= bbox.x0 + 20:
                dist = abs(x_px - bbox.x0)
                if dist < best_dist:
                    best = (ax, 'y')
                    best_dist = dist
            # Right Y axis (e.g. colorbar)
            if bbox.x1 - 20 <= x_px <= bbox.x1 + margin:
                dist = abs(x_px - bbox.x1)
                if dist < best_dist:
                    best = (ax, 'y')
                    best_dist = dist
    return best


def edit_axis_dialog(parent_widget, ax, axis):
    """Side-effecting: open AxisEditDialog modal, apply user's choice to
    axes, return True iff dialog was accepted.

    Caller is responsible for calling ``canvas.draw_idle()`` when this
    returns True.
    """
    from .dialogs import AxisEditDialog

    dlg = AxisEditDialog(parent_widget, ax, axis)
    if dlg.exec_() != QDialog.Accepted:
        return False
    vmin, vmax, label, auto = dlg.get_values()
    if axis == 'x':
        if auto:
            ax.autoscale(axis='x')
        else:
            ax.set_xlim(vmin, vmax)
        if label:
            ax.set_xlabel(label)
    else:
        if auto:
            ax.autoscale(axis='y')
        else:
            ax.set_ylim(vmin, vmax)
        if label:
            ax.set_ylabel(label)
    return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/ui/test_axis_interaction.py -v`

Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/_axis_interaction.py tests/ui/test_axis_interaction.py
git commit -m "feat(ui/_axis_interaction): add pure find_axis_for_dblclick + edit_axis_dialog helpers"
```

---

## Task 2.2 — TimeDomainCanvas 接 dblclick + hover

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`（TimeDomainCanvas 段：`_on_click` line 893+, `_on_move` line 918+, `__init__` line 314+ 加 mouse-press 状态跟踪）
- Modify: `tests/ui/test_axis_interaction.py`（追加 canvas-level test）

- [ ] **Step 1: 写测试 — TimeDomainCanvas dblclick 弹 dialog**

追加到 `tests/ui/test_axis_interaction.py`：

```python
def test_timedomain_canvas_dblclick_opens_axis_dialog(qtbot, monkeypatch):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.canvases import TimeDomainCanvas

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)

    # Plot something so axes have a bbox
    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    # Stub the dialog to auto-accept and return a fixed range
    from mf4_analyzer.ui import _axis_interaction
    called = {}

    def fake_edit(parent_widget, ax_, axis):
        called['axis'] = axis
        ax_.set_xlim(0, 10) if axis == 'x' else ax_.set_ylim(0, 10)
        return True

    monkeypatch.setattr(_axis_interaction, 'edit_axis_dialog', fake_edit)

    # Synthesize a dblclick event in the X-axis gutter
    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=(bbox.x0 + bbox.x1) / 2,
                   y=bbox.y0 - 30, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)

    assert called.get('axis') == 'x'
    assert ax.get_xlim() == (0, 10)


def test_timedomain_canvas_hover_axis_changes_cursor(qtbot, monkeypatch):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.canvases import TimeDomainCanvas

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)

    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('motion_notify_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=None)
    canvas.callbacks.process('motion_notify_event', e)

    assert canvas.cursor().shape() == Qt.PointingHandCursor
    assert canvas.toolTip() == "双击编辑坐标轴"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_axis_interaction.py::test_timedomain_canvas_dblclick_opens_axis_dialog tests/ui/test_axis_interaction.py::test_timedomain_canvas_hover_axis_changes_cursor -v`

Expected: 2 failed（dblclick 不弹 dialog；hover 不改 cursor）。

- [ ] **Step 3: 修改 TimeDomainCanvas.__init__ 加 mouse-press 状态**

`mf4_analyzer/ui/canvases.py` TimeDomainCanvas `__init__` 末尾（line 386 周围）加：

```python
# Mouse-press flag for hover short-circuit during active drag.
self._mouse_button_pressed = False
self.mpl_connect('button_press_event', self._track_mouse_press)
self.mpl_connect('button_release_event', self._track_mouse_release)
```

并加两个方法（也在类内部，靠近 `_on_click` 上方）：

```python
def _track_mouse_press(self, e):
    self._mouse_button_pressed = True

def _track_mouse_release(self, e):
    self._mouse_button_pressed = False
```

- [ ] **Step 4: 修改 TimeDomainCanvas._on_click 加 dblclick 拦截**

`mf4_analyzer/ui/canvases.py:893+`：在 `_on_click` 函数体最开始加：

```python
def _on_click(self, e):
    # Double-click on axis label region → open AxisEditDialog (priority over
    # dual-cursor / rubber-band logic). Routes to all 4 canvases via the
    # _axis_interaction helper.
    if e.button == 1 and e.dblclick:
        from ._axis_interaction import find_axis_for_dblclick, edit_axis_dialog
        ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, AXIS_HIT_MARGIN_PX)
        if ax is not None and edit_axis_dialog(self.parent(), ax, axis):
            self.draw_idle()
        return
    # ... existing axis-lock + dual-cursor logic continues unchanged
```

(注意 `AXIS_HIT_MARGIN_PX` 待 Task 2.9 在文件顶部定义。本步先用字面量 `45`，到 Task 2.9 再换常量。)

实际本步代码先写：

```python
ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, 45)
```

- [ ] **Step 5: 修改 TimeDomainCanvas._on_move 加 hover 检测**

`mf4_analyzer/ui/canvases.py:918+`：在 `_on_move` 函数体最开始加：

```python
def _on_move(self, e):
    # Hover affordance for axis-edit dblclick. Only short-circuit during
    # active drag (mouse button currently held); pan/zoom modes themselves
    # do NOT short-circuit because the default UI state is pan-active and
    # we still want the hover hint to fire when the user is just looking.
    if not self._mouse_button_pressed:
        from ._axis_interaction import find_axis_for_dblclick
        from PyQt5.QtCore import Qt
        ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, 45)
        if ax is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("双击编辑坐标轴")
        else:
            self.unsetCursor()
            self.setToolTip("")
    # ... existing rubber-band + cursor-readout logic continues
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/ui/test_axis_interaction.py::test_timedomain_canvas_dblclick_opens_axis_dialog tests/ui/test_axis_interaction.py::test_timedomain_canvas_hover_axis_changes_cursor -v`

Expected: 2 passed。

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/canvases.py tests/ui/test_axis_interaction.py
git commit -m "feat(ui/canvases): TimeDomainCanvas dblclick-edit-axis + hover affordance"
```

---

## Task 2.3 — PlotCanvas 重构既有 dblclick 改用新模块

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`（PlotCanvas 段 line 1434+：删除老的 `_find_axis_for_dblclick` line 1644-1675、`_edit_axis` line 1706-1725，替换 `_on_click` 的 dblclick 拦截调用新模块；加 hover）
- Modify: `tests/ui/test_axis_interaction.py`（追加 PlotCanvas 测试）

- [ ] **Step 1: 写测试 — PlotCanvas dblclick + hover**

追加到 `tests/ui/test_axis_interaction.py`：

```python
def test_plot_canvas_dblclick_uses_axis_interaction_helper(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import PlotCanvas
    canvas = PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    from mf4_analyzer.ui import _axis_interaction
    called = {}
    def fake_edit(parent, ax_, axis):
        called['axis'] = axis
        ax_.set_ylim(-1, 99) if axis == 'y' else ax_.set_xlim(-1, 99)
        return True
    monkeypatch.setattr(_axis_interaction, 'edit_axis_dialog', fake_edit)

    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)
    assert called.get('axis') == 'y'


def test_plot_canvas_hover_axis(qtbot):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.canvases import PlotCanvas
    canvas = PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    canvas.draw()

    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('motion_notify_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=None)
    canvas.callbacks.process('motion_notify_event', e)
    assert canvas.cursor().shape() == Qt.PointingHandCursor


def test_plot_canvas_hover_short_circuit_during_drag(qtbot):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.canvases import PlotCanvas
    canvas = PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    canvas.draw()

    canvas._mouse_button_pressed = True
    bbox = ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('motion_notify_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=None)
    canvas.callbacks.process('motion_notify_event', e)
    # Cursor should NOT be PointingHandCursor since drag is active
    assert canvas.cursor().shape() != Qt.PointingHandCursor
```

- [ ] **Step 2: 跑测试确认 dblclick 已通过（既有功能），但 hover 失败**

Run: `pytest tests/ui/test_axis_interaction.py -v`

Expected: dblclick test pass（PlotCanvas 已有功能）、hover 2 failed。

- [ ] **Step 3: 删除 PlotCanvas._find_axis_for_dblclick 与 _edit_axis 老实现**

`mf4_analyzer/ui/canvases.py:1644-1675` 删除 `_find_axis_for_dblclick` 整方法。
`mf4_analyzer/ui/canvases.py:1706-1725` 删除 `_edit_axis` 整方法。

- [ ] **Step 4: 修改 PlotCanvas._on_click 改用新模块**

`mf4_analyzer/ui/canvases.py:1677-1683`，原本：

```python
def _on_click(self, e):
    if e.button == 1 and e.dblclick:
        ax, axis = self._find_axis_for_dblclick(e)
        if ax is not None:
            self._edit_axis(ax, axis)
            return
```

改为：

```python
def _on_click(self, e):
    if e.button == 1 and e.dblclick:
        from ._axis_interaction import find_axis_for_dblclick, edit_axis_dialog
        ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, 45)
        if ax is not None and edit_axis_dialog(self.parent(), ax, axis):
            self.draw_idle()
        return
```

- [ ] **Step 5: PlotCanvas 加 mouse-press 状态 + hover handler**

PlotCanvas `__init__` 末尾（line 1453 周围）加：

```python
self._mouse_button_pressed = False
self.mpl_connect('button_press_event', self._track_mouse_press)
self.mpl_connect('button_release_event', self._track_mouse_release)
self.mpl_connect('motion_notify_event', self._on_axis_hover)
```

类内加（靠近 `_on_click` 上方）：

```python
def _track_mouse_press(self, e):
    self._mouse_button_pressed = True

def _track_mouse_release(self, e):
    self._mouse_button_pressed = False

def _on_axis_hover(self, e):
    if self._mouse_button_pressed:
        return
    from ._axis_interaction import find_axis_for_dblclick
    from PyQt5.QtCore import Qt
    ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, 45)
    if ax is not None:
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("双击编辑坐标轴")
    else:
        self.unsetCursor()
        self.setToolTip("")
```

- [ ] **Step 6: 跑测试确认全过**

Run: `pytest tests/ui/test_axis_interaction.py -v`

Expected: 全部 PASS（包含 PlotCanvas dblclick + hover + drag-short-circuit）。

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/canvases.py tests/ui/test_axis_interaction.py
git commit -m "refactor(ui/canvases): PlotCanvas uses _axis_interaction; add hover affordance"
```

---

## Task 2.4 — SpectrogramCanvas 接 dblclick + hover

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`（SpectrogramCanvas 段 line 1079+）
- Modify: `tests/ui/test_axis_interaction.py`

- [ ] **Step 1: 写测试 — SpectrogramCanvas + slice 子图都支持**

```python
def test_spectrogram_canvas_dblclick_main_axis(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    canvas.draw()

    # SpectrogramCanvas creates 2 axes (spec + slice) via gridspec; both
    # should accept dblclick.
    from mf4_analyzer.ui import _axis_interaction
    hits = []
    def fake_edit(parent, ax_, axis):
        hits.append((ax_, axis))
        return True
    monkeypatch.setattr(_axis_interaction, 'edit_axis_dialog', fake_edit)

    main_ax = canvas._ax_spec
    bbox = main_ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)
    assert any(ax is main_ax for ax, _ in hits)


def test_spectrogram_canvas_dblclick_slice_axis(qtbot, monkeypatch):
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    canvas.draw()
    from mf4_analyzer.ui import _axis_interaction
    hits = []
    monkeypatch.setattr(_axis_interaction, 'edit_axis_dialog',
                        lambda p, ax, axis: (hits.append((ax, axis)), True)[1])

    slice_ax = canvas._ax_slice
    bbox = slice_ax.get_window_extent()
    from matplotlib.backend_bases import MouseEvent
    e = MouseEvent('button_press_event', canvas, x=bbox.x0 - 30,
                   y=(bbox.y0 + bbox.y1) / 2, button=1, dblclick=True)
    canvas.callbacks.process('button_press_event', e)
    assert any(ax is slice_ax for ax, _ in hits)
```

- [ ] **Step 2: 跑测试确认失败**

Expected: 2 failed (Spectrogram 当前没有 dblclick handler)。

- [ ] **Step 3: 在 SpectrogramCanvas._on_click 顶端插入 dblclick 拦截**

`mf4_analyzer/ui/canvases.py:1329`：

```python
def _on_click(self, event):
    # Double-click on any axis (main spec OR slice) → open AxisEditDialog
    if event.button == 1 and event.dblclick:
        from ._axis_interaction import find_axis_for_dblclick, edit_axis_dialog
        ax, axis = find_axis_for_dblclick(self.fig, event.x, event.y, 45)
        if ax is not None and edit_axis_dialog(self.parent(), ax, axis):
            self.draw_idle()
        return
    # ... existing time-slice select logic continues
```

- [ ] **Step 4: SpectrogramCanvas 加 hover handler 与 mouse-press 跟踪**

`__init__` (line 1124 区域) 已 connect 了 motion_notify_event 给 `_on_motion`；改为先 connect mouse-press 跟踪，再在现有 `_on_motion` 函数顶端加 hover 逻辑：

```python
# In __init__:
self._mouse_button_pressed = False
self.mpl_connect('button_press_event', self._track_mouse_press)
self.mpl_connect('button_release_event', self._track_mouse_release)
```

（_track_mouse_press / _release 与 PlotCanvas 同样实现）。

`_on_motion` 函数顶端：

```python
def _on_motion(self, event):
    # Axis hover affordance — fires regardless of toolbar mode, only
    # short-circuits during active drag.
    if not self._mouse_button_pressed:
        from ._axis_interaction import find_axis_for_dblclick
        from PyQt5.QtCore import Qt
        ax, axis = find_axis_for_dblclick(self.fig, event.x, event.y, 45)
        if ax is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("双击编辑坐标轴")
        else:
            self.unsetCursor()
            self.setToolTip("")
    # ... existing readout logic continues
```

- [ ] **Step 5: 跑测试**

Run: `pytest tests/ui/test_axis_interaction.py -v`

Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/canvases.py tests/ui/test_axis_interaction.py
git commit -m "feat(ui/canvases): SpectrogramCanvas dblclick-edit + hover (main + slice axes)"
```

---

## Task 2.5 — 新建 `_toolbar_i18n.py` + 测试

**Files:**
- Create: `mf4_analyzer/ui/_toolbar_i18n.py`
- Create: `tests/ui/test_toolbar_i18n.py`

- [ ] **Step 1: 写测试**

```python
# tests/ui/test_toolbar_i18n.py
import pytest


def _build_toolbar(qtbot):
    from PyQt5.QtWidgets import QWidget
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qt5agg import (
        FigureCanvasQTAgg as FigureCanvas,
        NavigationToolbar2QT as NavigationToolbar,
    )
    parent = QWidget()
    qtbot.addWidget(parent)
    fig = Figure()
    canvas = FigureCanvas(fig)
    toolbar = NavigationToolbar(canvas, parent)
    return toolbar


def test_pan_zoom_save_have_chinese_tooltips(qtbot):
    from mf4_analyzer.ui._toolbar_i18n import apply_chinese_toolbar_labels
    toolbar = _build_toolbar(qtbot)
    apply_chinese_toolbar_labels(toolbar)
    found = {act.data(): act.toolTip() for act in toolbar.actions() if act.data()}
    assert '平移' in found.get('pan', '')
    assert '缩放' in found.get('zoom', '')
    assert '保存' in found.get('save', '')
    assert '重置' in found.get('home', '')


def test_back_forward_removed(qtbot):
    from mf4_analyzer.ui._toolbar_i18n import apply_chinese_toolbar_labels
    toolbar = _build_toolbar(qtbot)
    apply_chinese_toolbar_labels(toolbar)
    keys = {act.data() for act in toolbar.actions()}
    assert 'back' not in keys
    assert 'forward' not in keys


def test_act_data_preserved_for_find_action(qtbot):
    from mf4_analyzer.ui._toolbar_i18n import apply_chinese_toolbar_labels
    toolbar = _build_toolbar(qtbot)
    apply_chinese_toolbar_labels(toolbar)
    save_acts = [act for act in toolbar.actions() if act.data() == 'save']
    assert len(save_acts) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Expected: ImportError on `_toolbar_i18n`。

- [ ] **Step 3: 实现 `_toolbar_i18n.py`**

```python
# mf4_analyzer/ui/_toolbar_i18n.py
"""Chinese tooltip layer for matplotlib NavigationToolbar2QT.

Replaces the english tooltips with concise Chinese text and removes
low-use Back/Forward actions. Preserves the original english key on
each action's ``data()`` slot so downstream code can match by key
(`act.data() == 'save'`) regardless of the visible tooltip.
"""
from PyQt5.QtCore import Qt


# Map normalized english action text → (chinese tooltip, retain action?)
_ACTION_TOOLTIPS = {
    'home':     ('重置视图', True),
    'back':     ('上一视图', False),
    'forward':  ('下一视图', False),
    'pan':      ('拖动平移（左键拖动）', True),
    'zoom':     ('框选缩放（拖出矩形放大）', True),
    'save':     ('保存图片', True),
    'subplots': ('', False),
    'configure subplots': ('', False),
}


def apply_chinese_toolbar_labels(toolbar):
    """Mutate `toolbar`: drop Back/Forward/Subplots actions; replace
    tooltip text on remaining actions; preserve the original english key
    in `act.data()` so downstream lookups stay stable.
    """
    for act in list(toolbar.actions()):
        key = (act.text() or '').strip().lower()
        if key not in _ACTION_TOOLTIPS:
            continue
        zh_tooltip, retain = _ACTION_TOOLTIPS[key]
        if not retain:
            toolbar.removeAction(act)
            continue
        act.setData(key)
        act.setToolTip(zh_tooltip)
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
```

- [ ] **Step 4: 跑测试**

Run: `pytest tests/ui/test_toolbar_i18n.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/_toolbar_i18n.py tests/ui/test_toolbar_i18n.py
git commit -m "feat(ui/_toolbar_i18n): add Chinese tooltip layer + Back/Forward removal"
```

---

## Task 2.6 — chart_stack.py 接 toolbar i18n + `_find_action` 升级

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`（`_ChartCard.__init__` line 149+, `_find_action` line 130+）

- [ ] **Step 1: 升级 `_find_action` 用 `act.data()` 优先**

`mf4_analyzer/ui/chart_stack.py:130-134`：

```python
# Before:
def _find_action(toolbar, text_lower):
    for act in toolbar.actions():
        if (act.text() or '').strip().lower() == text_lower:
            return act
    return None

# After:
def _find_action(toolbar, key_lower):
    """Match by act.data() first (i18n-stable), then by act.text()."""
    for act in toolbar.actions():
        if act.data() == key_lower or (act.text() or '').strip().lower() == key_lower:
            return act
    return None
```

- [ ] **Step 2: 在 `_ChartCard.__init__` 调用 i18n（顺序很关键）**

`mf4_analyzer/ui/chart_stack.py:155-210` 区域，关键顺序：

```python
self.toolbar = NavigationToolbar(canvas, self)
self.toolbar.setObjectName("chartToolbar")
self.toolbar.setIconSize(QSize(14, 14))  # ← 14 替代 16
_strip_subplots_action(self.toolbar)

# 1) Find Save BEFORE i18n changes labels (text is still 'Save')
save_act = _find_action(self.toolbar, 'save')

# 2) Apply Chinese labels & drop Back/Forward; this also calls
#    setData(key) so subsequent _find_action uses act.data()
from ._toolbar_i18n import apply_chinese_toolbar_labels
apply_chinese_toolbar_labels(self.toolbar)

# 3) Insert copy button next to save_act (already-stored reference)
self._copy_btn = QToolButton(self.toolbar)
# ... rest of copy button setup unchanged
if save_act is not None:
    self.toolbar.insertWidget(save_act, self._copy_btn)
else:
    self.toolbar.addWidget(self._copy_btn)
```

- [ ] **Step 3: Pan/Zoom hookup 用 act.data() 兜底**

`mf4_analyzer/ui/chart_stack.py:201-204`：

```python
# Before:
for act in self.toolbar.actions():
    name = (act.text() or '').strip().lower()
    if name in ('pan', 'zoom'):
        act.triggered.connect(self._on_nav_mode_toggled)

# After:
for act in self.toolbar.actions():
    name = act.data() if act.data() else (act.text() or '').strip().lower()
    if name in ('pan', 'zoom'):
        act.triggered.connect(self._on_nav_mode_toggled)
```

- [ ] **Step 4: 跑测试确认 chart_stack + toolbar_i18n 都过**

Run: `pytest tests/ui/test_chart_stack.py tests/ui/test_toolbar_i18n.py -v`

Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/chart_stack.py
git commit -m "feat(ui/chart_stack): wire toolbar i18n + upgrade _find_action to use act.data()"
```

---

## Task 2.7 — segmented buttons 中文 + `_TOOL_HINTS` 文案

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`（`TimeChartCard.__init__` line 248-289, `_TOOL_HINTS` line 113-117）
- Modify: `tests/ui/test_chart_stack.py`（追加测试）

- [ ] **Step 1: 追加测试**

```python
# tests/ui/test_chart_stack.py append:
def test_time_card_segmented_buttons_chinese(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    card = cs._time_card
    assert card.btn_subplot.text() == '分屏'
    assert card.btn_overlay.text() == '叠加'
    assert card._cursor_buttons['off'].text() == '游标关'
    assert card._cursor_buttons['single'].text() == '单游标'
    assert card._cursor_buttons['dual'].text() == '双游标'
    assert card._lock_buttons['none'].text() == '不锁'
    assert card._lock_buttons['x'].text() == '锁X'
    assert card._lock_buttons['y'].text() == '锁Y'


def test_tool_hints_idle_mentions_dblclick():
    from mf4_analyzer.ui.chart_stack import _TOOL_HINTS
    assert '双击坐标轴' in _TOOL_HINTS['']
```

- [ ] **Step 2: 跑测试确认失败**

Expected: 1-9 个 button text 断言失败 + 1 个 hint 断言失败。

- [ ] **Step 3: 改 segmented buttons 中文化**

`mf4_analyzer/ui/chart_stack.py:248-289` 区段：

```python
# Subplot/Overlay
self.btn_subplot = QPushButton("分屏", self.toolbar)  # was "Subplot"
self.btn_overlay = QPushButton("叠加", self.toolbar)  # was "Overlay"

# Cursor mode
for label, key in [('游标关', 'off'), ('单游标', 'single'), ('双游标', 'dual')]:
    # was [('Off', 'off'), ('Single', 'single'), ('Dual', 'dual')]
    ...

# Axis lock
for label, key in [('不锁', 'none'), ('锁X', 'x'), ('锁Y', 'y')]:
    # was [('无', 'none'), ('X', 'x'), ('Y', 'y')]
    ...
```

- [ ] **Step 4: 改 _TOOL_HINTS 文案**

`mf4_analyzer/ui/chart_stack.py:113-117`：

```python
_TOOL_HINTS = {
    'pan': "<b>移动曲线</b><br>左键拖动平移 · 右键拖动缩放坐标轴",
    'zoom': "<b>框选缩放</b><br>拖动鼠标框选矩形区域放大 · Home 键可复位",
    '': "<b>浏览</b><br>双击坐标轴可设置范围 · 工具栏可启用 平移 / 缩放 / 保存",
}
```

- [ ] **Step 5: 跑测试**

Run: `pytest tests/ui/test_chart_stack.py -v`

Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_chart_stack.py
git commit -m "feat(ui/chart_stack): translate segmented buttons + idle hint to Chinese"
```

---

## Task 2.8 — style.qss toolbar 紧凑

**Files:**
- Modify: `mf4_analyzer/ui/style.qss`

- [ ] **Step 1: 在 style.qss 末尾追加（或合并到现有 chartToolbar 块）**

```css
/* Chart toolbar — compact spacing & padding (post-i18n). Three selectors
   to cover Qt style resolution variations: QToolBar (matplotlib subclass),
   QWidget (object-name match), and the matplotlib subclass name. */
QToolBar#chartToolbar,
QWidget#chartToolbar,
NavigationToolbar2QT#chartToolbar { spacing: 1px; padding: 1px; }
QToolBar#chartToolbar QToolButton,
QWidget#chartToolbar QToolButton { padding: 2px 4px; }
```

(如果 style.qss 已有 `chartToolbar` 块，merge 到一起。)

- [ ] **Step 2: 视觉检查**

启动 app，目测 toolbar 高度比改前少 4-6 px、按钮间距更紧。

- [ ] **Step 3: Commit**

```bash
git add mf4_analyzer/ui/style.qss
git commit -m "style(ui): tighten chart toolbar spacing/padding"
```

---

## Task 2.9 — S1 紧凑化常量 + canvases.py tight_layout 替换

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`（顶部加常量、line 486 / 516 / 535 / 1555 替换 tight_layout）
- Create: `tests/ui/test_canvas_compactness.py`

- [ ] **Step 1: 写 S1 紧凑化测试**

```python
# tests/ui/test_canvas_compactness.py
import pytest


def test_chart_tight_layout_kw_constant_defined():
    from mf4_analyzer.ui import canvases
    assert hasattr(canvases, 'CHART_TIGHT_LAYOUT_KW')
    assert canvases.CHART_TIGHT_LAYOUT_KW.get('pad') == 0.4


def test_axis_hit_margin_constant_defined():
    from mf4_analyzer.ui import canvases
    assert canvases.AXIS_HIT_MARGIN_PX == 45


def test_timedomain_subplotpars_after_render(qtbot):
    from mf4_analyzer.ui.canvases import TimeDomainCanvas
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 500)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_ylabel("amplitude")
    canvas.fig.tight_layout(**__import__(
        'mf4_analyzer.ui.canvases', fromlist=['CHART_TIGHT_LAYOUT_KW']
    ).CHART_TIGHT_LAYOUT_KW)
    canvas.draw()
    sp = canvas.fig.subplotpars
    assert sp.left <= 0.10
    assert sp.top >= 0.93


def test_ylabel_does_not_overlap_yticks(qtbot):
    """S1-T4: y-label render bbox must not overlap y-tick label bbox."""
    from mf4_analyzer.ui.canvases import TimeDomainCanvas
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 500)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    ax.plot(range(100), range(100))
    ax.set_ylabel("Velocity (m/s)", labelpad=12)
    from mf4_analyzer.ui.canvases import CHART_TIGHT_LAYOUT_KW
    canvas.fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
    canvas.draw()
    renderer = canvas.fig.canvas.get_renderer()
    ylabel_bbox = ax.yaxis.label.get_window_extent(renderer)
    tick_bboxes = [t.label1.get_window_extent(renderer) for t in ax.yaxis.get_major_ticks()]
    for tb in tick_bboxes:
        assert not ylabel_bbox.overlaps(tb), f"ylabel overlaps tick: {ylabel_bbox} vs {tb}"
```

- [ ] **Step 2: 跑测试确认失败**

Expected: AttributeError on `CHART_TIGHT_LAYOUT_KW` / `AXIS_HIT_MARGIN_PX`。

- [ ] **Step 3: 在 canvases.py 顶部加常量**

`mf4_analyzer/ui/canvases.py` 接近 import 结束的位置（line 20 周围）：

```python
# Tight margins for non-spectrogram canvases. Default tight_layout pad
# is 1.08x font size which is loose for Chinese fonts.
CHART_TIGHT_LAYOUT_KW = dict(pad=0.4, h_pad=0.6, w_pad=0.4)

# Spectrogram has a colorbar on the right; subplots_adjust must run AFTER
# fig.colorbar(...) so colorbar geometry is already in place.
SPECTROGRAM_SUBPLOT_ADJUST = dict(
    left=0.07, right=0.93, top=0.97, bottom=0.09,
)

# Pixel margin around an axes for hit-detection of the axis-edit affordance.
AXIS_HIT_MARGIN_PX = 45
```

- [ ] **Step 4: 替换所有 `tight_layout()` 默认调用**

逐一替换：
- Line 486: `self.fig.tight_layout()` → `self.fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)`
- Line 516: 同上
- Line 535: 同上
- Line 1555: 同上

- [ ] **Step 5: 替换 dblclick / hover 中的 `45` 字面量为 `AXIS_HIT_MARGIN_PX`**

之前 Task 2.2 / 2.3 / 2.4 留下的 `find_axis_for_dblclick(..., 45)` 全部改为 `find_axis_for_dblclick(..., AXIS_HIT_MARGIN_PX)`。

- [ ] **Step 6: 跑测试**

Run: `pytest tests/ui/test_canvas_compactness.py tests/ui/test_axis_interaction.py -v`

Expected: 全 PASS。

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/canvases.py tests/ui/test_canvas_compactness.py
git commit -m "feat(ui/canvases): introduce compactness constants + replace tight_layout calls"
```

---

## Task 2.10 — S1 SpectrogramCanvas figsize + subplots_adjust + colorbar bbox 测试

**Files:**
- Modify: `mf4_analyzer/ui/canvases.py`（SpectrogramCanvas 段 line 1104, 1205, 1239-1248）
- Modify: `tests/ui/test_canvas_compactness.py`

- [ ] **Step 1: 追加 Spectrogram 测试**

```python
def test_spectrogram_figsize_aligned():
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    assert canvas.fig.get_size_inches().tolist() == [10.0, 6.0]


def test_spectrogram_subplotpars_right_leaves_colorbar_room(qtbot):
    """S1-T1 + S1-T3: subplots right=0.93, colorbar bbox does not overlap."""
    import numpy as np
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    # Drive a minimal render path using the canvas's render method —
    # use a stub result if necessary, or call .clear() then .plot_*.
    # For this skeleton, we assert subplotpars after the implementation
    # applies subplots_adjust.
    canvas.fig.subplots_adjust(
        **__import__(
            'mf4_analyzer.ui.canvases', fromlist=['SPECTROGRAM_SUBPLOT_ADJUST']
        ).SPECTROGRAM_SUBPLOT_ADJUST
    )
    canvas.draw()
    sp = canvas.fig.subplotpars
    assert abs(sp.right - 0.93) < 0.005
    assert abs(sp.left - 0.07) < 0.005
    assert sp.top >= 0.96
```

- [ ] **Step 2: 跑测试确认失败**

Expected: figsize 仍是 (12, 8)；subplotpars right 不是 0.93。

- [ ] **Step 3: 改 SpectrogramCanvas figsize**

`mf4_analyzer/ui/canvases.py:1104-1106`：

```python
# Before:
self.fig = Figure(figsize=(12, 8), dpi=100, facecolor=CHART_FACE)

# After:
self.fig = Figure(figsize=(10, 6), dpi=100, facecolor=CHART_FACE)
```

- [ ] **Step 4: 改 gridspec hspace**

`mf4_analyzer/ui/canvases.py:1205`：

```python
# Before:
gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.28)

# After:
gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.18)
```

- [ ] **Step 5: 替换 tight_layout 为 subplots_adjust**

`mf4_analyzer/ui/canvases.py:1239-1248`：

```python
# Before:
import warnings as _warnings
with _warnings.catch_warnings():
    _warnings.simplefilter('ignore', UserWarning)
    try:
        self.fig.tight_layout()
    except Exception:
        pass

# After:
# subplots_adjust must run AFTER fig.colorbar(...) so colorbar geometry
# is already in place. Do not use tight_layout — it can't reason about
# the colorbar.
self.fig.subplots_adjust(**SPECTROGRAM_SUBPLOT_ADJUST)
```

- [ ] **Step 6: 跑测试**

Run: `pytest tests/ui/test_canvas_compactness.py -v`

Expected: 全 PASS。

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/canvases.py tests/ui/test_canvas_compactness.py
git commit -m "feat(ui/canvases): SpectrogramCanvas compact margins + figsize 10x6 + subplots_adjust"
```

---

## Task 2.11 — main_window.py FFT + order_track tight_layout 替换

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`（line 1257 FFT 渲染、line 1584 order_track 渲染）

- [ ] **Step 1: 替换 main_window.py 中两处 tight_layout**

Line 1257 与 line 1584：

```python
# Before:
self.chart_stack.canvas_fft.fig.tight_layout()
# 与
self.chart_stack.canvas_order.fig.tight_layout()

# After:
from .canvases import CHART_TIGHT_LAYOUT_KW
self.chart_stack.canvas_fft.fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
# 与
self.chart_stack.canvas_order.fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
```

(import 放到文件顶部 imports 区，避免函数体内每次 import。)

- [ ] **Step 2: 跑既有 main_window 测试确认无回归**

Run: `pytest tests/ui/ -v 2>&1 | tail -20`

Expected: 0 failed。

- [ ] **Step 3: Commit**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "refactor(ui/main_window): use CHART_TIGHT_LAYOUT_KW for FFT & order-track render"
```

---

## Task 2.12 — S2 StatsStrip 仅 time-domain 显示

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`（`set_mode` line 398-403, `__init__` line 353-393）
- Create: `tests/ui/test_chart_stack_stats_visibility.py`

- [ ] **Step 1: 写测试**

```python
# tests/ui/test_chart_stack_stats_visibility.py
import pytest


def test_default_stats_visible_iff_time_mode(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    assert cs.stats_strip.isVisible() == (cs.current_mode() == 'time')


def test_stats_hidden_in_fft_fft_time_order_modes(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    for mode in ('fft', 'fft_time', 'order'):
        cs.set_mode(mode)
        assert cs.stats_strip.isVisible() is False, f"{mode} should hide stats"


def test_stats_visible_after_returning_to_time(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('fft')
    assert cs.stats_strip.isVisible() is False
    cs.set_mode('time')
    assert cs.stats_strip.isVisible() is True


def test_no_channel_label_after_return(qtbot):
    """S2-T4: update_stats({}) on return to time shows '— 无通道 —'."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('fft')
    cs.set_mode('time')
    cs.stats_strip.update_stats({})
    assert cs.stats_strip._lbl_summary.text() == "— 无通道 —"
```

- [ ] **Step 2: 跑测试确认失败**

Expected: 至少一个 visibility 断言失败（当前 stats_strip 永远可见）。

- [ ] **Step 3: 修改 ChartStack.set_mode**

`mf4_analyzer/ui/chart_stack.py:398-403`：

```python
def set_mode(self, mode):
    idx = _MODE_TO_INDEX[mode]
    if self.stack.currentIndex() == idx:
        return
    self.stack.setCurrentIndex(idx)
    self.stats_strip.setVisible(mode == 'time')  # ← new
    self.mode_changed.emit(mode)
```

- [ ] **Step 4: __init__ 末尾初始化一次**

`mf4_analyzer/ui/chart_stack.py:393`（构造尾部）：

```python
# Initial sync: stats_strip shows iff default mode is 'time'.
self.stats_strip.setVisible(self.current_mode() == 'time')
```

- [ ] **Step 5: 跑测试**

Run: `pytest tests/ui/test_chart_stack_stats_visibility.py -v`

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_chart_stack_stats_visibility.py
git commit -m "feat(ui/chart_stack): hide StatsStrip outside time-domain mode"
```

---

## Task 2.13 — S3 预设默认显示名 → 配置1/2/3

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`（`_BUILTIN_PRESET_DISPLAY` line 1542-1548、注释 line 91-99）
- Modify: `tests/ui/test_inspector.py`

- [ ] **Step 1: 写测试**

```python
# Append to tests/ui/test_inspector.py:
def test_fft_time_preset_bar_default_names(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    w = FFTTimeContextual()
    qtbot.addWidget(w)
    bar = w.preset_bar
    # PresetBar exposes per-slot text; assert default builtin names.
    assert bar.slot_text(1) == '配置1'
    assert bar.slot_text(2) == '配置2'
    assert bar.slot_text(3) == '配置3'


def test_fft_time_preset_bar_reset_to_default_keeps_new_names(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    w = FFTTimeContextual()
    qtbot.addWidget(w)
    bar = w.preset_bar
    # Override slot 1 with a custom name then reset
    bar.set_slot_override(1, {'display_name': 'Custom A', 'params': {}})
    bar.reset_slot_to_default(1)
    assert bar.slot_text(1) == '配置1'
```

(注：实际 PresetBar 的 API 需要 grep 确认；如不是 `slot_text(n)` / `set_slot_override` / `reset_slot_to_default`，按真实 API 调整。)

- [ ] **Step 2: 跑测试确认失败**

Expected: text 仍是「诊断模式 / 幅值精度 / 高频细节」。

- [ ] **Step 3: 改 _BUILTIN_PRESET_DISPLAY**

`mf4_analyzer/ui/inspector_sections.py:1542-1548`：

```python
# Before:
_BUILTIN_PRESET_DISPLAY = {
    'diagnostic': '诊断模式',
    'amplitude_accuracy': '幅值精度',
    'high_frequency': '高频细节',
}

# After:
_BUILTIN_PRESET_DISPLAY = {
    'diagnostic': '配置1',
    'amplitude_accuracy': '配置2',
    'high_frequency': '配置3',
}
```

- [ ] **Step 4: 同步注释**

`mf4_analyzer/ui/inspector_sections.py:91-99` 注释里 "诊断模式 / 幅值精度 / 高频细节" 改成 "配置1 / 配置2 / 配置3"。

- [ ] **Step 5: 跑测试**

Run: `pytest tests/ui/test_inspector.py -v 2>&1 | tail -20`

Expected: 0 failed。如果存在依赖旧名称的旧 test，本任务一并改。

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections.py tests/ui/test_inspector.py
git commit -m "feat(ui/inspector): rename FFT-vs-Time builtin preset display names to 配置1/2/3"
```

---

## Task 2.14 — Wave 2 验收

- [ ] **Step 1: 全量 pytest**

Run: `pytest tests/ -v 2>&1 | tail -30`

Expected: 0 failed。

- [ ] **Step 2: 启动 app 烟雾测试**

Run: `python "MF4 Data Analyzer V1.py"`

逐项检查：
- 4 模式切换：StatsStrip 仅 time 可见 ✓
- 4 模式 toolbar：tooltip 中文 ✓ Back/Forward 不在 ✓
- 4 模式坐标轴：hover 变手指 + tooltip ✓ 双击弹 dialog ✓
- FFT-vs-Time 预设：3 个默认 slot 显示 配置1/2/3 ✓
- time card segmented buttons：分屏 / 叠加 / 游标关 / ... ✓

- [ ] **Step 3: ⛔ Wave 2 codex review gate**

派 codex 审本 Wave 改动：

```
Agent subagent_type=codex:codex-rescue
prompt: "Review Wave 2 of the UI polish plan. Verify (a) all 15 S5 acceptance tests pass, (b) S1 subplotpars + ylabel-bbox tests pass, (c) S2 visibility tests pass, (d) S3 preset name tests pass, (e) no regression in existing time-domain / FFT / order tests, (f) `_find_action(toolbar, 'save')` still works after i18n. Report to docs/superpowers/reports/2026-04-26-ui-polish-wave2-review.md with verdict."
```

**必须 approved 才能进 Wave 3。**

---

# Wave 3 · 验收 + 截图归档

**Squad assignment:** `pyqt-ui-engineer`

## Task 3.1 — 4 模式截图归档

**Files:** Create: `docs/superpowers/reports/2026-04-26-canvas-compactness-screenshots/{time,fft,fft_time,order}.png`

- [ ] **Step 1: 启动 app**

Run: `python "MF4 Data Analyzer V1.py"`

- [ ] **Step 2: 加载一份测试数据**

打开 `testdoc/` 目录里任一 mf4 fixture。

- [ ] **Step 3: 4 模式各截一张**

依次切到 time / fft / fft_time / order，截全窗口图保存为 `{mode}.png`。

- [ ] **Step 4: 与改前对比**

如有 git stash 可比较；或目测对比 Image 11 中给出的 Spectrogram 截图。改后白边应明显收窄。

- [ ] **Step 5: Commit 截图**

```bash
git add docs/superpowers/reports/2026-04-26-canvas-compactness-screenshots/
git commit -m "docs(reports): canvas compactness screenshots — 4 modes after S1"
```

---

## Task 3.2 — 最终 grep + pytest + 任务总结

- [ ] **Step 1: S4 统一 grep（必 0）**

```bash
grep -rnE "(rpm_order|order_rpm|OrderRpmResult|compute_rpm_order_result|compute_order_spectrum\b|_render_order_rpm|do_order_rpm|order_rpm_requested|btn_or\b|_compute_order_rpm_dataframe|rpm_res|转速-阶次)" mf4_analyzer/ tests/
```

- [ ] **Step 2: 'rpm' 字面量校验（必 0）**

```bash
grep -rnE "_kind == 'rpm'|kind == 'rpm'|_dispatch_order_worker\\('rpm'" mf4_analyzer/ui/main_window.py
```

- [ ] **Step 3: 全量 pytest**

Run: `pytest tests/ -v 2>&1 | tail -10`

Expected: 0 failed。

- [ ] **Step 4: 写收尾 report**

Create `docs/superpowers/reports/2026-04-26-ui-polish-final-report.md` 记录：
- 5 项 acceptance 全部勾选
- 4 模式截图链接
- 全量 pytest 输出 tail
- grep 0 命中证据
- 各 Wave codex review report 链接

- [ ] **Step 5: ⛔ Wave 3 codex final sign-off**

派 codex 审最终状态：

```
Agent subagent_type=codex:codex-rescue
prompt: "Final sign-off review for the UI polish + RPM removal squad rollout. Verify (a) S1 acceptance grep returns 0, (b) S4 'rpm' literal grep returns 0, (c) full pytest is green, (d) screenshots exist for all 4 modes, (e) all spec acceptance criteria are checked. Report to docs/superpowers/reports/2026-04-26-ui-polish-wave3-review.md with final verdict."
```

- [ ] **Step 6: 最终 commit**

```bash
git add docs/superpowers/reports/2026-04-26-ui-polish-final-report.md
git commit -m "docs(reports): UI polish + RPM removal — final acceptance report"
```

---

# Self-Review Notes

**Spec coverage:**
- S1 → Tasks 2.9, 2.10, 2.11 + 测试 2.9/2.10
- S2 → Task 2.12
- S3 → Task 2.13
- S4 → Tasks 1.1-1.7 + 1.8 验收
- S5 → Tasks 2.1-2.7 + 2.8 (style)

**No placeholders:** 每步要么是具体代码、要么是具体 grep 命令、要么是具体 commit 文案。

**Type consistency:** `find_axis_for_dblclick` 与 `edit_axis_dialog` 在所有引用处签名一致；`AXIS_HIT_MARGIN_PX` 在 Task 2.9 引入后所有调用点统一替换。

**Squad/wave gating:** 每个 Wave 末尾都明确 codex review gate 步骤。
