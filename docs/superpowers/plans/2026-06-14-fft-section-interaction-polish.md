# FFT Section 交互与视觉打磨 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修好 FFT section 的四个交互/视觉问题：标注字体宋体（全局 setFont）、时域预览顶部双线（网格/边框）、时域拖动应为"框选范围做 FFT"而非平移、拖动卡顿（AA 未真正取消）。

**Architecture:** R1 在 app 启动期把应用默认字体的 family 改成解析出的 CJK family（复用现有 `pg_canvas/fonts.py`），一次覆盖所有未显式设字体的 pg 图元。R2/R4 是 `line_canvas.py` 的点状修复（关 top/right 冗余网格 + 空状态 Y 留白；AA 下沉到被渲染的子 `PlotCurveItem`）。R3 给时域预览加 `LinearRegionItem` + 专用 ViewBox，把左键拖动语义从平移改为框选，复用既有 `time_preview_range_changed → main_window` 链路驱动 FFT 范围。

**Tech Stack:** PyQt5、pyqtgraph 0.14、pytest-qt、既有 `tests/ui/` 套件。

**配套 spec：** `docs/superpowers/specs/2026-06-14-fft-section-interaction-polish-design.md`

---

## 协调前置（必读）

- **codex 正在改 `line_canvas.py` / `heatmap_canvas.py`（分隔条 `_SplitDivider`，未提交）。**
- **Task 1（R1）** 只碰 `app.py` + `pg_canvas/fonts.py`（codex 未碰）→ 可立即执行、独立提交。
- **Task 2/3/4（R4/R2/R3）** 全在 `line_canvas.py`：**必须等 codex 的分隔条改动提交到 main 后**，在干净基线上做，避免同文件撞 hunk。执行前先 `git log --oneline -3` 确认 codex 已落地、`git status` 该文件 clean。
- 下文行号为 2026-06-14 快照，codex 落地后会漂移；**以函数/符号名定位**。

## File Structure

- `mf4_analyzer/ui/pg_canvas/fonts.py` — 新增 `apply_global_chart_font(app)`（R1）。
- `mf4_analyzer/app.py` — 启动期调用 `apply_global_chart_font`（R1）。
- `mf4_analyzer/ui/pg_canvas/line_canvas.py` — 关 top/right 网格 + 空状态 Y 留白（R2）；`_set_curve_aa` 下沉子 curve（R4）；`LinearRegionItem` + `_TimePreviewViewBox` + `select_time_region`/`clear_time_region`（R3）。
- `tests/ui/test_pg_line_canvas.py` — 全部回归测试（已有 `canvas` / `qapp` fixture）。

---

## Task 1: R1 — 全局 setFont（只改 family，不改字号）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/fonts.py`
- Modify: `mf4_analyzer/app.py:78-80`
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试**

加到 `tests/ui/test_pg_line_canvas.py`（用已有 `qapp` fixture）。测试自带 save/restore，避免污染全局字体影响其它用例：

```python
def test_apply_global_chart_font_sets_cjk_family(qapp):
    import pyqtgraph as pg
    from mf4_analyzer.ui.pg_canvas.fonts import (
        apply_global_chart_font, _pg_chart_font,
    )
    saved = qapp.font()
    try:
        apply_global_chart_font(qapp)
        family = _pg_chart_font().family()
        # 应用默认字体 family 跟随解析出的 CJK family（字号不强制相等）
        assert qapp.font().family() == family
        # 未显式设字体的 pg.TextItem 继承之（标注/banner 走这条路）
        item = pg.TextItem("x")
        assert item.textItem.font().family() == family
    finally:
        qapp.setFont(saved)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_apply_global_chart_font_sets_cjk_family -q`
Expected: FAIL — `ImportError: cannot import name 'apply_global_chart_font'`。

- [ ] **Step 3: 实现 helper**

在 `mf4_analyzer/ui/pg_canvas/fonts.py` 末尾（`__all__` 之前）加：

