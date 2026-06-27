# 游标 Pill 几何锚定可靠性设计

## 背景

用户在单游标读数面板密度与 `+` / `-` 状态优化后，又发现一个更底层的问题：

- 切换 `单游标` / `双游标` 时，pill 会漂移。
- pill 可能跑到屏幕外，也可能从右侧边缘跳到屏幕中间附近。
- 这个现象在侧边栏附近、pill 宽度发生明显变化时更容易出现。

这不是单纯的 QSS、行距或按钮状态问题，而是 cursor pill 内容变化后的几何锚定策略不一致。

当前代码锚点：

- `mf4_analyzer/ui/chart_stack/cursor_pill.py:205` 的 `_toggle_mode()` 已经只为 `+` / `-` 内部切换保留右边缘。
- `mf4_analyzer/ui/chart_stack/cursor_pill.py:83` 的 `set_primary()`、`:87` 的 `set_detail_html()`、`:102` 的 `set_single_detail_html()`、`:235` 的 `set_dual_rows()` 都会改变内容和尺寸。
- `mf4_analyzer/ui/chart_stack/stack.py:1040` 的 `_on_cursor_info()` 处理单游标 primary/detail。
- `mf4_analyzer/ui/chart_stack/stack.py:1158` 的 `_on_dual_cursor_info()` 处理双游标 HTML detail。
- `mf4_analyzer/ui/chart_stack/stack.py:228` 和 `:646` 把 `dual_cursor_rows` 直接连接到 `CursorPill.set_dual_rows()`，绕过 `ChartStack._reposition_pill()`。
- `mf4_analyzer/ui/chart_stack/stack.py:1189` 的 `_reposition_one_pill()` 对用户拖放过的 pill 只 clamp 左上角，不保留右边缘。
- `mf4_analyzer/ui/pg_canvas/cursor.py:585-587` 的双游标 emit 顺序是 `cursor_info` → `dual_cursor_info` → `dual_cursor_rows`，最后一次 `dual_cursor_rows` 仍可能改变 pill 尺寸。

offscreen probe 已复现当前漂移链路：

```text
single mini: x=782 w=110 right=892 stackw=900
switch dual: x=573 w=327 right=900
switch single mini: x=573 w=110 right=683
```

含义：双游标变宽时，旧逻辑把左边界 clamp 到 `573`；再切回更窄的单游标时，仍保留左边界，于是右边缘退到 `683`，视觉上就像 pill 跑到屏幕中间。

## 问题定义

Cursor pill 目前有多个尺寸变化入口，但只有 `+` / `-` toggle 一个入口保留右边缘。其它入口依赖 `adjustSize()` 后的左上角位置，导致：

1. 宽内容切入时可能超出父容器右边界。
2. 宽内容被 clamp 后，再切回窄内容会保留被 clamp 后的左边界，右边缘漂到中间。
3. `dual_cursor_rows` 是最后到达的双游标信号，且当前直接写 pill，可能在最后一步重新把 pill 撑宽但不 reposition。
4. 主/副 pane 各有自己的 pill，任何修复都必须保持 source canvas 路由，不能把 secondary readout 写回 primary pill。

## 目标

1. 所有会改变 pill 尺寸的内容更新都使用同一套几何策略。
2. 用户拖放过的 pill 在内容变宽或变窄时保留原右边缘和顶部位置，并 clamp 在 `ChartStack.stack` 父容器内。
3. 未被用户拖放过的 pill 继续自动锚定到 emitting canvas/card 的右上角。
4. `cursor_info`、`dual_cursor_info`、`dual_cursor_rows` 都经过 `ChartStack` 的统一几何 wrapper。
5. 主 pane 与 secondary pane 的单/双游标 readout 继续进入各自的 `CursorPill`。
6. 现有 `+` / `-` 切换、单游标 mini value-only、双游标 mini、圆角透明像素、复制图片合成不退化。

## 非目标

- 不改变游标数值计算、插值、min/max/mean/delta 统计。
- 不改变 `PgTimeDomainCursorController._emit_dual_cursor_html()` 的 emit 顺序。
- 不改变 `CursorPill` 的拖拽手势。
- 不重新设计 pill 的视觉样式、行距、颜色或按钮图标。
- 不把 TimeDomain 以外的 FFT / FFT vs Time / Order hover 重新接回 cursor pill。
- 不把 user-placed pill 改成相对 canvas 的持久布局；本轮只修内容变化期间的瞬时漂移和越界。

## 几何契约

### 用户拖放后的 pill

当 `pill.is_user_placed()` 为真时：

- 内容更新前记录：
  - `old_right = pill.x() + pill.width()`
  - `old_top = pill.y()`
- 内容更新后重新计算尺寸。
- 将 pill 移动到：
  - `x = clamped_right - pill.width()`
  - `y = old_top`
- `clamped_right` 必须落在 `[0, parent.width()]`。
- 最终 `x` 必须落在 `[0, parent.width() - pill.width()]`。
- 最终 `y` 必须落在 `[0, parent.height() - pill.height()]`。
- 如果新 pill 宽度大于父容器宽度，允许 `x = 0`，但不允许右侧继续跑出父容器。

