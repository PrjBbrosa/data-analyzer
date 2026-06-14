# 分析 Section 上下折叠改 drawer 风格细带 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 FFT line / FFT-time / Order heatmap 三个分析 section 的上下折叠，从「左 gutter 三角按钮」改成「拖分隔条到近底部折叠 + 底部细带小灰▴点击展开」的 drawer 风格；保留可拖拽分隔条调比例。

**Architecture:** 在共享模块 `heatmap_canvas.py` 新增横向 `_CollapsedRail`（rail 作为 canvas 顶层 QVBoxLayout 中 `_glw` 下方成员，隐藏时占 0 高、绝不遮上图底轴）+ 折叠阈值常量 + 新定位 helper；两个 canvas 把 `_collapse_ctrl`(三角) 换成 `_collapsed_rail`，`_on_split_drag_delta` 在下图原始目标高 ≤ 阈值时折叠，`_set_bottom_collapsed` 统一应用状态。保留 `_on_collapse_changed`/`_position_collapse_ctrl`/`_position_split_divider` 作为兼容入口（仅改 body），最大限度复用既有测试。

**Tech Stack:** PyQt5、pyqtgraph 0.14、pytest-qt、既有 `tests/ui/test_pg_line_canvas.py` + `tests/ui/test_pg_heatmap_canvas.py`。

**配套 spec:** `docs/superpowers/specs/2026-06-14-analysis-section-vertical-drawer-collapse-design.md`

---

## 执行前置
- 确认 `git status` 干净、`mf4_analyzer/ui/pg_canvas/line_canvas.py` 与 `heatmap_canvas.py` clean（codex baseline 0f7338e 已落地）。行号为 2026-06-14 快照，以函数/符号名定位。
- 测试一律用 `.venv/bin/python -m pytest ...`（`python` 不在 PATH）。
- 每个 task 用显式 pathspec `git add <files>`，不要 `git add -A`。

## File Structure
- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` — 共享控件/常量/helper（Task 1）+ PgHeatmapCanvas 接线（Task 3）+ 删 `_PlotCollapseControl`/旧 helper（Task 4）。
- `mf4_analyzer/ui/pg_canvas/line_canvas.py` — PgLineCanvas 接线（Task 2）。
- `mf4_analyzer/ui_kit/style.qss` — QSS（Task 4）。
- `tests/ui/test_pg_line_canvas.py`、`tests/ui/test_pg_heatmap_canvas.py` — 新增 + 迁移测试。

---

## Task 1: 共享控件 — `_CollapsedRail` + 阈值 + 定位 helper（纯新增）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`（在 `_SplitDivider` 之后、`_apply_plot_collapse` 之前插入）
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试**

加到 `tests/ui/test_pg_line_canvas.py`：

```python
def test_collapsed_rail_emits_expand_on_left_click(qapp):
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _CollapsedRail
    rail = _CollapsedRail()
    got = []
    rail.expand_requested.connect(lambda: got.append(True))
    ev = QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(5, 5),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    rail.mousePressEvent(ev)
    assert got == [True]
    assert rail.height() == _CollapsedRail.HEIGHT_PX
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_collapsed_rail_emits_expand_on_left_click -q`
Expected: FAIL — `ImportError: cannot import name '_CollapsedRail'`。

- [ ] **Step 3: 实现 `_CollapsedRail` + 常量 + helper**

在 `heatmap_canvas.py` 的 `_SplitDivider` 类之后插入（`QFrame`/`QPointF`/`QPolygonF`/`QColor`/`QPainter`/`Qt` 均已 import）：

