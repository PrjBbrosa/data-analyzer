# 分析 Section 上下折叠改用 drawer 风格细带 — Spec

日期：2026-06-14
状态：已评审（设计经用户三处确认：简化两态 / 保留拖拽分隔条 / 三 section 全做；折叠触发=拖到近底部，无独立按钮）
配套 plan：`docs/superpowers/plans/2026-06-14-analysis-section-vertical-drawer-collapse.md`

## 1. 背景与已确认事实

三个分析 section 的 pg 画布都是「上图 + 下图」上下分栏，共用 `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` 里的折叠/分隔控件：

- **FFT line**（`PgLineCanvas`）：上 `_plot_amp`（谱图）/ 下 `_plot_time`（时域预览），默认下图高 170。
- **FFT-time heatmap / Order heatmap**（`PgHeatmapCanvas`，`with_slice=True`）：上 `_plot`（主热力图）/ 下 `_slice_plot`（切片），默认下图高 140。

现有控件（**本次要替换**）：
- `_PlotCollapseControl`（heatmap_canvas.py:85）：左 gutter 一个 ▾/▴ 三角，点击切换"折叠/恢复下图"。`collapse_changed('none'|'bottom')` → 两 canvas 的 `_on_collapse_changed`。**用户要求删除。**
- `_SplitDivider`（heatmap_canvas.py:174）：上下图间一条可拖拽 1px 线，拖动调比例、双击复位。`drag_started/drag_delta(px)/drag_finished/reset_requested` → `_on_split_drag_*` / `_on_split_reset`。**用户要求保留。**
- `_apply_plot_collapse(top, bottom, state, bottom_default_max)`（:248）：真正执行折叠（切换行 maxHeight/visible，`'none'|'bottom'|'top'`）。**保留。**
- `_position_split_controls(ctrl, divider, top, bottom)`（:304）：定位三角(左 gutter)+分隔线(gap)。**改造。**
- `_clamp_bottom_split(value, total)`（:286，区间 `[_SPLIT_MIN_BOTTOM=70, total-_SPLIT_MIN_TOP=90]`）、`_available_split_height`、`_bottom_split_h`（记忆高度）、`_drag_start_bottom_h`。**保留。**

要效仿的模式（`mf4_analyzer/ui/side_panels.py`）：`SidePanelStrip` = 12px 淡色边 rail + 灰 chevron，折叠态显示、点击切换；侧栏折叠触发是「拖 splitter 到 ≤ `COLLAPSE_THRESHOLD`」（`DRAG_COLLAPSED`）。本设计把这套「拖到边折叠 + 细带 rail 重开」的逻辑搬到上下方向，但**简化为两态**（无 PEEK 浮层）。

## 2. 目标 / 非目标

**目标**
- G1：删除 gutter 三角按钮 `_PlotCollapseControl`，折叠入口改为「把分隔条拖到近底部」自动折叠（drawer 的 `DRAG_COLLAPSED` 逻辑）。
- G2：折叠态在画布**底部**显示一条 drawer 风格细带 `_CollapsedRail`（≈14px、淡背景、居中小灰 ▴），点击恢复下图到记忆高度。
- G3：展开态保留 `_SplitDivider` 拖拽调比例 + 双击复位，行为不变。
- G4：三 section（FFT line + FFT-time + Order heatmap）统一行为，共用实现。
- G5：rail 绝不遮挡上图底轴刻度/标签。

**非目标**
- 不做 PEEK 浮层 / hover 预览 / 自动收起定时器（用户选了简化两态）。
- 不折叠上图（上图永远是主图）。
- 不动 FFT 数值、不动 side_panels.py（左右侧栏）。
- 不引入 OpenGL、不改导出链。

## 3. 设计