### 默认自动锚定的 pill

当 `pill.is_user_placed()` 为假时：

- 内容更新后仍由 `ChartStack._reposition_one_pill(pill, card)` 锚定。
- primary pill 锚定 primary time card canvas。
- secondary pill 锚定 secondary time card canvas。
- split 模式下，secondary canvas 发出的 readout 不能影响 primary pill 的位置或内容。

### 信号入口

以下入口都视为尺寸变化入口，必须经过同一几何 wrapper：

- `ChartStack._on_cursor_info()`
- `ChartStack._on_dual_cursor_info()`
- 新增的 `ChartStack._on_dual_cursor_rows()`

`CursorPill._toggle_mode()` 可以继续保留自身的右边缘保护，因为它是用户直接点击 pill 内按钮的局部交互；但 `ChartStack` 不应再依赖 “调用者记得 reposition” 这种分散契约。

## 技术设计

### CursorPill

把现有 `_move_preserving_right_edge()` 提升为可由 `ChartStack` 调用的 public helper：`move_preserving_right_edge(self, right_edge, top)`。实现沿用当前 clamp 公式，不改变 `+` / `-` toggle 的表现。

`_toggle_mode()` 改为调用 public helper。为了降低回归风险，可以短期保留 `_move_preserving_right_edge = move_preserving_right_edge` 兼容别的内部调用。

### ChartStack

新增一个只负责内容更新后几何收口的 helper：

```python
def _update_pill_content(self, pill, card, update):
    was_user_placed = pill.is_user_placed()
    old_right = pill.x() + pill.width()
    old_top = pill.y()
    update()
    if not pill.isVisible():
        return
    if was_user_placed:
        pill.move_preserving_right_edge(old_right, old_top)
        pill.raise_()
    else:
        self._reposition_one_pill(pill, card)
```

这个 helper 的职责边界：

- 不解析 cursor HTML。
- 不决定 primary/secondary routing。
- 不改变 cursor mode。
- 只在 update 完成后根据 user-placed 状态处理位置。

### dual_cursor_rows 路由

将当前 direct connect：

```python
self.canvas_time.dual_cursor_rows.connect(self._pill.set_dual_rows)
canvas.dual_cursor_rows.connect(self._pill_secondary.set_dual_rows)
```

改为：

```python
self.canvas_time.dual_cursor_rows.connect(
    lambda rows: self._on_dual_cursor_rows(rows, self.canvas_time)
)
canvas.dual_cursor_rows.connect(
    lambda rows, c=canvas: self._on_dual_cursor_rows(rows, c)
)
```

新增 `_on_dual_cursor_rows()`，通过 `_pill_for_canvas(source)` 和 `_card_for_canvas(source)` 找到正确 pill/card，并走 `_update_pill_content()`。

## 验收标准

### Primary pill

- 单游标 mini 用户放在右侧后，切到双游标 rows，pill 右边缘保持在原位置或父容器右边界内。
- 双游标宽内容用户放在右侧后，切回单游标内容，pill 不保留旧左边界漂到中间，右边缘保持稳定。
- 宽内容不会跑出 `ChartStack.stack` 右边界。

### Secondary pill

- split 模式下 secondary pill 用户放在右侧后，secondary canvas 的 `dual_cursor_rows` 更新仍保留 secondary pill 右边缘。
- secondary 更新不改变 primary pill 的内容和位置。

### 默认锚定

- 未被用户拖放的 primary pill，在单/双游标切换后仍贴近 primary canvas 右上角。
- 未被用户拖放的 secondary pill，在 split 模式下仍贴近 secondary canvas 右上角。

### 回归

- `tests/ui/test_chart_stack.py::test_cursor_pill_toggle_collapse_preserves_right_edge` 继续通过。
- `tests/ui/test_chart_stack.py::test_cursor_pill_toggle_expand_stays_inside_parent_right_edge` 继续通过。
- `tests/ui/test_chart_stack.py::test_cursor_pill_renders_transparent_rounded_corners` 继续通过。
- `tests/ui/test_split_per_pane_controls.py` 的 per-pane cursor pill 测试继续通过。
- `tests/ui/test_split_routing.py` 继续通过，避免 view/split cursor state 回归。

## 人工验证

在真实 TraceLab 窗口中：

1. 打开 5 条以上通道的 TimeDomain 图。
2. 开启单游标，点击 `+` / `-` 至 mini 和 full 都确认一次。
3. 把 pill 拖到靠近右侧 Inspector 的位置。
4. 在 `单游标` / `双游标` 间切换多次。
5. 展开和收起右侧面板或改变窗口宽度，再切换 `单游标` / `双游标`。
6. 确认 pill 不跑出图表区域、不跳到屏幕中间、不覆盖到 Inspector 外侧。
7. 进入 split 模式，对主/副 pane 分别重复上述操作，确认两侧 pill 互不串扰。