```python
# Bottom-plot height (px) below which a divider drag collapses the lower plot
# instead of clamping — the vertical analog of SidePanelController.COLLAPSE_THRESHOLD.
_SPLIT_COLLAPSE_AT = 40


class _CollapsedRail(QFrame):
    """Thin horizontal rail shown at the canvas bottom when the lower plot is
    folded away — the vertical analog of side_panels.SidePanelStrip. Paints a
    small gray ▴; left-click re-expands the bottom plot. Laid out by the canvas
    QVBoxLayout (below the GraphicsLayoutWidget); hidden => occupies 0 height,
    so it never overlaps the top plot's bottom axis."""

    expand_requested = pyqtSignal()
    HEIGHT_PX = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plotCollapsedRail")
        self.setFixedHeight(self.HEIGHT_PX)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("展开下图")
        self._hover = False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.expand_requested.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, event):
        super().paintEvent(event)  # QSS faint bg + top border
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            color = QColor("#2563eb") if self._hover else QColor("#7b8699")
            cx, cy = self.width() / 2.0, self.height() / 2.0
            hw, hh = 5.0, 3.0
            pts = [QPointF(cx, cy - hh), QPointF(cx + hw, cy + hh),
                   QPointF(cx - hw, cy + hh)]  # ▴ apex up
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF(pts))
        finally:
            painter.end()


def _position_collapse_layout(rail, divider, top_plot, bottom_plot, collapsed):
    """Drawer-style placement: when collapsed, hide the divider and surface the
    bottom rail (the rail is laid out by the canvas QVBoxLayout, so it only
    needs show + raise); when expanded, hide the rail and place the draggable
    divider on the gap between the two plots (data-area width)."""
    if collapsed:
        if divider is not None:
            divider.hide()
        if rail is not None:
            rail.setVisible(True)
            rail.raise_()
        return
    if rail is not None:
        rail.setVisible(False)
    if divider is None:
        return
    try:
        vb = top_plot.vb.sceneBoundingRect()
    except Exception:
        return
    try:
        boundary_y = _split_boundary_y(top_plot, bottom_plot, False)
    except Exception:
        boundary_y = float(vb.bottom())
    parent = divider.parentWidget()
    width = int(parent.width()) if parent is not None else int(vb.width())
    if not top_plot.isVisible() or width <= 0:
        divider.hide()
        return
    divider.setFixedWidth(width)
    divider.move(0, max(0, int(boundary_y - divider.height() / 2)))
    divider.show()
    divider.raise_()
```

- [ ] **Step 4: 跑测试确认通过 + 既有套件未破**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_collapsed_rail_emits_expand_on_left_click tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py -q`
Expected: 新用例 PASS；其余全绿（纯新增，未动既有路径）。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "feat(analysis): add horizontal _CollapsedRail + drag-collapse threshold + layout helper"
```

---

## Task 2: PgLineCanvas 接线改 rail + 拖拽折叠

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（import 块；`__init__` 折叠控件块；`_on_collapse_changed`/`_position_collapse_ctrl`/`_on_split_drag_delta`/`_on_split_reset`；新增 `_set_bottom_collapsed`）
- Test: `tests/ui/test_pg_line_canvas.py`

- [ ] **Step 1: 写失败测试（新行为）**

加到 `tests/ui/test_pg_line_canvas.py`：

```python
def test_fft_drag_near_bottom_collapses_and_rail_expands(canvas, qapp):
    canvas.resize(900, 460); canvas.show(); qapp.processEvents()
    # 拖到近底部：raw 目标高 <= 阈值 -> 折叠
    canvas._on_split_drag_started()
    canvas._on_split_drag_delta(-100000)   # 大负 delta 把下图拖没
    assert canvas._bottom_collapsed is True
    assert not canvas._plot_time.isVisible()
    assert canvas._collapsed_rail.isVisible()
    assert not canvas._split_divider.isVisible()
    # 点 rail 展开，恢复到记忆高度
    canvas._collapsed_rail.expand_requested.emit()
    assert canvas._bottom_collapsed is False
    assert canvas._plot_time.isVisible()
    assert not canvas._collapsed_rail.isVisible()
    assert canvas._split_divider.isVisible()
    assert canvas._plot_time.maximumHeight() == int(canvas._bottom_split_h)


def test_fft_drag_dead_zone_does_not_collapse(canvas, qapp):
    canvas.resize(900, 460); canvas.show(); qapp.processEvents()
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _SPLIT_COLLAPSE_AT, _SPLIT_MIN_BOTTOM)
    canvas._on_split_drag_started()
    # 落在 (阈值, MIN_BOTTOM] 的死区：clamp 到最小、不折叠
    target = (_SPLIT_COLLAPSE_AT + _SPLIT_MIN_BOTTOM) / 2.0
    canvas._on_split_drag_delta(int(target - canvas._drag_start_bottom_h))
    assert canvas._bottom_collapsed is False
    assert canvas._plot_time.isVisible()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -k "drag_near_bottom_collapses or dead_zone" -q`
Expected: FAIL — `AttributeError: '_collapsed_rail'` / `_bottom_collapsed`。

