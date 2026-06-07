# 叠加模式网格/刻度对齐修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本仓库约束（CLAUDE.md）**：这是 UI 子系统改动，正式实施走 squad runbook，由 **pyqt-ui-engineer** 执行；TDD 先红后绿；完成后按 `feedback-verify-ui-visually` 经验做一次真机/截图复核。

**Goal:** 修复时域叠加模式两类网格/刻度错位——切换分叠时（#2）与「Y 轴自适应」后（#3）。

**Architecture:** 叠加体系 = X 主轴 ViewBox 承载 `[0,1]` 固定 `k/n` 网格，每通道一条 aux ViewBox 框进网格。#3 在 `fit_y_to_visible_x` 末尾补一次 graticule 重框（复用 `_repin_overlay_channel_ticks`）；#2 把 aux 几何同步挪到 `_build` 真正末尾、先强制 GraphicsLayout settle，并补一条 resize 兜底。

**Tech Stack:** Python 3, PyQt5, pyqtgraph 0.14, pytest（offscreen Qt，`tests/ui/test_pg_timedomain_canvas.py::_pg_canvas` 夹具）。

设计依据：`docs/superpowers/specs/2026-06-07-overlay-grid-tick-realign-design.md`；时序经验 `docs/lessons-learned/codex-pg-subplot-layout-settle.md` 与 `docs/lessons-learned/codex-overlay-graticule-wheel-contract.md`。

**Commit policy:** 不在 Task 1/2/3 中途提交。实现、测试、真机复核都完成后，再按用户要求用一个窄范围 commit 提交 `mf4_analyzer/ui/pg_canvases.py` 与 `tests/ui/test_overlay_grid_ticks.py`；若工作区有其他未提交改动，保持隔离，不混入。

---

## File Structure

- `mf4_analyzer/ui/pg_canvases.py` — 唯一改动的源文件：
  - `fit_y_to_visible_x`（≈2395）：叠加模式末尾追加重框（#3）。
  - 新增 `_settle_layout()`（置于 `_sync_overlay_aux_viewboxes` 4219 附近）：封装既有 `invalidate()/activate()` 模式（#2）。
  - `_build`（≈1687 与 ≈1699-1701）：删早期同步、末尾补 settle+sync（#2）。
  - `_on_resize_settled`（≈5388）：叠加模式补 settle+sync 兜底（#2）。
- `tests/ui/test_overlay_grid_ticks.py` — 追加 2 个测试类的回归用例：`TestFitYToVisibleOverlay` 与 `TestOverlaySwitchGeometry`。

不改 `_frame_to_nice` 数值算法、不动滚轮/鼠标链路、不动 subplot 既有 `_unify_*` 路径、不触碰 5296/5347 两处既有 settle 调用。

---

