# 图表右键菜单两列一级编辑优化 — Design Spec

- 日期：2026-06-20
- 状态：待实现
- 范围：pyqtgraph 图表右键菜单（TimeDomain / FFT line / FFT-vs-Time / Order heatmap）和对应 HTML 原型

## 1. Decision

把图表右键菜单从「若干顶层菜单项 + X/Y 原生子菜单 + 网格子菜单」收敛成一个 **两列 inline panel**：

- 左列：所有可点击、可输入的控件，靠近鼠标出现位置。
- 右列：极短说明标签，只解释这一行是什么，不承载主要交互。

目标不是做更多功能，而是降低右键后的鼠标移动距离，减少层级跳转，让范围、查看、网格、鼠标模式都在第一眼能完成。

推荐信息结构：

```text
[框选] [平移]        鼠标
[Y适应] [全图]      查看
[0.0] — [1.0]       X范围
[-1.0] — [1.0]      Y范围
[X] [Y]             网格
```

## 2. Product Rules

### 2.1 两列语义

- 左列是操作区，所有按钮、输入框、chip 都放这里。
- 右列是说明区，使用弱化标签：`鼠标`、`查看`、`X范围`、`Y范围`、`网格`。
- 右列标签不可点击，不要做 hover 背景，不要抢视觉权重。
- 不加竖分割线；靠列间距和文字弱化表达结构，避免菜单变成表格。

### 2.2 文案

- `查看全部` 缩短为 `全图`。
- `Y 轴自适应` 缩短为 `Y适应`。
- `X 轴范围` / `Y 轴范围` 右列缩短为 `X范围` / `Y范围`。
- `显示 X 网格` / `显示 Y 网格` 收敛为 chip：`X` / `Y`。
- `框选` / `平移` 继续使用图标按钮，tooltip 仍保留完整语义。

### 2.3 范围显示规则

不要把 Y 范围固定显示成 `自动`。

X/Y 范围行都显示当前真实 ViewBox 可见范围：

- X 行读取当前 `viewRange()[0]`。
- Y 行读取当前 `viewRange()[1]`。
- 输入任意合法 min/max 后，关闭对应轴 autorange，并用 `setXRange(..., padding=0)` 或 `setYRange(..., padding=0)` 应用。
- 无效范围（非数字、`hi <= lo`）不应用，输入框恢复打开菜单时的当前范围。
- `Y适应` 是独立查看动作：保持当前 X 窗口，把 Y 调整到可见数据；它不是 `Y范围` 行的固定状态。
- `全图` 走现有 `view_all_handler` / `reset_view_to_data_extents`，语义保持和 toolbar Home 一致。

这条规则解决「为什么 Y 范围是自动」的误解：inline 范围编辑行只表达当前可见数值范围，自动/适应动作放在查看 row。

### 2.4 网格规则

- 网格 X/Y 在一级显示为两个 checkable chip。
- 选中态复用现有浅蓝底 + 蓝色边框。
- `allow_y_grid=False` 时，Y chip 显示 disabled 且不改变任何 Y 网格。
- 应用网格仍走 `show_major_grid_left_bottom_only(..., alpha=0.28)`，保持 top/right grid 不被点亮。

### 2.5 鼠标模式规则

- 鼠标 row 继续由 toolbar controller 驱动。
- `current_mouse_mode()==''` 时，`框选` / `平移` 都不选中。
- 点击按钮优先调用 `set_mouse_mode_broadcast(mode)`，没有该方法时回退 `set_zoom_mode()` / `set_pan_mode()`。
- 分屏 peer 广播、防递归、shared toolbar 高亮刷新语义不变。

## 3. Visual Spec

### 3.1 Layout Tokens

- 菜单宽度：`280-304px`，首版建议 `292px`。
- 外层 padding：`10px`。
- 行高：`32px`；行间距：`6px`。
- 左操作列宽：`196-210px`；右说明列宽：`42-52px`；列间距：`10-12px`。
- 左操作列内部固定三轨对齐：左控件 `88px`，中间分隔/占位 `28px`，右控件 `88px`；不要用内容自适应的 flex 排布。
- 右侧说明字号：`11-12px`，字重 `600`，颜色 `#94a3b8` 或等价弱灰蓝。
- 控件圆角：按钮/chip `7-8px`，输入框 `7px`。
- 输入框高度：`30px`。