- [ ] **Step 3: 改 import 块**

`line_canvas.py` 顶部 `from .heatmap_canvas import (...)`：删 `_PlotCollapseControl`，加 `_CollapsedRail`、`_SPLIT_COLLAPSE_AT`、`_position_collapse_layout`。结果：

```python
from .heatmap_canvas import (
    _apply_neutral_axis_frame,
    _apply_plot_collapse,
    _available_split_height,
    _clamp_bottom_split,
    _CollapsedRail,
    _position_collapse_layout,
    _position_split_controls,
    _SPLIT_COLLAPSE_AT,
    _SPLIT_ROW_SPACING,
    _SplitDivider,
    _tick_counts_to_density,
    _visual_padded_bounds,
)
```
（`_position_split_controls` 暂留——Task 4 才删它和别处引用。）

- [ ] **Step 4: 改 `__init__` 折叠控件块**

把现有块（`# Collapse triangle + draggable divider ...` 到 `self._plot_amp.vb.sigResized.connect(self._position_split_divider)`）替换为：

```python
        # Draggable split divider (resize) + drawer-style collapsed rail.
        # Drag the divider near the bottom to collapse the time preview; click
        # the rail's ▴ to bring it back. (Replaces the old gutter triangle.)
        self._bottom_collapsed = False
        self._split_divider = _SplitDivider(self)
        self._split_divider.drag_started.connect(self._on_split_drag_started)
        self._split_divider.drag_delta.connect(self._on_split_drag_delta)
        self._split_divider.drag_finished.connect(self._on_split_drag_finished)
        self._split_divider.reset_requested.connect(self._on_split_reset)
        self._collapsed_rail = _CollapsedRail(self)
        self._collapsed_rail.setVisible(False)
        self.layout().addWidget(self._collapsed_rail)
        self._collapsed_rail.expand_requested.connect(
            lambda: self._set_bottom_collapsed(False))
        self._plot_amp.vb.sigResized.connect(self._position_collapse_ctrl)
```

- [ ] **Step 5: 改/加方法**

替换 `_on_collapse_changed` 与 `_position_collapse_ctrl`，新增 `_set_bottom_collapsed`，改 `_on_split_drag_delta`、`_on_split_reset`：

```python
    def _set_bottom_collapsed(self, collapsed: bool) -> None:
        self._bottom_collapsed = bool(collapsed)
        state = 'bottom' if self._bottom_collapsed else 'none'
        _apply_plot_collapse(self._plot_amp, self._plot_time, state,
                             self._bottom_split_h)
        self._position_collapse_ctrl()
        self.layout_geometry_changed.emit()

    def _on_collapse_changed(self, state) -> None:
        # Compat entry (programmatic / tests): 'bottom' collapses, else expands.
        self._set_bottom_collapsed(state == 'bottom')

    def _position_collapse_ctrl(self, *_args) -> None:
        _position_collapse_layout(
            getattr(self, '_collapsed_rail', None),
            getattr(self, '_split_divider', None),
            self._plot_amp, self._plot_time,
            getattr(self, '_bottom_collapsed', False))
```

`_on_split_drag_delta` 改为：

```python
    def _on_split_drag_delta(self, delta) -> None:
        raw = self._drag_start_bottom_h + delta
        if raw <= _SPLIT_COLLAPSE_AT:
            self._set_bottom_collapsed(True)
            return
        self._bottom_split_h = _clamp_bottom_split(
            raw, self._available_split_height())
        self._plot_time.setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._position_split_divider()
        self.layout_geometry_changed.emit()
```

`_on_split_reset` 把 `_collapse_ctrl.state()` 改为 `_bottom_collapsed`：

```python
    def _on_split_reset(self) -> None:
        self._bottom_split_h = float(self._bottom_split_default)
        if not self._bottom_collapsed:
            self._plot_time.setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._position_split_divider()
        self.layout_geometry_changed.emit()
```

（`_position_split_divider` 保留，仍调 `_position_collapse_ctrl`，无需改。）

- [ ] **Step 6: 迁移既有 line 测试的「`_collapse_ctrl`/三角」专项断言**