### 3.1 状态模型（两态）
每个带下图的画布有 `_bottom_collapsed: bool`（替代 `_collapse_ctrl.state()`）：
- **展开**（`False`）：上下图都显示；`_SplitDivider` 在 gap 上可拖/双击复位；rail 隐藏。
- **折叠**（`True`）：`_apply_plot_collapse(top, bottom, 'bottom', ...)` 折叠下图；`_SplitDivider` 隐藏；rail 在画布底部显示。
切换仍走现有 `_apply_plot_collapse` + `_bottom_split_h` 记忆，仅 trigger/UI 变化。

### 3.2 折叠触发（拖到近底部，无按钮）
新增常量 `_SPLIT_COLLAPSE_AT = 40`（下图原始目标高度像素阈值，实现期可视觉微调）。改 `_on_split_drag_delta(delta)`：
```
raw = _drag_start_bottom_h + delta          # 未 clamp 的目标下图高
if raw <= _SPLIT_COLLAPSE_AT:               # 拖到近底部 → 折叠（drawer DRAG_COLLAPSED）
    collapse_bottom()                       # 见 3.5；下图原 _bottom_split_h 作为记忆保留
else:
    _bottom_split_h = _clamp_bottom_split(raw, _available_split_height())
    bottom.setMaximumHeight(int(_bottom_split_h)); reposition
```
注意：`raw <= 阈值` 才折叠，落在 `[阈值, _SPLIT_MIN_BOTTOM]` 之间时按 clamp 停在 min（与现状一致），只有继续往下拖越过阈值才折叠——给一个"死区"避免误折叠。`_drag_start_bottom_h` 在折叠前已记住展开高度，重开时用它。

### 3.3 `_CollapsedRail`（横向版 `SidePanelStrip`）
新 `QFrame` 放在 heatmap_canvas.py（与其它分隔控件同处，供两 canvas 复用）：
- `expand_requested = pyqtSignal()`；`HEIGHT_PX = 14`。
- `objectName = "plotCollapsedRail"`；`setCursor(PointingHandCursor)`；`setToolTip("展开下图")`。
- `paintEvent`：居中画一个小灰 ▴（填充三角，色 `#7b8699`，hover 时 `#2563eb`，复刻 `_PlotCollapseControl` 的画法但固定向上 + 灰）。
- `mousePressEvent` 左键 → `expand_requested.emit()`；`enter/leaveEvent` 切 hover 重绘。

### 3.4 布局：rail 是 canvas QVBoxLayout 底部成员，仅折叠可见
不走绝对覆盖（会遮上图底轴）。两 canvas 的顶层 `QVBoxLayout`（现含 `_glw`）在 `_glw` **之后** `addWidget(self._collapsed_rail)`，构造时 `setVisible(False)`（隐藏 → 占 0 高度）。
- 折叠：`rail.setVisible(True)` → 占 14px，`_glw` 自然上移 14px，下图行折叠后上图填满 `_glw`，rail 在其下方独立成带——**绝不重叠**（满足 G5）。
- 展开：`rail.setVisible(False)` → 占 0，`_glw` 复原。
`_SplitDivider` 维持现状为 `_glw` 上的绝对覆盖子控件（仅展开态定位/显示）。

### 3.5 `_position_split_controls` 改造 + 折叠/展开方法
签名改为 `_position_split_controls(rail, divider, top_plot, bottom_plot, collapsed)`：
- `collapsed=True`：`divider.hide()`；rail 由布局管理（不需绝对定位），仅确保 `setVisible(True)` + `raise_`。
- `collapsed=False`：`rail.setVisible(False)`；分隔线定位逻辑同现状（gap 中心、data 宽度）。
两 canvas 新增/改：
- `collapse_bottom()`：`_apply_plot_collapse(top, bottom, 'bottom', _bottom_split_h)`；`_bottom_collapsed=True`；rail 可见、divider 隐藏；`layout_geometry_changed.emit()`。
- `expand_bottom()`（rail.expand_requested 槽）：`_apply_plot_collapse(top, bottom, 'none', _bottom_split_h)`；`_bottom_collapsed=False`；rail 隐藏、divider 显示；`bottom.setMaximumHeight(int(_bottom_split_h))`；`layout_geometry_changed.emit()`。
- `_on_split_reset`（双击）：保持——展开态复位 `_bottom_split_h` 到默认。