### 3.2 Control Geometry

- 鼠标按钮：`32x30` 或 `32x32`，图标居中。
- 查看按钮：两个等宽文本按钮，建议 `88x30`。
- 范围输入：与查看按钮同宽，建议 `88px` + dash `28px` + `88px`；输入文本水平居中。
- 网格 chip：`56x30`，在左/右控件轨道内居中。

### 3.3 Interaction Feel

- 右键点附近首先落在左列操作区。
- 右说明列只做扫描辅助，视觉上应该比输入框和按钮轻。
- 菜单高度不应明显超过当前版本；如果高度增长，优先压缩垂直间距，不恢复子菜单。

## 4. Architecture

在 `mf4_analyzer/ui/pg_canvas/context_menu.py` 内新增一个可复用 inline panel，而不是继续拼多个 QAction/submenu：

- `_PgContextInlinePanel(QWidget)`：负责两列布局、按钮、输入、chip。
- `_make_inline_context_panel_action(...) -> QWidgetAction`：创建 panel 并插入 menu。
- `_format_range_value(value: float) -> str`：把 ViewBox 范围变成短输入文本。
- `_restore_line_edits_on_invalid(...)`：无效输入恢复当前范围。

`redesign_pg_context_menu(...)` 改为：

1. 保留 `_localize_pg_context_menu(menu)` 和 `_style_pg_context_menu(menu)`。
2. 清理 pyqtgraph 原生高级项和旧顶层项。
3. 插入一个 `QWidgetAction`，其 widget objectName 为 `pgContextInlinePanel`。
4. 不再插入 `pgMouseModeToggleRow`、`Y 轴自适应` 顶层 action、`网格` submenu、`X/Y 轴范围` 原生子菜单。
5. `keep_plot_options=True` 时，`绘图选项` 可继续保留在 inline panel 下方；默认仍移除。

## 5. Non-Goals

- 不做色图、色阶、tick density、导出入口。
- 不把右键菜单变成完整 Inspector。
- 不改变 `Y适应`、`全图`、网格、pan/zoom 的底层行为。
- 不引入新的状态存储；范围输入直接读/写当前 ViewBox。
- 不改变 chart toolbar 或 inspector 的布局。

## 6. Acceptance Criteria

- [ ] 右键菜单顶部只有一个 `pgContextInlinePanel` inline widget（除 `keep_plot_options=True` 的保留项外）。
- [ ] panel 行顺序为：鼠标、查看、X范围、Y范围、网格。
- [ ] X/Y 范围行都显示当前真实数值范围，不固定显示 `自动`。
- [ ] 输入合法 X/Y 范围后，对应 ViewBox 范围改变且 `padding=0`。
- [ ] 输入非法范围后，不改变 ViewBox，并恢复原显示。
- [ ] `Y适应` 仍保持当前 X 窗口并拟合 Y。
- [ ] `全图` 仍走现有 Home / View All reset。
- [ ] 网格 X/Y chip 在一级切换，`allow_y_grid=False` 时 Y chip disabled。
- [ ] idle 鼠标模式下 `框选` / `平移` 都不高亮。
- [ ] 分屏下右键切鼠标模式仍广播到 peer。
- [ ] top/right grid 不被任何 inline 网格操作点亮。
- [ ] 菜单圆角透明背景、NoDropShadowWindowHint、tooltip 关闭规则不回退。

## 7. Test Requirements

- `tests/ui/test_pg_timedomain_canvas.py`
  - inline panel 存在，旧顶层项/网格 submenu 不存在。
  - 行标签和控件文案正确。
  - X/Y 范围读取当前 ViewBox 范围。
  - 合法/非法 range 输入行为。
  - overlay `allow_y_grid=False` 行为。
  - `Y适应`、`全图` 继续触发原 handler。
  - translucent / no native shadow / tooltip contract 保持。
- `tests/ui/test_pg_line_canvas.py`
  - FFT line 菜单使用同一 inline panel。
  - 鼠标模式按钮仍调用 broadcast。
- `tests/ui/test_pg_heatmap_canvas.py`
  - heatmap 菜单使用同一 inline panel。
  - View All / range / grid 在 heatmap 上不回归。
- 原型文件 `docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html`
  - 更新为两列左操作右说明布局。