只改下列引用了被删内部的用例（行为类用例靠 `_on_collapse_changed` 兼容入口自动通过）：
- `test_collapse_divider_toggles_plot_visibility`：删除 `assert canvas._collapse_ctrl is not None`（其余 `_on_collapse_changed(...)` + 可见性断言保留；把 `'top'` 分支断言改为：`_on_collapse_changed('top')` 视作展开 → `_plot_time` 可见、`_plot_amp` 可见）。
- `test_collapse_control_is_single_triangle_toggling_bottom`：删除（三角控件已不存在；`_CollapsedRail` 由 Task 1 的新用例覆盖）。
- `test_fft_collapse_control_sits_in_left_gutter`：替换为 rail 在底部的断言：

```python
def test_fft_collapsed_rail_shows_at_bottom_when_folded(canvas, qapp):
    canvas.resize(900, 460); canvas.show(); qapp.processEvents()
    canvas._on_collapse_changed('bottom')
    qapp.processEvents()
    assert canvas._collapsed_rail.isVisible()
    # rail 在画布底部、且不与上图数据区重叠
    assert canvas._collapsed_rail.y() >= canvas._plot_amp.vb.sceneBoundingRect().bottom() - 2
```

- `test_fft_collapse_restores_last_dragged_height`：若含 `_collapse_ctrl` 引用则改为 `_bottom_collapsed`；用 `_on_collapse_changed('bottom'/'none')` 驱动，断言恢复高度不变。
- `test_fft_split_divider_hidden_when_collapsed`：保留（`_on_collapse_changed('bottom')` → divider 隐藏，经兼容入口仍成立）。

- [ ] **Step 7: 跑全文件**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q`
Expected: 全绿（含新增 + 迁移）。

- [ ] **Step 8: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "feat(fft): drawer-style vertical collapse (drag-to-collapse + bottom rail) for line canvas"
```

---

## Task 3: PgHeatmapCanvas 接线改 rail（保留 slice 联动）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`（`PgHeatmapCanvas.__init__` slice 分支；`_on_collapse_changed`/`_position_collapse_ctrl`/`_on_split_drag_delta`/`_on_split_reset`；新增 `_set_bottom_collapsed`）
- Test: `tests/ui/test_pg_heatmap_canvas.py`

- [ ] **Step 1: 写失败测试**

加到 `tests/ui/test_pg_heatmap_canvas.py`（参照该文件已有的 with_slice 画布构造方式）：

```python
def test_heatmap_drag_near_bottom_collapses_and_rail_expands(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(900, 520); c.show(); qapp.processEvents()
    c._on_split_drag_started()
    c._on_split_drag_delta(-100000)
    assert c._bottom_collapsed is True
    assert not c._slice_plot.isVisible()
    assert c._collapsed_rail.isVisible()
    assert not c._split_divider.isVisible()
    if c._slice_panel is not None:
        assert not c._slice_panel.isVisible()
    c._collapsed_rail.expand_requested.emit()
    assert c._bottom_collapsed is False
    assert c._slice_plot.isVisible()
    assert not c._collapsed_rail.isVisible()


def test_heatmap_no_slice_has_no_rail(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    c = PgHeatmapCanvas(with_slice=False)
    assert c._collapsed_rail is None
    assert c._split_divider is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -k "drag_near_bottom_collapses or no_slice_has_no_rail" -q`
Expected: FAIL — `AttributeError: '_collapsed_rail'`。

- [ ] **Step 3: 改 `__init__` slice 分支**

在 `PgHeatmapCanvas.__init__` 里：slice 分支（现 `self._collapse_ctrl = _PlotCollapseControl(self)` ... `self._plot.vb.sigResized.connect(self._position_split_divider)`）替换为：

```python
            self._bottom_collapsed = False
            self._split_divider = _SplitDivider(self)
            self._split_divider.drag_started.connect(self._on_split_drag_started)
            self._split_divider.drag_delta.connect(self._on_split_drag_delta)
            self._split_divider.drag_finished.connect(self._on_split_drag_finished)
            self._split_divider.reset_requested.connect(self._on_split_reset)
            self._collapsed_rail = _CollapsedRail(self)
            self._collapsed_rail.setVisible(False)
            self.layout().addWidget(self._collapsed_rail)
            self._collapsed_rail.expand_requested.connect(
                lambda: self._set_bottom_collapsed(False))
            self._plot.vb.sigResized.connect(self._position_collapse_ctrl)
```