## Task 1: #3 —「Y 轴自适应」后叠加刻度重新落到网格

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py:2457`（`fit_y_to_visible_x` 内 `self._refresh = True` 之前）
- Test: `tests/ui/test_overlay_grid_ticks.py`（文件末尾追加 `TestFitYToVisibleOverlay`）

- [ ] **Step 1: 写失败测试**

在 `tests/ui/test_overlay_grid_ticks.py` 末尾追加：

```python
class TestFitYToVisibleOverlay:
    """『Y 轴自适应』(fit_y_to_visible_x) 在叠加模式下必须把每个通道的
    数据拟合范围再规整回 k/n graticule，否则刻度与固定网格线错位 (#3)。"""

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

    def test_fit_y_to_visible_x_keeps_overlay_ticks_on_grid(self, qapp):
        canvas = self._overlay(qapp)
        canvas.fit_y_to_visible_x()
        n = canvas._overlay_divisions
        for handle in canvas.axes_list:
            lo, hi = handle.get_ylim()
            span = hi - lo
            assert span > 0
            axis = handle.y_axis_item()
            major = axis._tickLevels[0]
            fracs = sorted(((value - lo) / span) for value, _label in major)
            expected = [k / n for k in range(n + 1)]
            assert fracs == pytest.approx(expected, abs=1e-6)

    def test_fit_y_to_visible_x_subplot_does_not_reframe(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        sig0 = 3.1 * np.sin(2 * np.pi * t)
        sig1 = 1.7 * np.cos(2 * np.pi * 2 * t)
        rows = [
            ("ch0", True, t, sig0, "#1769e0", "V", "fid-0"),
            ("ch1", True, t, sig1, "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        canvas.fit_y_to_visible_x()
        handle = canvas.axes_list[0]
        lo, hi = handle.get_ylim()
        data_lo, data_hi = float(sig0.min()), float(sig0.max())
        pad = (data_hi - data_lo) * 0.05
        # subplot/single 保持原始拟合范围（不规整到 nice 网格）。
        assert lo == pytest.approx(data_lo - pad, rel=1e-3)
        assert hi == pytest.approx(data_hi + pad, rel=1e-3)
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py::TestFitYToVisibleOverlay -v`
Expected: `test_fit_y_to_visible_x_keeps_overlay_ticks_on_grid` FAIL（fracs 偏离 k/n）；`test_fit_y_to_visible_x_subplot_does_not_reframe` PASS（subplot 路径本就不变）。

- [ ] **Step 3: 最小实现**

在 `mf4_analyzer/ui/pg_canvases.py` 的 `fit_y_to_visible_x` 内，`self._refresh = True` 与 `self.draw_idle()` 之前插入叠加重框。定位（Edit 锚点，含上下文）：

把
```python
                try:
                    handle.set_ylim(lo - pad, hi + pad)
                except Exception:
                    pass
            self._refresh = True
            self.draw_idle()
        finally:
```
改为
```python
                try:
                    handle.set_ylim(lo - pad, hi + pad)
                except Exception:
                    pass
            if self._overlay_mode:
                # #3 叠加 graticule 不变量：上面每个通道刚设的"原始拟合范围"
                # 必须再规整到 nice n 等分网格并重钉刻度，否则固定 k/n 网格线
                # 与通道刻度会错位。与 set_tick_density / box-zoom 同款重框。
                self._repin_overlay_channel_ticks()
            self._refresh = True
            self.draw_idle()
        finally:
```

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py::TestFitYToVisibleOverlay -v`
Expected: 两条都 PASS。

- [ ] **Step 5: 回归既有叠加测试**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py -v`
Expected: 全部 PASS（未触碰 `_frame_to_nice`/repin 算法）。

- [ ] **Step 6: 暂不提交**

记录 Task 1 结果即可；继续 Task 2/3，避免把同一修复拆成多个半成品 commit。

---

## Task 2: #2(a) — aux 几何同步挪到 build 末尾 + 强制 layout settle

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`
  - 新增 `_settle_layout()`（≈4219，`_sync_overlay_aux_viewboxes` 上方）
  - `_build` ≈1687：删早期 `_sync_overlay_aux_viewboxes()`
  - `_build` ≈1699-1701：末尾补 settle+sync
- Test: `tests/ui/test_overlay_grid_ticks.py`（追加 `TestOverlaySwitchGeometry`）

- [ ] **Step 1: 写失败测试**

在 `tests/ui/test_overlay_grid_ticks.py` 末尾追加：

```python
class TestOverlaySwitchGeometry:
    """分叠切换 (#2)：叠加 aux ViewBox 是场景项、只能由 setGeometry 定位。
    build 必须在 tick/axis 几何工作之后，再 layout settle + sync aux，
    不靠后续 sigResized 自愈 (codex-pg-subplot-layout-settle)。"""

    def _rows(self):
        t = np.linspace(0.0, 1.0, 256)
        return [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t), "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.5 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
            ("ch2", True, t, 1.2 * np.sin(2 * np.pi * 5 * t), "#17a07b", "Nm", "fid-2"),
        ]

    def _assert_aux_match_xmaster(self, canvas, tol=1.0):
        xm = canvas._x_master_handle.view_box.sceneBoundingRect()
        assert canvas._overlay_aux_viewboxes, "overlay must build aux ViewBoxes"
        assert xm.width() > 1.0 and xm.height() > 1.0, "X-master rect must be settled"
        for aux in canvas._overlay_aux_viewboxes:
            r = aux.sceneBoundingRect()
            assert abs(r.x() - xm.x()) <= tol
            assert abs(r.y() - xm.y()) <= tol
            assert abs(r.width() - xm.width()) <= tol
            assert abs(r.height() - xm.height()) <= tol

    def test_overlay_build_syncs_aux_after_tick_density_layout_work(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        density_applied = {"value": False}
        sync_calls = []

        original_density = canvas._apply_tick_density_to_all_axes
        original_sync = canvas._sync_overlay_aux_viewboxes

        def mark_density_applied():
            density_applied["value"] = True
            return original_density()

        def record_sync_order():
            sync_calls.append(density_applied["value"])
            return original_sync()

        canvas._apply_tick_density_to_all_axes = mark_density_applied
        canvas._sync_overlay_aux_viewboxes = record_sync_order

        canvas.plot_channels(self._rows(), mode="overlay")

        assert sync_calls, "overlay build must sync aux ViewBoxes"
        assert any(sync_calls), (
            "aux sync must run after tick-density/axis geometry work, not only early"
        )

    def test_switch_subplot_to_overlay_aux_matches_xmaster_after_build(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas
        from PyQt5.QtCore import QCoreApplication

        canvas = _pg_canvas(qapp)
        rows = self._rows()
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        self._assert_aux_match_xmaster(canvas)
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py::TestOverlaySwitchGeometry::test_overlay_build_syncs_aux_after_tick_density_layout_work -v`
Expected: FAIL —— 当前代码只在 `_apply_tick_density_to_all_axes()` 之前调用 `_sync_overlay_aux_viewboxes()`，记录为 `[False]`；修复后早期 sync 删除，build 末尾 sync 记录到 `True`。

- [ ] **Step 3: 新增 `_settle_layout()` 辅助**

在 `mf4_analyzer/ui/pg_canvases.py` 中 `def _sync_overlay_aux_viewboxes(self):`（≈4219）之前插入：

```python
    def _settle_layout(self):
        """Force the GraphicsLayout to recompute geometry NOW.

        Overlay aux ViewBoxes live on the scene (not the layout) and are
        positioned only via setGeometry, so callers that must read a settled
        X-master rect before syncing aux geometry settle the layout first.
        Mirrors the invalidate()+activate() the subplot axis unifiers already
        use. See docs/lessons-learned/codex-pg-subplot-layout-settle.md.
        """
        try:
            layout = self._glw.ci.layout
            layout.invalidate()
            layout.activate()
        except Exception:
            pass
```

- [ ] **Step 4: 删 build 早期同步**

在 `_build` 内（≈1687）把
```python
            if self._overlay_mode:
                self._sync_overlay_aux_viewboxes()
                self._connect_overlay_view_sync()
```
改为
```python
            if self._overlay_mode:
                # 真正的几何同步移到 _build 末尾，待 tick-density / repin /
                # axis 几何整理后再 settle + sync。这里仅连实时 sigResized 兜底。
                self._connect_overlay_view_sync()
```

- [ ] **Step 5: build 末尾补 settle + sync**

在 `_build` 末尾 `self._unify_subplot_left_axis_widths()`（≈1699）与其后的 `# Bug 3: notify owners...` 注释之间插入：

把
```python
        self._unify_subplot_left_axis_widths()

        # Bug 3: notify owners that fresh ViewBoxes exist so they can
```
改为
```python
        self._unify_subplot_left_axis_widths()

        if self._overlay_mode:
            # #2 aux ViewBox 是场景项、只能由 setGeometry 定位；叠加模式下上面的
            # _unify_subplot_left_axis_widths 当前会 no-op，但 tick-density / repin
            # 等 build 尾部工作仍应先完成。此处强制 settle 并按最终 X 主轴矩形
            # 对齐 aux，使切换后的首帧即对齐 (codex-pg-subplot-layout-settle)。
            # 放在回调之前，让重置交互态的回调看到正确几何。
            self._settle_layout()
            self._sync_overlay_aux_viewboxes()

        # Bug 3: notify owners that fresh ViewBoxes exist so they can
```

- [ ] **Step 6: 跑测试确认 GREEN**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py::TestOverlaySwitchGeometry -v`
Expected: PASS（顺序合同与几何 smoke 都通过）。

- [ ] **Step 7: 暂不提交**

记录 Task 2 结果即可；继续 Task 3，最终统一提交。

---

## Task 3: #2(b) — resize 稳定后重同步 aux 几何兜底

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py:5388`（`_on_resize_settled`）
- Test: `tests/ui/test_overlay_grid_ticks.py`（向 `TestOverlaySwitchGeometry` 追加用例）

- [ ] **Step 1: 写失败测试**

向 `TestOverlaySwitchGeometry` 类追加方法：

```python
    def test_resize_settled_resyncs_aux_geometry(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas
        from PyQt5.QtCore import QCoreApplication, QRectF

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(self._rows(), mode="overlay")
        QCoreApplication.processEvents()

        # 断开实时兜底，人为打乱 aux 几何，验证 resize-settle 路径能纠正。
        canvas._disconnect_overlay_view_sync()
        for aux in canvas._overlay_aux_viewboxes:
            aux.setGeometry(QRectF(0.0, 0.0, 5.0, 5.0))

        canvas._on_resize_settled()
        self._assert_aux_match_xmaster(canvas)
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_overlay_grid_ticks.py::TestOverlaySwitchGeometry::test_resize_settled_resyncs_aux_geometry" -v`
Expected: FAIL —— `_on_resize_settled` 当前不调 `_sync_overlay_aux_viewboxes`，被打乱的 5×5 aux 几何保持不变。

- [ ] **Step 3: 实现 — `_on_resize_settled` 补叠加兜底**

在 `_on_resize_settled` 内，`_unify_subplot_*` 的 try 块之后插入。把
```python
        try:
            self._apply_target_x_ticks_to_all_axes()
            self._unify_subplot_left_axis_widths()
            self._unify_subplot_bottom_axis_heights()
        except Exception:
            pass
```
改为
```python
        try:
            self._apply_target_x_ticks_to_all_axes()
            self._unify_subplot_left_axis_widths()
            self._unify_subplot_bottom_axis_heights()
        except Exception:
            pass
        try:
            # #2 兜底：sigResized 不覆盖所有重排时机，窗口缩放稳定后按最终 X 主轴
            # 矩形重对齐 aux 几何。
            if self._overlay_mode:
                self._settle_layout()
                self._sync_overlay_aux_viewboxes()
        except Exception:
            pass
```

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_overlay_grid_ticks.py::TestOverlaySwitchGeometry" -v`
Expected: 三条都 PASS。

- [ ] **Step 5: 全量回归**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py tests/ui/test_pg_timedomain_canvas.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 暂不提交**

记录 Task 3 结果即可；进入 Task 4 真机视觉复核。若用户要求提交，所有任务完成后再用一个窄范围 commit。

---

## Task 4: 真机视觉复核（非测试，按 verify-ui-visually 经验）

**Files:** 无代码改动。

- [ ] **Step 1: 启动应用，载入多通道 MF4，进入时域叠加模式。**
- [ ] **Step 2: 反复在 分图 ↔ 叠加 之间切换数次**，确认每次切换后网格线与各通道右轴刻度即时对齐、曲线坐在网格上，无"歪"的首帧。截图留档。
- [ ] **Step 3: 平移 X 后右键「Y 轴自适应」**，确认刻度落在网格线上、标签为规整数；对每个通道分别验证。截图留档。
- [ ] **Step 4: 拖动窗口边缘改变大小**，确认稳定后 aux 与网格仍对齐。
- [ ] **Step 5: 把两张截图与结论附到** `docs/superpowers/reports/`（沿用既有命名）。

---

## Self-Review

- **Spec 覆盖**：#3 → Task 1；#2 build 尾部同步顺序 + 首帧几何 smoke → Task 2；#2 resize 兜底 → Task 3；视觉验证 → Task 4。#1 明确非目标，无对应任务（符合 spec）。✓
- **占位符扫描**：所有步骤含真实测试/实现代码与可执行命令。✓
- **类型/命名一致**：`_settle_layout`、`_sync_overlay_aux_viewboxes`、`_repin_overlay_channel_ticks`、`_disconnect_overlay_view_sync`、`_overlay_divisions`、`y_axis_item()`、`_channel_lines`、`axes_list`、`_x_master_handle.view_box` 全部与现有源码一致（已核对）。✓
- **测试可红可绿**：#3 用当前 tick fraction 偏离 `k/n` 证伪；#2 build 用 monkeypatch 调用顺序合同稳定先红后绿，避免 offscreen 下 1px 几何容差伪绿；#2 resize 用打乱 aux 几何隔离 resize-settle 路径。✓

---

## Execution Handoff

Plan 已存至 `docs/superpowers/plans/2026-06-07-overlay-grid-tick-realign.md`。

本仓库 CLAUDE.md 规定 UI 代码改动走 squad（pyqt-ui-engineer 实施）。建议执行路径：

1. **Squad runbook（符合仓库约定）** —— 主 Claude 调 `squad-orchestrator` 出 plan、再派 `pyqt-ui-engineer` 按本 Task 表逐条 TDD 实施。
2. **subagent-driven-development** —— 每个 Task 派一个全新 subagent，Task 间评审。

下一步如需执行，按本计划从 Task 1 的 RED 测试开始；执行前先确认工作区中其他未提交改动是否需要隔离。