```python
def apply_global_chart_font(app=None):
    """Set the application default font FAMILY to the resolved CJK chart family,
    preserving the existing point size, so pyqtgraph graphics items (TextItem,
    and axes without an explicit tickFont) stop falling back to the platform
    default (SimSun on Windows). Family-only change keeps widget metrics stable.
    """
    app = app or QApplication.instance()
    if app is None:
        return
    family = _pg_chart_font().family()
    base = app.font()
    if base.family() != family:
        base.setFamily(family)
        app.setFont(base)
```

并把 `apply_global_chart_font` 加入 `__all__`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_apply_global_chart_font_sets_cjk_family -q`
Expected: PASS。

- [ ] **Step 5: 在 app 启动期调用**

`mf4_analyzer/app.py`，把 `app = QApplication(sys.argv)` 之后改为：

```python
    app = QApplication(sys.argv)
    from mf4_analyzer.ui.pg_canvas.fonts import apply_global_chart_font
    apply_global_chart_font(app)
    app.setStyle('Fusion')
```

- [ ] **Step 6: 跑既有套件 + 目视主窗口**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_main_window_smoke.py -q`
Expected: PASS。再手动起一次应用，确认标注文字与坐标轴在中文环境为雅黑/PingFang，控件布局无明显漂移。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/fonts.py mf4_analyzer/app.py tests/ui/test_pg_line_canvas.py
git commit -m "fix(fft): apply global CJK chart font so pg text stops falling back to SimSun"
```

---

## Task 2: R4 — AA 下沉到被渲染的子 curve（拖动卡顿）

> 先做 R4：改动最小、收益最大，且为后续 R2/R3 验证拖动手感打底。**需 codex 分隔条已落地**（见协调前置）。

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（`_set_curve_aa`）
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试**

```python
def test_disable_interactive_quality_drops_aa_on_rendered_child(canvas):
    """AA 必须落到被绘制的子 PlotCurveItem，否则平移期 AA 根本没关。"""
    import numpy as np
    def _e(label, color):
        t = np.linspace(0, 1, 200)
        return {'label': label, 'color': color, 'freq': t, 'amp': t,
                'time': t, 'signal': np.sin(t)}
    canvas.plot_spectra(
        [_e('a', '#2563eb'), _e('b', '#22c55e'), _e('c', '#f59e0b')],
        xlim=(0.0, 1.0), amp_label='Amplitude', title='t')
    canvas.disable_interactive_quality()
    for c in canvas._interactive_curves():
        child = getattr(c, 'curve', None)
        assert child is not None
        assert child.opts.get('antialias') is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_disable_interactive_quality_drops_aa_on_rendered_child -q`
Expected: FAIL — 至少一条 child 的 `antialias` 仍为 `True`（实证已确认）。

- [ ] **Step 3: 改 `_set_curve_aa` 下沉到子 curve**

把 `line_canvas.py` 的 `_set_curve_aa` 改为：

```python
    @staticmethod
    def _set_curve_aa(curve, on):
        on = bool(on)
        try:
            curve.opts["antialias"] = on
        except Exception:
            pass
        # pyqtgraph 0.14: PlotDataItem 的 antialias 只在 updateItems() 经
        # curve.setData(...) 流到子 PlotCurveItem；FFT 预览平移不重新 setData，
        # 故直接落到被渲染的子 curve 并触发重绘（不重新 setData，便宜）。
        child = getattr(curve, "curve", None)
        if child is not None:
            try:
                child.opts["antialias"] = on
                child.update()
            except Exception:
                pass
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_disable_interactive_quality_drops_aa_on_rendered_child -q`
Expected: PASS。

- [ ] **Step 5: 跑 AA 相关既有用例 + 手感验证**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "aa or antialias or quality or idle" -q`
Expected: PASS。手动在 FFT 叠加多通道后拖动谱图/时域，确认明显跟手、空闲后恢复清晰。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "fix(fft): sink interactive AA toggle onto rendered child curve to drop pan lag"
```

---

## Task 3: R2 — 时域预览顶部去双线（网格/边框）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（构造里的 `showGrid` 循环；`full_reset` 空状态）
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试**

```python
def test_grid_only_on_left_and_bottom(canvas):
    for plot in (canvas._plot_amp, canvas._plot_time):
        assert plot.getAxis('top').grid is False
        assert plot.getAxis('right').grid is False
        assert plot.getAxis('left').grid is not False     # 仍开启（int alpha）
        assert plot.getAxis('bottom').grid is not False