### 3.6 删除 `_PlotCollapseControl` + 接线迁移
- 删除 `_PlotCollapseControl` 类、`_apply_plot_collapse` 的 `'top'` 分支（已无用）可留可删（保留以最小改动）。
- 两 canvas：删 `_collapse_ctrl` 及其 `collapse_changed` 接线、`_on_collapse_changed`、`set_state` 调用；`_position_collapse_ctrl`/`_position_split_divider` 改为调新 `_position_split_controls(rail, divider, ...)`；`__init__` 把 `_PlotCollapseControl` 换成 `_CollapsedRail`（接 `expand_requested → expand_bottom`）并加入布局。
- line_canvas.py 从 heatmap_canvas 的 import 去掉 `_PlotCollapseControl`、加 `_CollapsedRail`。

### 3.7 QSS
`style.qss` 加（复刻 `#sidePanelStrip` 的淡色 + 顶部 1px 分隔）：
```
QFrame#plotCollapsedRail { background-color:#f3f5f8; border:none; border-top:1px solid #e2e6eb; }
QFrame#plotCollapsedRail:hover { background-color:#e7ecf2; }
```
原 `#plotCollapseBar` 选择器随类删除而清理；`#plotSplitDivider` 保留。

## 4. 受影响文件
- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`：删 `_PlotCollapseControl`；加 `_CollapsedRail`；改 `_position_split_controls`；改 `PgHeatmapCanvas` 接线（`__init__` 706-721 / `_on_collapse_changed` / `_on_split_drag_delta` / 定位方法）。
- `mf4_analyzer/ui/pg_canvas/line_canvas.py`：同步 `PgLineCanvas` 接线（import、`__init__` 157-224、`_on_*`、定位方法）。
- `mf4_analyzer/ui_kit/style.qss`：加 `#plotCollapsedRail`，清理 `#plotCollapseBar`。
- `tests/ui/test_pg_line_canvas.py` / `tests/ui/test_pg_heatmap_canvas.py`：回归测试。

## 5. 测试（验收）
- `_CollapsedRail` 左键 → `expand_requested` 发射一次。
- 拖拽折叠：调 `_on_split_drag_started()` 后 `_on_split_drag_delta(delta)`，delta 使 raw ≤ `_SPLIT_COLLAPSE_AT` → `_bottom_collapsed True`、下图 `isVisible()` False、rail `isVisible()` True、divider 隐藏。
- 重开：触发 rail `expand_requested` → `_bottom_collapsed False`、下图可见、rail 隐藏、divider 显示、下图 maxHeight == 记忆 `_bottom_split_h`。
- 死区：raw 落在 `(_SPLIT_COLLAPSE_AT, _SPLIT_MIN_BOTTOM]` → 不折叠，停在 clamp 最小值。
- 不再有 `_PlotCollapseControl`（import/属性均无）。
- 三 canvas（line + heatmap with_slice）均通过；既有套件全绿。
- 视觉验证（截图）：折叠态底部单条细带 + 灰 ▴、上图底轴刻度完整不被遮；展开态分隔条可拖。

## 6. 风险
- rail 进 QVBoxLayout 动态显隐会触发 `_glw` resize → 注意 `_position_collapse_ctrl`/overlay 重定位与 `layout_geometry_changed` 不产生抖动/递归。
- 拖拽折叠阈值 `_SPLIT_COLLAPSE_AT` 需真机手感微调（太大易误折叠，太小难触发）。
- heatmap 折叠下图时可能还有 slice 控件/colorbar 联动，沿用现有 `_apply_plot_collapse` 行为即可，勿扩范围；执行期视觉确认 colorbar 不残留。
- codex 近期重写过该区域（baseline 0f7338e）；执行前确认 `line_canvas.py`/`heatmap_canvas.py` clean，以函数名定位（行号会漂）。