no-slice 分支（现 `self._collapse_ctrl = None` / `self._split_divider = None`）替换为：

```python
            self._collapsed_rail = None
            self._split_divider = None
            self._bottom_collapsed = False
            self._bottom_split_default = 140.0
            self._bottom_split_h = self._bottom_split_default
            self._drag_start_bottom_h = self._bottom_split_h
```

并把构造里 import 的 `_PlotCollapseControl`（同文件内类，无需 import）不再使用。

- [ ] **Step 4: 改/加方法（保留 slice_panel 联动）**

```python
    def _set_bottom_collapsed(self, collapsed: bool) -> None:
        if self._slice_plot is None:
            return
        self._bottom_collapsed = bool(collapsed)
        state = 'bottom' if self._bottom_collapsed else 'none'
        _apply_plot_collapse(self._plot, self._slice_plot, state,
                             self._bottom_split_h)
        if self._slice_panel is not None:
            self._slice_panel.setVisible(not self._bottom_collapsed)
        self._position_collapse_ctrl()
        if not self._bottom_collapsed:
            self._align_slice_to_main()
            self._position_slice_panel()
        self.layout_geometry_changed.emit()

    def _on_collapse_changed(self, state) -> None:
        self._set_bottom_collapsed(state == 'bottom')

    def _position_collapse_ctrl(self, *_args) -> None:
        _position_collapse_layout(
            getattr(self, '_collapsed_rail', None),
            getattr(self, '_split_divider', None),
            self._plot, self._slice_plot,
            getattr(self, '_bottom_collapsed', False))
```

`_on_split_drag_delta` 改为：

```python
    def _on_split_drag_delta(self, delta) -> None:
        if self._slice_plot is None:
            return
        raw = self._drag_start_bottom_h + delta
        if raw <= _SPLIT_COLLAPSE_AT:
            self._set_bottom_collapsed(True)
            return
        self._bottom_split_h = _clamp_bottom_split(
            raw, self._available_split_height())
        self._slice_plot.setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._position_split_divider()
        self._position_slice_panel()
        self.layout_geometry_changed.emit()
```

`_on_split_reset` 把 `_collapse_ctrl ... state()` 改为 `_bottom_collapsed`：

```python
    def _on_split_reset(self) -> None:
        self._bottom_split_h = float(self._bottom_split_default)
        if not self._bottom_collapsed and self._slice_plot is not None:
            self._slice_plot.setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._position_split_divider()
        self._align_slice_to_main()
        self._position_slice_panel()
        self.layout_geometry_changed.emit()
```

- [ ] **Step 5: 迁移既有 heatmap 测试的专项断言**

- `test_heatmap_collapse_divider_folds_slice`：删 `assert c._collapse_ctrl is not None`；`assert c2._collapse_ctrl is None` 改 `assert c2._collapsed_rail is None`；其余 `_on_collapse_changed('bottom'/'none')` + 可见性断言保留。
- `test_heatmap_collapse_restores_last_dragged_height`：若引用 `_collapse_ctrl` 改 `_bottom_collapsed`；行为靠兼容入口保留。
- `test_heatmap_split_divider_spans_full_canvas_width` / `test_heatmap_split_reset_returns_to_default`：保留（divider/reset 行为不变）。

- [ ] **Step 6: 跑全文件**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py -q`
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "feat(heatmap): drawer-style vertical collapse (drag-to-collapse + bottom rail) for heatmap slice"
```

---

## Task 4: 清理 `_PlotCollapseControl` + 旧 helper + QSS

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`（删 `_PlotCollapseControl` 类、删旧 `_position_split_controls`）
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（去 import 里的 `_position_split_controls`）
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Test: 既有套件

- [ ] **Step 1: 确认 `_PlotCollapseControl` / `_position_split_controls` 已无引用**

Run: `grep -rn "_PlotCollapseControl\|_position_split_controls" mf4_analyzer/ tests/`
Expected: 仅剩定义处（heatmap_canvas.py）+ line_canvas.py import 行；无其它调用。若仍有调用，先迁移再继续。

- [ ] **Step 2: 删类与旧 helper**

在 `heatmap_canvas.py` 删除 `class _PlotCollapseControl(...)` 整段，删除 `def _position_split_controls(...)` 整段。`line_canvas.py` 的 import 去掉 `_position_split_controls`。

- [ ] **Step 3: QSS 替换**

`mf4_analyzer/ui_kit/style.qss`：把 `#plotCollapseBar` 选择器段替换为 rail（保留 `#plotSplitDivider`）：