def test_empty_state_time_y_padded_off_top_frame(canvas):
    """空状态最高刻度网格线不贴顶边框（视图上界 > 1.0）。"""
    canvas.full_reset()
    (_y0, y1) = canvas._plot_time.vb.viewRange()[1]
    assert y1 > 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "grid_only or padded_off_top" -q`
Expected: FAIL — top/right `grid == 63`；空状态 Y 上界 `== 1.0`。

- [ ] **Step 3: 关 top/right 网格**

`line_canvas.py` 构造里，把 `for p in (self._plot_amp, self._plot_time):` 中 `p.showGrid(x=True, y=True, alpha=0.25)` 之后补：

```python
            p.showGrid(x=True, y=True, alpha=0.25)
            # major grid 只画在 left+bottom；top/right 关掉，避免横向网格被
            # 左右两轴重复过绘、且顶部网格线与边框叠成"双线"（spec R2）。
            p.getAxis('top').setGrid(False)
            p.getAxis('right').setGrid(False)
```

- [ ] **Step 4: 空状态 Y 留白**

`full_reset` 里把两图的 `enableAutoRange(axis='y')` 段改为给一个带 padding 的初始 Y（pyqtgraph 对空数据 autorange 硬给 `(0,1)`、不吃 defaultPadding），使边界刻度离开边框：

```python
        # 空状态：显式留白，避免最高刻度网格线贴顶边框（spec R2）。有数据时
        # 后续 plot_*/reset 会重新设范围，这里只管空态观感。
        for p in (self._plot_amp, self._plot_time):
            p.setYRange(0.0, 1.0, padding=0.08)
```

（替换原先 `for p in (...): p.enableAutoRange(axis='y')` 那两行。）

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "grid_only or padded_off_top" -q`
Expected: PASS。

- [ ] **Step 6: 视觉验证（对照用户截图）**

渲染空 `PgLineCanvas`、抓 `_glw.grab()`，裁切 `_plot_time` 顶部 ~16px 放大对比：顶部应为**单条边框线**，内部网格正常、无紧贴边框的第二条线。若仍有残留双线，确认是否为 codex 两图间距（`_SplitDivider` 间隙）导致，必要时在本任务补间距调整。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "fix(fft): drop redundant top/right grid + pad empty-state Y so top frame reads single line"
```

---

## Task 4: R3 — 时域预览左键拖动 = 框选范围做 FFT（功能改造）

> 最大的一项。先做"选区逻辑 + 信号"（可确定性测试），再做"拖动交互接线"（轻测 + 目视）。

### 4a：选区 region + select/clear 方法 + 信号

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（`__init__` 加 region；新增 `select_time_region` / `clear_time_region`）
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试**

```python
def test_select_time_region_emits_range_without_panning(canvas):
    import numpy as np
    t = np.linspace(0.0, 10.0, 500)
    canvas.plot_spectra(
        [{'label': 's', 'color': '#2563eb', 'freq': np.linspace(0, 50, 128),
          'amp': np.ones(128), 'time': t, 'signal': np.sin(t)}],
        xlim=(0.0, 50.0), amp_label='Amplitude', title='t')
    x_before = tuple(canvas._plot_time.vb.viewRange()[0])
    got = []
    canvas.time_preview_range_changed.connect(lambda lo, hi: got.append((lo, hi)))
    canvas.select_time_region(2.0, 6.0)
    # region 已建立、范围已发射
    assert canvas._time_region.isVisible()
    assert got and got[-1][0] == __import__('pytest').approx(2.0, abs=1e-6)
    assert got[-1][1] == __import__('pytest').approx(6.0, abs=1e-6)
    # 关键：X 视图未被平移
    x_after = tuple(canvas._plot_time.vb.viewRange()[0])
    assert x_after == __import__('pytest').approx(x_before, abs=1e-6)


def test_clear_time_region_hides_selection(canvas):
    import numpy as np
    t = np.linspace(0.0, 10.0, 500)
    canvas.plot_spectra(
        [{'label': 's', 'color': '#2563eb', 'freq': np.linspace(0, 50, 128),
          'amp': np.ones(128), 'time': t, 'signal': np.sin(t)}],
        xlim=(0.0, 50.0), amp_label='Amplitude', title='t')
    canvas.select_time_region(2.0, 6.0)
    canvas.clear_time_region()
    assert not canvas._time_region.isVisible()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "select_time_region or clear_time_region" -q`
Expected: FAIL — `AttributeError: '_time_region'` / `select_time_region`。

- [ ] **Step 3: 加 region item（构造）**

`__init__` 末尾（collapse/divider 之后）加：

```python
        # 时域预览的"框选范围做 FFT"选区。左键拖动建立（见 _TimePreviewViewBox），
        # 区间变化驱动 time_preview_range_changed；视图不平移。
        self._time_region = pg.LinearRegionItem(
            brush=pg.mkBrush(37, 99, 235, 40),
            pen=pg.mkPen('#2563eb', width=1),
            movable=True,
        )
        self._time_region.setZValue(20)
        self._time_region.setVisible(False)
        self._plot_time.addItem(self._time_region, ignoreBounds=True)
        self._time_region.sigRegionChangeFinished.connect(
            self._on_time_region_changed)
```

- [ ] **Step 4: 加 select/clear/handler 方法**

```python
    def select_time_region(self, t0, t1):
        """Set the FFT time-window selection to [t0, t1] (no view pan) and emit
        the range so the FFT inspector picks it up."""
        lo, hi = (float(t0), float(t1)) if t0 <= t1 else (float(t1), float(t0))
        self._time_region.blockSignals(True)
        try:
            self._time_region.setRegion((lo, hi))
        finally:
            self._time_region.blockSignals(False)
        self._time_region.setVisible(True)
        if hi > lo:
            self.time_preview_range_changed.emit(lo, hi)

    def clear_time_region(self):
        self._time_region.setVisible(False)

    def _on_time_region_changed(self, *_args):
        lo, hi = self._time_region.getRegion()
        if hi > lo:
            self.time_preview_range_changed.emit(float(lo), float(hi))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "select_time_region or clear_time_region" -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "feat(fft): add time-preview range selection region driving FFT window"
```

### 4b：左键拖动语义改为框选（专用 ViewBox）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（新增 `_TimePreviewViewBox`；`_plot_time` 改用之）
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试（直接驱动拖动处理，不模拟原始鼠标事件）**

```python
def test_time_preview_left_drag_builds_region_not_pan(canvas):
    import numpy as np
    t = np.linspace(0.0, 10.0, 500)
    canvas.plot_spectra(
        [{'label': 's', 'color': '#2563eb', 'freq': np.linspace(0, 50, 128),
          'amp': np.ones(128), 'time': t, 'signal': np.sin(t)}],
        xlim=(0.0, 50.0), amp_label='Amplitude', title='t')
    vb = canvas._plot_time.vb
    from mf4_analyzer.ui.pg_canvas.line_canvas import _TimePreviewViewBox
    assert isinstance(vb, _TimePreviewViewBox)
    x_before = tuple(vb.viewRange()[0])
    # 数据坐标的拖动 [3, 7] → 选区建立、X 不平移
    vb.build_region_from_data(3.0, 7.0)
    assert canvas._time_region.isVisible()
    lo, hi = canvas._time_region.getRegion()
    assert (lo, hi) == __import__('pytest').approx((3.0, 7.0), abs=1e-6)
    assert tuple(vb.viewRange()[0]) == __import__('pytest').approx(x_before, abs=1e-6)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_time_preview_left_drag_builds_region_not_pan -q`
Expected: FAIL — 无 `_TimePreviewViewBox` / `build_region_from_data`。

- [ ] **Step 3: 新增 `_TimePreviewViewBox`**

在 `line_canvas.py` 顶部（`PgLineCanvas` 之前）加，继承现有 `_ModifierWheelViewBox` 以保留 Ctrl/Shift 滚轮缩放与右键菜单：

```python
from .viewbox import _ModifierWheelViewBox