```css
/* 2026-06-14 折叠下图后的底部细带（drawer 风格，复刻 #sidePanelStrip 淡色）。
 * #plotSplitDivider 仍画自身 1px 拖拽线。 */
QWidget#plotSplitDivider {
    background: transparent;
    border: none;
}
QFrame#plotCollapsedRail {
    background-color: #f3f5f8;
    border: none;
    border-top: 1px solid #e2e6eb;
}
QFrame#plotCollapsedRail:hover {
    background-color: #e7ecf2;
}
```

- [ ] **Step 4: 跑全相关套件**

Run: `.venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py tests/ui/test_analysis_section_page.py tests/ui/test_main_window_smoke.py -q`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui_kit/style.qss
git commit -m "chore(analysis): remove obsolete _PlotCollapseControl/_position_split_controls + rail QSS"
```

---

## Task 5: 三 section 视觉验证

**Files:** 无代码改动（验证）

- [ ] **Step 1: 渲染三个 section 的展开/折叠态**

写临时脚本（`PYTHONPATH=$PWD .venv/bin/python`）：分别构造 `PgLineCanvas`、`PgHeatmapCanvas(with_slice=True)`（FFT-time / Order 同类），`resize(1200,520); show()`，喂一份数据；
- 展开态：抓 `_glw.grab()` 截图，确认中间有可拖拽分隔线、上下图都在。
- 调 `_on_collapse_changed('bottom')`：抓整 canvas（`canvas.grab()`）截图，确认底部一条细带 + 居中小灰 ▴，上图底轴刻度完整未被遮，slice/colorbar（heatmap）无残留。
存到 `docs/reports/2026-06-14-vertical-drawer-*.png`，逐张目视。

- [ ] **Step 2: 拖拽折叠手感确认**

真机/离屏：`_on_split_drag_started()` + 逐步 `_on_split_drag_delta(-N)` 增大，确认到近底部（raw≤`_SPLIT_COLLAPSE_AT`）才折叠、死区内只 clamp；rail 点击展开回到记忆高度。必要时微调 `_SPLIT_COLLAPSE_AT`（提交说明里记录最终值）。

- [ ] **Step 3: 全量回归**

Run: `.venv/bin/python -m pytest tests/ui/ -q`
Expected: 全绿（除已知与本功能无关的既有失败——本批不应新增失败）。

- [ ] **Step 4: 提交验证产物**

```bash
git add docs/reports/2026-06-14-vertical-drawer-*.png
git commit -m "docs(analysis): visual verification for vertical drawer-style collapse"
```

---

## Self-Review

**1. Spec 覆盖**：G1(删三角+拖拽折叠)→Task2/3 的 `_on_split_drag_delta`+Task4 删类；G2(底部 rail)→Task1 `_CollapsedRail`+Task2/3 接线；G3(保留分隔条)→`_SplitDivider` 全程保留；G4(三 section 统一)→Task2(line)+Task3(heatmap，FFT-time/Order 同 `PgHeatmapCanvas`)；G5(不遮底轴)→Task1 rail 入 QVBoxLayout 隐藏占 0 高 + Task5 视觉确认。无缺口。

**2. Placeholder 扫描**：无 TBD/TODO；`_SPLIT_COLLAPSE_AT=40` 为具体默认（Task5 可微调并记录）；所有改动步骤含完整真实代码。Task5 临时脚本为验证步骤、非占位。

**3. 命名/签名一致**：`_CollapsedRail`/`expand_requested`/`HEIGHT_PX`、`_position_collapse_layout(rail,divider,top,bottom,collapsed)`、`_set_bottom_collapsed(bool)`、`_bottom_collapsed`、`_collapsed_rail`、`_SPLIT_COLLAPSE_AT` 在 Task1→4 一致；兼容入口 `_on_collapse_changed(state)`/`_position_collapse_ctrl`/`_position_split_divider` 名称保留、签名不变。

**4. 绿色递进**：Task1 纯新增；Task2 line 改完+测试迁移（heatmap 仍用旧类，存在）；Task3 heatmap 改完+测试迁移；Task4 删已无引用的旧类/helper+QSS；Task5 验证。每步可独立通过。