class _TimePreviewViewBox(_ModifierWheelViewBox):
    """时域预览专用 ViewBox：左键拖动 = 框选 FFT 时间范围（不平移）。

    其余交互（Ctrl/Shift 滚轮缩放、右键菜单）沿用父类。"""

    def build_region_from_data(self, x0, x1):
        owner = self._owner_canvas
        if owner is not None and hasattr(owner, "select_time_region"):
            owner.select_time_region(x0, x1)

    def mouseDragEvent(self, ev, axis=None):
        from PyQt5.QtCore import Qt
        if ev.button() == Qt.LeftButton and axis is None:
            ev.accept()
            p0 = self.mapToView(ev.buttonDownPos())
            p1 = self.mapToView(ev.pos())
            self.build_region_from_data(float(p0.x()), float(p1.x()))
            return
        super().mouseDragEvent(ev, axis=axis)
```

- [ ] **Step 4: `_plot_time` 改用专用 ViewBox**

把 `__init__` 里创建 `_plot_time` 的 `viewBox=_ModifierWheelViewBox(owner_canvas=self)` 改为 `viewBox=_TimePreviewViewBox(owner_canvas=self)`。`_plot_amp` 保持 `_ModifierWheelViewBox` 不变。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_time_preview_left_drag_builds_region_not_pan -q`
Expected: PASS。

- [ ] **Step 6: 加清除入口（右键菜单"清除选区"）+ 测试**

在 `_redesign_context_menu_for_viewbox` 里，当 `plot is self._plot_time` 时追加一个"清除选区"动作调用 `self.clear_time_region`。补一条断言菜单含该动作、触发后 `_time_region` 隐藏的测试。

- [ ] **Step 7: 导出不收录选区**

确认 `grab_pixmap` 不把 region 画进数据像素；若收录，导出前临时 `setVisible(False)` 再恢复。加一条测试：`select_time_region(2,6)` 后 `grab_pixmap(scale=1.0)` 不为 null（冒烟）。

- [ ] **Step 8: 全套件 + 目视**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_analysis_section_page.py -q`
Expected: PASS。手动：FFT 选源→在下方时域左键拖一段→inspector 范围更新、谱图按该段重算；视图未被拖走；右键可清除。

- [ ] **Step 9: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "feat(fft): left-drag on time preview selects FFT range instead of panning"
```

---

## Self-Review（写完自查）

**1. Spec 覆盖**：R1→Task 1；R4→Task 2；R2→Task 3；R3→Task 4a/4b。四项需求各有任务，无缺口。

**2. Placeholder 扫描**：Task 4b Step 6/7 用文字描述了"加清除动作 / 导出不收录"而未贴完整代码——这两步依赖 codex 落地后的 `_redesign_context_menu_for_viewbox` 与 `grab_pixmap` 实际形态，执行时按当时代码补全；其余步骤均含可直接落地的真实代码。

**3. 类型/命名一致**：`select_time_region` / `clear_time_region` / `_time_region` / `_on_time_region_changed` / `_TimePreviewViewBox` / `build_region_from_data` / `apply_global_chart_font` 在各任务间一致；`time_preview_range_changed(float, float)` 沿用既有签名，不改 `main_window` 侧。

**4. 风险点**：R3 的拖动接线（4b）与 codex 的 ViewBox/分隔条改动同处一文件，务必在 codex 提交后基线上做；R2 空状态 Y 留白只改空分支、不碰有数据路径。
